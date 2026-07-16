"""FastAPI dependencies for authentication and authorization."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import APIKey, Role, User, UserRole
from .context import Principal
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


def _principal_from_user(db: Session, user: User, session_id: str | None = None) -> Principal:
    perms, roles = _effective_permissions(db, user)
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
        if key and hash_token(x_api_key) == key.key_hash:
            if key.expires_at and key.expires_at < datetime.now(UTC):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="API key expired")
            key.last_used_at = datetime.now(UTC)
            user = db.get(User, key.user_id) if key.user_id else None
            if user is None:
                # Scope-only key without a user — synthesize a service principal.
                return Principal(
                    user_id=key.id, tenant_id=key.tenant_id,
                    email=f"{key.prefix}@service", full_name=key.name,
                    roles=["service"], permissions=key.scopes or [],
                    is_service_account=True,
                )
            db.flush()
            return _principal_from_user(db, user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    # 2) Bearer JWT (interactive users).
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "message": "Missing bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")

    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return _principal_from_user(db, user, session_id=payload.get("sid"))


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
