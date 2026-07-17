# Live Mode

Live mode uses configured integrations and can send production-changing actions
through the governed response gateway. It is deliberately hard to enter.

## Activation requirements (all enforced server-side)
1. Caller holds `mode:manage` (SOC Manager or admin).
2. `ASTRASOC_ALLOW_LIVE_MODE=true` (deployments can hard-lock to demo).
3. **Explicit confirmation** (`confirm=true`).
4. **Readiness checks pass** — see `GET /api/v1/mode/readiness`:
   - at least one enabled, non-mock connector (real data source);
   - durable database recommended (SQLite flagged);
   - a real LLM provider *or* AI explicitly disabled.

Switch from **System Settings**. The header shows a persistent red **LIVE**
indicator. The switch is audited.

## Live guarantees
- Demo and live data remain fully separated by `data_scope`.
- All production actions go through policy → approval → dry-run → execute →
  verify → rollback.
- The gateway **never reports success unless the connector confirms it**.
- If a critical dependency fails, the platform marks itself `degraded` and shows
  the reason in the header and Platform Health.
