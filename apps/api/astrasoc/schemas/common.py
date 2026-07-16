"""Common API schemas: pagination, standard errors, serialization helpers."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy.orm import DeclarativeBase

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(cls, items: list[T], total: int, page: int, page_size: int) -> Page[T]:
        pages = (total + page_size - 1) // page_size if page_size else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


class ErrorResponse(BaseModel):
    error: str
    message: str
    request_id: str | None = None
    detail: Any | None = None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=200)
    sort: str | None = None
    order: str = Field(default="desc", pattern="^(asc|desc)$")
    q: str | None = None


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def serialize(obj: DeclarativeBase, exclude: set[str] | None = None) -> dict[str, Any]:
    """Convert a SQLAlchemy model instance to a JSON-safe dict."""
    exclude = exclude or set()
    result: dict[str, Any] = {}
    for column in obj.__table__.columns:
        if column.name in exclude:
            continue
        result[column.name] = _json_safe(getattr(obj, column.name))
    return result


def serialize_many(objs: list[DeclarativeBase], exclude: set[str] | None = None) -> list[dict]:
    return [serialize(o, exclude) for o in objs]
