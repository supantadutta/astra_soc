"""FastAPI dependencies for authentication and authorization."""
from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import APIKey, Role, Tenant, User, UserRole
from ..models import Session as SessionModel
from .context import Principal
from .permissions import role_has_permission
from .security import decode_token, hash_token


def _effective_permissions(db: Session, user: User) -> tuple[list[str], list[str]]:
    """Union of permissions across the user's active (non-expired) roles."""
    now = datetime.now(UTC)
    rows = db.execute(
        select(UserRole, Role).join(Role, UserRole.role_id == Role.id).where(
            UserRole.user_id == user.id
        )
    ).all()
    perms: set[str] = set()
    roles: list[str] = []
    for ur, role in rows:
        if ur.expires_at is not None and ur.expires_at < now:
            continue  # expired temporary elevation
        roles.append(role.name)
        perms.update(role.permissions or [])
    return sorted(perms), roles


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED,
                         detail={"error": "unauthorized", "message": message},
                         headers={"WWW-Authenticate": "Bearer"})


def _check_tenant_active(db: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail={"error": "tenant_inactive", "message": "Tenant is disabled."})
    return tenant


def _principal_from_user(db: Session, user: User, session_id: str | None = None,
                         scopes: list[str] | None = None) -> Principal:
    perms, roles = _effective_permissions(db, user)
    tenant = _check_tenant_active(db, user.tenant_id)
    if scopes:
        # A scoped API key can never exceed its owner's current permissions.
        perms = sorted(p for p in scopes if role_has_permission(perms, p))
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        roles=roles,
        permissions=perms,
        is_service_account=user.is_service_account,
        allowed_classifications=(user.attributes or {}).get(
            "allowed_classifications", ["public", "internal", "confidential"]
        ),
        session_id=session_id,
        tenant_slug=tenant.slug,
    )


def get_current_principal(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    """Resolve the caller from a Bearer JWT or an API key."""
    # 1) API key (machine identities).
    if x_api_key:
        prefix = x_api_key.split(".", 1)[0]
        key = db.execute(
            select(APIKey).where(APIKey.prefix == prefix, APIKey.revoked_at.is_(None))
        ).scalar_one_or_none()
        if key and hmac.compare_digest(hash_token(x_api_key), key.key_hash):
            if key.expires_at and key.expires_at < datetime.now(UTC):
                raise _unauthorized("API key expired")
            user = db.get(User, key.user_id) if key.user_id else None
            if user is None or not user.is_active:
                raise _unauthorized("API key owner is missing or disabled")
            key.last_used_at = datetime.now(UTC)
            db.flush()
            return _principal_from_user(db, user, scopes=key.scopes or None)
        raise _unauthorized("Invalid API key")

    # 2) Bearer JWT (interactive users).
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")
    if payload.get("type") != "access":
        raise _unauthorized("Wrong token type")
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except ValueError:
        raise _unauthorized("Invalid token subject")

    # Every access token is bound to a live session; logout / revocation /
    # refresh-token theft detection immediately invalidates it.
    sid = payload.get("sid")
    if not sid:
        raise _unauthorized("Token is not bound to a session")
    sess = db.execute(select(SessionModel).where(
        SessionModel.sid == sid, SessionModel.user_id == user_id)).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or sess.expires_at < datetime.now(UTC):
        raise _unauthorized("Session revoked or expired")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive")
    return _principal_from_user(db, user, session_id=sid)


def require_permission(permission: str):
    """Dependency factory enforcing a single permission on a route."""

    def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        principal.require(permission)
        return principal

    return _dep


def require_any(*permissions: str):
    def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not any(principal.has(p) for p in permissions):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"error": "forbidden",
                        "message": f"Requires one of: {', '.join(permissions)}"},
            )
        return principal

    return _dep
