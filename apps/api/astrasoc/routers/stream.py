"""Authenticated, tenant-isolated Server-Sent Events.

Browsers cannot attach an Authorization header to ``EventSource``, so the
client first exchanges its normal credentials for a short-lived *stream
ticket* (``POST /stream/ticket``, honours ``X-Tenant-ID``) and opens
``GET /stream?ticket=…``. The ticket is a 60-second JWT of type ``stream``
bound to the user's session, acting tenant and scope. The session is
re-checked on every heartbeat, so logout / revocation ends the stream.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from ..auth.context import Principal
from ..auth.deps import get_current_principal
from ..auth.security import decode_token
from ..config import settings
from ..db import SessionLocal, get_db
from ..models import Session as SessionModel
from ..services.events import bus
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1", tags=["stream"])

TICKET_TTL = 60
HEARTBEAT = 15.0


@router.post("/stream/ticket")
def stream_ticket(principal: Principal = Depends(get_current_principal),
                  db=Depends(get_db)) -> dict:
    scope = current_scope(db, principal.tenant_id)
    now = datetime.now(UTC)
    extra = []
    if principal.home_tenant_id and principal.home_tenant_id != principal.tenant_id:
        extra.append(str(principal.home_tenant_id))
    payload = {
        "type": "stream", "sub": str(principal.user_id), "sid": principal.session_id,
        "tid": str(principal.tenant_id), "extra": extra, "scope": scope,
        "iat": now, "exp": now + timedelta(seconds=TICKET_TTL),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return {"ticket": token, "expires_in": TICKET_TTL, "scope": scope,
            "tenant_id": str(principal.tenant_id)}


def _session_alive(user_id: str, sid: str | None) -> bool:
    if not sid:  # API-key principals have no interactive session
        return True
    with SessionLocal() as db:
        sess = db.execute(select(SessionModel).where(
            SessionModel.sid == sid, SessionModel.user_id == uuid.UUID(user_id))).scalar_one_or_none()
        return bool(sess and sess.revoked_at is None and sess.expires_at > datetime.now(UTC))


@router.get("/stream")
async def event_stream(request: Request, ticket: str):
    try:
        claims = decode_token(ticket)
    except jwt.PyJWTError:
        raise HTTPException(401, detail={"error": "unauthorized", "message": "Invalid stream ticket"})
    if claims.get("type") != "stream":
        raise HTTPException(401, detail={"error": "unauthorized", "message": "Wrong token type"})
    user_id, sid = claims["sub"], claims.get("sid")
    if not await asyncio.to_thread(_session_alive, user_id, sid):
        raise HTTPException(401, detail={"error": "unauthorized", "message": "Session revoked"})

    tenant_id, scope = claims["tid"], claims["scope"]
    extra = set(claims.get("extra") or [])
    sub = bus.subscribe(tenant_id, scope, extra)

    async def generator():
        try:
            for ev in bus.recent(tenant_id, scope, limit=20, extra_tenants=extra):
                yield ev.sse()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(sub.queue.get(), timeout=HEARTBEAT)
                    yield ev.sse()
                except TimeoutError:
                    if not await asyncio.to_thread(_session_alive, user_id, sid):
                        yield {"event": "session_ended", "data": "{}"}
                        break
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            bus.unsubscribe(sub)

    return EventSourceResponse(generator())
