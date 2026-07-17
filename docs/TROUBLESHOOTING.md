# Troubleshooting

**Web can't reach the API**
Check `NEXT_PUBLIC_API_BASE_URL` and CORS (`ASTRASOC_CORS_ORIGINS`). In Docker the
web service proxies `/api/*` to `http://api:8000`.

**401 on every request**
Token expired or missing — log in again. The client auto-refreshes; if refresh
fails you're redirected to `/login`.

**Login fails with correct password**
Ensure the DB was seeded (it seeds on first boot). Reset with `make demo-reset`
or delete the SQLite file and restart.

**Provider test says `not_configured`**
No secret resolved. Set the env var matching your secret reference (e.g.
`ASTRASOC_SECRET_OPENAI_API_KEY` for `vault://openai#api_key`).

**Connector test says `not_configured`/`unhealthy`**
Mock off but no base URL/secret → `not_configured`; auth rejected → `unhealthy`.
This is correct — the platform never fakes a healthy integration.

**Can't switch to LIVE mode**
Requires `mode:manage`, `ASTRASOC_ALLOW_LIVE_MODE=true`, `confirm=true`, and
passing readiness checks (needs an enabled non-mock connector). See the Settings
page readiness list.

**SSE / live updates not appearing**
The stream is `/api/v1/stream?scope=DEMO`. Corporate proxies that buffer SSE can
delay events; the client also reconnects automatically.

**Playwright can't find a browser**
Set `PLAYWRIGHT_CHROMIUM_PATH` or install browsers (`npx playwright install`).

**`no space left on device` in a container**
Remove build caches / old volumes; the SQLite demo DB is tiny, Postgres data grows.
