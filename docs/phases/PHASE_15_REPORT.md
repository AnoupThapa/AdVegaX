# Phase 15 — Report (Production Readiness & Staging) — interim

**Status:** Tasks 15-01 … 15-05 done — awaiting your review. Tasks 15-06 … 15-08 need your accounts (§6); this report will then gain the staging results.
**Plan:** `PHASE_15_PLAN.md` (A34). **Progress:** `PHASE_15_PROGRESS.md`.

## 1. Summary

Everything needed to run AdVegaX on a staging server is now in the repository:

- **Deployment** for Fly.io in Sydney. One image runs the API, the background worker and exactly one scheduler; the web app is a second app. Database migrations run once per release.
- **Safer production settings.** A deployed AdVegaX refuses to start in two new cases: billing switched on without its Stripe keys, or a live Stripe key on staging. This is on top of the earlier checks.
- **Data retention**, off until you switch it on. A store, ad account or analytics property that has been unlinked for **90 days** is deleted with its imported data, and each deletion is audited. Audit logs are kept.
- **More CI checks.** Each push now also audits the web app's dependencies and scans both Docker images for serious, fixable vulnerabilities. This adds to the existing secret scan and Python dependency audit.
- **Runbooks** in `docs/runbooks/`:
  - deploy and roll back (with the list of secrets);
  - backup and restore drill;
  - key rotation;
  - incidents (including Australia's notifiable data breach scheme);
  - Stripe set-up.
- **A load-test script** (k6) for staging.
- **SECURITY.md** has the updated threat model for Phases 13–15.

## 2. Test results

| Suite | Result |
|---|---|
| Backend `make check` | ✅ 2,118 passed, coverage 95.35 % |
| Frontend / browser | Unchanged this phase (586 / 21 passing at Phase 14) |

New tests:

- `tests/api/test_retention.py` — the retention period, a resource linked again, audit, off by default, the schedule;
- the deployed-settings checks in `tests/unit/test_settings.py`.

## 3. Database

Migration **0026** (reversible) makes two narrow grants, both to the system role:

- read which resources are linked;
- delete an `external_resources` row, for the retention job only. The database's cascades then remove what was imported for it.

The app role still cannot delete integration rows (the Phase 1B security rule; its test caught a first version that gave that right to the app role).

## 4. Deviations from the plan

1. **Retention covers removed stores, ad accounts and properties.** AdVegaX has no "close organization" action yet, so there is nothing to delete for closed organizations. Deleting an organization's data would be added together with such an action.
2. **Audit logs:** nothing is deleted, because none can be older than 7 years before 2033. A clean-up can be added before then.
3. **Monitoring:** health checks and Fly.io's logs. Sentry is left out until you want it (optional in the plan).

## 5. Not yet done (needs staging)

Each of these is reported here once staging runs:

- the ZAP scan;
- the load test;
- the restore drill;
- the two-week soak, together with Step 0 for Phases 8–13;
- the outside penetration test.

## 6. Your checklist

**A. Decide or confirm:**

1. The domain names: for example `app.advegax.com` and `api.advegax.com`, with `-staging` versions.
2. The deviations in §4.
3. A penetration-test firm (ask for quotes; needed before taking payments).

**B. Set up (15-06), following `docs/runbooks/deploy.md` §1:**

1. A **Fly.io** account. Install `flyctl` on your computer (you already have a `.fly` folder).
2. A managed **Postgres in Sydney**: Fly Managed Postgres or Neon in AWS Sydney. I will check it supports the three AdVegaX roles before we use it.
3. **Upstash Redis** in Sydney.
4. **Amazon SES** in Sydney (`ap-southeast-2`):
   - verify your domain;
   - add the DKIM, SPF and DMARC records;
   - create SMTP credentials;
   - request production access.
5. Put every password and key only into Fly.io secrets, never in chat. Then tell me, and I deploy staging and run 15-07 with you.

**C. Documents to read:**

- this report;
- `docs/runbooks/` (deploy, restore, keys, incidents, stripe);
- SECURITY.md (the new section at the end);
- `.env.example` (the Retention block).
