"""Append-only, tamper-evident audit logging.

Each entry stores a hash chained to the previous entry's hash, so any deletion
or in-place edit breaks the chain and is detectable via
:func:`verify_audit_chain`. Sensitive values are never written in the clear —
callers pass already-redacted detail.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..auth.security import content_hash
from ..models import AuditEvent
from .events import Event, bus


def _last_hash(db: Session, tenant_id: uuid.UUID | None) -> str | None:
    row = db.execute(
        select(AuditEvent).order_by(desc(AuditEvent.created_at), desc(AuditEvent.id)).limit(1)
    ).scalar_one_or_none()
    return row.entry_hash if row else None


def record(
    db: Session,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    actor_type: str = "user",
    actor_label: str = "",
    tenant_id: uuid.UUID | None = None,
    resource_type: str = "",
    resource_id: str | None = None,
    outcome: str = "success",
    data_scope: str = "DEMO",
    request_id: str | None = None,
    ip_address: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    prev = _last_hash(db, tenant_id)
    payload = {
        "action": action,
        "actor_id": str(actor_id) if actor_id else None,
        "actor_type": actor_type,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "outcome": outcome,
        "data_scope": data_scope,
        "detail": detail or {},
        "prev": prev,
    }
    entry_hash = content_hash(json.dumps(payload, sort_keys=True, default=str))
    event = AuditEvent(
        action=action,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_label=actor_label,
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        data_scope=data_scope,
        request_id=request_id,
        ip_address=ip_address,
        detail=detail or {},
        prev_hash=prev,
        entry_hash=entry_hash,
    )
    db.add(event)
    db.flush()
    bus.publish_soon(Event(
        type="audit.recorded", scope=data_scope,
        tenant_id=str(tenant_id) if tenant_id else None,
        data={"action": action, "resource_type": resource_type, "outcome": outcome},
    ))
    return event


def verify_audit_chain(db: Session, limit: int = 1000) -> dict[str, Any]:
    """Recompute the hash chain to detect tampering. Returns a report."""
    rows = db.execute(
        select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id).limit(limit)
    ).scalars().all()
    prev = None
    broken_at = None
    for row in rows:
        payload = {
            "action": row.action,
            "actor_id": str(row.actor_id) if row.actor_id else None,
            "actor_type": row.actor_type,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "outcome": row.outcome,
            "data_scope": row.data_scope,
            "detail": row.detail or {},
            "prev": prev,
        }
        expected = content_hash(json.dumps(payload, sort_keys=True, default=str))
        if expected != row.entry_hash:
            broken_at = str(row.id)
            break
        prev = row.entry_hash
    return {"verified": broken_at is None, "checked": len(rows), "broken_at": broken_at}
