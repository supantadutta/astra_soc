# Known Limitations

What is fully working, what is simplified, and what is not included. Read this
before committing ASTRASOC to a production service. Nothing here is hidden
elsewhere in the product; the UI states the same limits where they apply.

## Deployment topology

| Limitation | Impact | Mitigation / path |
|------------|--------|-------------------|
| **The API must run as a single replica.** The live event bus, SLA breach sweeper, rate limiter and demo generator are in-process. | No horizontal scaling of the API; a restart drops live streams (browsers reconnect automatically with a new ticket). The Helm chart and manifests enforce `replicas: 1` with a `Recreate` strategy. | Scale the web tier freely. For multi-replica API, move the bus to Redis/Kafka, the sweeper to a leader-elected worker and rate limiting to Redis or the ingress. |
| Rate limiting is in-memory per process. | Resets on restart. Authenticated traffic is limited per credential; login/refresh per client IP (`ASTRASOC_AUTH_RATE_LIMIT_PER_MINUTE`, default 20). | Also enforce limits at the ingress / WAF. Set `ASTRASOC_TRUSTED_PROXIES` so the real client IP is used. |
| Behind the web tier's `/api` proxy, the API sees the web container's address unless `WEB_TRUST_FORWARDED_FOR=true` and `ASTRASOC_TRUSTED_PROXIES` include the web tier. | Per-IP login limits and audit IPs would reflect the proxy. | The Kubernetes ingress routes `/api` straight to the API (real IPs preserved). The production compose file enables forwarding and expects a TLS reverse proxy in front of port 3000. |
| Optional enterprise datastores (ClickHouse, Neo4j, OpenSearch, Kafka/Redpanda, Temporal, OPA, Redis) are not wired. | PostgreSQL holds everything. Platform Health reports them as `not_configured`, never healthy. | The service interfaces are in place; each is an integration project. |

## Response and automation

| Limitation | Details |
|------------|---------|
| **The response-action gateway was not re-engineered in the MSSP hardening pass.** | It predates the delegation model and has not been re-reviewed against it. Specifically: the per-customer **`customer_approval_actions`** contract setting is stored and displayed but **not enforced** (actions are not routed to the customer for approval), and response actions are **not metered** for billing (the column reads 0). Treat LIVE-mode automated response as requiring an independent security review before production use; keep customers in DEMO mode or restrict `action:execute` until then. |
| Endpoint-control vendor actions | Vendor-specific containment APIs (CrowdStrike, Defender, …) raise `NotImplementedError` rather than guessing a bespoke API. Generic webhook, chat and ticketing writes perform real HTTP calls and report the true outcome. |
| Playbooks start manually | Runs are started by an analyst (optionally bound to an incident). There is no automatic trigger on incident creation. |
| Workflow engine | Durable in-database state machine (survives restarts and approval waits). Not Temporal. |
| Policy engine | Built-in Python engine with an OPA-compatible input/decision shape; no external OPA. |

## Identity and sessions

- **No SSO/OIDC/SAML and no MFA.** Local accounts only, with a password policy,
  lockout and revocable server-side sessions. Front the platform with an
  identity-aware proxy if SSO or MFA is required.
- Access and refresh tokens are held in the browser's `localStorage`. The CSP
  blocks third-party scripts and framing, but still permits inline scripts
  (needed by Next.js), so an XSS bug would expose tokens. Moving to
  `HttpOnly` cookies is the recommended next step.
- User provisioning is manual (no SCIM).

## AI

- Chat calls are implemented for Anthropic, Ollama and OpenAI-compatible
  endpoints (OpenAI, vLLM and other compatible servers). Other provider kinds
  in the catalog support connectivity tests but must expose an
  OpenAI-compatible API to be used for chat. These paths were exercised in
  tests only against a mocked provider; no real vendor API keys were used.
- Knowledge retrieval is lexical (term frequency), not vector embeddings.
- Prompt-injection detection is pattern-based. It flags and wraps untrusted
  content; it cannot guarantee a model will not follow injected text. That is
  why models are advisory and never execute actions.

## Integrations

- 28 connector definitions exist, plus a mock server for contract testing.
  **None has been tested against a real vendor environment.**
- Notifications are delivered through the tenant's own write-capable comms
  connector (email webhook, Slack, Microsoft Teams). There is no built-in SMTP.
  Without one, notifications stay in-app and record `not_configured`.
- Secrets: HashiCorp Vault KV v2 is supported (`ASTRASOC_VAULT_ADDR`,
  `ASTRASOC_VAULT_TOKEN`). Other secret stores (AWS Secrets Manager, Azure Key
  Vault) are not.

## Reporting

- The PDF export uses a dependency-free built-in writer with plain layout.
- Service reports cover one calendar month per customer.

## Not performed

- Load, soak and chaos testing.
- External penetration test.
- Tests against real vendor systems or real LLM APIs (see above).
- Accessibility audit (keyboard and screen-reader basics were addressed, not
  formally audited).
