# Backup & Recovery

## What to back up
- **Database** — the system of record (cases, evidence, audit, config).
- **Secret store** — Vault/Secrets Manager (out of band; never in the app DB).
- **Object storage** — raw/historical events (S3/MinIO) in production.

## PostgreSQL
```bash
# Backup
pg_dump -Fc -U astrasoc astrasoc > astrasoc_$(date +%F).dump
# Restore
pg_restore -c -U astrasoc -d astrasoc astrasoc_YYYY-MM-DD.dump
```
Schedule with a CronJob; keep encrypted, off-site copies; test restores.

## SQLite (demo)
The demo DB is a single file (`/data/astrasoc.db` in Docker). Copy it while the
app is stopped, or use `.backup` from the sqlite3 CLI. Demo data is disposable —
`make demo-reset` regenerates it.

## Audit integrity after restore
Run `GET /api/v1/audit/verify` — the hash chain confirms the audit log was not
altered in transit.

## RPO/RTO guidance
Set the pg_dump/CronJob interval to your RPO. For RTO, keep the latest dump and a
known-good image; `docker compose up` + restore recovers the platform quickly.
