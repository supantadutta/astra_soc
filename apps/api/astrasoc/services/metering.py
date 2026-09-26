"""Usage metering per tenant and month — the basis for MSSP billing.

Counters are incremented at the point where the billable thing actually
happens (event ingested, alert raised, agent run, LLM tokens, response
action executed, report generated). They are never estimated.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import UsageCounter

METRICS = {
    "events_ingested": "Security events ingested",
    "alerts": "Alerts raised by detections",
    "incidents": "Incidents opened",
    "agent_runs": "AI agent runs",
    "llm_tokens": "LLM tokens consumed",
    "response_actions": "Response actions executed",
    "reports": "Reports generated",
}


def period_of(dt: datetime | None = None) -> str:
    return (dt or datetime.now(UTC)).strftime("%Y-%m")


def record(db: Session, tenant_id: uuid.UUID, metric: str, quantity: float = 1.0,
           when: datetime | None = None) -> None:
    if metric not in METRICS or not quantity:
        return
    period = period_of(when)
    row = db.execute(select(UsageCounter).where(
        UsageCounter.tenant_id == tenant_id, UsageCounter.period == period,
        UsageCounter.metric == metric)).scalar_one_or_none()
    if row is None:
        # Nested transaction so a concurrent insert of the same key does not
        # poison the caller's transaction.
        try:
            with db.begin_nested():
                db.add(UsageCounter(tenant_id=tenant_id, period=period, metric=metric,
                                    quantity=float(quantity)))
            return
        except Exception:  # noqa: BLE001 — lost the race; fall through to update
            row = db.execute(select(UsageCounter).where(
                UsageCounter.tenant_id == tenant_id, UsageCounter.period == period,
                UsageCounter.metric == metric)).scalar_one()
    row.quantity = (row.quantity or 0.0) + float(quantity)


def usage_for(db: Session, tenant_ids: list[uuid.UUID], period: str) -> dict[uuid.UUID, dict]:
    out: dict[uuid.UUID, dict] = {tid: {m: 0.0 for m in METRICS} for tid in tenant_ids}
    if not tenant_ids:
        return out
    for row in db.execute(select(UsageCounter).where(
            UsageCounter.tenant_id.in_(tenant_ids), UsageCounter.period == period)).scalars():
        out[row.tenant_id][row.metric] = row.quantity
    return out
