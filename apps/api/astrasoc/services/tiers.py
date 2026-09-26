"""MSSP service tiers: default SLA targets and feature entitlements.

A tenant's contract picks a tier; individual contracts can override SLA
targets (``Tenant.sla_policy``) and toggle features
(``Tenant.settings["feature_overrides"]``). Entitlements are enforced on the
server — a disabled feature returns ``403 feature_not_in_plan``.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Tenant

SEVERITIES = ("critical", "high", "medium", "low", "info")

# Minutes to acknowledge / resolve by severity.
_SLA = {
    "essentials": {
        "critical": {"ack": 60, "resolve": 1440}, "high": {"ack": 240, "resolve": 2880},
        "medium": {"ack": 1440, "resolve": 7200}, "low": {"ack": 2880, "resolve": 14400},
        "info": {"ack": 10080, "resolve": 43200},
    },
    "professional": {
        "critical": {"ack": 30, "resolve": 480}, "high": {"ack": 120, "resolve": 1440},
        "medium": {"ack": 480, "resolve": 4320}, "low": {"ack": 1440, "resolve": 10080},
        "info": {"ack": 4320, "resolve": 20160},
    },
    "enterprise": {
        "critical": {"ack": 15, "resolve": 240}, "high": {"ack": 60, "resolve": 720},
        "medium": {"ack": 240, "resolve": 2880}, "low": {"ack": 720, "resolve": 7200},
        "info": {"ack": 2880, "resolve": 14400},
    },
}

FEATURES = {
    "monitoring": "24x7 alert monitoring and triage",
    "reports": "Scheduled and on-demand service reports",
    "threat_intel": "Threat-intelligence enrichment",
    "ai_investigation": "AI-assisted investigation (agents)",
    "threat_hunting": "Query workbench / proactive hunting",
    "custom_detections": "Customer-specific detection engineering",
    "automated_response": "Governed response actions and response playbooks",
    "external_llm": "Hosted / private LLM providers (beyond the built-in reasoner)",
}

_TIER_FEATURES = {
    "essentials": {"monitoring", "reports", "threat_intel"},
    "professional": {"monitoring", "reports", "threat_intel", "ai_investigation",
                     "threat_hunting", "automated_response"},
    "enterprise": set(FEATURES),
}

TIERS = {
    name: {"sla": _SLA[name], "features": sorted(_TIER_FEATURES[name])}
    for name in ("essentials", "professional", "enterprise")
}


def default_sla(tier: str) -> dict:
    return {k: dict(v) for k, v in _SLA.get(tier, _SLA["professional"]).items()}


def effective_sla(tenant: Tenant) -> dict:
    """Tier defaults overlaid with contract-specific overrides."""
    sla = default_sla(tenant.service_tier)
    for sev, targets in (tenant.sla_policy or {}).items():
        if sev in sla and isinstance(targets, dict):
            sla[sev].update({k: int(v) for k, v in targets.items() if k in ("ack", "resolve")})
    return sla


def tenant_features(tenant: Tenant) -> set[str]:
    feats = set(_TIER_FEATURES.get(tenant.service_tier, _TIER_FEATURES["professional"]))
    for name, enabled in ((tenant.settings or {}).get("feature_overrides") or {}).items():
        if name in FEATURES:
            (feats.add if enabled else feats.discard)(name)
    return feats


def has_feature(db: Session, tenant_id: uuid.UUID, feature: str) -> bool:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return False
    if tenant.kind in ("provider", "reseller"):
        return True  # providers operate their own SOC without plan limits
    return feature in tenant_features(tenant)


def require_feature(db: Session, tenant_id: uuid.UUID, feature: str) -> None:
    if not has_feature(db, tenant_id, feature):
        raise HTTPException(403, detail={
            "error": "feature_not_in_plan",
            "message": f"'{FEATURES.get(feature, feature)}' is not included in this tenant's "
                       "service plan. Contact your service provider to enable it.",
            "feature": feature,
        })
