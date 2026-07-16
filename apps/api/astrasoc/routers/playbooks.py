"""Automation Playbooks API: playbooks, versions, and durable workflow runs."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import Playbook, PlaybookVersion, WorkflowRun
from ..schemas.common import serialize, serialize_many
from ..services import workflow
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/playbooks", tags=["playbooks"])


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
    scope = current_scope(db)
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
def upsert_playbook(playbook_key: str, payload: dict,
                    principal: Principal = Depends(require_permission("playbook:write")),
                    db: Session = Depends(get_db)) -> dict:
    """Create or update a playbook (visual builder save). Bumps the version and
    stores the new graph, keeping prior versions."""
    pb = db.execute(select(Playbook).where(
        Playbook.tenant_id == principal.tenant_id, Playbook.key == playbook_key)).scalar_one_or_none()
    if pb is None:
        pb = Playbook(tenant_id=principal.tenant_id, key=playbook_key,
                      name=payload.get("name", playbook_key), description=payload.get("description", ""),
                      trigger=payload.get("trigger", {}), tags=payload.get("tags", []))
        db.add(pb)
        db.flush()
    else:
        for f in ("name", "description", "enabled", "trigger", "tags"):
            if f in payload:
                setattr(pb, f, payload[f])
    if "graph" in payload:
        # deactivate old, add new version
        for v in db.execute(select(PlaybookVersion).where(
                PlaybookVersion.playbook_id == pb.id)).scalars():
            v.is_active = False
        parts = pb.current_version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        pb.current_version = ".".join(parts)
        db.add(PlaybookVersion(playbook_id=pb.id, version=pb.current_version,
                               graph=payload["graph"], is_active=True,
                               changelog=payload.get("changelog", "Updated via builder.")))
    db.commit()
    return get_playbook(playbook_key, principal, db)


@router.post("/{playbook_key}/run")
def run_playbook(playbook_key: str, payload: dict,
                 principal: Principal = Depends(require_permission("playbook:read")),
                 db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    incident_id = uuid.UUID(payload["incident_id"]) if payload.get("incident_id") else None
    run = workflow.start_workflow(db, principal, playbook_key, incident_id, scope,
                                  idempotency_key=payload.get("idempotency_key"))
    db.commit()
    return serialize(run)


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: uuid.UUID,
               principal: Principal = Depends(require_permission("playbook:read")),
               db: Session = Depends(get_db)) -> dict:
    run = db.get(WorkflowRun, run_id)
    if not run or run.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Workflow run not found")
    workflow.resume_workflow(db, principal, run)
    db.commit()
    return serialize(run)
