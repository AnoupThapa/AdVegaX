# Phase 5 — Google Analytics 4 (read-only): Implementation Plan

**Status:** 📝 **Draft — awaiting product-owner approval.** Nothing in this plan is implemented until it is approved. · **Date:** 2026-10-19

> **Live tests (Q-5-9):** recommended option C, as for Google Ads and Meta: build against Google's documentation and a GA4 simulator; Step 0 (5-01) runs when the Google OAuth client and network access to Google's Analytics APIs are available. Google's public **demo property** (Google Merchandise Store) and one of your own properties are the live checks.

**Depends on:** Phase 1 (connections, credentials, jobs, SSRF-safe client) and the Google sign-in built in Phase 3 (PKCE, refresh, revocation). It reuses the Phase 3 patterns (import chain, schedule, "may still change" days, read API shape, pages), but GA4 data is not advertising data, so it gets its own small model. · **Followed by:** Phase 6 (unified analytics and financial engine).
**Governing documents:** MASTER_SPECIFICATION §7, §20 (D4, D5, D14, D19, D22), A2, A10; DISCOVERY_REPORT C6 and Q11; DATABASE_SCHEMA §12 (`analytics_events`, Q11 notice); ARCHITECTURE §9–§10; `phases/PHASE_03_PLAN.md`, `PHASE_03_REPORT.md`, `PHASE_04_REPORT.md`; INTEGRATION_GUIDES §2.

---

## 1. Objective

Let an organization connect **Google Analytics 4 read-only** with one Google sign-in:

- see every GA4 property that sign-in can reach, grouped by the Analytics account that owns it;
- choose which properties to link;
- import each linked property's **daily figures**: sessions, engaged sessions, users, new users, key events, purchases and purchase revenue;
- in total, by default channel group, and by source / medium / campaign;
- keep them up to date, including Google's later processing.

At the end of Phase 5, with the simulator (and the demo property once Step 0 runs):

- a manager connects Google Analytics and links two properties in different currencies and time zones;
- daily figures appear per property, **clearly labelled "Reported by Google Analytics"**, in each property's own currency and time zone;
- recent days are marked "still being processed by Google"; days where Google grouped rows into "(other)" or held some back for privacy say so;
- an Analytics tab sits next to Stores and Advertising; GA4 figures are never added to store sales or ad-platform figures;
- disconnect, removed permission and reconnect work cleanly;
- **the code contains no call that changes anything in Google Analytics.**

**Decision Q11** (from the discovery report, C6) is settled by this plan: GA4's Data API returns **aggregated reports, not events**, so AdVegaX stores **daily aggregates** (`analytics_daily`) and discovers properties with the **GA4 Admin API** (read-only). The event-level `analytics_events` table in the target schema is dropped from the design (it was never created).

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all of them at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q11** | How is GA4 data stored? | **Daily aggregates** per property (and per breakdown), not individual events. Property discovery uses the **Admin API** (read-only). | That is what Google's Data API returns. Event-level data is only available through BigQuery export, which is a separate, paid-for set-up per property and not needed for Phases 6–7. |
| **Q-5-1** | Which API versions? | **Data API v1beta** and **Admin API v1beta** (the current stable versions; `v1alpha` features are not used), kept in a setting. | Both are Google's production versions; alpha features (such as the new conversational queries) can change without notice. |
| **Q-5-2** | Which Google sign-in? | **Its own connection** ("Google Analytics"), asking only for `analytics.readonly` (plus `openid` for Google's stable account id, as for Google Ads). It uses the **same Google Cloud project and OAuth client** as Google Ads. | People often use a different Google account for Analytics than for Ads. A separate connection keeps each permission small and lets either be removed alone. One Google Cloud project means one consent screen and one verification. |
| **Q-5-3** | Which properties can be linked? | **Every GA4 property the sign-in can reach**, shown under its Analytics account. Properties without a currency or time zone, or that Google reports as deleted, are listed as "not available". | It mirrors Google Ads and Meta (Q-3-3, Q-4-3). Linking a property to a particular store is Phase 6. |
| **Q-5-4** | What is imported? | Per property and day: **sessions, engaged sessions, total users, new users, key events, purchases (`ecommercePurchases`) and purchase revenue (`purchaseRevenue`)**. Three views: **total**, by **default channel group**, and by **source / medium / campaign**. | Enough for Phase 6 (traffic and revenue next to ad spend) and Phase 7 (funnel), matching campaigns by UTM names. Pages, events, devices, countries and demographics are left out until a phase needs them. Demographics would also trigger Google's privacy thresholds. |
| **Q-5-5** | Users over a period | **Users are shown per day and never added across days.** For a period, AdVegaX shows sessions, key events, purchases and revenue as totals, and users as "per day". | One person who visits on two days is one user for the two days together, but counts once on each day. Adding days would overstate users. |
| **Q-5-6** | How fresh, and how much history? | A **3-hour run** reads today and yesterday; **nightly**, the last **14 days** are read again; **weekly**, the last **90**. **13 months** of history on first link. The last **3 days** are marked "still being processed by Google". | Google says processing takes 24–48 hours, data can arrive up to 7 days late, and key-event attribution can change for 12 days. The nightly 14-day re-read catches all of it. 13 months matches stores and ads. |
| **Q-5-7** | Google's limits | Every request asks Google for its **remaining quota** (`returnPropertyQuota`). AdVegaX slows down and pauses a property's run when its hourly or daily tokens run low, then continues by itself. | Each standard property allows **200,000 tokens a day, 40,000 an hour, and 14,000 an hour per app**, with 10 requests at once. A day's reports cost a few dozen tokens, so normal use stays far below. Pacing protects first imports of large properties. |
| **Q-5-8** | Privacy thresholds, "(other)" rows and sampling | **Recorded and shown, never hidden.** If Google withheld small rows (thresholding), grouped rare values into "(other)", sampled, or truncated a report, the day says so ("Google grouped some sources into (other)"). | These are normal in GA4. Hiding them would make the figures look more exact than they are (A10: never pretend). |
| **Q-5-9** | Live test environment | **C:** build against the documentation and a GA4 simulator. Step 0 runs on **Google's public demo property** (Google Merchandise Store, which any Google account can add) and on **one of your own properties**, once the OAuth client exists and the network allows `analyticsdata.googleapis.com`, `analyticsadmin.googleapis.com`, `oauth2.googleapis.com` and `accounts.google.com`. | The demo property has real e-commerce data, so figures can be compared with the GA4 interface without your own data. To confirm in Step 0 that the API can read it. |
| **Q-5-10** | The same property in two organizations? | **Allowed**, as for Google Ads and Meta. | Agencies and businesses share Analytics access. |
| **Q-5-11** | Google's app verification | **One verification for the whole Google app** (Google Ads + Analytics), started before the pilot. | `analytics.readonly` is expected to need the same Google review as Google Ads' permission (to confirm on the consent screen). Until verified, only listed test users can sign in. |

## 2A. What you need to set up

1. **Nothing new in Google Cloud beyond Phase 3:** in the same project, enable the **Google Analytics Data API** and **Google Analytics Admin API**, and add `analytics.readonly` to the consent screen.
2. **A Google account with access to a GA4 property** (yours, e.g. Eve Zone's, with at least Viewer access) for the Step 0 comparison. Optionally add Google's demo account (Google Merchandise Store) to the same Google account.
3. The client id and secret stay **only in the local untracked settings file** (shared with Google Ads).
4. **Network access** for the four Google addresses above, when Step 0 runs.

## 3. Scope

| Area | In Phase 5 |
|---|---|
| Analytics provider | `app/providers/google_analytics/`: Google sign-in with `analytics.readonly` (reusing the Phase 3 sign-in code), Admin API discovery (`accountSummaries`, `properties.get`), Data API reports (`runReport` / `batchRunReports`), quota reading, error mapping, paging |
| Core | A platform-neutral **analytics** model and `AnalyticsProvider` interface (as D4 requires), an import chain and schedule modelled on Phase 3, health |
| Data | Migration **0014**: `analytics_properties`, `analytics_daily`, `analytics_sync_state` (forced row-level security) |
| Read-only guarantee | Only `accountSummaries.list`, `properties.get`, `runReport`, `batchRunReports` (and `getMetadata`). A static test fails if anything else appears; no write capability is declared |
| API | `/analytics-properties`, `/analytics-properties/{id}`, `/analytics-properties/{id}/metrics/daily` (with `breakdown`), `/analytics-properties/{id}/resync` |
| Web app | Google Analytics on the Connections page (properties by Analytics account), an **Analytics** tab, a property page (totals, by day, by channel, by source / medium / campaign) |

## 3A. Non-goals

- Linking a property to a store, combining GA4 revenue with store sales or ad spend, attribution (Phase 6).
- Funnels and paths (Phase 7). Realtime reports. BigQuery export. Event-level data.
- Pages, events by name, devices, countries, demographics, audiences.
- Anything that changes GA4 (properties, data streams, key events, audiences). `analytics.edit` is never requested.
- Universal Analytics (shut down by Google).

## 4. Platform facts and Step 0

### 4.1 From Google's documentation (checked 2026-10-19)

1. **Versions:** the Data API and the Admin API are `v1beta`; new features appear in `v1alpha` first (for example conversational queries and conversion reporting in 2026). A `dataTruncationReasons` field was added to report metadata in both versions on 14 September 2026.
2. **Permission:** `https://www.googleapis.com/auth/analytics.readonly` — "See and download your Google Analytics data" — covers both APIs.
3. **Discovery:** `accountSummaries.list` returns every Analytics account and its property summaries the person can reach; `properties.get` gives a property's currency and time zone.
4. **Reports:** `runReport` with `dateRanges`, `dimensions` (`date`, `sessionDefaultChannelGroup`, `sessionSourceMedium`, `sessionCampaignName`) and `metrics` (`sessions`, `engagedSessions`, `totalUsers`, `newUsers`, `keyEvents`, `ecommercePurchases`, `purchaseRevenue`); up to 5 reports per `batchRunReports`. Dates are in the **property's time zone**; money in the **property's currency**.
5. **Quotas (standard properties):** 200,000 core tokens per property per day; 40,000 per hour; 14,000 per app per property per hour; 10 concurrent requests; 10 server errors per app per property per hour; 120 potentially thresholded requests per hour (demographics and audiences only). `returnPropertyQuota: true` returns the tokens used and left. Analytics 360 properties have higher limits.
6. **Freshness:** intraday data typically in 2–6 hours; daily data typically within 12 hours; "data processing can take 24–48 hours"; some data can arrive up to 7 days late; attribution credit for key events can change for up to 12 days.
7. **Data quality signals** in every response: `subjectToThresholding`, `dataLossFromOtherRow` ("(other)" row, more likely above 500 unique values a day), `samplingMetadatas`, and now `dataTruncationReasons`.
8. **Key events** replaced "conversions" in GA4's metrics (2024); `keyEvents` is the metric.

### 4.2 Step 0 — verify on the demo property and one of your properties (task 5-01)

1. `accountSummaries` and `properties.get`: the fields, the demo account, a property with Viewer access only.
2. The exact report JSON: values as strings, the date format, the empty-day behaviour, and the quota block.
3. Errors: a removed permission, a property without access, quota exhausted, an invalid metric.
4. Google sign-in with `analytics.readonly` in the existing OAuth client (consent screen marking), refresh and revocation.
5. The "(other)" row, thresholding and sampling flags on a busy property.
6. **On one property: AdVegaX's daily sessions, users, key events, purchases and revenue for a fixed settled week equal the GA4 interface** (same date range, property time zone).

## 5. Proposed structure

```
app/providers/google_analytics/   client.py (Admin + Data, read-only guard), provider.py, mapping.py
app/providers/base/               AnalyticsProvider interface and analytics record types
app/domains/analytics/            models, importer (chain + schedule), read_service, router, schemas
frontend/features/analytics/      tab, property page, labels
```

The core never imports `providers/google_analytics` (the D19 static test is extended). The Google sign-in code from Phase 3 is shared, not copied.

## 6. Connect, credentials and health

1. **Start:** "Connect Google Analytics" → the existing `/connections/google_analytics/start` with PKCE, offline access, `analytics.readonly` and `openid`.
2. **Callback:** code exchanged on the server; tokens encrypted (1B); only Google's stable account id is kept to recognise a reconnect.
3. **Discovery:** `accountSummaries` → one `analytics_property` resource per property, grouped by Analytics account (`group_path`), with currency and time zone from `properties.get`.
4. **Refresh and revocation** as for Google Ads (Phase 3).
5. **Health on the property page**, in plain words: "You no longer have access to this property", "Google is limiting how much AdVegaX can read — figures will update later", "This property was deleted in Google Analytics".

## 7. Outbound safety and secrets

- Only `analyticsdata.googleapis.com`, `analyticsadmin.googleapis.com` and Google's sign-in hosts, through the existing SSRF-safe client; no redirects followed.
- Tokens in the `Authorization` header only; property ids checked (`properties/<digits>`) before they enter an address.
- The client secret and tokens are never logged, audited, returned, shown or given to AI.
- The read-only static test fails the build if any other Analytics method appears.

## 8. Data model (migration 0014, additive)

- **`analytics_properties`** (resource extension): property id, display name, Analytics account name, currency, time zone, status, platform status, history start, first import time, health code and time.
- **`analytics_daily`**: property, day, `breakdown` (`total` | `channel` | `source`), the breakdown's values (channel group; source, medium, campaign), sessions, engaged sessions, total users, new users, key events, purchases, purchase revenue (exact decimal, property currency), and data-quality flags (other row, thresholded, sampled, truncated), fetched time. Unique per property, day, breakdown and values.
- **`analytics_sync_state`**: as `ad_sync_state` (chain cursor, mode, progress, last runs, last error).
- Forced row-level security on all three, like every tenant table.

Missing measures are stored as null, never 0 (A10). A day Google reports with no rows gets real zeros at the total level only, as for ad accounts.

## 9. Import and sync

- **First import:** 13 months in monthly slices; each slice is one `batchRunReports` call holding the three views.
- **Ongoing:** 3-hour (today + yesterday), nightly (14 days), weekly (90 days). Each re-read replaces the days it covers.
- **"Sync now":** the last 14 days, limited per property (existing rule).
- **Quota:** each answer's remaining tokens are kept per property; below 10 % of the hour or the day, the run waits until the window moves on, without using a retry attempt. Google's "quota exhausted" answer does the same.
- **Pagination:** reports above Google's row limit are read page by page with `offset`; the source / medium / campaign view is capped per day, and the cap is recorded as "(other)".

## 10. Figures

- **Platform-reported only**, labelled "Reported by Google Analytics". No comparison with store sales or ad spend (Phase 6).
- **Period totals** for sessions, engaged sessions, new users, key events, purchases and revenue; **users only per day** (Q-5-5).
- **Rates derived on read:** engagement rate (engaged sessions ÷ sessions), key events per session, purchase conversion rate (purchases ÷ sessions), revenue per session. Each says why when it cannot be computed.
- Data-quality notes per day and per period (Q-5-8). The last 3 days marked "still being processed by Google".

## 11. API

New routes, same conventions as Phase 3 (`analytics.view` for every member, `analytics.manage` for owners, admins and managers):

- `GET /analytics-properties`, `GET /analytics-properties/{id}`;
- `GET /analytics-properties/{id}/metrics/daily?from&to&breakdown=total|channel|source`;
- `POST /analytics-properties/{id}/resync`.

## 12. Web app

- **Connections:** "Connect Google Analytics" with a note that AdVegaX only reads; properties grouped under their Analytics account; Google's reasons in plain words.
- **Analytics tab:** the linked properties with platform, currency, time zone and status.
- **Property page:** totals for the period, by day, by channel, by source / medium / campaign; "Reported by Google Analytics"; processing and data-quality notes; "Sync now".
- Every page is checked for accessibility.

## 13. Security and privacy (additions to SECURITY.md)

- **No personal data:** reports are aggregates; no user ids, client ids, IP addresses or demographics are requested. GA4's privacy thresholds are respected, never worked around.
- **Read-only:** static test, no write capability, `analytics.edit` never requested.
- **Tenant isolation:** forced row-level security on the three new tables; the generated route sweeps cover the new routes.
- **Google's API Services User Data Policy** applies with the app's verification; the privacy policy must describe Google Analytics data use and deletion.

## 14. Testing

- **GA4 simulator** (in-process, like the Google Ads and Meta ones): Google sign-in with `analytics.readonly`; `accountSummaries`, `properties.get`; `runReport` / `batchRunReports` with dimensions, metrics, `offset` paging, quota blocks, "(other)" and thresholding flags; Google's error format.
- **Golden values** in two currencies and time zones (AUD / Australia/Sydney, USD / America/Los_Angeles), checked through import, API and pages.
- **Journey:** connect → discover → link two → import → 3-hour run → a late correction picked up nightly → quota runs low and the run waits → permission removed → reconnect → Sync now → disconnect.
- **Browser test** of the Connections page, Analytics tab and property page, with accessibility checks; no token on any page.
- **Static tests:** the read-only rule and the core never importing the provider.

## 15. Tasks (one at a time, report after each)

| Task | Content |
|---|---|
| 5-01 | Step 0 on the demo property and one of your properties (§4.2) — waits for the OAuth client and network access |
| 5-02 | Analytics model (migration 0014), `AnalyticsProvider` interface, read-only static rule |
| 5-03 | Google Analytics sign-in (shared Google sign-in code), Admin and Data API client (quota, errors, paging), simulator |
| 5-04 | Discovery (accounts and properties, details), linking rules |
| 5-05 | Daily import: 13 months, monthly slices, three views, data-quality flags, exact money, property time zone |
| 5-06 | Ongoing sync, quota pacing, health |
| 5-07 | Read API |
| 5-08 | Web app: Connections, Analytics tab, property page |
| 5-09 | Journey test, browser test, docs, `PHASE_05_REPORT.md` |

## 16. Acceptance criteria

1. A Google sign-in connects Google Analytics, discovers properties by Analytics account, links them, and imports 13 months of daily figures in three views. It stays up to date, and handles a removed permission, a property without access, Google's quotas, reconnect and disconnect without manual database work.
2. Daily figures match hand-calculated golden values in both currencies, and match the GA4 interface for one property for a fixed settled week (Step 0 item 6).
3. Re-read days are replaced, with no stale or duplicated rows; users are never added across days.
4. **No Google Analytics call that changes anything exists in the code** (static test); `analytics.edit` is never requested.
5. Tokens and the client secret never appear in responses, logs, audit, UI or AI context.
6. Missing data is never shown as 0; thresholding, "(other)" rows, sampling and truncation are shown, never hidden. GA4 figures are never added to store or ad figures.
7. All suites pass, with no calls to Google in CI.

Estimate: **2–3 weeks** including your reviews. Google's app verification runs in parallel and is needed only before real customers connect.

## 17. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Google app verification for the combined Ads + Analytics permissions | **HIGH** | One verification for both; start before the pilot; test users meanwhile |
| Figures differ from the GA4 interface (time zone, processing, thresholding, "(other)") | MEDIUM | Property time zone; 14-day nightly re-read; flags shown; Step 0 item 6 on a settled week |
| High-cardinality source / medium / campaign views | MEDIUM | Daily cap with an explicit "(other)" note; only three views |
| Users mistakenly summed in later phases | MEDIUM | Users stored per day only; the API never returns a period user total; documented for Phase 6 |
| Quotas on very large properties during first import | LOW | One batch call per month; quota read from every answer; waits instead of failing |
| Google changes the Data API (still beta) | LOW | Version in a setting; unknown values skipped and counted; changelog checked per release |

## 18. Rollback

Google Analytics is off by default (`GOOGLE_ANALYTICS_ENABLED=false`) and can be switched off by configuration. Migration 0014 is additive and reversible (down to 0013 removes only the three analytics tables). Stores, Google Ads and Meta are unaffected.

## 19. Approval checklist

Approve or change:

- **Q11** (daily aggregates + Admin API discovery) and **Q-5-1 … Q-5-11**;
- the read-only guarantee (§3, §7);
- the new analytics model (§8) and the schedule (§9);
- task-by-task delivery 5-01 … 5-09.

No new runtime packages are proposed: the Analytics client uses the existing `httpx`-based safe client, not Google's SDK, to keep one hardened network path.

## Sources (checked 2026-10-19)

- [Data API quotas](https://developers.google.com/analytics/devguides/reporting/data/v1/quotas) (updated 2026-10-13)
- [Reporting data expectations: thresholding, "(other)", sampling](https://developers.google.cn/analytics/devguides/reporting/data/v1/reporting-data-expectations) (updated 2026-10-14)
- [Data freshness](https://support.google.com/analytics/answer/11198161?hl=en)
- [Analytics API changelog](https://developers.google.com/analytics/devguides/reporting/changelog?hl=en) (2026 entries: conversion reporting in v1alpha, conversational queries, `dataTruncationReasons`)
- [OAuth 2.0 scopes for Google APIs](https://developers.google.com/identity/protocols/oauth2/scopes/) (`analytics.readonly`)
- [Admin API `accountSummaries.list`](https://developers.google.com/analytics/devguides/config/admin/v1/rest/v1beta/accountSummaries/list)
- [Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
