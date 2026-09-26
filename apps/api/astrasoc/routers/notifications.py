"""In-app notifications for the caller's (acting) tenant."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..models import Notification
from ..schemas.common import serialize_many

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def _mine(principal: Principal):
    return (Notification.tenant_id == principal.tenant_id,
            or_(Notification.user_id.is_(None), Notification.user_id == principal.user_id))


@router.get("")
def list_notifications(principal: Principal = Depends(require_permission("notification:read")),
                       db: Session = Depends(get_db), unread: bool = False,
                       limit: int = Query(50, ge=1, le=200)) -> dict:
    q = select(Notification).where(*_mine(principal))
    if unread:
        q = q.where(Notification.read_at.is_(None))
    rows = db.execute(q.order_by(Notification.created_at.desc()).limit(limit)).scalars().all()
    unread_count = db.execute(select(func.count()).select_from(Notification).where(
        *_mine(principal), Notification.read_at.is_(None))).scalar() or 0
    return {"items": serialize_many(rows), "unread": unread_count}


@router.post("/{notification_id}/read")
def mark_read(notification_id: uuid.UUID,
              principal: Principal = Depends(require_permission("notification:read")),
              db: Session = Depends(get_db)) -> dict:
    n = db.get(Notification, notification_id)
    if n is None or n.tenant_id != principal.tenant_id or n.user_id not in (None, principal.user_id):
        raise HTTPException(404, detail="Notification not found")
    n.read_at = n.read_at or datetime.now(UTC)
    db.commit()
    return {"status": "read"}


@router.post("/read-all")
def mark_all_read(principal: Principal = Depends(require_permission("notification:read")),
                  db: Session = Depends(get_db)) -> dict:
    res = db.execute(update(Notification).where(*_mine(principal), Notification.read_at.is_(None))
                     .values(read_at=datetime.now(UTC)))
    db.commit()
    return {"status": "read", "count": res.rowcount or 0}
