"""Reusable model mixins: UUID PKs, timestamps, tenant scoping, data scope."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import GUID, new_uuid, utcnow
from .enums import DataScope


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class TenantMixin:
    """Every operational row is scoped to a tenant for isolation."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )


class ScopeMixin:
    """DEMO vs LIVE separation. Enforced by the query layer, never mixed."""

    data_scope: Mapped[str] = mapped_column(
        String(8), default=DataScope.DEMO.value, index=True
    )


def scoped_index(*columns: str, name: str) -> Index:
    return Index(name, *columns)
