"""Integrations API: connector CRUD, credential references, connection tests."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..models import Connector, ConnectorCredentialReference, ConnectorHealth
from ..schemas.common import serialize
from ..services import audit
from ..services.connectors.registry import get_adapter
from ..services.secrets import secret_configured

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


def _serialize_connector(db: Session, c: Connector) -> dict:
    data = serialize(c)
    refs = db.execute(select(ConnectorCredentialReference).where(
        ConnectorCredentialReference.connector_id == c.id)).scalars().all()
    data["credential_refs"] = [{"field": r.field, "secret_ref": r.secret_ref,
                                "configured": secret_configured(r.secret_ref)} for r in refs]
    latest = db.execute(select(ConnectorHealth).where(
        ConnectorHealth.connector_id == c.id).order_by(
        ConnectorHealth.checked_at.desc()).limit(1)).scalar_one_or_none()
    data["latest_health"] = serialize(latest) if latest else None
    return data


@router.get("")
def list_connectors(principal: Principal = Depends(require_permission("connector:read")),
                    db: Session = Depends(get_db), category: str | None = None) -> dict:
    q = select(Connector).where(Connector.tenant_id == principal.tenant_id)
    if category:
        q = q.where(Connector.category == category)
    rows = db.execute(q.order_by(Connector.category, Connector.name)).scalars().all()
    return {"items": [_serialize_connector(db, c) for c in rows]}


@router.get("/{connector_id}")
def get_connector(connector_id: uuid.UUID,
                  principal: Principal = Depends(require_permission("connector:read")),
                  db: Session = Depends(get_db)) -> dict:
    c = db.get(Connector, connector_id)
    if not c or c.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Connector not found")
    return _serialize_connector(db, c)


@router.patch("/{connector_id}")
def update_connector(connector_id: uuid.UUID, payload: dict,
                     principal: Principal = Depends(require_permission("connector:manage")),
                     db: Session = Depends(get_db)) -> dict:
    c = db.get(Connector, connector_id)
    if not c or c.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Connector not found")
    for field in ("name", "enabled", "base_url", "config", "can_read", "can_write",
                  "collection_interval_seconds", "rate_limit_per_minute", "use_mock"):
        if field in payload:
            setattr(c, field, payload[field])
    # Credential references (never the secret value itself).
    if "credential_refs" in payload:
        db.execute(select(ConnectorCredentialReference).where(
            ConnectorCredentialReference.connector_id == c.id))
        existing = {r.field: r for r in db.execute(select(ConnectorCredentialReference).where(
            ConnectorCredentialReference.connector_id == c.id)).scalars()}
        for ref in payload["credential_refs"]:
            field, sref = ref.get("field"), ref.get("secret_ref")
            if not field or not sref:
                continue
            if field in existing:
                existing[field].secret_ref = sref
            else:
                db.add(ConnectorCredentialReference(connector_id=c.id, field=field, secret_ref=sref))
    audit.record(db, action="connector.updated", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="connector",
                 resource_id=str(connector_id), detail={"fields": list(payload)})
    db.commit()
    return _serialize_connector(db, c)


@router.post("/{connector_id}/test")
def test_connection(connector_id: uuid.UUID,
                    principal: Principal = Depends(require_permission("connector:manage")),
                    db: Session = Depends(get_db)) -> dict:
    """Perform a real connection test (or a truthful mock result in mock mode).
    Records a ConnectorHealth entry — never fabricates a healthy status."""
    c = db.get(Connector, connector_id)
    if not c or c.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Connector not found")
    result = get_adapter(c).test_connection()
    now = datetime.now(UTC)
    db.add(ConnectorHealth(
        connector_id=c.id, state=result.state, checked_at=now, latency_ms=result.latency_ms,
        last_success_at=now if result.state == "healthy" else None,
        last_error=result.error, detail=result.to_dict(),
    ))
    audit.record(db, action="connector.tested", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="connector",
                 resource_id=str(connector_id),
                 outcome="success" if result.state == "healthy" else "failure",
                 detail={"state": result.state, "mock": result.mock})
    db.commit()
    return result.to_dict()


@router.post("/{connector_id}/sync")
def sync_connector(connector_id: uuid.UUID,
                   principal: Principal = Depends(require_permission("connector:manage")),
                   db: Session = Depends(get_db)) -> dict:
    c = db.get(Connector, connector_id)
    if not c or c.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Connector not found")
    if not c.enabled:
        raise HTTPException(400, detail="Connector is disabled.")
    events = get_adapter(c).fetch_events()
    audit.record(db, action="connector.sync", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="connector",
                 resource_id=str(connector_id), detail={"fetched": len(events)})
    db.commit()
    return {"fetched": len(events), "sample": events[:5],
            "note": "Mock/read-only fetch. Live ingestion writes normalized OCSF events."}
