"""Built-in policy-as-code engine (OPA-compatible shape).

Evaluates response-action requests against declarative rules (seeded in
``SystemSetting['response_policy']``). The result is one of allow / deny /
require_approval plus obligations (e.g. which role must approve). When an
external OPA is configured (``ASTRASOC_OPA_URL``) the same PolicyInput can be
POSTed to it instead; the decision shape is identical so callers don't change.

This engine is deterministic and independent of any LLM. An LLM can never
change or bypass a policy decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...models.enums import PolicyEffect


@dataclass
class PolicyInput:
    action: str
    asset_criticality: str = "low"
    confidence: float = 0.0
    evidence_count: int = 0
    reversible: bool = True
    blast_radius: int = 1
    data_scope: str = "DEMO"
    requester_permissions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class PolicyResult:
    effect: str
    reasons: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)
    approver_role: str | None = None
    obligations: list[dict] = field(default_factory=list)
    policy_name: str = "response_policy"

    @property
    def allowed(self) -> bool:
        return self.effect == PolicyEffect.ALLOW.value

    @property
    def denied(self) -> bool:
        return self.effect == PolicyEffect.DENY.value

    @property
    def needs_approval(self) -> bool:
        return self.effect == PolicyEffect.REQUIRE_APPROVAL.value


_CRIT_ORDER = ["info", "low", "medium", "high", "critical"]


def _match(cond: dict, inp: PolicyInput) -> bool:
    for key, val in cond.items():
        if key == "confidence_lt" and not (inp.confidence < val):
            return False
        if key == "confidence_gte" and not (inp.confidence >= val):
            return False
        if key == "evidence_count_lt" and not (inp.evidence_count < val):
            return False
        if key == "asset_criticality_in" and inp.asset_criticality not in val:
            return False
        if key == "reversible_eq" and inp.reversible != val:
            return False
        if key == "blast_radius_gt" and not (inp.blast_radius > val):
            return False
        if key == "action_in" and inp.action not in val:
            return False
    return True


def evaluate_policy(policy: dict, inp: PolicyInput) -> PolicyResult:
    """Evaluate rules in order. Deny wins immediately; otherwise the first
    matching allow/require_approval rule decides. Falls back to the policy
    default (require_approval) so nothing is allowed by omission."""
    defaults = policy.get("defaults", {})
    min_conf = defaults.get("min_confidence", 0.7)
    rules = policy.get("rules", [])

    matched: list[str] = []
    reasons: list[str] = []
    decision: str | None = None
    approver: str | None = None

    # Deny rules take precedence — scan for any deny first.
    for rule in rules:
        if rule.get("effect") == PolicyEffect.DENY.value and _match(rule.get("if", {}), inp):
            return PolicyResult(
                effect=PolicyEffect.DENY.value, reasons=[rule.get("reason", "Denied by policy.")],
                matched_rules=[rule["name"]], policy_name=policy.get("name", "response_policy"),
            )

    for rule in rules:
        effect = rule.get("effect")
        if effect == PolicyEffect.DENY.value:
            continue
        if _match(rule.get("if", {}), inp):
            matched.append(rule["name"])
            reasons.append(rule.get("reason", ""))
            if effect == PolicyEffect.REQUIRE_APPROVAL.value:
                decision = PolicyEffect.REQUIRE_APPROVAL.value
                approver = approver or rule.get("approver_role")
            elif effect == PolicyEffect.ALLOW.value and decision != PolicyEffect.REQUIRE_APPROVAL.value:
                decision = PolicyEffect.ALLOW.value

    # Global confidence floor.
    if inp.confidence < min_conf and decision == PolicyEffect.ALLOW.value:
        decision = PolicyEffect.REQUIRE_APPROVAL.value
        reasons.append(f"Confidence below auto-allow floor ({min_conf}).")
        approver = approver or "incident_commander"

    if decision is None:
        decision = defaults.get("effect", PolicyEffect.REQUIRE_APPROVAL.value)
        reasons.append("No allow rule matched; defaulting to approval.")
        approver = approver or "incident_commander"

    obligations = []
    if decision == PolicyEffect.REQUIRE_APPROVAL.value:
        obligations.append({"type": "approval", "role": approver or "incident_commander"})

    return PolicyResult(
        effect=decision, reasons=[r for r in reasons if r], matched_rules=matched,
        approver_role=approver, obligations=obligations,
        policy_name=policy.get("name", "response_policy"),
    )
