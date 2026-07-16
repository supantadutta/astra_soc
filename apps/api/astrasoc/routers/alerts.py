"""Alerts API: list/filter/search, acknowledge/triage, promote to incident."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import Alert, Incident, IncidentAlert
from ..models.enums import AlertStatus, IncidentStatus
from ..schemas.common import serialize
from ..services import audit
from ..services.events import Event, bus
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    principal: Principal = Depends(require_permission("alert:read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    severity: str | None = None, status: str | None = None, source: str | None = None,
    q: str | None = None, sort: str | None = None, order: str = "desc",
) -> dict:
    scope = current_scope(db)
    filters = []
    if severity:
        filters.append(Alert.severity == severity)
    if status:
        filters.append(Alert.status == status)
    if source:
        filters.append(Alert.source == source)
    return paginate(db, Alert, tenant_id=principal.tenant_id, scope=scope, filters=filters,
                    search=q, search_fields=["title", "description", "source"],
                    sort=sort, order=order, page=page, page_size=page_size)


@router.get("/{alert_id}")
def get_alert(alert_id: uuid.UUID,
              principal: Principal = Depends(require_permission("alert:read")),
              db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    a = db.get(Alert, alert_id)
    if not a or a.tenant_id != principal.tenant_id or a.data_scope != scope:
        raise HTTPException(404, detail="Alert not found")
    return serialize(a)


@router.post("/{alert_id}/acknowledge")
def acknowledge(alert_id: uuid.UUID,
                principal: Principal = Depends(require_permission("alert:write")),
                db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    a = db.get(Alert, alert_id)
    if not a or a.tenant_id != principal.tenant_id or a.data_scope != scope:
        raise HTTPException(404, detail="Alert not found")
    a.status = AlertStatus.ACKNOWLEDGED.value
    a.acknowledged_at = datetime.now(UTC)
    a.assignee_id = principal.user_id
    audit.record(db, action="alert.acknowledged", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="alert", resource_id=str(alert_id),
                 data_scope=scope)
    db.commit()
    return serialize(a)


@router.patch("/{alert_id}")
def update_alert(alert_id: uuid.UUID, payload: dict,
                 principal: Principal = Depends(require_permission("alert:write")),
                 db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    a = db.get(Alert, alert_id)
    if not a or a.tenant_id != principal.tenant_id or a.data_scope != scope:
        raise HTTPException(404, detail="Alert not found")
    for field in ("status", "severity"):
        if field in payload:
            setattr(a, field, payload[field])
    db.commit()
    return serialize(a)


@router.post("/{alert_id}/promote")
def promote_to_incident(alert_id: uuid.UUID,
                        principal: Principal = Depends(require_permission("incident:write")),
                        db: Session = Depends(get_db)) -> dict:
    """Create a new incident from an alert (or attach to an existing one)."""
    scope = current_scope(db)
    a = db.get(Alert, alert_id)
    if not a or a.tenant_id != principal.tenant_id or a.data_scope != scope:
        raise HTTPException(404, detail="Alert not found")
    if a.incident_id:
        raise HTTPException(400, detail="Alert already belongs to an incident.")

    from sqlalchemy import func
    count = db.execute(select(func.count()).select_from(Incident).where(
        Incident.tenant_id == principal.tenant_id)).scalar() or 0
    inc = Incident(
        tenant_id=principal.tenant_id, data_scope=scope, key=f"INC-{count + 1:06d}",
        title=a.title, summary=a.description or f"Promoted from alert {a.id}.",
        severity=a.severity, status=IncidentStatus.NEW.value, confidence=a.confidence,
        business_risk=a.risk_score, risk_score=a.risk_score,
        attack_techniques=a.attack_techniques, owner_id=principal.user_id,
        affected_hosts=[a.observables.get("host")] if a.observables.get("host") else [],
        affected_users=[a.observables.get("user")] if a.observables.get("user") else [],
    )
    db.add(inc)
    db.flush()
    a.incident_id = inc.id
    a.status = AlertStatus.INVESTIGATING.value
    db.add(IncidentAlert(incident_id=inc.id, alert_id=a.id,
                         correlation_reason="Promoted by analyst", correlation_score=1.0))
    audit.record(db, action="incident.created_from_alert", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="incident", resource_id=str(inc.id),
                 data_scope=scope, detail={"alert_id": str(alert_id)})
    bus.publish_soon(Event(type="incident.created", scope=scope, tenant_id=str(principal.tenant_id),
                           data={"incident_id": str(inc.id), "key": inc.key, "title": inc.title,
                                 "severity": inc.severity}))
    db.commit()
    return serialize(inc)


@router.get("/meta/facets")
def facets(principal: Principal = Depends(require_permission("alert:read")),
           db: Session = Depends(get_db)) -> dict:
    """Distinct values for building filter UIs."""
    scope = current_scope(db)
    from sqlalchemy import func
    def distinct(col):
        return [r[0] for r in db.execute(
            select(col, func.count()).where(Alert.tenant_id == principal.tenant_id,
                                            Alert.data_scope == scope).group_by(col)
        ).all()]
    return {"severities": distinct(Alert.severity), "statuses": distinct(Alert.status),
            "sources": distinct(Alert.source)}
