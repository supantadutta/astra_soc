# Monitoring & Observability

## Built-in
- **Platform Health** page + `GET /api/v1/platform/health` — service status,
  dependency status (honest "not configured"), AI provider health + circuit
  breakers, connector status, failed/retry/dead-letter queue counts.
- **Readiness** `GET /api/v1/health/ready` — dependency probe with real state.
- **Liveness** `GET /health`, `GET /api/v1/health/live`.
- **AI Model Operations** — token usage, cost, latency, provider health.
- **Analyst Performance** — MTTA/MTTI/MTTR, automation success by agent.
- Every response carries `x-request-id` and `x-response-time-ms`.

## Instrumented signals
API requests, agent runs, tool calls, connector calls, query execution, policy
decisions, approvals, response actions, errors — all recorded (audit + metrics
endpoints). Sensitive prompts/secrets are never logged in the clear.

## Production wiring
The env-var integration points (`ASTRASOC_*`) allow OpenTelemetry export to
Prometheus/Grafana and log shipping to OpenSearch. The metrics surfaced by the
dashboard/health endpoints map directly onto Grafana panels.
