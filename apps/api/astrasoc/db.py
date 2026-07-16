"""Database engine, session management, and the declarative base.

The models are written to run on **either** SQLite (the zero-dependency demo
profile) or PostgreSQL (development/production). To stay portable we use a
custom :class:`GUID` type that maps to native ``UUID`` on Postgres and to a
``CHAR(36)`` on SQLite, and a JSON type that degrades gracefully.
"""
from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, String, TypeDecorator, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import JSON


class TZDateTime(TypeDecorator):
    """Timezone-aware datetime that stays aware even on SQLite.

    SQLite has no native tz type, so stored datetimes come back naive; we coerce
    them to UTC-aware on read so comparisons with ``datetime.now(timezone.utc)``
    never raise. On Postgres this is a passthrough over ``TIMESTAMPTZ``.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

from .config import settings

# Deterministic constraint naming keeps Alembic migrations stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class GUID(TypeDecorator):
    """Platform-independent UUID type."""

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def JSONType():
    """JSONB on Postgres, generic JSON elsewhere."""
    return JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        dict: JSONType(),
        list: JSONType(),
        datetime: TZDateTime(),
    }


connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=not settings.is_sqlite,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (used by the demo/test profiles; production uses Alembic)."""
    from . import models  # noqa: F401  (ensures all models are registered)

    Base.metadata.create_all(bind=engine)
