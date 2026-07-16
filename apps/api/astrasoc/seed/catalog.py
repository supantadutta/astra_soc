"""Static catalog: agents, tools, connectors, model deployments, routes, policy.

These definitions describe the platform's *capabilities*, independent of any
particular incident. They are seeded once and then editable through the API/UI.
"""
from __future__ import annotations

from ..models.enums import ConnectorCategory, ToolScope

# --- Capability aliases (spec §8) ----------------------------------------
CAPABILITIES = [
    "fast_triage", "deep_investigator", "independent_critic", "private_investigator",
    "detection_engineer", "malware_analyst", "multimodal_analyst", "report_writer",
    "embedding_model", "security_classifier", "response_planner",
]

# --- Simulated model deployments -----------------------------------------
# The built-in provider exposes deterministic "models" so the platform is fully
# functional with AI assistance even when no external LLM is configured.
MODEL_DEPLOYMENTS = [
    {"model_identifier": "sim-triage-1", "display_name": "Simulated Triage",
     "capabilities": ["fast_triage", "security_classifier"], "context_window": 32000,
     "cost_input_per_1k": 0.0, "cost_output_per_1k": 0.0, "avg_latency_ms": 180,
     "quality_score": 0.62, "tool_reliability": 0.7},
    {"model_identifier": "sim-investigator-1", "display_name": "Simulated Investigator",
     "capabilities": ["deep_investigator", "response_planner", "detection_engineer"],
     "context_window": 128000, "cost_input_per_1k": 0.0, "cost_output_per_1k": 0.0,
     "avg_latency_ms": 620, "quality_score": 0.71, "tool_reliability": 0.82},
    {"model_identifier": "sim-critic-1", "display_name": "Simulated Independent Critic",
     "capabilities": ["independent_critic", "malware_analyst"], "context_window": 64000,
     "cost_input_per_1k": 0.0, "cost_output_per_1k": 0.0, "avg_latency_ms": 400,
     "quality_score": 0.68, "tool_reliability": 0.75},
    {"model_identifier": "sim-writer-1", "display_name": "Simulated Report Writer",
     "capabilities": ["report_writer", "multimodal_analyst"], "context_window": 128000,
     "cost_input_per_1k": 0.0, "cost_output_per_1k": 0.0, "avg_latency_ms": 500,
     "quality_score": 0.7, "tool_reliability": 0.7},
    {"model_identifier": "sim-embed-1", "display_name": "Simulated Embeddings",
     "capabilities": ["embedding_model"], "context_window": 8192,
     "cost_input_per_1k": 0.0, "cost_output_per_1k": 0.0, "avg_latency_ms": 40,
     "quality_score": 0.6, "tool_reliability": 0.9, "supports_tools": False},
]

ROUTE_DEFS = {
    "fast_triage": "sim-triage-1",
    "security_classifier": "sim-triage-1",
    "deep_investigator": "sim-investigator-1",
    "response_planner": "sim-investigator-1",
    "detection_engineer": "sim-investigator-1",
    "independent_critic": "sim-critic-1",
    "malware_analyst": "sim-critic-1",
    "report_writer": "sim-writer-1",
    "multimodal_analyst": "sim-writer-1",
    "embedding_model": "sim-embed-1",
    "private_investigator": "sim-investigator-1",
}

# --- Bounded specialist agents (spec §9) ---------------------------------
def _agent(key, name, purpose, capability, tools, cls="internal", secs=90, tokens=40000, calls=10):
    return {
        "key": key, "name": name, "purpose": purpose, "enabled": True,
        "required_capability": capability, "tool_allowlist": tools,
        "required_data_classification": cls, "max_execution_seconds": secs,
        "max_token_budget": tokens, "max_tool_calls": calls,
        "failure_policy": "halt", "retry_policy": {"max_retries": 1, "backoff_seconds": 2},
        "input_schema": {"type": "object", "properties": {"incident_id": {"type": "string"}}},
        "output_schema": {"type": "object", "properties": {"claims": {"type": "array"}}},
        "evaluation_score": 0.7, "current_version": "1.0.0",
    }


AGENT_DEFS = [
    _agent("incident_coordinator", "Incident Coordinator",
           "Orchestrates the investigation workflow graph and invokes specialists.",
           "deep_investigator", ["get_incident", "list_evidence", "list_alerts"], secs=180, calls=20),
    _agent("triage_agent", "Triage Agent",
           "Rapidly assesses new alerts, deduplicates, and proposes initial severity.",
           "fast_triage", ["get_alert", "search_events", "lookup_ioc"], secs=45),
    _agent("evidence_collector", "Evidence Collection Agent",
           "Gathers read-only evidence from events and enrichment tools.",
           "deep_investigator", ["search_events", "get_entity", "lookup_ioc", "get_user_context"]),
    _agent("endpoint_investigator", "Endpoint Investigation Agent",
           "Investigates host/process/file activity on affected endpoints.",
           "deep_investigator", ["get_endpoint_detail", "list_processes", "search_events"]),
    _agent("identity_investigator", "Identity Investigation Agent",
           "Analyzes authentication, sign-ins and identity risk signals.",
           "deep_investigator", ["get_user_context", "list_signins", "search_events"]),
    _agent("network_investigator", "Network Investigation Agent",
           "Examines network flows, beaconing and DNS patterns.",
           "deep_investigator", ["search_events", "lookup_ioc", "resolve_domain"]),
    _agent("cloud_investigator", "Cloud Investigation Agent",
           "Investigates cloud control-plane and access-key activity.",
           "deep_investigator", ["search_events", "get_cloud_activity"]),
    _agent("email_investigator", "Email Investigation Agent",
           "Analyzes suspicious email, headers and attachments (read-only).",
           "deep_investigator", ["get_email_detail", "lookup_ioc"]),
    _agent("threat_intel_agent", "Threat-Intelligence Agent",
           "Enriches observables against threat-intel sources.",
           "security_classifier", ["lookup_ioc", "search_threat_intel"]),
    _agent("malware_analyst", "Malware-Analysis Agent",
           "Reasons over file/behavioral indicators (static, sandbox interface).",
           "malware_analyst", ["lookup_ioc", "get_file_reputation"]),
    _agent("attack_path_agent", "Attack-Path Agent",
           "Builds and scores attack paths across the entity graph.",
           "deep_investigator", ["get_entity_graph", "get_entity"]),
    _agent("detection_engineer_agent", "Detection-Engineering Agent",
           "Drafts Sigma detections from incident TTPs (never auto-deploys).",
           "detection_engineer", ["search_events", "get_incident"]),
    _agent("response_planner", "Response-Planning Agent",
           "Proposes governed response actions with evidence and blast radius.",
           "response_planner", ["get_incident", "list_evidence", "get_entity"], cls="confidential"),
    _agent("independent_verifier", "Independent Verification Agent",
           "Critiques the primary conclusion using a different model.",
           "independent_critic", ["get_incident", "list_evidence"]),
    _agent("incident_reporter", "Incident-Reporting Agent",
           "Produces technical and executive reports with evidence citations.",
           "report_writer", ["get_incident", "list_evidence", "get_timeline"]),
    _agent("lessons_learned", "Lessons-Learned Agent",
           "Extracts detection/playbook improvement proposals post-incident.",
           "deep_investigator", ["get_incident", "list_evidence"]),
]

# --- Tool registry (spec §11) --------------------------------------------
def _tool(key, name, desc, scope=ToolScope.READ_ONLY.value, perm="tool:read", egress=None):
    return {
        "key": key, "name": name, "description": desc, "version": "1.0.0",
        "scope": scope, "required_permission": perm,
        "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
        "allowed_tenants": [], "egress_allowlist": egress or [],
        "rate_limit_per_minute": 60, "timeout_seconds": 30,
        "max_response_bytes": 1_000_000, "approved": True, "enabled": True,
    }


TOOL_DEFS = [
    # Read-only investigation tools.
    _tool("get_incident", "Get Incident", "Fetch an incident with related entities."),
    _tool("get_alert", "Get Alert", "Fetch a single alert."),
    _tool("list_alerts", "List Alerts", "List alerts for an incident."),
    _tool("list_evidence", "List Evidence", "List evidence items for an incident."),
    _tool("get_timeline", "Get Timeline", "Fetch the incident timeline."),
    _tool("search_events", "Search Events", "Read-only search over normalized events."),
    _tool("get_entity", "Get Entity", "Fetch an enriched entity."),
    _tool("get_entity_graph", "Get Entity Graph", "Fetch the entity relationship graph."),
    _tool("get_user_context", "Get User Context", "Identity/role/risk for a user."),
    _tool("list_signins", "List Sign-ins", "Recent authentication events for a user."),
    _tool("get_endpoint_detail", "Get Endpoint Detail", "Host posture and status."),
    _tool("list_processes", "List Processes", "Recent processes on a host."),
    _tool("get_cloud_activity", "Get Cloud Activity", "Cloud control-plane events."),
    _tool("get_email_detail", "Get Email Detail", "Headers/links/attachments of an email."),
    _tool("lookup_ioc", "Lookup IOC", "Reputation lookup for an indicator.",
          egress=["api.virustotal.com", "misp.local"]),
    _tool("search_threat_intel", "Search Threat Intel", "Search the TI knowledge base."),
    _tool("get_file_reputation", "Get File Reputation", "Static/behavioral file reputation."),
    _tool("resolve_domain", "Resolve Domain", "Passive DNS / resolution info.",
          egress=["dns.local"]),
    # Production-changing response tools (require action:execute + approval).
    _tool("isolate_endpoint", "Isolate Endpoint", "Network-isolate a host.",
          scope=ToolScope.RESPONSE.value, perm="action:execute"),
    _tool("release_endpoint", "Release Endpoint", "Remove host isolation.",
          scope=ToolScope.RESPONSE.value, perm="action:execute"),
    _tool("disable_account", "Disable Account", "Disable a user account.",
          scope=ToolScope.RESPONSE.value, perm="action:execute"),
    _tool("revoke_sessions", "Revoke Sessions", "Revoke active user sessions.",
          scope=ToolScope.RESPONSE.value, perm="action:execute"),
    _tool("block_ip", "Block IP", "Add an IP to the blocklist.",
          scope=ToolScope.RESPONSE.value, perm="action:execute"),
    _tool("block_domain", "Block Domain", "Add a domain to the blocklist.",
          scope=ToolScope.RESPONSE.value, perm="action:execute"),
    _tool("quarantine_email", "Quarantine Email", "Quarantine a message.",
          scope=ToolScope.RESPONSE.value, perm="action:execute"),
    _tool("create_ticket", "Create Ticket", "Open an ITSM ticket.",
          scope=ToolScope.RESPONSE.value, perm="action:request"),
    _tool("collect_endpoint_evidence", "Collect Endpoint Evidence",
          "Trigger forensic collection on a host.",
          scope=ToolScope.RESPONSE.value, perm="action:execute"),
]

# --- Connector catalog (spec §12) ----------------------------------------
def _conn(kind, name, category, can_write=False):
    return {
        "kind": kind, "name": name, "category": category, "enabled": False,
        "can_read": True, "can_write": can_write, "use_mock": True,
        "config": {"data_mappings": {}, "notes": "Uses built-in mock server until real credentials are supplied."},
        "collection_interval_seconds": 300, "rate_limit_per_minute": 120,
    }


CONNECTOR_DEFS = [
    _conn("crowdstrike_logscale", "CrowdStrike LogScale", ConnectorCategory.SIEM.value),
    _conn("splunk", "Splunk", ConnectorCategory.SIEM.value),
    _conn("microsoft_sentinel", "Microsoft Sentinel", ConnectorCategory.SIEM.value),
    _conn("elastic", "Elastic / OpenSearch", ConnectorCategory.SIEM.value),
    _conn("generic_rest_siem", "Generic REST SIEM", ConnectorCategory.SIEM.value),
    _conn("generic_syslog", "Generic Syslog", ConnectorCategory.SIEM.value),
    _conn("crowdstrike_falcon", "CrowdStrike Falcon", ConnectorCategory.EDR.value, can_write=True),
    _conn("microsoft_defender", "Microsoft Defender", ConnectorCategory.EDR.value, can_write=True),
    _conn("vectra", "Vectra", ConnectorCategory.NDR.value),
    _conn("stellar_cyber", "Stellar Cyber", ConnectorCategory.NDR.value),
    _conn("generic_edr", "Generic EDR/NDR REST", ConnectorCategory.EDR.value, can_write=True),
    _conn("entra_id", "Microsoft Entra ID", ConnectorCategory.IDENTITY.value, can_write=True),
    _conn("active_directory", "Active Directory", ConnectorCategory.IDENTITY.value, can_write=True),
    _conn("keycloak", "Keycloak", ConnectorCategory.IDENTITY.value),
    _conn("generic_ldap", "Generic LDAP (read)", ConnectorCategory.IDENTITY.value),
    _conn("misp", "MISP", ConnectorCategory.THREAT_INTEL.value),
    _conn("virustotal", "VirusTotal", ConnectorCategory.THREAT_INTEL.value),
    _conn("taxii", "TAXII", ConnectorCategory.THREAT_INTEL.value),
    _conn("generic_stix_taxii", "Generic STIX/TAXII", ConnectorCategory.THREAT_INTEL.value),
    _conn("servicenow", "ServiceNow", ConnectorCategory.ITSM.value, can_write=True),
    _conn("jira", "Jira", ConnectorCategory.ITSM.value, can_write=True),
    _conn("slack", "Slack", ConnectorCategory.COMMS.value, can_write=True),
    _conn("microsoft_teams", "Microsoft Teams", ConnectorCategory.COMMS.value, can_write=True),
    _conn("email_webhook", "Email Webhook", ConnectorCategory.COMMS.value, can_write=True),
    _conn("aws", "AWS", ConnectorCategory.CLOUD.value),
    _conn("azure", "Azure", ConnectorCategory.CLOUD.value),
    _conn("gcp", "Google Cloud", ConnectorCategory.CLOUD.value),
    _conn("k8s_audit", "Kubernetes Audit Logs", ConnectorCategory.CLOUD.value),
]

# --- Response policy-as-code (spec §16) ----------------------------------
# Evaluated by the built-in policy engine (or handed to OPA when configured).
# Higher-criticality targets and irreversible actions require approval; unsafe
# combinations are denied outright.
RESPONSE_POLICY = {
    "version": "1.0.0",
    "defaults": {"min_confidence": 0.7, "effect": "require_approval"},
    "rules": [
        {"name": "deny_low_confidence",
         "if": {"confidence_lt": 0.5},
         "effect": "deny",
         "reason": "Confidence below 0.5 — insufficient basis for any response."},
        {"name": "deny_no_evidence",
         "if": {"evidence_count_lt": 1},
         "effect": "deny",
         "reason": "No supporting evidence cited."},
        {"name": "critical_asset_requires_approval",
         "if": {"asset_criticality_in": ["high", "critical"]},
         "effect": "require_approval",
         "approver_role": "incident_commander",
         "reason": "Target is a business-critical asset."},
        {"name": "irreversible_requires_approval",
         "if": {"reversible_eq": False},
         "effect": "require_approval",
         "approver_role": "soc_manager",
         "reason": "Action is not reversible."},
        {"name": "wide_blast_radius_requires_approval",
         "if": {"blast_radius_gt": 5},
         "effect": "require_approval",
         "approver_role": "incident_commander",
         "reason": "Action affects more than 5 assets."},
        {"name": "auto_allow_safe_monitoring",
         "if": {"action_in": ["increase_monitoring", "create_ticket", "notify_team"],
                "confidence_gte": 0.7},
         "effect": "allow",
         "reason": "Low-risk, reversible enrichment/monitoring action."},
        {"name": "auto_allow_high_confidence_reversible",
         "if": {"reversible_eq": True, "confidence_gte": 0.9,
                "asset_criticality_in": ["info", "low", "medium"]},
         "effect": "allow",
         "reason": "High-confidence reversible action on non-critical asset."},
    ],
}
