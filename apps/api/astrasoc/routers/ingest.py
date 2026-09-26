"""Event ingestion API — push-based telemetry for LIVE operation.

SIEM forwarders, syslog relays and EDR webhooks push batches here with a
scoped API key (``event:ingest``). Events land in the tenant's CURRENT scope
and go through the same deterministic detection and correlation pipeline as
everything else.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..services import audit
from ..services.mode import current_scope
from ..services.pipeline import ingest_batch

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

MAX_BATCH = 500


@router.post("/events")
def ingest_events(payload: dict = Body(...),
                  principal: Principal = Depends(require_permission("event:ingest")),
                  db: Session = Depends(get_db)) -> dict:
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise HTTPException(422, detail="events must be a non-empty list")
    if len(events) > MAX_BATCH:
        raise HTTPException(413, detail=f"At most {MAX_BATCH} events per batch")
    if not all(isinstance(e, dict) for e in events):
        raise HTTPException(422, detail="each event must be an object")
    scope = current_scope(db, principal.tenant_id)
    result = ingest_batch(db, principal.tenant_id, scope, events)
    audit.record(db, action="ingest.batch", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="events", data_scope=scope, detail=result)
    db.commit()
    return {**result, "scope": scope}
