# Phase 15 — Progress (Production Readiness & Staging)

Plan: `PHASE_15_PLAN.md` (approved 2026-10-28, A34: Fly.io Sydney, Amazon SES, 90-day retention with audit logs 7 years, the rest as recommended).

| Task | Status |
|---|---|
| 15-01 Retention job; production settings check | ✅ Done |
| 15-02 Fly.io files (api, worker, scheduler, web); release migrations | ✅ Done |
| 15-03 CI: dependency, container and secret scans | ✅ Done |
| 15-04 Runbooks | ✅ Done (`docs/runbooks/`) |
| 15-05 k6 load-test script | ✅ Done (`scripts/load/`) |
| 15-06 Accounts and DNS **(you)**, then staging deploy | ⏸ Waiting for your Fly.io, database, Redis and Amazon SES accounts and a domain |
| 15-07 Restore drill, ZAP scan, load test, two-week soak **(you + me)** | ⏸ After 15-06 |
| 15-08 Final report and go-live checklist | ⏸ After 15-07 (this interim report: `PHASE_15_REPORT.md`) |
