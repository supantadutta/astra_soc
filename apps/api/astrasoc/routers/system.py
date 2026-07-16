"""System endpoints: health, dependency status, and mode management."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import get_current_principal, require_permission
from ..config import settings
from ..db import get_db
from ..models import Alert, Connector, Incident, ModelProvider
from ..services import audit
from ..services.events import bus
from ..services.mode import current_scope, get_mode, live_readiness, set_mode

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health/live")
def liveness() -> dict:
    return {"status": "ok", "ts": datetime.now(UTC).isoformat()}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)) -> dict:
    """Dependency health. Reports real state — unconfigured deps say so."""
    deps = []

    # Primary database (always required).
    try:
        db.execute(select(func.count()).select_from(Alert))
        deps.append({"name": "database", "state": "healthy",
                     "kind": "sqlite" if settings.is_sqlite else "postgresql", "required": True})
    except Exception as exc:  # pragma: no cover
        deps.append({"name": "database", "state": "unhealthy", "error": str(exc), "required": True})

    optional = [
        ("redis", settings.redis_url), ("clickhouse", settings.clickhouse_url),
        ("neo4j", settings.neo4j_url), ("opensearch", settings.opensearch_url),
        ("kafka", settings.kafka_brokers), ("temporal", settings.temporal_host),
        ("opa", settings.opa_url), ("vault", settings.vault_addr),
    ]
    for name, url in optional:
        deps.append({
            "name": name,
            "state": "not_configured" if not url else "configured",
            "required": False,
            "detail": None if url else "Optional enterprise dependency. Platform runs degraded-but-functional without it.",
        })

    required_ok = all(d["state"] == "healthy" for d in deps if d.get("required"))
    return {
        "status": "ok" if required_ok else "degraded",
        "mode": get_mode(db).to_dict(),
        "dependencies": deps,
        "event_bus": {"subscribers": bus.subscriber_count, "published": bus.total_published},
    }


@router.get("/mode")
def read_mode(db: Session = Depends(get_db)) -> dict:
    return get_mode(db).to_dict()


@router.get("/mode/readiness")
def read_readiness(
    principal: Principal = Depends(require_permission("mode:manage")),
    db: Session = Depends(get_db),
) -> dict:
    checks = live_readiness(db)
    required_failed = [c.name for c in checks if c.required and not c.passed]
    return {
        "ready": len(required_failed) == 0,
        "required_failed": required_failed,
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail, "required": c.required}
            for c in checks
        ],
    }


@router.post("/mode/switch")
def switch_mode(
    request: Request,
    payload: dict = Body(...),
    principal: Principal = Depends(require_permission("mode:manage")),
    db: Session = Depends(get_db),
) -> dict:
    """Switch operating mode. DEMO->LIVE requires explicit confirmation and
    passing required readiness checks. Enforced server-side."""
    target = str(payload.get("mode", "")).upper()
    if target not in ("DEMO", "LIVE"):
        raise HTTPException(400, detail="mode must be DEMO or LIVE")

    if target == "LIVE":
        if not settings.allow_live_mode:
            raise HTTPException(403, detail="Live mode is disabled for this deployment.")
        if not payload.get("confirm"):
            raise HTTPException(400, detail={
                "error": "confirmation_required",
                "message": "Switching to LIVE requires confirm=true after reviewing readiness.",
            })
        checks = live_readiness(db)
        failed = [c.name for c in checks if c.required and not c.passed]
        if failed:
            raise HTTPException(400, detail={
                "error": "readiness_failed",
                "message": "Required readiness checks failed.",
                "failed": failed,
            })

    state = set_mode(
        db, target, changed_by=principal.email,
        ai_enabled=payload.get("ai_enabled"),
        llm_strategy=payload.get("llm_strategy"),
    )
    audit.record(db, action="mode.switch", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, actor_label=principal.email,
                 resource_type="operating_mode", resource_id=target,
                 data_scope=target, detail={"to": target})
    db.commit()
    return state.to_dict()


@router.get("/system/summary")
def system_summary(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    scope = current_scope(db)
    incidents = db.execute(
        select(func.count()).select_from(Incident).where(
            Incident.tenant_id == principal.tenant_id, Incident.data_scope == scope)
    ).scalar() or 0
    alerts = db.execute(
        select(func.count()).select_from(Alert).where(
            Alert.tenant_id == principal.tenant_id, Alert.data_scope == scope)
    ).scalar() or 0
    connectors = db.execute(
        select(func.count()).select_from(Connector).where(
            Connector.tenant_id == principal.tenant_id, Connector.enabled.is_(True))
    ).scalar() or 0
    providers = db.execute(
        select(func.count()).select_from(ModelProvider).where(
            ModelProvider.tenant_id == principal.tenant_id, ModelProvider.enabled.is_(True))
    ).scalar() or 0
    return {
        "mode": get_mode(db).to_dict(),
        "scope": scope,
        "counts": {"incidents": incidents, "alerts": alerts,
                   "enabled_connectors": connectors, "enabled_providers": providers},
        "version": "0.1.0",
    }
