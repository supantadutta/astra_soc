# Testing Report

What was actually executed, with the real results. Nothing here is
estimated. Anything not run is listed under **Not executed**, with the reason.

## Environment

Linux; Python 3.11.15; Node 22.22; PostgreSQL 16.13; Docker 29.3;
Playwright with the pre-installed Chromium.

## Backend (pytest)

```bash
cd apps/api
python -m pytest -q                                               # SQLite
ASTRASOC_TEST_DATABASE_URL=postgresql+psycopg2://user@host/db python -m pytest -q   # PostgreSQL
```

**Result: 122 passed on SQLite and 122 passed on PostgreSQL 16.**

| Suite | Tests | Covers |
|-------|------:|--------|
| `test_security_hardening.py` | 26 | Secret-reference confinement (`env://`/`file://` refused, tenant `vault://` namespace), egress policy (metadata, loopback, non-HTTP blocked), RBAC grant rules (no wildcard/unheld/platform/provider permissions), logout revokes the token, refresh rotation with reuse detection, lockout, password policy, scoped API keys, evidence integrity (analysts cannot mint confirmed facts; attestation requires a source), cross-tenant report refusal, HTML export escaping, production configuration guard, security headers, body-size limit, internal-domain sign-in, demo-account advertisement, per-credential rate limiting |
| `test_mssp.py` | 25 | Granted vs ungranted access, SOC-manager reach including reseller customers, customer isolation from peers and the provider, delegated actions attributed in the customer's audit trail, customer switching provider access off (break-glass only), provider cannot change the customer's policy, portfolio scoping, unified queue ordering, SLA report and usage/billing, plan entitlements (essentials blocks AI), contract feature overrides, grant rules and revocation, onboarding (isolated, ready tenant; input validation), offboarding only after suspension and typed confirmation, content distribution, shift handover, service reports, SLA sweeper escalation, `/auth/me` delegation context, profile/contract field validation |
| `test_workflows_and_content.py` | 14 | Durable playbooks (approval gates, approver authority, conditions, failure halts, idempotency), query engine, detection lifecycle (four-eyes, managed rules locked) |
| `test_pipeline_and_stream.py` | 10 | Cross-thread, tenant-isolated event bus; stream tickets; ingestion → detection → alert → correlation; rule exceptions; threat-intel matching; vendor field aliases (Sysmon/ECS); ingest validation; mock connector sync |
| `test_evidence_and_policy.py` | 7 | Evidence-first schema, claims without evidence cannot justify actions, policy decisions |
| `test_agents_and_injection.py` | 6 | Agent output, coordinator workflow, injection detection, DLP masking, external-content wrapping, tool broker blocks response tools |
| `test_auth_rbac.py` | 6 | Login, bad credentials, unauthenticated access, route RBAC |
| `test_connectors_and_models.py` | 6 | Truthful provider/connector status (`not_configured` without secrets, mocks labelled), destructive query rejection, PDF export, audit chain |
| `test_ai_guardrails.py` | 5 | Provider eligibility (AI off, strategy, plan, private-only, hybrid classification, residency, budgets), untrusted-content wrapping, real-provider path with hallucinated evidence dropped, per-tenant model routes |
| `test_connector_live_write.py` | 5 | Live writes hit the real HTTP adapter against the mock server; true outcomes (200 → success, 401 → failure), missing secret → not sent |
| `test_mode_and_isolation.py` | 4 | Per-tenant DEMO/LIVE, readiness gate, scope filtering |
| `test_response_flow.py` | 3 | Governed response pipeline end to end |
| `test_tenant_isolation.py` | 3 | Another tenant sees none of Acme's incidents, cannot fetch one by id, and cannot switch into a peer tenant |
| `test_audit_chain.py` | 2 | Keyed HMAC chain verifies; an edited entry and a deleted entry are both detected |

## Database migrations

On a fresh PostgreSQL database: `alembic upgrade head` applies both migrations,
then `alembic check` reports **"No new upgrade operations detected"**, so the
migrations match the models exactly. CI runs the same check.

## Static checks

| Check | Result |
|-------|--------|
| `ruff check astrasoc tests` | All checks passed |
| `npm run typecheck` | 0 errors |
| `npm run lint` | No ESLint warnings or errors |
| `npm run build` (Next.js 15.5 production build) | Succeeded |
| `npm audit` (production and dev dependencies) | 0 vulnerabilities |

## End-to-end (Playwright)

```bash
# API in demo profile on :8000, web production build on :3000
cd apps/web && npx playwright test
```

**Result: 27 passed**: 9 specs × 3 device profiles (desktop Chromium,
iPad Pro 11 viewport, Pixel 7).

Specs: demo accounts shown only when seeded; customer SOC manager dashboard
(and no provider navigation); incident workspace (SLA clock, add note, add
evidence); run investigation; MSSP portfolio → open customer → delegation
banner → return home; unified queue with SLA states; granted analyst sees
only granted customers; onboard a customer end to end; every one of the 32
module routes renders.

Issues found **by** these runs and fixed: the sidebar crushed content on
phones (now an off-canvas drawer); wide tables stretched the page on tablets
and pushed dialogs off-screen; and all users behind one proxy shared a single
rate-limit bucket (now per credential). Page width was then probed on 11 data-heavy
pages at 412 px and 834 px, and matched the viewport exactly on all of them.

## Container images and production stack

Both images were built with Docker and the production compose file was run
locally (PostgreSQL, strong generated secrets, bootstrap admin). Verified:

- API refuses to start with weak secrets; with valid config it auto-migrates.
- Only the bootstrap administrator exists; the demo credentials are refused.
- Onboarding a customer with its first admin; tenant switching (`via platform`).
- Event ingestion through the web proxy; the SSE stream flows through the
  proxy (`text/event-stream`, events delivered).
- Audit chain verifies (`HMAC-SHA256 chain v2`).
- A customer admin is denied the provider portfolio (403) and the provider
  tenant (403).
- API runs as uid 10001, web as uid 1001; security headers and CSP present.

This smoke run found and fixed two real defects: bootstrap admins on internal
domains (`corp.local`) could not sign in, and vendor-shaped events
(`CommandLine`, `process_creation`) silently missed detections.

## Deployment manifests

- `helm lint`: passed. `helm template` refuses to render without secrets or
  with identical JWT and audit keys, and renders cleanly with
  `secrets.existingSecret` or with an external database.
- The rendered chart, the plain Kubernetes manifest, the ArgoCD application,
  the CI workflow and both compose files all parse as valid YAML.
  `docker compose config` validates both compose files.

## Not executed

| Item | Reason |
|------|--------|
| Real vendor integrations (SIEM/EDR/ticketing) | No vendor environments or credentials. Adapters are exercised against the bundled mock server only. |
| Real LLM API calls | No API keys. The real-provider code path is tested with a mocked provider response. |
| Kubernetes schema validation (kubeconform) and a live cluster install | The schema tool image could not be downloaded in this environment; no cluster available. |
| The GitHub Actions workflow itself | Written and syntax-checked; it runs on the next push to GitHub. |
| WebKit/Safari | Only Chromium is installed; the tablet profile runs the iPad viewport in Chromium. |
| Load, soak, chaos, penetration testing | Out of scope for this build. |
