# ASTRASOC

**Multi-tenant, AI-assisted security operations platform for MSSPs and in-house SOCs.**

One deployment runs a managed security service: the provider's SOC, resellers,
and many isolated customers, with contractual SLAs, delegated analyst access,
per-customer entitlements and usage metering. Inside each tenant, analysts get
a real-time detection pipeline, an investigation workspace, bounded AI agents,
durable playbooks and governed response.

> **Design principle:** models are advisory. Detection, authorization, tenant
> isolation, policy, approvals and audit are deterministic and enforced by the
> API. No model output can grant access or execute an action.

---

## Quick start (demo, zero credentials)

```bash
docker compose -f docker-compose.demo.yml up --build
```

Open <http://localhost:3000>. Demo accounts are listed on the sign-in page
(password `Demo!Pass123`). Try `soc@astrasoc.io` (MSSP SOC manager),
`manager@acme.io` (customer SOC manager) and `ciso@acme.io` (customer admin).
The walkthrough is in [docs/QUICKSTART.md](docs/QUICKSTART.md).

To understand the whole platform (data sources, the flow, every capability,
and what is not built yet), read [docs/PLATFORM_GUIDE.md](docs/PLATFORM_GUIDE.md).

For production see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The API refuses to
start with unsafe configuration and never creates demo accounts in production.

---

## What you get

**Managed service (MSSP)**, see [docs/MSSP.md](docs/MSSP.md)
- Provider → reseller → customer hierarchy with tenant lifecycle (onboarding,
  active, suspended, offboarding), contracts, data-residency regions, export
  and confirmed offboarding.
- Delegated access: provider-wide for SOC managers, time-boxed justified grants
  per analyst, audited break-glass. Customers can switch provider access off.
  Every delegated action lands in the customer's own audit trail.
- Service tiers (Essentials / Professional / Enterprise) with API-enforced
  feature entitlements and per-contract overrides.
- SLA engine: per-severity acknowledgement and resolution clocks, background
  breach detection, escalation to customer and provider, compliance reports.
- Portfolio, unified cross-customer queue, content distribution of managed
  detections, shift handover, usage metering with CSV export, monthly service
  reports.

**Security operations (per tenant)**
- Ingestion API for log forwarders (normalises common Sysmon / Windows / ECS
  fields) → deterministic detections with exceptions and threat-intel matching
  → deduplicated alerts → correlated incidents.
- Investigation workspace: timeline, evidence that keeps confirmed facts,
  analyst conclusions and AI inferences apart, source-attested facts, entity
  graph, hypotheses.
- 16 bounded AI agents behind a model gateway with per-tenant AI policy,
  residency, classification, private-model and budget guardrails, prompt-
  injection wrapping, and verification of cited evidence. A built-in simulated
  reasoner works without any external LLM.
- Detection engineering with four-eyes approval, replay, versioning.
- Durable playbooks with conditions and approval gates; governed response
  actions with approvals ([limitations](docs/KNOWN_LIMITATIONS.md#response-and-automation)).
- 28 connector definitions with truthful health checks and a mock server.
- Real-time UI over server-sent events (short-lived stream tickets).
- 13 report types; JSON / CSV / HTML / PDF export.

**Platform security**, see [docs/SECURITY.md](docs/SECURITY.md)
- TOTP two-step verification with recovery codes; organizations can require
  it, and the requirement binds provider staff entering the customer.
- HttpOnly cookie sessions with CSRF protection (tokens never reach page
  JavaScript), revocable server-side sessions, rotating refresh tokens with
  reuse detection, lockout, password policy, scoped expiring API keys.
- 56 permissions, 21 built-in roles, grant rules that prevent privilege
  escalation, per-tenant DEMO/LIVE operating modes.
- Keyed (HMAC) tamper-evident audit chain.
- Secret references only (tenant-confined `vault://`, HashiCorp Vault
  support); SSRF-safe egress policy.
- Horizontally scalable API: replicas coordinate through PostgreSQL (event
  fan-out, leader election with failover, serialised migrations).
- Hardened containers, Helm chart, Kubernetes manifests, ArgoCD, CI.

## Verified

148 backend tests pass on PostgreSQL 16 (146 on SQLite, where the two
cross-replica tests are skipped); migrations match the models; lint,
type-check and production build are clean; `npm audit` reports 0
vulnerabilities; 42 Playwright end-to-end runs pass on desktop, tablet and
phone; both images were built and the production stack was run with two API
replicas (cross-replica events, leader failover, 1.5 s shutdown with live
streams open). Details and what was **not** tested:
[docs/TESTING_REPORT.md](docs/TESTING_REPORT.md).

Read [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) before production
use, especially the response gateway section.

## Repository layout

```
apps/api/            FastAPI backend (Python 3.11, SQLAlchemy 2, Alembic)
apps/web/            Next.js 15 / React 19 console
infrastructure/      helm/, kubernetes/, argocd/
docs/                Documentation (index: docs/README.md)
docker-compose.demo.yml   Demo stack (SQLite, simulated data)
docker-compose.yml        Production-like stack (PostgreSQL)
.github/workflows/   CI: lint, tests on SQLite and PostgreSQL, migrations, web build, images
```

## Common commands

```bash
make demo          # demo stack in Docker
make dev           # API (:8000) + web (:3000) locally
make test          # backend tests + web type-check
make test-e2e      # Playwright (servers must be running)
make build         # production build validation
make demo-reset    # reset demo data (LIVE data untouched)
```

## License

Provided as-is for evaluation and internal use.
