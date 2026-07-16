"""Read-only investigation tool implementations.

Each function takes (db, tenant_id, scope, args) and returns a JSON-safe dict.
They only ever READ, and only within the caller's tenant + data scope. Response
(production-changing) tools are NOT here — they are executed exclusively through
the response gateway after policy + approval.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    Alert,
    Entity,
    EntityRelationship,
    Evidence,
    Incident,
    SecurityEvent,
    ThreatIndicator,
    TimelineEntry,
)
from ...schemas.common import serialize, serialize_many


def _incident(db: Session, tenant_id, scope, args) -> dict:
    inc = db.get(Incident, uuid.UUID(args["incident_id"]))
    if not inc or inc.tenant_id != tenant_id or inc.data_scope != scope:
        return {"error": "not_found"}
    return serialize(inc)


def _list_alerts(db: Session, tenant_id, scope, args) -> dict:
    q = select(Alert).where(Alert.tenant_id == tenant_id, Alert.data_scope == scope)
    if args.get("incident_id"):
        q = q.where(Alert.incident_id == uuid.UUID(args["incident_id"]))
    rows = db.execute(q.limit(50)).scalars().all()
    return {"alerts": serialize_many(rows)}


def _get_alert(db: Session, tenant_id, scope, args) -> dict:
    a = db.get(Alert, uuid.UUID(args["alert_id"]))
    if not a or a.tenant_id != tenant_id or a.data_scope != scope:
        return {"error": "not_found"}
    return serialize(a)


def _list_evidence(db: Session, tenant_id, scope, args) -> dict:
    rows = db.execute(
        select(Evidence).where(
            Evidence.tenant_id == tenant_id, Evidence.data_scope == scope,
            Evidence.incident_id == uuid.UUID(args["incident_id"]))
    ).scalars().all()
    return {"evidence": serialize_many(rows)}


def _get_timeline(db: Session, tenant_id, scope, args) -> dict:
    rows = db.execute(
        select(TimelineEntry).where(
            TimelineEntry.tenant_id == tenant_id, TimelineEntry.data_scope == scope,
            TimelineEntry.incident_id == uuid.UUID(args["incident_id"]))
        .order_by(TimelineEntry.occurred_at)
    ).scalars().all()
    return {"timeline": serialize_many(rows)}


def _search_events(db: Session, tenant_id, scope, args) -> dict:
    q = select(SecurityEvent).where(
        SecurityEvent.tenant_id == tenant_id, SecurityEvent.data_scope == scope)
    if args.get("host"):
        q = q.where(SecurityEvent.host_name == args["host"])
    if args.get("user"):
        q = q.where(SecurityEvent.user_name == args["user"])
    rows = db.execute(q.order_by(SecurityEvent.event_time.desc()).limit(args.get("limit", 25))).scalars().all()
    return {"events": serialize_many(rows), "count": len(rows)}


def _get_entity(db: Session, tenant_id, scope, args) -> dict:
    q = select(Entity).where(Entity.tenant_id == tenant_id, Entity.data_scope == scope)
    if args.get("entity_id"):
        q = q.where(Entity.id == uuid.UUID(args["entity_id"]))
    elif args.get("value"):
        q = q.where(Entity.value == args["value"])
    row = db.execute(q.limit(1)).scalar_one_or_none()
    return serialize(row) if row else {"error": "not_found"}


def _get_entity_graph(db: Session, tenant_id, scope, args) -> dict:
    inc_id = uuid.UUID(args["incident_id"]) if args.get("incident_id") else None
    rq = select(EntityRelationship).where(
        EntityRelationship.tenant_id == tenant_id, EntityRelationship.data_scope == scope)
    if inc_id:
        rq = rq.where(EntityRelationship.incident_id == inc_id)
    rels = db.execute(rq.limit(200)).scalars().all()
    ids: set[uuid.UUID] = set()
    for r in rels:
        ids.add(r.src_entity_id)
        ids.add(r.dst_entity_id)
    ents = db.execute(select(Entity).where(Entity.id.in_(ids))).scalars().all() if ids else []
    return {
        "nodes": serialize_many(ents),
        "edges": [{"source": str(r.src_entity_id), "target": str(r.dst_entity_id),
                   "type": r.relationship_type, "weight": r.weight} for r in rels],
    }


def _lookup_ioc(db: Session, tenant_id, scope, args) -> dict:
    value = args.get("value", "")
    row = db.execute(
        select(ThreatIndicator).where(
            ThreatIndicator.tenant_id == tenant_id, ThreatIndicator.value == value)
    ).scalar_one_or_none()
    if row:
        return {"found": True, "indicator": serialize(row)}
    return {"found": False, "value": value,
            "note": "No matching indicator in the configured threat-intel sources."}


def _get_user_context(db: Session, tenant_id, scope, args) -> dict:
    row = db.execute(
        select(Entity).where(
            Entity.tenant_id == tenant_id, Entity.data_scope == scope,
            Entity.kind.in_(["user", "account"]), Entity.value == args.get("user", ""))
    ).scalar_one_or_none()
    return serialize(row) if row else {"error": "not_found", "user": args.get("user")}


def _stub(name: str) -> Callable:
    def _fn(db, tenant_id, scope, args) -> dict:
        return {
            "tool": name, "status": "simulated",
            "note": f"'{name}' returns simulated read-only data in demo mode. In live mode this "
                    f"queries the corresponding connector (read-only).",
            "args": args,
        }
    return _fn


# Registry: tool_key -> implementation. Response tools intentionally absent.
READ_TOOL_IMPLS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_incident": _incident,
    "list_alerts": _list_alerts,
    "get_alert": _get_alert,
    "list_evidence": _list_evidence,
    "get_timeline": _get_timeline,
    "search_events": _search_events,
    "get_entity": _get_entity,
    "get_entity_graph": _get_entity_graph,
    "lookup_ioc": _lookup_ioc,
    "get_user_context": _get_user_context,
    "list_signins": _stub("list_signins"),
    "get_endpoint_detail": _stub("get_endpoint_detail"),
    "list_processes": _stub("list_processes"),
    "get_cloud_activity": _stub("get_cloud_activity"),
    "get_email_detail": _stub("get_email_detail"),
    "search_threat_intel": _stub("search_threat_intel"),
    "get_file_reputation": _stub("get_file_reputation"),
    "resolve_domain": _stub("resolve_domain"),
}
