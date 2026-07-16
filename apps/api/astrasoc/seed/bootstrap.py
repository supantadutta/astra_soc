"""Baseline seed: permissions, roles, tenant, users, and platform config.

This runs once (idempotently) on first startup so the platform is usable
immediately in DEMO mode with a full RBAC matrix, a simulated LLM provider,
registered agents and tools, mock connectors, starter detections, playbooks and
response policy. It does NOT create any live/production data.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.permissions import (
    BUILTIN_ROLES,
    PERMISSIONS,
    ROLE_DESCRIPTIONS,
)
from ..auth.security import hash_password
from ..models import (
    Agent,
    Connector,
    ModelDeployment,
    ModelProvider,
    ModelRoute,
    Permission,
    Playbook,
    PlaybookVersion,
    Role,
    SystemSetting,
    Tenant,
    Tool,
    User,
    UserRole,
)
from ..models.enums import ProviderKind
from .catalog import (
    AGENT_DEFS,
    CONNECTOR_DEFS,
    MODEL_DEPLOYMENTS,
    RESPONSE_POLICY,
    ROUTE_DEFS,
    TOOL_DEFS,
)

DEFAULT_TENANT_SLUG = "acme"
DEMO_PASSWORD = "Demo!Pass123"  # documented demo credential; not a real secret

# (email, full_name, role, is_service)
DEMO_USERS = [
    ("admin@astrasoc.io", "Ada Sysadmin", "platform_super_admin", False),
    ("manager@acme.io", "Morgan Chen (SOC Manager)", "soc_manager", False),
    ("commander@acme.io", "Ivy Commander", "incident_commander", False),
    ("t3@acme.io", "Theo Tier-3", "tier3_analyst", False),
    ("t2@acme.io", "Tara Tier-2", "tier2_analyst", False),
    ("t1@acme.io", "Sam Tier-1", "tier1_analyst", False),
    ("hunter@acme.io", "Nadia Hunter", "threat_hunter", False),
    ("deteng@acme.io", "Dev Detections", "detection_engineer", False),
    ("intel@acme.io", "Ravi Intel", "threat_intel_analyst", False),
    ("auditor@acme.io", "Olive Auditor", "auditor", False),
    ("exec@acme.io", "Blake Executive", "readonly_executive", False),
]


def _ensure_permissions(db: Session) -> None:
    existing = {p.key for p in db.execute(select(Permission)).scalars()}
    for key, desc in PERMISSIONS.items():
        if key not in existing:
            db.add(Permission(key=key, category=key.split(":", 1)[0], description=desc))


def _ensure_roles(db: Session, tenant_id) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for name, perms in BUILTIN_ROLES.items():
        role = db.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.name == name)
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                tenant_id=tenant_id, name=name, permissions=perms, is_builtin=True,
                description=ROLE_DESCRIPTIONS.get(name, ""),
            )
            db.add(role)
        else:
            role.permissions = perms  # keep in sync with code
        roles[name] = role
    db.flush()
    return roles


def _ensure_mode(db: Session) -> None:
    row = db.execute(
        select(SystemSetting).where(SystemSetting.tenant_id.is_(None),
                                    SystemSetting.key == "operating_mode")
    ).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(
            tenant_id=None, key="operating_mode",
            value={"mode": "DEMO", "ai_enabled": True, "llm_strategy": "simulated",
                   "changed_at": datetime.now(UTC).isoformat(),
                   "changed_by": "system", "degraded": False, "degraded_reasons": []},
            description="Authoritative operating mode (DEMO/LIVE).",
        ))
    # Response policy stored as a setting so it is inspectable/editable.
    pol = db.execute(
        select(SystemSetting).where(SystemSetting.tenant_id.is_(None),
                                    SystemSetting.key == "response_policy")
    ).scalar_one_or_none()
    if pol is None:
        db.add(SystemSetting(tenant_id=None, key="response_policy", value=RESPONSE_POLICY,
                             description="Policy-as-code rules for response actions."))


def _ensure_providers(db: Session, tenant_id) -> None:
    sim = db.execute(
        select(ModelProvider).where(ModelProvider.tenant_id == tenant_id,
                                    ModelProvider.kind == ProviderKind.SIMULATED.value)
    ).scalar_one_or_none()
    if sim is None:
        sim = ModelProvider(
            tenant_id=tenant_id, name="Built-in Simulated Reasoner",
            kind=ProviderKind.SIMULATED.value, enabled=True,
            data_classification_allowance="restricted", private_only=True,
            health="healthy", last_health_check=datetime.now(UTC),
            fallback_priority=1000,
        )
        db.add(sim)
        db.flush()
        for dep in MODEL_DEPLOYMENTS:
            db.add(ModelDeployment(provider_id=sim.id, **dep))
        db.flush()
    # Routes map capability aliases to the simulated deployments by default.
    deployments = {
        d.model_identifier: d
        for d in db.execute(select(ModelDeployment)).scalars()
    }
    for cap, model_id in ROUTE_DEFS.items():
        existing = db.execute(
            select(ModelRoute).where(ModelRoute.tenant_id == tenant_id,
                                     ModelRoute.capability == cap)
        ).scalar_one_or_none()
        if existing is None and model_id in deployments:
            db.add(ModelRoute(
                tenant_id=tenant_id, capability=cap,
                primary_deployment_id=deployments[model_id].id,
                require_verification=(cap in ("response_planner", "deep_investigator")),
            ))


def _ensure_agents(db: Session) -> None:
    existing = {a.key for a in db.execute(select(Agent)).scalars()}
    for defn in AGENT_DEFS:
        if defn["key"] not in existing:
            db.add(Agent(**defn))


def _ensure_tools(db: Session) -> None:
    existing = {t.key for t in db.execute(select(Tool)).scalars()}
    for defn in TOOL_DEFS:
        if defn["key"] not in existing:
            db.add(Tool(**defn))


def _ensure_connectors(db: Session, tenant_id) -> None:
    existing = {c.kind for c in db.execute(
        select(Connector).where(Connector.tenant_id == tenant_id)).scalars()}
    for defn in CONNECTOR_DEFS:
        if defn["kind"] not in existing:
            db.add(Connector(tenant_id=tenant_id, **defn))


def _ensure_playbooks(db: Session, tenant_id) -> None:
    from .playbooks import PLAYBOOK_DEFS

    existing = {p.key for p in db.execute(
        select(Playbook).where(Playbook.tenant_id == tenant_id)).scalars()}
    for defn in PLAYBOOK_DEFS:
        if defn["key"] in existing:
            continue
        pb = Playbook(
            tenant_id=tenant_id, key=defn["key"], name=defn["name"],
            description=defn["description"], enabled=defn.get("enabled", True),
            trigger=defn.get("trigger", {}), tags=defn.get("tags", []),
        )
        db.add(pb)
        db.flush()
        db.add(PlaybookVersion(
            playbook_id=pb.id, version="1.0.0", graph=defn["graph"], is_active=True,
            changelog="Initial version (seed).",
        ))


def ensure_seed(db: Session) -> Tenant:
    """Idempotently ensure baseline data exists. Returns the default tenant."""
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == DEFAULT_TENANT_SLUG)
    ).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            name="Acme Corporation", slug=DEFAULT_TENANT_SLUG,
            settings={"daily_token_budget": 2_000_000, "monthly_cost_limit_usd": 5000,
                      "private_model_only": False, "timezone": "UTC"},
        )
        db.add(tenant)
        db.flush()

    _ensure_permissions(db)
    roles = _ensure_roles(db, tenant.id)
    _ensure_mode(db)
    _ensure_providers(db, tenant.id)
    _ensure_agents(db)
    _ensure_tools(db)
    _ensure_connectors(db, tenant.id)
    _ensure_playbooks(db, tenant.id)

    # Users.
    for email, full_name, role_name, is_service in DEMO_USERS:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(
                tenant_id=tenant.id, email=email, full_name=full_name,
                password_hash=hash_password(DEMO_PASSWORD),
                is_service_account=is_service,
                attributes={"allowed_classifications": ["public", "internal", "confidential",
                                                          "restricted"]},
            )
            db.add(user)
            db.flush()
            role = roles.get(role_name)
            if role:
                db.add(UserRole(user_id=user.id, role_id=role.id))

    db.commit()
    return tenant
