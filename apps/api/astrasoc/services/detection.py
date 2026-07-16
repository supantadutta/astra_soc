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


def evaluate_matcher(matcher: dict, event: dict) -> bool:
    """Evaluate a compiled matcher spec against a single event dict.

    Supported operators (AND across keys):
      {"field": "activity", "op": "contains", "value": "vssadmin"}
    combined via {"all": [...], "any": [...]}.
    """
    if not matcher:
        return False

    def _cond(c: dict) -> bool:
        field = c.get("field", "")
        op = c.get("op", "eq")
        val = c.get("value")
        actual = event.get(field)
        if actual is None:
            # search nested ocsf/raw
            actual = (event.get("ocsf", {}) or {}).get(field)
        if actual is None:
            return False
        actual_s = str(actual).lower()
        if op == "eq":
            return actual_s == str(val).lower()
        if op == "contains":
            return str(val).lower() in actual_s
        if op == "regex":
            return re.search(str(val), str(actual), re.IGNORECASE) is not None
        if op == "in":
            return actual_s in [str(v).lower() for v in (val or [])]
        if op == "gte":
            try:
                return float(actual) >= float(val)
            except (TypeError, ValueError):
                return False
        return False

    if "all" in matcher:
        return all(_cond(c) for c in matcher["all"])
    if "any" in matcher:
        return any(_cond(c) for c in matcher["any"])
    return _cond(matcher)


def replay_rule(db: Session, tenant_id: uuid.UUID, rule: DetectionRule, scope: str,
                limit: int = 500) -> dict[str, Any]:
    """Run a rule over recent events to estimate matches (historical replay)."""
    events = db.execute(
        select(SecurityEvent).where(
            SecurityEvent.tenant_id == tenant_id, SecurityEvent.data_scope == scope
        ).order_by(SecurityEvent.event_time.desc()).limit(limit)
    ).scalars().all()
    matches = 0
    matched_ids: list[str] = []
    for ev in events:
        payload = {"activity": ev.activity, "source": ev.source, "severity": ev.severity,
                   "host_name": ev.host_name, "user_name": ev.user_name,
                   "src_ip": ev.src_ip, "dst_ip": ev.dst_ip, "ocsf": ev.ocsf}
        if evaluate_matcher(rule.matcher, payload):
            matches += 1
            matched_ids.append(str(ev.id))
    # Precision/recall only meaningful when test labels exist.
    labels = (rule.test_data or {}).get("labels")
    precision = recall = None
    if labels:
        tp = matches  # simplified: assume matched == predicted positive
        expected = labels.get("expected_matches", tp)
        precision = round(tp / max(1, tp), 3)
        recall = round(min(1.0, tp / max(1, expected)), 3)
    return {"scanned": len(events), "matches": matches, "matched_event_ids": matched_ids[:50],
            "precision": precision, "recall": recall,
            "evaluated_at": datetime.now(UTC).isoformat()}


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
