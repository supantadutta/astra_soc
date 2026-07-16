"""AI Model Operations API: providers, deployments, routes, connectivity tests."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..models import ModelDeployment, ModelProvider, ModelRoute
from ..models.enums import ProviderKind
from ..schemas.common import serialize, serialize_many
from ..services import audit
from ..services.model_gateway.providers import test_connectivity
from ..services.secrets import secret_configured

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("/providers")
def list_providers(principal: Principal = Depends(require_permission("model:read")),
                   db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(ModelProvider).where(
        ModelProvider.tenant_id == principal.tenant_id)).scalars().all()
    out = []
    for p in rows:
        data = serialize(p, exclude={"secret_ref"})
        data["secret_configured"] = secret_configured(p.secret_ref)
        data["deployments"] = serialize_many(
            db.execute(select(ModelDeployment).where(
                ModelDeployment.provider_id == p.id)).scalars().all())
        out.append(data)
    return {"items": out}


@router.post("/providers")
def create_provider(payload: dict,
                    principal: Principal = Depends(require_permission("model:manage")),
                    db: Session = Depends(get_db)) -> dict:
    kind = payload.get("kind")
    if kind not in [k.value for k in ProviderKind]:
        raise HTTPException(422, detail="Invalid provider kind")
    p = ModelProvider(
        tenant_id=principal.tenant_id, name=payload.get("name", kind), kind=kind,
        enabled=payload.get("enabled", True), base_url=payload.get("base_url"),
        region=payload.get("region"), secret_ref=payload.get("secret_ref"),
        data_classification_allowance=payload.get("data_classification_allowance", "internal"),
        private_only=payload.get("private_only", False),
        daily_token_limit=payload.get("daily_token_limit", 0),
        timeout_seconds=payload.get("timeout_seconds", 60),
        fallback_priority=payload.get("fallback_priority", 100),
    )
    db.add(p)
    db.flush()
    for dep in payload.get("deployments", []):
        db.add(ModelDeployment(provider_id=p.id, model_identifier=dep["model_identifier"],
                               display_name=dep.get("display_name", ""),
                               capabilities=dep.get("capabilities", []),
                               cost_input_per_1k=dep.get("cost_input_per_1k", 0.0),
                               cost_output_per_1k=dep.get("cost_output_per_1k", 0.0)))
    audit.record(db, action="model.provider_created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="model_provider",
                 resource_id=str(p.id), detail={"kind": kind})
    db.commit()
    return serialize(p, exclude={"secret_ref"})


@router.patch("/providers/{provider_id}")
def update_provider(provider_id: uuid.UUID, payload: dict,
                    principal: Principal = Depends(require_permission("model:manage")),
                    db: Session = Depends(get_db)) -> dict:
    p = db.get(ModelProvider, provider_id)
    if not p or p.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Provider not found")
    for field in ("name", "enabled", "base_url", "region", "secret_ref", "private_only",
                  "daily_token_limit", "monthly_cost_limit_usd", "timeout_seconds",
                  "fallback_priority", "data_classification_allowance", "rate_limit_per_minute"):
        if field in payload:
            setattr(p, field, payload[field])
    audit.record(db, action="model.provider_updated", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="model_provider",
                 resource_id=str(provider_id))
    db.commit()
    return serialize(p, exclude={"secret_ref"})


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: uuid.UUID,
                  principal: Principal = Depends(require_permission("model:read")),
                  db: Session = Depends(get_db)) -> dict:
    """Perform a REAL connectivity test. Never reports success without a
    confirming response from the provider."""
    p = db.get(ModelProvider, provider_id)
    if not p or p.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Provider not found")
    result = test_connectivity(p.kind, p.base_url, p.secret_ref, timeout=p.timeout_seconds)
    p.health = result.state
    p.last_health_check = datetime.now(UTC)
    p.last_error = result.error
    if result.ok:
        p.consecutive_failures = 0
    audit.record(db, action="model.provider_tested", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="model_provider",
                 resource_id=str(provider_id), outcome="success" if result.ok else "failure",
                 detail={"state": result.state})
    db.commit()
    return {"provider_id": str(provider_id), "state": result.state, "latency_ms": result.latency_ms,
            "detail": result.detail, "error": result.error, "models_seen": result.models_seen}


@router.get("/routes")
def list_routes(principal: Principal = Depends(require_permission("model:read")),
                db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(ModelRoute).where(
        ModelRoute.tenant_id == principal.tenant_id)).scalars().all()
    return {"items": serialize_many(rows)}


@router.put("/routes/{capability}")
def upsert_route(capability: str, payload: dict,
                 principal: Principal = Depends(require_permission("model:manage")),
                 db: Session = Depends(get_db)) -> dict:
    route = db.execute(select(ModelRoute).where(
        ModelRoute.tenant_id == principal.tenant_id,
        ModelRoute.capability == capability)).scalar_one_or_none()
    if route is None:
        route = ModelRoute(tenant_id=principal.tenant_id, capability=capability)
        db.add(route)
    for field in ("primary_deployment_id", "fallback_deployment_id", "verifier_deployment_id",
                  "shadow_deployment_id"):
        if field in payload and payload[field]:
            setattr(route, field, uuid.UUID(payload[field]))
    if "require_verification" in payload:
        route.require_verification = payload["require_verification"]
    if "enabled" in payload:
        route.enabled = payload["enabled"]
    audit.record(db, action="model.route_updated", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="model_route", resource_id=capability)
    db.commit()
    return serialize(route)


@router.get("/usage")
def usage(principal: Principal = Depends(require_permission("model:read")),
          db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(ModelProvider).where(
        ModelProvider.tenant_id == principal.tenant_id)).scalars().all()
    return {
        "providers": [{"name": p.name, "kind": p.kind, "health": p.health,
                       "total_tokens": p.total_tokens, "total_requests": p.total_requests,
                       "total_cost_usd": round(p.total_cost_usd, 4),
                       "circuit_open": bool(p.circuit_open_until and
                                            p.circuit_open_until > datetime.now(UTC))}
                      for p in rows],
        "capabilities": ["fast_triage", "deep_investigator", "independent_critic",
                         "private_investigator", "detection_engineer", "malware_analyst",
                         "multimodal_analyst", "report_writer", "embedding_model",
                         "security_classifier", "response_planner"],
    }
