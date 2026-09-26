"""RBAC APIs (roles, users, assignments) and the caller's own tenant profile.

Grant rules (enforced here, not in the UI):
* a principal can only grant permissions it holds itself;
* the wildcard and platform-level permissions can only be granted by a
  platform administrator;
* provider-level (``mssp:*``) permissions only exist in provider/reseller
  tenants;
* every user/role lookup is confined to the caller's (acting) tenant.

Cross-tenant tenant administration lives in :mod:`astrasoc.routers.mssp`.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import get_current_principal, require_permission
from ..auth.permissions import PERMISSIONS, PROVIDER_PERMISSIONS, grant_violations
from ..db import get_db
from ..models import Role, Tenant, User, UserRole
from ..models import Session as SessionModel
from ..schemas.common import serialize, serialize_many
from ..services import audit
from ..services.tenancy import accessible_tenants, delegation_policy
from ..services.tenants import TenantError, clean_branding, clean_contacts
from ..services.tenants import create_user as provision_user

router = APIRouter(prefix="/api/v1/rbac", tags=["rbac"])

_ROLE_NAME = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"]


def _tenant(db: Session, principal: Principal) -> Tenant:
    t = db.get(Tenant, principal.tenant_id)
    if t is None:
        raise HTTPException(404, detail="Tenant not found")
    return t


def _check_grantable(db: Session, principal: Principal, perms: list[str]) -> None:
    bad = grant_violations(principal.permissions, perms)
    tenant = _tenant(db, principal)
    if tenant.kind == "customer":
        bad += [p for p in perms if p in PROVIDER_PERMISSIONS and p not in bad]
    if bad:
        raise HTTPException(403, detail={
            "error": "permission_not_grantable",
            "message": "You can only grant permissions you hold; platform and provider "
                       "permissions are restricted.", "detail": sorted(set(bad))})


def _user_in_tenant(db: Session, principal: Principal, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="User not found")
    return user


def _role_in_tenant(db: Session, principal: Principal, name: str) -> Role:
    role = db.execute(select(Role).where(
        Role.tenant_id == principal.tenant_id, Role.name == name)).scalar_one_or_none()
    if role is None:
        raise HTTPException(404, detail="Role not found")
    return role


@router.get("/permissions")
def list_permissions(principal: Principal = Depends(require_permission("rbac:manage"))) -> dict:
    return {"permissions": [{"key": k, "category": k.split(":", 1)[0], "description": v}
                            for k, v in PERMISSIONS.items()]}


@router.get("/roles")
def list_roles(principal: Principal = Depends(require_permission("rbac:manage")),
               db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Role).where(Role.tenant_id == principal.tenant_id)
                      .order_by(Role.name)).scalars().all()
    return {"items": serialize_many(rows)}


@router.post("/roles")
def create_role(payload: dict = Body(...),
                principal: Principal = Depends(require_permission("rbac:manage")),
                db: Session = Depends(get_db)) -> dict:
    name = str(payload.get("name", "")).strip()
    if not _ROLE_NAME.match(name):
        raise HTTPException(422, detail="Role name must be 3-80 chars: lowercase, digits, '_'.")
    if db.execute(select(Role).where(Role.tenant_id == principal.tenant_id, Role.name == name)).first():
        raise HTTPException(409, detail="A role with that name already exists.")
    perms = sorted(set(payload.get("permissions") or []))
    _check_grantable(db, principal, perms)
    role = Role(tenant_id=principal.tenant_id, name=name,
                description=str(payload.get("description", ""))[:1000],
                permissions=perms, is_builtin=False)
    db.add(role)
    db.flush()
    audit.record(db, action="rbac.role_created", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="role", resource_id=str(role.id),
                 detail={"name": name, "permissions": perms})
    db.commit()
    return serialize(role)


@router.patch("/roles/{role_id}")
def update_role(role_id: uuid.UUID, payload: dict = Body(...),
                principal: Principal = Depends(require_permission("rbac:manage")),
                db: Session = Depends(get_db)) -> dict:
    role = db.get(Role, role_id)
    if role is None or role.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Role not found")
    if role.is_builtin:
        raise HTTPException(400, detail="Built-in roles cannot be edited; create a custom role.")
    if "permissions" in payload:
        perms = sorted(set(payload["permissions"] or []))
        _check_grantable(db, principal, perms)
        role.permissions = perms
    if "description" in payload:
        role.description = str(payload["description"])[:1000]
    audit.record(db, action="rbac.role_updated", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="role", resource_id=str(role_id), detail={"fields": list(payload)})
    db.commit()
    return serialize(role)


@router.get("/users")
def list_users(principal: Principal = Depends(require_permission("user:manage")),
               db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(User).where(User.tenant_id == principal.tenant_id)
                      .order_by(User.email)).scalars().all()
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
def create_user(payload: dict = Body(...),
                principal: Principal = Depends(require_permission("user:manage")),
                db: Session = Depends(get_db)) -> dict:
    role_names = list(payload.get("roles") or [])
    for name in role_names:
        _check_grantable(db, principal, _role_in_tenant(db, principal, name).permissions or [])
    classes = payload.get("allowed_classifications") or ["public", "internal", "confidential"]
    if any(c not in CLASSIFICATIONS for c in classes):
        raise HTTPException(422, detail=f"allowed_classifications must be within {CLASSIFICATIONS}")
    try:
        user = provision_user(
            db, _tenant(db, principal), email=str(payload.get("email", "")),
            full_name=str(payload.get("full_name", "")), password=str(payload.get("password", "")),
            roles=role_names, attributes={"allowed_classifications": classes})
    except TenantError as exc:
        raise HTTPException(409 if exc.code == "conflict" else 422,
                            detail={"error": exc.code, "message": exc.message})
    audit.record(db, action="rbac.user_created", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="user", resource_id=str(user.id),
                 detail={"email": user.email, "roles": role_names})
    db.commit()
    return serialize(user, exclude={"password_hash"})


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, payload: dict = Body(...),
                principal: Principal = Depends(require_permission("user:manage")),
                db: Session = Depends(get_db)) -> dict:
    user = _user_in_tenant(db, principal, user_id)
    if "is_active" in payload:
        active = bool(payload["is_active"])
        if not active and user.id == principal.user_id:
            raise HTTPException(400, detail="You cannot deactivate your own account.")
        user.is_active = active
        if not active:
            for s in db.execute(select(SessionModel).where(
                    SessionModel.user_id == user.id, SessionModel.revoked_at.is_(None))).scalars():
                s.revoked_at, s.revoked_reason = datetime.now(UTC), "user_deactivated"
        if active:
            user.locked_until, user.failed_login_count = None, 0
    if "full_name" in payload:
        user.full_name = str(payload["full_name"])[:200]
    if "allowed_classifications" in payload:
        classes = list(payload["allowed_classifications"] or [])
        if any(c not in CLASSIFICATIONS for c in classes):
            raise HTTPException(422, detail=f"allowed_classifications must be within {CLASSIFICATIONS}")
        user.attributes = {**(user.attributes or {}), "allowed_classifications": classes}
    audit.record(db, action="rbac.user_updated", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="user", resource_id=str(user_id), detail={"fields": list(payload)})
    db.commit()
    return serialize(user, exclude={"password_hash"})


@router.post("/users/{user_id}/roles")
def assign_role(user_id: uuid.UUID, payload: dict = Body(...),
                principal: Principal = Depends(require_permission("rbac:manage")),
                db: Session = Depends(get_db)) -> dict:
    user = _user_in_tenant(db, principal, user_id)
    role = _role_in_tenant(db, principal, str(payload.get("role", "")))
    _check_grantable(db, principal, role.permissions or [])
    expires_at = None
    minutes = payload.get("temporary_minutes")
    if minutes:
        minutes = int(minutes)
        if minutes < 1 or minutes > 60 * 24 * 30:
            raise HTTPException(422, detail="temporary_minutes must be between 1 and 43200")
        expires_at = datetime.now(UTC) + timedelta(minutes=minutes)
    existing = db.execute(select(UserRole).where(UserRole.user_id == user.id,
                                                 UserRole.role_id == role.id)).scalar_one_or_none()
    if existing:
        existing.expires_at = expires_at
    else:
        db.add(UserRole(user_id=user.id, role_id=role.id, expires_at=expires_at,
                        granted_by=principal.user_id))
    audit.record(db, action="rbac.role_assigned", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="user", resource_id=str(user_id),
                 detail={"role": role.name, "temporary_minutes": minutes})
    db.commit()
    return {"status": "assigned", "role": role.name,
            "expires_at": expires_at.isoformat() if expires_at else None}


@router.delete("/users/{user_id}/roles/{role_name}")
def revoke_role(user_id: uuid.UUID, role_name: str,
                principal: Principal = Depends(require_permission("rbac:manage")),
                db: Session = Depends(get_db)) -> dict:
    user = _user_in_tenant(db, principal, user_id)
    role = _role_in_tenant(db, principal, role_name)
    _check_grantable(db, principal, role.permissions or [])
    ur = db.execute(select(UserRole).where(UserRole.user_id == user.id,
                                           UserRole.role_id == role.id)).scalar_one_or_none()
    if ur:
        db.delete(ur)
        audit.record(db, action="rbac.role_revoked", actor_id=principal.user_id,
                     actor_label=principal.label, tenant_id=principal.tenant_id,
                     resource_type="user", resource_id=str(user_id), detail={"role": role_name})
    db.commit()
    return {"status": "revoked"}


@router.post("/users/{user_id}/mfa/reset")
def reset_user_mfa(user_id: uuid.UUID,
                   principal: Principal = Depends(require_permission("user:manage")),
                   db: Session = Depends(get_db)) -> dict:
    """Clear a user's second factor (lost device). Their sessions are revoked;
    if the tenant requires MFA they must enroll again at next sign-in. You
    cannot reset someone who holds permissions you lack, or yourself."""
    user = _user_in_tenant(db, principal, user_id)
    if user.id == principal.user_id:
        raise HTTPException(400, detail="Use My Account to manage your own MFA.")
    perms, _ = _user_permissions(db, user)
    _check_grantable(db, principal, perms)
    user.mfa_enabled, user.mfa_secret_enc, user.mfa_pending_secret_enc = False, None, None
    user.mfa_recovery_hashes, user.mfa_last_step, user.mfa_enrolled_at = [], None, None
    for sess in db.execute(select(SessionModel).where(
            SessionModel.user_id == user.id, SessionModel.revoked_at.is_(None))).scalars():
        sess.revoked_at, sess.revoked_reason = datetime.now(UTC), "mfa_reset"
    audit.record(db, action="rbac.user_mfa_reset", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.tenant_id,
                 resource_type="user", resource_id=str(user_id), detail={"email": user.email})
    db.commit()
    return {"status": "mfa_reset"}


def _user_permissions(db: Session, user: User) -> tuple[list[str], list[str]]:
    from ..auth.deps import _effective_permissions

    return _effective_permissions(db, user)


# --- The caller's tenant ------------------------------------------------------
tenants_router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

# Fields a customer may manage itself. Tier, SLA, status and hierarchy are
# contractual and managed by the provider via /api/v1/mssp/tenants.
_NON_DELEGABLE_ROLES = {"tenant_admin", "customer_admin", "platform_super_admin"}
@tenants_router.get("")
def list_accessible(principal: Principal = Depends(get_current_principal),
                    db: Session = Depends(get_db)) -> dict:
    """Tenants the caller can act in (home first) — drives the tenant switcher."""
    user = db.get(User, principal.user_id)
    return {"items": [d.to_dict() for d in accessible_tenants(db, user, principal.home_permissions)]}


@tenants_router.get("/current")
def current_tenant(principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> dict:
    from ..services.tiers import effective_sla, tenant_features

    t = _tenant(db, principal)
    data = serialize(t)
    data["effective_sla"] = effective_sla(t)
    data["features"] = sorted(tenant_features(t)) if t.kind == "customer" else ["*"]
    data["delegation"] = delegation_policy(t)
    data["acting_as"] = {"delegated_via": principal.delegated_via,
                         "home_tenant": principal.home_tenant_slug, "roles": principal.roles,
                         "mfa_verified": principal.mfa_verified}
    sec = (t.settings or {}).get("security") or {}
    data["security"] = {"require_mfa": bool(sec.get("require_mfa")),
                        "require_mfa_set_by": sec.get("require_mfa_set_by")}
    return data


@tenants_router.patch("/current")
def update_current_tenant(payload: dict = Body(...),
                          principal: Principal = Depends(require_permission("tenant:manage")),
                          db: Session = Depends(get_db)) -> dict:
    """Customer self-service: branding, escalation contacts and the delegation
    policy that controls provider access. Only the tenant's OWN users (not
    delegated provider staff) may change the delegation policy."""
    t = _tenant(db, principal)
    try:
        if "branding" in payload:
            t.branding = clean_branding(payload["branding"])
        if "contacts" in payload:
            t.contacts = clean_contacts(payload["contacts"])
    except TenantError as exc:
        raise HTTPException(422, detail={"error": exc.code, "message": exc.message})
    if "delegation" in payload:
        if principal.is_delegated:
            raise HTTPException(403, detail={
                "error": "customer_only", "message": "Only the customer can change provider access."})
        pol = payload["delegation"] or {}
        if not isinstance(pol, dict):
            raise HTTPException(422, detail="delegation must be an object")
        default_role = str(pol.get("default_provider_role", "soc_manager"))
        allowed = pol.get("allowed_roles") or []
        if not isinstance(allowed, list):
            raise HTTPException(422, detail="allowed_roles must be a list")
        allowed = [str(r) for r in allowed]
        existing = set(db.execute(select(Role.name).where(Role.tenant_id == t.id)).scalars())
        for r in [default_role, *allowed]:
            if r not in existing:
                raise HTTPException(422, detail=f"Unknown role '{r}'")
            if r in _NON_DELEGABLE_ROLES:
                raise HTTPException(422, detail=f"Role '{r}' cannot be delegated to provider staff")
        t.settings = {**(t.settings or {}), "delegation": {
            "allow_provider_access": bool(pol.get("allow_provider_access", True)),
            "default_provider_role": default_role,
            "allowed_roles": allowed,
        }}
    if "security" in payload:
        _apply_security_policy(t, payload["security"], principal, set_by="customer")
    audit.record(db, action="tenant.self_service_update", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=t.id, resource_type="tenant",
                 resource_id=str(t.id), detail={"fields": list(payload),
                                                 "security": payload.get("security")})
    db.commit()
    return serialize(t)


def _apply_security_policy(t: Tenant, pol, principal: Principal, *, set_by: str) -> None:
    """Tenant security policy (currently: require MFA for everyone acting in
    the tenant, including delegated provider staff).

    * Only the tenant's own users change it from the customer side.
    * Turning it on requires the caller's own session to be MFA-verified, so
      an administrator cannot lock everyone out, themselves included.
    * The provider may impose it, but may only lift a requirement it imposed
      itself; a customer's own requirement stays in force.
    """
    if not isinstance(pol, dict) or not isinstance(pol.get("require_mfa"), bool):
        raise HTTPException(422, detail="security must be an object like {\"require_mfa\": true}")
    if set_by == "customer" and principal.is_delegated:
        raise HTTPException(403, detail={"error": "customer_only",
                                         "message": "Only the customer's own administrators can change this."})
    current = dict((t.settings or {}).get("security") or {})
    want = pol["require_mfa"]
    if want and not principal.mfa_verified:
        raise HTTPException(409, detail={"error": "mfa_not_verified",
                                         "message": "Enable MFA on your own account (My Account) and sign "
                                                    "in with it before requiring it for the organization."})
    if not want and current.get("require_mfa") and set_by == "provider" \
            and current.get("require_mfa_set_by") == "customer":
        raise HTTPException(403, detail={"error": "customer_policy",
                                         "message": "The customer requires MFA; only the customer can lift it."})
    current["require_mfa"] = want
    current["require_mfa_set_by"] = set_by if want else None
    t.settings = {**(t.settings or {}), "security": current}
