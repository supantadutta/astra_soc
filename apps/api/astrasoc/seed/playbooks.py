"""Seed playbook definitions.

A playbook graph is an ordered list of typed steps. The demo workflow engine
(:mod:`astrasoc.services.workflow`) executes them durably, persisting state
after every step so a run survives restarts, approval delays and failures.
Step types: trigger, condition, enrichment, query, agent_task, approval, delay,
branch, parallel, response_action, verification, rollback, notification,
case_update, report.
"""
from __future__ import annotations

PLAYBOOK_DEFS = [
    {
        "key": "pb_ransomware_containment",
        "name": "Ransomware Precursor — Contain & Verify",
        "description": "Triage a ransomware-precursor incident, gather evidence, "
                       "then isolate the affected endpoint with human approval and verify.",
        "tags": ["endpoint", "containment", "high-severity"],
        "trigger": {"on": "incident.created", "if": {"scenario_key": "ransomware_precursor"}},
        "graph": {
            "steps": [
                {"id": "s1", "type": "trigger", "name": "Incident created"},
                {"id": "s2", "type": "enrichment", "name": "Enrich host & user",
                 "tool": "get_endpoint_detail"},
                {"id": "s3", "type": "agent_task", "name": "Endpoint investigation",
                 "agent": "endpoint_investigator"},
                {"id": "s4", "type": "condition", "name": "Confidence >= 0.7",
                 "if": {"confidence_gte": 0.7}},
                {"id": "s5", "type": "approval", "name": "Approve isolation",
                 "required_role": "incident_commander"},
                {"id": "s6", "type": "response_action", "name": "Isolate endpoint",
                 "action": "isolate_endpoint"},
                {"id": "s7", "type": "verification", "name": "Verify isolation"},
                {"id": "s8", "type": "case_update", "name": "Update case to contained"},
                {"id": "s9", "type": "notification", "name": "Notify response team"},
                {"id": "s10", "type": "report", "name": "Generate incident report"},
            ],
        },
    },
    {
        "key": "pb_identity_compromise",
        "name": "Identity Compromise — Revoke & Monitor",
        "description": "For impossible-travel / credential-compromise incidents: "
                       "revoke sessions, optionally disable account, and raise monitoring.",
        "tags": ["identity", "containment"],
        "trigger": {"on": "incident.created", "if": {"scenario_key": "identity_compromise"}},
        "graph": {
            "steps": [
                {"id": "s1", "type": "trigger", "name": "Incident created"},
                {"id": "s2", "type": "agent_task", "name": "Identity investigation",
                 "agent": "identity_investigator"},
                {"id": "s3", "type": "condition", "name": "Confirmed compromise",
                 "if": {"confidence_gte": 0.75}},
                {"id": "s4", "type": "approval", "name": "Approve session revocation",
                 "required_role": "incident_commander"},
                {"id": "s5", "type": "response_action", "name": "Revoke sessions",
                 "action": "revoke_sessions"},
                {"id": "s6", "type": "verification", "name": "Verify revocation"},
                {"id": "s7", "type": "response_action", "name": "Increase monitoring",
                 "action": "increase_monitoring"},
                {"id": "s8", "type": "notification", "name": "Notify SOC"},
            ],
        },
    },
    {
        "key": "pb_phishing_triage",
        "name": "Phishing — Quarantine & Purge",
        "description": "Investigate a reported phishing email and quarantine/remove it "
                       "from affected mailboxes after approval.",
        "tags": ["email", "phishing"],
        "trigger": {"on": "incident.created", "if": {"scenario_key": "phishing_attachment"}},
        "graph": {
            "steps": [
                {"id": "s1", "type": "trigger", "name": "Incident created"},
                {"id": "s2", "type": "agent_task", "name": "Email investigation",
                 "agent": "email_investigator"},
                {"id": "s3", "type": "enrichment", "name": "IOC lookup", "tool": "lookup_ioc"},
                {"id": "s4", "type": "approval", "name": "Approve quarantine",
                 "required_role": "incident_commander"},
                {"id": "s5", "type": "response_action", "name": "Quarantine email",
                 "action": "quarantine_email"},
                {"id": "s6", "type": "verification", "name": "Verify quarantine"},
                {"id": "s7", "type": "case_update", "name": "Update case"},
            ],
        },
    },
    {
        "key": "pb_generic_enrich",
        "name": "Generic Enrichment & Triage",
        "description": "Default playbook: enrich entities, run triage agent, summarize.",
        "tags": ["triage"],
        "trigger": {"on": "incident.created"},
        "graph": {
            "steps": [
                {"id": "s1", "type": "trigger", "name": "Incident created"},
                {"id": "s2", "type": "enrichment", "name": "Enrich observables",
                 "tool": "lookup_ioc"},
                {"id": "s3", "type": "agent_task", "name": "Triage", "agent": "triage_agent"},
                {"id": "s4", "type": "case_update", "name": "Record triage outcome"},
            ],
        },
    },
]
