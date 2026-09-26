# Production Readiness Checklist

Work through this before putting customer data on the platform.

## Enforced automatically

The API refuses to start in production unless these hold:

- [x] Strong `ASTRASOC_JWT_SECRET` and a different, strong `ASTRASOC_AUDIT_KEY`
- [x] PostgreSQL (not SQLite), schema at the latest migration
- [x] No wildcard CORS
- [x] Demo accounts disabled; unsafe secret schemes disabled

## You must do

- [ ] TLS in front of the platform; HSTS is sent by the API in production.
- [ ] `ASTRASOC_TRUSTED_PROXIES` set to your ingress/proxy network.
- [ ] Managed PostgreSQL with automated backups and tested restores.
- [ ] `ASTRASOC_AUDIT_KEY` backed up separately from the database.
- [ ] Vault (or another secret store you front with `vault://` references)
      configured; no plaintext credentials anywhere.
- [ ] `ASTRASOC_EGRESS_HOST_ALLOWLIST` set to the integrations you actually use.
- [ ] Bootstrap administrator signs in, changes the password, and creates
      named accounts; the bootstrap credentials are removed from the
      environment.
- [ ] Monitoring on `/api/v1/health/ready`, container restarts, and a periodic
      `GET /api/v1/audit/verify`.
- [ ] Ingress / WAF rate limiting in addition to the in-process limiter.
- [ ] Each customer: connectors tested (a real **Test connection**, not
      assumed), readiness checks green, then LIVE mode.

## Decide consciously (see Known Limitations)

- [ ] **Automated response in LIVE mode.** The response gateway was not
      re-reviewed in the MSSP hardening pass, and customer approval routing is
      not enforced. Get an independent review, or restrict `action:execute`.
- [ ] Run at least two API replicas (the Helm default) for zero-downtime
      rollouts and leader failover; size PostgreSQL for its role as the
      coordination point.
- [ ] Require two-step verification for your provider tenant (Organization →
      Sign-in security) and encourage or require it for customers. No SSO:
      put an identity-aware proxy in front if corporate SSO is required.
- [ ] External LLMs: which tiers/customers may use hosted models? Configure
      strategies, private-model-only and budgets per tenant.
- [ ] Penetration test and load test before general availability.
