# ASTRASOC

**Autonomous Security Operations & Cognitive Response Platform**

An AI-native Security Operations Center: a workflow-first, agent-assisted command
center that ingests alerts, correlates them into incidents, investigates with
multiple LLMs, and executes **governed** response through a policy + approval
gateway — with backend-enforced DEMO/LIVE modes, RBAC, and a tamper-evident
audit trail.

> **Design principle:** LLMs are *advisory*. They never replace deterministic
> detections, policy decisions, authorization, or response execution. Every
> trust-bearing control is enforced server-side and audited.

---

## Quick start (DEMO mode — zero credentials)

```bash
docker compose -f docker-compose.demo.yml up --build
```

- Web command center → <http://localhost:3000>
- API + OpenAPI docs → <http://localhost:8000/api/docs>

Or run locally without Docker:

```bash
# Terminal 1 — API (Python 3.11+)
cd apps/api && pip install -r requirements.txt && uvicorn astrasoc.main:app --port 8000

# Terminal 2 — Web (Node 20+)
cd apps/web && npm install && npm run dev
```

### Demo accounts (password `Demo!Pass123`)

| Role | Email | Can do |
|------|-------|--------|
| Platform Super Admin | `admin@astrasoc.io` | Everything |
| SOC Manager | `manager@acme.io` | Approvals, detection sign-off, RBAC, mode switch |
| Incident Commander | `commander@acme.io` | Lead response, approve actions |
| Tier-3 Analyst | `t3@acme.io` | Execute approved actions, write detections |
| Tier-1 Analyst | `t1@acme.io` | Triage, acknowledge, promote alerts |
| Auditor | `auditor@acme.io` | Read-only audit & oversight |
| Read-only Executive | `exec@acme.io` | Dashboards & reports |

The DEMO profile seeds **15 realistic attack scenarios**, generates live events
continuously, and runs the full investigation → response workflow with a
built-in **simulated reasoner** so everything works with no external LLM.

---

## What's actually implemented

This is a working platform, not a UI mock. Verified end-to-end (see
[`docs/TESTING_REPORT.md`](docs/TESTING_REPORT.md)):

- **Backend-enforced DEMO/LIVE modes** — mode is server state; data is scoped
  (`DEMO`/`LIVE`) and never mixed; LIVE requires an admin, explicit confirmation,
  and passing readiness checks.
- **Deterministic detection + correlation** — alerts fuse into incidents with
  entities, evidence, timeline, and a claim-evidence graph.
- **Multi-LLM gateway** — capability-based routing across OpenAI / Azure /
  Anthropic / Gemini / Bedrock / vLLM / Ollama / OpenAI-compatible, with **real
  connectivity tests** (never fake success), circuit breakers, fallback, and
  independent verification. A deterministic simulated reasoner keeps the platform
  usable when every external provider is down.
- **16 bounded specialist agents** + a coordinator workflow graph, a **tool
  broker** with strict read-only/response separation, and **evidence-first**
  JSON output (a claim without valid evidence can never trigger a response).
- **Response gateway** — every production-changing action passes: schema →
  evidence → confidence → asset criticality → blast radius → RBAC → policy (OPA-
  compatible) → approval → dry-run → execute → verify → rollback → immutable
  audit. Bound by short-lived action tokens.
- **28 connectors** with real adapters, health checks, and a built-in mock
  server; read/write permission separation.
- **RBAC** (14 roles) enforced on every API route; tenant isolation.
- **Prompt-injection & DLP defenses**, external-content labeling, secret masking.
- **Controlled learning** pipeline (feedback → review → dataset → offline eval →
  human approval); the platform never self-modifies production.
- **Reporting** (12 report types) with evidence citations and fact/inference
  separation; export to JSON/CSV/HTML/PDF.
- **Tamper-evident audit log** (hash-chained, verifiable).

See [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) for an honest account
of what is scaffolded vs. fully wired.

---

## Repository layout

```
astrasoc/
├── apps/
│   ├── api/            FastAPI backend (models, auth, AI gateway, agents,
│   │                   policy, response gateway, connectors, 105 endpoints)
│   └── web/            Next.js command center (25 modules, ECharts, React Flow)
├── infrastructure/     docker / kubernetes / helm / argocd
├── docs/               Full documentation set
├── docker-compose.demo.yml   Zero-dependency demo stack
├── docker-compose.yml        Postgres + Redis dev/prod-like stack
├── Makefile
└── .env.example
```

## Common commands

```bash
make demo          # docker demo stack
make dev           # run API + web locally
make test          # backend pytest + web typecheck
make test-e2e      # Playwright end-to-end (servers must be running)
make build         # production build validation
make demo-reset    # reset & reseed DEMO data (LIVE data untouched)
```

## Technology

**Frontend:** Next.js 14, React 18, TypeScript, Tailwind, Apache ECharts,
React Flow, Server-Sent Events, PWA.
**Backend:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic.
**Datastores:** SQLite (demo) / PostgreSQL (prod), Redis (optional), and
first-class integration points for ClickHouse, Neo4j, OpenSearch, Redpanda,
Temporal, OPA, and Vault — reported honestly as "not configured" until wired.

## Documentation

Start with [`docs/QUICKSTART.md`](docs/QUICKSTART.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Full index in
[`docs/README.md`](docs/README.md).

## License

Provided as-is for evaluation and internal use.
