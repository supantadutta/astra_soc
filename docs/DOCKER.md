# Docker Guide

## Images
- `apps/api/Dockerfile` — Python 3.11 slim, installs requirements, runs uvicorn,
  has a `/health` healthcheck.
- `apps/web/Dockerfile` — multi-stage Node 20 build producing the Next.js
  **standalone** bundle (small runtime image, non-root user).

## Compose
- `docker-compose.demo.yml` — api (SQLite volume) + web. Zero credentials.
- `docker-compose.yml` — postgres + redis + api + web + a mock integration server.

## Commands
```bash
docker compose -f docker-compose.demo.yml up --build   # demo
docker compose up --build                              # dev/prod-like
docker compose config                                  # validate
docker compose down -v                                 # stop + remove volumes
```

## Notes
- The web container proxies `/api/*` to the `api` service via Next.js rewrites.
- Set `ASTRASOC_JWT_SECRET` for the non-demo compose.
- Volumes hold the SQLite demo DB / Postgres data; exclude them from any archive.
