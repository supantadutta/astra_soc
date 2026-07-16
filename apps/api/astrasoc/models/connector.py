"""Connector framework models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import GUID, Base
from .base import TenantMixin, TimestampMixin, UUIDMixin
from .enums import ConnectorCategory, HealthState


class Connector(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "connectors"

    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(60), index=True)  # e.g. crowdstrike_falcon
    category: Mapped[str] = mapped_column(String(24), default=ConnectorCategory.SIEM.value, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    config: Mapped[dict] = mapped_column(default=dict)  # non-secret settings + data mappings
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)  # response permission
    collection_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=120)
    # Whether this connector points at the built-in mock server (demo/testing).
    use_mock: Mapped[bool] = mapped_column(Boolean, default=True)

    credential_refs: Mapped[list[ConnectorCredentialReference]] = relationship(
        back_populates="connector", cascade="all, delete-orphan"
    )
    health_records: Mapped[list[ConnectorHealth]] = relationship(
        back_populates="connector", cascade="all, delete-orphan"
    )


class ConnectorCredentialReference(UUIDMixin, TimestampMixin, Base):
    """Points at a secret in the secret manager. Never stores the value."""

    __tablename__ = "connector_credential_references"

    connector_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("connectors.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(60))  # e.g. api_token, client_secret
    secret_ref: Mapped[str] = mapped_column(String(300))  # e.g. vault://astrasoc/splunk#token
    last_rotated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    connector: Mapped[Connector] = relationship(back_populates="credential_refs")


class ConnectorHealth(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "connector_health"

    connector_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("connectors.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(20), default=HealthState.UNKNOWN.value, index=True)
    checked_at: Mapped[datetime] = mapped_column(index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(default=dict)

    connector: Mapped[Connector] = relationship(back_populates="health_records")
