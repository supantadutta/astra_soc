"""SOC Overview dashboard + Platform Health APIs (metrics for the command center)."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..config import settings
from ..db import get_db
from ..models import (
    AgentRun,
    Alert,
    ApprovalRequest,
    Connector,
    Incident,
    ModelProvider,
    ResponseAction,
)
from ..models.enums import ApprovalStatus, IncidentStatus
from ..seed.engine import generator_state
from ..services.events import bus
from ..services.mode import current_scope, get_mode

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _mins(a: datetime | None, b: datetime | None) -> float | None:
    if not a or not b:
        return None
    return round(abs((b - a).total_seconds()) / 60, 1)


@router.get("/overview")
def overview(principal: Principal = Depends(require_permission("incident:read")),
             db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    tid = principal.tenant_id
    incidents = db.execute(select(Incident).where(
        Incident.tenant_id == tid, Incident.data_scope == scope)).scalars().all()
    active = [i for i in incidents if i.status not in
              (IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value,
               IncidentStatus.FALSE_POSITIVE.value)]
    critical = [i for i in active if i.severity == "critical"]

    # Risk score: weighted blend of active incident business risk.
    risk = round(min(100, sum(i.business_risk for i in active) / max(1, len(active))) if active else 0, 1)

    # MTTA / MTTI / MTTR from timestamps.
    def avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None
    mtta = avg([_mins(i.created_at, i.acknowledged_at) for i in incidents])
    mtti = avg([_mins(i.acknowledged_at, i.investigated_at) for i in incidents])
    mttr = avg([_mins(i.created_at, i.resolved_at) for i in incidents])

    # Automation success rate.
    runs = db.execute(select(AgentRun).where(
        AgentRun.tenant_id == tid, AgentRun.data_scope == scope)).scalars().all()
    ok_runs = sum(1 for r in runs if r.status == "succeeded")
    automation_rate = round(ok_runs / len(runs), 3) if runs else None

    # ATT&CK tactic distribution.
    tactic_counter: Counter = Counter()
    for i in active:
        tactic_counter.update(i.attack_tactics or [])

    # Alerts/sec from generator + recent alerts.
    recent_alerts = db.execute(select(func.count()).select_from(Alert).where(
        Alert.tenant_id == tid, Alert.data_scope == scope,
        Alert.created_at > datetime.now(UTC) - timedelta(minutes=5))).scalar() or 0
    gen = generator_state()

    pending_approvals = db.execute(select(func.count()).select_from(ApprovalRequest).where(
        ApprovalRequest.tenant_id == tid,
        ApprovalRequest.status == ApprovalStatus.PENDING.value)).scalar() or 0

    providers = db.execute(select(ModelProvider).where(ModelProvider.tenant_id == tid)).scalars().all()
    connectors = db.execute(select(Connector).where(Connector.tenant_id == tid)).scalars().all()

    return {
        "mode": get_mode(db).to_dict(),
        "scope": scope,
        "kpis": {
            "global_risk_score": risk,
            "active_incidents": len(active),
            "critical_incidents": len(critical),
            "alerts_per_second": gen.get("aps", 0),
            "alerts_last_5m": recent_alerts,
            "mtta_minutes": mtta, "mtti_minutes": mtti, "mttr_minutes": mttr,
            "automation_success_rate": automation_rate,
            "pending_approvals": pending_approvals,
            "analyst_workload": len(active),
        },
        "attack_tactics": [{"tactic": k, "count": v} for k, v in tactic_counter.most_common()],
        "severity_distribution": _dist(active, "severity"),
        "status_distribution": _dist(incidents, "status"),
        "ai_health": [{"name": p.name, "kind": p.kind, "health": p.health} for p in providers],
        "connector_health": {
            "total": len(connectors),
            "enabled": sum(1 for c in connectors if c.enabled),
            "write_capable": sum(1 for c in connectors if c.can_write),
        },
        "top_risky_entities": _top_entities(db, tid, scope),
        "top_targeted_assets": _top_assets(active),
    }


def _dist(items, field):
    c = Counter(getattr(i, field) for i in items)
    return [{"key": k, "count": v} for k, v in c.items()]


def _top_entities(db, tid, scope):
    from ..models import Entity
    rows = db.execute(select(Entity).where(
        Entity.tenant_id == tid, Entity.data_scope == scope,
        Entity.kind.in_(["user", "account"])).order_by(
        Entity.risk_score.desc()).limit(5)).scalars().all()
    return [{"value": e.value, "display": e.display_name, "risk": e.risk_score} for e in rows]


def _top_assets(active):
    c: Counter = Counter()
    for i in active:
        c.update(i.affected_hosts or [])
    return [{"host": h, "incidents": n} for h, n in c.most_common(5)]


@router.get("/trends")
def trends(principal: Principal = Depends(require_permission("incident:read")),
           db: Session = Depends(get_db), days: int = 14) -> dict:
    scope = current_scope(db)
    incidents = db.execute(select(Incident).where(
        Incident.tenant_id == principal.tenant_id, Incident.data_scope == scope)).scalars().all()
    buckets: dict[str, dict] = {}
    now = datetime.now(UTC)
    for d in range(days):
        day = (now - timedelta(days=days - 1 - d)).strftime("%Y-%m-%d")
        buckets[day] = {"date": day, "incidents": 0, "risk": 0}
    for i in incidents:
        day = i.created_at.strftime("%Y-%m-%d")
        if day in buckets:
            buckets[day]["incidents"] += 1
            buckets[day]["risk"] = max(buckets[day]["risk"], i.business_risk)
    return {"incident_trend": list(buckets.values())}


@router.get("/live-events")
def live_events(principal: Principal = Depends(require_permission("incident:read")),
                db: Session = Depends(get_db), limit: int = 30) -> dict:
    scope = current_scope(db)
    events = bus.recent(scope, limit=limit)
    return {"events": [{"type": e.type, "ts": e.ts, **e.data} for e in events]}


# --- Platform Health (spec §23) ------------------------------------------
health_router = APIRouter(prefix="/api/v1/platform", tags=["platform-health"])


@health_router.get("/health")
def platform_health(principal: Principal = Depends(require_permission("health:read")),
                    db: Session = Depends(get_db)) -> dict:
    tid = principal.tenant_id
    providers = db.execute(select(ModelProvider).where(ModelProvider.tenant_id == tid)).scalars().all()
    connectors = db.execute(select(Connector).where(Connector.tenant_id == tid)).scalars().all()
    failed_actions = db.execute(select(func.count()).select_from(ResponseAction).where(
        ResponseAction.tenant_id == tid, ResponseAction.status == "failed")).scalar() or 0
    return {
        "mode": get_mode(db).to_dict(),
        "services": [
            {"name": "api", "state": "healthy"},
            {"name": "database", "state": "healthy",
             "detail": "sqlite" if settings.is_sqlite else "postgresql"},
            {"name": "event_bus", "state": "healthy",
             "detail": f"{bus.subscriber_count} subscribers, {bus.total_published} published"},
            {"name": "demo_generator", "state": "healthy" if generator_state()["running"]
             else "degraded", "detail": generator_state()},
        ],
        "dependencies": [
            {"name": "redis", "state": "not_configured" if not settings.redis_url else "configured"},
            {"name": "clickhouse", "state": "not_configured" if not settings.clickhouse_url else "configured"},
            {"name": "neo4j", "state": "not_configured" if not settings.neo4j_url else "configured"},
            {"name": "opensearch", "state": "not_configured" if not settings.opensearch_url else "configured"},
            {"name": "kafka", "state": "not_configured" if not settings.kafka_brokers else "configured"},
            {"name": "temporal", "state": "not_configured" if not settings.temporal_host else "configured"},
            {"name": "opa", "state": "not_configured" if not settings.opa_url else "configured"},
        ],
        "ai_providers": [{"name": p.name, "health": p.health,
                          "circuit_open": bool(p.circuit_open_until and
                                               p.circuit_open_until > datetime.now(UTC))}
                         for p in providers],
        "connectors": [{"name": c.name, "enabled": c.enabled, "mock": c.use_mock} for c in connectors],
        "queues": {"failed_response_actions": failed_actions,
                   "dead_letter": 0, "retry_queue": 0},
    }
