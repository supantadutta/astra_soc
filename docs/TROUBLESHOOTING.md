# Troubleshooting

**Web can't reach the API (502 `upstream_unavailable`)**
The web tier's `/api` proxy reads `API_INTERNAL_URL` at start-up (Docker:
`http://api:8000`; local dev default: `http://localhost:8000`). Check the value
and that the API is healthy (`/api/v1/health/ready`).

**401 on every request**
Token expired or missing — log in again. The client auto-refreshes; if refresh
fails you're redirected to `/login`.

**Login fails with correct password**
- Demo accounts exist only in `demo`/`development`/`test` environments; the
  sign-in page lists them only when they exist.
- Five failures lock an account for 15 minutes.
- A suspended tenant cannot sign in.
- Production: the first admin comes from `ASTRASOC_BOOTSTRAP_ADMIN_EMAIL` /
  `_PASSWORD` and is created only when the database has no users.

**429 Too Many Requests at sign-in**
Sign-in is limited per client IP (`ASTRASOC_AUTH_RATE_LIMIT_PER_MINUTE`,
default 20). If many analysts share one egress IP, raise it; make sure
`ASTRASOC_TRUSTED_PROXIES` is set so the real client IP is used.

**API refuses to start in production**
The log names each failed check (weak or identical JWT/audit keys, SQLite,
`*` CORS, demo accounts, unsafe secret schemes, outdated schema). Fix them or
set `ASTRASOC_AUTO_MIGRATE=true` for the schema.

**403 `tenant_access_denied` after switching tenants**
Your grant expired or was revoked, or the customer switched provider access
off. The UI returns you to your home tenant automatically.

**403 `feature_not_in_plan`**
The customer's service tier does not include the feature. Change the tier or
add a contract override (Customers → Edit contract).

**Provider test says `not_configured`**
No secret resolved. Tenant references must be `vault://tenants/<slug>/…`.
With Vault, check the path and field. Without Vault, set the matching
environment variable, e.g. `ASTRASOC_SECRET_TENANTS_ACME_OPENAI_API_KEY` for
`vault://tenants/acme/openai#api_key`.

**Connector or provider URL rejected with `egress_blocked`**
The egress policy blocks metadata/link-local addresses always, loopback by
default, and anything outside `ASTRASOC_EGRESS_HOST_ALLOWLIST` when it is set.

**Connector test says `not_configured`/`unhealthy`**
Mock off but no base URL/secret → `not_configured`; auth rejected → `unhealthy`.
This is correct — the platform never fakes a healthy integration.

**Can't switch to LIVE mode**
Requires `mode:manage`, `ASTRASOC_ALLOW_LIVE_MODE=true`, `confirm=true`, and
passing readiness checks (needs an enabled non-mock connector). See the Settings
page readiness list.

**Live updates not appearing (header shows "offline")**
The client exchanges its session for a 60-second ticket
(`POST /api/v1/stream/ticket`) and opens `/api/v1/stream?ticket=…`. Proxies
must not buffer `text/event-stream` (nginx: `proxy_buffering off`). The client
reconnects automatically with backoff.

**Playwright can't find a browser**
Set `PLAYWRIGHT_CHROMIUM_PATH` or install browsers (`npx playwright install`).

**`no space left on device` in a container**
Remove build caches / old volumes; the SQLite demo DB is tiny, Postgres data grows.
