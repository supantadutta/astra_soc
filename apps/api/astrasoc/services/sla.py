"""SLA engine: due times from the tenant's contract, state, breaches, reporting.

* :func:`apply_sla` stamps ``sla_ack_due`` / ``sla_resolve_due`` from the
  tenant's effective SLA (tier defaults + contract overrides) at creation and
  whenever severity changes.
* :func:`sla_state` classifies an incident as ``met`` / ``on_track`` /
  ``at_risk`` (less than 25 % of the window left) / ``breached``.
* :func:`sweep_breaches` runs periodically: each newly breached target is
  recorded once, the incident's escalation level rises, and the customer,
  its provider chain and matching escalation contacts are notified.
* :func:`sla_report` computes per-tenant compliance for a period.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Incident, Tenant
from .tiers import effective_sla

CLOSED = ("resolved", "closed", "false_positive")


def apply_sla(db: Session, incident: Incident, tenant: Tenant | None = None) -> None:
    tenant = tenant or db.get(Tenant, incident.tenant_id)
    if tenant is None:
        return
    targets = effective_sla(tenant).get(incident.severity) or effective_sla(tenant)["medium"]
    base = incident.created_at or datetime.now(UTC)
    incident.sla_ack_due = base + timedelta(minutes=targets["ack"])
    incident.sla_resolve_due = base + timedelta(minutes=targets["resolve"])


def _target_state(due: datetime | None, done: datetime | None, start: datetime | None,
                  now: datetime) -> dict:
    if due is None:
        return {"due": None, "state": "n/a", "minutes_remaining": None}
    if done is not None:
        return {"due": due.isoformat(), "state": "met" if done <= due else "breached",
                "minutes_remaining": None, "completed_at": done.isoformat()}
    remaining = (due - now).total_seconds() / 60
    if remaining < 0:
        state = "breached"
    else:
        window = max(1.0, (due - (start or now)).total_seconds() / 60)
        state = "at_risk" if remaining < 0.25 * window else "on_track"
    return {"due": due.isoformat(), "state": state, "minutes_remaining": round(remaining, 1)}


def sla_state(inc: Incident, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    closed_at = inc.resolved_at if inc.status in CLOSED else None
    if inc.status in CLOSED and closed_at is None:
        closed_at = inc.updated_at
    ack = _target_state(inc.sla_ack_due, inc.acknowledged_at, inc.created_at, now)
    res = _target_state(inc.sla_resolve_due, closed_at, inc.created_at, now)
    order = ["breached", "at_risk", "on_track", "met", "n/a"]
    overall = min((ack["state"], res["state"]), key=order.index)
    return {"ack": ack, "resolve": res, "overall": overall,
            "escalation_level": inc.escalation_level or 0}


def mark_acknowledged(inc: Incident) -> None:
    if inc.acknowledged_at is None:
        inc.acknowledged_at = datetime.now(UTC)


def on_status_change(inc: Incident, new_status: str) -> None:
    now = datetime.now(UTC)
    if new_status in ("triaged", "investigating", "contained") and inc.acknowledged_at is None:
        inc.acknowledged_at = now
    if new_status == "investigating" and inc.investigated_at is None:
        inc.investigated_at = now
    if new_status == "contained" and inc.responded_at is None:
        inc.responded_at = now
    if new_status in CLOSED:
        inc.resolved_at = inc.resolved_at or now
        inc.acknowledged_at = inc.acknowledged_at or now
    elif inc.resolved_at is not None:
        inc.resolved_at = None  # reopened


def sweep_breaches(db: Session, now: datetime | None = None) -> int:
    """Record newly breached SLA targets and escalate. Idempotent."""
    from .notify import escalate_incident

    now = now or datetime.now(UTC)
    rows = db.execute(select(Incident).where(
        Incident.status.notin_(CLOSED),
        ((Incident.sla_ack_due < now) & Incident.acknowledged_at.is_(None)
         & Incident.sla_ack_breached_at.is_(None))
        | ((Incident.sla_resolve_due < now) & Incident.sla_resolve_breached_at.is_(None)),
    ).limit(500)).scalars().all()
    count = 0
    for inc in rows:
        kinds = []
        if inc.acknowledged_at is None and inc.sla_ack_due and inc.sla_ack_due < now \
                and inc.sla_ack_breached_at is None:
            inc.sla_ack_breached_at = now
            kinds.append("acknowledge")
        if inc.sla_resolve_due and inc.sla_resolve_due < now and inc.sla_resolve_breached_at is None:
            inc.sla_resolve_breached_at = now
            kinds.append("resolve")
        if not kinds:
            continue
        inc.escalation_level = (inc.escalation_level or 0) + 1
        escalate_incident(db, inc, reason=f"SLA breached ({', '.join(kinds)})",
                          category="sla_breach")
        count += 1
    db.flush()
    return count


def sla_report(db: Session, tenant_ids: list[uuid.UUID], start: datetime,
               end: datetime, scope: str | None = None) -> list[dict]:
    """Per-tenant SLA compliance for incidents created in [start, end)."""
    out = []
    now = datetime.now(UTC)
    for tid in tenant_ids:
        tenant = db.get(Tenant, tid)
        q = select(Incident).where(Incident.tenant_id == tid, Incident.created_at >= start,
                                   Incident.created_at < end)
        if scope:
            q = q.where(Incident.data_scope == scope)
        incs = db.execute(q).scalars().all()
        ack_met = ack_total = res_met = res_total = 0
        mtta: list[float] = []
        mttr: list[float] = []
        by_sev: dict[str, int] = {}
        for inc in incs:
            by_sev[inc.severity] = by_sev.get(inc.severity, 0) + 1
            st = sla_state(inc, now)
            if st["ack"]["state"] in ("met", "breached"):
                ack_total += 1
                ack_met += st["ack"]["state"] == "met"
            if st["resolve"]["state"] in ("met", "breached"):
                res_total += 1
                res_met += st["resolve"]["state"] == "met"
            if inc.acknowledged_at and inc.created_at:
                mtta.append(max(0.0, (inc.acknowledged_at - inc.created_at).total_seconds() / 60))
            if inc.resolved_at and inc.created_at:
                mttr.append(max(0.0, (inc.resolved_at - inc.created_at).total_seconds() / 60))
        breached_open = sum(1 for i in incs if sla_state(i, now)["overall"] == "breached"
                            and i.status not in CLOSED)
        out.append({
            "tenant_id": str(tid), "tenant": tenant.name if tenant else str(tid),
            "slug": tenant.slug if tenant else "", "service_tier": tenant.service_tier if tenant else "",
            "incidents": len(incs), "by_severity": by_sev,
            "ack_compliance": round(ack_met / ack_total, 3) if ack_total else None,
            "resolve_compliance": round(res_met / res_total, 3) if res_total else None,
            "ack_measured": ack_total, "resolve_measured": res_total,
            "mtta_minutes": round(sum(mtta) / len(mtta), 1) if mtta else None,
            "mttr_minutes": round(sum(mttr) / len(mttr), 1) if mttr else None,
            "open_breaches": breached_open,
        })
    return out
