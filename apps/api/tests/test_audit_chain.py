"""The keyed audit chain detects edits, deletions and forged re-hashing."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, update


def _verify(client, auditor):
    return client.get("/api/v1/audit/verify", headers=auditor).json()


def test_chain_verifies_and_detects_tampering(client, auditor, manager):
    from astrasoc.db import SessionLocal
    from astrasoc.models import AuditEvent

    client.post("/api/v1/reports", headers=manager, json={"report_type": "executive_summary"})
    ok = _verify(client, auditor)
    assert ok["verified"] is True and ok["checked"] >= 3 and ok["algorithm"].startswith("HMAC")

    with SessionLocal() as db:
        target = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).offset(2)
                            .limit(1)).scalar_one()
        target_id, original_detail, original_hash = target.id, target.detail, target.entry_hash
        # 1) edit content
        db.execute(update(AuditEvent).where(AuditEvent.id == target_id)
                   .values(detail={"tampered": True}))
        db.commit()
    bad = _verify(client, auditor)
    assert bad["verified"] is False and "signature" in bad["reason"]

    with SessionLocal() as db:
        # 2) an attacker with DB access recomputes an UNKEYED hash — still detected
        forged = hashlib.sha256(json.dumps({"tampered": True}).encode()).hexdigest()
        db.execute(update(AuditEvent).where(AuditEvent.id == target_id).values(entry_hash=forged))
        db.commit()
    assert _verify(client, auditor)["verified"] is False

    with SessionLocal() as db:  # restore
        db.execute(update(AuditEvent).where(AuditEvent.id == target_id)
                   .values(detail=original_detail, entry_hash=original_hash))
        db.commit()
    assert _verify(client, auditor)["verified"] is True


def test_chain_detects_deleted_entry(client, auditor):
    from astrasoc.db import SessionLocal
    from astrasoc.models import AuditEvent
    from astrasoc.schemas.common import serialize

    with SessionLocal() as db:
        victim = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).offset(1)
                            .limit(1)).scalar_one()
        snapshot = serialize(victim)
        db.delete(victim)
        db.commit()
    rep = _verify(client, auditor)
    assert rep["verified"] is False and "sequence gap" in rep["reason"]
    with SessionLocal() as db:  # restore the row exactly
        import uuid
        from datetime import datetime

        data = dict(snapshot)
        for k in ("id", "tenant_id", "actor_id"):
            data[k] = uuid.UUID(data[k]) if data.get(k) else None
        for k in ("created_at", "updated_at"):
            data[k] = datetime.fromisoformat(data[k])
        db.add(AuditEvent(**data))
        db.commit()
    assert _verify(client, auditor)["verified"] is True
