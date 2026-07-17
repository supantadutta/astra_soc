"""Evidence-first AI schema, policy engine, and action safety."""
import pytest

from astrasoc.schemas.ai_output import AIOutputValidationError, validate_ai_output
from astrasoc.services.policy import PolicyInput, evaluate_policy


def test_evidence_first_valid_claim():
    c = validate_ai_output({"claim": "compromise", "confidence": 0.8, "evidence_ids": ["e1"]})
    ok, _ = c.can_justify_response()
    assert ok


def test_evidence_first_rejects_malformed():
    with pytest.raises(AIOutputValidationError):
        validate_ai_output({"claim": "x", "confidence": 5})  # confidence out of range


def test_claim_without_evidence_cannot_justify():
    c = validate_ai_output({"claim": "compromise", "confidence": 0.95, "evidence_ids": []})
    ok, reason = c.can_justify_response()
    assert not ok and "evidence" in reason


POLICY = {
    "defaults": {"min_confidence": 0.7, "effect": "require_approval"},
    "rules": [
        {"name": "deny_low", "if": {"confidence_lt": 0.5}, "effect": "deny", "reason": "low"},
        {"name": "deny_no_ev", "if": {"evidence_count_lt": 1}, "effect": "deny", "reason": "no ev"},
        {"name": "crit_approve", "if": {"asset_criticality_in": ["high", "critical"]},
         "effect": "require_approval", "approver_role": "incident_commander", "reason": "crit"},
        {"name": "auto_ok", "if": {"reversible_eq": True, "confidence_gte": 0.9,
                                   "asset_criticality_in": ["low"]}, "effect": "allow", "reason": "ok"},
    ],
}


def test_policy_denies_low_confidence():
    r = evaluate_policy(POLICY, PolicyInput(action="block_ip", confidence=0.3, evidence_count=1))
    assert r.effect == "deny"


def test_policy_denies_no_evidence():
    r = evaluate_policy(POLICY, PolicyInput(action="block_ip", confidence=0.9, evidence_count=0))
    assert r.effect == "deny"


def test_policy_critical_requires_approval():
    r = evaluate_policy(POLICY, PolicyInput(action="isolate_endpoint", confidence=0.9,
                                            evidence_count=2, asset_criticality="critical",
                                            reversible=True))
    assert r.effect == "require_approval"
    assert r.approver_role == "incident_commander"


def test_policy_auto_allows_safe_case():
    r = evaluate_policy(POLICY, PolicyInput(action="block_ip", confidence=0.95, evidence_count=2,
                                            asset_criticality="low", reversible=True))
    assert r.effect == "allow"
