# Architecture

## Overview

ASTRASOC is a monorepo with a FastAPI backend (`apps/api`) and a Next.js frontend
(`apps/web`). The backend is the **authority** for everything that must be
trustworthy; the frontend is a rich client that renders backend state and can
never bypass a control.

```
                          ┌─────────────────────────────────────────────┐
   Browser  ── HTTPS ──▶  │  Next.js (apps/web)                          │
   (SSE)                  │  25 modules · ECharts · React Flow · PWA      │
                          └───────────────┬─────────────────────────────┘
                                          │  /api/* (rewrite) + /stream (SSE)
                          ┌───────────────▼─────────────────────────────┐
                          │  FastAPI (apps/api)                          │
                          │  ┌────────────┬───────────┬───────────────┐  │
                          │  │ Auth/RBAC  │ Mode       │ Audit (chain) │  │
                          │  ├────────────┴───────────┴───────────────┤  │
                          │  │ Domain: alerts, incidents, entities,   │  │
                          │  │ evidence, timeline, hypotheses         │  │
                          │  ├────────────────────────────────────────┤  │
                          │  │ AI: model gateway · agents · tool      │  │
                          │  │ broker · evidence-first schema         │  │
                          │  ├────────────────────────────────────────┤  │
                          │  │ Governance: policy · approvals ·       │  │
                          │  │ response gateway · connectors          │  │
                          │  └────────────────────────────────────────┘  │
                          └───────┬───────────────┬──────────────┬──────┘
                                  │               │              │
                        PostgreSQL/SQLite   (optional)      External APIs
                                            Redis/Kafka/…    (LIVE only)
```

## The trust boundary

The most important architectural idea: **the LLM is outside the trust boundary.**

- Agents produce **evidence-first claims** validated against a strict schema.
- A claim becomes a **hypothesis** (labelled `MODEL_INFERENCE`), never a
  confirmed fact.
- Only an analyst can promote an inference to an `ANALYST_CONCLUSION`.
- A response action requires at least one `CONFIRMED_FACT`, must clear a
  confidence threshold, and must pass policy + approval — all evaluated in
  Python, independent of any model output.
- Agents reach tools only through the **tool broker**, which hard-blocks
  production-changing tools; those only run via the **response gateway**.

## Services (logical)

Implemented in-process in the demo profile for zero-dependency startup; each maps
cleanly onto a standalone service in production:

| Service | Module | Responsibility |
|---------|--------|----------------|
| Model gateway | `services/model_gateway` | Routing, provider adapters, verification |
| Agent orchestrator | `services/agents` | Bounded agent runs, coordinator graph |
| Tool broker | `services/tool_broker` | Controlled tool access, read/write split |
| Response gateway | `services/response.py` | Action safety pipeline, tokens, rollback |
| Policy engine | `services/policy` | OPA-compatible policy-as-code |
| Connector framework | `services/connectors` | Adapters, health, mock servers |
| Detection engine | `services/detection.py` | Deterministic matchers, Sigma, replay |
| Event bus | `services/events.py` | SSE fan-out (Redpanda in prod) |
| Workflow engine | `services/workflow.py` | Durable playbook state machine (Temporal in prod) |

## Real-time

The backend publishes events to an in-process bus; the browser subscribes via
Server-Sent Events at `/api/v1/stream?scope=DEMO|LIVE`. Events are scope-filtered
so a client only sees its mode's activity. In production the same `publish()`
calls target Redpanda/Kafka.

## Portability

Models use a custom `GUID` type (native UUID on Postgres, CHAR(36) on SQLite) and
a JSON type (JSONB on Postgres). A `TZDateTime` type keeps datetimes tz-aware on
SQLite. This lets the exact same schema run on the demo SQLite DB and a
production Postgres without change.
