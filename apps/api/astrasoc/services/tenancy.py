"""Tenant hierarchy and delegated (MSSP) access resolution.

A request normally runs in the caller's *home* tenant. Provider and reseller
staff can act inside a descendant customer tenant by sending
``X-Tenant-ID``; this module decides whether that is allowed and with which
permissions. Rules, evaluated in order:

1. ``platform:admin`` may enter any tenant. If the customer has switched
   provider access off, the entry is flagged as *break-glass* in the audit
   trail.
2. The target must be a descendant of the caller's home tenant, and the
   home tenant must be a provider or reseller.
3. The customer's delegation policy (``settings.delegation``) can refuse all
   provider access or restrict which roles providers may use.
4. ``mssp:all_customers`` grants the customer's configured default provider
   role (``soc_manager`` unless the customer chose otherwise).
5. Otherwise an unexpired, unrevoked :class:`TenantAccessGrant` must exist
   for this user and customer; its role is used.

The acting permissions are always the named role **as defined in the
customer tenant** — never the provider's own permissions — and never
include platform or provider-level permissions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.permissions import (
    PLATFORM_PERMISSIONS,
    PROVIDER_PERMISSIONS,
    WILDCARD,
    role_has_permission,
)
from ..models import Role, Tenant, TenantAccessGrant, User

PROVIDER_KINDS = ("provider", "reseller")


@dataclass
class AccessDecision:
    tenant: Tenant
    role_name: str
    permissions: list[str]
    via: str  # home | platform | break_glass | provider | grant
    grant_id: uuid.UUID | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        t = self.tenant
        return {
            "id": str(t.id), "name": t.name, "slug": t.slug, "kind": t.kind,
            "status": t.status, "service_tier": t.service_tier, "region": t.region,
            "role": self.role_name, "via": self.via,
            "branding": t.branding or {},
        }


class TenantAccessDenied(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def children_map(db: Session) -> dict[uuid.UUID | None, list[Tenant]]:
    out: dict[uuid.UUID | None, list[Tenant]] = {}
    for t in db.execute(select(Tenant)).scalars():
        out.setdefault(t.parent_id, []).append(t)
    return out


def descendant_ids(db: Session, root_id: uuid.UUID) -> set[uuid.UUID]:
    kids = children_map(db)
    out: set[uuid.UUID] = set()
    stack = [root_id]
    while stack:
        node = stack.pop()
        for child in kids.get(node, []):
            if child.id not in out:
                out.add(child.id)
                stack.append(child.id)
    return out


def is_descendant(db: Session, ancestor_id: uuid.UUID, tenant: Tenant) -> bool:
    seen: set[uuid.UUID] = set()
    cur = tenant
    while cur is not None and cur.parent_id is not None and cur.id not in seen:
        seen.add(cur.id)
        if cur.parent_id == ancestor_id:
            return True
        cur = db.get(Tenant, cur.parent_id)
    return False


def delegation_policy(tenant: Tenant) -> dict:
    pol = dict((tenant.settings or {}).get("delegation") or {})
    pol.setdefault("allow_provider_access", True)
    pol.setdefault("default_provider_role", "soc_manager")
    pol.setdefault("allowed_roles", [])  # empty = any role
    return pol


def _role_permissions(db: Session, tenant_id: uuid.UUID, role_name: str) -> list[str] | None:
    role = db.execute(select(Role).where(
        Role.tenant_id == tenant_id, Role.name == role_name)).scalar_one_or_none()
    if role is None:
        return None
    return sorted(p for p in (role.permissions or [])
                  if p not in PLATFORM_PERMISSIONS and p not in PROVIDER_PERMISSIONS
                  and p != WILDCARD)


def _active_grant(db: Session, user_id: uuid.UUID, tenant_id: uuid.UUID) -> TenantAccessGrant | None:
    now = datetime.now(UTC)
    grants = db.execute(select(TenantAccessGrant).where(
        TenantAccessGrant.user_id == user_id,
        TenantAccessGrant.customer_tenant_id == tenant_id,
        TenantAccessGrant.revoked_at.is_(None),
    ).order_by(TenantAccessGrant.created_at.desc())).scalars().all()
    for g in grants:
        if g.expires_at is None or g.expires_at > now:
            return g
    return None


def resolve_access(db: Session, user: User, home_permissions: list[str],
                   target: Tenant) -> AccessDecision:
    """Decide whether ``user`` may act inside ``target``. Raises
    :class:`TenantAccessDenied` with a human-readable reason otherwise."""
    home = db.get(Tenant, user.tenant_id)
    if home is None:
        raise TenantAccessDenied("Home tenant not found.")
    if target.id == home.id:
        return AccessDecision(target, "home", home_permissions, "home")
    if target.status == "offboarding":
        raise TenantAccessDenied("Tenant is being offboarded.")

    policy = delegation_policy(target)
    if role_has_permission(home_permissions, "platform:admin"):
        via = "platform" if policy["allow_provider_access"] else "break_glass"
        return AccessDecision(target, "platform_super_admin", [WILDCARD], via)

    if home.kind not in PROVIDER_KINDS or not is_descendant(db, home.id, target):
        raise TenantAccessDenied("Tenant is outside your managed portfolio.")
    if not policy["allow_provider_access"]:
        raise TenantAccessDenied("The customer has disabled provider access to this tenant.")
    if not target.is_active and not role_has_permission(home_permissions, "mssp:onboard"):
        raise TenantAccessDenied("Tenant is suspended.")

    grant = None
    if role_has_permission(home_permissions, "mssp:all_customers"):
        role_name, via = policy["default_provider_role"], "provider"
    else:
        grant = _active_grant(db, user.id, target.id)
        if grant is None:
            raise TenantAccessDenied("No active access grant for this customer.")
        role_name, via = grant.role_name, "grant"

    if policy["allowed_roles"] and role_name not in policy["allowed_roles"]:
        raise TenantAccessDenied(f"The customer does not allow provider role '{role_name}'.")
    perms = _role_permissions(db, target.id, role_name)
    if perms is None:
        raise TenantAccessDenied(f"Role '{role_name}' does not exist in the customer tenant.")
    return AccessDecision(target, role_name, perms, via, grant_id=grant.id if grant else None)


def accessible_tenants(db: Session, user: User, home_permissions: list[str]) -> list[AccessDecision]:
    """Every tenant the user can act in (home first), for tenant switchers and
    portfolio views."""
    home = db.get(Tenant, user.tenant_id)
    out: list[AccessDecision] = [AccessDecision(home, "home", home_permissions, "home")]
    if role_has_permission(home_permissions, "platform:admin"):
        candidates = [t for t in db.execute(select(Tenant).order_by(Tenant.name)).scalars()
                      if t.id != home.id]
    elif home.kind in PROVIDER_KINDS:
        ids = descendant_ids(db, home.id)
        candidates = [t for t in db.execute(select(Tenant).where(Tenant.id.in_(ids))
                                            .order_by(Tenant.name)).scalars()] if ids else []
    else:
        candidates = []
    for t in candidates:
        try:
            out.append(resolve_access(db, user, home_permissions, t))
        except TenantAccessDenied:
            continue
    return out


def portfolio_tenant_ids(db: Session, user: User, home_permissions: list[str]) -> list[uuid.UUID]:
    """Customer tenants (not providers) the user can see in portfolio views."""
    return [d.tenant.id for d in accessible_tenants(db, user, home_permissions)
            if d.tenant.kind == "customer"]
