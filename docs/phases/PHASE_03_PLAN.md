# Phase 3 — Google Ads (read-only): Implementation Plan

**Status:** ✅ **Approved by the product owner (2026-10-15, A21: "Approve all") with all §2 recommendations (Q-3-1 … Q-3-11).** Implementation authorized for Phase 3 only. · **Date:** 2026-10-15

> **Live tests (Q-3-10, option C):** build against Google's documentation and a simulator; Step 0 (3-01) runs when the developer token, the Google Cloud OAuth client and network access to Google's API are available.
**Depends on:** Phase 1 (connections, credentials, jobs, SSRF-safe client). Phases 2A and 2B are reviewed (A20) but not required. · **Followed by:** Phase 4 (Meta Ads), which reuses the advertising model built here.
**Governing documents:** MASTER_SPECIFICATION §7, §20 (D4, D5, D14, D19, D22), A2, A10, A13; ARCHITECTURE §9–§10; DATABASE_SCHEMA §8–§11 (target model); DISCOVERY_REPORT §5.5, §6; `phases/PHASE_03_GOOGLE_ADS.md` (outline); INTEGRATION_GUIDES §2.

---

## 1. Objective

Let an organization connect **Google Ads read-only** with one Google sign-in:

- see every ad account that sign-in can reach, including accounts under manager (MCC) accounts;
- choose which ad accounts to link;
- import each linked account's **campaign structure** (campaigns, budgets, ad groups, ads) and **daily performance** (impressions, clicks, cost, conversions, conversion value);
- keep both up to date, including when Google corrects past days.

At the end of Phase 3, on a Google Ads test account (structure) and the simulator (figures):

- a manager connects Google Ads and links two ad accounts in different currencies and time zones;
- campaigns, ad groups and ads appear with their status and budgets;
- daily figures appear per account, campaign, ad group and ad, **clearly labelled "reported by Google Ads"**, in the account's own currency and time zone;
- days Google later corrects are overwritten;
- disconnect, a revoked Google permission and reconnect work cleanly;
- **the code contains no call that changes anything in Google Ads.**

The advertising model is designed against **both Google Ads and Meta** from the start (lesson from 2B: design the shared model against two platforms). Meta is implemented in Phase 4.

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all recommendations at once, or change any of them.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-3-1** | Which Google Ads API version? | **The newest major version available when coding starts**: v25 today, v26 if Google has released it by then. Kept in a setting, with a yearly upgrade task. | Google releases a major version about every quarter and keeps each one for about a year (v25 sunsets August 2027, v26 about November 2027). Starting on the newest gives the longest time before the first forced upgrade. |
| **Q-3-2** | Which developer-token access level do we apply for? | **Now:** the token starts at *Test* (test accounts only). Apply for **Explorer** at once; it is usually granted automatically and reaches real accounts (2,880 operations a day). **Before the pilot:** apply for **Basic** (15,000 a day; needs Google Cloud brand verification first). **Standard** (unlimited, a 10-business-day audit) only when the pilot outgrows Basic, or for campaign building in Phase 10B. | The daily allowance is **shared by every AdVegaX customer**, because one developer token serves the whole product. Explorer is enough to develop and try a few real accounts; Basic covers a pilot of roughly 200 ad accounts with the sync pace in Q-3-5 (Explorer about 40). Google reports a review backlog, so apply early. |
| **Q-3-3** | Which accounts can be linked? | **Advertiser accounts only.** Manager accounts are shown as the groups their accounts sit in, but have no figures of their own. Cancelled or suspended accounts are listed as "not available" and cannot be linked. | Manager accounts do not run ads. Linking advertiser accounts keeps the figures unambiguous. |
| **Q-3-4** | What is imported? | **Structure:** campaigns (name, status, type, bidding strategy type, start/end dates, budget amount, budget period, shared or not), ad groups (name, status, type), ads (type, status, name where Google has one). **Daily figures** at four levels: account, campaign, ad group and ad. Measures: impressions, clicks, cost, conversions, conversion value. | That is what Phases 6–8 need for spend, ROAS and campaign comparison. Keywords, search terms, audiences and ad texts are left for the phases that use them, so nothing is collected without a purpose. Account totals come from Google's account-level figures, not from adding campaigns up, because some campaign types (e.g. Performance Max) have no ad groups. |
| **Q-3-5** | How fresh, and how are corrections handled? | **Every 3 hours:** today and yesterday. **Nightly:** the last 30 days are read again and overwritten. **Weekly:** the last 90 days. Plus "Sync now" (rate-limited, as for stores). Structure changes are checked with each 3-hour run. | Google updates cost about hourly, but conversions arrive up to 15+ hours later and can be credited to past days for weeks; invalid clicks are removed afterwards and month-end adjustments happen. Re-reading recent days keeps figures right. This pace costs about 70 operations per account per day (8 per 3-hour run, plus the re-reads), leaving room in the shared allowance (Q-3-2). An hourly pace would cost about 200 a day per account and cut the number of accounts a pilot can hold to about a third. |
| **Q-3-6** | How much history? | **13 months** on first link (same as stores). | Year-over-year comparison needs 13 months. Google keeps 11 years, and a longer import is cheap, but 13 months keeps the first import short and consistent. |
| **Q-3-7** | Which conversions? | **Google Ads' own "Conversions" column** (the conversion actions the advertiser marked as primary, credited to the day of the ad interaction), plus its conversion value. Shown as **"reported by Google Ads"**, never mixed with store sales. | It matches what the advertiser sees in Google Ads. AdVegaX's own attribution (store orders vs ad spend) comes in Phase 6 and is never based on one platform's claim (A2). |
| **Q-3-8** | Money and time | Cost is converted from Google's millionths of a unit to an exact decimal in **the account's currency**. Days are in **the account's time zone**. No currency conversion before Phase 6. | Accounts in different currencies are never added together without exchange rates (A10). |
| **Q-3-9** | Disconnect and people leaving | Disconnect **revokes AdVegaX's permission at Google** and deletes the stored token; imported data is kept. The page shows who connected Google Ads. If that person loses access, the connection shows **"Needs reconnecting"** and another manager can reconnect. | Google permissions belong to the person who signed in, not to the organization. |
| **Q-3-10** | Live test environment | Same choice as Shopify (2A §2A). **Recommended C now:** build against Google's documentation and a Google Ads simulator, and run live checks on a **test manager account** as soon as you have the developer token and the Google Cloud OAuth client and the network allows Google's API addresses. Test accounts show no figures (they never serve ads), so live checks cover connect, discovery and structure; figures are proven with the simulator and later on one real account under Explorer access. | This workspace cannot reach Google's API (checked 2026-10-15), and the Google sign-in needs an address your browser can return to (a staging server or tunnel). |
| **Q-3-11** | The same ad account in two organizations? | **Allowed.** Each organization connects with its own Google sign-in, which Google has given access to that account (e.g. the business and its agency). Unlike a store (Q6), nothing is retired at Google when a second organization connects. To be reviewed with agency mode (Phase 14). | Google lets several people and managers work on one account; refusing would block normal agency set-ups. Each organization only sees what its own sign-in can reach. |

## 2A. What you need to set up (long lead — start now)

1. **A Google Ads manager account for AdVegaX** (free). The developer token belongs to it: Google Ads → Admin → API Center → apply. The token starts at Test access.
2. **A Google Cloud project** with the Google Ads API switched on, an **OAuth consent screen** (app name AdVegaX, support email, home page, privacy policy) and a **web OAuth client**.
   - The Google Ads permission (`adwords`) is a "sensitive" permission. Until the app is verified, only listed test users can sign in, Google shows an "unverified app" warning, and sign-ins expire after 7 days.
   - Verification needs a public home page and privacy policy on our domain, domain ownership in Google Search Console, a short demo video and a reason for the permission. Google says it usually takes 3–5 business days.
   - **Brand verification** of the same project is required before applying for Basic access.
3. **A test manager account** (signed in with a Google account that is *not* linked to the real manager account), with two test advertiser accounts in different currencies and time zones.
4. The **developer token, OAuth client ID and client secret** go only into the local untracked settings file, never into chat or the repository (as for Shopify).

## 3. Scope

| Area | In scope |
|---|---|
| Advertising model | Platform-neutral tables for ad accounts, campaigns, budgets, ad groups, ads and daily performance, designed to fit Meta too (§8) |
| Google Ads provider | `app/providers/google_ads/`: Google sign-in (OAuth with PKCE, offline access), token refresh, REST calls to `googleads.googleapis.com` through the existing SSRF-safe client (fixed Google hosts only), Google Ads Query Language (GAQL) reads, error mapping, paging |
| Connect & discovery | One sign-in → accounts with direct access → each manager's hierarchy → one resource per advertiser account (name, currency, time zone, status, manager path) → the person links the ones they want |
| Sync | First import (structure + 13 months), 3-hour, nightly (30 days) and weekly (90 days) re-reads, "Sync now"; corrections overwrite |
| Quota | A shared daily allowance tracked per developer token; pacing and back-off; plain messages when Google says "too many requests" |
| Read-only guarantee | Only three Google Ads calls exist in the code: list accessible accounts, `search` and `searchStream`. A static test fails if any other Google Ads method appears |
| API / UI | Ad accounts list (status, currency, time zone, last sync), account page with daily totals and a campaign table, campaign page with ad groups and ads; every figure labelled "reported by Google Ads"; never 0 for missing data |
| Testing | Google Ads simulator, journey test, browser test with accessibility checks, read-only static test |
| Docs | INTEGRATION_GUIDES (Google Ads entry), DATABASE_SCHEMA, API_SPECIFICATION, SECURITY, report |

## 3A. Non-goals

- **Any change in Google Ads**: no creating, pausing or editing; no budget changes (Phase 10A/10B, through the Action Engine only).
- Keywords, search terms, audiences, ad texts and images, assets, recommendations, keyword planning (later phases, when used).
- Linking ad accounts to stores, currency conversion, ROAS against store sales, attribution (Phase 6).
- Google Analytics (Phase 5, a separate Google sign-in and connection).
- Google Ads offline conversion uploads or tags.
- Standard access and Required Minimum Functionality (only relevant to campaign management, Phase 10B).

## 4. Verified platform facts and Step 0

### 4.1 Verified against Google's documentation on 2026-10-15

1. **Versions:** v25 (July 2026) is the newest major version, with v25.2 (Sep 2026) the newest minor; sunset August 2027. v26 is expected in October 2026 (sunset about November 2027). From v26 Google releases twice a month; minor releases add features without breaking changes. v22 was switched off on 7 Oct 2026.
2. **Access levels** (daily operations): Test 15,000 (test accounts only); Explorer 2,880 on production accounts and 15,000 on test accounts (no account creation, user management, planning or billing services); Basic 15,000 (brand verification first); Standard unlimited (audit, about 10 business days). "Per day" is a sliding 24 hours per Google Cloud project.
3. **What counts as an operation:** each `search` or `searchStream` request counts as **one** operation, whatever the number of rows. Follow-up pages with a valid page token do not count. Rejected requests still count. Too many requests → `RESOURCE_EXHAUSTED` (HTTP 429).
4. **Sign-in:** OAuth 2.0 with the `https://www.googleapis.com/auth/adwords` scope, offline access (refresh token). The same scope covers read and write, so read-only is enforced in our code (§3).
5. **REST:** `POST https://googleads.googleapis.com/v25/customers/{id}/googleAds:search` (10,000 rows per page, `nextPageToken`) or `:searchStream` (whole result in one response), body `{"query": "<GAQL>"}`. Headers: `Authorization: Bearer …`, `developer-token`, and `login-customer-id` (the manager account) when reaching an account through a manager.
6. **Access model:** `customers:listAccessibleCustomers` returns **only accounts with direct access**. Accounts under a manager are found by querying the manager's hierarchy (`customer_client`) with that manager as `login-customer-id`. Read-only users exist; roles are inherited down the hierarchy.
7. **Test accounts** are created under a test manager account, never serve ads, and return **empty** impressions, cost and conversions. A Test-access token gets an authorization error on production accounts. Inactive test accounts are deleted after a year.
8. **Data freshness:** clicks, impressions and cost are refreshed about hourly; last-click conversions take about 3 hours and other attribution models about 15 hours. **Past days change**: invalid traffic is removed retroactively, conversions arrive days after the interaction, and month-end adjustments happen. Google gives no point at which a day is final.
9. **Reporting columns:** "Conversions" = `metrics.conversions`, "All conv." = `metrics.all_conversions`, "Conversions (by conv. time)" = `metrics.conversions_by_conversion_date`. Rows whose metrics are all zero are not returned.
10. **Google sign-in in testing mode:** only listed test users, an "unverified app" warning, and refresh tokens that expire after 7 days. Sensitive-scope verification needs a privacy policy, domain verification, a demo video and a home page.

### 4.2 Step 0 — verify on the test manager account (task 3-01)

1. Exact JSON shapes for the GAQL fields we read: are int64 values (cost in micros, ids) strings? Are dates `YYYY-MM-DD` in the account time zone?
2. `listAccessibleCustomers` and the `customer_client` hierarchy with a manager as `login-customer-id`, including a user with read-only access.
3. Errors and their codes: revoked permission, account cancelled or not enabled, no access, test token on a production account, quota exceeded, bad query.
4. Google's handling of PKCE and `prompt=consent` for a new refresh token on reconnect; the token revocation endpoint.
5. Campaign types without ad groups (Performance Max): what campaign and ad-group reports return.
6. Budget fields: daily vs total budget, shared budgets, budgets in micros.
7. Whether a removed campaign or ad still appears in reports for the days it ran.
8. **On one real account (under Explorer access):** our daily figures for a fixed week equal the Google Ads interface for the same days (cost, clicks, impressions, conversions, value).

## 5. Proposed structure

```text
backend/app/
├── providers/google_ads/          # Google-only: sign-in, REST client, GAQL queries, mapping, error codes
│   ├── provider.py  client.py  queries.py  mapping.py
├── domains/advertising/           # platform-neutral: models, import and sync, read service, routes
frontend/features/advertising/     # ad accounts list, account page, campaign page
```

The core never imports `providers/google_ads` (static test D19, extended). `AdvertisingProvider` (today an empty interface) gains the read methods the core needs: `discover_accounts`, `read_structure`, `read_performance`.

## 6. Connect, credentials and health

1. **Start:** a manager clicks "Connect Google Ads". The existing `POST /organizations/{org}/connections/google_ads/start` returns Google's sign-in address (scope `adwords`, offline access, PKCE, single-use state).
2. **Callback:** the existing OAuth callback exchanges the code (with the PKCE verifier) for tokens. Both are encrypted (1B). The person's Google account email is **not** stored. The connection records the AdVegaX user who connected it.
3. **One Google sign-in, one connection per organization.** The same Google sign-in may be connected in two organizations, and the same ad account may be linked in two organizations (Q-3-11).
4. **Discovery:** list direct accounts, read each manager's hierarchy, create one `ad_account` resource per advertiser account with its manager path. Managers themselves are not linkable (Q-3-3).
5. **Tokens:** access tokens (about 1 hour) are refreshed on demand under the existing per-connection lock. A refused refresh (`invalid_grant`: revoked, expired, password or test-mode limits) → **"Needs reconnecting"**.
6. **Health on the account page:** "Needs reconnecting", "This account was cancelled or suspended in Google Ads", "You no longer have access to this account", "Google's daily limit for AdVegaX was reached — figures will update later". Never an error code.
7. **Disconnect:** revoke the token at Google, delete it, stop syncs, keep the data. Reconnect reuses the connection and data.

## 7. Outbound safety and secrets

- Calls go only to fixed Google hosts (`googleads.googleapis.com`, `oauth2.googleapis.com`) through the existing SSRF-safe client: no addresses from users, HTTPS only, no redirects, size and time limits.
- **Secrets:** the developer token, the OAuth client secret and every access and refresh token are never logged, audited, returned, shown or given to AI (A12). The developer token and client secret live only in the local untracked settings file in development, and in the secret store when deployed.
- The **read-only static test** (§3) fails the build if any Google Ads call other than the three allowed ones is added.

## 8. Data model (additive migration 0012)

Designed for Google Ads and Meta. Names are platform-neutral: Google "ad group" and Meta "ad set" are both `ad_groups`.

| Table | Content |
|---|---|
| `ad_accounts` | extension of the `ad_account` resource: name, currency, time zone, status (`active`, `not_enabled`, `cancelled`, `suspended`, `closed`), manager path (display only), `history_from`, `first_import_completed_at`, health code |
| `ad_campaigns` | external id, name, status (`active`, `paused`, `removed`), channel or objective type (platform value + normalized family), bidding strategy type, start/end dates, `external_updated_at` |
| `ad_budgets` | external id, level (`campaign` / `ad_group`), period (`daily` / `lifetime`), amount (exact decimal) in the account currency, shared or not |
| `ad_groups` | external id, campaign, name, status, type |
| `ads` | external id, ad group, name (nullable), type, status |
| `ad_performance_daily` | account, level (`account` / `campaign` / `ad_group` / `ad`), entity, `day` (account time zone), impressions, clicks, cost, conversions (decimal: Google reports fractions), conversion value, currency, `source` (`platform_reported`), `fetched_at`. Unique per account, level, entity and day |
| `ad_sync_state` | per account: running mode, progress, last 3-hour / nightly / weekly run, last error code |

- Forced row-level security and composite organization keys on every table, as in 2A.
- Deleted structure is never removed: `status = removed` keeps history readable.
- A day that was never read has **no row**, and is shown as "not synced yet". A day read with no activity has a row with real zeros. Missing measures are NULL with a reason, never 0 (A10).
- No Google-specific columns in the core. Platform-only details go in a typed, display-only `provider_extensions` field (DISCOVERY_REPORT §5.4).

## 9. Import and sync

- **First import (per linked account):** structure, then daily figures for 13 months, read in monthly slices (one `searchStream` per level per slice, so about 52 operations), one slice per job step and resumable.
- **3-hour run:** structure (4 operations) and today + yesterday at four levels (4 operations).
- **Nightly:** the last 30 days at four levels, overwriting. **Weekly:** the last 90 days.
- **Quota:** a shared counter per developer token in Redis (sliding 24 hours). Accounts are spread over the 3 hours rather than all at once. At 80 % of the allowance, the nightly and weekly re-reads wait; at 100 % only "today" runs continue when the allowance frees up. On 429, back off and retry later; the account page says figures will update later.
- **Corrections:** each re-read replaces the rows for the days it covers. A row that disappears (an entity with no activity left after a correction) is set to zeros for that day, never left stale.
- **"Sync now":** the nightly-style 30-day re-read plus structure, with the per-account limit used for stores.

## 10. Figures

- **Platform-reported only.** Every figure is labelled "reported by Google Ads". No ROAS against store sales and no attribution in Phase 3 (Phase 6).
- **Derived on read** (A5): click-through rate = clicks ÷ impressions, cost per click = cost ÷ clicks, cost per conversion, conversion value ÷ cost. Each is "not available" when its divisor is 0.
- **Totals** for a period come from the account-level rows; campaign totals from campaign rows. Levels are never added into each other.
- **Recent days are marked "may still change"** (last 3 days by default, a setting), because Google's figures for them are not settled.

## 11. API

- Existing generic routes: start, callback, discover, link, unlink, disconnect, resources.
- New, under `/organizations/{org}`:
  - `GET /ad-accounts` (status, currency, time zone, sync, health);
  - `GET /ad-accounts/{id}`;
  - `GET /ad-accounts/{id}/metrics/daily?from&to` (account level; days and totals with availability);
  - `GET /ad-accounts/{id}/campaigns?from&to` (structure + period figures);
  - `GET /campaigns/{id}` (with ad groups and ads + period figures);
  - `POST /ad-accounts/{id}/resync`.
- Same rules as the store API: all members can read, managers and above can "Sync now", 404 for other organizations' data, exact decimal strings, availability and reason on every missing value.

## 12. Web app

- **Connections page:** "Connect Google Ads". After sign-in, the discovered accounts are grouped under their manager; the person ticks the ones to link.
- **Advertising tab:** ad accounts with status, currency, time zone and last update.
- **Account page:** daily totals (spend, clicks, impressions, conversions, value, and the derived rates), a date range as on the store page, the campaign table, a health panel, "Sync now". Recent days are marked "may still change".
- **Campaign page:** budget, status, ad groups and ads with their figures.
- Every page labelled "reported by Google Ads", and checked for accessibility.

## 13. Security and privacy (additions to SECURITY.md)

- **Tokens and the developer token:** encrypted at rest or kept in the secret store; never exposed (§7).
- **No personal data:** the person's Google email and name are not stored. Ad accounts hold no customer data.
- **Read-only:** enforced by the static test and by the provider declaring no write capability.
- **Tenant isolation:** row-level security on every new table; generated route sweeps cover every new route.
- **Google's API Services User Data Policy** applies once the app is verified. The privacy policy must describe Google Ads data use (item for the privacy policy you are preparing).

## 14. Testing

- **Google Ads simulator** (in-process, like the Shopify and WooCommerce ones):
  - sign-in and token endpoints, including refusal and revocation;
  - `listAccessibleCustomers` and manager hierarchies;
  - GAQL `search` (paged) and `searchStream` for the queries we send, with realistic JSON;
  - errors (revoked, no access, account cancelled, 429, bad query);
  - a test-access token refused on production accounts;
  - accounts in two currencies and time zones;
  - corrections to past days;
  - a Performance Max campaign without ad groups.
- **Golden figures:** a fixed sample whose daily rows, totals and derived rates are calculated by hand.
- **Journey test:** connect → discover (with a manager) → link two accounts → first import → 3-hour run → a correction picked up nightly → quota limit → permission revoked → reconnect → disconnect (token revoked at Google), with token and developer-token scans of every response, the audit log and the logs.
- **Read-only static test**, quota tests, tenant-isolation sweeps.
- **Browser test** with a simulated Google Ads connection, with axe.
- **No call to Google in CI.**

## 15. Tasks (one at a time, report after each)

| Task | Content |
|---|---|
| 3-01 | Step 0 on the test manager account (§4.2), when the credentials and network allow it |
| 3-02 | Advertising model + migration 0012; `AdvertisingProvider` read interface; read-only static test |
| 3-03 | Google sign-in (PKCE, offline), token refresh and revocation, Google Ads REST client (headers, errors, paging), simulator |
| 3-04 | Discovery (direct accounts + manager hierarchies), linking rules (Q-3-3) |
| 3-05 | Structure import (campaigns, budgets, ad groups, ads) |
| 3-06 | Performance import: 13-month first import, four levels, exact money, account time zone |
| 3-07 | Ongoing sync: 3-hour, nightly, weekly re-reads, corrections, shared quota and pacing, "Sync now", health |
| 3-08 | Read API (§11) with availability and derived rates |
| 3-09 | Web app (§12) |
| 3-10 | Journey test, browser test, docs, `PHASE_03_REPORT.md` |

Estimate: **2–3 weeks** including your reviews, plus Google's review times for the developer token and app verification, which run in parallel.

## 16. Acceptance criteria

1. A Google Ads sign-in connects, discovers accounts directly and under managers, links advertiser accounts, imports structure and 13 months of figures, stays up to date, and handles revoked permission, a cancelled account, the daily limit, reconnect and disconnect without manual database work.
2. Daily figures match hand-calculated golden values to the cent, and match the Google Ads interface for one real account for a fixed week (Step 0 item 8).
3. Corrected past days are overwritten; no stale or duplicated rows.
4. **No Google Ads call that changes anything exists in the code** (static test).
5. Tokens, the developer token and the client secret never appear in responses, logs, audit, UI or AI context.
6. Missing data is never shown as 0 (unsynced days, divisions by zero, accounts not available).
7. All suites pass, with no calls to Google in CI.

## 17. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Developer-token review delays (Google reports a backlog) | **HIGH** | Apply now; build with the simulator and test accounts meanwhile; Explorer is usually automatic |
| Google app verification (sensitive scope) blocks real users | **HIGH** | Prepare home page, privacy policy, domain verification and demo video early; test users until then |
| Shared daily allowance across all customers | MEDIUM | 3-hour pace, shared counter and pacing, Basic before the pilot, Standard when needed |
| Figures differ from the Google Ads interface (time zone, removed items, conversion column) | MEDIUM | Step 0 item 8; account time zone; "Conversions" column as in the interface |
| A connector person leaves the organization | MEDIUM | "Needs reconnecting"; any manager can reconnect; who connected is shown |
| Quarterly API versions and yearly sunsets | LOW | Version in a setting; yearly upgrade task with simulator refresh |
| Test accounts have no figures | LOW | Simulator for figures; one real account under Explorer for the comparison |

## 18. Rollback

The migration is additive: downgrade to 0011. The provider is off by default (`GOOGLE_ADS_ENABLED=false`) and can be switched off by configuration. No existing table or route changes behaviour.

## 19. Approval checklist

Approve or change: **Q-3-1 … Q-3-11**, the read-only guarantee (§3, §7), the advertising model (§8), the sync pace (§9), and task-by-task delivery 3-01 … 3-10. No new runtime packages are proposed: the REST client uses the existing `httpx`-based safe client, not Google's client library, to keep one hardened network path.

---

**Sources (verified 2026-10-15):**
- Google Ads API: [Access levels and permissible use](https://developers.google.com/google-ads/api/docs/access-levels), [Quotas](https://developers.google.com/google-ads/api/docs/best-practices/quotas), [Release notes](https://developers.google.com/google-ads/api/docs/release-notes), [v22 sunset reminder](https://ads-developers.googleblog.com/2026/09/google-ads-api-v22-sunset-reminder.html), [Multi-user authentication](https://developers.google.com/google-ads/api/docs/oauth/multi-user-authentication), [REST authorization and headers](https://developers.google.com/google-ads/api/rest/auth), [REST search and searchStream](https://developers.google.com/google-ads/api/rest/common/search), [Access model](https://developers.google.com/google-ads/api/docs/oauth/access-model), [Test accounts](https://developers.google.com/google-ads/api/docs/best-practices/test-accounts), [Conversion reporting](https://developers.google.com/google-ads/api/docs/conversions/reporting), [Account hierarchy sample](https://developers.google.com/google-ads/api/samples/get-account-hierarchy).
- Google Ads Help: [About data freshness](https://support.google.com/google-ads/answer/2544985).
- Google Identity: [Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification).
- Release cadence and backlog (trade press, cross-checked with Google's pages): [v26 twice-monthly releases](https://ppc.land/google-ads-api-moves-to-two-releases-a-month-starting-with-v26/), [version and sunset table](https://www.digitalapplied.com/blog/google-ads-api-versions-sunset-dates-v22-deadline), [Explorer tier and review backlog](https://ppc.land/google-faces-developer-token-application-backlog-as-new-api-tier-debuts/).
- To confirm in Step 0: the refresh-token rules in testing mode (from Google's verification page and [this summary](https://www.unipile.com/google-oauth-refresh-token/)), and that `adwords` is classed as a sensitive scope (as Google's developer forum describes it).
