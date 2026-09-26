# Live Mode

Live mode uses configured integrations and can send production-changing actions
through the governed response gateway. It is deliberately hard to enter.

**The mode is per tenant.** Each customer moves to LIVE on its own schedule
once its integrations are ready; the others stay in DEMO. A tenant without its
own setting inherits the deployment default (`ASTRASOC_DEFAULT_MODE`).

## Activation requirements (all enforced server-side)
1. Caller holds `mode:manage` (SOC Manager or admin).
2. `ASTRASOC_ALLOW_LIVE_MODE=true` (deployments can hard-lock to demo).
3. **Explicit confirmation** (`confirm=true`).
4. **Readiness checks pass** for that tenant (`GET /api/v1/mode/readiness`):
   - at least one enabled, non-mock connector (real data source);
   - durable database recommended (SQLite flagged);
   - a real LLM provider configured for the tenant, *or* AI explicitly disabled.

Switch from **System Settings**. The header shows a persistent red **LIVE**
indicator. The switch is audited.

## Live guarantees
- Demo and live data remain fully separated by `data_scope`.
- All production actions go through policy → approval → dry-run → execute →
  verify → rollback. Read the response-gateway notes in
  [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md#response-and-automation) before
  enabling automated response for a customer.
- The gateway **never reports success unless the connector confirms it**.
- If a critical dependency fails, the platform marks itself `degraded` and shows
  the reason in the header and Platform Health.
