# Agent Architecture

## Bounded specialists (16)
incident_coordinator, triage_agent, evidence_collector, endpoint_investigator,
identity_investigator, network_investigator, cloud_investigator,
email_investigator, threat_intel_agent, malware_analyst, attack_path_agent,
detection_engineer_agent, response_planner, independent_verifier,
incident_reporter, lessons_learned.

Each agent has: id, version, purpose, input/output schema, tool allowlist, max
execution time, max token budget, max tool calls, required data classification,
failure policy, retry policy, audit events, evaluation score, enabled state.

## Guarantees
- **Bounded:** every run enforces token/tool-call/time budgets.
- **Tool-restricted:** agents call tools only via the **tool broker**, and only
  those in their allowlist. Production-changing tools are hard-blocked at the
  broker — they can never run from an agent/tool call.
- **Evidence-first:** output must validate against the strict claim schema
  (claim, confidence, evidence_ids, alternatives, missing evidence, ATT&CK, …).
  It is persisted as `MODEL_INFERENCE`, never as fact.
- **Coordinator graph:** the coordinator invokes specialists in an explicit
  sequence (triage → evidence → domain specialist → independent verification)
  and threads a shared, versioned case snapshot — agents do not message each
  other freely.

## Evidence-first output
See `apps/api/astrasoc/schemas/ai_output.py`. A claim with no valid evidence
references **cannot** initiate a response — enforced by the response gateway.
The incident workspace renders the claim-evidence relationship and keeps facts,
inferences, assumptions and missing evidence visually distinct.
