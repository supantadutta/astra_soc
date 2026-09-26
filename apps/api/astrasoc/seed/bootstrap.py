"""Baseline seed: global registry, the root provider tenant, and (in demo /
development only) a realistic MSSP estate with demo accounts.

Production behaviour:
* creates the global permission catalogue, agent/tool registry and the
  platform default response policy;
* creates the root provider tenant (``ASTRASOC_PLATFORM_TENANT_*``);
* creates the first administrator from ``ASTRASOC_BOOTSTRAP_ADMIN_EMAIL`` /
  ``ASTRASOC_BOOTSTRAP_ADMIN_PASSWORD`` when the database has no users;
* never creates demo accounts or demo data unless explicitly enabled.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.permissions import PERMISSIONS
from ..config import settings
from ..models import (
    Agent,
    Permission,
    SystemSetting,
    Tenant,
    TenantAccessGrant,
    Tool,
    User,
    UserRole,
)
from ..services.tenants import create_user, ensure_roles, ensure_tenant_baseline, provision_tenant
from .catalog import AGENT_DEFS, RESPONSE_POLICY, TOOL_DEFS

logger = logging.getLogger("astrasoc.bootstrap")

DEFAULT_TENANT_SLUG = "acme"
DEMO_PASSWORD = "Demo!Pass123"  # documented demo credential; never created in production

# --- Demo MSSP estate ---------------------------------------------------------
# (slug, name, kind, parent_slug, tier, region, scenarios)
DEMO_TENANTS = [
    ("northwind", "Northwind Security (Reseller)", "reseller", None, "enterprise", "eu", 0),
    ("acme", "Acme Corporation", "customer", None, "enterprise", "us", 15),
    ("globex", "Globex Manufacturing", "customer", None, "professional", "eu", 6),
    ("initech", "Initech Financial", "customer", None, "essentials", "us", 4),
    ("contoso", "Contoso Retail", "customer", "northwind", "professional", "eu", 4),
]

# (email, full_name, tenant_slug, role)  — tenant_slug None = root provider
DEMO_USERS = [
    ("admin@astrasoc.io", "Ada Sysadmin (Platform)", None, "platform_super_admin"),
    ("soc@astrasoc.io", "Sam Okoro (MSSP SOC Manager)", None, "mssp_soc_manager"),
    ("analyst@astrasoc.io", "Lee Park (MSSP Analyst)", None, "mssp_analyst"),
    ("accounts@astrasoc.io", "Priya Shah (Account Manager)", None, "mssp_account_manager"),
    ("ops@northwind.io", "Nora West (Reseller Admin)", "northwind", "provider_admin"),
    # Acme runs a co-managed SOC: its own analysts work alongside the MSSP.
    ("manager@acme.io", "Morgan Chen (SOC Manager)", "acme", "soc_manager"),
    ("commander@acme.io", "Ivy Commander", "acme", "incident_commander"),
    ("t3@acme.io", "Theo Tier-3", "acme", "tier3_analyst"),
    ("t2@acme.io", "Tara Tier-2", "acme", "tier2_analyst"),
    ("t1@acme.io", "Sam Tier-1", "acme", "tier1_analyst"),
    ("hunter@acme.io", "Nadia Hunter", "acme", "threat_hunter"),
    ("deteng@acme.io", "Dev Detections", "acme", "detection_engineer"),
    ("intel@acme.io", "Ravi Intel", "acme", "threat_intel_analyst"),
    ("auditor@acme.io", "Olive Auditor", "acme", "auditor"),
    ("exec@acme.io", "Blake Executive", "acme", "readonly_executive"),
    ("ciso@acme.io", "Casey Ito (Acme CISO)", "acme", "customer_admin"),
    ("approver@acme.io", "Jordan Blake (Acme IT Ops)", "acme", "customer_approver"),
    ("admin@globex.io", "Greta Olsen (Globex Admin)", "globex", "customer_admin"),
    ("viewer@initech.io", "Ian Tech (Initech Viewer)", "initech", "customer_viewer"),
    ("admin@contoso.io", "Carla Diaz (Contoso Admin)", "contoso", "customer_admin"),
]

# MSSP analyst works only the customers explicitly granted to them.
DEMO_GRANTS = [
    ("analyst@astrasoc.io", "acme", "tier2_analyst"),
    ("analyst@astrasoc.io", "globex", "tier2_analyst"),
]


def _ensure_global_registry(db: Session) -> None:
    existing = {p.key for p in db.execute(select(Permission)).scalars()}
    for key, desc in PERMISSIONS.items():
        if key not in existing:
            db.add(Permission(key=key, category=key.split(":", 1)[0], description=desc))

    agents = {a.key for a in db.execute(select(Agent)).scalars()}
    for defn in AGENT_DEFS:
        if defn["key"] not in agents:
            db.add(Agent(**defn))
    tools = {t.key for t in db.execute(select(Tool)).scalars()}
    for defn in TOOL_DEFS:
        if defn["key"] not in tools:
            db.add(Tool(**defn))

    def _setting(key: str, value: dict, desc: str) -> None:
        row = db.execute(select(SystemSetting).where(
            SystemSetting.tenant_id.is_(None), SystemSetting.key == key)).scalar_one_or_none()
        if row is None:
            db.add(SystemSetting(tenant_id=None, key=key, value=value, description=desc))

    _setting("operating_mode",
             {"mode": settings.default_mode, "ai_enabled": True, "llm_strategy": "simulated",
              "changed_at": datetime.now(UTC).isoformat(), "changed_by": "system",
              "degraded": False, "degraded_reasons": []},
             "Platform default operating mode for tenants that never switched.")
    _setting("response_policy", RESPONSE_POLICY,
             "Platform default policy-as-code for response actions (tenants may override).")
    db.flush()


def _ensure_root(db: Session) -> Tenant:
    root = db.execute(select(Tenant).where(Tenant.parent_id.is_(None), Tenant.kind == "provider")
                      .order_by(Tenant.created_at)).scalars().first()
    if root is None:
        root = db.execute(select(Tenant).where(
            Tenant.slug == settings.platform_tenant_slug)).scalar_one_or_none()
        if root is not None:
            root.kind = "provider"
    if root is None:
        root = provision_tenant(db, name=settings.platform_tenant_name,
                                slug=settings.platform_tenant_slug, kind="provider",
                                tier="enterprise", platform_root=True,
                                branding={"display_name": settings.platform_tenant_name})
    else:
        ensure_tenant_baseline(db, root, platform_root=True)
    return root


def _ensure_bootstrap_admin(db: Session, root: Tenant) -> None:
    if db.execute(select(func.count()).select_from(User)).scalar():
        return
    email, password = settings.bootstrap_admin_email, settings.bootstrap_admin_password
    if not email or not password:
        logger.warning("No users exist and ASTRASOC_BOOTSTRAP_ADMIN_EMAIL/PASSWORD are unset — "
                       "nobody can log in until an administrator is bootstrapped.")
        return
    create_user(db, root, email=email, full_name="Platform Administrator",
                password=password, roles=["platform_super_admin"])
    logger.info("Bootstrapped platform administrator %s", email)


def _ensure_demo_estate(db: Session, root: Tenant) -> None:
    by_slug = {t.slug: t for t in db.execute(select(Tenant)).scalars()}
    now = datetime.now(UTC)
    for slug, name, kind, parent_slug, tier, region, _ in DEMO_TENANTS:
        parent = by_slug.get(parent_slug) if parent_slug else root
        t = by_slug.get(slug)
        if t is None:
            t = provision_tenant(
                db, name=name, slug=slug, kind=kind, parent_id=parent.id, tier=tier, region=region,
                contract_start=now - timedelta(days=200), contract_end=now + timedelta(days=530),
                contacts=[
                    {"name": f"{name} SOC hotline", "email": f"soc@{slug}.example",
                     "phone": "+1-555-0100", "role": "security_contact", "level": 1,
                     "notify_on": ["critical", "sla_breach"]},
                    {"name": f"{name} CISO", "email": f"ciso@{slug}.example",
                     "phone": "+1-555-0199", "role": "executive", "level": 2,
                     "notify_on": ["sla_breach"]},
                ],
                branding={"display_name": name, "primary_color": "#22d3ee"},
                settings={"delegation": {"allow_provider_access": True},
                          "customer_approval_actions":
                              ["disable_account"] if slug == "acme" else []},
            )
            by_slug[slug] = t
        else:
            # Upgrade path for databases created before the MSSP hierarchy.
            if t.parent_id is None and t.id != root.id:
                t.parent_id = parent.id
            if t.kind != kind:
                t.kind = kind
            ensure_tenant_baseline(db, t)

    for email, full_name, slug, role in DEMO_USERS:
        tenant = root if slug is None else by_slug[slug]
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            create_user(db, tenant, email=email, full_name=full_name, password=DEMO_PASSWORD,
                        roles=[role], attributes={"allowed_classifications":
                                                  ["public", "internal", "confidential", "restricted"]})
        elif user.tenant_id != tenant.id:
            # Legacy DB: move the account into its new tenant with the right role.
            user.tenant_id = tenant.id
            db.query(UserRole).filter(UserRole.user_id == user.id).delete()
            role_row = ensure_roles(db, tenant, platform_root=tenant.id == root.id)[role]
            db.add(UserRole(user_id=user.id, role_id=role_row.id))

    for email, slug, role in DEMO_GRANTS:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        cust = by_slug[slug]
        exists = db.execute(select(TenantAccessGrant).where(
            TenantAccessGrant.user_id == user.id,
            TenantAccessGrant.customer_tenant_id == cust.id)).first()
        if not exists:
            db.add(TenantAccessGrant(provider_tenant_id=root.id, customer_tenant_id=cust.id,
                                     user_id=user.id, role_name=role,
                                     reason="Demo: assigned analyst for this customer"))
    db.flush()


def ensure_seed(db: Session) -> Tenant:
    """Idempotently ensure baseline data exists. Returns the default demo
    customer tenant when demo seeding is on, otherwise the root provider."""
    _ensure_global_registry(db)
    root = _ensure_root(db)
    if settings.should_seed_demo_users:
        _ensure_demo_estate(db, root)
    else:
        _ensure_bootstrap_admin(db, root)
    db.commit()
    acme = db.execute(select(Tenant).where(Tenant.slug == DEFAULT_TENANT_SLUG)).scalar_one_or_none()
    return acme or root


def demo_customer_scenarios() -> dict[str, int]:
    """slug -> number of seeded scenarios for the demo estate."""
    return {slug: n for slug, _, kind, _, _, _, n in DEMO_TENANTS if kind == "customer"}
