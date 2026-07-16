"""Deterministic simulated reasoner.

This is the built-in fallback that keeps the platform fully usable when no
external LLM is configured (or when all providers are down). It is *not* a
random text generator: it reads the actual case evidence and produces a
schema-valid, evidence-first claim that cites real evidence IDs. Because it is
deterministic it is also used as a stable baseline for evaluations and as the
``private_investigator`` when data may not leave the environment.
"""
from __future__ import annotations

import hashlib
from typing import Any


def _seeded_confidence(evidence: list[dict], base: float) -> float:
    facts = [e for e in evidence if e.get("kind") == "confirmed_fact"]
    # More corroborating facts -> higher confidence, capped.
    bump = min(0.2, 0.04 * len(facts))
    return round(min(0.97, base + bump), 2)


def simulate_investigation(task: dict[str, Any]) -> dict[str, Any]:
    """Produce an evidence-first claim for a `deep_investigator` task.

    ``task`` carries the incident summary, its evidence (with ids/kinds), and
    existing hypotheses. The output is validated against EvidenceFirstClaim by
    the gateway.
    """
    incident = task.get("incident", {})
    evidence = task.get("evidence", [])
    hypotheses = task.get("hypotheses", [])

    fact_ids = [e["id"] for e in evidence if e.get("kind") == "confirmed_fact"]
    primary = next((h for h in hypotheses if h.get("is_primary")), None)

    if primary:
        claim = primary["statement"]
        base_conf = float(primary.get("confidence", 0.6))
        techniques = primary.get("attack_techniques", [])
        missing = primary.get("missing_evidence", [])
        supporting = primary.get("supporting_evidence_ids") or fact_ids
    else:
        claim = incident.get("summary") or "Suspicious activity requires triage."
        base_conf = float(incident.get("confidence", 0.5))
        techniques = incident.get("attack_techniques", [])[:3]
        missing = ["Root-cause evidence not yet collected."]
        supporting = fact_ids

    alt = [
        {"statement": h["statement"], "likelihood": round(float(h.get("confidence", 0.2)), 2)}
        for h in hypotheses if not h.get("is_primary")
    ][:3]

    attack_mapping = [
        {"tactic": _tactic_for(t), "technique_id": t, "technique_name": ""}
        for t in techniques if t.startswith("T")
    ]

    queries = _recommended_queries(incident, techniques)

    return {
        "claim": claim,
        "confidence": _seeded_confidence(evidence, base_conf),
        "evidence_ids": supporting,
        "supporting_explanation": _explain(evidence, supporting),
        "alternative_hypotheses": alt,
        "missing_evidence": missing,
        "recommended_queries": queries,
        "attack_mapping": attack_mapping,
        "suggested_action": task.get("suggested_action"),
        "model": "sim-investigator-1",
        "provider": "simulated",
    }


def simulate_triage(task: dict[str, Any]) -> dict[str, Any]:
    incident = task.get("incident", {})
    evidence = task.get("evidence", [])
    fact_ids = [e["id"] for e in evidence if e.get("kind") == "confirmed_fact"][:3]
    sev = incident.get("severity", "medium")
    return {
        "claim": f"Triage: severity {sev}. "
                 f"{'Escalate for investigation.' if sev in ('high', 'critical') else 'Monitor and enrich.'}",
        "confidence": round(float(incident.get("confidence", 0.5)) * 0.9, 2),
        "evidence_ids": fact_ids,
        "supporting_explanation": f"{len(fact_ids)} corroborating fact(s); mapped to "
                                  f"{len(incident.get('attack_techniques', []))} technique(s).",
        "alternative_hypotheses": [],
        "missing_evidence": [] if fact_ids else ["No confirmed facts yet — enrich first."],
        "recommended_queries": _recommended_queries(incident, incident.get("attack_techniques", [])),
        "attack_mapping": [],
        "suggested_action": None,
        "model": "sim-triage-1",
        "provider": "simulated",
    }


def simulate_critique(task: dict[str, Any]) -> dict[str, Any]:
    """Independent-critic pass: deliberately conservative, surfaces gaps."""
    primary = task.get("primary_claim", {})
    missing = list(primary.get("missing_evidence", []))
    if not primary.get("evidence_ids"):
        missing.append("Primary claim cites no evidence — cannot corroborate.")
    conf = max(0.1, float(primary.get("confidence", 0.6)) - 0.15)
    return {
        "claim": f"Independent review: primary conclusion is "
                 f"{'plausible but not fully corroborated' if missing else 'well-supported'}.",
        "confidence": round(conf, 2),
        "evidence_ids": primary.get("evidence_ids", [])[:3],
        "supporting_explanation": "Cross-checked cited evidence; applied a lower prior to avoid "
                                  "over-confidence. Confirm the listed missing evidence before response.",
        "alternative_hypotheses": primary.get("alternative_hypotheses", [])[:2],
        "missing_evidence": missing,
        "recommended_queries": [],
        "attack_mapping": primary.get("attack_mapping", []),
        "suggested_action": None,
        "model": "sim-critic-1",
        "provider": "simulated",
    }


def simulate_generic(task: dict[str, Any]) -> dict[str, Any]:
    text = str(task.get("prompt", ""))[:400]
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    return {
        "claim": f"Simulated analysis ({digest}). Configure a real provider for richer output.",
        "confidence": 0.5, "evidence_ids": [], "supporting_explanation": text,
        "alternative_hypotheses": [], "missing_evidence": [], "recommended_queries": [],
        "attack_mapping": [], "suggested_action": None,
        "model": "sim-investigator-1", "provider": "simulated",
    }


_TACTIC_BY_PREFIX = {
    "T1078": "Initial Access", "T1110": "Credential Access", "T1621": "Credential Access",
    "T1059": "Execution", "T1204": "Execution", "T1490": "Impact", "T1486": "Impact",
    "T1071": "Command and Control", "T1573": "Command and Control", "T1090": "Command and Control",
    "T1021": "Lateral Movement", "T1570": "Lateral Movement", "T1569": "Execution",
    "T1567": "Exfiltration", "T1048": "Exfiltration", "T1052": "Exfiltration", "T1074": "Collection",
    "T1552": "Credential Access", "T1098": "Persistence", "T1190": "Initial Access",
    "T1505": "Persistence", "T1087": "Discovery", "T1069": "Discovery", "T1482": "Discovery",
    "T1562": "Defense Evasion", "T1620": "Defense Evasion", "T1580": "Discovery",
    "T1566": "Initial Access", "T1219": "Command and Control",
}


def _tactic_for(technique: str) -> str:
    return _TACTIC_BY_PREFIX.get(technique.split(".")[0], "Unknown")


def _explain(evidence: list[dict], ids: list[str]) -> str:
    cited = [e for e in evidence if e.get("id") in ids]
    if not cited:
        return "No confirmed facts cited; recommendation limited to enrichment."
    titles = "; ".join(e.get("title", "") for e in cited[:4])
    return f"Conclusion is supported by {len(cited)} evidence item(s): {titles}."


def _recommended_queries(incident: dict, techniques: list[str]) -> list[str]:
    hosts = incident.get("affected_hosts", [])
    users = incident.get("affected_users", [])
    q: list[str] = []
    if hosts:
        q.append(f'search host="{hosts[0]}" | table _time, process, parent_process, cmdline')
    if users:
        q.append(f'SigninLogs | where UserPrincipalName == "{users[0]}" | order by TimeGenerated desc')
    if "T1071.001" in techniques or "T1071" in techniques:
        q.append("network_conn | stats count by dest_domain, dest_ip | where count > 100")
    return q[:4]
