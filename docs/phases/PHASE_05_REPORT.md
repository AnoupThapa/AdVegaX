# Phase 5 — Implementation Report (Google Analytics 4, read-only)

**Date:** 2026-10-20 · **Branch:** `feature/phase-1a` · **Status:** Implemented against the GA4 simulator — awaiting product-owner review. **Step 0 on Google's demo property and one of your properties (5-01) is still pending**: it needs the Google Analytics Data and Admin APIs switched on in the Google Cloud project, `analytics.readonly` on the consent screen, a Google account with access to a GA4 property, and network access to `analyticsdata.googleapis.com`, `analyticsadmin.googleapis.com`, `oauth2.googleapis.com` and `accounts.google.com`.
**Plan:** `PHASE_05_PLAN.md` (approved 2026-10-19, A23, all recommendations; Q11 settled) · Task-by-task reports: `PHASE_05_PROGRESS.md` (5-02 … 5-09).

---

## 1. Summary

An organization can now connect Google Analytics read-only and see its website's visits, key events, purchases and revenue next to its stores and its advertising. Concretely, it can:

- **connect** by signing in with Google (the same Google Cloud app as Google Ads, but its **own connection** asking only for `analytics.readonly`). The same Google account connected to Google Ads and to Google Analytics is two connections, and either can be removed alone;
- **see every GA4 property** the Google account can reach, grouped under its Analytics account, with its currency and time zone. Properties that cannot be used say why: deleted, no access, or no currency or time zone;
- **link** the properties it uses. Each one imports **13 months of daily figures in three views**:
  - the property's **total** per day;
  - **by channel** (Organic Search, Paid Search, …);
  - **by source / medium / campaign** (google / cpc / Spring Sale — what Phase 6 needs to match ad campaigns).

  Each day has sessions, engaged sessions, users, new users, key events, purchases and purchase revenue, exact, in the property's own currency and days;
- **stay up to date by itself:** every 3 hours today and yesterday; every night the last **14** days (Google's late data and changing key-event credit); every week the last 90 days. Each re-read replaces the days it covers. "Sync now" re-reads 14 days;
- **stay inside Google's limits:** every report tells AdVegaX how much of the property's hourly and daily allowance is left. Below a quarter AdVegaX slows down; below a tenth, or when Google says the quota is used up, that property pauses and continues by itself. Other properties carry on;
- **see the figures honestly:**
  - every figure is labelled "Reported by Google Analytics";
  - **users are never added up**: a day shows that day's users, a period says "Shown per day only" (one person visiting on two days counts once on each day);
  - the last 3 days are marked "still being processed by Google";
  - Google's notes travel with the figures: rare values grouped into "(other)", small numbers withheld for privacy, sampling, truncation;
  - revenue is purchases minus refunds, so a refund day can be negative — shown as Google reports it;
- recover from a **removed property access**, a **deleted property**, **Google's limits**, a **refused sign-in** ("Needs reconnecting"), **reconnect** (same connection, links and data) and **disconnect** (permission revoked at Google, figures still readable). None of this needs manual database work.

The same promises as Phases 3 and 4 hold:

- **Read-only.** Every request passes one gate that allows only the discovery reads (account summaries, a property, its metadata) and the two report methods. The edit permission is never requested. Static tests check both.
- **Platform-reported figures, labelled as such.** No comparison with store sales or ad spend yet (Phase 6). Google Analytics figures are never added to store or ad figures.
- **Missing data is never shown as 0.** A value Google does not give is unknown; a day not read is "Not synced yet"; a rate without sessions says "No sessions".
- **No token or the client secret is ever shown.** Tokens travel in the `Authorization` header only. Only Google's stable account id is kept; no user ids, client ids, IP addresses or demographics are requested.

Everything is built from Google's documentation (checked 2026-10-19) and tested against an in-process **GA4 simulator**:

- Google's sign-in, shared with the Google Ads simulator;
- the Admin API: account summaries with paging, a property's details (and the bin);
- the Data API: `batchRunReports` and `runReport` grouped by the dimensions asked for, ordered, paged with `offset`, values as strings, Google's quota block and data-quality metadata;
- Google's error format.

It has **not yet run against Google**; §9 lists what Step 0 must confirm.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 5-01 | ⏸ **Waiting:** needs the Analytics APIs and `analytics.readonly` in the Google Cloud project, a Google account with a GA4 property, and network access to Google's Analytics hosts |
| 5-02 | Analytics model (migration 0014): properties, daily aggregates in three views with data-quality flags, sync state; forced row-level security; the scheduler reads four columns only. `AnalyticsProvider` interface; read-only static rule |
| 5-03 | One Google sign-in shared by Google Ads and Google Analytics; the Google Analytics connection (`analytics.readonly` only); the Admin and Data API client behind a read-only gate; Google's errors as plain codes; quota kept; GA4 simulator |
| 5-04 | Discovery by Analytics account (account summaries with paging, each property's currency and time zone); plain reasons a property cannot be linked; rediscovery keeps links |
| 5-05 | Daily import on link: 13 months in monthly slices, one Google call per slice holding the three views; exact money, property days, users never added, real zeros in the total only, data-quality flags, paging, the source view capped at 500 values a day into a marked "(other)"; migration 0015 (revenue net of refunds can be negative) |
| 5-06 | Ongoing sync (3-hour, nightly 14 days, weekly 90 days), "Sync now", pacing from Google's remaining allowance, plain health codes that clear by themselves. Fix: the web app's error-code check (from 5-03) |
| 5-07 | Read API: properties, daily figures in three views with period totals, users per day only, derived rates with reasons, processing and data-quality notes, "Sync now"; `analytics.view` / `analytics.manage` |
| 5-08 | Web app: "Connect Google Analytics", properties grouped by Analytics account with reasons, the Analytics tab, the property page |
| 5-09 | Whole-journey simulator test, browser test with a simulated GA4 property and accessibility checks, browser-test helper, CI switch, security notes, this report |

## 3. Acceptance criteria (plan §16)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | A Google sign-in connects Google Analytics, discovers properties by Analytics account, links them, imports 13 months in three views, stays up to date, and handles a removed permission, a property without access, Google's quotas, reconnect and disconnect without manual database work | ✅ with the simulator · ⏸ on Google | `test_google_analytics_journey.py`: connect → discover by Analytics account → a property without a currency refused → link AUD and USD → import → 3-hour run → nightly correction → quota used up (pause, then continue) → property access removed → sign-in refused → reconnect → Sync now → disconnect. Also `test_google_analytics_{connect,discovery,import,sync}.py`, `test_analytics_properties_api.py`; browser: `google-analytics.spec.ts` |
| 2 | Daily figures match hand-calculated golden values in both currencies, and the GA4 interface for one property for a fixed settled week | ✅ golden values · ⏸ GA4 interface match | Golden values in AUD (Sydney) and USD (Los Angeles) through import, API and pages (sessions, Google's own users per day, A$170.45 and a −A$30.00 refund day, rates to six decimals). The GA4 interface match is Step 0 item 6 |
| 3 | Re-read days are replaced, with no stale or duplicated rows; users are never added across days | ✅ | `test_google_analytics_import.py` (re-read replaces its days in every view, duplicates stored once), `test_analytics_properties_api.py` ("users_per_day_only"), journey step 4 |
| 4 | No Google Analytics call that changes anything exists in the code; `analytics.edit` is never requested | ✅ | `test_static_rules.py` (one request gate, preceded by the read-only guard; the edit permission never named); journey check that every Analytics call was a discovery read or a report |
| 5 | Tokens and the client secret never appear in responses, logs, audit, UI or AI context | ✅ | Journey scan of every response, the audit log and the logs; API and browser page scans. No AI features use analytics data yet |
| 6 | Missing data is never shown as 0; thresholding, "(other)", sampling and truncation are shown; GA4 figures are never added to store or ad figures | ✅ | Import, API and page tests; the property page lists Google's notes per day and per period; the Analytics tab is separate from Stores and Advertising |
| 7 | All suites pass, with no calls to Google in CI | ✅ locally · CI on GitHub not yet run | §5. The simulator replaces the network; the browser helper refuses deployed environments; CI uses placeholder Google settings only to show the pages |

## 4. Security controls — how each is verified

| Control | Verified by |
|---|---|
| Read-only: one request gate allowing the discovery reads and the report methods only; the edit permission never requested; no write capability declared | `test_static_rules.py`, `test_google_analytics_client.py` (anything else refused before it is sent), journey |
| Sign-in: PKCE S256, offline access, single-use state bound to the person; code exchanged on the server; `analytics.readonly` required; refresh before expiry; revocation on disconnect | `test_google_analytics_connect.py` |
| Tokens only in the `Authorization` header; property ids checked before they enter an address; only Google's fixed hosts through the SSRF-safe client, no redirects | `test_google_analytics_client.py`; the simulator refuses tokens in addresses |
| Tokens encrypted at rest; never in responses, audit, logs or the web app | `test_google_analytics_connect.py`, journey scan, API and browser page scans |
| Google Ads and Google Analytics are separate connections; removing one leaves the other | `test_google_analytics_connect.py` |
| Per-property problems (no access, deleted, quota) never mark the connection; sign-in problems do | `test_google_analytics_sync.py`, journey steps 5–7 |
| Tenant isolation: forced RLS on the three new tables; the route sweeps cover the new routes; the scheduler reads four columns only | `test_analytics_data.py`, `test_tenant_isolation.py`, `test_google_analytics_sync.py` |
| No personal data: aggregates only; no user ids, client ids, IP addresses or demographics; Google's privacy thresholds respected and shown | Report request tests (only the seven metrics and four dimensions listed in `INTEGRATION_GUIDES.md`) |
| Test simulator and helpers never ship | `backend/tests` is excluded from the Docker image; the helper refuses staging and production |

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` | ruff, mypy --strict, **1,488 passed** (1,301 at the end of Phase 4), coverage **97 %** |
| Frontend unit/component (Vitest) | **387 passed** (370 at the end of Phase 4); ESLint, Prettier, strict types and API-type drift tests pass; build passes |
| End-to-end + accessibility (Playwright + axe) | **14 passed** (was 13). No serious or critical accessibility issues on the Connections page with Google Analytics, the Google Analytics connection page, the Analytics tab or the property page; no Google token on any page |

## 6. Database

- **0014_analytics** (5-02): `analytics_properties`, `analytics_daily` (three views, data-quality flags), `analytics_sync_state`; forced RLS; a four-column read for the scheduler.
- **0015_analytics_refunds** (5-05): drops the "revenue ≥ 0" check on `analytics_daily.purchase_revenue` only, because GA4's revenue is purchases minus refunds. Downgrade restores it.

Both are additive. The planned `analytics_events` table is marked superseded in `DATABASE_SCHEMA.md` (Q11: GA4 gives aggregates, not events).

## 7. Defects found during Phase 5 (all fixed)

- **5-02:** a unique-key name was longer than PostgreSQL's 63-character limit; renamed.
- **5-02:** a docstring naming the edit permission tripped the read-only static rule (as intended); reworded.
- **5-06:** a Google error status in the GA4 client (5-03) was read by the web app's error-code check as an AdVegaX code, so the frontend check had failed since 5-03. Fixed; the frontend check is now run after every task.
- **5-07:** the tenant-isolation sweep had no value for the new `{property_id}`; added, so the new routes are swept for non-members.
- **5-09:** the local development database had not been migrated past 0012, so the browser helper failed until it was migrated. CI migrates before its browser tests, so CI was never affected.

## 8. Deviations from the plan

Each task's deviations are listed in `PHASE_05_PROGRESS.md`. The ones that matter most for review:

1. **Migration 0015** (the plan named only 0014): revenue is purchases minus refunds and can be negative (5-05).
2. **Source and medium are read as two dimensions** (`sessionSource`, `sessionMedium`), not the combined `sessionSourceMedium`, so they are stored in their own columns (5-05).
3. **The source view keeps 500 values a day**; the rest go into one marked "(other)" row with users unknown (5-05). Breakdown answers return at most 500 values, 100 by default, with the full count (5-07).
4. **A low daily allowance pauses until the next hour** and is checked again hourly, because Google does not say when a property's day restarts (5-06). Slowing down below a quarter was added, as Q-5-7 says "slows down and pauses".
5. **For a one-day period, users are given** (that day's count); longer periods say "per day only" (5-07).
6. **The Google sign-in error wording is now shared:** "Please reconnect on the Connections page" instead of "reconnect Google Ads" (5-08).
7. **The browser test imports its property through a helper process with the simulator.** The CI browser job switches Google Analytics on with placeholder settings only to show the pages (5-09).
8. **The remaining allowance is remembered per worker process** (5-06): each answer carries fresh figures, as for Meta's usage in Phase 4.

## 9. Not verified in this environment

- **Anything against Google Analytics (5-01, Step 0, plan §4.2).** To confirm on Google's demo property and one of your properties:
  - `accountSummaries` and `properties.get`: the fields, the demo account, a property with Viewer access only, a property in the bin;
  - the exact report JSON: values as strings, the `date` format, how an empty day and an empty report look, the `propertyQuota` block, and whether the separate `sessionSource` / `sessionMedium` dimensions behave as documented;
  - errors for a removed permission, a property without access, an exhausted quota and an invalid metric;
  - the Google sign-in with `analytics.readonly` in the existing OAuth client (consent-screen marking), refresh and revocation;
  - the "(other)" row, thresholding, sampling and `dataTruncationReasons` on a busy property;
  - **on one property: AdVegaX's daily sessions, users, key events, purchases and revenue for a fixed settled week equal the GA4 interface** (same date range, property time zone).
- **GitHub CI.** It runs on a pull request `feature/phase-1a → main`.
- **Docker image builds.** No Docker daemon is available here; the CI `docker` job builds both images.

## 10. Known limitations and remaining risks

| Item | Severity | Note |
|---|---|---|
| No live verification yet | **HIGH** (until Step 0) | Built from documentation. Unknown values are skipped and counted, never guessed; a report with unexpected headers stops the read rather than storing wrong numbers |
| Google app verification for Google Ads + Analytics permissions | **HIGH** | One verification for both (Q-5-11); until then only listed test users can sign in |
| Figures differ from the GA4 interface (time zone, processing, thresholding, "(other)") | MEDIUM | Property time zone; 14-day nightly re-read; notes shown; Step 0 item 6 on a settled week |
| High-cardinality source / medium / campaign views | MEDIUM | Paging, a 500-a-day cap into a marked "(other)", only three views |
| Users mistakenly added up in later phases | MEDIUM | Stored per day only; the API never returns a period user total; noted for Phase 6 |
| Quotas on very large properties during first imports | LOW | One batch call per month; pacing from every answer; pauses instead of failures |
| The Data API is still `v1beta` | LOW | Version in a setting; unknown values skipped and counted |

## 11. Rollback

- Google Analytics is off by default (`GOOGLE_ANALYTICS_ENABLED=false`). Switching it off stops offering it; scheduled runs then find no provider and start nothing.
- Migrations 0015 and 0014 can be migrated down (0015 first; it fails while negative revenue rows exist, so delete those first). Removing the Google Analytics provider and its pages leaves Google Ads, Meta and the stores unchanged — the shared Google sign-in keeps working for Google Ads (tested).

## 12. Next

1. Product-owner review of this report and `PHASE_05_PROGRESS.md`.
2. The Google set-up for Step 0 (plan §2A):
   - in the same Google Cloud project as Google Ads, switch on the **Google Analytics Data API** and **Google Analytics Admin API**, and add `analytics.readonly` to the consent screen;
   - a Google account with at least Viewer access to one of your GA4 properties (for example Eve Zone's); optionally add Google's demo account (Google Merchandise Store);
   - the client id and secret stay **only** in the local untracked settings file.

   Then allow the four Google addresses in Claude's network settings, and I run Step 0 (5-01).
3. The Google Ads (3-01) and Meta (4-01) Step 0 checks are still pending as well.
4. Apply `advegax-pending.bundle` to your desktop folder, push, and open a pull request `feature/phase-1a → main` so GitHub CI runs every job.
5. Then Phase 6 (unified analytics and financial engine), which needs the signed-off metric definitions (Q7).
