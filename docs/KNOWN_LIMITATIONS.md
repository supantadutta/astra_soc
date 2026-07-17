# Known Limitations

An honest account of what is fully wired versus scaffolded. The platform is a
genuinely working system in DEMO mode; this page is where we are candid about the
edges so nobody is surprised.

## Fully implemented and verified

- Backend-enforced DEMO/LIVE modes with data-scope separation and readiness gate.
- JWT auth, 14-role RBAC enforced on every route, tenant scoping.
- Deterministic detection matcher, alert→incident correlation, 15 seeded
  scenarios, continuous event generation, SSE live updates.
- Evidence-first AI schema (strict validation), 16 bounded agents, coordinator
  workflow graph, tool broker with read/response separation.
- Multi-LLM gateway with capability routing, **real** provider connectivity
  tests, circuit breakers, fallback, deterministic simulated reasoner, and
  independent verification.
- Policy-as-code engine, full response-action safety pipeline (dry-run, execute,
  verify, rollback, action tokens), approvals.
- 28 connector definitions with adapters, health checks, and an in-process +
  standalone mock server; read/write permission separation.
- Prompt-injection detection, DLP/secret masking, external-content labeling.
- Tamper-evident hash-chained audit log with verification.
- 12 report types with fact/inference separation and JSON/CSV/HTML/PDF export.
- Controlled-learning pipeline with human-approval gate.
- 25 frontend modules, all wired to the API and verified rendering in a browser.

## Scaffolded / simplified (production would extend)

| Area | Current state | Production path |
|------|---------------|-----------------|
| **Enterprise datastores** | ClickHouse, Neo4j, OpenSearch, Redpanda, Temporal, OPA, Vault are integration points reported as "not configured". The demo uses SQLite + an in-process bus/workflow/vector store. | Wire the env vars in `docker-compose.yml` / Helm values; swap the in-process implementations (interfaces are already in place). |
| **Live connector writes** | Message/ticket/webhook kinds (Slack, Teams, email webhook, generic REST SIEM/EDR, ServiceNow, Jira) perform a **real** live HTTP POST and report the true HTTP outcome (2xx→success, 4xx/5xx→failure — verified in `tests/test_connector_live_write.py` against the mock server). Endpoint-control vendors (CrowdStrike, Defender, …) still raise `NotImplementedError` rather than guessing a bespoke multi-step API. | Implement each endpoint-control vendor's action API; the base adapter and response gateway already report the true outcome and never fabricate success. |
| **Real LLM calls** | The OpenAI-compatible and Anthropic chat paths are implemented; only the simulated path is exercised without keys. | Add a provider with a secret reference and Test connectivity. |
| **Vector retrieval** | Lexical (term-frequency) retriever in the demo. | Replace `KnowledgeChunk.lexical_vector` with pgvector embeddings; the query interface is unchanged. |
| **Durable workflows** | Persisted in-process state machine that survives restart/approval delay. | Map onto Temporal (`ASTRASOC_TEMPORAL_HOST`); step semantics already match. |
| **OPA** | Built-in Python policy engine with an OPA-compatible input/decision shape. | Point `ASTRASOC_OPA_URL` at an OPA sidecar. |
| **PDF export** | Dependency-free built-in PDF writer (single text stream). | Swap in a full renderer (e.g. WeasyPrint) for rich layout. |
| **Secret manager** | Local env-var-backed resolver (`vault://`, `env://`, `file://` refs). | Point at HashiCorp Vault / AWS Secrets Manager; callers use references only. |
| **Go connector-gateway** | Directory reserved; the connector SDK is Python in this build. | Optional high-throughput Go service using the typed adapter contract. |
| **Rate limiting** | In-process per-IP limiter. | Back with Redis for multi-node. |

## Not included

- Real vendor credentials or live integration test results (none available).
- Load/performance/chaos testing.
- SSO/OIDC login UI (Keycloak-compatible backend hooks exist; the demo uses
  local password auth).

## Security note

The demo ships with well-known demo passwords and a random per-process JWT
secret. **Before any real deployment**, set `ASTRASOC_JWT_SECRET`, rotate all
demo accounts, and follow [PRODUCTION_READINESS](PRODUCTION_READINESS.md).
