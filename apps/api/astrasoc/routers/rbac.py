"""RBAC + Tenant Management APIs: roles, permissions, users, assignments."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..auth.permissions import PERMISSIONS
from ..auth.security import hash_password
from ..db import get_db
from ..models import Role, Tenant, User, UserRole
from ..schemas.common import serialize, serialize_many
from ..services import audit

router = APIRouter(prefix="/api/v1/rbac", tags=["rbac"])


@router.get("/permissions")
def list_permissions(principal: Principal = Depends(require_permission("rbac:manage"))) -> dict:
    return {"permissions": [{"key": k, "category": k.split(":", 1)[0], "description": v}
                            for k, v in PERMISSIONS.items()]}


@router.get("/roles")
def list_roles(principal: Principal = Depends(require_permission("rbac:manage")),
               db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Role).where(
        (Role.tenant_id == principal.tenant_id) | (Role.tenant_id.is_(None)))).scalars().all()
    return {"items": serialize_many(rows)}


@router.post("/roles")
def create_role(payload: dict,
                principal: Principal = Depends(require_permission("rbac:manage")),
                db: Session = Depends(get_db)) -> dict:
    invalid = [p for p in payload.get("permissions", []) if p not in PERMISSIONS and p != "*"]
    if invalid:
        raise HTTPException(422, detail={"error": "unknown_permissions", "detail": invalid})
    role = Role(tenant_id=principal.tenant_id, name=payload["name"],
                description=payload.get("description", ""),
                permissions=payload.get("permissions", []), is_builtin=False)
    db.add(role)
    audit.record(db, action="rbac.role_created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="role", resource_id=str(role.id))
    db.commit()
    return serialize(role)


@router.patch("/roles/{role_id}")
def update_role(role_id: uuid.UUID, payload: dict,
                principal: Principal = Depends(require_permission("rbac:manage")),
                db: Session = Depends(get_db)) -> dict:
    role = db.get(Role, role_id)
    if not role or (role.tenant_id and role.tenant_id != principal.tenant_id):
        raise HTTPException(404, detail="Role not found")
    if role.is_builtin:
        raise HTTPException(400, detail="Built-in roles cannot be edited.")
    for f in ("name", "description", "permissions"):
        if f in payload:
            setattr(role, f, payload[f])
    audit.record(db, action="rbac.role_updated", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="role", resource_id=str(role_id))
    db.commit()
    return serialize(role)


@router.get("/users")
def list_users(principal: Principal = Depends(require_permission("user:manage")),
               db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(User).where(User.tenant_id == principal.tenant_id)).scalars().all()
    out = []
    for u in rows:
        data = serialize(u, exclude={"password_hash"})
        assignments = db.execute(select(UserRole, Role).join(
            Role, UserRole.role_id == Role.id).where(UserRole.user_id == u.id)).all()
        data["roles"] = [{"role": r.name, "expires_at": ur.expires_at.isoformat()
                          if ur.expires_at else None} for ur, r in assignments]
        out.append(data)
    return {"items": out}


@router.post("/users")
def create_user(payload: dict,
                principal: Principal = Depends(require_permission("user:manage")),
                db: Session = Depends(get_db)) -> dict:
    if db.execute(select(User).where(User.email == payload["email"])).scalar_one_or_none():
        raise HTTPException(409, detail="A user with that email already exists.")
    user = User(tenant_id=principal.tenant_id, email=payload["email"],
                full_name=payload.get("full_name", payload["email"]),
                password_hash=hash_password(payload.get("password", "ChangeMe!123")),
                is_service_account=payload.get("is_service_account", False),
                attributes={"allowed_classifications": payload.get(
                    "allowed_classifications", ["public", "internal", "confidential"])})
    db.add(user)
    db.flush()
    for role_name in payload.get("roles", []):
        role = db.execute(select(Role).where(Role.tenant_id == principal.tenant_id,
                                             Role.name == role_name)).scalar_one_or_none()
        if role:
            db.add(UserRole(user_id=user.id, role_id=role.id))
    audit.record(db, action="rbac.user_created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="user", resource_id=str(user.id))
    db.commit()
    return serialize(user, exclude={"password_hash"})


@router.post("/users/{user_id}/roles")
def assign_role(user_id: uuid.UUID, payload: dict,
                principal: Principal = Depends(require_permission("rbac:manage")),
                db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if not user or user.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="User not found")
    role = db.execute(select(Role).where(Role.tenant_id == principal.tenant_id,
                                         Role.name == payload["role"])).scalar_one_or_none()
    if not role:
        raise HTTPException(404, detail="Role not found")
    expires_at = None
    if payload.get("temporary_minutes"):  # temporary elevation
        expires_at = datetime.now(UTC) + timedelta(minutes=payload["temporary_minutes"])
    existing = db.execute(select(UserRole).where(UserRole.user_id == user_id,
                                                 UserRole.role_id == role.id)).scalar_one_or_none()
    if existing:
        existing.expires_at = expires_at
    else:
        db.add(UserRole(user_id=user_id, role_id=role.id, expires_at=expires_at,
                        granted_by=principal.user_id))
    audit.record(db, action="rbac.role_assigned", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="user", resource_id=str(user_id),
                 detail={"role": payload["role"], "temporary": bool(expires_at)})
    db.commit()
    return {"status": "assigned", "role": payload["role"], "expires_at":
            expires_at.isoformat() if expires_at else None}


@router.delete("/users/{user_id}/roles/{role_name}")
def revoke_role(user_id: uuid.UUID, role_name: str,
                principal: Principal = Depends(require_permission("rbac:manage")),
                db: Session = Depends(get_db)) -> dict:
    role = db.execute(select(Role).where(Role.tenant_id == principal.tenant_id,
                                         Role.name == role_name)).scalar_one_or_none()
    if role:
        ur = db.execute(select(UserRole).where(UserRole.user_id == user_id,
                                               UserRole.role_id == role.id)).scalar_one_or_none()
        if ur:
            db.delete(ur)
            audit.record(db, action="rbac.role_revoked", actor_id=principal.user_id,
                         tenant_id=principal.tenant_id, resource_type="user",
                         resource_id=str(user_id), detail={"role": role_name})
    db.commit()
    return {"status": "revoked"}


# --- Tenant management ----------------------------------------------------
tenants_router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@tenants_router.get("")
def list_tenants(principal: Principal = Depends(require_permission("tenant:manage")),
                 db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Tenant)).scalars().all()
    return {"items": serialize_many(rows)}


@tenants_router.get("/current")
def current_tenant(principal: Principal = Depends(require_permission("incident:read")),
                   db: Session = Depends(get_db)) -> dict:
    t = db.get(Tenant, principal.tenant_id)
    return serialize(t) if t else {}


@tenants_router.patch("/{tenant_id}")
def update_tenant(tenant_id: uuid.UUID, payload: dict,
                  principal: Principal = Depends(require_permission("tenant:manage")),
                  db: Session = Depends(get_db)) -> dict:
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, detail="Tenant not found")
    for f in ("name", "is_active", "settings"):
        if f in payload:
            setattr(t, f, payload[f])
    db.commit()
    return serialize(t)
