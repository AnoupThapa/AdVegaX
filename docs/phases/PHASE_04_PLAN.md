# Phase 4 — Meta Ads (read-only): Implementation Plan

**Status:** ✅ **Approved by the product owner (2026-10-18, A22: "Approve all") with all §2 recommendations (Q-4-1 … Q-4-12).** Implementation authorized for Phase 4 only. · **Date:** 2026-10-18

> **Live tests (Q-4-10):** recommended option C, as for Google Ads: build against Meta's documentation and a Meta simulator; Step 0 (4-01) runs when the Meta app, a test ad account and network access to Meta's API are available.
**Depends on:** Phase 1 (connections, credentials, jobs, SSRF-safe client) and the Phase 3 advertising model, import chain, sync schedule, read API and pages, which were designed for Meta too. Phase 3 is implemented and awaiting review; this plan does not change it. · **Followed by:** Phase 5 (GA4).
**Governing documents:** MASTER_SPECIFICATION §7, §20 (D4, D5, D14, D19, D22), A2, A10, A13; ARCHITECTURE §9–§10; DATABASE_SCHEMA §4B; `phases/PHASE_04_META_ADS.md` (outline); `phases/PHASE_03_PLAN.md` and `PHASE_03_REPORT.md`; INTEGRATION_GUIDES §2.

---

## 1. Objective

Let an organization connect **Meta Ads (Facebook and Instagram ads) read-only** with one Facebook sign-in:

- see every ad account that sign-in can reach, grouped by the business that owns it;
- choose which ad accounts to link;
- import each linked account's **structure**: campaigns, ad sets (stored as ad groups) and ads, with budgets at campaign or ad set level, removed and archived items kept;
- import its **daily figures**: impressions, clicks, spend, purchases and purchase value;
- keep both up to date, including Meta's later corrections.

At the end of Phase 4, with the simulator (and a Meta test ad account for structure, once Step 0 runs):

- a manager connects Meta and links two ad accounts in different currencies and time zones;
- campaigns, ad sets and ads appear with their status and budgets;
- daily figures appear per account, campaign, ad set and ad, **clearly labelled "Reported by Meta"**, in each account's own currency and time zone;
- the Advertising tab shows Google Ads and Meta accounts side by side; their figures are never added together;
- an expiring sign-in is announced before it stops working;
- disconnect, removed permission and reconnect work cleanly;
- **the code contains no call that changes anything in Meta.**

Almost everything after sign-in reuses Phase 3: the tables, import chain, schedule, read API and pages are already platform-neutral. Phase 4 is mostly a second provider plus Meta-specific wording.

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all of them at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-4-1** | Which Meta API version? | **v26.0** (released 29 July 2026), kept in a setting, with an upgrade task each time Meta releases a version. | Meta releases about twice a year. An old version keeps working for at least 90 days after a newer one appears; Meta then upgrades calls automatically where nothing changed. Starting on the newest gives the most time. |
| **Q-4-2** | What kind of Meta sign-in? | **Now:** "Facebook Login for Business" with a **user access token**. A person signs in and AdVegaX reads the ad accounts that person can manage. The token lasts about **60 days**. AdVegaX warns 14 and 3 days before it ends; any manager can then reconnect in a few clicks. **Later (optional):** once AdVegaX qualifies as a Meta *Tech Provider*, switch to a **business system-user token**. It does not expire, and the business chooses exactly which ad accounts AdVegaX may read. | User tokens work today, in development and for your own businesses. System-user tokens are better for a product (they don't break when a person leaves), but only Tech Providers can issue them, and that needs Business Verification and App Review first. The rest of the design works with both. |
| **Q-4-3** | Which accounts can be linked? | **Every ad account the sign-in can reach**, shown under the business that owns it. Accounts Meta reports as disabled, closed or unsettled are listed as "not available" and cannot be linked. | It mirrors Google Ads (Q-3-3). Meta groups ad accounts by business, which is how people know them. |
| **Q-4-4** | What is imported? | **Structure:** campaigns (name, status, objective, buying type, start/end dates, budget), ad sets (name, status, optimization goal, budget when the ad set holds it), ads (name, status, and the creative's id and name only). **Daily figures** at four levels: account, campaign, ad set and ad. Measures: impressions, clicks, spend, purchases and purchase value. | The same measures as Google Ads, so Phases 6–8 can compare them. Ad texts, images, audiences and targeting are left to the phases that use them (Phase 9 creative engine). Nothing is collected without a purpose. |
| **Q-4-5** | Which conversions? | **Purchases**, as Meta reports them across website, app and offline (`omni_purchase`), and their value. They are shown as "Purchases (reported by Meta)" and never mixed with store sales. | Meta has hundreds of action types. For an e-commerce product, purchases are the conversion that matters, and Ads Manager uses the same combined purchase figure. Other actions (leads, add-to-cart) can be added later without changing the model. |
| **Q-4-6** | Which attribution? | **The advertiser's own attribution setting on each ad set** (`use_unified_attribution_setting`). Figures then match what the advertiser sees in Ads Manager. | Meta removed the 7-day and 28-day view windows in January 2026. The remaining windows differ per ad set; using each ad set's own setting avoids figures nobody recognises. AdVegaX's own attribution comes in Phase 6 (A2). |
| **Q-4-7** | How fresh, and how much history? | **The same as Google Ads.** A 3-hour run reads the structure plus today and yesterday. Nightly, the last 30 days are read again; weekly, the last 90. **13 months** of history on first link. | Meta says figures refresh every 15 minutes and stop changing after 28 days, so the nightly 30-day re-read catches every correction. One schedule for both platforms keeps the product simple. Meta keeps 37 months, so 13 is well inside it. |
| **Q-4-8** | Money and time | Spend is kept as Meta reports it, an exact amount in **the account's currency**. Budgets arrive in the currency's smallest unit (cents) — except for 11 currencies such as JPY, KRW and IDR, which Meta counts in whole units — and are converted exactly. Days are in **the account's time zone**. No currency conversion before Phase 6. | Getting the cents rule wrong by a factor of 100 is the classic Meta mistake, so it is tested for every currency group. |
| **Q-4-9** | Meta's access levels | **Now:** develop with the app's default **Limited Access**; it reads your own ad accounts, heavily rate-limited. **Before the pilot:** Business Verification, then App Review for **Advanced Access to `ads_read`**, plus the **Marketing API Full Access** tier. Full Access needs at least 500 successful calls in the last 15 days with under 15 % errors. | Reading other businesses' ad accounts needs Advanced Access and Full Access. Business Verification and App Review often take 2–6 weeks, so they should start as soon as the app exists. |
| **Q-4-10** | Live test environment | **C, as for Google Ads:** build against Meta's documentation and a Meta simulator. Run live checks as soon as the Meta app exists and the network allows Meta's addresses (`graph.facebook.com`, `www.facebook.com`). A **sandbox ad account** checks connect, discovery and structure (it never delivers ads, so it has no figures). Figures are proven with the simulator, then on one of your real ad accounts. | This workspace has not been allowed to reach Meta yet. Meta's sandbox accounts have no Insights, just as Google's test accounts have no figures. |
| **Q-4-11** | The same ad account in two organizations? | **Allowed**, as for Google Ads (Q-3-11). Each organization signs in with its own Facebook account. | Agencies and businesses commonly share ad accounts. |
| **Q-4-12** | Meta's rate limits | **Read Meta's usage headers on every answer.** Slow down above 75 % and pause an account's run when Meta says so, then continue by itself. Big ranges switch to Meta's **asynchronous report jobs** only when a normal request is too large. | Meta limits per app and per ad account, and says retrying while blocked extends the block. Normal requests are simpler; async jobs are Meta's own answer for large reads. |

## 2A. What you need to set up (long lead — start now)

1. **A Meta business portfolio for AdVegaX** (business.facebook.com), then **Business Verification** (company documents, domain). It is needed for Advanced Access and for Tech Provider status.
2. **A Meta developer app** (developers.facebook.com, type Business) with the **Marketing API** and **Facebook Login for Business** products, and a **Login for Business configuration** that asks for `ads_read` and `business_management`.
   - App settings need a privacy policy URL, terms URL, app icon, category and the AdVegaX website domain.
   - The privacy policy must describe Meta ads data use (an item for the policy you are preparing).
3. **A sandbox ad account** (Marketing API → Tools in the app), plus **one real ad account** you manage, for the figures comparison in Step 0.
4. The **app ID and app secret** go only into the local untracked settings file, never into chat or the repository (as for Google).
5. **App Review** (Advanced Access to `ads_read`; Marketing API Full Access) once Business Verification is done and the 500 test calls have run. It needs a screencast of the connect flow; I can script it once the pages exist.

## 3. Scope

| Area | In scope |
|---|---|
| Meta provider | `app/providers/meta_ads/`: Facebook Login for Business (authorization code, `state`, PKCE where Meta accepts it, server-side exchange with the app secret), long-lived token exchange, `appsecret_proof` on every call, token check (`debug_token`), Graph API reads through the existing SSRF-safe client (fixed Meta hosts only), error mapping, paging, usage headers |
| Connect & discovery | One sign-in → the person's ad accounts (`me/adaccounts`), grouped by owning business, with currency, time zone and status → the person links the ones they want |
| Structure import | Campaigns, ad sets, ads, including archived and deleted ones (filtered explicitly, as Meta hides them by default); budgets at campaign or ad set level; Meta's status kept as shown values |
| Figures import | Insights per level (`account`, `campaign`, `adset`, `ad`), one row per day (`time_increment=1`), each ad set's own attribution setting, purchases and purchase value from the `actions` and `action_values` lists, monthly slices for the first import, async jobs only for slices that are too large |
| Sync | Reuses the Phase 3 schedule (3-hour, nightly 30 days, weekly 90 days, "Sync now") |
| Rate limits | Usage headers (`x-fb-ads-insights-throttle`, `X-Business-Use-Case-Usage`) → slow down or pause; Meta's "too many calls" errors → wait, never retry at once |
| Token lifecycle | Expiry date stored with the token; warnings at 14 and 3 days; "Needs reconnecting" at expiry or when the person removes AdVegaX; reconnect keeps the connection, links and data |
| Read-only guarantee | Only `GET` requests to the Graph API, plus `POST` to `insights` (to start an async report) and the token exchange. A static test fails if any other Meta call appears, and the provider declares no write capability |
| API / UI | No new routes: the Phase 3 ad account, campaign and figures routes serve Meta too. Pages say "ad set" for Meta and "Reported by Meta"; the Connections page groups accounts by business; the account page shows when the sign-in expires |
| Testing | Meta simulator, golden figures for both currency groups, journey test, browser test with accessibility checks, read-only static test |
| Docs | INTEGRATION_GUIDES (Meta entry), API_SPECIFICATION, SECURITY, DATABASE_SCHEMA (if anything changes), report |

## 3A. Non-goals

- **Any change in Meta**: no creating, pausing or editing; no budget changes (Phase 10A/10B, through the Action Engine only). `ads_management` is not requested.
- Ad texts, images and videos, audiences, targeting, placements and breakdowns (age, gender, placement), reach and frequency (later phases, when used).
- Meta Pixel / Conversions API, catalogs, Instagram organic data, Pages.
- Linking ad accounts to stores, currency conversion, ROAS against store sales, attribution (Phase 6).
- Tech Provider system-user tokens. They are prepared for by the design, but not built until Meta grants the status (Q-4-2).
- Meta webhooks for ad accounts (the schedule is enough; webhooks can be added later).

## 4. Platform facts and Step 0

### 4.1 From Meta's documentation (checked 2026-10-18)

1. **Versions:** Graph and Marketing API v26.0 was released on 29 July 2026; v25.0 on 18 February 2026. When a version is replaced, the previous one keeps working for at least 90 days. Since May 2024, Meta automatically upgrades calls to an expired version where the endpoint did not change. Upgraded answers carry an `X-Ad-Api-Version-Warning` header.
2. **v26.0 changes relevant to reading:**
   - delivery-estimate fields are removed;
   - `pretty`, `debug` and `date_format` are ignored or refused (on all versions from 27 October 2026);
   - the Instagram Explore placement is gone.

   Nothing changes in Insights.
3. **Access:** Limited Access is the default and is meant for development, with low limits. Full Access needs App Review, plus 500 Marketing API calls in 15 days with under 15 % errors. Reading other businesses' ad accounts needs **Advanced Access to `ads_read`** (App Review). Business Verification is required for Advanced Access.
4. **Sign-in:**
   - Facebook Login for Business uses a configuration ID instead of a scope list.
   - User access tokens last about 60 days; a server must get a new one when that runs out, and the person signs in again.
   - The 90-day "data access" expiry does **not** apply to `ads_read` or `business_management`.
   - Business system-user tokens (Tech Providers only) do not expire by default.
   - The manual login flow documents PKCE (S256) for its OpenID Connect variant.
   - People can remove AdVegaX in their Facebook or Business settings at any time.
5. **Insights:**
   - available on ad account, campaign, ad set and ad;
   - `level`, `time_range`, `time_increment=1` for one row per day;
   - results are **in the ad account's time zone**, refresh about every 15 minutes, and **stop changing after 28 days** (a deleted ad can still gain clicks and actions for 28 days after its last delivery);
   - aggregate history up to 37 months (`date_preset=maximum`);
   - since 12 January 2026 the 7-day and 28-day **view** windows return nothing; 1-day click, 7-day click, 28-day click, 1-day engaged view and 1-day view remain.
6. **Limits:**
   - every answer carries `x-fb-ads-insights-throttle` (app and ad-account usage in %, and the access tier);
   - error 4 means the app limit (subcode 1504022 means global load: wait);
   - error 100 / 1487534 means too much data per call: narrow the range or level.
   - Async report jobs: `POST <object>/insights` returns a `report_run_id`; poll until "Job Completed" at 100 %, then read `<report_run_id>/insights`. Ids expire after 30 days.
7. **Archived and deleted objects:**
   - lists hide them unless filtered by `effective_status`;
   - deleted objects are still readable by id;
   - **parent-level insights still include deleted children**, which is why account totals must come from account-level rows (as in Phase 3);
   - a campaign's paused, archived or deleted status passes down to its ad sets and ads.
8. **Currency:** amounts such as bids and budgets use an **offset**:
   - offset 100 (cents) for most currencies;
   - offset 1 for CLP, COP, CRC, HUF, ISK, IDR, JPY, KRW, PYG, TWD and VND.
9. **Sandbox ad accounts:**
   - one per app;
   - no funding needed and ads are never delivered;
   - **no Insights**;
   - managed only through the API.

### 4.2 Step 0 — verify on the sandbox and one real account (task 4-01)

1. The exact JSON:
   - is `spend` a decimal string in currency units;
   - are budgets in minor units, with the offset for JPY-type currencies;
   - id formats (`act_…`);
   - date fields and time zone names.
2. `me/adaccounts`:
   - which fields arrive (`account_status` values, `business`, `currency`, `timezone_name`);
   - accounts the person reaches through a business they are part of.
3. Login for Business:
   - the configuration flow and the code exchange;
   - whether PKCE is accepted alongside `ads_read`;
   - the long-lived token and its `expires_at`;
   - `debug_token`;
   - revocation (`DELETE /me/permissions`).
4. Errors and their codes:
   - expired or removed token (190 and subcodes);
   - missing permission;
   - disabled account;
   - rate limit (4, 17, 80004);
   - too much data (100 / 1487534).
5. Archived and deleted campaigns, ad sets and ads: are they listed with the `effective_status` filter, and do their insights arrive for the days they ran?
6. Budgets: campaign budget vs ad set budget, lifetime vs daily, and the offset currencies.
7. Purchases: `omni_purchase` in `actions` / `action_values` with `use_unified_attribution_setting=true`, compared with the "Purchases" column in Ads Manager.
8. **On one real account:** AdVegaX's daily figures for a fixed week equal Ads Manager for the same days (spend, impressions, clicks, purchases, purchase value), with the same attribution setting.

## 5. Proposed structure

```text
backend/app/providers/meta_ads/   # Meta-only: sign-in, Graph client, queries, mapping, error codes
    provider.py  client.py  fields.py  mapping.py
backend/tests/meta_sim.py         # the in-process Meta simulator
```

The core never imports `providers/meta_ads` (the D19 static test is extended). The provider implements the same `AdvertisingProvider` read interface as Google Ads: `discover_resources`, `read_account`, `read_structure` and `read_performance`. The importer, schedule, read API and pages are reused. Meta-specific wording ("ad set", "Reported by Meta", the business name) comes from small provider-keyed labels.

## 6. Connect, credentials and health

1. **Start:** "Connect Meta" → the existing `POST /organizations/{org}/connections/meta_ads/start` returns Meta's login address. It carries the Login for Business configuration ID, a single-use `state` and PKCE where Meta accepts it.
2. **Callback:**
   - the existing OAuth callback exchanges the code on the server, with the app secret, for a token, then for the **long-lived** token;
   - the token and its expiry date are encrypted (1B);
   - the person's Facebook user id is kept only to recognise a reconnect by the same person (as with Google's account id); no name, email or picture is stored.
3. **Every call** carries `appsecret_proof` (an HMAC of the token with the app secret), so a leaked token alone cannot be used against AdVegaX's app.
4. **Discovery:** `me/adaccounts` with name, currency, time zone, status and owning business → one `ad_account` resource per account, grouped by business (`group_path`). Accounts that cannot be used get a plain reason (Q-4-3).
5. **Expiry:**
   - the account page and the Connections page show "Meta sign-in ends on …" from 14 days before;
   - an in-app warning appears at 14 and 3 days before the end;
   - at expiry, or when Meta answers "token invalid" (190), the connection shows **"Needs reconnecting"**;
   - reconnecting with the same Facebook account reuses the connection and data.
6. **Health on the account page:** in plain words, as for Google Ads.
   - "Meta disabled this ad account"
   - "The ad account has an unpaid balance in Meta"
   - "You no longer have access to this account"
   - "Meta is limiting how much AdVegaX can read — figures will update later"
7. **Disconnect:**
   - ask Meta to remove AdVegaX's permission (`DELETE /me/permissions`);
   - delete the token;
   - stop syncs;
   - keep the data.

## 7. Outbound safety and secrets

- Calls go only to fixed Meta hosts (`graph.facebook.com`; the browser alone opens `www.facebook.com`) through the existing SSRF-safe client: HTTPS only, no redirects followed, size and time limits.
- **Secrets:** the app secret and every access token are never logged, audited, returned, shown or given to AI (A12). The app secret lives only in the local untracked settings file in development and in the secret store when deployed. Tokens are sent in the `Authorization` header, never in URLs.
- The **read-only static test** fails the build if any Meta call other than the allowed reads appears (§3).

## 8. Data model

**No new tables are expected.** The Phase 3 model already holds Meta:

- ad sets are `ad_groups`, with an optional budget;
- budgets have `level` `campaign` or `ad_group` and `period` `daily` or `lifetime`;
- statuses include `archived`;
- `platform_type` holds the objective or optimization goal as Meta names it;
- `provider_extensions` holds display-only details (buying type, the creative's id and name).

`ad_performance_daily` stores Meta's `adset` level as `ad_group` and its ads by ad id. If Step 0 shows Meta needs something the model cannot hold, the change will be an **additive** migration (0014), reported before it is made. The connection's token expiry date is already part of the 1B credentials.

## 9. Import and sync

- **First import:** structure (campaigns, ad sets, ads with archived and deleted ones), then 13 months of daily insights in monthly slices, four levels per slice.
  - Meta has no shared daily allowance like Google's developer token, so the Phase 3 allowance counter is not used for Meta.
  - Pacing comes from Meta's usage headers instead (Q-4-12).
- **Ongoing:** the Phase 3 schedule and windows, unchanged.
- **Large slices:** if Meta answers "too much data" (100 / 1487534) or a request times out, that slice is read again as an **async report job**: start, poll, read, as a resumable step. Report ids are never kept beyond the job.
- **Corrections:** as in Phase 3, each re-read replaces the stored days it covers.
- **"Sync now":** the structure plus the last 30 days, limited per account (existing rule).

## 10. Figures

- **Platform-reported only**, labelled "Reported by Meta". There is no ROAS against store sales and no attribution (Phase 6).
- **Conversions** are purchases (`omni_purchase`) and **conversion value** is purchase value (Q-4-5). An account with no purchases recorded shows 0 purchases, because Meta reports none. The page notes that purchases depend on the advertiser's Meta Pixel or Conversions API being set up.
- **Rates** are derived on read, exactly as in Phase 3: click-through rate, cost per click, cost per purchase, and purchase value per amount spent. Each says why when it cannot be computed.
- **Levels are never added into each other.** Account totals come from account-level rows, which also include deleted ads' activity.
- Google Ads and Meta figures appear side by side on the Advertising tab, **never summed** across platforms or currencies.

## 11. API

No new routes. The Phase 3 routes (`/ad-accounts`, `/ad-accounts/{id}`, `/metrics/daily`, `/campaigns`, `/campaigns/{id}`, `/resync`) serve Meta accounts too. Two additive fields:

- `connection_expires_at` on an ad account (when the sign-in ends; null for Google Ads);
- the existing `provider` field drives the "ad set" wording.

## 12. Web app

- **Connections page:**
  - "Connect Meta", with a note that AdVegaX only reads;
  - discovered accounts grouped under their business;
  - the sign-in's end date.
- **Advertising tab:** Google Ads and Meta accounts together, each labelled with its platform.
- **Account and campaign pages:**
  - "Ad sets" instead of "Ad groups" for Meta;
  - "Purchases" instead of "Conversions";
  - "Reported by Meta";
  - an expiry notice with a "Reconnect" link from 14 days before.
- Every page is checked for accessibility.

## 13. Security and privacy (additions to SECURITY.md)

- The app secret and tokens are encrypted at rest or kept in the secret store, never exposed (§7); `appsecret_proof` is on every call.
- **No personal data:** no Facebook name, email or picture is stored. Ad accounts hold no customer data. Breakdowns by age or gender are out of scope.
- **Read-only:** enforced by the static test, by the provider declaring no write capability, and by never requesting `ads_management`.
- **Tenant isolation:** the existing row-level security; the generated route sweeps already cover the advertising routes.
- **Meta Platform Terms and Developer Policies** apply once the app is live. The privacy policy must describe Meta ads data use and deletion (Meta requires a data-deletion instructions URL).

## 14. Testing

- **Meta simulator** (in-process, like the Google Ads one):
  - login dialog, code exchange, long-lived exchange, `debug_token`, revocation;
  - `me/adaccounts` with businesses;
  - campaigns, ad sets and ads with `effective_status` filtering;
  - insights at four levels with `time_increment=1`, `actions` and `action_values`, and usage headers;
  - async report jobs;
  - Meta's error format (190, 4, 17, 80004, 100/1487534);
  - accounts in an offset-100 currency (AUD) and an offset-1 currency (JPY).
- **Golden figures:** a fixed sample whose daily rows, totals and rates are hand-calculated, in both currency groups.
- **Journey test:**
  1. connect → discover (two businesses) → link two accounts → first import;
  2. 3-hour run → a correction picked up nightly → a too-large slice read through an async job;
  3. Meta's rate limit, then the expiry warning;
  4. permission removed → reconnect → disconnect (permission removed at Meta).

  Token and app-secret scans run over every response, the audit log and the logs.
- **Read-only static test**, tenant-isolation sweeps, a browser test with axe, and **no call to Meta in CI**.

## 15. Tasks (one at a time, report after each)

| Task | Content |
|---|---|
| 4-01 | Step 0 on the sandbox and one real account (§4.2), when the Meta app and network allow it |
| 4-02 | Meta sign-in (Login for Business, code and long-lived exchange, `appsecret_proof`, `debug_token`, revocation), Graph client (errors, paging, usage headers), simulator, read-only static test |
| 4-03 | Discovery (ad accounts by business, statuses), linking rules (Q-4-3), token expiry date |
| 4-04 | Structure import (campaigns, ad sets, ads incl. archived and deleted; budgets with the currency offset) |
| 4-05 | Insights import: 13 months, four levels, purchases with each ad set's attribution, exact money, account time zone, async jobs for large slices |
| 4-06 | Ongoing sync on the Phase 3 schedule, rate-limit pacing from Meta's headers, expiry warnings and "Needs reconnecting", health |
| 4-07 | API additions (§11) and web app (§12): Meta wording, business grouping, expiry notice, both platforms on the Advertising tab |
| 4-08 | Journey test, browser test, docs, `PHASE_04_REPORT.md` |

Estimate: **2–3 weeks** including your reviews. Meta's Business Verification and App Review (often 2–6 weeks) run in parallel and are needed only before real customers connect.

## 16. Acceptance criteria

1. A Facebook sign-in connects, discovers ad accounts by business, links them, and imports structure and 13 months of figures. It stays up to date, and handles a removed permission, an expiring token, a disabled account, Meta's rate limits, reconnect and disconnect without manual database work.
2. Daily figures match hand-calculated golden values to the cent in both currency groups, and match Ads Manager for one real account for a fixed week (Step 0 item 8).
3. Corrected past days are overwritten, with no stale or duplicated rows; deleted ads' activity is kept in account totals.
4. **No Meta call that changes anything exists in the code** (static test), and `ads_management` is never requested.
5. Tokens and the app secret never appear in responses, logs, audit, UI or AI context.
6. Missing data is never shown as 0 (unsynced days, divisions by zero, unavailable accounts). Google Ads and Meta figures are never added together.
7. All suites pass, with no calls to Meta in CI.

## 17. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Business Verification and App Review take weeks or need resubmission | **HIGH** | Start now (§2A); build with the simulator and your own accounts meanwhile; script the screencast once the pages exist |
| 60-day user tokens lapse when nobody reconnects | **HIGH** | Warnings at 14 and 3 days, "Needs reconnecting", one-click reconnect; system-user tokens once Tech Provider status is granted (Q-4-2) |
| Budgets off by 100× (currency offset) | MEDIUM | Offset table from Meta's docs, golden tests in AUD and JPY, Step 0 item 6 |
| Figures differ from Ads Manager (attribution, time zone, deleted ads) | MEDIUM | Each ad set's own attribution; account time zone; account totals from account rows; Step 0 items 7–8 |
| Meta's rate limits during first imports | MEDIUM | Usage-header pacing, monthly slices, async jobs for large slices, Full Access before the pilot |
| Meta changes or removes metrics with little notice (as in 2026) | LOW | Version in a setting, upgrade task per release, unknown values skipped and counted, never guessed |

## 18. Rollback

Meta is off by default (`META_ADS_ENABLED=false`) and can be switched off by configuration. No migration is expected; if Step 0 needs one, it will be additive and reversible. No existing table or route changes behaviour, and Google Ads is unaffected.

## 19. Approval checklist

Approve or change:

- **Q-4-1 … Q-4-12**;
- the read-only guarantee (§3, §7);
- the reuse of the Phase 3 model and schedule (§8, §9);
- task-by-task delivery 4-01 … 4-08.

No new runtime packages are proposed: the Graph client uses the existing `httpx`-based safe client, not Meta's SDK, to keep one hardened network path.

## Sources (checked 2026-10-18)

- Meta: [Graph and Marketing API versions](https://developers.facebook.com/docs/graph-api/changelog/versions/), [Introducing v26.0](https://developers.facebook.com/blog/post/2026/07/29/introducing-graph-api-v26-and-marketing-api-v26/), [Marketing API versioning](https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/versioning), [Access and authentication](https://developers.facebook.com/docs/marketing-api/access/), [Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/), [Authentication vs data access](https://developers.facebook.com/docs/facebook-login/auth-vs-data/), [OIDC code flow with PKCE](https://developers.facebook.com/documentation/facebook-login/guides/advanced/oidc-token.md), [Insights limits and best practices](https://developers.facebook.com/docs/marketing-api/insights/best-practices), [Ad account insights reference](https://developers.facebook.com/docs/graph-api/reference/adaccount/insights/), [Ad object status](https://developers.facebook.com/docs/marketing-api/best-practices/manage-your-ad-object-status), [Currencies and offsets](https://developers.facebook.com/docs/marketing-api/currencies), [Sandbox ad accounts](https://developers.secure.facebook.com/blog/post/2023/06/21/marketing-api-sandbox-capability-now-re-enabled).
- Trade press, cross-checked with Meta's pages: [attribution windows and retention changes (Jan 2026)](https://ppc.land/meta-restricts-attribution-windows-and-data-retention-in-ads-insights-api/), [v26.0 overview](https://ppc.land/meta-blocks-47-commerce-endpoints-as-graph-api-v26-0-lands-today/), [Q2 2026 Marketing API update](https://www.kitchn.io/blog/meta-marketing-api-q2-2026-update).
- Field notes (not official; to confirm in Step 0): [Meta Marketing API setup notes](https://github.com/amster93/meta-ads-api-notes) — token options and usage headers.
