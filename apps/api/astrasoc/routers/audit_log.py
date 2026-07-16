"""Audit Logs API: list, filter, and verify the tamper-evident chain."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import AuditEvent
from ..services.audit import verify_audit_chain

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("")
def list_audit(principal: Principal = Depends(require_permission("audit:read")),
               db: Session = Depends(get_db),
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               action: str | None = None, actor_type: str | None = None,
               q: str | None = None) -> dict:
    filters = [AuditEvent.tenant_id == principal.tenant_id]
    if action:
        filters.append(AuditEvent.action == action)
    if actor_type:
        filters.append(AuditEvent.actor_type == actor_type)
    return paginate(db, AuditEvent, tenant_id=None, filters=filters,
                    search=q, search_fields=["action", "actor_label", "resource_type"],
                    sort="created_at", page=page, page_size=page_size)


@router.get("/verify")
def verify(principal: Principal = Depends(require_permission("audit:read")),
           db: Session = Depends(get_db)) -> dict:
    """Recompute the audit hash chain to prove no entry was altered/deleted."""
    return verify_audit_chain(db)
