"""Durable playbook workflow engine.

A persisted state machine: the run's state and full step history are written
to ``WorkflowRun`` after every step (a new list object each time, so the JSON
column change is always detected), so a run survives process restart, worker
failure and approval delays — it pauses at ``WAITING_APPROVAL`` and resumes
later without re-running completed steps.

Semantics:
* ``condition`` steps are evaluated against the incident
  (``confidence_gte``, ``severity_in``, ``scenario_key``). A false condition
  ends the run with outcome ``condition_not_met``; the remaining steps are
  recorded as skipped.
* A step that fails halts the run (status ``failed``) unless the playbook's
  step sets ``"on_failure": "continue"``. Failures are never reported as a
  completed run.
* ``approval`` steps can only be passed by a principal holding
  ``approval:decide`` and the step's ``required_role`` (or a role with
  authority over it).
* ``response_action`` steps never execute directly — they create a
  ResponseAction through the response gateway, which applies policy and
  approval.
* Idempotency keys are scoped to the tenant.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.permissions import APPROVAL_AUTHORITY
from ..models import Evidence, Incident, Playbook, PlaybookVersion, WorkflowRun
from ..models.enums import EvidenceKind, WorkflowStatus
from . import audit, response
from .agents import orchestrator
from .events import Event, bus
from .tool_broker import broker
from .tool_broker.broker import ToolBrokerError

STEP_TYPES = {"trigger", "condition", "enrichment", "query", "agent_task", "approval", "delay",
              "branch", "parallel", "response_action", "verification", "rollback",
              "notification", "case_update", "report"}


class WorkflowError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def validate_graph(graph: dict) -> list[dict]:
    steps = (graph or {}).get("steps")
    if not isinstance(steps, list):
        raise WorkflowError("invalid_graph", "graph.steps must be a list")
    seen: set[str] = set()
    for step in steps:
        if not isinstance(step, dict) or not step.get("id") or step.get("type") not in STEP_TYPES:
            raise WorkflowError("invalid_step", f"Each step needs an id and a type in {sorted(STEP_TYPES)}")
        if step["id"] in seen:
            raise WorkflowError("duplicate_step", f"Duplicate step id '{step['id']}'")
        seen.add(step["id"])
    return steps


def start_workflow(db: Session, principal: Principal, playbook_key: str,
                   incident_id: uuid.UUID | None, scope: str,
                   idempotency_key: str | None = None) -> WorkflowRun:
    pb = db.execute(select(Playbook).where(
        Playbook.tenant_id == principal.tenant_id, Playbook.key == playbook_key)).scalar_one_or_none()
    if pb is None:
        raise WorkflowError("not_found", f"Unknown playbook: {playbook_key}")
    if not pb.enabled:
        raise WorkflowError("disabled", "Playbook is disabled.")
    if incident_id is not None:
        inc = db.get(Incident, incident_id)
        if inc is None or inc.tenant_id != principal.tenant_id or inc.data_scope != scope:
            raise WorkflowError("not_found", "Incident not found.")
    if idempotency_key:
        existing = db.execute(select(WorkflowRun).where(
            WorkflowRun.tenant_id == principal.tenant_id,
            WorkflowRun.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing:
            return existing
    run = WorkflowRun(
        tenant_id=principal.tenant_id, playbook_key=playbook_key,
        playbook_version=pb.current_version, incident_id=incident_id,
        status=WorkflowStatus.PENDING.value, data_scope=scope,
        context={"actor": principal.email, "actor_id": str(principal.user_id)},
        step_history=[], idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()
    audit.record(db, action="workflow.started", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="workflow_run", resource_id=str(run.id), data_scope=scope,
                 detail={"playbook": playbook_key})
    bus.publish_soon(Event(type="workflow.started", scope=scope, tenant_id=str(principal.tenant_id),
                           data={"run_id": str(run.id), "playbook": playbook_key}))
    _advance(db, principal, run)
    return run


def resume_workflow(db: Session, principal: Principal, run: WorkflowRun,
                    decision: str = "approve", note: str = "") -> WorkflowRun:
    if run.status != WorkflowStatus.WAITING_APPROVAL.value:
        raise WorkflowError("not_waiting", f"Run is {run.status}, not waiting for approval.")
    step = next((s for s in _graph(db, run) if s["id"] == run.current_step), None)
    required = (step or {}).get("required_role", "incident_commander")
    if not principal.has("approval:decide"):
        raise WorkflowError("forbidden", "Missing approval:decide permission.")
    allowed = APPROVAL_AUTHORITY.get(required, {required})
    if not set(principal.roles) & allowed:
        raise WorkflowError("wrong_approver_role", f"This step requires role '{required}'.")
    history = list(run.step_history or [])
    history.append({"id": run.current_step, "type": "approval", "status": "done",
                    "result": {"ok": decision == "approve", "decision": decision,
                               "by": principal.email, "note": note[:1000]},
                    "ts": _now()})
    run.step_history = history
    audit.record(db, action=f"workflow.approval_{decision}", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=run.tenant_id,
                 resource_type="workflow_run", resource_id=str(run.id), data_scope=run.data_scope,
                 detail={"step": run.current_step, "note": note[:200]})
    if decision != "approve":
        _finish(db, run, WorkflowStatus.CANCELLED.value, outcome="approval_rejected")
        return run
    _advance(db, principal, run)
    return run


def _graph(db: Session, run: WorkflowRun) -> list[dict]:
    pb = db.execute(select(Playbook).where(
        Playbook.tenant_id == run.tenant_id, Playbook.key == run.playbook_key)).scalar_one_or_none()
    if pb is None:
        return []
    ver = db.execute(select(PlaybookVersion).where(
        PlaybookVersion.playbook_id == pb.id, PlaybookVersion.version == run.playbook_version)
    ).scalar_one_or_none() or db.execute(select(PlaybookVersion).where(
        PlaybookVersion.playbook_id == pb.id, PlaybookVersion.is_active.is_(True))).scalar_one_or_none()
    return (ver.graph or {}).get("steps", []) if ver else []


def _record(db: Session, run: WorkflowRun, entry: dict) -> None:
    # Always assign a NEW list so SQLAlchemy detects the JSON change.
    run.step_history = [*(run.step_history or []), entry]
    db.flush()


def _finish(db: Session, run: WorkflowRun, status: str, outcome: str,
            error: str | None = None) -> None:
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.current_step = None
    run.error = error
    run.context = {**(run.context or {}), "outcome": outcome}
    bus.publish_soon(Event(type=f"workflow.{status}", scope=run.data_scope,
                           tenant_id=str(run.tenant_id),
                           data={"run_id": str(run.id), "outcome": outcome}))
    db.flush()


def _advance(db: Session, principal: Principal, run: WorkflowRun) -> None:
    steps = _graph(db, run)
    run.status = WorkflowStatus.RUNNING.value
    run.started_at = run.started_at or datetime.now(UTC)
    done = {h["id"] for h in (run.step_history or []) if h.get("status") in ("done", "skipped")}

    for idx, step in enumerate(steps):
        if step["id"] in done:
            continue
        stype = step.get("type")
        run.current_step = step["id"]

        if stype == "approval":
            run.status = WorkflowStatus.WAITING_APPROVAL.value
            _record(db, run, {"id": step["id"], "type": stype, "name": step.get("name"),
                              "status": "waiting", "required_role": step.get("required_role"),
                              "ts": _now()})
            bus.publish_soon(Event(type="workflow.waiting_approval", scope=run.data_scope,
                                   tenant_id=str(run.tenant_id),
                                   data={"run_id": str(run.id), "step": step["id"]}))
            return

        if stype == "condition":
            ok, detail = _evaluate_condition(db, run, step.get("if") or {})
            _record(db, run, {"id": step["id"], "type": stype, "name": step.get("name"),
                              "status": "done", "result": {"ok": True, "passed": ok, **detail},
                              "ts": _now()})
            if not ok:
                for rest in steps[idx + 1:]:
                    _record(db, run, {"id": rest["id"], "type": rest.get("type"),
                                      "name": rest.get("name"), "status": "skipped",
                                      "result": {"reason": "condition_not_met"}, "ts": _now()})
                _finish(db, run, WorkflowStatus.COMPLETED.value, outcome="condition_not_met")
                return
            continue

        result = _execute_step(db, principal, run, step)
        _record(db, run, {"id": step["id"], "type": stype, "name": step.get("name"),
                          "status": "done" if result.get("ok") else "failed",
                          "result": result, "ts": _now()})
        if not result.get("ok") and step.get("on_failure", "halt") != "continue":
            _finish(db, run, WorkflowStatus.FAILED.value, outcome="step_failed",
                    error=f"Step {step['id']} failed: {result.get('error') or result.get('message')}")
            return

    _finish(db, run, WorkflowStatus.COMPLETED.value, outcome="completed")


def _evaluate_condition(db: Session, run: WorkflowRun, cond: dict) -> tuple[bool, dict]:
    inc = db.get(Incident, run.incident_id) if run.incident_id else None
    if inc is None or inc.tenant_id != run.tenant_id:
        return False, {"reason": "no incident"}
    checks = {}
    if "confidence_gte" in cond:
        checks["confidence_gte"] = inc.confidence >= float(cond["confidence_gte"])
    if "severity_in" in cond:
        checks["severity_in"] = inc.severity in cond["severity_in"]
    if "scenario_key" in cond:
        checks["scenario_key"] = inc.scenario_key == cond["scenario_key"]
    return all(checks.values()), {"checks": checks, "confidence": inc.confidence,
                                  "severity": inc.severity}


def _execute_step(db: Session, principal: Principal, run: WorkflowRun, step: dict) -> dict:
    stype = step.get("type")
    inc_id = run.incident_id
    try:
        if stype in ("trigger", "delay", "branch", "parallel"):
            return {"ok": True, "note": f"{stype} step recorded (no side effect)."}
        if stype == "enrichment":
            if not (step.get("tool") and inc_id):
                return {"ok": False, "error": "enrichment needs a tool and an incident"}
            try:
                res = broker.execute(db, run.tenant_id, step["tool"], {"incident_id": str(inc_id)},
                                     scope=run.data_scope, incident_id=inc_id)
                return {"ok": res["success"], "tool": step["tool"],
                        "simulated": (res.get("output") or {}).get("status") == "simulated"}
            except ToolBrokerError as exc:
                return {"ok": False, "error": exc.code}
        if stype == "query":
            return {"ok": True, "note": "Query step recorded (read-only)."}
        if stype == "agent_task":
            if not (step.get("agent") and inc_id):
                return {"ok": False, "error": "agent_task needs an agent and an incident"}
            agent_run = orchestrator.run_agent(db, run.tenant_id, step["agent"], inc_id,
                                               run.data_scope, actor_label=f"workflow:{run.id}",
                                               workflow_run_id=run.id)
            return {"ok": agent_run.status == "succeeded", "agent_run_id": str(agent_run.id),
                    "status": agent_run.status}
        if stype == "response_action":
            if not (step.get("action") and inc_id):
                return {"ok": False, "error": "response_action needs an action and an incident"}
            inc = db.get(Incident, inc_id)
            fact = db.execute(select(Evidence).where(
                Evidence.tenant_id == run.tenant_id, Evidence.incident_id == inc_id,
                Evidence.kind == EvidenceKind.CONFIRMED_FACT.value)).scalars().first()
            value = (inc.affected_users if step["action"] in ("disable_account", "revoke_sessions")
                     else inc.affected_hosts) or inc.affected_hosts or inc.affected_users
            if not value:
                return {"ok": False, "error": "no target entity on the incident"}
            try:
                action = response.create_action(
                    db, principal, scope=run.data_scope, action_type=step["action"],
                    target={"value": value[0]}, incident_id=inc_id,
                    evidence_ids=[str(fact.id)] if fact else [],
                    confidence=inc.confidence,
                    expected_outcome=f"Playbook {run.playbook_key} step {step['id']}",
                    requested_by_kind="automation",
                )
                return {"ok": True, "action_id": str(action.id), "status": action.status}
            except response.ResponseError as exc:
                return {"ok": False, "error": exc.code, "message": exc.message}
        if stype in ("verification", "rollback", "notification", "case_update", "report"):
            return {"ok": True, "note": f"{stype} step recorded; the corresponding operation is "
                                        "performed through its own governed API."}
        return {"ok": False, "error": f"unsupported step type {stype}"}
    except Exception as exc:  # noqa: BLE001 — a failing step fails the run, visibly
        return {"ok": False, "error": str(exc)[:200]}


def _now() -> str:
    return datetime.now(UTC).isoformat()
