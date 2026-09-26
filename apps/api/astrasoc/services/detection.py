"""Deterministic detection engine.

Detections are the *deterministic* backbone of the platform — the LLM never
replaces them. A rule carries Sigma source plus a compiled ``matcher`` spec
that is evaluated against normalized events without any model involvement.
Also provides Sigma->target-language translation and historical replay for
precision/recall estimation where labels exist.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DetectionRule, SecurityEvent

_DESTRUCTIVE = re.compile(r"\b(delete|drop|truncate|remove-item|rm\s+-rf|update|insert|"
                          r"alter|shutdown|del\s)\b", re.IGNORECASE)


def is_read_only(query: str) -> tuple[bool, str | None]:
    """Reject destructive query text before execution (spec §13)."""
    if _DESTRUCTIVE.search(query or ""):
        m = _DESTRUCTIVE.search(query)
        return False, f"Query contains a potentially destructive keyword: '{m.group(0)}'."
    return True, None


MATCHER_OPS = {"eq", "ne", "contains", "regex", "in", "gte", "lte", "threat_intel", "exists"}


def validate_matcher(matcher: dict) -> None:
    """Raise ValueError if a matcher spec is malformed (unknown op, bad regex)."""
    if not isinstance(matcher, dict) or not matcher:
        raise ValueError("matcher must be a non-empty object")
    conds = matcher.get("all") or matcher.get("any") or [matcher]
    if not isinstance(conds, list) or not conds:
        raise ValueError("matcher.all / matcher.any must be a non-empty list")
    for c in conds:
        if not isinstance(c, dict) or not c.get("field"):
            raise ValueError("each condition needs a field")
        op = c.get("op", "eq")
        if op not in MATCHER_OPS:
            raise ValueError(f"unknown op '{op}' (allowed: {sorted(MATCHER_OPS)})")
        if op == "regex":
            pattern = str(c.get("value", ""))
            if len(pattern) > 300:
                raise ValueError("regex too long (max 300 chars)")
            re.compile(pattern)
        if op == "in" and not isinstance(c.get("value"), list):
            raise ValueError("'in' needs a list value")


def evaluate_matcher(matcher: dict, event: dict, context: dict | None = None) -> bool:
    """Evaluate a compiled matcher spec against a single event dict.

    Conditions look at top-level event fields first, then the OCSF payload.
    Combine with {"all": [...]} or {"any": [...]}. ``threat_intel`` matches
    when the value is in ``context["iocs"]`` (the tenant's enabled indicators).
    """
    if not matcher:
        return False
    iocs = (context or {}).get("iocs") or set()

    def _cond(c: dict) -> bool:
        field = c.get("field", "")
        op = c.get("op", "eq")
        val = c.get("value")
        actual = event.get(field)
        if actual is None:
            actual = (event.get("ocsf", {}) or {}).get(field)
        if op == "exists":
            return actual is not None
        if actual is None:
            return False
        actual_s = str(actual).lower()
        if op == "eq":
            return actual_s == str(val).lower()
        if op == "ne":
            return actual_s != str(val).lower()
        if op == "contains":
            return str(val).lower() in actual_s
        if op == "regex":
            return re.search(str(val), str(actual)[:4096], re.IGNORECASE) is not None
        if op == "in":
            return actual_s in [str(v).lower() for v in (val or [])]
        if op == "threat_intel":
            return actual_s in iocs
        if op in ("gte", "lte"):
            try:
                a, b = float(actual), float(val)
            except (TypeError, ValueError):
                return False
            return a >= b if op == "gte" else a <= b
        return False

    if "all" in matcher:
        return all(_cond(c) for c in matcher["all"])
    if "any" in matcher:
        return any(_cond(c) for c in matcher["any"])
    return _cond(matcher)


def event_payload(ev: SecurityEvent) -> dict:
    """The dict a matcher sees for a stored event."""
    return {"activity": ev.activity, "source": ev.source, "severity": ev.severity,
            "host_name": ev.host_name, "user_name": ev.user_name, "src_ip": ev.src_ip,
            "dst_ip": ev.dst_ip, "ocsf": ev.ocsf or {}}


def tenant_iocs(db: Session, tenant_id: uuid.UUID) -> set[str]:
    from ..models import ThreatIndicator

    now = datetime.now(UTC)
    rows = db.execute(select(ThreatIndicator.value, ThreatIndicator.expires_at).where(
        ThreatIndicator.tenant_id == tenant_id, ThreatIndicator.enabled.is_(True))).all()
    return {v.lower() for v, exp in rows if exp is None or exp > now}


def replay_rule(db: Session, tenant_id: uuid.UUID, rule: DetectionRule, scope: str,
                limit: int = 500) -> dict[str, Any]:
    """Run a rule over recent events (historical replay).

    Precision/recall are reported ONLY when the rule's test data carries
    ground-truth labels (``test_data.labels.positive_event_ids``); otherwise
    they are ``None`` — never estimated."""
    events = db.execute(
        select(SecurityEvent).where(
            SecurityEvent.tenant_id == tenant_id, SecurityEvent.data_scope == scope
        ).order_by(SecurityEvent.event_time.desc()).limit(limit)
    ).scalars().all()
    ctx = {"iocs": tenant_iocs(db, tenant_id)}
    matched_ids = [str(ev.id) for ev in events if evaluate_matcher(rule.matcher, event_payload(ev), ctx)]
    labels = (rule.test_data or {}).get("labels") or {}
    positives = set(labels.get("positive_event_ids") or [])
    precision = recall = None
    if positives:
        scanned = {str(e.id) for e in events}
        positives &= scanned
        tp = len(positives & set(matched_ids))
        precision = round(tp / len(matched_ids), 3) if matched_ids else None
        recall = round(tp / len(positives), 3) if positives else None
    return {"scanned": len(events), "matches": len(matched_ids),
            "matched_event_ids": matched_ids[:50], "precision": precision, "recall": recall,
            "labelled": bool(positives), "evaluated_at": datetime.now(UTC).isoformat()}


def translate_sigma(sigma: str, target: str) -> dict[str, Any]:
    """Best-effort Sigma -> target query-language translation.

    This is a pragmatic translator for common selection patterns, not a full
    Sigma compiler. It is explicit about what it could not translate.
    """
    target = target.lower()
    fields = re.findall(r"(\w+):\s*['\"]?([^\n'\"]+)['\"]?", sigma or "")
    conds = [(k, v.strip()) for k, v in fields
             if k not in ("title", "id", "status", "description", "author", "level",
                          "logsource", "detection", "condition", "tags", "falsepositives")]
    if not conds:
        return {"target": target, "query": "", "translated": False,
                "note": "No translatable selection fields found."}
    if target in ("spl", "splunk"):
        q = "search " + " ".join(f'{k}="{v}"' for k, v in conds)
    elif target in ("kql", "sentinel"):
        q = "SecurityEvent | where " + " and ".join(f'{k} == "{v}"' for k, v in conds)
    elif target in ("logscale", "crowdstrike"):
        q = " | ".join(f'{k}="{v}"' for k, v in conds)
    elif target in ("es", "elastic", "dsl"):
        q = {"bool": {"must": [{"match": {k: v}} for k, v in conds]}}
    else:
        q = " AND ".join(f'{k}="{v}"' for k, v in conds)
    return {"target": target, "query": q, "translated": True, "fields": conds}
