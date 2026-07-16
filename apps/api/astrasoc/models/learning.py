"""Controlled learning: analyst feedback and evaluation pipeline."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import GUID, Base
from .base import TenantMixin, TimestampMixin, UUIDMixin


class AnalystFeedback(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "analyst_feedback"

    kind: Mapped[str] = mapped_column(String(30), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))  # agent_run|hypothesis|action|alert
    subject_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    analyst_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    corrected_value: Mapped[dict] = mapped_column(default=dict)
    # Learning-pipeline status: raw -> reviewed -> sanitized -> in_dataset.
    review_status: Mapped[str] = mapped_column(String(20), default="raw", index=True)
    sanitized: Mapped[bool] = mapped_column(Boolean, default=False)


class EvaluationDataset(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_datasets"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[list] = mapped_column(default=list)  # sanitized labelled examples
    source: Mapped[str] = mapped_column(String(80), default="analyst_feedback")
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)


class EvaluationRun(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """An offline experiment stage in the controlled-learning workflow.

    stage: offline_experiment | incident_replay | security_testing |
    champion_challenger | shadow | canary. Promotion to production always
    requires explicit human approval — the platform never self-promotes.
    """

    __tablename__ = "evaluation_runs"

    name: Mapped[str] = mapped_column(String(200))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(40), default="offline_experiment", index=True)
    target_type: Mapped[str] = mapped_column(String(40), default="prompt")  # prompt|route|detection
    target_ref: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    metrics: Mapped[dict] = mapped_column(default=dict)
    baseline_metrics: Mapped[dict] = mapped_column(default=dict)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved_for_production: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
