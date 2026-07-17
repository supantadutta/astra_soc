# Security Architecture

## Trust model
All logs, emails, web pages, documents and threat-intel content are **untrusted**.
LLMs are advisory and sit outside the trust boundary. Deterministic controls
(detection, policy, RBAC, approval, audit) never depend on model output.

## AI / prompt-injection defenses (`services/injection.py`)
- Direct + indirect prompt-injection detection (pattern-based, flagged not trusted).
- DLP: secret and PII masking (AWS keys, JWTs, private keys, Slack tokens, SSNs,
  PANs, emails) before any external text enters a model context or is stored.
- External-content labeling: retrieved text is wrapped in an explicit
  `<untrusted_external_content>` boundary — never treated as instructions.
- Output schema validation: malformed model output is rejected at the boundary.
- Tool-call allowlists and argument validation via the tool broker.

## Action safety (`services/response.py`)
Every production-changing action passes, in order: schema validation → evidence
validation (requires a `CONFIRMED_FACT`) → confidence threshold → asset
criticality → blast-radius calculation → RBAC → OPA-compatible policy → approval
determination → dry-run → execution → post-action verification → rollback (when
reversible) → immutable audit.

Execution is authorized by a **short-lived action token** bound to tenant, user,
exact action, exact target, expiration, and request id. An LLM/agent can propose
an action but can never execute one.

## Authn / authz
- PBKDF2-HMAC-SHA256 password hashing (no plaintext, no reversible storage).
- JWT access + refresh tokens; API keys are stored hashed, shown once.
- RBAC on every route; ABAC attributes (allowed data classifications) on users.
- Tenant isolation on every operational query; cross-tenant retrieval prevented.

## Audit
Append-only, hash-chained audit log (`services/audit.py`). Each entry chains to
the previous; `GET /api/v1/audit/verify` recomputes the chain to detect tampering.

## Secrets
Never stored in the DB or browser. Referenced by URI (`vault://`, `env://`,
`file://`) and resolved through the secret-manager interface. Logs and prompts
are redacted; vector indexes never store raw secrets.

## Network / SSRF
Tools declare an egress allowlist and response-size cap; the broker signs
results (HMAC) for tamper-evidence.
