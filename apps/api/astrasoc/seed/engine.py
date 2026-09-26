"""Demo-data engine.

Responsibilities:
* Build seeded attack scenarios into fully-populated incidents (idempotent).
* Continuously generate realistic events/alerts so the UI updates in real time.
* Support reset/reseed of DEMO-scoped data without touching LIVE data.

Everything produced here is ``data_scope="DEMO"`` and clearly simulated.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth.security import content_hash
from ..config import settings
from ..db import SessionLocal
from ..models import (
    Alert,
    Entity,
    EntityRelationship,
    Evidence,
    Hypothesis,
    Incident,
    IncidentAlert,
    SecurityEvent,
    Tenant,
    ThreatIndicator,
    TimelineEntry,
)
from ..models.enums import AlertStatus, DataScope, IncidentStatus
from ..services.events import Event, bus
from .scenarios import SCENARIO_INDEX, SCENARIOS

DEMO = DataScope.DEMO.value
logger = logging.getLogger("astrasoc.demo")

# Denominators for continuous synthetic telemetry.
_EVENT_SOURCES = ["crowdstrike_falcon", "microsoft_defender", "splunk", "vectra",
                  "entra_id", "elastic", "microsoft_sentinel", "aws"]
_OCSF_CLASSES = [(4001, "Network Activity"), (1001, "File System Activity"),
                 (3002, "Authentication"), (1007, "Process Activity"),
                 (4003, "DNS Activity")]
_HOSTS = ["FIN-WKS-014", "ENG-LT-233", "HR-WKS-051", "SRV-APP-01", "DMZ-WEB-03",
          "OPS-WKS-020", "SAL-WKS-077", "MKT-WKS-118"]
_USERS = ["acme\\jlaurent", "m.okafor@acme.io", "acme\\rpatel", "acme\\svc-scan",
          "acme\\dkowalski", "acme\\hkim"]


def _next_incident_key(db: Session, tenant_id: uuid.UUID) -> str:
    count = db.execute(
        select(func.count()).select_from(Incident).where(Incident.tenant_id == tenant_id)
    ).scalar() or 0
    return f"INC-{count + 1:06d}"


def build_scenario(db: Session, tenant_id: uuid.UUID, defn: dict, scope: str = DEMO) -> Incident:
    """Create a full incident (entities, alerts, evidence, timeline, hypotheses)."""
    now = datetime.now(UTC)
    # Realistic history: the case opened some time ago; most were
    # acknowledged within minutes, a few were not (so SLA tracking has real
    # breaches and at-risk cases to show — nothing is faked downstream).
    opened = now - timedelta(minutes=random.randint(8, 600))
    acked = opened + timedelta(minutes=random.randint(2, 45)) if random.random() < 0.75 else None
    inc = Incident(
        tenant_id=tenant_id, data_scope=scope, key=_next_incident_key(db, tenant_id),
        title=defn["title"], summary=defn["summary"], severity=defn["severity"],
        status=(IncidentStatus.INVESTIGATING.value if acked else IncidentStatus.NEW.value),
        confidence=defn["confidence"],
        business_risk=defn["business_risk"], risk_score=defn["business_risk"],
        scenario_key=defn["key"], attack_tactics=defn["attack_tactics"],
        attack_techniques=defn["attack_techniques"],
        created_at=opened, acknowledged_at=acked if acked and acked < now else None,
    )
    db.add(inc)
    db.flush()
    from ..services.metering import record
    from ..services.sla import apply_sla

    apply_sla(db, inc)
    record(db, tenant_id, "incidents")

    # Entities.
    entity_rows: list[Entity] = []
    affected_users, affected_hosts, related_ips, related_domains = [], [], [], []
    for e in defn["entities"]:
        ent = Entity(
            tenant_id=tenant_id, data_scope=scope, kind=e["kind"], value=e["value"],
            display_name=e.get("display", e["value"]), risk_score=e.get("risk", 0),
            criticality=e.get("criticality", "low"), is_internal=e.get("internal", True),
            first_seen=now - timedelta(hours=random.randint(1, 72)), last_seen=now,
            enrichment={"seeded": True, "scenario": defn["key"]},
        )
        db.add(ent)
        entity_rows.append(ent)
        if e["kind"] == "user" or e["kind"] == "account":
            affected_users.append(e["value"])
        elif e["kind"] == "host":
            affected_hosts.append(e["value"])
        elif e["kind"] == "ip":
            related_ips.append(e["value"])
        elif e["kind"] == "domain":
            related_domains.append(e["value"])
    db.flush()

    inc.affected_users = affected_users
    inc.affected_hosts = affected_hosts
    inc.related_ips = related_ips
    inc.related_domains = related_domains

    # Relationships.
    for src_i, dst_i, rel in defn.get("relationships", []):
        if src_i < len(entity_rows) and dst_i < len(entity_rows):
            db.add(EntityRelationship(
                tenant_id=tenant_id, data_scope=scope,
                src_entity_id=entity_rows[src_i].id, dst_entity_id=entity_rows[dst_i].id,
                relationship_type=rel, incident_id=inc.id, weight=1.0,
            ))

    # Alerts + a few backing raw events.
    for a in defn["alerts"]:
        event_ids = []
        for _ in range(random.randint(1, 3)):
            ev = SecurityEvent(
                tenant_id=tenant_id, data_scope=scope, source=a["source"],
                event_time=now - timedelta(minutes=random.randint(1, 60)),
                ocsf_class_uid=random.choice(_OCSF_CLASSES)[0],
                ocsf_category=random.choice(_OCSF_CLASSES)[1],
                activity=a["title"][:100], severity=a["severity"],
                ocsf={"scenario": defn["key"], "message": a["desc"]},
                raw={"seeded": True},
                host_name=affected_hosts[0] if affected_hosts else None,
                user_name=affected_users[0] if affected_users else None,
                src_ip=related_ips[0] if related_ips else None,
            )
            db.add(ev)
            db.flush()
            event_ids.append(str(ev.id))
        alert = Alert(
            tenant_id=tenant_id, data_scope=scope, title=a["title"], description=a["desc"],
            source=a["source"], severity=a["severity"], status=AlertStatus.INVESTIGATING.value,
            risk_score=defn["business_risk"] * a.get("confidence", 0.7),
            confidence=a.get("confidence", 0.7), attack_techniques=a.get("techniques", []),
            observables={"hosts": affected_hosts, "users": affected_users, "ips": related_ips},
            incident_id=inc.id, event_ids=event_ids,
        )
        db.add(alert)
        db.flush()
        db.add(IncidentAlert(incident_id=inc.id, alert_id=alert.id,
                             correlation_reason=f"Shared entities in scenario {defn['key']}",
                             correlation_score=0.8))

    # Evidence (record index -> id map for hypotheses/timeline wiring).
    evidence_rows: list[Evidence] = []
    for ev in defn["evidence"]:
        row = Evidence(
            tenant_id=tenant_id, data_scope=scope, incident_id=inc.id, kind=ev["kind"],
            title=ev["title"], content=ev["content"], source=ev["source"],
            produced_by="agent" if ev["source"].startswith("sim-") else
                        ("analyst" if ev["source"] == "analyst" else "tool"),
            confidence=ev.get("confidence", 1.0), attack_techniques=ev.get("techniques", []),
            content_hash=content_hash(ev["content"]),
        )
        db.add(row)
        evidence_rows.append(row)
    db.flush()

    # Timeline.
    for t in defn.get("timeline", []):
        ev_id = None
        if "evidence" in t and t["evidence"] < len(evidence_rows):
            ev_id = evidence_rows[t["evidence"]].id
        db.add(TimelineEntry(
            tenant_id=tenant_id, data_scope=scope, incident_id=inc.id,
            occurred_at=now + timedelta(minutes=t["offset_min"]),
            title=t["title"], detail=t.get("detail", ""), category=t.get("category", "event"),
            actor=t.get("actor", ""), evidence_id=ev_id,
            attack_techniques=t.get("techniques", []),
        ))

    # Hypotheses (wire supporting evidence IDs).
    for h in defn.get("hypotheses", []):
        supporting = [str(evidence_rows[i].id) for i in h.get("supporting", [])
                      if i < len(evidence_rows)]
        db.add(Hypothesis(
            tenant_id=tenant_id, data_scope=scope, incident_id=inc.id,
            statement=h["statement"], is_primary=h.get("is_primary", False),
            confidence=h.get("confidence", 0.5),
            status="supported" if h.get("is_primary") else "open",
            supporting_evidence_ids=supporting, missing_evidence=h.get("missing", []),
            attack_techniques=h.get("techniques", []), produced_by="agent",
        ))

    db.flush()
    return inc


def _seed_threat_intel(db: Session, tenant_id: uuid.UUID, scope: str = DEMO) -> None:
    iocs = [
        ("ip", "185.220.101.42", "tor_exit", 0.8, "misp"),
        ("ip", "45.155.205.233", "bruteforce", 0.7, "misp"),
        ("ip", "88.119.169.20", "malware_c2", 0.9, "misp"),
        ("ip", "194.26.29.156", "exploit_host", 0.85, "virustotal"),
        ("domain", "cdn-metrics-sync.com", "c2", 0.82, "virustotal"),
        ("domain", "acme-invoices.com", "phishing", 0.88, "misp"),
        ("domain", "mega-upload-sync.io", "exfil", 0.6, "taxii"),
        ("domain", "sync.telemetry-cdn.net", "dns_tunnel", 0.7, "misp"),
    ]
    now = datetime.now(UTC)
    for ioc_type, value, threat, conf, src in iocs:
        exists = db.execute(
            select(ThreatIndicator).where(ThreatIndicator.tenant_id == tenant_id,
                                          ThreatIndicator.value == value)
        ).scalar_one_or_none()
        if exists is None:
            db.add(ThreatIndicator(
                tenant_id=tenant_id, ioc_type=ioc_type, value=value, threat_type=threat,
                confidence=conf, source=src, first_seen=now - timedelta(days=random.randint(1, 30)),
                last_seen=now, tags=[threat, src],
            ))


def ensure_demo_data(db: Session, tenant_id: uuid.UUID, limit: int | None = None) -> None:
    """Idempotently build the seeded scenarios and TI if not already present."""
    existing = db.execute(
        select(func.count()).select_from(Incident).where(
            Incident.tenant_id == tenant_id, Incident.data_scope == DEMO)
    ).scalar() or 0
    _seed_threat_intel(db, tenant_id)
    if existing == 0:
        for defn in SCENARIOS[:limit] if limit is not None else SCENARIOS:
            build_scenario(db, tenant_id, defn, DEMO)
    db.commit()


def ensure_demo_estate_data(db: Session) -> None:
    """Seed demo incidents for every demo customer tenant."""
    from .bootstrap import demo_customer_scenarios

    for slug, count in demo_customer_scenarios().items():
        tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
        if tenant is not None and count:
            ensure_demo_data(db, tenant.id, limit=count)


def reset_demo(db: Session, tenant_id: uuid.UUID) -> dict:
    """Delete ALL demo-scoped operational data for ONE tenant and reseed.

    Every delete is filtered by tenant AND ``data_scope == "DEMO"`` (join
    tables through their DEMO parent rows). LIVE data and other tenants are
    never touched.
    """
    from ..models import (
        AgentRun,
        ApprovalRequest,
        PolicyDecision,
        Report,
        ResponseAction,
        ToolExecution,
        WorkflowRun,
    )
    from .bootstrap import demo_customer_scenarios

    scope = DEMO
    demo_incidents = select(Incident.id).where(Incident.tenant_id == tenant_id,
                                               Incident.data_scope == scope)
    demo_actions = select(ResponseAction.id).where(ResponseAction.tenant_id == tenant_id,
                                                   ResponseAction.data_scope == scope)
    db.execute(delete(IncidentAlert).where(IncidentAlert.incident_id.in_(demo_incidents)))
    db.execute(delete(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_id,
                                             ApprovalRequest.response_action_id.in_(demo_actions)))
    db.execute(delete(PolicyDecision).where(PolicyDecision.tenant_id == tenant_id,
                                            PolicyDecision.response_action_id.in_(demo_actions)))
    counts = {}
    for model in (ResponseAction, WorkflowRun, AgentRun, ToolExecution, Report,
                  Evidence, TimelineEntry, Hypothesis, EntityRelationship,
                  Alert, SecurityEvent, Entity, Incident):
        res = db.execute(delete(model).where(model.tenant_id == tenant_id,
                                             model.data_scope == scope))
        counts[model.__tablename__] = res.rowcount or 0
    db.commit()
    tenant = db.get(Tenant, tenant_id)
    limit = demo_customer_scenarios().get(tenant.slug) if tenant else None
    ensure_demo_data(db, tenant_id, limit=limit)
    bus.publish_soon(Event(type="demo.reset", scope=DEMO, tenant_id=str(tenant_id),
                           data={"message": "Demo data reset and reseeded."}))
    return {"status": "reset", "deleted": counts,
            "scenarios": limit if limit is not None else len(SCENARIOS)}


def launch_scenario(db: Session, tenant_id: uuid.UUID, key: str) -> Incident:
    """Create a fresh incident from a scenario on demand."""
    defn = SCENARIO_INDEX.get(key)
    if defn is None:
        raise KeyError(f"Unknown scenario: {key}")
    inc = build_scenario(db, tenant_id, defn, DEMO)
    db.commit()
    bus.publish_soon(Event(
        type="incident.created", scope=DEMO, tenant_id=str(tenant_id),
        data={"incident_id": str(inc.id), "key": inc.key, "title": inc.title,
              "severity": inc.severity, "simulated": True},
    ))
    return inc


# --- Continuous generator -------------------------------------------------
# Control (paused/speed) lives in the database so a request handled by any API
# replica reaches the replica that runs the generator (the cluster leader).
# That replica publishes its stats to the same row.
_GEN_KEY = "demo_generator"
_local = {"running": False, "events": 0, "aps": 0.0, "last_error": None}


def _gen_row(db):
    from ..models import SystemSetting

    row = db.execute(select(SystemSetting).where(SystemSetting.tenant_id.is_(None),
                                                 SystemSetting.key == _GEN_KEY)).scalar_one_or_none()
    if row is None:
        row = SystemSetting(tenant_id=None, key=_GEN_KEY, value={"paused": False, "speed": 1.0},
                            description="Demo event generator control and status.")
        db.add(row)
        db.flush()
    return row


def _control(db) -> dict:
    v = _gen_row(db).value or {}
    return {"paused": bool(v.get("paused", False)), "speed": float(v.get("speed", 1.0))}


def generator_state() -> dict:
    with SessionLocal() as db:
        v = dict(_gen_row(db).value or {})
        db.commit()
    stats = v.get("stats") or {}
    # Stats are refreshed every ~10 s by the generating replica; if they are
    # older than a minute, nothing is generating (e.g. that replica died).
    fresh = False
    if stats.get("updated_at"):
        try:
            fresh = datetime.now(UTC) - datetime.fromisoformat(stats["updated_at"]) < timedelta(seconds=60)
        except ValueError:
            fresh = False
    return {"paused": bool(v.get("paused", False)), "speed": float(v.get("speed", 1.0)),
            "running": bool(stats.get("running", False)) and fresh, "events": int(stats.get("events", 0)),
            "aps": float(stats.get("aps", 0.0)), "last_error": stats.get("last_error"),
            "updated_at": stats.get("updated_at"), "replica": stats.get("replica")}


def set_generator(paused: bool | None = None, speed: float | None = None) -> dict:
    with SessionLocal() as db:
        row = _gen_row(db)
        v = dict(row.value or {})
        if paused is not None:
            v["paused"] = bool(paused)
        if speed is not None:
            v["speed"] = max(0.25, min(10.0, float(speed)))
        row.value = v
        db.commit()
    return generator_state()


def _publish_stats(running: bool) -> None:
    from ..services.cluster import REPLICA_ID

    with SessionLocal() as db:
        row = _gen_row(db)
        row.value = {**(row.value or {}), "stats": {
            **_local, "running": running, "replica": REPLICA_ID,
            "updated_at": datetime.now(UTC).isoformat()}}
        db.commit()


_BENIGN = [
    {"activity": "Process create", "cmdline": "C:\\Windows\\System32\\svchost.exe -k netsvcs"},
    {"activity": "Process create", "cmdline": "\"C:\\Program Files\\Microsoft Office\\WINWORD.EXE\" /n"},
    {"activity": "Network connection", "dst_ip": "52.96.165.18", "dst_port": 443},
    {"activity": "DNS query", "query": "login.microsoftonline.com"},
    {"activity": "Sign-in", "result": "success", "src_ip": "10.20.4.18"},
    {"activity": "File write", "path": "C:\\Users\\Public\\report.xlsx"},
]
# Attack patterns the starter detection content recognises. IPs/domains are
# the seeded threat-intel indicators.
_MALICIOUS = [
    {"activity": "Process create", "cmdline": "vssadmin.exe delete shadows /all /quiet",
     "severity": "high"},
    {"activity": "Process create", "cmdline": "powershell.exe -nop -w hidden -enc SQBFAFgAIAAoAE4AZQB3AA==",
     "severity": "medium"},
    {"activity": "Process access", "target_process": "lsass.exe", "severity": "high"},
    {"activity": "Network connection", "dst_ip": "88.119.169.20", "dst_port": 443, "severity": "medium"},
    {"activity": "DNS query", "query": "cdn-metrics-sync.com", "severity": "low"},
    {"activity": "Sign-in", "result": "success", "src_ip": "185.220.101.42", "severity": "medium"},
    {"activity": "Group membership change", "group": "Domain Admins", "severity": "medium"},
]


def _synthetic_event() -> dict:
    malicious = random.random() < 0.06
    tmpl = dict(random.choice(_MALICIOUS if malicious else _BENIGN))
    tmpl.setdefault("severity", random.choices(["info", "low", "medium"], weights=[60, 30, 10])[0])
    tmpl.update({
        "source": random.choice(_EVENT_SOURCES), "host": random.choice(_HOSTS),
        "user": random.choice(_USERS), "synthetic": True,
    })
    tmpl.setdefault("src_ip", f"10.0.{random.randint(0, 255)}.{random.randint(1, 254)}")
    return tmpl


def _emit_tick() -> int:
    """One tick: one synthetic event per demo customer tenant that is in DEMO
    mode, pushed through the real detection/correlation pipeline. Tenants in
    LIVE mode never receive generated data."""
    from ..services.mode import current_scope
    from ..services.pipeline import ingest_event

    produced = 0
    with SessionLocal() as db:
        tenant_ids = [t.id for t in db.execute(select(Tenant).where(
            Tenant.kind == "customer", Tenant.is_active.is_(True))).scalars()]
        for tid in tenant_ids:
            if current_scope(db, tid) != DEMO:
                continue
            ingest_event(db, tid, DEMO, _synthetic_event())
            produced += 1
        db.commit()
    _local["events"] += produced
    return produced


async def run_live_generator(leader=None) -> None:
    """Background loop producing synthetic demo telemetry. With several API
    replicas only the leader generates (see services.cluster)."""
    interval = settings.demo_event_interval_seconds
    last_stats = 0.0
    try:
        while True:
            speed = 1.0
            if leader is None or leader.is_leader:
                try:
                    control = await asyncio.to_thread(lambda: _with_db(_control))
                    speed = control["speed"]
                    if not control["paused"]:
                        produced = await asyncio.to_thread(_emit_tick)
                        _local["aps"] = round(produced * speed / interval, 2)
                    _local["last_error"] = None
                except Exception as exc:  # never let the loop die — but surface the error
                    _local["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
                    logger.exception("Demo generator tick failed")
                if time.monotonic() - last_stats > 10:
                    last_stats = time.monotonic()
                    await asyncio.to_thread(_publish_stats, True)
            await asyncio.sleep(max(0.3, interval / speed))
    except asyncio.CancelledError:  # pragma: no cover
        raise


def _with_db(fn):
    with SessionLocal() as db:
        out = fn(db)
        db.commit()
        return out
