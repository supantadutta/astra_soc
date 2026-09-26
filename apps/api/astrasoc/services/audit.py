"""Append-only, tamper-evident audit logging (keyed hash chain).

Each entry stores ``entry_hash = HMAC-SHA256(audit_key, canonical(entry))``
where the canonical form covers every recorded field (sequence number,
tenant, actor, action, resource, outcome, scope, network context, detail,
timestamp) plus the previous entry's hash. Because the chain is keyed with
``ASTRASOC_AUDIT_KEY`` (kept outside the database), someone with database
write access cannot edit, delete or insert entries and recompute a valid
chain. Appends are serialised (process lock + a PostgreSQL advisory
transaction lock) so concurrent writers cannot fork the chain.

:func:`verify_audit_chain` walks the WHOLE chain in sequence order in
batches and reports the first break.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuditEvent
from .events import Event, bus

_APPEND_LOCK = threading.Lock()
_PG_LOCK_KEY = 0x41535452  # "ASTR"


def _canonical(e: AuditEvent) -> str:
    return json.dumps({
        "v": 2, "seq": e.seq, "tenant_id": str(e.tenant_id) if e.tenant_id else None,
        "actor_id": str(e.actor_id) if e.actor_id else None, "actor_type": e.actor_type,
        "actor_label": e.actor_label, "action": e.action, "resource_type": e.resource_type,
        "resource_id": e.resource_id, "outcome": e.outcome, "data_scope": e.data_scope,
        "ip_address": e.ip_address, "request_id": e.request_id, "detail": e.detail or {},
        "created_at": e.created_at.astimezone(UTC).isoformat() if e.created_at else None,
        "prev": e.prev_hash,
    }, sort_keys=True, default=str, separators=(",", ":"))


def _sign(e: AuditEvent) -> str:
    return hmac.new(settings.audit_signing_key.encode(), _canonical(e).encode(),
                    hashlib.sha256).hexdigest()


def _normalise_detail(detail: dict[str, Any] | None) -> dict:
    # Round-trip through JSON so the stored value hashes identically on read.
    return json.loads(json.dumps(detail or {}, default=str))


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
    with _APPEND_LOCK:
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PG_LOCK_KEY})
        last = db.execute(select(AuditEvent).where(AuditEvent.seq.is_not(None))
                          .order_by(desc(AuditEvent.seq)).limit(1)).scalar_one_or_none()
        event = AuditEvent(
            seq=(last.seq + 1) if last else 1, chain_version=2,
            action=action, actor_id=actor_id, actor_type=actor_type,
            actor_label=(actor_label or "")[:160], tenant_id=tenant_id,
            resource_type=resource_type, resource_id=resource_id, outcome=outcome,
            data_scope=data_scope, request_id=request_id, ip_address=ip_address,
            detail=_normalise_detail(detail), prev_hash=last.entry_hash if last else None,
            created_at=datetime.now(UTC),
        )
        event.entry_hash = _sign(event)
        db.add(event)
        db.flush()
    bus.publish_soon(Event(
        type="audit.recorded", scope=data_scope,
        tenant_id=str(tenant_id) if tenant_id else None,
        data={"action": action, "resource_type": resource_type, "outcome": outcome},
    ))
    return event


def verify_audit_chain(db: Session, batch: int = 1000) -> dict[str, Any]:
    """Recompute the full keyed chain in sequence order. Returns a report."""
    prev: str | None = None
    expected_seq = 1
    checked = 0
    broken_at = None
    reason = None
    last_seq = 0
    while broken_at is None:
        rows = db.execute(select(AuditEvent).where(AuditEvent.seq > last_seq)
                          .order_by(AuditEvent.seq).limit(batch)).scalars().all()
        if not rows:
            break
        for row in rows:
            if row.seq != expected_seq:
                broken_at, reason = str(row.id), f"sequence gap: expected {expected_seq}, found {row.seq}"
                break
            if row.prev_hash != prev:
                broken_at, reason = str(row.id), "previous-hash link mismatch"
                break
            if not hmac.compare_digest(row.entry_hash or "", _sign(row)):
                broken_at, reason = str(row.id), "entry content does not match its signature"
                break
            prev = row.entry_hash
            expected_seq += 1
            checked += 1
            last_seq = row.seq
    legacy = db.execute(select(func.count()).select_from(AuditEvent)
                        .where(AuditEvent.seq.is_(None))).scalar() or 0
    return {"verified": broken_at is None, "checked": checked, "broken_at": broken_at,
            "reason": reason, "legacy_unchained": legacy, "algorithm": "HMAC-SHA256 chain v2"}
