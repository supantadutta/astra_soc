"""Strict evidence-first AI output contract.

Every important AI claim the platform accepts MUST conform to
:class:`EvidenceFirstClaim`. Malformed output is rejected at the boundary
(:func:`validate_ai_output`). A claim with no valid evidence references cannot
be used to justify a response action — that rule is enforced by the response
gateway, not merely by convention.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AttackMapping(BaseModel):
    tactic: str = Field(..., description="MITRE ATT&CK tactic, e.g. 'Lateral Movement'")
    technique_id: str = Field(..., pattern=r"^T\d{4}(\.\d{3})?$")
    technique_name: str = ""


class AlternativeHypothesis(BaseModel):
    statement: str
    likelihood: float = Field(..., ge=0.0, le=1.0)


class EvidenceFirstClaim(BaseModel):
    """The mandatory shape of a substantive AI conclusion."""

    claim: str = Field(..., min_length=3)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_explanation: str = ""
    alternative_hypotheses: list[AlternativeHypothesis] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_queries: list[str] = Field(default_factory=list)
    attack_mapping: list[AttackMapping] = Field(default_factory=list)
    suggested_action: str | None = None
    model: str = "unknown"
    provider: str = "unknown"
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Set by the platform, not the model: whether external/untrusted content was
    # part of the context this claim was produced from.
    derived_from_untrusted_content: bool = False

    @field_validator("claim")
    @classmethod
    def _no_injection_echo(cls, v: str) -> str:
        return v.strip()

    @property
    def has_evidence(self) -> bool:
        return len(self.evidence_ids) > 0

    def can_justify_response(self, min_confidence: float = 0.7) -> tuple[bool, str]:
        """A claim may justify a response only if it cites evidence and clears
        the confidence bar. Returns (ok, reason)."""
        if not self.has_evidence:
            return False, "claim cites no evidence"
        if self.confidence < min_confidence:
            return False, f"confidence {self.confidence:.2f} below threshold {min_confidence:.2f}"
        return True, "ok"


class AIOutputValidationError(Exception):
    def __init__(self, errors: Any) -> None:
        self.errors = errors
        super().__init__("AI output failed schema validation")


def validate_ai_output(raw: dict[str, Any]) -> EvidenceFirstClaim:
    """Validate raw model output against the evidence-first contract.

    Raises :class:`AIOutputValidationError` on malformed output so callers can
    reject it rather than silently trusting a hallucinated structure.
    """
    try:
        return EvidenceFirstClaim.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError or others
        raise AIOutputValidationError(str(exc)) from exc
