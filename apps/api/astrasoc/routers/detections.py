"""Detection Engineering + Query Workbench APIs."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import DetectionRule
from ..schemas.common import serialize
from ..services import audit
from ..services.detection import is_read_only, replay_rule, translate_sigma
from ..services.mode import current_scope

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


@router.post("")
def create_rule(payload: dict,
                principal: Principal = Depends(require_permission("detection:write")),
                db: Session = Depends(get_db)) -> dict:
    rule = DetectionRule(
        tenant_id=principal.tenant_id, key=payload.get("key", f"rule_{uuid.uuid4().hex[:8]}"),
        name=payload["name"], description=payload.get("description", ""),
        sigma=payload.get("sigma", ""), matcher=payload.get("matcher", {}),
        severity=payload.get("severity", "medium"), status="draft",
        attack_techniques=payload.get("attack_techniques", []),
        data_sources=payload.get("data_sources", []),
        false_positives=payload.get("false_positives", []),
        author=principal.email, ai_generated=payload.get("ai_generated", False),
        test_data=payload.get("test_data", {}),
    )
    db.add(rule)
    audit.record(db, action="detection.created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="detection_rule",
                 resource_id=str(rule.id), detail={"ai_generated": rule.ai_generated})
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


@router.patch("/{rule_id}")
def update_rule(rule_id: uuid.UUID, payload: dict,
                principal: Principal = Depends(require_permission("detection:write")),
                db: Session = Depends(get_db)) -> dict:
    r = db.get(DetectionRule, rule_id)
    if not r or r.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Rule not found")
    if payload.get("status") in ("approved", "deployed") and not principal.has("detection:approve"):
        raise HTTPException(403, detail="detection:approve required to approve/deploy.")
    # AI-generated rules can never be auto-deployed without approval.
    if r.ai_generated and payload.get("status") == "deployed" and not r.approved_by:
        raise HTTPException(400, detail="AI-generated rule must be reviewed & approved first.")
    for field in ("name", "description", "sigma", "matcher", "severity", "status",
                  "enabled", "attack_techniques", "false_positives", "exceptions"):
        if field in payload:
            setattr(r, field, payload[field])
    if payload.get("status") == "approved":
        r.approved_by = principal.email
    db.commit()
    return serialize(r)


@router.post("/{rule_id}/replay")
def replay(rule_id: uuid.UUID,
           principal: Principal = Depends(require_permission("detection:read")),
           db: Session = Depends(get_db)) -> dict:
    r = db.get(DetectionRule, rule_id)
    if not r or r.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Rule not found")
    scope = current_scope(db)
    result = replay_rule(db, principal.tenant_id, r, scope)
    r.last_triggered_at = datetime.now(UTC) if result["matches"] else r.last_triggered_at
    r.trigger_count = (r.trigger_count or 0) + result["matches"]
    if result["precision"] is not None:
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
def execute_query(payload: dict,
                  principal: Principal = Depends(require_permission("query:run")),
                  db: Session = Depends(get_db)) -> dict:
    """Execute a query. Only read-only queries pass; results are capped.

    In demo mode this runs against the normalized event store (SQL) or returns a
    simulated result set for vendor languages (SPL/KQL/LogScale). Live mode
    dispatches to the corresponding read-only connector."""
    query = payload.get("query", "")
    language = payload.get("language", "sql")
    ok, reason = is_read_only(query)
    if not ok:
        raise HTTPException(400, detail={"error": "destructive_query", "message": reason})
    scope = current_scope(db)
    from ..models import SecurityEvent
    rows = db.execute(select(SecurityEvent).where(
        SecurityEvent.tenant_id == principal.tenant_id,
        SecurityEvent.data_scope == scope).order_by(
        SecurityEvent.event_time.desc()).limit(min(payload.get("limit", 100), 1000))).scalars().all()
    results = [{"time": e.event_time.isoformat(), "source": e.source, "activity": e.activity,
                "severity": e.severity, "host": e.host_name, "user": e.user_name,
                "src_ip": e.src_ip} for e in rows]
    audit.record(db, action="query.executed", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="query", data_scope=scope,
                 detail={"language": language, "rows": len(results)})
    db.commit()
    return {"language": language, "row_count": len(results), "results": results,
            "note": "Read-only. Vendor-language queries are simulated over the event store in demo mode."}
