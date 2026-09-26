"""Authentication endpoints: login, refresh, logout, sessions, API keys, password."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import get_current_principal
from ..auth.permissions import grant_violations
from ..auth.security import (
    create_access_token,
    create_refresh_token,
    generate_api_key,
    hash_password,
    hash_token,
    normalize_email,
    password_policy_errors,
    verify_password,
)
from ..config import settings
from ..db import get_db
from ..models import APIKey, User
from ..models import Session as SessionModel
from ..schemas.auth import (
    APIKeyCreate,
    APIKeyCreated,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from ..services import audit
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _invalid() -> HTTPException:
    # One uniform response for unknown user, wrong password and locked account
    # so the endpoint cannot be used to enumerate accounts.
    return HTTPException(status.HTTP_401_UNAUTHORIZED,
                         detail={"error": "invalid_credentials", "message": "Invalid credentials"})


def _client_ip(request: Request) -> str | None:
    return getattr(request.state, "client_ip", None) or (request.client.host if request.client else None)


def _issue(db: Session, user: User, request: Request) -> TokenResponse:
    sid = uuid.uuid4().hex
    access = create_access_token({"sub": str(user.id), "tid": str(user.tenant_id), "sid": sid})
    refresh, exp = create_refresh_token({"sub": str(user.id), "sid": sid})
    db.add(SessionModel(
        user_id=user.id, sid=sid, refresh_token_hash=hash_token(refresh),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:400], expires_at=exp,
        last_used_at=datetime.now(UTC),
    ))
    return TokenResponse(access_token=access, refresh_token=refresh,
                         expires_in=settings.access_token_ttl_seconds)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = normalize_email(body.email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = datetime.now(UTC)
    ip = _client_ip(request)

    locked = bool(user and user.locked_until and user.locked_until > now)
    if user is None or locked or not verify_password(body.password, user.password_hash):
        if user is not None and not locked:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
                audit.record(db, action="auth.account_locked", actor_id=user.id,
                             actor_label=user.email, tenant_id=user.tenant_id, outcome="failure",
                             data_scope=current_scope(db, user.tenant_id), ip_address=ip,
                             detail={"minutes": settings.login_lockout_minutes})
        audit.record(
            db, action="auth.login_failed", actor_type="user", outcome="failure",
            tenant_id=user.tenant_id if user else None,
            data_scope=current_scope(db, user.tenant_id if user else None), ip_address=ip,
            detail={"email": email, "locked": locked},
        )
        db.commit()
        raise _invalid()
    if not user.is_active:
        raise _invalid()

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    tokens = _issue(db, user, request)
    audit.record(db, action="auth.login", actor_id=user.id, actor_label=user.email,
                 tenant_id=user.tenant_id, data_scope=current_scope(db, user.tenant_id),
                 ip_address=ip)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """Rotate the refresh token. Presenting an already-rotated token is treated
    as token theft: the whole session is revoked."""
    token_hash = hash_token(body.refresh_token)
    now = datetime.now(UTC)
    sess = db.execute(select(SessionModel).where(
        SessionModel.refresh_token_hash == token_hash)).scalar_one_or_none()
    if sess is None:
        reused = db.execute(select(SessionModel).where(
            SessionModel.previous_token_hash == token_hash)).scalar_one_or_none()
        if reused is not None and reused.revoked_at is None:
            reused.revoked_at = now
            reused.revoked_reason = "refresh_token_reuse"
            audit.record(db, action="auth.refresh_reuse_detected", actor_id=reused.user_id,
                         outcome="failure", ip_address=_client_ip(request),
                         detail={"session": str(reused.id)})
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    if sess.revoked_at is not None or sess.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    new_refresh, _ = create_refresh_token({"sub": str(user.id), "sid": sess.sid})
    sess.previous_token_hash = sess.refresh_token_hash
    sess.refresh_token_hash = hash_token(new_refresh)
    sess.last_used_at = now
    access = create_access_token({"sub": str(user.id), "tid": str(user.tenant_id), "sid": sess.sid})
    db.commit()
    return TokenResponse(access_token=access, refresh_token=new_refresh,
                         expires_in=settings.access_token_ttl_seconds)


@router.post("/logout")
def logout(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke the caller's session server-side. Every access and refresh token
    issued for it stops working immediately."""
    if principal.session_id:
        sess = db.execute(select(SessionModel).where(
            SessionModel.sid == principal.session_id)).scalar_one_or_none()
        if sess and sess.revoked_at is None:
            sess.revoked_at = datetime.now(UTC)
            sess.revoked_reason = "logout"
    audit.record(db, action="auth.logout", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, actor_label=principal.email)
    db.commit()
    return {"status": "logged_out"}


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(get_current_principal)) -> MeResponse:
    return MeResponse(
        id=str(principal.user_id),
        email=principal.email,
        full_name=principal.full_name,
        tenant_id=str(principal.tenant_id),
        roles=principal.roles,
        permissions=principal.permissions,
        is_service_account=principal.is_service_account,
    )


@router.get("/sessions")
def list_sessions(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(SessionModel).where(SessionModel.user_id == principal.user_id)
        .order_by(SessionModel.created_at.desc()).limit(50)
    ).scalars().all()
    return {"items": [{
        "id": str(s.id), "ip_address": s.ip_address, "user_agent": s.user_agent,
        "created_at": s.created_at.isoformat(), "expires_at": s.expires_at.isoformat(),
        "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
        "revoked": s.revoked_at is not None, "revoked_reason": s.revoked_reason,
        "current": s.sid == principal.session_id,
    } for s in rows]}


@router.post("/sessions/{session_id}/revoke")
def revoke_session(session_id: uuid.UUID,
                   principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> dict:
    sess = db.get(SessionModel, session_id)
    if sess is None or sess.user_id != principal.user_id:
        raise HTTPException(404, detail="Session not found")
    if sess.revoked_at is None:
        sess.revoked_at = datetime.now(UTC)
        sess.revoked_reason = "user_revoked"
    audit.record(db, action="auth.session_revoked", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="session", resource_id=str(session_id))
    db.commit()
    return {"status": "revoked"}


@router.post("/password")
def change_password(payload: dict = Body(...),
                    principal: Principal = Depends(get_current_principal),
                    db: Session = Depends(get_db)) -> dict:
    """Change own password. Revokes every other session of the user."""
    user = db.get(User, principal.user_id)
    if user is None or not verify_password(str(payload.get("current_password", "")), user.password_hash):
        raise HTTPException(400, detail={"error": "invalid_password",
                                         "message": "Current password is incorrect."})
    new = str(payload.get("new_password", ""))
    problems = password_policy_errors(new)
    if problems:
        raise HTTPException(422, detail={"error": "weak_password", "message": "; ".join(problems)})
    user.password_hash = hash_password(new)
    user.password_changed_at = datetime.now(UTC)
    for s in db.execute(select(SessionModel).where(
            SessionModel.user_id == user.id, SessionModel.revoked_at.is_(None))).scalars():
        if s.sid != principal.session_id:
            s.revoked_at = datetime.now(UTC)
            s.revoked_reason = "password_changed"
    audit.record(db, action="auth.password_changed", actor_id=user.id,
                 tenant_id=user.tenant_id, actor_label=user.email)
    db.commit()
    return {"status": "password_changed"}


# --- API keys ----------------------------------------------------------------
@router.get("/api-keys")
def list_api_keys(principal: Principal = Depends(get_current_principal),
                  db: Session = Depends(get_db)) -> dict:
    principal.require("user:manage")
    rows = db.execute(select(APIKey).where(APIKey.tenant_id == principal.tenant_id)
                      .order_by(APIKey.created_at.desc())).scalars().all()
    return {"items": [{
        "id": str(k.id), "name": k.name, "prefix": k.prefix, "scopes": k.scopes,
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "revoked": k.revoked_at is not None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
    } for k in rows]}


@router.post("/api-keys", response_model=APIKeyCreated, status_code=201)
def create_api_key(
    body: APIKeyCreate,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> APIKeyCreated:
    principal.require("user:manage")
    if not body.scopes:
        raise HTTPException(422, detail={"error": "scopes_required",
                                         "message": "API keys must declare explicit scopes."})
    bad = grant_violations(principal.permissions, body.scopes)
    if bad:
        raise HTTPException(403, detail={"error": "scope_not_grantable",
                                         "message": "You cannot grant scopes you do not hold.",
                                         "detail": bad})
    days = body.expires_in_days or 90
    if days < 1 or days > 365:
        raise HTTPException(422, detail="expires_in_days must be between 1 and 365")
    full, prefix, key_hash = generate_api_key()
    key = APIKey(
        tenant_id=principal.tenant_id, user_id=principal.user_id, name=body.name,
        prefix=prefix, key_hash=key_hash, scopes=body.scopes,
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )
    db.add(key)
    db.flush()
    audit.record(db, action="apikey.created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="api_key", resource_id=str(key.id),
                 detail={"name": body.name, "scopes": body.scopes, "expires_in_days": days})
    db.commit()
    return APIKeyCreated(
        id=str(key.id), name=key.name, prefix=prefix, api_key=full, scopes=body.scopes
    )


@router.post("/api-keys/{key_id}/revoke")
def revoke_api_key(key_id: uuid.UUID,
                   principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> dict:
    principal.require("user:manage")
    key = db.get(APIKey, key_id)
    if key is None or key.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="API key not found")
    key.revoked_at = key.revoked_at or datetime.now(UTC)
    audit.record(db, action="apikey.revoked", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="api_key", resource_id=str(key_id))
    db.commit()
    return {"status": "revoked"}
