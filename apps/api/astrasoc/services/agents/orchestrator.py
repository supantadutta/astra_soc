"""Agent orchestrator.

Runs a single bounded agent or the coordinator workflow. Every run is:
* budget-bounded (max tokens, max tool calls, max wall-clock),
* tool-restricted (only the agent's allowlist, via the broker),
* evidence-first (the output must validate against the AI schema),
* fully audited (an AgentRun row with an ordered step trace).

Agents do NOT message each other freely. The coordinator invokes specialists in
an explicit sequence and threads a shared, versioned case snapshot between them.
LLMs here are advisory: their output becomes MODEL_INFERENCE evidence /
hypotheses, never confirmed fact and never an executed action.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Agent, AgentRun, Evidence, Hypothesis, Incident
from ...models.enums import AgentRunStatus, EvidenceKind
from ...schemas.common import serialize, serialize_many
from ..events import Event, bus
from ..model_gateway import gateway
from ..tool_broker import broker
from ..tool_broker.broker import ToolBrokerError


class AgentOrchestrator:
    def _load_case_snapshot(self, db, tenant_id, incident_id, scope, agent) -> dict:
        """Gather read-only context for the agent through the tool broker,
        respecting its tool allowlist and the case's data scope."""
        snapshot: dict = {"steps": []}
        inc = db.get(Incident, incident_id)
        if inc is None or inc.tenant_id != tenant_id:
            return snapshot
        snapshot["incident"] = serialize(inc)

        allow = set(agent.tool_allowlist or [])
        # Pull evidence and timeline if permitted.
        for tool_key, args, key in [
            ("list_evidence", {"incident_id": str(incident_id)}, "evidence"),
            ("get_timeline", {"incident_id": str(incident_id)}, "timeline"),
            ("get_entity_graph", {"incident_id": str(incident_id)}, "graph"),
        ]:
            if tool_key in allow:
                try:
                    res = broker.execute(db, tenant_id, tool_key, args, scope=scope,
                                         incident_id=incident_id)
                    snapshot["steps"].append({"tool": tool_key, "ok": res["success"]})
                    payload = res["output"]
                    if key == "evidence":
                        snapshot["evidence"] = payload.get("evidence", [])
                    elif key == "timeline":
                        snapshot["timeline"] = payload.get("timeline", [])
                    else:
                        snapshot["graph"] = payload
                except ToolBrokerError as exc:
                    snapshot["steps"].append({"tool": tool_key, "ok": False, "error": exc.code})
        if "evidence" not in snapshot:
            ev = db.execute(
                select(Evidence).where(Evidence.incident_id == incident_id)
            ).scalars().all()
            snapshot["evidence"] = serialize_many(ev)
        # Existing hypotheses for context.
        hyps = db.execute(
            select(Hypothesis).where(Hypothesis.incident_id == incident_id)
        ).scalars().all()
        snapshot["hypotheses"] = serialize_many(hyps)
        return snapshot

    def run_agent(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        agent_key: str,
        incident_id: uuid.UUID | None,
        scope: str,
        *,
        actor_label: str = "system",
        workflow_run_id: uuid.UUID | None = None,
        write_hypothesis: bool = True,
    ) -> AgentRun:
        agent = db.execute(select(Agent).where(Agent.key == agent_key)).scalar_one_or_none()
        if agent is None:
            raise ValueError(f"Unknown agent: {agent_key}")
        run = AgentRun(
            tenant_id=tenant_id, agent_key=agent_key, agent_version=agent.current_version,
            incident_id=incident_id, workflow_run_id=workflow_run_id,
            status=AgentRunStatus.RUNNING.value, data_scope=scope,
            started_at=datetime.now(UTC), input={"actor": actor_label},
        )
        db.add(run)
        db.flush()
        bus.publish_soon(Event(type="agent.started", scope=scope, tenant_id=str(tenant_id),
                               data={"agent": agent_key, "run_id": str(run.id),
                                     "incident_id": str(incident_id) if incident_id else None}))

        if not agent.enabled:
            run.status = AgentRunStatus.FAILED.value
            run.error = "Agent is disabled."
            run.finished_at = datetime.now(UTC)
            db.flush()
            return run

        try:
            snapshot = self._load_case_snapshot(db, tenant_id, incident_id, scope, agent) \
                if incident_id else {"prompt": actor_label}
            tool_calls = len(snapshot.get("steps", []))
            if tool_calls > agent.max_tool_calls:
                run.status = AgentRunStatus.BUDGET_EXCEEDED.value
                run.error = "Tool-call budget exceeded."
                run.finished_at = datetime.now(UTC)
                db.flush()
                return run

            result = gateway.invoke(
                db, tenant_id, agent.required_capability, snapshot,
                force_verification=(agent_key in ("response_planner", "independent_verifier")),
            )
            if result.tokens_used > agent.max_token_budget:
                run.status = AgentRunStatus.BUDGET_EXCEEDED.value
                run.error = f"Token budget exceeded ({result.tokens_used} > {agent.max_token_budget})."
                run.tokens_used = result.tokens_used
                run.finished_at = datetime.now(UTC)
                db.flush()
                return run

            run.output = result.to_dict()
            run.steps = snapshot.get("steps", []) + [{"stage": "reason", "provider": result.provider_kind}]
            run.tokens_used = result.tokens_used
            run.tool_calls_made = tool_calls
            run.model_used = result.model
            run.provider_used = result.provider_kind
            run.simulated = result.simulated
            run.status = AgentRunStatus.SUCCEEDED.value
            run.finished_at = datetime.now(UTC)

            # Persist the conclusion as a MODEL_INFERENCE hypothesis (never fact).
            if write_hypothesis and incident_id and result.claim.has_evidence:
                claim = result.claim
                db.add(Hypothesis(
                    tenant_id=tenant_id, data_scope=scope, incident_id=incident_id,
                    statement=claim.claim, is_primary=False, confidence=claim.confidence,
                    status="open", supporting_evidence_ids=claim.evidence_ids,
                    missing_evidence=claim.missing_evidence,
                    attack_techniques=[m.technique_id for m in claim.attack_mapping],
                    produced_by=f"agent:{agent_key}",
                ))
                db.add(Evidence(
                    tenant_id=tenant_id, data_scope=scope, incident_id=incident_id,
                    kind=EvidenceKind.MODEL_INFERENCE.value,
                    title=f"[AI:{agent_key}] {claim.claim[:120]}",
                    content=claim.supporting_explanation, source=result.model,
                    produced_by=f"agent:{agent_key}", confidence=claim.confidence,
                    attack_techniques=[m.technique_id for m in claim.attack_mapping],
                ))
            db.flush()
            bus.publish_soon(Event(
                type="agent.finished", scope=scope, tenant_id=str(tenant_id),
                data={"agent": agent_key, "run_id": str(run.id), "status": run.status,
                      "confidence": result.claim.confidence, "simulated": result.simulated}))
        except Exception as exc:  # noqa: BLE001
            run.status = AgentRunStatus.FAILED.value
            run.error = str(exc)[:500]
            run.finished_at = datetime.now(UTC)
            db.flush()
        return run

    def run_investigation(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        incident_id: uuid.UUID,
        scope: str,
        actor_label: str = "system",
    ) -> dict:
        """Coordinator workflow graph: triage -> evidence -> specialist ->
        independent verification. Each step is a bounded AgentRun."""
        inc = db.get(Incident, incident_id)
        if inc is None:
            raise ValueError("Incident not found")

        # Pick a domain specialist by the incident's dominant technique.
        specialist = self._specialist_for(inc)
        plan = ["triage_agent", "evidence_collector", specialist, "independent_verifier"]
        runs = []
        for agent_key in plan:
            run = self.run_agent(db, tenant_id, agent_key, incident_id, scope,
                                 actor_label=actor_label)
            runs.append({"agent": agent_key, "run_id": str(run.id), "status": run.status,
                         "confidence": (run.output or {}).get("claim", {}).get("confidence")})
        db.commit()
        return {"incident_id": str(incident_id), "plan": plan, "runs": runs}

    def _specialist_for(self, inc: Incident) -> str:
        techniques = " ".join(inc.attack_techniques or [])
        tactics = " ".join(inc.attack_tactics or [])
        if any(t in techniques for t in ["T1078", "T1110", "T1621", "T1098"]):
            return "identity_investigator"
        if any(t in techniques for t in ["T1071", "T1090", "T1573", "T1048"]):
            return "network_investigator"
        if any(t in techniques for t in ["T1566", "T1204"]):
            return "email_investigator"
        if any(t in techniques for t in ["T1552", "T1078.004", "T1580"]) or "Cloud" in tactics:
            return "cloud_investigator"
        return "endpoint_investigator"


orchestrator = AgentOrchestrator()
