"""Tenant lifecycle: provisioning, user creation, export and purge.

Provisioning gives every tenant a complete, isolated baseline: a role
catalogue appropriate to its kind, the built-in simulated LLM provider and
capability routes, the connector catalogue (mock, disabled), starter
playbooks and deployed detection content. Nothing is shared between tenants
except the global agent/tool registry and the platform default policy.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth.permissions import ROLE_DESCRIPTIONS, roles_for_tenant_kind
from ..auth.security import hash_password, is_valid_email, normalize_email, password_policy_errors
from ..models import (
    Agent,
    AgentRun,
    Alert,
    AnalystFeedback,
    APIKey,
    ApprovalRequest,
    Connector,
    ConnectorCredentialReference,
    ConnectorHealth,
    DetectionRule,
    Entity,
    EntityRelationship,
    EvaluationDataset,
    EvaluationRun,
    Evidence,
    Hypothesis,
    Incident,
    IncidentAlert,
    KnowledgeChunk,
    KnowledgeDocument,
    ModelDeployment,
    ModelProvider,
    ModelRoute,
    Notification,
    Playbook,
    PlaybookVersion,
    PolicyDecision,
    PromptTemplate,
    Report,
    ResponseAction,
    Role,
    SecurityEvent,
    ShiftHandover,
    SystemSetting,
    Tenant,
    TenantAccessGrant,
    ThreatIndicator,
    TimelineEntry,
    ToolExecution,
    UsageCounter,
    User,
    UserRole,
    WorkflowRun,
)
from ..models import Session as SessionModel
from ..models.enums import ProviderKind
from ..schemas.common import serialize_many
from ..seed.catalog import CONNECTOR_DEFS, DETECTION_DEFS, MODEL_DEPLOYMENTS, ROUTE_DEFS
from .tiers import TIERS

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
KINDS = ("provider", "reseller", "customer")
STATUSES = ("onboarding", "active", "suspended", "offboarding")


class TenantError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# --- Baseline ---------------------------------------------------------------
def ensure_roles(db: Session, tenant: Tenant, *, platform_root: bool = False) -> dict[str, Role]:
    catalogue = roles_for_tenant_kind(tenant.kind, platform_root=platform_root)
    roles: dict[str, Role] = {}
    for name, perms in catalogue.items():
        role = db.execute(select(Role).where(
            Role.tenant_id == tenant.id, Role.name == name)).scalar_one_or_none()
        if role is None:
            role = Role(tenant_id=tenant.id, name=name, permissions=perms, is_builtin=True,
                        description=ROLE_DESCRIPTIONS.get(name, ""))
            db.add(role)
        elif role.is_builtin:
            role.permissions = perms  # keep built-ins in sync with code
        roles[name] = role
    db.flush()
    return roles


def ensure_providers(db: Session, tenant_id: uuid.UUID) -> None:
    sim = db.execute(select(ModelProvider).where(
        ModelProvider.tenant_id == tenant_id,
        ModelProvider.kind == ProviderKind.SIMULATED.value)).scalar_one_or_none()
    if sim is None:
        sim = ModelProvider(
            tenant_id=tenant_id, name="Built-in Simulated Reasoner",
            kind=ProviderKind.SIMULATED.value, enabled=True,
            data_classification_allowance="restricted", private_only=True,
            health="healthy", last_health_check=datetime.now(UTC), fallback_priority=1000,
        )
        db.add(sim)
        db.flush()
        for dep in MODEL_DEPLOYMENTS:
            db.add(ModelDeployment(provider_id=sim.id, **dep))
        db.flush()
    # Routes point only at THIS tenant's deployments.
    deployments = {d.model_identifier: d for d in db.execute(
        select(ModelDeployment).where(ModelDeployment.provider_id == sim.id)).scalars()}
    for cap, model_id in ROUTE_DEFS.items():
        exists = db.execute(select(ModelRoute).where(
            ModelRoute.tenant_id == tenant_id, ModelRoute.capability == cap)).scalar_one_or_none()
        if exists is None and model_id in deployments:
            db.add(ModelRoute(tenant_id=tenant_id, capability=cap,
                              primary_deployment_id=deployments[model_id].id,
                              require_verification=cap in ("response_planner", "deep_investigator")))


def ensure_connectors(db: Session, tenant_id: uuid.UUID) -> None:
    existing = {c.kind for c in db.execute(
        select(Connector).where(Connector.tenant_id == tenant_id)).scalars()}
    for defn in CONNECTOR_DEFS:
        if defn["kind"] not in existing:
            db.add(Connector(tenant_id=tenant_id, **defn))


def ensure_playbooks(db: Session, tenant_id: uuid.UUID) -> None:
    from ..seed.playbooks import PLAYBOOK_DEFS

    existing = {p.key for p in db.execute(
        select(Playbook).where(Playbook.tenant_id == tenant_id)).scalars()}
    for defn in PLAYBOOK_DEFS:
        if defn["key"] in existing:
            continue
        pb = Playbook(tenant_id=tenant_id, key=defn["key"], name=defn["name"],
                      description=defn["description"], enabled=defn.get("enabled", True),
                      trigger=defn.get("trigger", {}), tags=defn.get("tags", []))
        db.add(pb)
        db.flush()
        db.add(PlaybookVersion(playbook_id=pb.id, version="1.0.0", graph=defn["graph"],
                               is_active=True, changelog="Initial version (seed)."))


def ensure_detections(db: Session, tenant_id: uuid.UUID) -> None:
    existing = {r.key for r in db.execute(
        select(DetectionRule).where(DetectionRule.tenant_id == tenant_id)).scalars()}
    for defn in DETECTION_DEFS:
        if defn["key"] not in existing:
            db.add(DetectionRule(tenant_id=tenant_id, **defn,
                                 version_history=[{"version": "1.0.0", "note": "starter content"}]))


def ensure_tenant_baseline(db: Session, tenant: Tenant, *, platform_root: bool = False) -> dict[str, Role]:
    roles = ensure_roles(db, tenant, platform_root=platform_root)
    ensure_providers(db, tenant.id)
    ensure_connectors(db, tenant.id)
    ensure_playbooks(db, tenant.id)
    ensure_detections(db, tenant.id)
    db.flush()
    return roles


# --- Provisioning -------------------------------------------------------------
def provision_tenant(
    db: Session, *, name: str, slug: str, kind: str = "customer",
    parent_id: uuid.UUID | None = None, tier: str = "professional", region: str = "global",
    sla_policy: dict | None = None, contacts: list | None = None, branding: dict | None = None,
    settings: dict | None = None, status: str = "active", platform_root: bool = False,
    contract_start: datetime | None = None, contract_end: datetime | None = None,
) -> Tenant:
    slug = (slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise TenantError("invalid_slug", "Slug must be 2-63 chars: lowercase letters, digits, '-'.")
    if kind not in KINDS:
        raise TenantError("invalid_kind", f"kind must be one of {KINDS}.")
    if tier not in TIERS:
        raise TenantError("invalid_tier", f"service_tier must be one of {sorted(TIERS)}.")
    if status not in STATUSES:
        raise TenantError("invalid_status", f"status must be one of {STATUSES}.")
    if db.execute(select(Tenant).where((Tenant.slug == slug) | (Tenant.name == name))).first():
        raise TenantError("conflict", "A tenant with that name or slug already exists.")
    if parent_id is not None:
        parent = db.get(Tenant, parent_id)
        if parent is None or parent.kind not in ("provider", "reseller"):
            raise TenantError("invalid_parent", "Parent must be a provider or reseller tenant.")
        if kind == "provider":
            raise TenantError("invalid_kind", "Only the root tenant may be a provider; use 'reseller'.")

    tenant = Tenant(
        name=name.strip(), slug=slug, kind=kind, parent_id=parent_id, service_tier=tier,
        region=region or "global", sla_policy=clean_sla_policy(sla_policy),
        contacts=clean_contacts(contacts), branding=clean_branding(branding),
        settings=settings or {}, status=status,
        is_active=status in ("active", "onboarding"),
        contract_start=contract_start, contract_end=contract_end,
    )
    db.add(tenant)
    db.flush()
    ensure_tenant_baseline(db, tenant, platform_root=platform_root)
    return tenant


def create_user(db: Session, tenant: Tenant, *, email: str, full_name: str, password: str,
                roles: list[str], enforce_policy: bool = True, attributes: dict | None = None) -> User:
    email = normalize_email(email)
    if not is_valid_email(email):
        raise TenantError("invalid_email", "A valid email is required.")
    if db.execute(select(User).where(User.email == email)).first():
        raise TenantError("conflict", "A user with that email already exists.")
    if enforce_policy:
        problems = password_policy_errors(password)
        if problems:
            raise TenantError("weak_password", "Password " + "; ".join(problems))
    user = User(tenant_id=tenant.id, email=email, full_name=full_name or email,
                password_hash=hash_password(password), password_changed_at=datetime.now(UTC),
                attributes=attributes or {"allowed_classifications":
                                          ["public", "internal", "confidential"]})
    db.add(user)
    db.flush()
    for role_name in roles:
        role = db.execute(select(Role).where(
            Role.tenant_id == tenant.id, Role.name == role_name)).scalar_one_or_none()
        if role is None:
            raise TenantError("unknown_role", f"Role '{role_name}' does not exist in this tenant.")
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    return user


# --- Offboarding -------------------------------------------------------------
# Tables exported/purged by tenant_id, children first.
_TENANT_TABLES = [
    ToolExecution, AgentRun, PolicyDecision, ApprovalRequest, ResponseAction, WorkflowRun,
    Report, Notification, AnalystFeedback, EvaluationRun, EvaluationDataset,
    KnowledgeChunk, KnowledgeDocument, TimelineEntry, Hypothesis, Evidence,
    EntityRelationship, Alert, Incident, Entity, SecurityEvent, ThreatIndicator,
    DetectionRule, ModelRoute, PromptTemplate, UsageCounter, APIKey, SystemSetting,
]
_EXPORT_EXCLUDE = {APIKey: {"key_hash"}, User: {"password_hash"}}  # plus SENSITIVE_COLUMNS, always


def export_tenant(db: Session, tenant: Tenant) -> dict:
    """A complete JSON export of a tenant's operational data (offboarding /
    data-portability). Credentials and secret material are never included."""
    bundle: dict = {
        "format": "astrasoc-tenant-export/1",
        "exported_at": datetime.now(UTC).isoformat(),
        "tenant": serialize_many([tenant])[0],
        "users": serialize_many(db.execute(select(User).where(
            User.tenant_id == tenant.id)).scalars().all(), _EXPORT_EXCLUDE[User]),
        "tables": {},
    }
    for model in _TENANT_TABLES + [Connector, ModelProvider, Playbook, Role]:
        rows = db.execute(select(model).where(model.tenant_id == tenant.id)).scalars().all()
        bundle["tables"][model.__tablename__] = serialize_many(rows, _EXPORT_EXCLUDE.get(model))
    from ..models import AuditEvent

    bundle["tables"]["audit_events"] = serialize_many(db.execute(select(AuditEvent).where(
        AuditEvent.tenant_id == tenant.id).order_by(AuditEvent.created_at)).scalars().all())
    return bundle


def purge_tenant(db: Session, tenant: Tenant) -> dict:
    """Irreversibly delete a tenant and all of its data. The audit trail is
    retained (tenant_id kept for compliance) — see docs/MSSP.md."""
    if db.execute(select(Tenant).where(Tenant.parent_id == tenant.id)).first():
        raise TenantError("has_children", "Offboard or re-parent child tenants first.")
    tid = tenant.id
    counts: dict[str, int] = {}

    inc_ids = select(Incident.id).where(Incident.tenant_id == tid)
    db.execute(delete(IncidentAlert).where(IncidentAlert.incident_id.in_(inc_ids)))
    pb_ids = select(Playbook.id).where(Playbook.tenant_id == tid)
    db.execute(delete(PlaybookVersion).where(PlaybookVersion.playbook_id.in_(pb_ids)))
    conn_ids = select(Connector.id).where(Connector.tenant_id == tid)
    db.execute(delete(ConnectorHealth).where(ConnectorHealth.connector_id.in_(conn_ids)))
    db.execute(delete(ConnectorCredentialReference).where(
        ConnectorCredentialReference.connector_id.in_(conn_ids)))
    prov_ids = select(ModelProvider.id).where(ModelProvider.tenant_id == tid)
    db.execute(delete(ModelDeployment).where(ModelDeployment.provider_id.in_(prov_ids)))
    user_ids = select(User.id).where(User.tenant_id == tid)
    db.execute(delete(SessionModel).where(SessionModel.user_id.in_(user_ids)))
    db.execute(delete(UserRole).where(UserRole.user_id.in_(user_ids)))
    db.execute(delete(TenantAccessGrant).where(
        (TenantAccessGrant.customer_tenant_id == tid) | (TenantAccessGrant.provider_tenant_id == tid)
        | TenantAccessGrant.user_id.in_(user_ids)))
    db.execute(delete(ShiftHandover).where(ShiftHandover.provider_tenant_id == tid))

    for model in _TENANT_TABLES + [Connector, ModelProvider, Playbook]:
        res = db.execute(delete(model).where(model.tenant_id == tid))
        counts[model.__tablename__] = res.rowcount or 0
    db.execute(delete(User).where(User.tenant_id == tid))
    db.execute(delete(Role).where(Role.tenant_id == tid))
    db.delete(tenant)
    db.flush()
    return counts


def global_registry_ready(db: Session) -> bool:
    return db.execute(select(Agent).limit(1)).first() is not None


# --- Self-service profile fields (validated; shown in reports and escalations) ---
_BRANDING_KEYS = {"display_name": 120, "primary_color": 7, "logo_url": 500, "report_footer": 500}


def clean_branding(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TenantError("invalid", "branding must be an object")
    out = {}
    for k, v in value.items():
        if v in (None, ""):
            continue
        if k not in _BRANDING_KEYS or not isinstance(v, str) or len(v) > _BRANDING_KEYS[k]:
            raise TenantError("invalid", f"Invalid branding field '{k}'")
        if k == "primary_color" and not re.fullmatch(r"#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}", v):
            raise TenantError("invalid", "primary_color must be a hex color like #0ea5e9")
        if k == "logo_url" and not v.startswith("https://"):
            raise TenantError("invalid", "logo_url must be an https:// URL")
        out[k] = v
    return out


def clean_contacts(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 25:
        raise TenantError("invalid", "contacts must be a list of at most 25 entries")
    out = []
    for c in value:
        if not isinstance(c, dict) or not is_valid_email(str(c.get("email", ""))):
            raise TenantError("invalid", "Each contact needs a valid email")
        out.append({k: str(c[k])[:200] for k in ("role", "email", "phone", "name") if c.get(k)})
    return out


_SEVERITIES = ("critical", "high", "medium", "low", "info")


def clean_sla_policy(value) -> dict:
    """Per-severity SLA overrides in minutes: {"critical": {"ack": 15, "resolve": 240}}."""
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise TenantError("invalid", "sla_policy must be an object")
    out: dict = {}
    for sev, targets in value.items():
        if sev not in _SEVERITIES or not isinstance(targets, dict):
            raise TenantError("invalid", f"Invalid SLA severity '{sev}'")
        clean = {}
        for k, v in targets.items():
            if k not in ("ack", "resolve"):
                raise TenantError("invalid", f"Invalid SLA target '{k}'")
            try:
                minutes = int(v)
            except (TypeError, ValueError):
                raise TenantError("invalid", "SLA targets must be whole minutes") from None
            if not 1 <= minutes <= 60 * 24 * 90:
                raise TenantError("invalid", "SLA targets must be between 1 minute and 90 days")
            clean[k] = minutes
        if clean:
            out[sev] = clean
    return out

