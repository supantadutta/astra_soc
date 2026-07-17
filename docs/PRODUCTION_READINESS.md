# Production Readiness Checklist

## Must do before LIVE
- [ ] Set a strong `ASTRASOC_JWT_SECRET` (32+ random bytes).
- [ ] Rotate/disable all demo accounts; enforce SSO/OIDC or strong passwords.
- [ ] Use PostgreSQL (not SQLite); run `alembic upgrade head`.
- [ ] Put secrets in Vault/Secrets Manager; verify every `vault://` reference resolves.
- [ ] Configure at least one real, enabled, non-mock connector.
- [ ] Configure LLM providers (or disable AI) and Test connectivity.
- [ ] Review and tune the response policy (`SystemSetting['response_policy']`).
- [ ] Confirm approval roles match your org's authority model.
- [ ] Terminate TLS at the ingress; set exact CORS origins.
- [ ] Back rate-limiting with Redis if multi-node.
- [ ] Set up backups (DB + secrets) and test a restore.
- [ ] Wire observability (OTel → Prometheus/Grafana; logs → OpenSearch).

## Should do
- [ ] Implement real `execute_action`/`verify_action` for each connector you
      intend to use for response (see KNOWN_LIMITATIONS).
- [ ] Point durable workflows at Temporal; policy at OPA; retrieval at pgvector.
- [ ] Enable per-tenant budgets and private-model-only policies as needed.
- [ ] Add malware-scanning + file-type/size validation to any upload paths.
- [ ] Load-test ingestion and the response pipeline.

## Verify
- [ ] `make test` green; `make build` succeeds; `docker compose config` valid.
- [ ] `GET /api/v1/audit/verify` returns `verified: true`.
- [ ] Mode readiness checks pass before flipping to LIVE.
