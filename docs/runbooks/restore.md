# Runbook — Backup and restore drill

Phase 15 (Q-15-8). Daily managed backups with point-in-time recovery, kept 35 days.

## Drill (on staging, at least once before go-live, then every quarter)

1. Note the time **T** and a known record (e.g. the newest audit-log entry).
2. Restore the database to a **new** database at T (the provider's point-in-time restore).
3. Point a separate copy of the API at it (`fly secrets set` on a scratch app, or locally), with the **same `ENCRYPTION_KEYS`**.
4. Check: `alembic current` is the latest revision; `/api/v1/health/ready` answers ok; sign in; the known record is there; a connection's credentials still decrypt (open the connection page — status is shown, never the secret).
5. Record how long the restore took and anything that failed in `PHASE_15_REPORT.md`; delete the scratch database.

## Real restore

Stop the worker and scheduler (`fly scale count worker=0 scheduler=0`), restore, switch `DATABASE_URL_*` secrets to the restored database, deploy, start the worker and exactly one scheduler. Tell customers what period was lost (if any).
