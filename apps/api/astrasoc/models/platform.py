"""Cross-cutting platform models: reports, audit, notifications, settings."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import GUID, Base
from .base import TenantMixin, TimestampMixin, UUIDMixin


class Report(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    report_type: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(300))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    data_scope: Mapped[str] = mapped_column(String(8), default="DEMO", index=True)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    format: Mapped[str] = mapped_column(String(20), default="html")
    # Structured content; distinguishes facts from AI inferences and cites
    # evidence IDs.
    content: Mapped[dict] = mapped_column(default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    parameters: Mapped[dict] = mapped_column(default=dict)


class AuditEvent(UUIDMixin, TimestampMixin, Base):
    """Append-only audit log. Each row chains to the previous via ``prev_hash``
    and stores its own ``entry_hash`` for tamper-evidence."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_tenant_ts", "tenant_id", "created_at"),
        Index("ix_audit_action", "action"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")  # user|agent|system|service
    actor_label: Mapped[str] = mapped_column(String(160), default="")
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(60), default="")
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), default="success")
    data_scope: Mapped[str] = mapped_column(String(8), default="DEMO")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(default=dict)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class Notification(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")  # info|warning|critical|success
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), default="general")
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    data_scope: Mapped[str] = mapped_column(String(8), default="DEMO")


class SystemSetting(UUIDMixin, TimestampMixin, Base):
    """Key/value platform settings. The authoritative operating MODE lives here
    (key ``operating_mode``) and is what the mode enforcer reads/writes."""

    __tablename__ = "system_settings"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[dict] = mapped_column(default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
