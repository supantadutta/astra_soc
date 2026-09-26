"""Integrations API: connector CRUD, credential references, connection tests."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..models import Connector, ConnectorCredentialReference, ConnectorHealth
from ..schemas.common import serialize
from ..services import audit
from ..services.connectors.registry import get_adapter
from ..services.egress import EgressError, validate_outbound_url
from ..services.mode import current_scope
from ..services.pipeline import ingest_batch
from ..services.secrets import SecretRefError, secret_configured, validate_secret_ref

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


_CRED_FIELDS = {"api_token", "api_key", "token", "client_id", "client_secret",
                "username", "password"}
_MUTABLE = ("name", "enabled", "base_url", "config", "can_read", "can_write",
            "collection_interval_seconds", "rate_limit_per_minute", "use_mock")


@router.patch("/{connector_id}")
def update_connector(connector_id: uuid.UUID, payload: dict = Body(...),
                     principal: Principal = Depends(require_permission("connector:manage")),
                     db: Session = Depends(get_db)) -> dict:
    c = db.get(Connector, connector_id)
    if not c or c.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Connector not found")
    if payload.get("base_url"):
        try:
            payload["base_url"] = validate_outbound_url(payload["base_url"], resolve=False)
        except EgressError as exc:
            raise HTTPException(422, detail={"error": "egress_blocked", "message": str(exc)})
    for field, lo, hi in (("collection_interval_seconds", 30, 86400), ("rate_limit_per_minute", 1, 6000)):
        if field in payload and not lo <= int(payload[field]) <= hi:
            raise HTTPException(422, detail=f"{field} must be between {lo} and {hi}")
    refs = []
    for ref in payload.get("credential_refs") or []:
        field, sref = ref.get("field"), ref.get("secret_ref")
        if not field or not sref:
            continue
        if field not in _CRED_FIELDS:
            raise HTTPException(422, detail=f"credential field must be one of {sorted(_CRED_FIELDS)}")
        try:
            sref = validate_secret_ref(sref, tenant_slug=principal.tenant_slug,
                                       platform_admin=principal.is_platform_admin)
        except SecretRefError as exc:
            raise HTTPException(422, detail={"error": "invalid_secret_ref", "message": str(exc)})
        refs.append((field, sref))
    for field in _MUTABLE:
        if field in payload:
            setattr(c, field, payload[field])
    if refs:
        existing = {r.field: r for r in db.execute(select(ConnectorCredentialReference).where(
            ConnectorCredentialReference.connector_id == c.id)).scalars()}
        for field, sref in refs:
            if field in existing:
                existing[field].secret_ref = sref
                existing[field].last_rotated_at = datetime.now(UTC)
            else:
                db.add(ConnectorCredentialReference(connector_id=c.id, field=field, secret_ref=sref))
    audit.record(db, action="connector.updated", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="connector", resource_id=str(connector_id),
                 detail={"fields": sorted(set(payload) - {"credential_refs"}),
                         "credential_fields": [f for f, _ in refs]})
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
    """Pull events from the connector and run them through the pipeline.

    Mock connectors produce simulated data and may only feed the DEMO scope:
    syncing a mock connector while the tenant is LIVE is refused, so
    simulated events can never contaminate live data."""
    c = db.get(Connector, connector_id)
    if not c or c.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Connector not found")
    if not c.enabled or not c.can_read:
        raise HTTPException(400, detail="Connector is disabled or not read-enabled.")
    scope = current_scope(db, principal.tenant_id)
    if c.use_mock and scope == "LIVE":
        raise HTTPException(409, detail={"error": "mock_in_live",
                                         "message": "Mock connectors cannot feed LIVE data."})
    events = get_adapter(c).fetch_events()
    result = ingest_batch(db, principal.tenant_id, scope, events, connector_id=c.id) if events \
        else {"ingested": 0, "alerts": 0}
    audit.record(db, action="connector.sync", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="connector", resource_id=str(connector_id), data_scope=scope,
                 detail={**result, "mock": c.use_mock})
    db.commit()
    note = ("Simulated events from the built-in mock server." if c.use_mock else
            "Live pull adapters for this vendor return no events in this build; "
            "use the push ingestion API (/api/v1/ingest/events) for live telemetry.")
    return {**result, "scope": scope, "mock": c.use_mock, "note": note}
