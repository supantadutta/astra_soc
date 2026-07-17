# Playbooks & Response Engine

## Visual builder
Playbooks are step graphs. Step types: trigger, condition, enrichment, query,
agent_task, human approval, delay, branch, parallel, response_action,
verification, rollback, notification, case_update, report.

Edit/save via **Automation Playbooks** or `PUT /playbooks/{key}` (bumps version,
keeps history).

## Durable execution
`services/workflow.py` is a **persisted state machine**: state is written after
every step, so a run survives process restart, worker failure, API timeout, LLM
failure and — especially — approval delays (it pauses at `WAITING_APPROVAL` and
resumes later). This mirrors the Temporal model used in production; the demo runs
it in-process without a Temporal cluster.

## Response actions
isolate/release endpoint, disable/re-enable account, revoke sessions, block
IP/domain, add/remove IOC, quarantine/remove email, create ticket, notify team,
increase monitoring, collect endpoint evidence.

**Critical:** a `response_action` step never executes directly — it creates a
`ResponseAction` through the response gateway, which enforces policy + approval +
verification. Playbooks cannot bypass governance.

## CACAO
The step model maps to CACAO playbook concepts; import/export is a documented
extension point.
