"""Ingestion → deterministic detection → alert → correlation pipeline.

Every event, from the demo generator, a connector sync or the ingestion API,
goes through the same path:

1. **Normalise & store** a :class:`SecurityEvent` (tenant + scope), meter it.
2. **Detect**: evaluate every *deployed, enabled* rule of the tenant with the
   deterministic matcher (no model involved). Per-rule exceptions suppress
   known-benign matches.
3. **Alert** with de-duplication: repeat matches of the same rule on the same
   entity within a 30-minute bucket extend the existing alert instead of
   creating noise.
4. **Correlate**: attach the alert to an open incident in the same tenant and
   scope that shares a host or user and was active in the last 24 h;
   otherwise open a new incident for high/critical alerts. The triggering
   event becomes CONFIRMED_FACT evidence (telemetry, with its event id as
   the source reference) and a timeline entry.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.security import content_hash
from ..models import (
    Alert,
    DetectionRule,
    Entity,
    EntityRelationship,
    Evidence,
    Incident,
    IncidentAlert,
    SecurityEvent,
    Tenant,
    TimelineEntry,
)
from ..models.enums import AlertStatus, EvidenceKind, IncidentStatus
from .detection import evaluate_matcher, event_payload, tenant_iocs
from .events import Event, bus
from .metering import record as meter
from .sla import CLOSED, apply_sla

_SEV_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_RULE_CONFIDENCE = {"critical": 0.85, "high": 0.75, "medium": 0.6, "low": 0.45, "info": 0.3}
CORRELATION_WINDOW = timedelta(hours=24)
DEDUP_BUCKET_MIN = 30

_OCSF = {
    "Process create": (1007, "Process Activity"), "Process access": (1007, "Process Activity"),
    "Network connection": (4001, "Network Activity"), "DNS query": (4003, "DNS Activity"),
    "Sign-in": (3002, "Authentication"), "File write": (1001, "File System Activity"),
    "Group membership change": (3005, "Account Change"),
}


# Vendor spellings (Sysmon / Windows Security / ECS / common EDR exports)
# mapped onto the canonical activity names detections are written against.
_ACTIVITY_ALIASES = {
    "process_creation": "Process create", "process_create": "Process create",
    "processcreate": "Process create", "process": "Process create",
    "process_start": "Process create", "sysmon:1": "Process create", "4688": "Process create",
    "process_access": "Process access", "sysmon:10": "Process access",
    "network_connection": "Network connection", "network": "Network connection",
    "connection": "Network connection", "sysmon:3": "Network connection",
    "dns": "DNS query", "dns_query": "DNS query", "sysmon:22": "DNS query",
    "sign_in": "Sign-in", "signin": "Sign-in", "login": "Sign-in", "logon": "Sign-in",
    "authentication": "Sign-in", "4624": "Sign-in",
    "file_write": "File write", "file_create": "File write", "sysmon:11": "File write",
    "group_membership_change": "Group membership change", "4728": "Group membership change",
    "4732": "Group membership change", "4756": "Group membership change",
}

# Field aliases -> canonical field names used by detection matchers. The
# canonical name wins when both are present; originals stay in the payload.
_FIELD_ALIASES = {
    "cmdline": ("command_line", "commandline", "CommandLine", "process.command_line",
                "process_command_line"),
    "target_process": ("target_image", "TargetImage", "target.process.name"),
    "query": ("dns_query", "QueryName", "dns.question.name"),
    "group": ("group_name", "TargetUserName", "group.name"),
    "process_name": ("image", "Image", "process.name", "process.executable"),
    "parent_process": ("parent_image", "ParentImage", "process.parent.name"),
}


def _canonical_activity(value: str) -> str:
    if value in _OCSF:
        return value
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    return _ACTIVITY_ALIASES.get(key, value)


def _with_field_aliases(raw: dict) -> dict:
    out = dict(raw)
    for canonical, aliases in _FIELD_ALIASES.items():
        if out.get(canonical) in (None, ""):
            for a in aliases:
                if out.get(a) not in (None, ""):
                    out[canonical] = out[a]
                    break
    return out


def normalize(raw: dict) -> dict:
    """Map a loosely-structured event onto the normalized columns. Common
    vendor field / activity spellings are canonicalised; unknown keys are
    kept in the OCSF payload so rules can still match them."""
    raw = _with_field_aliases(raw)
    activity = _canonical_activity(
        str(raw.get("activity") or raw.get("action") or raw.get("event_type") or "unknown"))[:120]
    cls = _OCSF.get(activity, (0, raw.get("category", "Other")))
    ts = raw.get("event_time") or raw.get("ts") or raw.get("time")
    try:
        when = datetime.fromisoformat(str(ts)) if ts else datetime.now(UTC)
    except ValueError:
        when = datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    known = {"activity", "action", "event_type", "event_time", "ts", "time", "severity", "source",
             "host", "host_name", "user", "user_name", "src_ip", "dst_ip", "category"}
    ocsf = {k: v for k, v in raw.items() if k not in known}
    sev = str(raw.get("severity", "info")).lower()
    return {
        "source": str(raw.get("source", "ingest"))[:80], "event_time": when,
        "activity": activity, "severity": sev if sev in _SEV_RANK else "info",
        "host_name": raw.get("host_name") or raw.get("host"),
        "user_name": raw.get("user_name") or raw.get("user"),
        "src_ip": raw.get("src_ip"), "dst_ip": raw.get("dst_ip"),
        "ocsf_class_uid": cls[0], "ocsf_category": cls[1], "ocsf": ocsf,
    }


class DetectionContext:
    """Per-batch cache of a tenant's deployed rules and IOC set."""

    def __init__(self, db: Session, tenant_id: uuid.UUID) -> None:
        self.rules = db.execute(select(DetectionRule).where(
            DetectionRule.tenant_id == tenant_id, DetectionRule.enabled.is_(True),
            DetectionRule.status == "deployed")).scalars().all()
        self.iocs = tenant_iocs(db, tenant_id)


def _excepted(rule: DetectionRule, payload: dict) -> bool:
    for exc in rule.exceptions or []:
        if isinstance(exc, dict) and exc and all(
                str(payload.get(k) or (payload.get("ocsf") or {}).get(k) or "").lower() == str(v).lower()
                for k, v in exc.items()):
            return True
    return False


def ingest_event(db: Session, tenant_id: uuid.UUID, scope: str, raw: dict,
                 ctx: DetectionContext | None = None, connector_id: uuid.UUID | None = None
                 ) -> tuple[SecurityEvent, list[Alert]]:
    fields = normalize(raw)
    ev = SecurityEvent(tenant_id=tenant_id, data_scope=scope, connector_id=connector_id,
                       raw={k: v for k, v in raw.items()}, **fields)
    db.add(ev)
    db.flush()
    meter(db, tenant_id, "events_ingested")
    ctx = ctx or DetectionContext(db, tenant_id)
    payload = event_payload(ev)
    alerts = []
    for rule in ctx.rules:
        if evaluate_matcher(rule.matcher, payload, {"iocs": ctx.iocs}) and not _excepted(rule, payload):
            alerts.append(_raise_alert(db, tenant_id, scope, rule, ev))
    bus.publish_soon(Event(type="event.ingested", scope=scope, tenant_id=str(tenant_id), data={
        "source": ev.source, "activity": ev.activity, "severity": ev.severity,
        "host": ev.host_name, "simulated": scope == "DEMO"}))
    return ev, [a for a in alerts if a is not None]


def _raise_alert(db: Session, tenant_id: uuid.UUID, scope: str, rule: DetectionRule,
                 ev: SecurityEvent) -> Alert | None:
    entity = ev.host_name or ev.user_name or ev.src_ip or "unknown"
    bucket = ev.event_time.replace(minute=(ev.event_time.minute // DEDUP_BUCKET_MIN) * DEDUP_BUCKET_MIN,
                                   second=0, microsecond=0)
    dedup = f"{rule.key}:{entity}:{bucket.isoformat()}"[:200]
    existing = db.execute(select(Alert).where(
        Alert.tenant_id == tenant_id, Alert.data_scope == scope, Alert.dedup_key == dedup,
        Alert.status.notin_([AlertStatus.CLOSED.value, AlertStatus.SUPPRESSED.value]))).scalars().first()
    rule.trigger_count = (rule.trigger_count or 0) + 1
    rule.last_triggered_at = datetime.now(UTC)
    if existing is not None:
        existing.event_ids = [*(existing.event_ids or []), str(ev.id)][-200:]
        return None
    confidence = _RULE_CONFIDENCE.get(rule.severity, 0.6)
    alert = Alert(
        tenant_id=tenant_id, data_scope=scope,
        title=f"{rule.name} on {entity}", description=rule.description or rule.name,
        source=ev.source, detection_rule_id=rule.id, severity=rule.severity,
        status=AlertStatus.NEW.value, confidence=confidence,
        risk_score=round(20 * _SEV_RANK.get(rule.severity, 2) * confidence + 10, 1),
        attack_techniques=list(rule.attack_techniques or []),
        observables={"host": ev.host_name, "user": ev.user_name, "src_ip": ev.src_ip,
                     "dst_ip": ev.dst_ip},
        dedup_key=dedup, event_ids=[str(ev.id)],
    )
    db.add(alert)
    db.flush()
    meter(db, tenant_id, "alerts")
    bus.publish_soon(Event(type="alert.created", scope=scope, tenant_id=str(tenant_id), data={
        "alert_id": str(alert.id), "title": alert.title, "severity": alert.severity,
        "rule": rule.key, "simulated": scope == "DEMO"}))
    correlate(db, alert, ev, rule)
    return alert


def _upsert_entity(db: Session, tenant_id, scope, kind: str, value: str | None) -> Entity | None:
    if not value:
        return None
    ent = db.execute(select(Entity).where(
        Entity.tenant_id == tenant_id, Entity.data_scope == scope, Entity.kind == kind,
        Entity.value == value)).scalars().first()
    now = datetime.now(UTC)
    if ent is None:
        ent = Entity(tenant_id=tenant_id, data_scope=scope, kind=kind, value=value,
                     display_name=value, first_seen=now, last_seen=now, is_internal=kind != "ip",
                     enrichment={"source": "detection_pipeline"})
        db.add(ent)
        db.flush()
    else:
        ent.last_seen = now
    return ent


def _next_key(db: Session, tenant_id: uuid.UUID) -> str:
    count = db.execute(select(func.count()).select_from(Incident).where(
        Incident.tenant_id == tenant_id)).scalar() or 0
    return f"INC-{count + 1:06d}"


def correlate(db: Session, alert: Alert, ev: SecurityEvent, rule: DetectionRule) -> Incident | None:
    tid, scope = alert.tenant_id, alert.data_scope
    since = datetime.now(UTC) - CORRELATION_WINDOW
    host, user = ev.host_name, ev.user_name
    candidates = db.execute(select(Incident).where(
        Incident.tenant_id == tid, Incident.data_scope == scope, Incident.status.notin_(CLOSED),
        Incident.updated_at >= since).order_by(Incident.updated_at.desc()).limit(200)).scalars().all()
    inc = next((i for i in candidates
                if (host and host in (i.affected_hosts or [])) or (user and user in (i.affected_users or []))),
               None)
    reason = None
    if inc is not None:
        reason = f"Shared {'host ' + host if host and host in (inc.affected_hosts or []) else 'user ' + str(user)}"
        if _SEV_RANK.get(alert.severity, 0) > _SEV_RANK.get(inc.severity, 0):
            inc.severity = alert.severity
            apply_sla(db, inc)
        inc.attack_techniques = sorted({*(inc.attack_techniques or []), *(alert.attack_techniques or [])})
        if host and host not in (inc.affected_hosts or []):
            inc.affected_hosts = [*(inc.affected_hosts or []), host]
        if user and user not in (inc.affected_users or []):
            inc.affected_users = [*(inc.affected_users or []), user]
        inc.updated_at = datetime.now(UTC)
    elif _SEV_RANK.get(alert.severity, 0) >= _SEV_RANK["high"]:
        inc = Incident(
            tenant_id=tid, data_scope=scope, key=_next_key(db, tid),
            title=alert.title, severity=alert.severity, status=IncidentStatus.NEW.value,
            summary=f"Opened automatically by detection '{rule.name}'. {rule.description or ''}".strip(),
            confidence=alert.confidence, business_risk=alert.risk_score, risk_score=alert.risk_score,
            attack_techniques=list(alert.attack_techniques or []),
            affected_hosts=[host] if host else [], affected_users=[user] if user else [],
            related_ips=[x for x in (ev.src_ip, ev.dst_ip) if x],
            tags=["auto-correlated", f"rule:{rule.key}"],
        )
        db.add(inc)
        db.flush()
        apply_sla(db, inc)
        meter(db, tid, "incidents")
        reason = "New incident from high-severity detection"
    else:
        return None  # low/medium alerts wait in the triage queue

    alert.incident_id = inc.id
    alert.status = AlertStatus.INVESTIGATING.value
    db.add(IncidentAlert(incident_id=inc.id, alert_id=alert.id,
                         correlation_reason=reason[:200], correlation_score=0.8))
    content = (f"{ev.activity} on {host or '-'} by {user or '-'} "
               f"(src {ev.src_ip or '-'} → dst {ev.dst_ip or '-'}); matched rule '{rule.key}'. "
               f"Details: {ev.ocsf}")
    fact = Evidence(tenant_id=tid, data_scope=scope, incident_id=inc.id,
                    kind=EvidenceKind.CONFIRMED_FACT.value, title=f"Telemetry: {rule.name}",
                    content=content[:4000], source=ev.source, source_ref=f"event:{ev.id}",
                    produced_by=f"detection:{rule.key}", confidence=1.0,
                    event_ids=[str(ev.id)], attack_techniques=list(rule.attack_techniques or []),
                    content_hash=content_hash(content))
    db.add(fact)
    db.flush()
    db.add(TimelineEntry(tenant_id=tid, data_scope=scope, incident_id=inc.id,
                         occurred_at=ev.event_time, title=alert.title, detail=content[:1000],
                         category="event", actor=f"detection:{rule.key}", evidence_id=fact.id,
                         attack_techniques=list(rule.attack_techniques or [])))
    a = _upsert_entity(db, tid, scope, "host", host)
    b = _upsert_entity(db, tid, scope, "user", user)
    c = _upsert_entity(db, tid, scope, "ip", ev.dst_ip or ev.src_ip)
    for src, dst, rel in ((b, a, "logged_into"), (a, c, "connected_to")):
        if src is not None and dst is not None:
            db.add(EntityRelationship(tenant_id=tid, data_scope=scope, src_entity_id=src.id,
                                      dst_entity_id=dst.id, relationship_type=rel,
                                      incident_id=inc.id))
    db.flush()
    is_new = reason.startswith("New")
    bus.publish_soon(Event(type="incident.created" if is_new else "incident.updated", scope=scope,
                           tenant_id=str(tid), data={
                               "incident_id": str(inc.id), "key": inc.key, "title": inc.title,
                               "severity": inc.severity, "simulated": scope == "DEMO"}))
    if is_new and inc.severity == "critical":
        from .notify import escalate_incident

        escalate_incident(db, inc, reason="new critical incident", category="critical")
    return inc


def ingest_batch(db: Session, tenant_id: uuid.UUID, scope: str, events: list[dict],
                 connector_id: uuid.UUID | None = None) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("Unknown tenant")
    ctx = DetectionContext(db, tenant_id)
    alerts = 0
    for raw in events:
        _, new_alerts = ingest_event(db, tenant_id, scope, raw, ctx, connector_id)
        alerts += len(new_alerts)
    return {"ingested": len(events), "alerts": alerts}
