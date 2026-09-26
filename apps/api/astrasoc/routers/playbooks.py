"""Automation Playbooks API: playbooks, versions, and durable workflow runs."""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import Playbook, PlaybookVersion, WorkflowRun
from ..schemas.common import serialize, serialize_many
from ..services import audit, workflow
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/playbooks", tags=["playbooks"])

_KEY = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


@router.get("")
def list_playbooks(principal: Principal = Depends(require_permission("playbook:read")),
                   db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Playbook).where(
        Playbook.tenant_id == principal.tenant_id)).scalars().all()
    return {"items": serialize_many(rows)}


@router.get("/runs")
def list_runs(principal: Principal = Depends(require_permission("playbook:read")),
              db: Session = Depends(get_db),
              page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
              status: str | None = None, incident_id: uuid.UUID | None = None) -> dict:
    scope = current_scope(db, principal.tenant_id)
    filters = []
    if status:
        filters.append(WorkflowRun.status == status)
    if incident_id:
        filters.append(WorkflowRun.incident_id == incident_id)
    return paginate(db, WorkflowRun, tenant_id=principal.tenant_id, scope=scope, filters=filters,
                    sort="created_at", page=page, page_size=page_size)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID,
            principal: Principal = Depends(require_permission("playbook:read")),
            db: Session = Depends(get_db)) -> dict:
    run = db.get(WorkflowRun, run_id)
    if not run or run.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Workflow run not found")
    return serialize(run)


@router.get("/{playbook_key}")
def get_playbook(playbook_key: str,
                 principal: Principal = Depends(require_permission("playbook:read")),
                 db: Session = Depends(get_db)) -> dict:
    pb = db.execute(select(Playbook).where(
        Playbook.tenant_id == principal.tenant_id, Playbook.key == playbook_key)).scalar_one_or_none()
    if not pb:
        raise HTTPException(404, detail="Playbook not found")
    versions = db.execute(select(PlaybookVersion).where(
        PlaybookVersion.playbook_id == pb.id)).scalars().all()
    active = next((v for v in versions if v.is_active), None)
    data = serialize(pb)
    data["graph"] = active.graph if active else {}
    data["versions"] = serialize_many(versions)
    return data


@router.put("/{playbook_key}")
def upsert_playbook(playbook_key: str, payload: dict = Body(...),
                    principal: Principal = Depends(require_permission("playbook:write")),
                    db: Session = Depends(get_db)) -> dict:
    """Create or update a playbook. Saving a graph bumps the version and keeps
    prior versions; runs in flight keep executing the version they started on."""
    if not _KEY.match(playbook_key):
        raise HTTPException(422, detail="Playbook key must be 3-80 chars: lowercase, digits, '_'.")
    if "graph" in payload:
        try:
            workflow.validate_graph(payload["graph"])
        except workflow.WorkflowError as exc:
            raise HTTPException(422, detail={"error": exc.code, "message": exc.message})
    pb = db.execute(select(Playbook).where(
        Playbook.tenant_id == principal.tenant_id, Playbook.key == playbook_key)).scalar_one_or_none()
    if pb is None:
        if "graph" not in payload:
            raise HTTPException(422, detail="A new playbook needs a graph.")
        pb = Playbook(tenant_id=principal.tenant_id, key=playbook_key,
                      name=str(payload.get("name", playbook_key))[:200],
                      description=str(payload.get("description", "")),
                      trigger=payload.get("trigger", {}), tags=payload.get("tags", []),
                      current_version="0.0.0")
        db.add(pb)
        db.flush()
    else:
        for f in ("name", "description", "enabled", "trigger", "tags"):
            if f in payload:
                setattr(pb, f, payload[f])
    if "graph" in payload:
        for v in db.execute(select(PlaybookVersion).where(
                PlaybookVersion.playbook_id == pb.id)).scalars():
            v.is_active = False
        parts = (pb.current_version or "0.0.0").split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        pb.current_version = ".".join(parts)
        db.add(PlaybookVersion(playbook_id=pb.id, version=pb.current_version,
                               graph=payload["graph"], is_active=True,
                               changelog=str(payload.get("changelog", "Updated via builder."))))
    audit.record(db, action="playbook.saved", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="playbook", resource_id=playbook_key,
                 detail={"version": pb.current_version})
    db.commit()
    return get_playbook(playbook_key, principal, db)


def _workflow_http(exc: workflow.WorkflowError) -> HTTPException:
    code = {"not_found": 404, "forbidden": 403, "wrong_approver_role": 403,
            "not_waiting": 409, "disabled": 409}.get(exc.code, 422)
    return HTTPException(code, detail={"error": exc.code, "message": exc.message})


@router.post("/{playbook_key}/run")
def run_playbook(playbook_key: str, payload: dict = Body(default={}),
                 principal: Principal = Depends(require_permission("playbook:run")),
                 db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db, principal.tenant_id)
    try:
        incident_id = uuid.UUID(payload["incident_id"]) if payload.get("incident_id") else None
    except ValueError:
        raise HTTPException(422, detail="incident_id must be a UUID")
    try:
        run = workflow.start_workflow(db, principal, playbook_key, incident_id, scope,
                                      idempotency_key=payload.get("idempotency_key"))
    except workflow.WorkflowError as exc:
        db.rollback()
        raise _workflow_http(exc)
    db.commit()
    return serialize(run)


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: uuid.UUID, payload: dict = Body(default={}),
               principal: Principal = Depends(require_permission("approval:decide")),
               db: Session = Depends(get_db)) -> dict:
    """Decide a waiting approval step: {"decision": "approve"|"reject", "note": "..."}."""
    run = db.get(WorkflowRun, run_id)
    if not run or run.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Workflow run not found")
    decision = payload.get("decision", "approve")
    if decision not in ("approve", "reject"):
        raise HTTPException(422, detail="decision must be approve or reject")
    try:
        workflow.resume_workflow(db, principal, run, decision, str(payload.get("note", "")))
    except workflow.WorkflowError as exc:
        db.rollback()
        raise _workflow_http(exc)
    db.commit()
    return serialize(run)
