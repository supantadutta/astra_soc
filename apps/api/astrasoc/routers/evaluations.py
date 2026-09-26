"""Controlled Learning API: analyst feedback + evaluation pipeline (spec §19)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
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


PASS_THRESHOLD = 0.6
_POSITIVE = {"correct", "helpful"}
_NEGATIVE = {"incorrect", "not_helpful", "unsafe_recommendation", "wrong_severity",
             "wrong_attack_mapping", "missing_evidence", "partially_correct"}


@router.post("/runs")
def create_run(payload: dict = Body(...),
               principal: Principal = Depends(require_permission("evaluation:manage")),
               db: Session = Depends(get_db)) -> dict:
    """Run the offline evaluation stage over a curated dataset.

    What is measured, precisely: the analyst-agreement rate — the share of
    labelled items where analysts judged the AI output correct/helpful. This
    is a quality signal from real feedback, not a model benchmark. The
    baseline is the previous PASSED run for the same target (or none). Later
    pipeline stages (replay, shadow, canary…) are not automated in this build
    and are refused rather than faked."""
    stage = payload.get("stage", "offline_experiment")
    if stage != "offline_experiment":
        raise HTTPException(422, detail={
            "error": "stage_not_automated",
            "message": f"Stage '{stage}' is not automated in this build; only "
                       "offline_experiment can be run."})
    try:
        ds_id = uuid.UUID(str(payload["dataset_id"]))
    except (KeyError, ValueError):
        raise HTTPException(422, detail="dataset_id is required")
    ds = db.get(EvaluationDataset, ds_id)
    if ds is None or ds.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Dataset not found")
    labelled = [it for it in ds.items or [] if it.get("kind") in _POSITIVE | _NEGATIVE]
    agree = sum(1 for it in labelled if it.get("kind") in _POSITIVE)
    accuracy = round(agree / len(labelled), 3) if labelled else None
    target_ref = str(payload.get("target_ref", ""))
    prev = db.execute(select(EvaluationRun).where(
        EvaluationRun.tenant_id == principal.tenant_id, EvaluationRun.target_ref == target_ref,
        EvaluationRun.passed.is_(True)).order_by(EvaluationRun.created_at.desc())).scalars().first()
    baseline = (prev.metrics or {}).get("agreement_rate") if prev else None
    passed = (accuracy is not None and accuracy >= PASS_THRESHOLD
              and (baseline is None or accuracy >= baseline))
    now = datetime.now(UTC)
    run = EvaluationRun(
        tenant_id=principal.tenant_id, name=str(payload.get("name", "Offline experiment"))[:200],
        dataset_id=ds.id, stage=stage, target_type=payload.get("target_type", "prompt"),
        target_ref=target_ref, status="completed", started_at=now, finished_at=now,
        metrics={"agreement_rate": accuracy, "labelled_items": len(labelled),
                 "dataset_items": ds.item_count,
                 "method": "analyst-agreement rate over labelled feedback",
                 "pass_threshold": PASS_THRESHOLD},
        baseline_metrics={"agreement_rate": baseline, "baseline_run": str(prev.id) if prev else None},
        passed=passed,
        notes="" if labelled else "No labelled items — nothing to evaluate.",
    )
    db.add(run)
    db.flush()
    audit.record(db, action="learning.eval_run", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="evaluation_run", resource_id=str(run.id),
                 detail={"stage": stage, "passed": passed, "agreement_rate": accuracy})
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
