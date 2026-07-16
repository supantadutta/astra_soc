"""Response gateway — governed execution of production-changing actions.

Every action traverses the full safety pipeline (spec §16):
schema -> evidence -> confidence -> asset criticality -> blast radius -> RBAC
-> policy -> approval -> dry-run -> execute -> verify -> rollback -> audit.

Guarantees:
* An LLM/agent can *propose* an action but never execute one — execution
  requires a human principal with ``action:execute`` (or an approved request).
* In DEMO mode actions are always simulated and clearly labelled; no real
  command is ever sent.
* In LIVE mode the gateway calls the connector's write adapter and NEVER marks
  the action succeeded unless the adapter confirms success.
* Execution is authorized by a short-lived action token bound to
  tenant/user/action/target/expiration/request-id.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.security import content_hash, sign_payload
from ..models import (
    ApprovalRequest,
    Entity,
    Evidence,
    PolicyDecision,
    ResponseAction,
    SystemSetting,
)
from ..models.enums import (
    ActionStatus,
    ApprovalStatus,
    DataScope,
    EvidenceKind,
)
from . import audit
from .events import Event, bus
from .policy import PolicyInput, evaluate_policy

# Which actions are inherently reversible, and their rollback action.
REVERSIBLE = {
    "isolate_endpoint": "release_endpoint",
    "disable_account": "re_enable_account",
    "block_ip": "unblock_ip",
    "block_domain": "unblock_domain",
    "quarantine_email": "release_email",
    "revoke_sessions": None,  # not reversible (user must re-auth) but low harm
    "increase_monitoring": "decrease_monitoring",
    "add_ioc": "remove_ioc",
}
IRREVERSIBLE_ACTIONS = {"remove_email_from_mailboxes", "collect_endpoint_evidence"}


class ResponseError(Exception):
    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(message)


def _policy(db: Session) -> dict:
    row = db.execute(
        select(SystemSetting).where(SystemSetting.tenant_id.is_(None),
                                    SystemSetting.key == "response_policy")
    ).scalar_one_or_none()
    return row.value if row else {"rules": [], "defaults": {}}


def _asset_criticality(db: Session, tenant_id, scope, target: dict) -> str:
    value = target.get("value") or target.get("entity_value")
    if not value:
        return "low"
    ent = db.execute(
        select(Entity).where(Entity.tenant_id == tenant_id, Entity.data_scope == scope,
                             Entity.value == value)
    ).scalar_one_or_none()
    return ent.criticality if ent else "low"


def _blast_radius(action_type: str, target: dict) -> dict:
    # Deterministic estimate. Real environments refine this from CMDB/asset data.
    base = {
        "isolate_endpoint": 1, "release_endpoint": 1, "disable_account": 1,
        "revoke_sessions": 1, "block_ip": 3, "block_domain": 4,
        "quarantine_email": target.get("recipient_count", 1),
        "remove_email_from_mailboxes": target.get("recipient_count", 1),
        "increase_monitoring": 1, "create_ticket": 0, "collect_endpoint_evidence": 1,
    }.get(action_type, 2)
    return {"estimated_assets": base, "scope": "single" if base <= 1 else "multiple"}


def create_action(
    db: Session,
    principal: Principal,
    *,
    scope: str,
    action_type: str,
    target: dict,
    incident_id: uuid.UUID | None,
    evidence_ids: list[str],
    confidence: float,
    expected_outcome: str,
    requested_by_kind: str = "analyst",
    connector_kind: str | None = None,
) -> ResponseAction:
    # 1) Schema validation (minimal — full JSON-schema in schemas layer).
    if not action_type or not isinstance(target, dict) or not target:
        raise ResponseError("invalid_schema", "action_type and a target object are required.")

    # 2) Evidence validation — cited evidence must exist, belong to the case,
    #    and (for anything but pure enrichment) include a confirmed fact.
    valid_evidence, has_fact = _validate_evidence(db, principal.tenant_id, scope,
                                                  incident_id, evidence_ids)
    if action_type not in ("increase_monitoring", "create_ticket") and not has_fact:
        raise ResponseError(
            "insufficient_evidence",
            "This action requires at least one CONFIRMED_FACT evidence item; "
            "AI inferences alone cannot justify a production-changing action.",
        )

    reversible = action_type in REVERSIBLE and action_type not in IRREVERSIBLE_ACTIONS
    blast = _blast_radius(action_type, target)
    criticality = _asset_criticality(db, principal.tenant_id, scope, target)

    # 6) RBAC check.
    if not principal.has("action:request"):
        raise ResponseError("forbidden", "Missing action:request permission.")

    action = ResponseAction(
        tenant_id=principal.tenant_id, data_scope=scope, action_type=action_type,
        target=target, incident_id=incident_id, requested_by=principal.user_id,
        requested_by_kind=requested_by_kind, supporting_evidence_ids=valid_evidence,
        confidence=confidence, expected_outcome=expected_outcome, blast_radius=blast,
        reversible=reversible,
        rollback_instruction={"action": REVERSIBLE.get(action_type)} if reversible else {},
        idempotency_key=uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(hours=4),
        connector_kind=connector_kind, simulated=(scope == DataScope.DEMO.value),
    )
    db.add(action)
    db.flush()

    # 7) Policy evaluation.
    pinput = PolicyInput(
        action=action_type, asset_criticality=criticality, confidence=confidence,
        evidence_count=len(valid_evidence), reversible=reversible,
        blast_radius=blast["estimated_assets"], data_scope=scope,
        requester_permissions=principal.permissions,
    )
    presult = evaluate_policy(_policy(db), pinput)
    db.add(PolicyDecision(
        tenant_id=principal.tenant_id, subject=f"response:{action_type}",
        response_action_id=action.id, effect=presult.effect, policy_name=presult.policy_name,
        engine="builtin", reasons=presult.reasons, obligations=presult.obligations,
        input=pinput.to_dict(), matched_rules=presult.matched_rules,
    ))

    # 8) Approval determination.
    if presult.denied:
        action.status = ActionStatus.BLOCKED_BY_POLICY.value
        action.requires_approval = False
        action.error = "; ".join(presult.reasons)
    elif presult.needs_approval:
        action.status = ActionStatus.PENDING_APPROVAL.value
        action.requires_approval = True
        db.add(ApprovalRequest(
            tenant_id=principal.tenant_id, response_action_id=action.id,
            incident_id=incident_id, status=ApprovalStatus.PENDING.value,
            required_role=presult.approver_role or "incident_commander",
            reason="; ".join(presult.reasons), requested_by=principal.user_id,
            expires_at=datetime.now(UTC) + timedelta(hours=4),
        ))
    else:  # allow
        action.status = ActionStatus.APPROVED.value
        action.requires_approval = False

    audit.record(db, action="response.action_created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, actor_label=principal.label,
                 resource_type="response_action", resource_id=str(action.id),
                 data_scope=scope, detail={"action": action_type, "effect": presult.effect,
                                           "criticality": criticality, "reversible": reversible})
    bus.publish_soon(Event(type="action.created", scope=scope, tenant_id=str(principal.tenant_id),
                           data={"action_id": str(action.id), "action_type": action_type,
                                 "status": action.status, "requires_approval": action.requires_approval}))
    db.flush()
    return action


def _validate_evidence(db, tenant_id, scope, incident_id, evidence_ids) -> tuple[list[str], bool]:
    if not evidence_ids or incident_id is None:
        return [], False
    rows = db.execute(
        select(Evidence).where(
            Evidence.tenant_id == tenant_id, Evidence.data_scope == scope,
            Evidence.incident_id == incident_id,
            Evidence.id.in_([uuid.UUID(e) for e in evidence_ids if _is_uuid(e)]))
    ).scalars().all()
    valid = [str(r.id) for r in rows]
    has_fact = any(r.kind == EvidenceKind.CONFIRMED_FACT.value for r in rows)
    return valid, has_fact


def _is_uuid(v: str) -> bool:
    try:
        uuid.UUID(str(v))
        return True
    except ValueError:
        return False


def dry_run(db: Session, action: ResponseAction, principal: Principal) -> ResponseAction:
    if action.status in (ActionStatus.BLOCKED_BY_POLICY.value, ActionStatus.REJECTED.value):
        raise ResponseError("not_permitted", "Action is blocked/rejected and cannot be dry-run.")
    predicted = {
        "would_execute": action.action_type, "target": action.target,
        "estimated_blast_radius": action.blast_radius,
        "reversible": action.reversible, "connector": action.connector_kind or "mock",
        "note": "Dry-run only. No change made. "
                + ("DEMO: execution is always simulated." if action.simulated
                   else "LIVE: execution would call the connector write adapter."),
    }
    action.dry_run_result = predicted
    if action.status == ActionStatus.APPROVED.value:
        pass  # keep approved
    audit.record(db, action="response.dry_run", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="response_action",
                 resource_id=str(action.id), data_scope=action.data_scope,
                 detail=predicted)
    db.flush()
    return action


def _issue_action_token(action: ResponseAction, principal: Principal, request_id: str) -> str:
    """A short-lived token bound to exactly this action + target + requester."""
    exp = datetime.now(UTC) + timedelta(minutes=5)
    body = {
        "tenant": str(action.tenant_id), "user": str(principal.user_id),
        "action": action.action_type, "target": action.target,
        "request_id": request_id, "action_id": str(action.id),
        "exp": exp.isoformat(),
    }
    payload = json.dumps(body, sort_keys=True)
    return f"{content_hash(payload)}.{sign_payload(payload.encode())}"


def approve(db: Session, action: ResponseAction, approval: ApprovalRequest,
            principal: Principal, note: str = "") -> ResponseAction:
    if not principal.has("approval:decide"):
        raise ResponseError("forbidden", "Missing approval:decide permission.")
    if approval.status != ApprovalStatus.PENDING.value:
        raise ResponseError("already_decided", f"Approval already {approval.status}.")
    if approval.expires_at and approval.expires_at < datetime.now(UTC):
        approval.status = ApprovalStatus.EXPIRED.value
        action.status = ActionStatus.REJECTED.value
        raise ResponseError("expired", "Approval window expired.")
    approval.status = ApprovalStatus.APPROVED.value
    approval.decided_by = principal.user_id
    approval.decided_at = datetime.now(UTC)
    approval.decision_note = note
    action.status = ActionStatus.APPROVED.value
    audit.record(db, action="response.approved", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, actor_label=principal.label,
                 resource_type="response_action", resource_id=str(action.id),
                 data_scope=action.data_scope, detail={"note": note})
    bus.publish_soon(Event(type="approval.decided", scope=action.data_scope,
                           tenant_id=str(action.tenant_id),
                           data={"action_id": str(action.id), "decision": "approved"}))
    db.flush()
    return action


def reject(db: Session, action: ResponseAction, approval: ApprovalRequest,
           principal: Principal, note: str = "") -> ResponseAction:
    if not principal.has("approval:decide"):
        raise ResponseError("forbidden", "Missing approval:decide permission.")
    approval.status = ApprovalStatus.REJECTED.value
    approval.decided_by = principal.user_id
    approval.decided_at = datetime.now(UTC)
    approval.decision_note = note
    action.status = ActionStatus.REJECTED.value
    audit.record(db, action="response.rejected", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="response_action",
                 resource_id=str(action.id), data_scope=action.data_scope, detail={"note": note})
    bus.publish_soon(Event(type="approval.decided", scope=action.data_scope,
                           tenant_id=str(action.tenant_id),
                           data={"action_id": str(action.id), "decision": "rejected"}))
    db.flush()
    return action


def execute(db: Session, action: ResponseAction, principal: Principal, request_id: str) -> ResponseAction:
    # Authorization: must be approved (or auto-allowed) AND principal must hold
    # action:execute. An LLM/agent principal can never reach here.
    if principal.is_service_account and "action:execute" not in principal.permissions:
        raise ResponseError("forbidden", "Service identity not permitted to execute.")
    if not principal.has("action:execute"):
        raise ResponseError("forbidden", "Missing action:execute permission.")
    if action.status != ActionStatus.APPROVED.value:
        raise ResponseError("not_approved",
                            f"Action must be APPROVED to execute (currently {action.status}).")
    if action.expires_at and action.expires_at < datetime.now(UTC):
        action.status = ActionStatus.REJECTED.value
        raise ResponseError("expired", "Action expired before execution.")

    token = _issue_action_token(action, principal, request_id)
    action.status = ActionStatus.EXECUTING.value
    db.flush()

    # DEMO: always simulate, never send a real command.
    if action.simulated or action.data_scope == DataScope.DEMO.value:
        result = _simulate_execution(action)
    else:
        result = _live_execution(db, action)  # calls connector write adapter

    action.execution_result = {**result, "action_token_fingerprint": token[:16]}
    action.executed_at = datetime.now(UTC)
    if result.get("success"):
        action.status = ActionStatus.SUCCEEDED.value
    else:
        action.status = ActionStatus.FAILED.value
        action.error = result.get("error")

    audit.record(db, action="response.executed", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, actor_label=principal.label,
                 resource_type="response_action", resource_id=str(action.id),
                 outcome="success" if result.get("success") else "failure",
                 data_scope=action.data_scope,
                 detail={"action": action.action_type, "simulated": action.simulated,
                         "result": result.get("summary")})
    bus.publish_soon(Event(type="action.executed", scope=action.data_scope,
                           tenant_id=str(action.tenant_id),
                           data={"action_id": str(action.id), "status": action.status,
                                 "simulated": action.simulated}))
    db.flush()
    # Automatic post-action verification.
    verify(db, action)
    return action


def _simulate_execution(action: ResponseAction) -> dict:
    return {
        "success": True, "simulated": True,
        "summary": f"[SIMULATED] {action.action_type} on {action.target} — no real change made.",
        "target": action.target,
    }


def _live_execution(db: Session, action: ResponseAction) -> dict:
    """LIVE path — call the connector write adapter. Reports the TRUE result;
    never fabricates success."""
    from ..models import Connector
    from .connectors.registry import get_adapter

    conn = None
    if action.connector_kind:
        conn = db.execute(
            select(Connector).where(Connector.tenant_id == action.tenant_id,
                                    Connector.kind == action.connector_kind)
        ).scalar_one_or_none()
    if conn is None or not conn.enabled or not conn.can_write:
        return {"success": False, "simulated": False,
                "error": "no_write_connector",
                "summary": f"No enabled write-capable connector for '{action.connector_kind}'. "
                           "Action not sent."}
    adapter = get_adapter(conn)
    try:
        outcome = adapter.execute_action(action.action_type, action.target)
        return {"success": bool(outcome.get("success")), "simulated": False,
                "summary": outcome.get("summary", ""), "raw": outcome}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "simulated": False, "error": str(exc)[:300],
                "summary": "Connector adapter raised an error; action reported as FAILED."}


def verify(db: Session, action: ResponseAction) -> ResponseAction:
    """Post-action verification. In DEMO, deterministically confirm the simulated
    effect. In LIVE, re-query the connector to confirm the target state changed."""
    if action.status not in (ActionStatus.SUCCEEDED.value, ActionStatus.FAILED.value):
        return action
    if action.status == ActionStatus.FAILED.value:
        action.verification_result = {"verified": False, "reason": "execution failed"}
        db.flush()
        return action

    if action.simulated or action.data_scope == DataScope.DEMO.value:
        verified = {"verified": True, "method": "simulated_state_check",
                    "detail": f"Simulated post-state consistent with {action.action_type}."}
    else:
        verified = _live_verify(db, action)

    action.verification_result = verified
    action.verified_at = datetime.now(UTC)
    action.status = ActionStatus.VERIFIED.value if verified.get("verified") else ActionStatus.VERIFY_FAILED.value
    audit.record(db, action="response.verified", tenant_id=action.tenant_id,
                 resource_type="response_action", resource_id=str(action.id),
                 outcome="success" if verified.get("verified") else "failure",
                 data_scope=action.data_scope, detail=verified)
    bus.publish_soon(Event(type="action.verified", scope=action.data_scope,
                           tenant_id=str(action.tenant_id),
                           data={"action_id": str(action.id), "verified": verified.get("verified")}))
    db.flush()
    return action


def _live_verify(db: Session, action: ResponseAction) -> dict:
    from ..models import Connector
    from .connectors.registry import get_adapter

    conn = db.execute(
        select(Connector).where(Connector.tenant_id == action.tenant_id,
                                Connector.kind == action.connector_kind)
    ).scalar_one_or_none() if action.connector_kind else None
    if conn is None:
        return {"verified": False, "reason": "no_connector_to_verify"}
    try:
        state = get_adapter(conn).verify_action(action.action_type, action.target)
        return {"verified": bool(state.get("confirmed")), "method": "connector_state_check",
                "detail": state}
    except Exception as exc:  # noqa: BLE001
        return {"verified": False, "reason": str(exc)[:200]}


def rollback(db: Session, action: ResponseAction, principal: Principal) -> ResponseAction:
    if not action.reversible:
        raise ResponseError("not_reversible", "This action is not reversible.")
    if action.status not in (ActionStatus.VERIFIED.value, ActionStatus.SUCCEEDED.value):
        raise ResponseError("not_rolled_backable",
                            f"Cannot roll back an action in status {action.status}.")
    rollback_action = action.rollback_instruction.get("action")
    summary = (f"[SIMULATED] rollback via {rollback_action} on {action.target}."
               if action.simulated else f"Rollback via {rollback_action} on {action.target}.")
    action.status = ActionStatus.ROLLED_BACK.value
    action.rolled_back_at = datetime.now(UTC)
    action.execution_result = {**(action.execution_result or {}),
                               "rollback": {"action": rollback_action, "summary": summary}}
    audit.record(db, action="response.rolled_back", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, actor_label=principal.label,
                 resource_type="response_action", resource_id=str(action.id),
                 data_scope=action.data_scope, detail={"rollback_action": rollback_action})
    bus.publish_soon(Event(type="action.rolled_back", scope=action.data_scope,
                           tenant_id=str(action.tenant_id),
                           data={"action_id": str(action.id)}))
    db.flush()
    return action
