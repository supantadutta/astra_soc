# Deployment Guide

## Profiles
- **demo** — SQLite, simulated LLM, mock connectors, no credentials.
  `docker compose -f docker-compose.demo.yml up --build`
- **development / production** — Postgres + Redis.
  `docker compose up --build`
- **Kubernetes / Helm / ArgoCD** — see [KUBERNETES](KUBERNETES.md).

## Environment variables (see `.env.example`)
| Var | Purpose |
|-----|---------|
| `ASTRASOC_ENVIRONMENT` | development / demo / production / test |
| `ASTRASOC_JWT_SECRET` | **required in production** |
| `ASTRASOC_DATABASE_URL` | SQLite or `postgresql+psycopg2://…` |
| `ASTRASOC_DEFAULT_MODE` | DEMO / LIVE startup default |
| `ASTRASOC_ALLOW_LIVE_MODE` | `false` hard-locks to demo |
| `ASTRASOC_REDIS_URL`, `_CLICKHOUSE_URL`, `_NEO4J_URL`, `_OPENSEARCH_URL`, `_KAFKA_BROKERS`, `_TEMPORAL_HOST`, `_OPA_URL`, `_VAULT_ADDR` | optional enterprise deps |
| `ASTRASOC_SECRET_*` | resolve `vault://`/`env://` secret references |
| `NEXT_PUBLIC_API_BASE_URL` | web → API base URL |

## Secrets
Never commit secrets. Provide provider/connector credentials via the secret
manager (env-var-backed locally; Vault/Secrets Manager in production). The app
stores only references.

## Production checklist
See [PRODUCTION_READINESS](PRODUCTION_READINESS.md).
