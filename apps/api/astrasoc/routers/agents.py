"""Agents API: registry, runs, and agent invocation (Agent Command Center)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import Agent, AgentRun
from ..schemas.common import serialize, serialize_many
from ..services import audit
from ..services.agents import orchestrator
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("")
def list_agents(principal: Principal = Depends(require_permission("agent:read")),
                db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Agent).order_by(Agent.key)).scalars().all()
    return {"items": serialize_many(rows)}


@router.get("/runs")
def list_runs(
    principal: Principal = Depends(require_permission("agent:read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    agent_key: str | None = None, status: str | None = None,
    incident_id: uuid.UUID | None = None,
) -> dict:
    scope = current_scope(db)
    filters = []
    if agent_key:
        filters.append(AgentRun.agent_key == agent_key)
    if status:
        filters.append(AgentRun.status == status)
    if incident_id:
        filters.append(AgentRun.incident_id == incident_id)
    return paginate(db, AgentRun, tenant_id=principal.tenant_id, scope=scope, filters=filters,
                    sort="created_at", order="desc", page=page, page_size=page_size)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID,
            principal: Principal = Depends(require_permission("agent:read")),
            db: Session = Depends(get_db)) -> dict:
    run = db.get(AgentRun, run_id)
    if not run or run.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Run not found")
    return serialize(run)


@router.get("/{agent_key}")
def get_agent(agent_key: str,
              principal: Principal = Depends(require_permission("agent:read")),
              db: Session = Depends(get_db)) -> dict:
    a = db.execute(select(Agent).where(Agent.key == agent_key)).scalar_one_or_none()
    if not a:
        raise HTTPException(404, detail="Agent not found")
    return serialize(a)


@router.patch("/{agent_key}")
def update_agent(agent_key: str, payload: dict,
                 principal: Principal = Depends(require_permission("agent:manage")),
                 db: Session = Depends(get_db)) -> dict:
    a = db.execute(select(Agent).where(Agent.key == agent_key)).scalar_one_or_none()
    if not a:
        raise HTTPException(404, detail="Agent not found")
    for field in ("enabled", "max_execution_seconds", "max_token_budget", "max_tool_calls",
                  "required_capability", "failure_policy"):
        if field in payload:
            setattr(a, field, payload[field])
    audit.record(db, action="agent.updated", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="agent", resource_id=agent_key,
                 detail={"fields": list(payload)})
    db.commit()
    return serialize(a)


@router.post("/{agent_key}/run")
def run_agent(agent_key: str, payload: dict,
              principal: Principal = Depends(require_permission("agent:run")),
              db: Session = Depends(get_db)) -> dict:
    """Invoke a single bounded agent on an incident."""
    scope = current_scope(db)
    incident_id = uuid.UUID(payload["incident_id"]) if payload.get("incident_id") else None
    run = orchestrator.run_agent(db, principal.tenant_id, agent_key, incident_id, scope,
                                 actor_label=principal.email)
    audit.record(db, action="agent.run", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="agent_run",
                 resource_id=str(run.id), data_scope=scope, detail={"agent": agent_key})
    db.commit()
    return serialize(run)
