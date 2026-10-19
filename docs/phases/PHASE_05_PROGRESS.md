# Phase 5 — Progress (Google Analytics 4, read-only)

Plan: `PHASE_05_PLAN.md` (approved 2026-10-19, A23, all recommendations; Q11 settled). One report per task; `PHASE_05_REPORT.md` follows task 5-09.

| Task | Status |
|---|---|
| 5-01 Step 0 on the demo property and one of your properties | ⏸ Waiting — needs the Google OAuth client (with the Analytics APIs enabled) and network access to Google's Analytics APIs (Q-5-9, option C) |
| 5-02 Analytics model, interface, read-only rule | ✅ Done — awaiting review |
| 5-03 Google Analytics sign-in, client, simulator | Not started |
| 5-04 Discovery and linking rules | Not started |
| 5-05 Daily import | Not started |
| 5-06 Ongoing sync, quota pacing, health | Not started |
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

