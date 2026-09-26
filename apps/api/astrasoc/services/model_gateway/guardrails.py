"""Guardrails applied by the model gateway before any real LLM is called.

* **Tenant AI policy** — the tenant's operating-mode AI switch and LLM
  strategy (``simulated`` / ``private`` / ``hosted`` / ``hybrid`` /
  ``disabled``), the tenant's ``private_model_only`` setting and the
  service plan's ``external_llm`` entitlement decide which providers are
  eligible. The built-in simulated reasoner is always eligible unless AI is
  disabled.
* **Data residency** — a provider pinned to a region serves only tenants in
  that region (``global`` tenants accept any).
* **Classification** — a provider may only receive data up to its
  ``data_classification_allowance``; ``hybrid`` routes confidential and
  restricted work to private providers only.
* **Budgets** — provider daily token limits and the tenant's monthly token
  budget (from usage metering).
* **Untrusted content** — all case text (incident summary, evidence,
  timeline, hypotheses) is DLP-scrubbed, screened for prompt injection and
  wrapped in an explicit ``<untrusted_external_content>`` boundary before it
  is sent to a non-simulated provider.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ...models import ModelProvider, Tenant
from ...models.enums import ProviderKind
from ..injection import detect_injection, wrap_external
from ..metering import period_of, usage_for
from ..mode import get_mode
from ..tiers import has_feature

_CLASS_ORDER = ["public", "internal", "confidential", "restricted"]
_PRIVATE_KINDS = {ProviderKind.OLLAMA.value, ProviderKind.VLLM.value}


@dataclass
class AIPolicy:
    ai_enabled: bool
    strategy: str
    private_only: bool
    external_allowed: bool
    region: str
    monthly_budget: int | None
    monthly_used: float
    reasons: list[str] = field(default_factory=list)


def tenant_ai_policy(db: Session, tenant_id: uuid.UUID) -> AIPolicy:
    tenant = db.get(Tenant, tenant_id)
    mode = get_mode(db, tenant_id)
    settings_ = (tenant.settings or {}) if tenant else {}
    budget = settings_.get("monthly_token_budget")
    used = usage_for(db, [tenant_id], period_of())[tenant_id]["llm_tokens"] if budget else 0.0
    return AIPolicy(
        ai_enabled=mode.ai_enabled and mode.llm_strategy != "disabled",
        strategy=mode.llm_strategy,
        private_only=bool(settings_.get("private_model_only")) or mode.llm_strategy == "private",
        external_allowed=has_feature(db, tenant_id, "external_llm"),
        region=(tenant.region if tenant else "global") or "global",
        monthly_budget=int(budget) if budget else None,
        monthly_used=used,
    )


def _is_private(prov: ModelProvider) -> bool:
    return prov.private_only or prov.kind in _PRIVATE_KINDS


def provider_allowed(prov: ModelProvider, policy: AIPolicy,
                     classification: str = "internal") -> tuple[bool, str]:
    """(allowed, reason). The simulated provider is in-process and always
    allowed while AI is enabled."""
    if not policy.ai_enabled:
        return False, "AI is disabled for this tenant"
    if prov.kind == ProviderKind.SIMULATED.value:
        return True, "built-in simulated reasoner"
    if policy.strategy == "simulated":
        return False, "tenant strategy is 'simulated'"
    if not policy.external_allowed:
        return False, "service plan does not include external LLMs"
    if policy.private_only and not _is_private(prov):
        return False, "tenant requires private models only"
    if policy.strategy == "hybrid" and classification in ("confidential", "restricted") \
            and not _is_private(prov):
        return False, f"hybrid routing keeps {classification} data on private models"
    allowance = prov.data_classification_allowance or "internal"
    if _CLASS_ORDER.index(classification) > _CLASS_ORDER.index(allowance):
        return False, f"provider allowance '{allowance}' is below data classification '{classification}'"
    if policy.region != "global" and prov.region and prov.region not in (policy.region, "global"):
        return False, f"data residency: provider region '{prov.region}' ≠ tenant region '{policy.region}'"
    if prov.allowed_geographies and policy.region != "global" \
            and policy.region not in prov.allowed_geographies:
        return False, f"provider not permitted for region '{policy.region}'"
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if prov.daily_token_limit and prov.tokens_day == today and prov.tokens_today >= prov.daily_token_limit:
        return False, "provider daily token budget exhausted"
    if policy.monthly_budget is not None and policy.monthly_used >= policy.monthly_budget:
        return False, "tenant monthly token budget exhausted"
    return True, "allowed"


def charge_tokens(prov: ModelProvider, tokens: int) -> None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if prov.tokens_day != today:
        prov.tokens_day, prov.tokens_today = today, 0
    prov.tokens_today = (prov.tokens_today or 0) + int(tokens)


_TEXT_FIELDS = {
    "incident": ("title", "summary"),
    "evidence": ("title", "content"),
    "timeline": ("title", "detail"),
    "hypotheses": ("statement",),
}


def prepare_untrusted(task: dict) -> tuple[dict, dict]:
    """Return a copy of ``task`` safe to send to an external model, plus a
    report: which fields were wrapped and whether injection was detected."""
    safe = copy.deepcopy(task)
    wrapped = 0
    injection_hits: list[str] = []

    def _wrap(obj: dict, key: str, source: str) -> None:
        nonlocal wrapped
        val = obj.get(key)
        if isinstance(val, str) and val:
            hit, patterns = detect_injection(val)
            if hit:
                injection_hits.extend(patterns)
            obj[key] = wrap_external(val, source=source)
            wrapped += 1

    inc = safe.get("incident")
    if isinstance(inc, dict):
        for k in _TEXT_FIELDS["incident"]:
            _wrap(inc, k, "incident")
    for section in ("evidence", "timeline", "hypotheses"):
        for item in safe.get(section) or []:
            if isinstance(item, dict):
                for k in _TEXT_FIELDS[section]:
                    _wrap(item, k, section)
    return safe, {"wrapped_fields": wrapped, "injection_detected": bool(injection_hits),
                  "injection_patterns": sorted(set(injection_hits))}


def valid_evidence_ids(task: dict) -> set[str]:
    return {str(e.get("id")) for e in task.get("evidence") or [] if isinstance(e, dict) and e.get("id")}
