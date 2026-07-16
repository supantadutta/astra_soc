"""Controlled Learning API: analyst feedback + evaluation pipeline (spec §19)."""
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
from ..models import AnalystFeedback, EvaluationDataset, EvaluationRun
from ..models.enums import FeedbackKind
from ..schemas.common import serialize, serialize_many
from ..services import audit
from ..services.injection import apply_dlp

router = APIRouter(prefix="/api/v1/learning", tags=["learning"])

# The controlled promotion pipeline. The platform NEVER self-promotes to
# production — the final step always requires a human approval.
PIPELINE = ["feedback", "review", "sanitization", "evaluation_dataset", "offline_experiment",
            "incident_replay", "security_testing", "champion_challenger", "shadow", "canary",
            "human_approval", "production"]


@router.get("/pipeline")
def pipeline(principal: Principal = Depends(require_permission("evaluation:manage"))) -> dict:
    return {"stages": PIPELINE,
            "note": "Feedback flows left-to-right. Promotion to production requires explicit "
                    "human approval; the platform cannot rewrite production code/policy/tools."}


@router.post("/feedback")
def submit_feedback(payload: dict,
                    principal: Principal = Depends(require_permission("feedback:write")),
                    db: Session = Depends(get_db)) -> dict:
    if payload.get("kind") not in [k.value for k in FeedbackKind]:
        raise HTTPException(422, detail="Invalid feedback kind")
    fb = AnalystFeedback(
        tenant_id=principal.tenant_id, kind=payload["kind"],
        subject_type=payload.get("subject_type", "agent_run"),
        subject_id=uuid.UUID(payload["subject_id"]) if payload.get("subject_id") else None,
        incident_id=uuid.UUID(payload["incident_id"]) if payload.get("incident_id") else None,
        analyst_id=principal.user_id, comment=apply_dlp(payload.get("comment", ""))[0],
        corrected_value=payload.get("corrected_value", {}), review_status="raw",
    )
    db.add(fb)
    audit.record(db, action="learning.feedback", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="analyst_feedback",
                 resource_id=str(fb.id), detail={"kind": payload["kind"]})
    db.commit()
    return serialize(fb)


@router.get("/feedback")
def list_feedback(principal: Principal = Depends(require_permission("evaluation:manage")),
                  db: Session = Depends(get_db),
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                  kind: str | None = None) -> dict:
    filters = [AnalystFeedback.kind == kind] if kind else []
    return paginate(db, AnalystFeedback, tenant_id=principal.tenant_id, filters=filters,
                    sort="created_at", page=page, page_size=page_size)


@router.post("/feedback/{feedback_id}/review")
def review_feedback(feedback_id: uuid.UUID, payload: dict | None = None,
                    principal: Principal = Depends(require_permission("evaluation:manage")),
                    db: Session = Depends(get_db)) -> dict:
    fb = db.get(AnalystFeedback, feedback_id)
    if not fb or fb.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Feedback not found")
    fb.review_status = (payload or {}).get("status", "reviewed")
    fb.sanitized = True
    db.commit()
    return serialize(fb)


@router.get("/datasets")
def list_datasets(principal: Principal = Depends(require_permission("evaluation:manage")),
                  db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(EvaluationDataset).where(
        EvaluationDataset.tenant_id == principal.tenant_id)).scalars().all()
    return {"items": serialize_many(rows, exclude={"items"})}


@router.post("/datasets/build")
def build_dataset(payload: dict | None = None,
                  principal: Principal = Depends(require_permission("evaluation:manage")),
                  db: Session = Depends(get_db)) -> dict:
    """Curate a dataset from sanitized feedback only."""
    fbs = db.execute(select(AnalystFeedback).where(
        AnalystFeedback.tenant_id == principal.tenant_id,
        AnalystFeedback.sanitized.is_(True))).scalars().all()
    items = [{"kind": f.kind, "subject_type": f.subject_type,
              "comment": f.comment, "corrected": f.corrected_value} for f in fbs]
    ds = EvaluationDataset(
        tenant_id=principal.tenant_id, name=(payload or {}).get("name", "Curated feedback set"),
        version="1.0.0", item_count=len(items), items=items, source="analyst_feedback",
    )
    db.add(ds)
    audit.record(db, action="learning.dataset_built", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="evaluation_dataset",
                 resource_id=str(ds.id), detail={"items": len(items)})
    db.commit()
    return serialize(ds, exclude={"items"})


@router.get("/runs")
def list_runs(principal: Principal = Depends(require_permission("evaluation:manage")),
              db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(EvaluationRun).where(
        EvaluationRun.tenant_id == principal.tenant_id)).scalars().all()
    return {"items": serialize_many(rows)}


@router.post("/runs")
def create_run(payload: dict,
               principal: Principal = Depends(require_permission("evaluation:manage")),
               db: Session = Depends(get_db)) -> dict:
    """Start an offline evaluation stage. Runs deterministically against the
    dataset; does not touch production."""
    ds_id = uuid.UUID(payload["dataset_id"]) if payload.get("dataset_id") else None
    ds = db.get(EvaluationDataset, ds_id) if ds_id else None
    # Deterministic mock metrics from dataset composition.
    n = ds.item_count if ds else 0
    correct = sum(1 for it in (ds.items if ds else []) if it.get("kind") == "correct")
    accuracy = round(correct / n, 3) if n else 0.0
    run = EvaluationRun(
        tenant_id=principal.tenant_id, name=payload.get("name", "Offline experiment"),
        dataset_id=ds_id, stage=payload.get("stage", "offline_experiment"),
        target_type=payload.get("target_type", "prompt"), target_ref=payload.get("target_ref", ""),
        status="completed", started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        metrics={"accuracy": accuracy, "items": n},
        baseline_metrics={"accuracy": max(0.0, accuracy - 0.05)},
        passed=accuracy >= 0.6,
    )
    db.add(run)
    audit.record(db, action="learning.eval_run", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="evaluation_run",
                 resource_id=str(run.id), detail={"stage": run.stage, "passed": run.passed})
    db.commit()
    return serialize(run)


@router.post("/runs/{run_id}/promote")
def promote(run_id: uuid.UUID,
            principal: Principal = Depends(require_permission("evaluation:manage")),
            db: Session = Depends(get_db)) -> dict:
    """Human approval to promote. Requires the run passed. This records intent —
    it does NOT rewrite production code/policy/tools automatically."""
    run = db.get(EvaluationRun, run_id)
    if not run or run.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Run not found")
    if not run.passed:
        raise HTTPException(400, detail="Only runs that passed evaluation can be promoted.")
    run.approved_for_production = True
    run.approved_by = principal.user_id
    audit.record(db, action="learning.promoted", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="evaluation_run",
                 resource_id=str(run_id))
    db.commit()
    return {"status": "approved_for_production", "note":
            "Recorded human approval. A change-management process applies the change; "
            "the platform does not self-modify production."}
