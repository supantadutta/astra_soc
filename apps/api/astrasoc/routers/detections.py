"""Detection Engineering + Query Workbench APIs."""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import DetectionRule
from ..schemas.common import serialize
from ..services import audit
from ..services.detection import is_read_only, replay_rule, translate_sigma, validate_matcher
from ..services.mode import current_scope
from ..services.query import execute as run_query
from ..services.tiers import require_feature

router = APIRouter(prefix="/api/v1/detections", tags=["detections"])


@router.get("")
def list_rules(principal: Principal = Depends(require_permission("detection:read")),
               db: Session = Depends(get_db),
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
               status: str | None = None, q: str | None = None) -> dict:
    filters = [DetectionRule.status == status] if status else []
    return paginate(db, DetectionRule, tenant_id=principal.tenant_id, filters=filters,
                    search=q, search_fields=["name", "description", "key"],
                    page=page, page_size=page_size)


_SEVERITIES = {"info", "low", "medium", "high", "critical"}
_STATUSES = {"draft", "review", "approved", "deployed", "disabled"}


def _check_matcher(matcher) -> None:
    try:
        validate_matcher(matcher)
    except (ValueError, re.error) as exc:
        raise HTTPException(422, detail={"error": "invalid_matcher", "message": str(exc)})


@router.post("")
def create_rule(payload: dict = Body(...),
                principal: Principal = Depends(require_permission("detection:write")),
                db: Session = Depends(get_db)) -> dict:
    require_feature(db, principal.tenant_id, "custom_detections")
    if not str(payload.get("name", "")).strip():
        raise HTTPException(422, detail="name is required")
    if payload.get("severity", "medium") not in _SEVERITIES:
        raise HTTPException(422, detail=f"severity must be one of {sorted(_SEVERITIES)}")
    _check_matcher(payload.get("matcher"))
    key = str(payload.get("key") or f"rule_{uuid.uuid4().hex[:8]}")
    if db.execute(select(DetectionRule).where(DetectionRule.tenant_id == principal.tenant_id,
                                              DetectionRule.key == key)).first():
        raise HTTPException(409, detail="A rule with that key already exists")
    rule = DetectionRule(
        tenant_id=principal.tenant_id, key=key,
        name=str(payload["name"])[:200], description=str(payload.get("description", "")),
        sigma=str(payload.get("sigma", "")), matcher=payload["matcher"],
        severity=payload.get("severity", "medium"), status="draft", enabled=False,
        attack_techniques=list(payload.get("attack_techniques") or []),
        data_sources=list(payload.get("data_sources") or []),
        false_positives=list(payload.get("false_positives") or []),
        author=principal.email, ai_generated=bool(payload.get("ai_generated", False)),
        test_data=payload.get("test_data") or {}, deployment_target="internal",
        version_history=[{"version": "1.0.0", "by": principal.email, "note": "created"}],
    )
    db.add(rule)
    db.flush()
    audit.record(db, action="detection.created", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="detection_rule", resource_id=str(rule.id),
                 detail={"key": key, "ai_generated": rule.ai_generated})
    db.commit()
    return serialize(rule)


@router.get("/{rule_id}")
def get_rule(rule_id: uuid.UUID,
             principal: Principal = Depends(require_permission("detection:read")),
             db: Session = Depends(get_db)) -> dict:
    r = db.get(DetectionRule, rule_id)
    if not r or r.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Rule not found")
    return serialize(r)


_LOGIC_FIELDS = ("sigma", "matcher", "severity", "name", "description", "attack_techniques")


@router.patch("/{rule_id}")
def update_rule(rule_id: uuid.UUID, payload: dict = Body(...),
                principal: Principal = Depends(require_permission("detection:write")),
                db: Session = Depends(get_db)) -> dict:
    r = db.get(DetectionRule, rule_id)
    if not r or r.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Rule not found")
    managed = (r.deployment_target or "").startswith("managed:")
    logic_change = any(f in payload for f in _LOGIC_FIELDS)
    if managed and logic_change:
        raise HTTPException(409, detail={
            "error": "managed_rule",
            "message": "This rule is managed by your service provider. You can tune exceptions "
                       "and enable/disable it; logic changes come from the provider."})
    if "matcher" in payload:
        _check_matcher(payload["matcher"])
    if "severity" in payload and payload["severity"] not in _SEVERITIES:
        raise HTTPException(422, detail=f"severity must be one of {sorted(_SEVERITIES)}")
    new_status = payload.get("status")
    if new_status is not None and new_status not in _STATUSES:
        raise HTTPException(422, detail=f"status must be one of {sorted(_STATUSES)}")
    if new_status in ("approved", "deployed") and not principal.has("detection:approve"):
        raise HTTPException(403, detail="detection:approve required to approve/deploy.")
    if new_status == "approved" and r.author == principal.email and not managed:
        raise HTTPException(403, detail="A rule must be approved by someone other than its author.")
    if new_status == "deployed" and r.status != "approved" and r.status != "deployed":
        raise HTTPException(409, detail="Rules must be approved before deployment.")
    for field in (*_LOGIC_FIELDS, "false_positives", "exceptions", "test_data"):
        if field in payload:
            setattr(r, field, payload[field])
    if logic_change and r.status in ("approved", "deployed"):
        # Approved logic changed: back to review, re-approval required.
        r.status, r.enabled, r.approved_by = "review", False, None
        parts = (r.version or "1.0.0").split(".")
        parts[1] = str(int(parts[1]) + 1)
        parts[2] = "0"
        r.version = ".".join(parts)
        r.version_history = [*(r.version_history or []),
                             {"version": r.version, "by": principal.email, "note": "logic changed"}]
    if new_status is not None:
        r.status = new_status
        if new_status == "approved":
            r.approved_by = principal.email
        r.enabled = new_status == "deployed" or (r.enabled and new_status == "approved")
        if new_status == "disabled":
            r.enabled = False
    if "enabled" in payload:
        if payload["enabled"] and r.status != "deployed":
            raise HTTPException(409, detail="Only deployed rules can be enabled.")
        r.enabled = bool(payload["enabled"])
    audit.record(db, action="detection.updated", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="detection_rule", resource_id=str(rule_id),
                 detail={"fields": list(payload), "status": r.status, "version": r.version})
    db.commit()
    return serialize(r)


@router.post("/{rule_id}/replay")
def replay(rule_id: uuid.UUID,
           principal: Principal = Depends(require_permission("detection:read")),
           db: Session = Depends(get_db)) -> dict:
    r = db.get(DetectionRule, rule_id)
    if not r or r.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Rule not found")
    scope = current_scope(db, principal.tenant_id)
    result = replay_rule(db, principal.tenant_id, r, scope)
    r.last_triggered_at = datetime.now(UTC) if result["matches"] else r.last_triggered_at
    r.trigger_count = (r.trigger_count or 0) + result["matches"]
    if result["labelled"]:
        r.precision, r.recall = result["precision"], result["recall"]
    db.commit()
    return result


@router.post("/translate")
def translate(payload: dict,
              principal: Principal = Depends(require_permission("detection:read"))) -> dict:
    return translate_sigma(payload.get("sigma", ""), payload.get("target", "spl"))


# --- Query Workbench (spec §13) ------------------------------------------
query_router = APIRouter(prefix="/api/v1/query", tags=["query"])


@query_router.post("/validate")
def validate_query(payload: dict,
                   principal: Principal = Depends(require_permission("query:run"))) -> dict:
    """Read-only validation. AI-generated & user queries are validated before
    execution; destructive commands are rejected."""
    ok, reason = is_read_only(payload.get("query", ""))
    return {"read_only": ok, "reason": reason,
            "row_limit": 10000, "time_limit_seconds": 300}


@query_router.post("/execute")
def execute_query(payload: dict = Body(...),
                  principal: Principal = Depends(require_permission("query:run")),
                  db: Session = Depends(get_db)) -> dict:
    """Execute a read-only query against the normalized event store.

    Destructive text is rejected first. Field predicates are extracted and run
    as parameterised filters; anything that could not be translated is listed
    in ``unsupported_terms`` — the result never pretends to have applied it."""
    require_feature(db, principal.tenant_id, "threat_hunting")
    query = str(payload.get("query", ""))
    language = str(payload.get("language", "sql"))
    ok, reason = is_read_only(query)
    if not ok:
        raise HTTPException(400, detail={"error": "destructive_query", "message": reason})
    scope = current_scope(db, principal.tenant_id)
    hours = payload.get("time_range_hours")
    result = run_query(db, principal.tenant_id, scope, query,
                       limit=int(payload.get("limit", 100)), hours=int(hours) if hours else None)
    audit.record(db, action="query.executed", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="query", data_scope=scope,
                 detail={"language": language, "rows": result["row_count"],
                         "filters": len(result["applied_filters"]),
                         "unsupported": len(result["unsupported_terms"])})
    db.commit()
    note = ("Executed against the normalized event store. "
            + ("Some terms were not applied — see unsupported_terms."
               if result["unsupported_terms"] else "All terms were applied."))
    return {"language": language, **result, "note": note}
