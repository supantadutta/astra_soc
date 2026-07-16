"""Demo-data engine.

Responsibilities:
* Build seeded attack scenarios into fully-populated incidents (idempotent).
* Continuously generate realistic events/alerts so the UI updates in real time.
* Support reset/reseed of DEMO-scoped data without touching LIVE data.

Everything produced here is ``data_scope="DEMO"`` and clearly simulated.
"""
from __future__ import annotations

import asyncio
import random
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
    inc = Incident(
        tenant_id=tenant_id, data_scope=scope, key=_next_incident_key(db, tenant_id),
        title=defn["title"], summary=defn["summary"], severity=defn["severity"],
        status=IncidentStatus.INVESTIGATING.value, confidence=defn["confidence"],
        business_risk=defn["business_risk"], risk_score=defn["business_risk"],
        scenario_key=defn["key"], attack_tactics=defn["attack_tactics"],
        attack_techniques=defn["attack_techniques"],
        sla_ack_due=now + timedelta(minutes=15), sla_resolve_due=now + timedelta(hours=8),
        acknowledged_at=now - timedelta(minutes=random.randint(1, 8)),
    )
    db.add(inc)
    db.flush()

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


def ensure_demo_data(db: Session, tenant_id: uuid.UUID) -> None:
    """Idempotently build the seeded scenarios and TI if not already present."""
    existing = db.execute(
        select(func.count()).select_from(Incident).where(
            Incident.tenant_id == tenant_id, Incident.data_scope == DEMO)
    ).scalar() or 0
    _seed_threat_intel(db, tenant_id)
    if existing == 0:
        for defn in SCENARIOS:
            build_scenario(db, tenant_id, defn, DEMO)
    db.commit()


def reset_demo(db: Session, tenant_id: uuid.UUID) -> dict:
    """Delete ALL demo-scoped operational data for a tenant and reseed.

    Only DEMO-scoped rows are touched — LIVE data is never affected.
    """
    scope = DEMO
    for model in (IncidentAlert,):
        db.execute(delete(model))  # join table (demo-only in practice)
    for model in (Evidence, TimelineEntry, Hypothesis, EntityRelationship,
                  Alert, SecurityEvent, Entity, Incident):
        db.execute(delete(model).where(
            model.tenant_id == tenant_id, model.data_scope == scope))
    db.commit()
    ensure_demo_data(db, tenant_id)
    bus.publish_soon(Event(type="demo.reset", scope=DEMO, tenant_id=str(tenant_id),
                           data={"message": "Demo data reset and reseeded."}))
    return {"status": "reset", "scenarios": len(SCENARIOS)}


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
_generator_state = {"running": False, "paused": False, "speed": 1.0, "events": 0, "aps": 0.0}


def generator_state() -> dict:
    return dict(_generator_state)


def set_generator(paused: bool | None = None, speed: float | None = None) -> dict:
    if paused is not None:
        _generator_state["paused"] = paused
    if speed is not None:
        _generator_state["speed"] = max(0.25, min(10.0, speed))
    return generator_state()


def _emit_tick() -> None:
    """One synchronous tick: create a synthetic event, sometimes an alert."""
    from ..services.mode import current_scope

    with SessionLocal() as db:
        tenant = db.execute(select(Tenant)).scalars().first()
        if tenant is None:
            return
        scope = current_scope(db)
        # Only fabricate data in DEMO scope. In LIVE, ingestion comes from
        # real connectors, never the generator.
        if scope != DEMO:
            return
        now = datetime.now(UTC)
        cls = random.choice(_OCSF_CLASSES)
        ev = SecurityEvent(
            tenant_id=tenant.id, data_scope=DEMO, source=random.choice(_EVENT_SOURCES),
            event_time=now, ocsf_class_uid=cls[0], ocsf_category=cls[1],
            activity=random.choice(["Process create", "Network connection", "Sign-in",
                                    "File write", "DNS query"]),
            severity=random.choices(["info", "low", "medium", "high"],
                                    weights=[50, 30, 15, 5])[0],
            ocsf={"synthetic": True}, raw={"synthetic": True},
            host_name=random.choice(_HOSTS), user_name=random.choice(_USERS),
            src_ip=f"10.0.{random.randint(0,255)}.{random.randint(1,254)}",
        )
        db.add(ev)
        _generator_state["events"] += 1

        made_alert = False
        if random.random() < 0.12:  # occasional new deterministic alert
            made_alert = True
            sev = random.choices(["low", "medium", "high", "critical"],
                                 weights=[40, 35, 20, 5])[0]
            alert = Alert(
                tenant_id=tenant.id, data_scope=DEMO,
                title=f"[SIMULATED] {ev.activity} anomaly on {ev.host_name}",
                description="Synthetic demo alert generated by the demo event engine.",
                source=ev.source, severity=sev, status=AlertStatus.NEW.value,
                risk_score=random.randint(20, 90), confidence=round(random.uniform(0.4, 0.9), 2),
                attack_techniques=random.sample(["T1059", "T1071", "T1078", "T1110"],
                                                k=random.randint(1, 2)),
                observables={"host": ev.host_name, "user": ev.user_name},
                event_ids=[str(ev.id)],
            )
            db.add(alert)
        db.commit()

    bus.publish_soon(Event(
        type="event.ingested", scope=DEMO, tenant_id=str(tenant.id),
        data={"source": ev.source, "activity": ev.activity, "severity": ev.severity,
              "host": ev.host_name, "simulated": True},
    ))
    if made_alert:
        bus.publish_soon(Event(
            type="alert.created", scope=DEMO, tenant_id=str(tenant.id),
            data={"title": alert.title, "severity": alert.severity, "simulated": True},
        ))


async def run_live_generator() -> None:
    """Background loop producing synthetic demo telemetry."""
    _generator_state["running"] = True
    interval = settings.demo_event_interval_seconds
    try:
        while True:
            if not _generator_state["paused"]:
                try:
                    await asyncio.to_thread(_emit_tick)
                    _generator_state["aps"] = round(_generator_state["speed"] / interval, 2)
                except Exception:  # pragma: no cover — never let the loop die
                    pass
            await asyncio.sleep(max(0.3, interval / _generator_state["speed"]))
    except asyncio.CancelledError:  # pragma: no cover
        _generator_state["running"] = False
        raise
