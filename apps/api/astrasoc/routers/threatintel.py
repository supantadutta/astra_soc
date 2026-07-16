"""Threat Intelligence API: indicators list/search/manage."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import ThreatIndicator
from ..schemas.common import serialize
from ..services import audit

router = APIRouter(prefix="/api/v1/threat-intel", tags=["threat-intel"])


@router.get("")
def list_indicators(principal: Principal = Depends(require_permission("threatintel:read")),
                    db: Session = Depends(get_db),
                    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                    ioc_type: str | None = None, source: str | None = None,
                    q: str | None = None) -> dict:
    filters = []
    if ioc_type:
        filters.append(ThreatIndicator.ioc_type == ioc_type)
    if source:
        filters.append(ThreatIndicator.source == source)
    return paginate(db, ThreatIndicator, tenant_id=principal.tenant_id, filters=filters,
                    search=q, search_fields=["value", "threat_type", "source"],
                    sort="last_seen", page=page, page_size=page_size)


@router.get("/lookup")
def lookup(value: str,
           principal: Principal = Depends(require_permission("threatintel:read")),
           db: Session = Depends(get_db)) -> dict:
    row = db.execute(select(ThreatIndicator).where(
        ThreatIndicator.tenant_id == principal.tenant_id,
        ThreatIndicator.value == value)).scalar_one_or_none()
    return {"found": row is not None, "indicator": serialize(row) if row else None}


@router.post("")
def create_indicator(payload: dict,
                     principal: Principal = Depends(require_permission("threatintel:write")),
                     db: Session = Depends(get_db)) -> dict:
    ioc = ThreatIndicator(
        tenant_id=principal.tenant_id, ioc_type=payload["ioc_type"], value=payload["value"],
        threat_type=payload.get("threat_type", ""), confidence=payload.get("confidence", 0.5),
        severity=payload.get("severity", "medium"), source=payload.get("source", "manual"),
        tlp=payload.get("tlp", "amber"), tags=payload.get("tags", []),
    )
    db.add(ioc)
    audit.record(db, action="threatintel.created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="threat_indicator",
                 resource_id=str(ioc.id))
    db.commit()
    return serialize(ioc)


@router.patch("/{indicator_id}")
def update_indicator(indicator_id: uuid.UUID, payload: dict,
                     principal: Principal = Depends(require_permission("threatintel:write")),
                     db: Session = Depends(get_db)) -> dict:
    ioc = db.get(ThreatIndicator, indicator_id)
    if not ioc or ioc.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Indicator not found")
    for field in ("threat_type", "confidence", "severity", "enabled", "tlp", "tags"):
        if field in payload:
            setattr(ioc, field, payload[field])
    db.commit()
    return serialize(ioc)
