"""MSSP operating models: delegated access, usage metering, shift handover."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import GUID, Base
from .base import TimestampMixin, UUIDMixin


class TenantAccessGrant(UUIDMixin, TimestampMixin, Base):
    """Explicit, auditable permission for a provider/reseller user to act
    inside a descendant customer tenant with a named role of that tenant.

    Grants can be time-boxed (``expires_at``) and must carry a reason; the
    customer can veto all provider access through its delegation policy.
    """

    __tablename__ = "tenant_access_grants"
    __table_args__ = (
        Index("ix_grants_user_customer", "user_id", "customer_tenant_id"),
    )

    provider_tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    customer_tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_name: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text, default="")
    granted_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class UsageCounter(UUIDMixin, TimestampMixin, Base):
    """Monthly metering per tenant — the basis for MSSP billing and capacity
    planning. ``period`` is ``YYYY-MM`` (UTC)."""

    __tablename__ = "usage_counters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period", "metric", name="uq_usage_tenant_period_metric"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    period: Mapped[str] = mapped_column(String(7), index=True)
    metric: Mapped[str] = mapped_column(String(40), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)


class ShiftHandover(UUIDMixin, TimestampMixin, Base):
    """A SOC shift handover note written by provider staff. May reference
    incidents in any customer the author could access at the time."""

    __tablename__ = "shift_handovers"

    provider_tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    author_label: Mapped[str] = mapped_column(String(200), default="")
    shift: Mapped[str] = mapped_column(String(40), default="")  # e.g. "2026-09-26 day"
    summary: Mapped[str] = mapped_column(Text, default="")
    # [{"tenant_id","incident_id","incident_key","note","owner"}]
    open_items: Mapped[list] = mapped_column(default=list)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
