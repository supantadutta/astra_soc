"""Notifications and escalation across the MSSP hierarchy.

In-app notifications are always created. Out-of-band delivery to escalation
contacts goes through the tenant's (or, failing that, its provider's) enabled
write-capable comms connector (email webhook, Slack, Teams). The delivery
status is recorded truthfully:

* ``simulated``      — the tenant is in DEMO mode; nothing was sent;
* ``not_configured`` — no enabled, non-mock comms connector exists;
* ``sent`` / ``failed`` — the real adapter's reported outcome.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Connector, Incident, Notification, Tenant
from .events import Event, bus
from .mode import current_scope

COMMS_KINDS = ("email_webhook", "slack", "microsoft_teams")


def notify(db: Session, *, tenant_id: uuid.UUID, title: str, body: str = "",
           level: str = "info", category: str = "general", link: str | None = None,
           subject_tenant_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None,
           scope: str | None = None) -> Notification:
    scope = scope or current_scope(db, subject_tenant_id or tenant_id)
    n = Notification(tenant_id=tenant_id, user_id=user_id, level=level, title=title[:200],
                     body=body, category=category, link=link, data_scope=scope,
                     subject_tenant_id=subject_tenant_id or tenant_id)
    db.add(n)
    db.flush()
    bus.publish_soon(Event(type="notification.created", scope=scope, tenant_id=str(tenant_id),
                           data={"id": str(n.id), "title": n.title, "level": level,
                                 "category": category, "link": link}))
    return n


def provider_chain(db: Session, tenant: Tenant) -> list[Tenant]:
    out: list[Tenant] = []
    seen: set[uuid.UUID] = set()
    cur = db.get(Tenant, tenant.parent_id) if tenant.parent_id else None
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        out.append(cur)
        cur = db.get(Tenant, cur.parent_id) if cur.parent_id else None
    return out


def _comms_connector(db: Session, tenants: list[Tenant]) -> Connector | None:
    for t in tenants:
        conn = db.execute(select(Connector).where(
            Connector.tenant_id == t.id, Connector.kind.in_(COMMS_KINDS),
            Connector.enabled.is_(True), Connector.can_write.is_(True),
            Connector.use_mock.is_(False))).scalars().first()
        if conn is not None:
            return conn
    return None


def deliver_to_contact(db: Session, tenant: Tenant, contact: dict, *, title: str, body: str,
                       category: str, link: str | None) -> Notification:
    """Create an out-of-band notification for an escalation contact and
    attempt delivery, recording the true outcome."""
    from .connectors.registry import get_adapter

    scope = current_scope(db, tenant.id)
    recipient = contact.get("email") or contact.get("phone") or contact.get("name", "contact")
    n = Notification(tenant_id=tenant.id, level="critical", title=title[:200], body=body,
                     category=category, link=link, data_scope=scope, channel="email",
                     recipient=str(recipient)[:255], subject_tenant_id=tenant.id)
    if scope == "DEMO":
        n.delivery_status = "simulated"
        n.delivery_detail = "DEMO mode — no message was sent."
    else:
        conn = _comms_connector(db, [tenant, *provider_chain(db, tenant)])
        if conn is None:
            n.delivery_status = "not_configured"
            n.delivery_detail = "No enabled, non-mock comms connector (email/Slack/Teams)."
        else:
            try:
                out = get_adapter(conn).execute_action("notify_team", {
                    "recipient": recipient, "title": title, "body": body,
                    "tenant": tenant.slug, "category": category})
                n.delivery_status = "sent" if out.get("success") else "failed"
                n.delivery_detail = str(out.get("summary") or out.get("error") or "")[:500]
            except Exception as exc:  # noqa: BLE001 — record the truth, never raise
                n.delivery_status = "failed"
                n.delivery_detail = str(exc)[:500]
    db.add(n)
    db.flush()
    return n


def escalate_incident(db: Session, inc: Incident, *, reason: str, category: str) -> None:
    tenant = db.get(Tenant, inc.tenant_id)
    if tenant is None:
        return
    title = f"[{tenant.slug}] {inc.key} {reason}"
    body = f"{inc.title} — severity {inc.severity}, escalation level {inc.escalation_level}."
    link = f"/incidents/{inc.id}"
    level = "critical" if inc.severity in ("critical", "high") or category == "sla_breach" else "warning"
    notify(db, tenant_id=tenant.id, title=title, body=body, level=level, category=category,
           link=link, scope=inc.data_scope)
    for provider in provider_chain(db, tenant):
        notify(db, tenant_id=provider.id, subject_tenant_id=tenant.id, title=title, body=body,
               level=level, category=category, link=link, scope=inc.data_scope)
    for contact in tenant.contacts or []:
        wants = set(contact.get("notify_on") or [])
        level_ok = int(contact.get("level", 1)) <= max(1, inc.escalation_level or 1)
        if (category in wants or inc.severity in wants) and level_ok:
            deliver_to_contact(db, tenant, contact, title=title, body=body,
                               category=category, link=link)
