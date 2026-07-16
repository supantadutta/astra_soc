"""Durable playbook workflow engine.

A persisted state machine: state is written to ``WorkflowRun`` after every step,
so a run survives process restart, worker failure, API timeout, LLM failure and
(especially) approval delays — it simply pauses at ``WAITING_APPROVAL`` and is
resumed later. This mirrors the Temporal model used in production; the demo
profile runs it in-process without requiring a Temporal cluster.

Response-action steps NEVER execute directly — they create a ResponseAction
through the response gateway, which enforces policy + approval + verification.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..models import Incident, Playbook, PlaybookVersion, WorkflowRun
from ..models.enums import WorkflowStatus
from . import audit, response
from .agents import orchestrator
from .events import Event, bus
from .tool_broker import broker
from .tool_broker.broker import ToolBrokerError


def start_workflow(db: Session, principal: Principal, playbook_key: str,
                   incident_id: uuid.UUID | None, scope: str,
                   idempotency_key: str | None = None) -> WorkflowRun:
    pb = db.execute(select(Playbook).where(
        Playbook.tenant_id == principal.tenant_id, Playbook.key == playbook_key)).scalar_one_or_none()
    if pb is None:
        raise ValueError(f"Unknown playbook: {playbook_key}")
    if idempotency_key:
        existing = db.execute(select(WorkflowRun).where(
            WorkflowRun.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing:
            return existing
    run = WorkflowRun(
        tenant_id=principal.tenant_id, playbook_key=playbook_key,
        playbook_version=pb.current_version, incident_id=incident_id,
        status=WorkflowStatus.PENDING.value, data_scope=scope,
        context={"actor": principal.email}, step_history=[],
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()
    audit.record(db, action="workflow.started", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="workflow_run",
                 resource_id=str(run.id), data_scope=scope, detail={"playbook": playbook_key})
    bus.publish_soon(Event(type="workflow.started", scope=scope, tenant_id=str(principal.tenant_id),
                           data={"run_id": str(run.id), "playbook": playbook_key}))
    _advance(db, principal, run)
    return run


def resume_workflow(db: Session, principal: Principal, run: WorkflowRun) -> WorkflowRun:
    if run.status != WorkflowStatus.WAITING_APPROVAL.value:
        return run
    _advance(db, principal, run, resuming=True)
    return run


def _graph(db: Session, run: WorkflowRun) -> list[dict]:
    pb = db.execute(select(Playbook).where(
        Playbook.tenant_id == run.tenant_id, Playbook.key == run.playbook_key)).scalar_one_or_none()
    if pb is None:
        return []
    ver = db.execute(select(PlaybookVersion).where(
        PlaybookVersion.playbook_id == pb.id, PlaybookVersion.is_active.is_(True))
    ).scalar_one_or_none()
    return (ver.graph or {}).get("steps", []) if ver else []


def _advance(db: Session, principal: Principal, run: WorkflowRun, resuming: bool = False) -> None:
    steps = _graph(db, run)
    run.status = WorkflowStatus.RUNNING.value
    if run.started_at is None:
        run.started_at = datetime.now(UTC)

    history = list(run.step_history or [])
    done_ids = {h["id"] for h in history if h.get("status") in ("done", "skipped")}

    for step in steps:
        if step["id"] in done_ids:
            continue
        stype = step.get("type")

        # Approval gate: pause and wait for external decision.
        if stype == "approval" and not resuming:
            run.status = WorkflowStatus.WAITING_APPROVAL.value
            run.current_step = step["id"]
            history.append({"id": step["id"], "type": stype, "name": step.get("name"),
                            "status": "waiting", "ts": _now()})
            run.step_history = history
            db.flush()
            bus.publish_soon(Event(type="workflow.waiting_approval", scope=run.data_scope,
                                   tenant_id=str(run.tenant_id),
                                   data={"run_id": str(run.id), "step": step["id"]}))
            return
        if stype == "approval" and resuming:
            resuming = False  # consumed the resume
            history.append({"id": step["id"], "type": stype, "name": step.get("name"),
                            "status": "done", "result": "approved", "ts": _now()})
            continue

        result = _execute_step(db, principal, run, step)
        history.append({"id": step["id"], "type": stype, "name": step.get("name"),
                        "status": "done", "result": result, "ts": _now()})
        run.step_history = history
        db.flush()

    run.status = WorkflowStatus.COMPLETED.value
    run.finished_at = datetime.now(UTC)
    run.current_step = None
    bus.publish_soon(Event(type="workflow.completed", scope=run.data_scope,
                           tenant_id=str(run.tenant_id), data={"run_id": str(run.id)}))
    db.flush()


def _execute_step(db: Session, principal: Principal, run: WorkflowRun, step: dict):
    stype = step.get("type")
    inc_id = run.incident_id
    try:
        if stype in ("trigger", "delay", "case_update", "notification", "report", "branch",
                     "parallel", "condition"):
            return {"ok": True, "note": f"{stype} step recorded."}
        if stype == "enrichment" and step.get("tool") and inc_id:
            try:
                res = broker.execute(db, run.tenant_id, step["tool"],
                                     {"incident_id": str(inc_id)}, scope=run.data_scope,
                                     incident_id=inc_id)
                return {"ok": res["success"], "tool": step["tool"]}
            except ToolBrokerError as exc:
                return {"ok": False, "error": exc.code}
        if stype == "query":
            return {"ok": True, "note": "Query step (read-only) recorded."}
        if stype == "agent_task" and step.get("agent") and inc_id:
            agent_run = orchestrator.run_agent(db, run.tenant_id, step["agent"], inc_id,
                                               run.data_scope, actor_label=f"workflow:{run.id}",
                                               workflow_run_id=run.id)
            return {"ok": agent_run.status == "succeeded", "agent_run_id": str(agent_run.id)}
        if stype == "response_action" and step.get("action") and inc_id:
            # Create (not execute) an action so it goes through policy + approval.
            inc = db.get(Incident, inc_id)
            from ..models import Evidence
            from ..models.enums import EvidenceKind
            fact = db.execute(select(Evidence).where(
                Evidence.incident_id == inc_id,
                Evidence.kind == EvidenceKind.CONFIRMED_FACT.value)).scalars().first()
            target = {"value": inc.affected_hosts[0] if inc and inc.affected_hosts else
                      (inc.affected_users[0] if inc and inc.affected_users else "unknown")}
            try:
                action = response.create_action(
                    db, principal, scope=run.data_scope, action_type=step["action"],
                    target=target, incident_id=inc_id,
                    evidence_ids=[str(fact.id)] if fact else [],
                    confidence=inc.confidence if inc else 0.6,
                    expected_outcome=f"Playbook {run.playbook_key} step {step['id']}",
                    requested_by_kind="automation",
                )
                return {"ok": True, "action_id": str(action.id), "status": action.status}
            except response.ResponseError as exc:
                return {"ok": False, "error": exc.code, "message": exc.message}
        if stype == "verification":
            return {"ok": True, "note": "Verification step recorded."}
        if stype == "rollback":
            return {"ok": True, "note": "Rollback step recorded."}
        return {"ok": True, "note": f"Unhandled step type {stype} recorded."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def _now() -> str:
    return datetime.now(UTC).isoformat()
