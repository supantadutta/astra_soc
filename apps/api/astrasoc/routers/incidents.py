"""Incidents API: the investigation workspace (spec §7)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..auth.security import content_hash
from ..db import get_db
from ..listing import paginate
from ..models import (
    AgentRun,
    Alert,
    ApprovalRequest,
    Entity,
    EntityRelationship,
    Evidence,
    Hypothesis,
    Incident,
    ResponseAction,
    TimelineEntry,
)
from ..models.enums import EvidenceKind, IncidentStatus
from ..schemas.common import serialize, serialize_many
from ..services import audit
from ..services.agents import orchestrator
from ..services.knowledge import search as knowledge_search
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("")
def list_incidents(
    principal: Principal = Depends(require_permission("incident:read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    severity: str | None = None, status: str | None = None, scenario: str | None = None,
    q: str | None = None, sort: str | None = None, order: str = "desc",
) -> dict:
    scope = current_scope(db)
    filters = []
    if severity:
        filters.append(Incident.severity == severity)
    if status:
        filters.append(Incident.status == status)
    if scenario:
        filters.append(Incident.scenario_key == scenario)
    return paginate(db, Incident, tenant_id=principal.tenant_id, scope=scope, filters=filters,
                    search=q, search_fields=["title", "summary", "key"],
                    sort=sort, order=order, page=page, page_size=page_size)


def _load_incident(db, principal, incident_id, scope) -> Incident:
    inc = db.get(Incident, incident_id)
    if not inc or inc.tenant_id != principal.tenant_id or inc.data_scope != scope:
        raise HTTPException(404, detail="Incident not found")
    return inc


@router.get("/{incident_id}")
def get_incident(incident_id: uuid.UUID,
                 principal: Principal = Depends(require_permission("incident:read")),
                 db: Session = Depends(get_db)) -> dict:
    """Full workspace payload: everything needed to investigate the case."""
    scope = current_scope(db)
    inc = _load_incident(db, principal, incident_id, scope)

    alerts = db.execute(select(Alert).where(Alert.incident_id == inc.id)).scalars().all()
    evidence = db.execute(select(Evidence).where(Evidence.incident_id == inc.id)
                          .order_by(Evidence.created_at)).scalars().all()
    timeline = db.execute(select(TimelineEntry).where(TimelineEntry.incident_id == inc.id)
                          .order_by(TimelineEntry.occurred_at)).scalars().all()
    hypotheses = db.execute(select(Hypothesis).where(Hypothesis.incident_id == inc.id)
                            .order_by(Hypothesis.is_primary.desc(), Hypothesis.confidence.desc())
                            ).scalars().all()
    rels = db.execute(select(EntityRelationship).where(
        EntityRelationship.incident_id == inc.id)).scalars().all()
    entity_ids = {r.src_entity_id for r in rels} | {r.dst_entity_id for r in rels}
    entities = db.execute(select(Entity).where(Entity.id.in_(entity_ids))).scalars().all() \
        if entity_ids else []
    agent_runs = db.execute(select(AgentRun).where(AgentRun.incident_id == inc.id)
                            .order_by(AgentRun.created_at.desc())).scalars().all()
    actions = db.execute(select(ResponseAction).where(ResponseAction.incident_id == inc.id)
                         .order_by(ResponseAction.created_at.desc())).scalars().all()
    approvals = db.execute(select(ApprovalRequest).where(
        ApprovalRequest.incident_id == inc.id)).scalars().all()

    # Similar historical incidents (same scenario or shared techniques).
    similar = db.execute(
        select(Incident).where(
            Incident.tenant_id == principal.tenant_id, Incident.data_scope == scope,
            Incident.id != inc.id,
            or_(Incident.scenario_key == inc.scenario_key,
                Incident.severity == inc.severity))
        .limit(5)
    ).scalars().all()

    # Split evidence by epistemic kind so the UI never conflates them.
    by_kind: dict[str, list] = {}
    for e in evidence:
        by_kind.setdefault(e.kind, []).append(serialize(e))

    return {
        "incident": serialize(inc),
        "alerts": serialize_many(alerts),
        "evidence": serialize_many(evidence),
        "evidence_by_kind": by_kind,
        "timeline": serialize_many(timeline),
        "hypotheses": serialize_many(hypotheses),
        "entities": serialize_many(entities),
        "relationships": [{"source": str(r.src_entity_id), "target": str(r.dst_entity_id),
                           "type": r.relationship_type, "weight": r.weight} for r in rels],
        "agent_runs": serialize_many(agent_runs),
        "response_actions": serialize_many(actions),
        "approvals": serialize_many(approvals),
        "similar_incidents": serialize_many(similar),
        "epistemic_legend": {k.value: k.name for k in EvidenceKind},
    }


@router.patch("/{incident_id}")
def update_incident(incident_id: uuid.UUID, payload: dict,
                    principal: Principal = Depends(require_permission("incident:write")),
                    db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    inc = _load_incident(db, principal, incident_id, scope)
    now = datetime.now(UTC)
    for field in ("title", "summary", "severity", "status", "confidence", "business_risk", "tags"):
        if field in payload:
            setattr(inc, field, payload[field])
    if payload.get("status") == IncidentStatus.RESOLVED.value and not inc.resolved_at:
        inc.resolved_at = now
    if "owner_id" in payload and payload["owner_id"]:
        inc.owner_id = uuid.UUID(payload["owner_id"])
    audit.record(db, action="incident.updated", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="incident",
                 resource_id=str(incident_id), data_scope=scope, detail={"fields": list(payload)})
    db.commit()
    return serialize(inc)


@router.post("/{incident_id}/notes")
def add_note(incident_id: uuid.UUID, payload: dict,
             principal: Principal = Depends(require_permission("incident:write")),
             db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    inc = _load_incident(db, principal, incident_id, scope)
    note = payload.get("note", "").strip()
    if not note:
        raise HTTPException(422, detail="note is required")
    entry = TimelineEntry(
        tenant_id=principal.tenant_id, data_scope=scope, incident_id=inc.id,
        occurred_at=datetime.now(UTC), title="Analyst note",
        detail=note, category="note", actor=principal.email,
    )
    db.add(entry)
    db.commit()
    return serialize(entry)


@router.post("/{incident_id}/evidence")
def add_evidence(incident_id: uuid.UUID, payload: dict,
                 principal: Principal = Depends(require_permission("evidence:write")),
                 db: Session = Depends(get_db)) -> dict:
    """Analyst-authored evidence. Defaults to ANALYST_CONCLUSION unless a kind is
    given; the UI must clearly distinguish this from confirmed facts."""
    scope = current_scope(db)
    inc = _load_incident(db, principal, incident_id, scope)
    content = payload.get("content", "")
    ev = Evidence(
        tenant_id=principal.tenant_id, data_scope=scope, incident_id=inc.id,
        kind=payload.get("kind", EvidenceKind.ANALYST_CONCLUSION.value),
        title=payload.get("title", "Analyst evidence"), content=content,
        source=principal.email, produced_by="analyst",
        confidence=float(payload.get("confidence", 1.0)),
        attack_techniques=payload.get("attack_techniques", []),
        content_hash=content_hash(content),
    )
    db.add(ev)
    audit.record(db, action="evidence.added", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="evidence",
                 resource_id=str(ev.id), data_scope=scope, detail={"kind": ev.kind})
    db.commit()
    return serialize(ev)


@router.post("/{incident_id}/promote-hypothesis/{hypothesis_id}")
def promote_hypothesis(incident_id: uuid.UUID, hypothesis_id: uuid.UUID,
                       principal: Principal = Depends(require_permission("evidence:write")),
                       db: Session = Depends(get_db)) -> dict:
    """An analyst promotes an AI hypothesis to an analyst conclusion (evidence).
    This is the ONLY way a model inference becomes an analyst-backed conclusion."""
    scope = current_scope(db)
    inc = _load_incident(db, principal, incident_id, scope)
    h = db.get(Hypothesis, hypothesis_id)
    if not h or h.incident_id != inc.id:
        raise HTTPException(404, detail="Hypothesis not found")
    ev = Evidence(
        tenant_id=principal.tenant_id, data_scope=scope, incident_id=inc.id,
        kind=EvidenceKind.ANALYST_CONCLUSION.value,
        title=f"[Analyst-confirmed] {h.statement[:120]}",
        content=f"Analyst {principal.email} confirmed hypothesis: {h.statement}",
        source=principal.email, produced_by="analyst", confidence=h.confidence,
        attack_techniques=h.attack_techniques, content_hash=content_hash(h.statement),
    )
    db.add(ev)
    h.status = "supported"
    audit.record(db, action="hypothesis.promoted", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="hypothesis",
                 resource_id=str(hypothesis_id), data_scope=scope)
    db.commit()
    return serialize(ev)


@router.post("/{incident_id}/investigate")
def investigate(incident_id: uuid.UUID,
                principal: Principal = Depends(require_permission("agent:run")),
                db: Session = Depends(get_db)) -> dict:
    """Run the coordinator workflow graph over the incident."""
    scope = current_scope(db)
    inc = _load_incident(db, principal, incident_id, scope)
    result = orchestrator.run_investigation(db, principal.tenant_id, inc.id, scope,
                                            actor_label=principal.email)
    audit.record(db, action="incident.investigate", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="incident",
                 resource_id=str(incident_id), data_scope=scope, detail={"plan": result["plan"]})
    db.commit()
    return result


@router.get("/{incident_id}/recommended-actions")
def recommended_actions(incident_id: uuid.UUID,
                        principal: Principal = Depends(require_permission("incident:read")),
                        db: Session = Depends(get_db)) -> dict:
    """Deterministic response recommendations derived from the scenario + facts.
    These are RECOMMENDATIONS only — nothing is executed here."""
    scope = current_scope(db)
    inc = _load_incident(db, principal, incident_id, scope)
    from ..seed.scenarios import SCENARIO_INDEX
    fact = db.execute(select(Evidence).where(
        Evidence.incident_id == inc.id,
        Evidence.kind == EvidenceKind.CONFIRMED_FACT.value)).scalars().first()
    recs = []
    defn = SCENARIO_INDEX.get(inc.scenario_key) if inc.scenario_key else None
    if defn and "recommended_action" in defn:
        ra = defn["recommended_action"]
        ent_idx = ra.get("target_entity", 0)
        ent = defn["entities"][ent_idx] if ent_idx < len(defn["entities"]) else {}
        recs.append({
            "action": ra["action"], "confidence": ra["confidence"],
            "reversible": ra["reversible"],
            "target": {"value": ent.get("value"), "kind": ent.get("kind"),
                       "display": ent.get("display")},
            "requires_evidence": True,
            "suggested_evidence_ids": [str(fact.id)] if fact else [],
            "rationale": f"Scenario '{inc.scenario_key}' recommends {ra['action']} on "
                         f"{ent.get('display')}.",
        })
    recs.append({"action": "increase_monitoring", "confidence": 0.9, "reversible": True,
                 "target": {"value": inc.affected_hosts[0] if inc.affected_hosts else "n/a"},
                 "requires_evidence": False,
                 "suggested_evidence_ids": [str(fact.id)] if fact else [],
                 "rationale": "Low-risk monitoring uplift while investigation continues."})
    return {"recommendations": recs}


@router.get("/{incident_id}/similar-knowledge")
def similar_knowledge(incident_id: uuid.UUID,
                      principal: Principal = Depends(require_permission("knowledge:read")),
                      db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    inc = _load_incident(db, principal, incident_id, scope)
    results = knowledge_search(
        db, principal.tenant_id, f"{inc.title} {inc.summary}",
        scopes=["tenant_knowledge", "global_knowledge", "playbook_knowledge"],
        allowed_classifications=principal.allowed_classifications,
    )
    return {"results": results}
