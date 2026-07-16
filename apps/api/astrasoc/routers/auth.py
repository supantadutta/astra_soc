"""Authentication endpoints: login, refresh, logout, me, API keys."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import get_current_principal
from ..auth.security import (
    create_access_token,
    create_refresh_token,
    generate_api_key,
    hash_token,
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


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        # Uniform error to avoid user enumeration.
        audit.record(
            db, action="auth.login_failed", actor_type="user", outcome="failure",
            data_scope=current_scope(db),
            ip_address=request.client.host if request.client else None,
            detail={"email": body.email},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account disabled")

    sid = uuid.uuid4().hex
    access = create_access_token({"sub": str(user.id), "tid": str(user.tenant_id), "sid": sid})
    refresh, exp = create_refresh_token({"sub": str(user.id), "sid": sid})

    db.add(SessionModel(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:400],
        expires_at=exp,
    ))
    user.last_login_at = datetime.now(UTC)
    audit.record(
        db, action="auth.login", actor_id=user.id, actor_label=user.email,
        tenant_id=user.tenant_id, data_scope=current_scope(db),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return TokenResponse(
        access_token=access, refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    token_hash = hash_token(body.refresh_token)
    sess = db.execute(
        select(SessionModel).where(
            SessionModel.refresh_token_hash == token_hash,
            SessionModel.revoked_at.is_(None),
        )
    ).scalar_one_or_none()
    if sess is None or sess.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User inactive")
    sid = uuid.uuid4().hex
    access = create_access_token({"sub": str(user.id), "tid": str(user.tenant_id), "sid": sid})
    return TokenResponse(
        access_token=access, refresh_token=body.refresh_token,
        expires_in=settings.access_token_ttl_seconds,
    )


@router.post("/logout")
def logout(
    body: RefreshRequest,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    sess = db.execute(
        select(SessionModel).where(
            SessionModel.refresh_token_hash == hash_token(body.refresh_token)
        )
    ).scalar_one_or_none()
    if sess:
        sess.revoked_at = datetime.now(UTC)
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
    return {
        "items": [
            {
                "id": str(s.id),
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "created_at": s.created_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
                "revoked": s.revoked_at is not None,
            }
            for s in rows
        ]
    }


@router.post("/api-keys", response_model=APIKeyCreated, status_code=201)
def create_api_key(
    body: APIKeyCreate,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> APIKeyCreated:
    principal.require("user:manage")
    full, prefix, key_hash = generate_api_key()
    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)
    key = APIKey(
        tenant_id=principal.tenant_id, user_id=principal.user_id, name=body.name,
        prefix=prefix, key_hash=key_hash, scopes=body.scopes, expires_at=expires_at,
    )
    db.add(key)
    audit.record(db, action="apikey.created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="api_key",
                 detail={"name": body.name, "scopes": body.scopes})
    db.commit()
    return APIKeyCreated(
        id=str(key.id), name=key.name, prefix=prefix, api_key=full, scopes=body.scopes
    )
