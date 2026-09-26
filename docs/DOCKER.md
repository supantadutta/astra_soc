# Docker

## Demo (zero credentials)

```bash
docker compose -f docker-compose.demo.yml up --build
```

- Web: <http://localhost:3000> (demo accounts are listed on the sign-in page;
  password `Demo!Pass123`).
- API docs: <http://127.0.0.1:8000/api/docs> (published on localhost only).

SQLite in a named volume, simulated telemetry, the built-in AI reasoner and
mock connectors. **Never expose the demo profile to an untrusted network**:
the demo passwords are public.

Reset demo data: Demo Control Center → Reset, or `make demo-reset`.

## Production (single host)

Create `.env` next to `docker-compose.yml` (never commit it):

```bash
POSTGRES_PASSWORD=$(openssl rand -hex 24)
ASTRASOC_JWT_SECRET=$(openssl rand -base64 48)
ASTRASOC_AUDIT_KEY=$(openssl rand -base64 48)
ASTRASOC_BOOTSTRAP_ADMIN_EMAIL=secops-admin@your-company.com
ASTRASOC_BOOTSTRAP_ADMIN_PASSWORD='<a strong password>'
ASTRASOC_PUBLIC_URL=https://soc.your-company.com
```

```bash
docker compose up -d --build
```

What the compose file does:

- Refuses to start if any required secret is missing (`${VAR:?}`).
- Runs PostgreSQL 16 with a named volume. Neither the database nor the API is
  published on the host; only the web tier's port 3000 is.
- The API auto-migrates, runs as uid 10001 with a read-only root filesystem
  and `no-new-privileges`, and becomes healthy only when the database is
  reachable. The web tier waits for it.
- The web tier proxies `/api/*` to the API at runtime and forwards the client
  IP from your reverse proxy (`WEB_TRUST_FORWARDED_FOR=true`).

Put a TLS-terminating reverse proxy (nginx, Caddy, Traefik, a cloud load
balancer) in front of port 3000. It must set `X-Forwarded-For`, and must not
buffer `text/event-stream` responses (for nginx: `proxy_buffering off` on
`/api/v1/stream`). If clients reach port 3000 directly, set
`WEB_TRUST_FORWARDED_FOR=false`.

Mock integration server for connector contract tests:

```bash
docker compose --profile mocks up mockserver
```

## Images

| Image | Base | User | Notes |
|-------|------|------|-------|
| `apps/api` | `python:3.11-slim` | 10001 | No OS packages added; stdlib health check; bounded graceful shutdown. |
| `apps/web` | `node:20-slim` | 1001 | Next.js standalone output; API location read at runtime, so one image serves every environment. |
