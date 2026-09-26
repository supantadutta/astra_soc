# Testing Report

What was actually executed, with the real results. Nothing here is
estimated. Anything not run is listed under **Not executed**, with the reason.

## Environment

Linux; Python 3.11.15; Node 22.22; PostgreSQL 16.13; Docker 29.3;
Playwright 1.61 with the pre-installed Chromium.

## Backend (pytest)

```bash
cd apps/api
python -m pytest -q                                               # SQLite
ASTRASOC_TEST_DATABASE_URL=postgresql+psycopg2://user@host/db python -m pytest -q   # PostgreSQL
```

**Result: 148 passed on PostgreSQL 16; on SQLite 146 passed and 2 skipped**
(the two cross-replica tests need PostgreSQL LISTEN/NOTIFY and advisory
locks). CI runs both.

| Suite | Tests | Covers |
|-------|------:|--------|
| `test_security_hardening.py` | 28 | Secret-reference confinement (`env://`/`file://` refused, tenant `vault://` namespace), egress policy (metadata, loopback, non-HTTP blocked), RBAC grant rules (no wildcard/unheld/platform/provider permissions), logout revokes the token, refresh rotation with reuse detection, the refresh grace window (a lost rotation is honoured once, briefly; can be disabled), lockout, password policy, scoped API keys, evidence integrity (analysts cannot mint confirmed facts; attestation requires a source), cross-tenant report refusal, HTML export escaping, production configuration guard, security headers, body-size limit, internal-domain sign-in, demo-account advertisement, per-credential rate limiting (Bearer, API key, session cookie) |
| `test_mssp.py` | 25 | Granted vs ungranted access, SOC-manager reach including reseller customers, customer isolation from peers and the provider, delegated actions attributed in the customer's audit trail, customer switching provider access off (break-glass only), provider cannot change the customer's policy, portfolio scoping, unified queue ordering, SLA report and usage/billing, plan entitlements (essentials blocks AI), contract feature overrides, grant rules and revocation, onboarding (isolated, ready tenant; input validation), offboarding only after suspension and typed confirmation, content distribution, shift handover, service reports, SLA sweeper escalation, `/auth/me` delegation context, profile/contract field validation |
| `test_mfa_and_sessions.py` | 18 | TOTP against the RFC 6238 test vectors; replay and drift rejection; secret encrypted at rest; enroll then sign-in requires the second factor; failed codes lock the account; MFA material never serialized; disable needs password + code; tenant policy forces enrollment at sign-in and ends existing non-MFA sessions; a customer's policy binds delegated provider staff and their API keys; MFA cannot be disabled where required; admin reset of a lost authenticator; cookie sessions keep tokens away from JavaScript; state changes by cookie need the CSRF token; cookie refresh rotates and logout clears; Bearer clients unaffected by CSRF; cookie session through the MFA step; production guard for the new settings |
| `test_workflows_and_content.py` | 14 | Durable playbooks (approval gates, approver authority, conditions, failure halts, idempotency), query engine, detection lifecycle (four-eyes, managed rules locked) |
| `test_pipeline_and_stream.py` | 10 | Cross-thread, tenant-isolated event bus; stream tickets; ingestion → detection → alert → correlation; rule exceptions; threat-intel matching; vendor field aliases (Sysmon/ECS); ingest validation; mock connector sync |
| `test_evidence_and_policy.py` | 7 | Evidence-first schema, claims without evidence cannot justify actions, policy decisions |
| `test_agents_and_injection.py` | 6 | Agent output, coordinator workflow, injection detection, DLP masking, external-content wrapping, tool broker blocks response tools |
| `test_ai_guardrails.py` | 6 | Provider eligibility (AI off, strategy, plan, private-only, hybrid classification, residency, budgets), untrusted-content wrapping, real-provider path with hallucinated evidence dropped, per-tenant model routes, oversized cases trimmed structurally (the prompt stays valid JSON) |
| `test_auth_rbac.py` | 6 | Login, bad credentials, unauthenticated access, route RBAC |
| `test_connectors_and_models.py` | 6 | Truthful provider/connector status (`not_configured` without secrets, mocks labelled), destructive query rejection, PDF export, audit chain |
| `test_cluster.py` | 5 | Exactly one leader with failover (PostgreSQL); events fan out to other replicas without echo (PostgreSQL); generator control shared through the database; in-process migration keeps application logging; an open live stream does not block shutdown (real server process, SIGTERM) |
| `test_connector_live_write.py` | 5 | Live writes hit the real HTTP adapter against the mock server; true outcomes (200 → success, 401 → failure), missing secret → not sent |
| `test_mode_and_isolation.py` | 4 | Per-tenant DEMO/LIVE, readiness gate, scope filtering |
| `test_response_flow.py` | 3 | Governed response pipeline end to end |
| `test_tenant_isolation.py` | 3 | Another tenant sees none of Acme's incidents, cannot fetch one by id, and cannot switch into a peer tenant |
| `test_audit_chain.py` | 2 | Keyed HMAC chain verifies; an edited entry and a deleted entry are both detected |

## Database migrations

On a fresh PostgreSQL database: `alembic upgrade head` applies all three
migrations, `alembic check` reports **"No new upgrade operations
detected"** (the migrations match the models exactly), `alembic downgrade
base` reverses all three, and upgrading again succeeds. CI runs the upgrade and
check.

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
# API in the demo profile on :8000. All specs sign in from one IP, so raise
# the per-IP sign-in limit: ASTRASOC_AUTH_RATE_LIMIT_PER_MINUTE=300
# Web production build on :3000.
cd apps/web && npx playwright test
```

**Result: 42 passed**: 14 specs × 3 device profiles (desktop Chromium,
iPad Pro 11 viewport, Pixel 7).

Specs: session tokens are not readable by page JavaScript; an expired access
cookie is refreshed transparently and the session survives the next
navigation; enroll an authenticator → sign out → sign back in with a code;
header controls (Sign out, notifications) stay on screen for two roles;
demo accounts shown only when seeded; customer SOC manager dashboard (and no
provider navigation); incident workspace (SLA clock, add note, add
evidence); run investigation; MSSP portfolio → open customer → delegation
banner → return home; unified queue with SLA states; granted analyst sees
only granted customers; onboard a customer end to end; every one of the 32
module routes renders.

The refresh spec was also repeated 5 times per profile (15/15). During those
runs the API logged 19 refreshes, all 200, with no revoked sessions and no
`auth.refresh_reuse_detected` events.

Issues found **by** these runs and fixed:
- The sidebar crushed content on phones (now an off-canvas drawer). Wide
  tables stretched the page on tablets and pushed dialogs off-screen.
- All users behind one proxy shared a single rate-limit bucket (now keyed
  per credential, including session cookies).
- On tablets the header overflowed and pushed Sign out off-screen.
- **A navigation during a token refresh signed the user out as a suspected
  token theft.** The browser aborted the refresh after the server had
  rotated the token, so the next page presented the previous one. Fixed with
  a 30-second, single-use grace window for the previous refresh token.
- Signed-out page loads spent the per-IP sign-in budget on refresh calls
  that could not succeed; the client now skips them when there is no session
  cookie.
- **The web proxy leaked live streams.** It never aborted the upstream
  request when a browser left, so every closed tab kept a stream (with a
  bus subscription and a session check every 15 s) open on the API until
  the session expired. Before the fix, all 23 streams opened during a
  Playwright run were still open on the API afterwards. After it, the full
  suite opened 120 streams and none remained
  (0 API connections 10 s after the suite); a direct check (5 streams via
  the proxy, clients killed) went from 5 lingering connections to 0.

## Multi-replica operation

**Two local API processes on one PostgreSQL** (production settings, started
simultaneously):
- Migrations and seeding ran once; the other replica waited on the startup
  lock and then skipped them.
- Ingest on replica A → the live stream on replica B received
  `event.ingested`, `alert.created`, `incident.created` and notifications.
- Killing the leader (SIGKILL): the other replica took over leadership in
  about 3 s.

**Production compose stack** (`docker compose … up --scale api=2`, images
built from this tree, PostgreSQL, Secure cookies), talking to each API
container directly:
- 6 events ingested on `api-1` → 6 `event.ingested` frames on a live stream
  connected to `api-2`.
- Exactly one replica reported itself leader.
- `docker stop` of the leader **with a live stream open on it** completed in
  1.5 s: the stream ended, the lifespan shutdown ran ("Application shutdown
  complete"), exit code 0. The surviving replica became leader 6.2 s later.
- Through the web proxy (earlier run of the same stack, before this round's
  proxy and shutdown fixes): all three session cookies were passed through with
  the correct flags (`HttpOnly`, `Secure`, `SameSite=Strict`, paths);
  cookie-authenticated `/auth/me` succeeded; a POST without the CSRF header
  was refused (403) and succeeded with it. The proxy sent all of this traffic
  to one replica, which is why cross-replica delivery was checked against
  the containers directly.

**Shutdown with open streams:** before the fix, SIGTERM with one stream open
left the API waiting indefinitely (still running 40 s later, and until the
client disconnected). sse-starlette's shutdown hook never engaged under
uvicorn 0.30. After the fix: 1.9 s locally and 1.5 s in the container. The
regression test fails (`TimeoutExpired`) with the fix disabled.

## Container images and production stack

Both images were built with Docker and the production compose file was run
(PostgreSQL, strong generated secrets, bootstrap admin). Verified in earlier
runs and again with the current images where noted above:

- API refuses to start with weak secrets; with valid config it auto-migrates.
- Only the bootstrap administrator exists; the demo credentials are refused.
- Onboarding a customer with its first admin; tenant switching (`via platform`).
- Event ingestion through the web proxy; the SSE stream flows through the
  proxy (`text/event-stream`, events delivered).
- Audit chain verifies (`HMAC-SHA256 chain v2`).
- A customer admin is denied the provider portfolio (403) and the provider
  tenant (403).
- API runs as uid 10001, web as uid 1001; security headers and CSP present.

Smoke runs found and fixed: bootstrap admins on internal domains
(`corp.local`) could not sign in; vendor-shaped events (`CommandLine`,
`process_creation`) silently missed detections; and running migrations
in-process disabled every application logger (Alembic's `fileConfig`), so a
production API logged nothing after startup.

## Deployment manifests

- `helm lint`: passed. `helm template` refuses to render without the JWT
  secret, the audit key or (with the bundled database) a PostgreSQL password,
  and with identical JWT and audit keys. With `api.replicas=2` (the default)
  it renders a RollingUpdate with `maxUnavailable: 0`, pod anti-affinity and a
  PodDisruptionBudget (`minAvailable: 1`); with `api.replicas=1` it renders
  neither of the last two.
- The rendered chart, the plain Kubernetes manifest (2 API replicas plus a
  PodDisruptionBudget), the ArgoCD application, the CI workflow and both
  compose files parse as valid YAML. `docker compose config` validates both
  compose files.

## Not executed

| Item | Reason |
|------|--------|
| Real vendor integrations (SIEM/EDR/ticketing) | No vendor environments or credentials. Adapters are exercised against the bundled mock server only. |
| Real LLM API calls | No API keys. The real-provider code path is tested with a mocked provider response. |
| Kubernetes schema validation (kubeconform) and a live cluster install | The schema tool image could not be downloaded in this environment; no cluster available. Rolling updates and PDB behaviour are therefore verified only as rendered manifests plus the compose stop/failover run above. |
| Real authenticator apps | TOTP is verified against the RFC 6238 vectors and in the browser with a Node implementation of the algorithm, not with a phone app. |
| WebKit/Safari | Only Chromium is installed; the tablet profile runs the iPad viewport in Chromium. |
| Load, soak, chaos, penetration testing | Out of scope for this build. |
