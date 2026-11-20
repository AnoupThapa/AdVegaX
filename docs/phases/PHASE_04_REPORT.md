# Phase 4 — Implementation Report (Meta Ads, read-only)

**Date:** 2026-10-19 · **Branch:** `feature/phase-1a` · **Status:** Implemented against the Meta simulator — awaiting product-owner review. **Step 0 on a Meta sandbox ad account and one real ad account (4-01) is still pending**: it needs the Meta app (app id, app secret, Login for Business configuration), a sandbox ad account, and network access to `graph.facebook.com` and `www.facebook.com`.
**Plan:** `PHASE_04_PLAN.md` (approved 2026-10-18, A22, all recommendations) · Task-by-task reports: `PHASE_04_PROGRESS.md` (4-02 … 4-08).

---

## 1. Summary

An organization can now connect Meta read-only and see its Meta advertising next to Google Ads and its stores. Concretely, it can:

- **connect** by signing in with Facebook Login for Business (a configuration that asks for `ads_read` and `business_management`, PKCE, the long-lived token of about 60 days);
- **see every ad account** the person can use, grouped under the business that owns it. The ones that cannot be used say why: disabled or closed, an unpaid balance, under Meta's review, or missing details;
- **link** the accounts it uses. Each one imports its **campaigns, ad sets and ads** (archived and deleted ones kept) with their budgets, and **13 months of daily figures** at four levels: account, campaign, ad set and ad;
- **stay up to date by itself**, on the Phase 3 schedule:
  - every 3 hours: the structure plus today and yesterday;
  - every night: the last 30 days are read again;
  - every week: the last 90 days.

  Meta's corrections overwrite the days they cover.
- **stay inside Meta's limits:**
  - from 75 % of a limit, each call waits a little;
  - from 95 %, or while Meta names a wait, AdVegaX stops calling and the run continues by itself later. A limit for one ad account pauses only that account; Meta's limit for AdVegaX's whole app pauses every Meta account;
  - a request Meta finds too large is read as one of Meta's report jobs;
- **see the figures in Meta's words:** spend, link clicks, impressions, purchases and purchase value, with the four rates. Every figure is labelled "Reported by Meta"; the pages say "ad sets", "Purchases", "Objective" and "Business";
- **keep the sign-in alive:**
  - the end date is shown;
  - a notice with "Reconnect Meta" appears from 14 days before the end (urgent from 3 days), and the warning is recorded at 14 and 3 days;
  - at the end, the connection says "Needs reconnecting";
  - reconnecting with the same Facebook account keeps the connection, its links and its data, and starts a new 60 days;
- recover from a **removed permission**, a **disabled or unpaid account**, **Meta's limits** and **disconnect** (permission removed at Meta, figures still readable). None of this needs manual database work.

The same four promises as Phase 3 hold:

- **Read-only.** Every request passes one guard that allows reading, plus three calls that change nothing in an ad account: the token exchange, starting a report, and removing AdVegaX's own permission. `ads_management` is never requested. Static tests check both.
- **Platform-reported figures, labelled as such.** There is no comparison with store sales and no attribution (Phase 6). Levels are never added into each other, and Google Ads and Meta figures are never summed.
- **Missing data is never shown as 0.** A budget of "0" from Meta means "held at the other level" and is stored as no budget.
- **No token or the app secret is ever shown.** Tokens travel in the `Authorization` header, never in an address. Every call carries `appsecret_proof`. No Facebook name, email or picture is requested or stored.

Everything is built from Meta's documentation (checked 2026-10-18) and tested against an in-process **Meta simulator**:

- Login for Business with PKCE, and both token exchanges;
- `appsecret_proof` on every call;
- the Graph API lists, which hide archived and deleted objects unless asked;
- insights with `actions` and `action_values`;
- the report jobs;
- Meta's usage headers and error format.

It has **not yet run against Meta**; §9 lists what Step 0 must confirm.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 4-01 | ⏸ **Waiting:** needs the Meta app, a sandbox ad account, one real ad account, and network access to `graph.facebook.com` and `www.facebook.com` |
| 4-02 | Meta sign-in (Login for Business, PKCE, server-side code exchange, long-lived token; `/me` and `/me/permissions` instead of `debug_token`), Graph client (`appsecret_proof`, header tokens, cursor paging, plain error codes, usage headers), read-only guard and static rules, Meta simulator |
| 4-03 | Discovery through `me/adaccounts`, grouped by business; plain reasons per account status (new: `account_unsettled`, `account_under_review`); linking reads the account itself |
| 4-04 | Structure import: campaigns, ad sets and ads with archived and deleted ones asked for explicitly; Meta's effective status passed down from parents; budgets at campaign or ad-set level converted with the currency offset (cents, or whole units for 11 currencies such as JPY) |
| 4-05 | Daily figures: 13 months in monthly slices, four levels, each ad set's own attribution, `omni_purchase` purchases and value, link clicks, exact spend, deleted objects included; report jobs for slices Meta finds too large |
| 4-06 | Pacing from Meta's usage headers, per-account and app-wide limits (pauses use no retry attempt), sign-in expiry check with warnings at 14 and 3 days and "Needs reconnecting" at the end, plain health reasons. Fix: the platform-wide wait is now checked for every step that calls a platform |
| 4-07 | API: `connection_expires_at` on ad accounts and `sign_in_expires_at` on connections. Web app: both platforms on the Advertising tab; Meta wording; the sign-in end date and its notice; business grouping and Meta's reasons on the Connections pages |
| 4-08 | Whole-journey simulator test, browser test with a simulated Meta account and accessibility checks, browser-test helper, CI switch, this report |

## 3. Acceptance criteria (plan §16)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | A Facebook sign-in connects, discovers ad accounts by business, links them, imports structure and 13 months of figures, stays up to date, and handles a removed permission, an expiring token, a disabled account, Meta's rate limits, reconnect and disconnect without manual database work | ✅ with the simulator · ⏸ on Meta | `test_meta_ads_journey.py`: connect → discover by business → unpaid account refused → link AUD and JPY → import → 3-hour run → nightly correction → Meta's limit (pause, then continue) → 14-day warning → permission removed → reconnect → Sync now → disconnect. Also `test_meta_ads_{connect,discovery,structure,performance,sync}.py`; browser: `meta.spec.ts` |
| 2 | Daily figures match hand-calculated golden values to the cent in both currency groups, and match Ads Manager for one real account for a fixed week | ✅ golden values · ⏸ Ads Manager match | Golden values: AUD spend 48.75, purchases 2 and value 159.90 through import, API and pages. Budgets: A$50.00 from 5,000 cents, ¥5,000 from 5,000 whole yen; every offset currency is tested. The Ads Manager match is Step 0 item 8 |
| 3 | Corrected past days are overwritten, with no stale or duplicated rows; deleted ads' activity is kept in account totals | ✅ | `test_meta_ads_performance.py` (re-read replaces its days, duplicates stored once, deleted ad's days kept, account totals from Meta's account rows), journey step 4 |
| 4 | No Meta call that changes anything exists in the code, and `ads_management` is never requested | ✅ | `test_static_rules.py` (one request gate, preceded by the read-only guard; no `ads_management` or `pages_manage`); journey check that every call to Meta was a read except the token exchanges and the permission removal |
| 5 | Tokens and the app secret never appear in responses, logs, audit, UI or AI context | ✅ | Journey scan of every response, the audit log and the logs (including the HTTP client's request log); browser page scan. No AI features use advertising data yet |
| 6 | Missing data is never shown as 0; Google Ads and Meta figures are never added together | ✅ | Phase 3 API and component tests apply to Meta unchanged; "0" budgets stored as none; the Advertising tab lists accounts per platform, never a combined total |
| 7 | All suites pass, with no calls to Meta in CI | ✅ locally · CI on GitHub not yet run | §5. The simulator replaces the network; the browser helper refuses deployed environments; CI uses placeholder Meta settings only to show the pages |

## 4. Security controls — how each is verified

| Control | Verified by |
|---|---|
| Read-only: one request gate allowing reads plus three documented calls that change nothing in an ad account; `ads_management` never requested; no write capability declared | `test_static_rules.py`, `test_meta_ads_client.py` (anything else refused before it is sent), journey |
| Sign-in: Login for Business configuration, PKCE S256, single-use state bound to the person; code exchanged on the server; `ads_read` required | `test_meta_ads_connect.py` |
| Tokens and the app secret never in an address; `appsecret_proof` on every call | `test_meta_ads_client.py`, the simulator refuses tokens in addresses and wrong proofs, journey scan |
| Tokens encrypted at rest with their end date; never in responses, audit, logs or the web app | `test_meta_ads_connect.py`, journey scan, browser page scan |
| An ended sign-in is never sent to Meta; the expiry check decrypts nothing | `test_meta_ads_sync.py` |
| Only Meta's fixed host through the SSRF-safe client; no redirects followed; ad account and report ids checked before they enter an address | `test_meta_ads_client.py` |
| Per-account problems (disabled, unpaid, under review, no access, Meta's limit for one account) never mark the connection; sign-in problems do | `test_meta_ads_structure.py`, `test_meta_ads_sync.py`, journey step 7 |
| Tenant isolation: the Phase 3 tables, routes and sweeps; warnings in each organization's own audit log | `test_rls.py`, `test_tenant_isolation.py`, `test_meta_ads_sync.py` |
| No personal data: no Facebook name, email or picture; no ad texts, images, audiences or age/gender breakdowns | Connect and structure tests (only ids, names and the fields listed in `INTEGRATION_GUIDES.md`) |
| Test simulator and helpers never ship | `backend/tests` is excluded from the Docker image; the helper refuses staging and production |

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` | ruff, mypy --strict, **1,301 passed** (1,062 at the end of Phase 3), coverage **97 %** |
| Frontend unit/component (Vitest) | **370 passed** (358 at the end of Phase 3); ESLint, Prettier, strict types and API-type drift tests pass; build passes |
| End-to-end + accessibility (Playwright + axe) | **13 passed** (was 12). No serious or critical accessibility issues on the Connections page with Meta, the Meta connection page, the Advertising tab, the Meta account page or the Meta campaign page; no Meta token on any page |

## 6. Database

**No migration.** The Phase 3 tables hold Meta as planned:

- ad sets are ad groups;
- budgets belong to a campaign or an ad group;
- the `archived` status already existed;
- display-only details (buying type, the creative's id and name, Meta's delivery status) sit in `provider_extensions`.

The sign-in's end date was already stored with the token (1B). Expiry warnings are audit events, so no column was added.

## 7. Defects found during Phase 4 (all fixed)

- **4-02:** the plan's token check (`debug_token`) puts the token in the web address, and the HTTP library's request log would have recorded it. The person and permissions now come from `/me` and `/me/permissions`, with the token in the header. The test scans that log too.
- **4-04:** objects whose status is not in the request's status filter are never returned by Meta, so they are not "skipped". The test was corrected, and Step 0 lists the live status values.
- **4-05:** retry errors were raised with a message instead of a code, so the account would have shown a generic reason. Report jobs now have their own codes (`report_failed`, `report_pending`).
- **4-06:** Meta's limit for the whole app would not have paused the other Meta accounts. The shared wait was checked only for platforms with a daily allowance (Google). It is now checked for every step that calls a platform.
- **4-07:** while an account waited for a platform's limit, its line also said "Something went wrong with the platform" (also for Google). It now only says it is waiting.

## 8. Deviations from the plan

Each task's deviations are listed in `PHASE_04_PROGRESS.md`. The ones that matter most for review:

1. **No `debug_token`** (4-02, §7). `appsecret_proof` makes Meta itself confirm that the token belongs to AdVegaX's app.
2. **The token exchange is a POST with the secret in the body.** Meta documents a GET with the secret in the address; Step 0 confirms that Meta accepts the POST (4-02).
3. **Clicks are link clicks** (`inline_link_clicks`), not "all clicks", so click-through rate and cost per click compare fairly with Google Ads. This can be switched (4-05).
4. **Report jobs are checked within one step** (every 5 seconds, up to 5 minutes) rather than as separate queued steps. Nothing is kept between steps (4-05).
5. **Expiry warnings are recorded and shown in the app; no email is sent** (4-06). An email to the organization's owners could be added with the existing email system.
6. **Meta's usage figures are remembered per worker process** (4-06). Each answer carries fresh figures; sharing them through Redis is possible later.
7. **Meta has no shared budgets**, so each budget is named by its holder (`campaign:<id>`, `adset:<id>`) (4-04).
8. **The browser test imports its account through a helper process with the simulator.** The CI browser job switches Meta on with placeholder settings only to show the pages (4-08).

## 9. Not verified in this environment

- **Anything against Meta (4-01, Step 0, plan §4.2).** To confirm on the sandbox account and one real ad account:
  - the exact JSON: `spend` as a decimal string, budgets in minor units with the offset currencies, id formats, dates and time zone names;
  - `me/adaccounts`: the fields (`account_status` values, `business`, `currency`, `timezone_name`), and accounts reached through a business;
  - PKCE with Login for Business, the POST form of the token exchange, the long-lived exchange and `DELETE /me/permissions`;
  - the error codes for an expired or removed token, a missing permission, the limits (4, 17, 80004) and "too much data";
  - the `effective_status` values, and whether deleted objects' insights arrive with the filter;
  - budgets: campaign vs ad set, daily vs lifetime, offset currencies;
  - `omni_purchase` with `use_unified_attribution_setting=true`, against the "Purchases" column in Ads Manager;
  - **on one real account: AdVegaX's daily figures for a fixed week equal Ads Manager** (spend, impressions, link clicks, purchases, purchase value).
- **GitHub CI.** It runs on a pull request `feature/phase-1a → main`.
- **Docker image builds.** No Docker daemon is available here; the CI `docker` job builds both images.

## 10. Known limitations and remaining risks

| Item | Severity | Note |
|---|---|---|
| No live verification yet | **HIGH** (until Step 0) | Built from documentation. Unknown values are skipped and counted, never guessed, so live differences show as import warnings, not silently wrong numbers |
| Business Verification and App Review take weeks | **HIGH** | Needed before real customers connect. Your own accounts work in development mode meanwhile |
| 60-day sign-ins lapse when nobody reconnects | **HIGH** | Notice from 14 days, urgent from 3, "Needs reconnecting", a few clicks to reconnect. Long term: business system-user tokens once AdVegaX is a Meta Tech Provider (Q-4-2) |
| Budgets off by 100× (currency offset) | MEDIUM | Offset table from Meta's documentation, tested for every currency group; Step 0 item 6 |
| Figures differ from Ads Manager (attribution, time zone, deleted ads) | MEDIUM | Each ad set's own attribution, the account's time zone, account totals from account rows; Step 0 items 7–8 |
| Meta's limits during first imports of large accounts | MEDIUM | Usage-header pacing, monthly slices, report jobs; apply for Advanced Access before the pilot |
| A status Meta adds later is not in the request filter | LOW | Such objects are not returned until the status is added; Step 0 lists the live values |
| Meta changes metrics or versions with little notice | LOW | Version in a setting (v26.0); unknown values skipped and counted; an upgrade task per release |

## 11. Rollback

- Meta is off by default (`META_ADS_ENABLED=false`). Switching it off stops offering it; scheduled syncs then find no provider and start nothing.
- No migration was added, so nothing needs migrating down. Removing the Meta provider and its wording leaves Google Ads and the stores unchanged.

## 12. Next

1. Product-owner review of this report and `PHASE_04_PROGRESS.md`.
2. The Meta set-up (plan §2A):
   - a Meta developer app (Business type) with Facebook Login for Business;
   - a Login for Business configuration asking for `ads_read` and `business_management`;
   - one sandbox ad account;
   - start Business Verification and App Review.

   Put the app id, app secret and configuration id **only** in the local untracked settings file. Then allow `graph.facebook.com` and `www.facebook.com` in Claude's network settings, and I run Step 0 (4-01) on the sandbox and on one of your real ad accounts.
3. The Google Ads Step 0 (3-01) is still pending as well. It needs the developer token, the OAuth client and network access to Google.
4. Open a pull request `feature/phase-1a → main` so GitHub CI runs every job. First, the pending work in `advegax-pending.bundle` must be applied to your desktop folder and pushed.
5. Then Phase 5 (GA4, read-only), which needs decision Q11.
