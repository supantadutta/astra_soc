"""Response Actions + Approval Center APIs."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import ApprovalRequest, PolicyDecision, ResponseAction
from ..schemas.common import serialize
from ..services import response as gateway
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/response", tags=["response"])


@router.get("/actions")
def list_actions(principal: Principal = Depends(require_permission("approval:read")),
                 db: Session = Depends(get_db),
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                 status: str | None = None, incident_id: uuid.UUID | None = None) -> dict:
    scope = current_scope(db)
    filters = []
    if status:
        filters.append(ResponseAction.status == status)
    if incident_id:
        filters.append(ResponseAction.incident_id == incident_id)
    return paginate(db, ResponseAction, tenant_id=principal.tenant_id, scope=scope,
                    filters=filters, sort="created_at", page=page, page_size=page_size)


@router.post("/actions")
def create_action(payload: dict,
                  principal: Principal = Depends(require_permission("action:request")),
                  db: Session = Depends(get_db)) -> dict:
    """Request a response action. Runs the full safety pipeline (schema,
    evidence, confidence, criticality, blast radius, RBAC, policy, approval
    determination). Never executes here."""
    scope = current_scope(db)
    try:
        action = gateway.create_action(
            db, principal, scope=scope, action_type=payload["action_type"],
            target=payload.get("target", {}),
            incident_id=uuid.UUID(payload["incident_id"]) if payload.get("incident_id") else None,
            evidence_ids=payload.get("evidence_ids", []),
            confidence=float(payload.get("confidence", 0.0)),
            expected_outcome=payload.get("expected_outcome", ""),
            connector_kind=payload.get("connector_kind"),
        )
    except gateway.ResponseError as exc:
        raise HTTPException(400, detail={"error": exc.code, "message": exc.message, **exc.detail})
    db.commit()
    decision = db.execute(select(PolicyDecision).where(
        PolicyDecision.response_action_id == action.id)).scalar_one_or_none()
    return {"action": serialize(action),
            "policy_decision": serialize(decision) if decision else None}


@router.get("/actions/{action_id}")
def get_action(action_id: uuid.UUID,
               principal: Principal = Depends(require_permission("approval:read")),
               db: Session = Depends(get_db)) -> dict:
    a = db.get(ResponseAction, action_id)
    if not a or a.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Action not found")
    decision = db.execute(select(PolicyDecision).where(
        PolicyDecision.response_action_id == a.id)).scalar_one_or_none()
    approval = db.execute(select(ApprovalRequest).where(
        ApprovalRequest.response_action_id == a.id)).scalar_one_or_none()
    return {"action": serialize(a),
            "policy_decision": serialize(decision) if decision else None,
            "approval": serialize(approval) if approval else None}


@router.post("/actions/{action_id}/dry-run")
def dry_run(action_id: uuid.UUID,
            principal: Principal = Depends(require_permission("action:request")),
            db: Session = Depends(get_db)) -> dict:
    a = _load(db, principal, action_id)
    try:
        gateway.dry_run(db, a, principal)
    except gateway.ResponseError as exc:
        raise HTTPException(400, detail={"error": exc.code, "message": exc.message})
    db.commit()
    return serialize(a)


@router.post("/actions/{action_id}/execute")
def execute(action_id: uuid.UUID, request: Request,
            principal: Principal = Depends(require_permission("action:execute")),
            db: Session = Depends(get_db)) -> dict:
    a = _load(db, principal, action_id)
    try:
        gateway.execute(db, a, principal, getattr(request.state, "request_id", "req"))
    except gateway.ResponseError as exc:
        raise HTTPException(400, detail={"error": exc.code, "message": exc.message})
    db.commit()
    return serialize(a)


@router.post("/actions/{action_id}/verify")
def verify(action_id: uuid.UUID,
           principal: Principal = Depends(require_permission("action:execute")),
           db: Session = Depends(get_db)) -> dict:
    a = _load(db, principal, action_id)
    gateway.verify(db, a)
    db.commit()
    return serialize(a)


@router.post("/actions/{action_id}/rollback")
def rollback(action_id: uuid.UUID,
             principal: Principal = Depends(require_permission("action:execute")),
             db: Session = Depends(get_db)) -> dict:
    a = _load(db, principal, action_id)
    try:
        gateway.rollback(db, a, principal)
    except gateway.ResponseError as exc:
        raise HTTPException(400, detail={"error": exc.code, "message": exc.message})
    db.commit()
    return serialize(a)


def _load(db, principal, action_id) -> ResponseAction:
    a = db.get(ResponseAction, action_id)
    if not a or a.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Action not found")
    return a


# --- Approval Center ------------------------------------------------------
approvals_router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


@approvals_router.get("")
def list_approvals(principal: Principal = Depends(require_permission("approval:read")),
                   db: Session = Depends(get_db),
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                   status: str | None = None) -> dict:
    filters = [ApprovalRequest.status == status] if status else []
    return paginate(db, ApprovalRequest, tenant_id=principal.tenant_id, filters=filters,
                    sort="created_at", page=page, page_size=page_size)


@approvals_router.post("/{approval_id}/approve")
def approve(approval_id: uuid.UUID, payload: dict | None = None,
            principal: Principal = Depends(require_permission("approval:decide")),
            db: Session = Depends(get_db)) -> dict:
    approval, action = _load_approval(db, principal, approval_id)
    # Enforce that the approver actually holds the role the policy required.
    if approval.required_role not in principal.roles and not principal.has("rbac:manage"):
        raise HTTPException(403, detail={
            "error": "wrong_approver_role",
            "message": f"This approval requires role '{approval.required_role}'."})
    try:
        gateway.approve(db, action, approval, principal, (payload or {}).get("note", ""))
    except gateway.ResponseError as exc:
        raise HTTPException(400, detail={"error": exc.code, "message": exc.message})
    db.commit()
    return {"approval": serialize(approval), "action": serialize(action)}


@approvals_router.post("/{approval_id}/reject")
def reject(approval_id: uuid.UUID, payload: dict | None = None,
           principal: Principal = Depends(require_permission("approval:decide")),
           db: Session = Depends(get_db)) -> dict:
    approval, action = _load_approval(db, principal, approval_id)
    gateway.reject(db, action, approval, principal, (payload or {}).get("note", ""))
    db.commit()
    return {"approval": serialize(approval), "action": serialize(action)}


def _load_approval(db, principal, approval_id):
    approval = db.get(ApprovalRequest, approval_id)
    if not approval or approval.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Approval not found")
    action = db.get(ResponseAction, approval.response_action_id)
    return approval, action
