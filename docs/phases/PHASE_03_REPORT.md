# Phase 3 — Implementation Report (Google Ads, read-only)

**Date:** 2026-10-18 · **Branch:** `feature/phase-1a` · **Status:** Implemented against the Google Ads simulator — awaiting product-owner review. **Step 0 on a real Google Ads test manager account (3-01) is still pending**: it needs the developer token, the Google Cloud OAuth client and network access to Google's API.
**Plan:** `PHASE_03_PLAN.md` (approved 2026-10-15, A21, all recommendations) · Task-by-task reports: `PHASE_03_PROGRESS.md` (3-02 … 3-10).

---

## 1. Summary

An organization can now connect Google Ads read-only and see its advertising next to its stores. Concretely, it can:

- **connect** by signing in with Google (PKCE, offline access). AdVegaX finds every ad account the Google account can reach, directly and through manager accounts. They are grouped under those managers, and the ones that cannot be used say why (cancelled, missing details, no access, not yet approved by Google);
- **link** the advertiser accounts it uses. Each one imports its **budgets, campaigns, ad groups and ads** (removed ones kept) and **13 months of daily figures** at four levels: account, campaign, ad group and ad;
- **stay up to date by itself:**
  - every 3 hours: the structure plus today and yesterday;
  - every night: the last 30 days are read again;
  - every week: the last 90 days.

  Google's later corrections overwrite the days they cover. A **shared counter** protects the Google allowance that every AdVegaX customer shares: re-reads wait at 80 %, and every run waits at 100 % or when Google says so.
- **see the figures** on an Advertising tab, an account page and a campaign page:
  - spend, clicks, impressions, conversions and conversion value;
  - four rates: click-through rate, cost per click, cost per conversion, and conversion value per amount spent;
  - the last 3 days marked "may still change";
  - "Sync now" for owners, admins and managers;
- recover from a **removed permission** ("Needs reconnecting", then reconnect with the same Google account: same connection, links and data), a **cancelled account** (health message; data kept), **Google's daily limit**, and **disconnect** (permission revoked at Google, figures still readable). None of this needs manual database work.

Four promises hold throughout:

- **Read-only.** No code exists that changes anything in Google Ads. A static test allows only `listAccessibleCustomers`, `search` and `searchStream`.
- **Platform-reported figures, labelled as such.** Every answer and page says "Reported by Google Ads". There is no comparison with store sales and no attribution (Phase 6). Levels are never added into each other.
- **Missing data is never shown as 0.** This covers days not read, rates whose divisor is 0 ("No clicks"…), periods partly before the history start, and accounts whose import did not finish.
- **No token, developer token or client secret is ever shown.** They never appear in a response, the audit log, the logs or the web app. No person's email or name is stored, only Google's stable account id.

Everything is built from Google's documentation (verified 2026-10-15) and tested against an in-process **Google Ads simulator**: Google's sign-in, the REST `searchStream` and `search`, managers, test and production accounts, quotas, and Google's error format. It has **not yet run against Google**; §9 lists what Step 0 must confirm.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 3-01 | ⏸ **Waiting:** needs the developer token, the OAuth client and network access to `googleads.googleapis.com`, `oauth2.googleapis.com` and `accounts.google.com` |
| 3-02 | Platform-neutral advertising model (migration 0012: ad accounts, budgets, campaigns, ad groups, ads, daily performance, sync state; forced row-level security). Read interface for advertising platforms. Read-only static guard |
| 3-03 | Google sign-in with PKCE and offline access (`adwords` + `openid`, the account id only), token refresh before expiry, revocation, REST client with Google's error codes in plain words, simulator |
| 3-04 | Discovery directly and through manager hierarchies (with limits). Reasons an account cannot be linked; the manager path for display; linking refused for unusable accounts |
| 3-05 | Linking creates the ad account and starts a resumable import chain. Structure import with exact budgets, statuses, dates and removed items kept. Per-account problems never mark the connection |
| 3-06 | 13 months of daily figures in calendar-month slices, four levels each (about 56 operations). Exact money from micros, the account's own time zone, real zeros for quiet days at account level, and each slice replaces its days |
| 3-07 | Ongoing sync (3-hour, nightly 30 days, weekly 90 days), shared allowance counter and waiting, Google's quota answer holding every account, "Sync now" logic, self-clearing health. Migration 0013 lets the scheduler read four columns only |
| 3-08 | Read API: ad accounts, daily figures with derived rates and "may still change" days, campaigns, one campaign with ad groups and ads, "Sync now" (`ads.view` / `ads.manage`) |
| 3-09 | Web app: Google Ads on the Connections page (grouped accounts, plain Google errors), the Advertising tab, the account page and the campaign page |
| 3-10 | Whole-journey simulator test, browser test with simulated Google Ads accounts and accessibility checks, browser-test helper, CI switch, this report |

## 3. Acceptance criteria (plan §16)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Connects, discovers accounts directly and under managers, links advertiser accounts, imports structure and 13 months of figures, stays up to date, and handles a revoked permission, a cancelled account, the daily limit, reconnect and disconnect without manual database work | ✅ with the simulator · ⏸ on Google | `test_google_ads_journey.py` (connect → discover → cancelled account refused → link two → import → 3-hour run → nightly correction → allowance used up → permission removed → reconnect → Sync now → disconnect); `test_google_ads_{connect,discovery,structure,performance,sync}.py`; browser: `advertising.spec.ts` |
| 2 | Daily figures match hand-calculated golden values to the cent, and match the Google Ads interface for one real account for a fixed week | ✅ golden values · ⏸ interface match | Exact sample values (AUD 12.345678 from micros, 1.5 conversions) through import, API and pages; derived rates checked against hand-computed half-even values. The interface match is Step 0 item 8 |
| 3 | Corrected past days are overwritten; no stale or duplicated rows | ✅ | `test_google_ads_performance.py` (re-read replaces its days, untouched days kept, duplicates stored once), `test_google_ads_sync.py` (a correction missed by the 3-hour run is picked up nightly), journey step 4 |
| 4 | No Google Ads call that changes anything exists in the code | ✅ | Static test of the provider code (only `listAccessibleCustomers`, `search`, `searchStream`; no write capability) |
| 5 | Tokens, the developer token and the client secret never appear in responses, logs, audit, UI or AI context | ✅ | Journey scan of every response, the audit log and the logs; API test; browser page scan. No AI features use advertising data yet |
| 6 | Missing data is never shown as 0 | ✅ | API tests (not-synchronized days and periods, rates "unavailable" with a reason), component tests (9 "Not synced yet" tiles, no $0.00), browser test |
| 7 | All suites pass, with no calls to Google in CI | ✅ locally · CI on GitHub not yet run | §5. The simulator replaces the network; the browser helper refuses deployed environments; CI uses placeholder Google settings only to show the pages |

## 4. Security controls — how each is verified

| Control | Verified by |
|---|---|
| Read-only: only `listAccessibleCustomers`, `search`, `searchStream`; no write capability declared | `test_static_rules.py` / provider static test |
| Google sign-in: PKCE S256, single-use state bound to the person, ID token checked (issuer, audience, expiry, account id only) | `test_google_ads_connect.py`, `test_google_ads_provider.py` |
| Tokens encrypted at rest, refreshed before expiry, revoked at Google on disconnect; never in responses, audit, logs or UI | `test_google_ads_connect.py`, journey scan, browser page scan |
| Developer token and client secret only in the secret store or local untracked settings; never in URLs | Client tests (headers only), journey scan |
| Only Google's fixed hosts through the SSRF-safe client; no redirects followed | `test_google_ads_client.py` |
| Customer ids validated before use (no path tricks) | `test_google_ads_client.py` |
| Per-account problems never mark the connection; sign-in problems do ("Needs reconnecting") | `test_google_ads_structure.py`, `test_google_ads_sync.py`, journey step 6 |
| Shared allowance key names only the platform, never a token | `test_google_ads_sync.py` |
| Tenant isolation: forced row-level security on every new table; the scheduler's system access is four columns of `ad_accounts` | `test_rls.py`, `test_tenant_isolation.py` (generated sweeps cover every new route), `test_google_ads_sync.py` (system role cannot read names) |
| Permissions: every member reads; owners, admins and managers "Sync now", limited to 6 an hour per account | `test_ad_accounts_api.py`, component tests |
| Test simulator and helpers never ship | `backend/tests` is excluded from the Docker image; the helper refuses staging and production |

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` | ruff, mypy --strict, **1,062 passed** (799 at the end of Phase 2B), coverage **97 %** |
| Frontend unit/component (Vitest) | **358 passed** (343 at the end of Phase 2B); ESLint, Prettier, strict types and API-type drift tests pass; build passes |
| End-to-end + accessibility (Playwright + axe) | **12 passed** (was 11). No serious or critical accessibility issues on the Google Ads connection page, the Advertising tab, the account page or either campaign page; no Google token on any page |

## 6. Database

- **0012** (the advertising tables and three discovery columns on `external_resources`) and **0013** (the scheduler may read four columns of `ad_accounts`). Both are additive only.
- Upgrade and downgrade are tested (`test_migrations.py`). Rollback: downgrade to 0011 removes everything Phase 3 added; stores are untouched.

## 7. Defects found during Phase 3 (all fixed)

- **3-05:** the simulator let an account under a manager be reached without naming the manager, which Google refuses. The simulator was fixed to match Google, and the provider always signs in through the manager.
- **3-07:** a sign-in problem raised **while reading** campaigns or figures (rather than before) did not mark the connection "Needs reconnecting". Reads now complete inside the protected call.
- **3-07:** a step waiting for the allowance could be run again early if its message was delivered twice. The waiting step's time is now stored with the job, so an early message finds it not yet due.
- **3-08:** the "already being updated" message named stores only. It now fits ad accounts too.

## 8. Deviations from the plan

Each task's deviations are listed in `PHASE_03_PROGRESS.md`. The ones that matter most for review:

1. **`openid` is requested with Google Ads**, for Google's stable account id only. That is how a reconnect by the same person keeps the connection and its data. No email, name or picture is requested or stored (3-03).
2. **The same Google account can be connected in two organizations.** Stores keep the one-live-connection rule (3-03).
3. **Cancelled accounts that were linked stay linked**, with a health message. Their history stays readable (3-04, 3-07).
4. **Ads are keyed by ad group and ad.** Google identifies an ad within its ad group (3-06).
5. **"Nightly" means 24 hours after the last nightly run**, not a fixed time of night, so accounts spread over the day (3-07).
6. **Corrections remove an entity's row for a day rather than writing zeros.** Totals are the same; the account level always has every day (3-07).
7. **The 3-hour run costs 9 operations, not 8.** The account's own status is read with the structure, so health stays current (3-07).
8. **"Sync now" is `…/resync`** and campaigns are listed per ad account, as in the plan; the older API outline differed (3-08).
9. **"Conversion value per AUD spent" is not called ROAS.** It is Google's conversion value, not store sales (3-09).
10. **The browser test imports its accounts through a helper process with the simulator.** The CI browser job switches Google Ads on with placeholder settings only to show the pages (3-10).

## 9. Not verified in this environment

- **Anything against Google (3-01, Step 0, plan §4.2).** To confirm on the test manager account:
  - the exact JSON shapes: int64 values as strings, camelCase keys, dates in the account time zone, metrics left out when zero;
  - `listAccessibleCustomers` and the `customer_client` hierarchy through a manager, including a read-only user;
  - the error codes for a revoked permission, a cancelled account, no access, a test token on a production account, the quota and a bad query;
  - PKCE, `prompt=consent` for a new refresh token on reconnect, and revocation;
  - Performance Max reports without ad groups;
  - budget fields (daily vs total, shared, micros), and the newer campaign date fields;
  - removed campaigns and ads in reports for the days they ran;
  - **on one real account under Explorer access: AdVegaX's daily figures for a fixed week equal the Google Ads interface** (cost, clicks, impressions, conversions, value).
- **GitHub CI.** It runs on a pull request `feature/phase-1a → main`.
- **Docker image builds.** No Docker daemon is available here; the CI `docker` job builds both images.

## 10. Known limitations and remaining risks

| Item | Severity | Note |
|---|---|---|
| No live verification yet | **HIGH** (until Step 0) | Built from documentation; unknown values are skipped and counted, not guessed, so live differences show as import warnings to fix, not silently wrong numbers |
| Developer-token review (Test → Explorer → Basic) | **HIGH** | Explorer (2,880 operations a day) holds about 40 accounts at this pace, Basic (15,000) about 200. Raise `GOOGLE_ADS_DAILY_OPERATIONS` when access is granted |
| Google app verification for the `adwords` permission | **HIGH** | Until verified, only listed test users can sign in and sign-ins expire after 7 days. Needs home page, privacy policy, domain verification and a demo video |
| Shared daily allowance across all customers | MEDIUM | Counter, waiting and Google's own quota answer are handled; first imports and 3-hour runs keep priority |
| Figures differ from the Google Ads interface (time zone, removed items, conversion column) | MEDIUM | Step 0 item 8; account time zone; recent days marked "may still change" |
| A connected person leaves the organization or loses access | MEDIUM | "Needs reconnecting" / "no account access" health; any manager can reconnect |
| Quarterly API versions and yearly sunsets (v25 until about August 2027) | LOW | Version in a setting; yearly upgrade with a simulator refresh |

## 11. Rollback

- Google Ads is off by default (`GOOGLE_ADS_ENABLED=false`); switching it off stops offering it. Scheduled syncs then find no provider and start nothing.
- For a full removal: migrate down to 0011 and remove the Google Ads provider, the advertising routes and the Advertising tab. No store table or route changes behaviour.

## 12. Next

1. Product-owner review of this report and `PHASE_03_PROGRESS.md`.
2. The Google set-up (plan §2A):
   - the manager account and its developer token (apply for Explorer now);
   - the Google Cloud project, OAuth consent screen and web client;
   - a test manager account with two test advertiser accounts.

   Put the developer token, client ID and client secret **only** in the local untracked settings file. Then allow `googleads.googleapis.com`, `oauth2.googleapis.com` and `accounts.google.com` in Claude's network settings, and I run Step 0.
3. Open a pull request `feature/phase-1a → main` so GitHub CI runs every job (after the pending work is pushed from your desktop folder).
4. The Shopify (2A-01) and WooCommerce (2B-01) live checks remain pending.
5. Then Phase 4 (Meta Ads, read-only). Its plan can be drafted while the live checks wait. Meta's App Review should start early.
