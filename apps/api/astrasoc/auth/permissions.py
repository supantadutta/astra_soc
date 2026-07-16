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
    "evidence:write": "Add / promote evidence",
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
    # Platform administration
    "audit:read": "Read audit logs",
    "rbac:manage": "Manage roles and assignments",
    "user:manage": "Manage users and API keys",
    "tenant:manage": "Manage tenants",
    "settings:manage": "Manage system settings",
    "mode:manage": "Switch demo/live operating mode",
    "demo:manage": "Control demo scenarios and reseed",
    "health:read": "View platform health and observability",
}

WILDCARD = "*"

# --- Built-in roles -------------------------------------------------------
# Each maps to a permission list. These are seeded per tenant plus a set of
# global templates.
READ_ANALYST = [
    "alert:read", "incident:read", "evidence:read", "entity:read", "agent:read",
    "model:read", "tool:read", "query:run", "knowledge:read", "detection:read",
    "threatintel:read", "playbook:read", "approval:read", "policy:read",
    "report:read", "connector:read", "health:read",
]

TIER1 = READ_ANALYST + ["alert:write", "incident:write", "feedback:write", "agent:run"]

TIER2 = TIER1 + [
    "evidence:write", "incident:assign", "action:request", "report:generate",
    "threatintel:write", "knowledge:write",
]

TIER3 = TIER2 + ["detection:write", "playbook:write", "action:execute"]

BUILTIN_ROLES: dict[str, list[str]] = {
    "platform_super_admin": [WILDCARD],
    "tenant_admin": [
        p for p in PERMISSIONS
        if not p.startswith("tenant:")
    ] + ["tenant:manage"],
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
        "audit:read", "incident:read", "alert:read", "evidence:read",
        "policy:read", "approval:read", "report:read", "health:read",
        "connector:read", "model:read", "detection:read",
    ],
    "readonly_executive": [
        "incident:read", "report:read", "report:generate", "health:read",
    ],
    "integration_service_account": [
        "alert:read", "alert:write", "incident:read", "incident:write",
        "connector:read", "query:run",
    ],
    "automation_service_account": [
        "incident:read", "agent:run", "action:request", "playbook:read",
        "query:run", "report:generate",
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
}


def role_has_permission(permissions: list[str], required: str) -> bool:
    if WILDCARD in permissions:
        return True
    if required in permissions:
        return True
    # Support resource-level wildcards like "incident:*".
    resource = required.split(":", 1)[0]
    return f"{resource}:*" in permissions
