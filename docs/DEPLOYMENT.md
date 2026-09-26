# Deployment

ASTRASOC is two containers plus PostgreSQL:

```
browser ──HTTPS──▶ reverse proxy / ingress
                     ├── /api/*  ──▶ api  (FastAPI, port 8000, ONE replica)  ──▶ PostgreSQL
                     └── /*      ──▶ web  (Next.js, port 3000, N replicas)
```

The web tier also contains a runtime `/api/*` proxy (it reads
`API_INTERNAL_URL` at start-up), so a single-host deployment can expose only
port 3000. In Kubernetes the ingress sends `/api` straight to the API, which
keeps real client IPs and avoids a hop for the live event stream.

| Option | Use for | Guide |
|--------|---------|-------|
| `docker-compose.demo.yml` | Evaluation, sales demos. SQLite, simulated data, demo accounts. | [DOCKER](DOCKER.md) |
| `docker-compose.yml` | Single-host production or pilot. PostgreSQL, no demo accounts. | [DOCKER](DOCKER.md) |
| Helm chart / plain manifests / ArgoCD | Kubernetes | [KUBERNETES](KUBERNETES.md) |

## Required configuration (production)

| Variable | Notes |
|----------|-------|
| `ASTRASOC_ENVIRONMENT=production` | Enables the start-up guard and HSTS; disables demo accounts. |
| `ASTRASOC_DATABASE_URL` | `postgresql+psycopg2://user:pass@host:5432/db` |
| `ASTRASOC_JWT_SECRET` | ≥ 32 random characters (`openssl rand -base64 48`). |
| `ASTRASOC_AUDIT_KEY` | ≥ 32 random characters, **different** from the JWT secret. Keep it outside the database; losing it means the existing audit chain can no longer be verified. |
| `ASTRASOC_BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | First platform administrator, created once when the database has no users. |
| `ASTRASOC_CORS_ORIGINS` | Your public URL, e.g. `https://soc.example.com`. `*` is refused. |
| `ASTRASOC_AUTO_MIGRATE=true` | Run `alembic upgrade head` at start-up. Otherwise run it yourself before starting; the API refuses to start on an outdated schema. |

The API refuses to start if any of these are unsafe, and prints exactly which
check failed.

## Recommended configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASTRASOC_TRUSTED_PROXIES` | (none) | CIDRs of your ingress / reverse proxy, so `X-Forwarded-For` is trusted for audit IPs and sign-in rate limiting. |
| `ASTRASOC_VAULT_ADDR`, `ASTRASOC_VAULT_TOKEN`, `ASTRASOC_VAULT_MOUNT` | (none), (none), `secret` | HashiCorp Vault KV v2 for `vault://` secret references. |
| `ASTRASOC_EGRESS_HOST_ALLOWLIST` | (none) | Comma-separated hosts or `.suffixes` connectors and LLMs may call. |
| `ASTRASOC_EGRESS_ALLOW_PRIVATE_NETWORKS` | `true` | Set `false` if no integrations live on private networks. |
| `ASTRASOC_AUTH_RATE_LIMIT_PER_MINUTE` | `20` | Raise if many analysts share one egress IP and sign in together. |
| `ASTRASOC_DEFAULT_MODE` | `DEMO` | Initial mode for new tenants. Each tenant switches to LIVE individually after its readiness checks pass. |
| `ASTRASOC_ALLOW_LIVE_MODE` | `true` | `false` hard-locks the deployment to DEMO. |
| `WEB_TRUST_FORWARDED_FOR` (web) | `false` | `true` only when a reverse proxy in front of the web tier sets `X-Forwarded-For`. |
| `API_INTERNAL_URL` (web) | `http://localhost:8000` | Where the web tier's `/api` proxy reaches the API. |

## Operations

- **Health:** `GET /api/v1/health/live` (process up) and
  `GET /api/v1/health/ready` (database reachable; returns 503 otherwise).
- **Scaling:** exactly one API replica (see Known Limitations); scale the web
  tier horizontally.
- **Upgrades:** with auto-migrate, deploy the new image; the API applies
  migrations before serving. Take a database backup first ([BACKUP](BACKUP.md)).
- **Shutdown:** the API bounds graceful shutdown to 10 s because live SSE
  streams never finish on their own; browsers reconnect automatically.
- **Audit integrity:** `GET /api/v1/audit/verify` periodically; alert if
  `verified` is false.
- **Backups:** PostgreSQL is the only stateful component. Back up
  `ASTRASOC_AUDIT_KEY` separately.
