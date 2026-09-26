"""Permission catalogue and built-in role definitions.

Permissions are simple ``resource:verb`` strings. The wildcard ``*`` grants
everything (platform super admin only). Authorization is always evaluated on
the server — the frontend merely hides controls the user cannot use, and every
protected API route re-checks.
"""
from __future__ import annotations

# --- Permission catalogue -------------------------------------------------
PERMISSIONS: dict[str, str] = {
    # Cases & signals
    "alert:read": "View alerts",
    "alert:write": "Acknowledge / triage / escalate alerts",
    "incident:read": "View incidents",
    "incident:write": "Create and modify incidents",
    "incident:assign": "Assign incident ownership",
    "evidence:read": "View evidence",
    "evidence:write": "Add analyst conclusions / assumptions / notes",
    "evidence:attest": "Attest a CONFIRMED_FACT with a verifiable source reference",
    "entity:read": "View entities and graph",
    # Investigation / AI
    "agent:read": "View agents and runs",
    "agent:run": "Start agent workflows",
    "agent:manage": "Enable/disable and configure agents",
    "model:read": "View model providers and routing",
    "model:manage": "Configure providers, routes and budgets",
    "tool:read": "Use read-only investigation tools",
    "query:run": "Execute read-only queries",
    "knowledge:read": "Read knowledge base",
    "knowledge:write": "Curate knowledge base",
    # Detection
    "detection:read": "View detection rules",
    "detection:write": "Author detection rules",
    "detection:approve": "Approve/deploy detection rules",
    "threatintel:read": "View threat intelligence",
    "threatintel:write": "Manage threat indicators",
    # Response / governance
    "playbook:read": "View playbooks",
    "playbook:write": "Author playbooks",
    "playbook:run": "Start and advance playbook workflow runs",
    "action:request": "Request response actions",
    "action:execute": "Execute approved response actions",
    "approval:read": "View approvals",
    "approval:decide": "Approve/reject response actions",
    "policy:read": "View policy decisions",
    "policy:manage": "Manage response/authorization policy",
    # Reporting / feedback / eval
    "report:read": "View reports",
    "report:generate": "Generate and export reports",
    "feedback:write": "Submit analyst feedback",
    "evaluation:manage": "Manage learning/evaluation pipeline",
    # Integrations
    "connector:read": "View connectors",
    "connector:manage": "Configure connectors and test connections",
    "event:ingest": "Push security events into the ingestion pipeline",
    # Platform administration
    "audit:read": "Read audit logs",
    "rbac:manage": "Manage roles and assignments",
    "user:manage": "Manage users and API keys",
    "tenant:manage": "Manage the caller's own tenant settings",
    "platform:admin": "Cross-tenant platform administration (tenants, global agents/tools)",
    "settings:manage": "Manage system settings",
    "mode:manage": "Switch demo/live operating mode",
    "demo:manage": "Control demo scenarios and reseed",
    "health:read": "View platform health and observability",
    "notification:read": "Read own / tenant notifications",
    # MSSP (only effective in provider / reseller tenants)
    "mssp:portfolio": "View the customer portfolio, unified queue and SLA dashboards",
    "mssp:all_customers": "Delegated access to every descendant customer tenant",
    "mssp:onboard": "Onboard, update, suspend and offboard customer tenants",
    "mssp:grants": "Grant / revoke provider staff access to customer tenants",
    "mssp:billing": "View usage metering and billing exports",
    "mssp:content": "Distribute managed detection content to customers",
    "mssp:handover": "Write and acknowledge SOC shift handovers",
}

WILDCARD = "*"

# --- Built-in roles -------------------------------------------------------
# Each maps to a permission list. These are seeded per tenant plus a set of
# global templates.
READ_ANALYST = [
    "notification:read", "alert:read", "incident:read", "evidence:read", "entity:read", "agent:read",
    "model:read", "tool:read", "query:run", "knowledge:read", "detection:read",
    "threatintel:read", "playbook:read", "approval:read", "policy:read",
    "report:read", "connector:read", "health:read",
]

TIER1 = READ_ANALYST + ["alert:write", "incident:write", "feedback:write", "agent:run"]

TIER2 = TIER1 + [
    "evidence:write", "incident:assign", "action:request", "report:generate",
    "threatintel:write", "knowledge:write", "playbook:run",
]

TIER3 = TIER2 + ["detection:write", "playbook:write", "action:execute", "evidence:attest"]

# Permissions that act across tenants. Only platform administrators hold them.
PLATFORM_PERMISSIONS = {"platform:admin"}
# Provider-level permissions: meaningful only in provider / reseller tenants.
PROVIDER_PERMISSIONS = {p for p in PERMISSIONS if p.startswith("mssp:")}

BUILTIN_ROLES: dict[str, list[str]] = {
    "platform_super_admin": [WILDCARD],
    "tenant_admin": [p for p in PERMISSIONS
                     if p not in PLATFORM_PERMISSIONS and p not in PROVIDER_PERMISSIONS],
    "soc_manager": TIER3 + [
        "approval:decide", "detection:approve", "policy:read", "rbac:manage",
        "demo:manage", "evaluation:manage", "connector:manage", "mode:manage",
    ],
    "incident_commander": TIER3 + ["approval:decide", "demo:manage"],
    "tier3_analyst": TIER3,
    "tier2_analyst": TIER2,
    "tier1_analyst": TIER1,
    "threat_hunter": TIER2 + ["detection:write", "query:run"],
    "detection_engineer": READ_ANALYST + [
        "detection:write", "detection:approve", "query:run", "feedback:write",
    ],
    "threat_intel_analyst": READ_ANALYST + ["threatintel:write", "knowledge:write"],
    "auditor": [
        "notification:read", "audit:read", "incident:read", "alert:read", "evidence:read",
        "policy:read", "approval:read", "report:read", "health:read",
        "connector:read", "model:read", "detection:read",
    ],
    "readonly_executive": [
        "notification:read", "incident:read", "report:read", "report:generate", "health:read",
    ],
    "integration_service_account": [
        "alert:read", "alert:write", "incident:read", "incident:write",
        "connector:read", "query:run", "event:ingest",
    ],
    "automation_service_account": [
        "incident:read", "agent:run", "action:request", "playbook:read", "playbook:run",
        "query:run", "report:generate",
    ],
}

# --- MSSP provider roles (seeded in provider / reseller tenants) ------------
PROVIDER_ROLES: dict[str, list[str]] = {
    "provider_admin": sorted(set(BUILTIN_ROLES["tenant_admin"]) | PROVIDER_PERMISSIONS),
    "mssp_soc_manager": sorted(set(BUILTIN_ROLES["soc_manager"]) | PROVIDER_PERMISSIONS),
    "mssp_analyst": sorted(set(TIER2) | {"mssp:portfolio", "mssp:handover"}),
    "mssp_account_manager": [
        "notification:read", "incident:read", "report:read", "report:generate",
        "health:read", "connector:read", "mssp:portfolio", "mssp:onboard", "mssp:billing",
    ],
}

# --- Customer-portal roles (seeded in customer tenants) --------------------
CUSTOMER_VIEWER = [
    "notification:read", "incident:read", "alert:read", "evidence:read", "entity:read",
    "report:read", "approval:read", "health:read", "policy:read", "detection:read",
]
CUSTOMER_ROLES: dict[str, list[str]] = {
    "customer_viewer": CUSTOMER_VIEWER,
    "customer_approver": CUSTOMER_VIEWER + ["approval:decide", "feedback:write"],
    "customer_admin": CUSTOMER_VIEWER + [
        "approval:decide", "feedback:write", "report:generate", "connector:read",
        "audit:read", "user:manage", "rbac:manage", "tenant:manage",
    ],
}

ROLE_DESCRIPTIONS = {
    "platform_super_admin": "Full platform control across all tenants.",
    "tenant_admin": "Administers a single tenant.",
    "soc_manager": "Runs the SOC: approvals, detection sign-off, RBAC, mode.",
    "incident_commander": "Leads incident response; can approve actions.",
    "tier3_analyst": "Senior analyst; can execute approved actions and write detections.",
    "tier2_analyst": "Investigates and requests response actions.",
    "tier1_analyst": "Triage and first response.",
    "threat_hunter": "Proactive hunting and detection authoring.",
    "detection_engineer": "Authors and approves detection content.",
    "threat_intel_analyst": "Manages threat intelligence and knowledge.",
    "auditor": "Read-only oversight and audit access.",
    "readonly_executive": "Executive dashboards and reports only.",
    "integration_service_account": "Machine identity for ingestion connectors.",
    "automation_service_account": "Machine identity for automation/playbooks.",
    "provider_admin": "Administers an MSSP / reseller tenant and its customer portfolio.",
    "mssp_soc_manager": "Runs the managed SOC across every customer in the portfolio.",
    "mssp_analyst": "Provider analyst; works customers they are explicitly granted.",
    "mssp_account_manager": "Customer onboarding, SLAs, usage and service reporting.",
    "customer_viewer": "Customer stakeholder: dashboards, incidents and reports (read-only).",
    "customer_approver": "Customer stakeholder who approves response actions on their assets.",
    "customer_admin": "Customer administrator: users, approvals, branding and contacts.",
}


def roles_for_tenant_kind(kind: str, *, platform_root: bool = False) -> dict[str, list[str]]:
    """Role catalogue appropriate for a tenant of the given kind."""
    roles = {k: v for k, v in BUILTIN_ROLES.items() if k not in PLATFORM_ONLY_ROLES}
    if platform_root:
        roles["platform_super_admin"] = BUILTIN_ROLES["platform_super_admin"]
    if kind in ("provider", "reseller"):
        roles.update(PROVIDER_ROLES)
    else:
        roles.update(CUSTOMER_ROLES)
    return roles


# Roles that only exist in the platform (operator) tenant.
PLATFORM_ONLY_ROLES = {"platform_super_admin"}

# Approval authority: which roles satisfy an approval that requires role X.
APPROVAL_AUTHORITY: dict[str, set[str]] = {
    "incident_commander": {"incident_commander", "soc_manager", "tenant_admin"},
    "soc_manager": {"soc_manager", "tenant_admin"},
    "tenant_admin": {"tenant_admin"},
    "customer_approver": {"customer_approver", "customer_admin"},
}


def is_known_permission(perm: str) -> bool:
    if perm == WILDCARD or perm in PERMISSIONS:
        return True
    if perm.endswith(":*"):
        resource = perm[:-2]
        return any(p.split(":", 1)[0] == resource for p in PERMISSIONS)
    return False


def grant_violations(granter_permissions: list[str], requested: list[str]) -> list[str]:
    """Return the requested permissions the granter may NOT hand out.

    A principal can only grant permissions it holds itself (no escalation),
    unknown permission strings are rejected, and the wildcard / platform
    permissions can only be granted by a platform administrator.
    """
    is_platform = role_has_permission(granter_permissions, "platform:admin")
    bad: list[str] = []
    for perm in requested:
        if not is_known_permission(perm):
            bad.append(perm)
        elif perm == WILDCARD or perm in PLATFORM_PERMISSIONS or perm == "platform:*":
            if not is_platform:
                bad.append(perm)
        elif perm.endswith(":*"):
            resource = perm[:-2]
            covered = all(role_has_permission(granter_permissions, p)
                          for p in PERMISSIONS if p.split(":", 1)[0] == resource)
            if not covered:
                bad.append(perm)
        elif not role_has_permission(granter_permissions, perm):
            bad.append(perm)
    return bad


def role_has_permission(permissions: list[str], required: str) -> bool:
    if WILDCARD in permissions:
        return True
    if required in permissions:
        return True
    # Support resource-level wildcards like "incident:*".
    resource = required.split(":", 1)[0]
    return f"{resource}:*" in permissions
