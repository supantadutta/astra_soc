"""Detection engineering and threat intelligence models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .base import TenantMixin, TimestampMixin, UUIDMixin
from .enums import Severity


class DetectionRule(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "detection_rules"

    key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # Sigma YAML (source of truth) plus a compiled deterministic matcher spec.
    sigma: Mapped[str] = mapped_column(Text, default="")
    matcher: Mapped[dict] = mapped_column(default=dict)  # deterministic evaluation spec
    severity: Mapped[str] = mapped_column(String(16), default=Severity.MEDIUM.value)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft|review|approved|deployed|disabled
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    attack_techniques: Mapped[list] = mapped_column(default=list)
    data_sources: Mapped[list] = mapped_column(default=list)
    false_positives: Mapped[list] = mapped_column(default=list)
    exceptions: Mapped[list] = mapped_column(default=list)  # allowlists
    deployment_target: Mapped[str] = mapped_column(String(60), default="internal")
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    version_history: Mapped[list] = mapped_column(default=list)
    author: Mapped[str] = mapped_column(String(120), default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Health / quality.
    last_triggered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_data: Mapped[dict] = mapped_column(default=dict)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)


class ThreatIndicator(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "threat_indicators"

    ioc_type: Mapped[str] = mapped_column(String(30), index=True)  # ip|domain|hash|url|email
    value: Mapped[str] = mapped_column(String(500), index=True)
    threat_type: Mapped[str] = mapped_column(String(80), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    severity: Mapped[str] = mapped_column(String(16), default=Severity.MEDIUM.value)
    source: Mapped[str] = mapped_column(String(120), default="")  # misp|virustotal|taxii...
    tlp: Mapped[str] = mapped_column(String(20), default="amber")
    first_seen: Mapped[datetime | None] = mapped_column(nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    tags: Mapped[list] = mapped_column(default=list)
    attributes: Mapped[dict] = mapped_column(default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
