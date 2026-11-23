# Production readiness checklist

✅ done and verified in this audit · ⬜ to do · ⚠️ done but not verified here

## Must complete before the first paying customer

- ⬜ **Fix QA-003:** throttle, lockout and audit for the Admin two-step code.
- ⬜ **Fix QA-004:** upgrade certifi; CI security job green.
- ⬜ **Fix QA-005:** turn concurrent duplicate creates into 409 or the existing record, and check the other create endpoints.
- ⬜ **Fix QA-019:** raise test coverage of the action engine, campaign builder, Autopilot and provider writes.
- ⬜ **QA-001:** deploy to staging (Fly.io Sydney) from documented steps only, and note any manual step.
- ⬜ **QA-001:** run the backup restore drill (`docs/runbooks/restore.md`) and record how long it took.
- ⬜ **QA-001:** run the k6 load test at 10, 50 and 100 users on staging and record p95 and error rate.
- ⬜ **QA-001:** run the staging soak (Phase 15 plan).
- ⬜ **QA-001:** outside penetration test before payments are switched on.
- ⬜ **QA-001:** error tracking and alerting (Sentry or similar), plus uptime checks on `/health/ready`.
- ⬜ **QA-002:** connect a sandbox or test account for each platform (Shopify, WooCommerce, Google Ads, Meta, GA4, Stripe test mode, SES) and complete the platform app reviews and developer-token access.
- ⬜ Rotate every development key. Generate production `SECRET_KEY` and `ENCRYPTION_KEYS` in the secret store.

## Should complete before general availability

- ⬜ QA-006: signed-in LCP ≤ 2.5 s on the mobile profile.
- ⬜ QA-007: correlation id on every error.
- ⬜ QA-008: database outage returns 503.
- ⬜ QA-009: reporting currency checked against ISO 4217.
- ⬜ QA-010: Playwright run with reduced motion; animate transform only.
- ⬜ QA-011: admin list pagination.
- ⬜ QA-012: request body size checked while streaming, or an edge limit verified.
- ⬜ QA-013: no two-step code reuse.
- ⬜ QA-018: confirmation before suspending an organization.
- ⬜ QA-014, QA-015, QA-016, QA-017 (low).

## Already in place

- ✅ Deployed environments refuse insecure configuration (secret and encryption keys, cookies, CORS, HTTPS URLs, email backend, eager Celery, Stripe keys).
- ✅ Health and readiness checks. Readiness reports database and Redis failures (verified).
- ✅ Tenant isolation in the database (forced RLS) and in routes (verified by tests).
- ✅ Migrations apply from scratch and round-trip down and up (tested).
- ✅ Durable email outbox and job tables recover after a worker outage (verified).
- ✅ Secrets encrypted at rest, scrubbed from logs, absent from git history.
- ✅ CI: lint, types, tests with coverage gates, secret scan, dependency audits, e2e.
- ⚠️ Fly.io configs (two API machines, two web machines, health checks, memory limits): present, never deployed.
- ⚠️ Runbooks (deploy, incidents, keys, restore, Stripe): written, never exercised.
- ⚠️ Retention (90 days, audit logs 7 years): implemented and tested, not observed running at scale.
- ⚠️ Rollback: migrations have downgrades; the application rollback procedure in `deploy.md` is untested.
