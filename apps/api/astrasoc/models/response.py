"""Governance and response: playbooks, workflows, actions, approvals, policy."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import GUID, Base
from .base import TenantMixin, TimestampMixin, UUIDMixin
from .enums import (
    ActionStatus,
    ApprovalStatus,
    PolicyEffect,
    WorkflowStatus,
)


class Playbook(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "playbooks"

    key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger: Mapped[dict] = mapped_column(default=dict)  # e.g. {"on": "incident.created", "if": ...}
    current_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    tags: Mapped[list] = mapped_column(default=list)

    versions: Mapped[list[PlaybookVersion]] = relationship(back_populates="playbook")


class PlaybookVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "playbook_versions"

    playbook_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("playbooks.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(20))
    # Ordered DAG of steps: trigger, condition, enrichment, query, agent_task,
    # approval, delay, branch, parallel, response_action, verification,
    # rollback, notification, case_update, report.
    graph: Mapped[dict] = mapped_column(default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    changelog: Mapped[str] = mapped_column(Text, default="")

    playbook: Mapped[Playbook] = relationship(back_populates="versions")


class WorkflowRun(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A durable execution of a playbook. State is persisted at each step so a
    run survives restarts (in the demo profile this is a persisted state
    machine; production maps these onto Temporal workflows)."""

    __tablename__ = "workflow_runs"

    playbook_key: Mapped[str] = mapped_column(String(80), index=True)
    playbook_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    incident_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default=WorkflowStatus.PENDING.value, index=True)
    data_scope: Mapped[str] = mapped_column(String(8), default="DEMO", index=True)
    current_step: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    context: Mapped[dict] = mapped_column(default=dict)
    step_history: Mapped[list] = mapped_column(default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)


class ResponseAction(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A production-changing action passing through the safety pipeline."""

    __tablename__ = "response_actions"

    action_type: Mapped[str] = mapped_column(String(60), index=True)  # isolate_endpoint...
    target: Mapped[dict] = mapped_column(default=dict)  # exact target descriptor
    incident_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    requested_by_kind: Mapped[str] = mapped_column(String(20), default="analyst")  # analyst|agent
    status: Mapped[str] = mapped_column(String(24), default=ActionStatus.DRAFT.value, index=True)
    data_scope: Mapped[str] = mapped_column(String(8), default="DEMO", index=True)
    # Justification & risk.
    supporting_evidence_ids: Mapped[list] = mapped_column(default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    expected_outcome: Mapped[str] = mapped_column(Text, default="")
    blast_radius: Mapped[dict] = mapped_column(default=dict)
    reversible: Mapped[bool] = mapped_column(Boolean, default=True)
    rollback_instruction: Mapped[dict] = mapped_column(default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(120), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    # Execution record.
    dry_run_result: Mapped[dict] = mapped_column(default=dict)
    execution_result: Mapped[dict] = mapped_column(default=dict)
    verification_result: Mapped[dict] = mapped_column(default=dict)
    executed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(nullable=True)
    connector_kind: Mapped[str | None] = mapped_column(String(60), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApprovalRequest(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "approval_requests"

    response_action_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("response_actions.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=ApprovalStatus.PENDING.value, index=True)
    required_role: Mapped[str] = mapped_column(String(60), default="incident_commander")
    reason: Mapped[str] = mapped_column(Text, default="")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)


class PolicyDecision(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """An immutable record of a policy-as-code evaluation."""

    __tablename__ = "policy_decisions"

    subject: Mapped[str] = mapped_column(String(120))  # what was evaluated
    response_action_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    effect: Mapped[str] = mapped_column(String(24), default=PolicyEffect.DENY.value, index=True)
    policy_name: Mapped[str] = mapped_column(String(120), default="")
    engine: Mapped[str] = mapped_column(String(20), default="builtin")  # builtin | opa
    reasons: Mapped[list] = mapped_column(default=list)
    obligations: Mapped[list] = mapped_column(default=list)  # e.g. require approval role X
    input: Mapped[dict] = mapped_column(default=dict)
    matched_rules: Mapped[list] = mapped_column(default=list)
