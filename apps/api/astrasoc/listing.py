"""Generic list-endpoint helper: tenant + scope scoping, filter, sort, paginate."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, asc, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from .schemas.common import serialize_many


def paginate(
    db: Session,
    model,
    *,
    tenant_id: uuid.UUID | None = None,
    scope: str | None = None,
    filters: list | None = None,
    search: str | None = None,
    search_fields: list[str] | None = None,
    sort: str | None = None,
    order: str = "desc",
    page: int = 1,
    page_size: int = 25,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    stmt = select(model)
    count_stmt = select(func.count()).select_from(model)

    conds = []
    if tenant_id is not None and hasattr(model, "tenant_id"):
        conds.append(model.tenant_id == tenant_id)
    if scope is not None and hasattr(model, "data_scope"):
        conds.append(model.data_scope == scope)
    if filters:
        conds.extend(filters)
    if search and search_fields:
        like = f"%{search.lower()}%"
        ors = [func.lower(cast(getattr(model, f), String)).like(like)
               for f in search_fields if hasattr(model, f)]
        if ors:
            conds.append(or_(*ors))
    for c in conds:
        stmt = stmt.where(c)
        count_stmt = count_stmt.where(c)

    total = db.execute(count_stmt).scalar() or 0

    sort_col = getattr(model, sort, None) if sort else None
    if sort_col is None:
        sort_col = getattr(model, "created_at", None) or model.id
    stmt = stmt.order_by(asc(sort_col) if order == "asc" else desc(sort_col))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = db.execute(stmt).scalars().all()
    pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "items": serialize_many(rows, exclude),
        "total": total, "page": page, "page_size": page_size, "pages": pages,
    }
