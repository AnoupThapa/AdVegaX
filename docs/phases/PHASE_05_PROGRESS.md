# Phase 5 — Progress (Google Analytics 4, read-only)

Plan: `PHASE_05_PLAN.md` (approved 2026-10-19, A23, all recommendations; Q11 settled). One report per task; `PHASE_05_REPORT.md` follows task 5-09.

| Task | Status |
|---|---|
| 5-01 Step 0 on the demo property and one of your properties | ⏸ Waiting — needs the Google OAuth client (with the Analytics APIs enabled) and network access to Google's Analytics APIs (Q-5-9, option C) |
| 5-02 Analytics model, interface, read-only rule | ✅ Done — awaiting review |
| 5-03 Google Analytics sign-in, client, simulator | ✅ Done — awaiting review |
| 5-04 Discovery and linking rules | ✅ Done — awaiting review |
| 5-05 Daily import | ✅ Done — awaiting review |
| 5-06 Ongoing sync, quota pacing, health | ✅ Done — awaiting review |
| 5-07 Read API | Not started |
| 5-08 Web app | Not started |
| 5-09 Journey test, browser test, docs, report | Not started |

## 5-01 — Step 0 on the demo property and one of your properties

Waiting. It needs:
- in the existing Google Cloud project: the Google Analytics Data API and Admin API enabled, and `analytics.readonly` on the consent screen;
- a Google account with Viewer access to one of your GA4 properties (and, optionally, Google's demo account);
- network access to `analyticsdata.googleapis.com`, `analyticsadmin.googleapis.com`, `oauth2.googleapis.com` and `accounts.google.com`.

The rest of Phase 5 is built against Google's documentation and a GA4 simulator meanwhile.

## 5-02 — Analytics model, provider interface and read-only rule (2026-10-19)

**Completed**
- **Migration 0014** (additive) with three tenant tables:
  - `analytics_properties`: a linked GA4 property with its name, Analytics account, currency, time zone, status, history start and health;
  - `analytics_daily`: one row per property, day and view. The views are the property's total, each default channel group, and each source / medium / campaign. Rows hold sessions, engaged sessions, users, new users, key events, purchases and purchase revenue (exact amounts), plus Google's data-quality flags ("(other)" row, privacy thresholds, sampling, truncation);
  - `analytics_sync_state`: as for ad accounts.
- **Protection:**
  - forced row-level security and composite tenant keys on all three tables;
  - the scheduler's system role may read four columns of properties only (no names, figures or anything else);
  - removing a property removes its figures and sync state.
- **Rules held by the database:** a measure Google did not give is empty, never 0; counts and revenue cannot be negative; one row per property, day, view and value; a total row must use the total key.
- **Users are documented as per-day counts**, never added across days or views (Q-5-5).
- **`AnalyticsProvider` interface** (platform-neutral, D4): `read_property` and `read_daily` (every view for a date range), with record types for a property and a daily row.
- **Read-only static rule for analytics providers:**
  - only the report methods `runReport` and `batchRunReports`, and plain reads for discovery;
  - never `analytics.edit` or the full `analytics` permission;
  - no PATCH, PUT or DELETE;
  - no write capability.

  It is tested against examples of forbidden calls.
- **Docs:** `DATABASE_SCHEMA.md` §12 describes the tables as built; the old `analytics_events` outline is marked superseded by Q11, not deleted.

**Files changed** (9)
- New (4): `alembic/versions/0014_analytics.py`, `app/domains/analytics/{__init__,models}.py`, `tests/security/test_analytics_data.py` (17 tests).
- Modified (5): `app/db/models.py`, `app/providers/base/{types,interfaces}.py`, `tests/security/test_static_rules.py` (3 new tests), `docs/DATABASE_SCHEMA.md`, and this report.
- Deleted: none.

**Tests**
- **20 new.**
- **Backend `make check`: 1,321 passed**, coverage 97 %. Migration up and down tested.
- **Frontend:** no changes.

**Security**
- Tenant isolation is enforced by the database for every new table (tested as the runtime role).
- The scheduler cannot read property names or any figure.

**Deviations**
1. **Postgres limits names to 63 characters,** so the per-organization unique key on properties is named `uq_analytics_properties_org_provider_external_id`.

**Blocked:** Step 0 (5-01): needs the Google OAuth client with the Analytics APIs enabled, and network access to Google's Analytics APIs.

**Next task:** 5-03 — the Google Analytics sign-in (shared with the Google Ads sign-in code), the Admin and Data API client (quota, errors, paging), and the GA4 simulator.

## 5-03 — Google Analytics sign-in, API client and simulator (2026-10-19)

**Completed**
- **One Google sign-in for both Google products.** The Google sign-in code from Phase 3 now lives in one shared place (`providers/google`): PKCE, offline access, the account-id check, refresh before expiry and revocation on disconnect. Google Ads uses it unchanged (all 225 Google Ads tests pass), and Google Analytics uses the same code with its own permission.
- **Google Analytics connection:** "Connect Google Analytics" asks only for `analytics.readonly` (plus Google's account id). It uses the same Google Cloud OAuth client as Google Ads and needs no developer token.
  - The same Google account connected to Google Ads and to Google Analytics is **two separate connections**; disconnecting one leaves the other working (tested).
  - A refused refresh shows "Needs reconnecting"; reconnecting with the same Google account reuses the connection.
  - The sign-in renews itself, so no end date is shown (unlike Meta).
- **GA4 API client** with a **read-only gate**: every request passes one check that allows only the discovery reads (account summaries, one property, metadata) and the report methods (`runReport`, `batchRunReports`). Anything else (editing a property, access reports, realtime, alpha versions, other hosts) is refused before it is sent. A static test checks the gate is the only way out.
- **Google's errors in plain codes:**
  - sign-in rejected → "Needs reconnecting";
  - the Analytics APIs are not enabled in the Google Cloud project → a set-up problem;
  - the permission is missing;
  - no access to a property;
  - a property's quota is used up → only that property waits;
  - a bad request; Google's temporary errors are retried.

  Google's own messages never travel on.
- **Quota:** every report asks Google for the property's remaining allowance (per day, per hour, per project per hour), and the client keeps the latest figures for pacing in 5-06.
- **GA4 simulator** for tests, which:
  - shares the Google sign-in with the Google Ads simulator;
  - offers account summaries with paging, a property's details (a property in the bin is marked), and batch reports with Google's quota block;
  - refuses unknown or expired tokens, a missing permission, a project without the APIs enabled, and tokens in addresses.

**Files changed** (20)
- New (9): `app/providers/google/{__init__,oauth}.py`, `app/providers/google_analytics/{__init__,client,provider}.py`, `tests/google_oauth_sim.py`, `tests/ga4_sim.py`, `tests/providers/test_google_analytics_client.py` (50 tests), `tests/api/test_google_analytics_connect.py` (12 tests).
- Modified (11): `app/providers/google_ads/{client,provider}.py` (now use the shared sign-in; their old names still work), `app/core/settings.py` (`GOOGLE_ANALYTICS_ENABLED`, `GOOGLE_ANALYTICS_API_VERSION`), `app/providers/base/registry.py`, `tests/google_ads_sim.py` (sign-in moved to the shared simulator), `tests/security/test_static_rules.py` (1 new rule; the shared folder is checked by both read-only rules), `.env.example`, docs `INTEGRATION_GUIDES.md`, `SECURITY.md`, this report and `PROJECT_STATUS.md`.
- Deleted: none. No migration.

**Tests**
- **63 new.**
- **Backend `make check`: 1,384 passed**, coverage 97 % (GA4 client 99 %, provider 100 %, shared sign-in 99 %).
- **Frontend:** no changes (Google Analytics is off by default; its wording comes in 5-08).

**Security**
- The edit permission is never requested. The read-only rule is strict enough that it flagged a docstring naming it, which was reworded.
- The token travels only in the `Authorization` header (tested on every request); property ids are checked before they enter an address.
- No token or the client secret appears in responses, the audit log or the logs (tested).

**Deviations**
1. **The shared OAuth client keeps its Google Ads setting names** (`GOOGLE_ADS_CLIENT_ID` / `_SECRET`) so nothing already set up changes; the settings and `.env.example` say it is shared.
2. **In the simulator, a refresh now returns the permissions granted at sign-in** (it used to return the Google Ads permission every time). Google Ads tests are unaffected.

**Blocked:** Step 0 (5-01): needs the Analytics APIs enabled in the Google Cloud project, a Google account with access to a GA4 property, and network access to Google's Analytics APIs.

**Next task:** 5-04: finding properties by Analytics account (account summaries, each property's currency and time zone), the reasons a property cannot be linked, and linking.

## 5-04 — Finding and linking Google Analytics properties (2026-10-19)

**Completed**
- **Properties are found by Analytics account.** After connecting, AdVegaX lists every GA4 property the Google account can see, grouped under its Analytics account name (for example "Eve Zone" → "Eve Zone AU", "Eve Zone NZ"), each with its currency and time zone.
- **Properties that cannot be linked say why**, in plain words, and the Link button is refused (409):
  - the currency or time zone cannot be read ("property details missing");
  - the property is in Google's bin ("property deleted");
  - Google refused to show its details ("no access to this property") — the other properties carry on.
- **Rediscovery** updates names, account groups and reasons and keeps existing links; a property that is no longer listed is shown as no longer accessible.
- **Edge cases:** large accounts are read page by page (200 accounts a page); discovery stops at 500 properties; a Google account with no Analytics access finds nothing and stays connected; the Analytics APIs not enabled in the Google Cloud project shows as a set-up error; a sign-in Google no longer accepts shows "Needs reconnecting".
- **Reading one property** (name, currency, time zone, deleted or not) is ready for the import in 5-05.
- Linking an available property works now; the analytics property record and the 13-month import start on link in 5-05.

**Files changed** (6)
- New (2): `app/providers/google_analytics/mapping.py`, `tests/api/test_google_analytics_discovery.py` (14 tests).
- Modified (4): `app/providers/google_analytics/provider.py`, `tests/ga4_sim.py` (per-property errors), `tests/providers/test_google_analytics_client.py` (placeholder test updated), docs `INTEGRATION_GUIDES.md`, this report and `PROJECT_STATUS.md`.
- Deleted: none. No migration.

**Tests**
- **14 new** (64 GA4 provider and discovery tests pass).
- **Backend `make check`: 1,398 passed**, coverage 97 %.

**Security**
- Discovery is read-only (account summaries and property details, through the gate); Google's messages never travel on; property ids are checked before they enter an address.
- Properties belong to the connection's organization only (the existing resource rules and RLS apply).

**Deviations:** none.

**Blocked:** Step 0 (5-01) — unchanged.

**Next task:** 5-05 — daily import: 13 months, monthly slices, three views, data-quality flags, exact money, property time zone.

## 5-05 — Importing a property's daily figures (2026-10-19)

**Completed**
- **Linking a Google Analytics property starts its import.** AdVegaX creates the property (name, Analytics account, currency, time zone), checks it with Google, then reads **13 months of daily figures, one calendar month per step** (about 14 Google calls). Each call holds all three views:
  - the property's **total** for each day;
  - **by channel** (Organic Search, Paid Search, …);
  - **by source / medium / campaign** (for example google / cpc / Spring Sale).
- **Figures kept per day:** sessions, engaged sessions, users, new users, key events, purchases and purchase revenue — exact amounts in the property's currency, on the property's own days (a Los Angeles property ends a day later than a Sydney one).
- **Users are never added up.** The day's users come from Google's own count for that day (11 people, even if channels show 8 + 4, because one person can arrive twice).
- **Nothing is invented:** a value Google does not give is unknown, never 0. A day with no activity at all is a real zero in the total only.
- **Refunds:** Google's purchase revenue is purchases minus refunds, so a day can be negative; it is stored exactly as reported (small migration 0015).
- **Google's data-quality notes are kept on every row:** rare values grouped into "(other)", rows withheld for privacy, sampling, truncation. They will be shown on the property page (5-08).
- **Very busy properties:** large views are read page by page; the source view keeps the 500 biggest values a day and adds the rest into one marked "(other)" row (its users are left unknown rather than added up).
- **Each read replaces the days it covers**, so Google's late corrections never leave old numbers. Linking a property again re-reads the last 14 days.
- **Problems in plain words, for that property only:** deleted in Google Analytics; no longer readable; currency or time zone changed in Google (recorded, figures not converted); Google's quota for the property used up → that property pauses 15 minutes and continues by itself, without using a retry, while other properties carry on.

**Files changed** (19)
- New (4): `app/domains/analytics/importer.py`, `alembic/versions/0015_analytics_refunds.py`, `tests/providers/test_google_analytics_reports.py` (15 tests), `tests/api/test_google_analytics_import.py` (13 tests).
- Modified (15): `app/providers/google_analytics/{mapping,provider}.py`, `app/domains/analytics/models.py`, `app/domains/integrations/service.py` (link starts the import), `app/workers/job_tasks.py`, `app/core/settings.py` (`ANALYTICS_*` import settings), `tests/ga4_sim.py` (sample traffic and Google-style reports), `tests/providers/test_google_analytics_client.py`, `tests/security/test_analytics_data.py` (1 new test, 1 case changed), docs `DATABASE_SCHEMA.md`, `INTEGRATION_GUIDES.md`, this report, `PROJECT_STATUS.md`.
- Deleted: none.

**Tests**
- **29 new.**
- **Backend `make check`: 1,427 passed**, coverage 96 % (importer 86 %: the 3-hour and weekly branches are used from 5-06).
- Frontend: no changes.

**Security**
- Reads only, through the read-only gate. Tokens never appear in the audit log or the logs (tested).
- All three tables keep forced row-level security; the import runs under the property's own organization.

**Migration:** `0015_analytics_refunds` drops the "revenue ≥ 0" check on `analytics_daily.purchase_revenue` only. Additive and safe; downgrade restores the check.

**Deviations**
1. **Migration 0015** (the plan named only 0014): Google's purchase revenue is net of refunds and can be negative, which 0014 refused. The security test that expected a refusal now checks a negative key-event count instead, and a new test checks negative revenue is stored.
2. **Source and medium are read as two dimensions** (`sessionSource`, `sessionMedium`) instead of the combined `sessionSourceMedium` in the plan, so they are stored in their own columns as the data model defines.
3. **The source view keeps 500 values a day** (setting `ANALYTICS_SOURCE_ROWS_PER_DAY`); the plan said "capped" without a number.

**Blocked:** Step 0 (5-01) — unchanged.

**Next task:** 5-06 — sync and health: the 3-hour, nightly (14 days) and weekly (90 days) runs, "Sync now", quota pacing from Google's remaining allowance, and the property health messages.

## 5-06 — Keeping properties up to date, Google's limits and health (2026-10-20)

**Completed**
- **Properties stay up to date by themselves:**
  - every 3 hours: today and yesterday;
  - nightly: the last 14 days (Google's late data and changing key-event credit — tested: a correction Google makes to a day 10 days back is picked up overnight);
  - weekly: the last 90 days.

  Each run reads the property's details first, and properties come due at their own times, so runs spread over the day. Unlinked properties, disconnected Google accounts and first imports still running are left alone.
- **"Sync now"** (the button arrives in 5-08): re-reads the last 14 days, or restarts a first import that failed. It is limited to 6 an hour per property, refused while a run is going, and recorded in the audit log.
- **Google's limits (Q-5-7):** every report tells AdVegaX how much of the property's hourly and daily allowance is left.
  - Below a quarter: each step waits 2 minutes (slower, never stopped).
  - Below a tenth: the property pauses until just after the next full hour and continues by itself. Its page will say "Google is limiting how much AdVegaX can read — figures will update later".
  - Google's "quota used up" answer pauses it 15 minutes the same way.

  No retry attempt is used, figures already imported stay visible, and other properties carry on. AdVegaX's share of the hour (14,000 tokens) is watched as well as the property's (40,000).
- **Health on the property, in plain words:** no access any more, deleted in Google Analytics, currency or time zone changed, Google limiting reads. Each clears by itself when the property answers normally again. A Google sign-in that is no longer accepted shows "Needs reconnecting" on the connection, and its properties wait until it is reconnected.
- **Fix:** a Google error status in the GA4 client from 5-03 was read by the web app's error-code check as an AdVegaX code (the frontend check failed; I had not run it in 5-03 because the frontend had not changed). It is now written so the check skips it, and the frontend check passes.

**Files changed** (16)
- New (1): `tests/api/test_google_analytics_sync.py` (31 tests).
- Modified (15): `app/domains/analytics/importer.py` (schedule, "Sync now", pacing, health), `app/providers/google_analytics/{client,provider}.py` (remaining allowance kept per property), `app/providers/base/{types,interfaces}.py` (`AnalyticsQuotaLeft`, optional `quota_left`), `app/core/settings.py` (`ANALYTICS_*` intervals and pacing, `THROTTLE_ANALYTICS_PROPERTY_RESYNC_PER_HOUR`), `app/workers/{job_tasks,celery_app}.py` (scheduled task every 5 minutes), `frontend/lib/api/errors.ts` (message for `ANALYTICS_PROPERTY_NOT_SYNCING`), `tests/providers/test_google_analytics_reports.py` (2 tests), docs `INTEGRATION_GUIDES.md`, `SECURITY.md`, this report, `PROJECT_STATUS.md`.
- Deleted: none. No migration.

**Tests**
- **33 new.**
- **Backend `make check`: 1,460 passed**, coverage 97 % (importer 91 %).
- **Frontend `npm run check`: 370 passed** (lint, types, unit tests).

**Security**
- The scheduler reads only four columns of other organizations' properties (tested: the property name is refused); everything else runs under each property's own organization.
- Reads only; no token in logs or the audit log.

**Deviations**
1. **The plan said "below 10 % … waits until the window moves on".** I paused until the next full hour for both the hour and the day: Google does not say when a property's day starts again, so a low day is checked again hourly (one small report each time) instead of guessed.
2. **Slowing down below 25 %** (2 minutes between steps) is added, as Q-5-7 says "slows down and pauses".

**Blocked:** Step 0 (5-01) — unchanged.

**Next task:** 5-07 — read API: the properties list and page, daily figures in three views with period totals (users per day only), derived rates with reasons, data-quality and "still being processed" notes, and "Sync now".
