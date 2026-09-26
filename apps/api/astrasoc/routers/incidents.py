"""Incidents API: the investigation workspace (spec §7)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
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
from ..models.enums import EvidenceKind, IncidentStatus, Severity
from ..schemas.common import serialize, serialize_many
from ..services import audit
from ..services.agents import orchestrator
from ..services.knowledge import search as knowledge_search
from ..services.mode import current_scope
from ..services.sla import apply_sla, mark_acknowledged, on_status_change, sla_state
from ..services.tiers import require_feature

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("")
def list_incidents(
    principal: Principal = Depends(require_permission("incident:read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    severity: str | None = None, status: str | None = None, scenario: str | None = None,
    q: str | None = None, sort: str | None = None, order: str = "desc",
) -> dict:
    scope = current_scope(db, principal.tenant_id)
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
    scope = current_scope(db, principal.tenant_id)
    inc = _load_incident(db, principal, incident_id, scope)

    alerts = db.execute(select(Alert).where(Alert.tenant_id == inc.tenant_id, Alert.incident_id == inc.id)).scalars().all()
    evidence = db.execute(select(Evidence).where(Evidence.tenant_id == inc.tenant_id, Evidence.incident_id == inc.id)
                          .order_by(Evidence.created_at)).scalars().all()
    timeline = db.execute(select(TimelineEntry).where(TimelineEntry.tenant_id == inc.tenant_id, TimelineEntry.incident_id == inc.id)
                          .order_by(TimelineEntry.occurred_at)).scalars().all()
    hypotheses = db.execute(select(Hypothesis).where(Hypothesis.tenant_id == inc.tenant_id, Hypothesis.incident_id == inc.id)
                            .order_by(Hypothesis.is_primary.desc(), Hypothesis.confidence.desc())
                            ).scalars().all()
    rels = db.execute(select(EntityRelationship).where(
        EntityRelationship.tenant_id == inc.tenant_id,
        EntityRelationship.incident_id == inc.id)).scalars().all()
    entity_ids = {r.src_entity_id for r in rels} | {r.dst_entity_id for r in rels}
    entities = db.execute(select(Entity).where(
        Entity.tenant_id == inc.tenant_id, Entity.id.in_(entity_ids))).scalars().all() \
        if entity_ids else []
    agent_runs = db.execute(select(AgentRun).where(AgentRun.tenant_id == inc.tenant_id, AgentRun.incident_id == inc.id)
                            .order_by(AgentRun.created_at.desc())).scalars().all()
    actions = db.execute(select(ResponseAction).where(ResponseAction.tenant_id == inc.tenant_id, ResponseAction.incident_id == inc.id)
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
        "sla": sla_state(inc),
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


_STATUSES = {st.value for st in IncidentStatus}
_SEVERITIES = {sv.value for sv in Severity}


@router.patch("/{incident_id}")
def update_incident(incident_id: uuid.UUID, payload: dict = Body(...),
                    principal: Principal = Depends(require_permission("incident:write")),
                    db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db, principal.tenant_id)
    inc = _load_incident(db, principal, incident_id, scope)
    changes: dict = {}
    if "severity" in payload:
        if payload["severity"] not in _SEVERITIES:
            raise HTTPException(422, detail=f"severity must be one of {sorted(_SEVERITIES)}")
        if payload["severity"] != inc.severity:
            changes["severity"] = [inc.severity, payload["severity"]]
            inc.severity = payload["severity"]
            apply_sla(db, inc)  # SLA targets follow severity (measured from creation)
    if "status" in payload:
        if payload["status"] not in _STATUSES:
            raise HTTPException(422, detail=f"status must be one of {sorted(_STATUSES)}")
        if payload["status"] != inc.status:
            changes["status"] = [inc.status, payload["status"]]
            inc.status = payload["status"]
            on_status_change(inc, inc.status)
    for field, lo, hi in (("confidence", 0.0, 1.0), ("business_risk", 0.0, 100.0)):
        if field in payload:
            try:
                val = float(payload[field])
            except (TypeError, ValueError):
                raise HTTPException(422, detail=f"{field} must be a number")
            if not lo <= val <= hi:
                raise HTTPException(422, detail=f"{field} must be between {lo} and {hi}")
            changes[field] = [getattr(inc, field), val]
            setattr(inc, field, val)
    for field in ("title", "summary"):
        if field in payload:
            setattr(inc, field, str(payload[field])[:300 if field == "title" else 20000])
            changes[field] = "updated"
    if "tags" in payload:
        inc.tags = [str(t)[:60] for t in (payload["tags"] or [])][:50]
        changes["tags"] = inc.tags
    if "owner_id" in payload:
        inc.owner_id = _validate_owner(db, principal, payload["owner_id"])
        changes["owner_id"] = str(inc.owner_id) if inc.owner_id else None
    audit.record(db, action="incident.updated", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="incident", resource_id=str(incident_id), data_scope=scope,
                 detail={"changes": changes})
    db.commit()
    return serialize(inc) | {"sla": sla_state(inc)}


def _validate_owner(db: Session, principal: Principal, owner) -> uuid.UUID | None:
    """Owners are users of this tenant or provider staff who can act in it."""
    if not owner:
        return None
    from ..models import Tenant, User
    from ..services.tenancy import TenantAccessDenied, resolve_access

    try:
        user = db.get(User, uuid.UUID(str(owner)))
    except ValueError:
        user = None
    if user is None or not user.is_active:
        raise HTTPException(422, detail="owner_id must be an active user")
    if user.tenant_id != principal.tenant_id:
        from ..auth.deps import _effective_permissions

        perms, _ = _effective_permissions(db, user)
        try:
            resolve_access(db, user, perms, db.get(Tenant, principal.tenant_id))
        except TenantAccessDenied:
            raise HTTPException(422, detail="owner_id must be able to access this tenant")
    return user.id


@router.post("/{incident_id}/acknowledge")
def acknowledge_incident(incident_id: uuid.UUID,
                         principal: Principal = Depends(require_permission("incident:write")),
                         db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db, principal.tenant_id)
    inc = _load_incident(db, principal, incident_id, scope)
    already = inc.acknowledged_at is not None
    mark_acknowledged(inc)
    if inc.status == IncidentStatus.NEW.value:
        inc.status = IncidentStatus.TRIAGED.value
    if inc.owner_id is None:
        inc.owner_id = principal.user_id
    if not already:
        audit.record(db, action="incident.acknowledged", actor_id=principal.user_id,
                     actor_label=principal.label, tenant_id=principal.tenant_id,
                     resource_type="incident", resource_id=str(incident_id), data_scope=scope)
    db.commit()
    return serialize(inc) | {"sla": sla_state(inc)}


@router.post("/{incident_id}/notes")
def add_note(incident_id: uuid.UUID, payload: dict = Body(...),
             principal: Principal = Depends(require_permission("incident:write")),
             db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db, principal.tenant_id)
    inc = _load_incident(db, principal, incident_id, scope)
    note = str(payload.get("note", "")).strip()[:10000]
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


# Kinds analysts may author directly. CONFIRMED_FACT is reserved for telemetry
# ingested by the platform or for an explicit attestation (evidence:attest)
# that cites a verifiable source; MODEL_INFERENCE is only produced by agents;
# EXECUTED_ACTION only by the response gateway.
_ANALYST_KINDS = {EvidenceKind.ANALYST_CONCLUSION.value, EvidenceKind.ASSUMPTION.value,
                  EvidenceKind.MISSING_EVIDENCE.value, EvidenceKind.RECOMMENDED_ACTION.value}


@router.post("/{incident_id}/evidence")
def add_evidence(incident_id: uuid.UUID, payload: dict = Body(...),
                 principal: Principal = Depends(require_permission("evidence:write")),
                 db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db, principal.tenant_id)
    inc = _load_incident(db, principal, incident_id, scope)
    kind = payload.get("kind", EvidenceKind.ANALYST_CONCLUSION.value)
    title = str(payload.get("title", "")).strip()
    content = str(payload.get("content", ""))
    if not title:
        raise HTTPException(422, detail="title is required")
    produced_by, source_ref = "analyst", payload.get("source_ref")
    if kind == EvidenceKind.CONFIRMED_FACT.value:
        principal.require("evidence:attest")
        if not source_ref or len(str(source_ref).strip()) < 6:
            raise HTTPException(422, detail={
                "error": "source_required",
                "message": "An attested fact must cite a verifiable source reference "
                           "(event id, ticket, log query, forensic artefact)."})
        # Recorded with the attester's identity so the response gateway can
        # enforce separation of duties (you cannot justify your own action
        # solely with your own attestation).
        produced_by = f"attested:{principal.user_id}"
    elif kind not in _ANALYST_KINDS:
        raise HTTPException(422, detail={
            "error": "kind_not_allowed",
            "message": f"Analysts may add: {sorted(_ANALYST_KINDS)} (or confirmed_fact with "
                       "evidence:attest and a source_ref)."})
    try:
        confidence = float(payload.get("confidence", 1.0))
    except (TypeError, ValueError):
        raise HTTPException(422, detail="confidence must be a number")
    if not 0.0 <= confidence <= 1.0:
        raise HTTPException(422, detail="confidence must be between 0 and 1")
    ev = Evidence(
        tenant_id=principal.tenant_id, data_scope=scope, incident_id=inc.id, kind=kind,
        title=title[:300], content=content, source=principal.email,
        source_ref=str(source_ref)[:300] if source_ref else None, produced_by=produced_by,
        confidence=confidence, attack_techniques=list(payload.get("attack_techniques") or [])[:20],
        content_hash=content_hash(content),
    )
    db.add(ev)
    db.flush()
    audit.record(db, action="evidence.added", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="evidence", resource_id=str(ev.id), data_scope=scope,
                 detail={"kind": kind, "attested": kind == EvidenceKind.CONFIRMED_FACT.value,
                         "source_ref": ev.source_ref})
    db.commit()
    return serialize(ev)


@router.post("/{incident_id}/promote-hypothesis/{hypothesis_id}")
def promote_hypothesis(incident_id: uuid.UUID, hypothesis_id: uuid.UUID,
                       principal: Principal = Depends(require_permission("evidence:write")),
                       db: Session = Depends(get_db)) -> dict:
    """An analyst promotes an AI hypothesis to an analyst conclusion (evidence).
    This is the ONLY way a model inference becomes an analyst-backed conclusion."""
    scope = current_scope(db, principal.tenant_id)
    inc = _load_incident(db, principal, incident_id, scope)
    h = db.get(Hypothesis, hypothesis_id)
    if not h or h.incident_id != inc.id or h.tenant_id != inc.tenant_id:
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
    require_feature(db, principal.tenant_id, "ai_investigation")
    scope = current_scope(db, principal.tenant_id)
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
    scope = current_scope(db, principal.tenant_id)
    inc = _load_incident(db, principal, incident_id, scope)
    from ..seed.scenarios import SCENARIO_INDEX
    fact = db.execute(select(Evidence).where(
        Evidence.tenant_id == inc.tenant_id, Evidence.incident_id == inc.id,
        Evidence.kind == EvidenceKind.CONFIRMED_FACT.value,
        Evidence.produced_by.notlike("attested:%"))).scalars().first()
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
    scope = current_scope(db, principal.tenant_id)
    inc = _load_incident(db, principal, incident_id, scope)
    results = knowledge_search(
        db, principal.tenant_id, f"{inc.title} {inc.summary}",
        scopes=["tenant_knowledge", "global_knowledge", "playbook_knowledge"],
        allowed_classifications=principal.allowed_classifications,
    )
    return {"results": results}
