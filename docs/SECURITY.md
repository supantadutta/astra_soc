# Security Architecture

## Trust model

- Every trust-bearing control (authentication, tenant isolation, RBAC,
  entitlements, policy, approvals, audit) is enforced **by the API**. The web
  UI only hides what the API would refuse anyway.
- Logs, emails, alerts, documents, threat-intel and case text are
  **untrusted input**. LLMs are advisory, sit outside the trust boundary, and
  can never execute actions.
- A tenant is the isolation boundary. Every operational query is filtered by
  the acting tenant and that tenant's data scope (DEMO or LIVE).

## Identity, sessions and API keys

- Passwords: PBKDF2-HMAC-SHA256, never stored reversibly. Policy: at least 12
  characters with mixed character classes (`ASTRASOC_PASSWORD_MIN_LENGTH`).
- Lockout: 5 failed attempts lock the account for 15 minutes (configurable).
  Failed second-factor codes count too, and a correct password alone never
  resets the counter. Sign-in failures return one uniform message.
- **Browser sessions** live in cookies page JavaScript cannot read:
  `HttpOnly`, `SameSite=Strict`, `Secure` in production; the refresh cookie is
  sent only to `/api/v1/auth`. State-changing requests authenticated by
  cookie must echo a separate CSRF cookie in `X-CSRF-Token` (double-submit).
  CLIs and integrations use `Authorization: Bearer` or API keys, which are not
  subject to CSRF.
- Sessions are server-side. Each access token carries a session id checked on
  every request, so **logout, password change and revocation take effect
  immediately**. Users can list and revoke their own sessions.
- Refresh tokens rotate on every use. Replaying a superseded refresh token is
  treated as theft and revokes the whole session. The web client serialises
  refreshes (across tabs too). The one token superseded by the latest
  rotation is honoured once for 30 seconds
  (`ASTRASOC_REFRESH_REUSE_GRACE_SECONDS`, 0 disables): a browser that
  navigates mid-refresh never receives the rotated cookie, and without this
  window it was signed out as a suspected theft.
- API keys are stored hashed and shown once, require explicit scopes (never
  more than the creator holds), expire (1–365 days), are bound to the tenant
  that issued them, and re-check delegated access on every use.
- Suspended tenants cannot sign in or use existing sessions.

## Two-step verification (MFA)

- TOTP per RFC 6238 (verified against the RFC test vectors) with any standard
  authenticator app; ±30 s drift; a time step, once used, is never accepted
  again (replay protection).
- The TOTP secret is encrypted at rest (Fernet, key derived with HKDF from
  `ASTRASOC_DATA_ENCRYPTION_KEY`, or from the audit key). Ten single-use
  recovery codes are shown once and stored as salted PBKDF2 hashes.
- Sign-in with MFA is two steps. The password step returns a 5-minute
  challenge token that grants nothing but the second step.
- **Tenant policy:** an organization can require MFA. Its users must enroll at
  their next sign-in (a 15-minute enrollment token allows only that), and
  existing sessions without a second factor stop working. The requirement
  also binds **provider staff entering the customer, including their API
  keys**. An administrator cannot switch the requirement on without MFA on
  their own account. The provider may impose it on a customer, but cannot
  lift a requirement the customer set.
- Users disable MFA only with password + code (not where required); admins
  reset a lost device (sessions revoked, grant rules apply). All MFA events
  are audited.
- No MFA secrets, recovery hashes, password or key hashes are ever serialised
  by the API: the serializer drops those columns for every endpoint.
- Not provided: SSO/OIDC/SAML, WebAuthn/passkeys, SCIM (see Known
  Limitations).

## Authorization

- 56 fine-grained permissions; roles are sets of permissions. Checked on every
  route. See [RBAC](RBAC.md).
- **Grant rules:** nobody can create a role or assign a permission they do not
  hold themselves; wildcard, platform and provider permissions cannot be
  granted inside customer tenants.
- **MSSP delegation** (see [MSSP](MSSP.md)): provider staff act inside a
  customer with the customer's own role permissions minus platform/provider
  permissions, re-evaluated per request, attributed in the customer's audit
  trail. Customers can switch provider access off; only audited break-glass
  remains.
- **Entitlements:** plan features are enforced by the API
  (`403 feature_not_in_plan`).

## Evidence integrity

Analysts cannot create `confirmed_fact` evidence directly. Attesting a fact
requires `evidence:attest` and a source reference, and is audited with the
attester's identity. Model output is always labelled as inference.

## AI guardrails (model gateway)

Before any non-simulated model is called, the gateway applies the tenant's AI
switch and LLM strategy (`simulated`, `private`, `hosted`, `hybrid`,
`disabled`), the private-model-only setting, the plan's `external_llm`
entitlement, data-residency region, data-classification allowance (hybrid
keeps confidential/restricted data on private models), and provider daily and
tenant monthly token budgets. Case text is DLP-scrubbed, screened for prompt
injection and wrapped in an explicit `<untrusted_external_content>` boundary.
Evidence ids cited by the model are checked against the real case, so
invented citations are dropped.

## Secrets

- Never stored in the database or sent to the browser. Connectors and model
  providers store **references** only.
- Tenant-configurable references must be `vault://tenants/<tenant-slug>/…`
  (a tenant cannot point at another tenant's secrets). `env://` and `file://`
  are refused unless an operator explicitly enables them, and even then only
  for platform administrators.
- HashiCorp Vault KV v2 is supported (`ASTRASOC_VAULT_ADDR`,
  `ASTRASOC_VAULT_TOKEN`, `ASTRASOC_VAULT_MOUNT`).

## Outbound requests (SSRF)

Every connector and model-provider URL is checked at configuration time and
again (with fresh DNS resolution) at request time. Link-local and
cloud-metadata addresses, multicast and reserved ranges are always blocked;
loopback is blocked by default; private networks are allowed by default for
on-prem SIEM/EDR (`ASTRASOC_EGRESS_ALLOW_PRIVATE_NETWORKS=false` to block);
only `http`/`https`; redirects are not followed; an optional host allowlist
(`ASTRASOC_EGRESS_HOST_ALLOWLIST`) restricts destinations further.

## Audit

Append-only, **keyed** hash chain: each entry is signed with
HMAC-SHA256 over all of its fields and the previous entry's signature, using
`ASTRASOC_AUDIT_KEY` (kept outside the database). Someone with database write
access cannot edit, delete or insert entries without breaking verification.
Appends are serialised (PostgreSQL advisory lock). `GET /api/v1/audit/verify`
walks the whole chain and reports the first break.

## HTTP hardening

- Security headers on every API response (`nosniff`, `DENY` framing,
  `no-referrer`, permissions policy, COOP, a restrictive CSP, `no-store` on API
  data, HSTS in production). The web tier sets a CSP limiting scripts and
  connections to its own origin and forbidding framing.
- 5 MiB request-body limit.
- Rate limiting: authenticated traffic per credential, sign-in/refresh per
  client IP. `X-Forwarded-For` is honoured only from `ASTRASOC_TRUSTED_PROXIES`.
- Short-lived (60 s) single-purpose tickets authenticate the live event
  stream, so long-lived tokens never appear in URLs.

## Production guard

With `ASTRASOC_ENVIRONMENT=production` the API **refuses to start** if the JWT
secret or audit key is missing, weak, or identical to each other, if SQLite is
used (unless explicitly allowed), if CORS allows `*`, if demo accounts are
enabled, or if unsafe secret schemes are enabled. Demo accounts are never
created in production; the first administrator comes from
`ASTRASOC_BOOTSTRAP_ADMIN_EMAIL` / `ASTRASOC_BOOTSTRAP_ADMIN_PASSWORD`.

## Containers

Both images run as non-root users. The API image has no OS packages beyond the
Python base. The compose file and Kubernetes manifests use read-only root
filesystems for the API, drop all capabilities, disable privilege escalation,
and do not mount service-account tokens.

## Response actions

The response gateway is designed so that production-changing actions pass
schema, evidence, confidence, asset-criticality, blast-radius, RBAC, policy
and approval checks, then dry-run, execution, verification, rollback and audit,
with execution bound to a short-lived action token. Agents may propose actions
but never execute them.

**This component was not re-reviewed during the MSSP hardening pass.** See
[Known Limitations](KNOWN_LIMITATIONS.md) for the specific gaps (customer
approval routing is not enforced; actions are not metered). Obtain an
independent review before enabling LIVE-mode automated response.

## Reporting a vulnerability

Report privately to the maintainers; do not open a public issue.
