# Detection Engineering

Detections are the **deterministic** backbone — the LLM never replaces them.

## Rules
A `DetectionRule` carries Sigma source **and** a compiled `matcher` spec that is
evaluated against normalized events with no model involvement. Fields: severity,
status (draft→review→approved→deployed), ATT&CK mapping, data sources, false
positives, exceptions/allowlists, version history, author/reviewer/approver,
deployment target, health (last triggered, count), precision/recall where labels
exist, test data.

## Studio (`/detections`)
Editor, replay (`POST /detections/{id}/replay` runs the matcher over recent
events), Sigma→target translation (`POST /detections/translate` for SPL/KQL/
LogScale/ES), approval workflow.

## Guardrails
An **AI-generated rule can never be auto-deployed** — it must be reviewed and
approved first (enforced in the API). Approval/deploy requires `detection:approve`.

## Query Workbench (`/query`)
Read-only, validated queries for SPL, KQL, LogScale, Elasticsearch DSL,
SQL/ClickHouse and Sigma. Destructive commands are rejected before execution
(`is_read_only`), results are row/time capped. AI-generated queries are validated
before running.
