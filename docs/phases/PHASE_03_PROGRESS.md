# Phase 3 — Task Reports

Plan: `PHASE_03_PLAN.md` (approved 2026-10-15, A21, all recommendations). One report per task; `PHASE_03_REPORT.md` follows task 3-10.

| Task | Status |
|---|---|
| 3-01 Step 0 on the test manager account | ⏸ Waiting — needs the developer token, the Google Cloud OAuth client and network access to Google's API (Q-3-10, option C) |
| 3-02 Advertising model + migration 0012; read interface; read-only guard | ✅ Done |
| 3-03 Google sign-in, token refresh and revocation, REST client, simulator | ✅ Done |
| 3-04 Discovery and linking rules | ✅ Done |
| 3-05 Structure import | ✅ Done — awaiting review |
| 3-06 Performance import | ✅ Done — awaiting review |
| 3-07 Ongoing sync | ✅ Done — awaiting review |
| 3-08 Read API | ✅ Done — awaiting review |
| 3-09 Web app | Not started |
| 3-10 Journey test, browser test, docs, report | Not started |

---

## 3-01 — Step 0 on the test manager account

Waiting. Step 0 needs:
- the AdVegaX Google Ads manager account and its developer token;
- the Google Cloud project with an OAuth client;
- a test manager account;
- network access to `googleads.googleapis.com`, `oauth2.googleapis.com` and `accounts.google.com`. This workspace was refused on 2026-10-15.

Until then, work follows option C: build against Google's documentation and a simulator. Everything Step 0 would confirm is marked "to confirm live".

---

## 3-02 — Advertising model, read interface, read-only guard (2026-10-16)

**Completed**
- **Advertising tables (migration 0012), the same for Google Ads and Meta:**
  - ad accounts;
  - budgets (daily or lifetime, shared or not, amount "not available" rather than 0);
  - campaigns, ad groups (Google ad groups and Meta ad sets) and ads;
  - daily performance at four levels (account, campaign, ad group, ad);
  - per-account sync state.
- **How the tables behave:**
  - every table is separated by organization with forced row-level security, as for stores;
  - money is exact, in the ad account's currency, and days are in the account's time zone;
  - removed campaigns, ad groups and ads are kept, so past figures stay readable;
  - each level is stored as Google reports it and never added into another. Some campaign types, such as Performance Max, have no ad groups, so account totals come from Google's account-level figures.
- **Discovery details on accounts:** each discovered account can say why it cannot be linked (a manager account, or a cancelled one), which groups it sits in (for display), and how to reach it again (Google Ads: the manager to sign in through). None of these is a secret.
- **Provider read interface:**
  - read an account's state (name, currency, time zone, status);
  - read its structure;
  - read daily figures for a level and a date range.

  No write method exists.
- **Read-only guard:** a build check fails if an advertising provider (Google Ads now, Meta later) names any Google Ads call other than the three allowed reads (list accessible accounts, `search`, `searchStream`), any "mutate", upload or create call, or declares a campaign-writing capability.

**Files changed** (9)
- New (4): `alembic/versions/0012_advertising.py`, `app/domains/advertising/{__init__,models}.py`, `tests/security/test_advertising_data.py` (18 tests).
- Modified (5):
  - `app/db/models.py`;
  - `app/domains/integrations/models.py` (discovery details);
  - `app/providers/base/{types,interfaces}.py`;
  - `tests/security/test_static_rules.py` (3 tests);
  - docs `DATABASE_SCHEMA.md` §4B, `PHASE_03_PLAN.md` (approval recorded), `PROJECT_STATUS.md`, `ROADMAP.md`, `AI_CONTEXT.md`, this report.
- Deleted: none.

**Tests**
- **21 new.** They cover:
  - organizations see and change only their own advertising rows, and cannot insert rows for another one;
  - links between tables cannot cross organizations;
  - money and conversions are exact decimals;
  - a measure Google did not provide stays empty, not 0;
  - one row per account, level, entity and day;
  - invalid rows (bad level, negative clicks, an account-level row naming an entity) are refused;
  - removing a campaign keeps its daily rows;
  - unlinking removes the account's data;
  - the read-only guard catches write calls and passes the allowed reads.
- The migration tests (upgrade, downgrade, upgrade again; row-level security on every table) include 0012.
- **Backend `make check`: 820 passed**, coverage 97 %. **Frontend `npm run check`: 343 passed** (unchanged). **E2E: 11 passed.**

**Security:** no new endpoint, secret or input. Tenant isolation is enforced by row-level security and composite keys on every new table. Read-only is enforced by the static guard.

**Migration:** `0012_advertising`. It only adds; downgrade to 0011 removes everything it added.

**Deviations**
1. **The account's manager path lives on the discovered resource** (`external_resources.group_path`), not on `ad_accounts`. Discovery shows it before an account is linked. The plan listed it under `ad_accounts`.
2. **Three discovery columns on `external_resources`** (any provider), not only advertising tables. They let the Connections page explain an account that cannot be linked, and let the provider reach an account through its manager.
3. **Table names are prefixed** (`ad_campaigns`, `ad_budgets`) so they cannot be confused with future campaign-planning tables (Phases 8–10).

**Blocked:** Step 0 (3-01), as above.

**Next task:** 3-03, the Google Ads connection:
- Google sign-in with PKCE and offline access;
- token refresh and revocation;
- the REST client (fixed Google hosts, headers, error codes, paging);
- the Google Ads simulator.

---

## 3-03 — Google sign-in, tokens, Google Ads client, simulator (2026-10-16)

**Completed**
- **Connect Google Ads:**
  - a manager clicks Connect and is sent to Google's own sign-in and consent page. AdVegaX asks for **Google Ads access only** (plus Google's account id, see deviation 1), with PKCE and offline access, so syncs can run while nobody is signed in;
  - after approval, the code is exchanged for tokens, which are stored encrypted. If the person unticks Google Ads on the consent page, nothing is connected and the reason is shown.
- **Keeping access fresh:**
  - Google's access token lasts about an hour and is renewed before it expires;
  - if Google refuses the renewal (permission removed, password or testing-mode limits), the connection shows **"Needs reconnecting"**.
- **Reconnect and sharing:**
  - reconnecting with the same Google account reuses the same connection, so linked accounts and data are kept;
  - another Google account becomes a second connection;
  - the same Google account can also be connected by another organization, such as an agency (Q-3-11).
- **Disconnect** removes AdVegaX's permission at Google and always deletes our copy, even if Google cannot be reached.
- **Google Ads client**, read-only:
  - lists the accounts a person can reach directly, and runs reports with `search` (all pages) and `searchStream`;
  - sends the developer token and, for accounts under a manager, the manager's id;
  - checks account ids before use;
  - calls only Google's fixed addresses, through the existing safe client.
- **Plain error codes** for every situation the plan lists:
  - no access to the account;
  - account cancelled or not enabled;
  - developer token not approved for real accounts (Test access);
  - wrong developer token;
  - person has no Google Ads account;
  - Google's limit reached, with Google's suggested wait;
  - bad query, temporary problems.
- **Google Ads simulator:**
  - Google's sign-in (consent, PKCE check, refresh, revoke);
  - manager hierarchies and Google's access rules;
  - test vs real accounts and Test vs Explorer tokens;
  - paged and streamed reports;
  - errors in Google's own format.
- **Settings:** `GOOGLE_ADS_ENABLED` (off), client id, client secret, developer token (secrets only from the secret store or the local untracked settings file), API version `v25`. Google Ads is offered only when all of them are set.

**Files changed** (16)
- New (7): `app/providers/google_ads/{__init__,client,provider}.py`, `tests/google_ads_sim.py`, `tests/providers/test_google_ads_client.py` (35 tests), `tests/providers/test_google_ads_provider.py` (50 tests), `tests/api/test_google_ads_connect.py` (18 tests).
- Modified (9):
  - `app/providers/base/{types,registry}.py`;
  - `app/core/settings.py`;
  - `app/domains/integrations/service.py` (connections whose platform account may serve several organizations);
  - docs `INTEGRATION_GUIDES.md` (Google Ads entry), `SECURITY.md` (Google sign-in), `PROJECT_STATUS.md`, this report.
- Deleted: none. No migration. No web-app change (Google Ads is off and its pages come in 3-09).

**Tests**
- **103 new.** They cover:
  - sign-in address, scopes, PKCE, offline access and consent;
  - stored tokens never appearing in responses, the audit log, the logs or the encrypted row in plain text;
  - declining, unticking Google Ads, a refused code, and single-use state;
  - renewal before expiry, a new refresh token from Google being saved, and a refused renewal → "Needs reconnecting";
  - reconnect reuse, a second Google account, and the same Google account in another organization;
  - disconnect revoking at Google, including when Google is unreachable;
  - ID-token rules (issuer, audience, expiry, account id);
  - headers, manager access, paging and streaming;
  - account-id checks and every error code;
  - Test token vs real accounts;
  - calls to private addresses refused;
  - offered only when fully configured.
- Google Ads code coverage: client 97 %, provider 100 %.
- **Backend `make check`: 923 passed**, coverage 97 %. **Frontend `npm run check`: 343 passed** (unchanged). **E2E: 11 passed.**

**Security**
- No secret ever leaves the server; the tests scan for the tokens, the client secret and the developer token.
- Only Google's fixed addresses are called. Read-only is enforced by the static guard (three read calls only).
- The Google account's email and name are never requested.

**Deviations**
1. **`openid` is requested alongside Google Ads.** It gives only Google's stable account id, which is how AdVegaX recognises a reconnect by the same person and keeps the connection and its data. No email, name or picture is requested or stored. The consent page may mention "associate you with your personal info on Google"; to confirm in Step 0.
2. **A connection can be marked "per organization".** The same Google account can be connected in two organizations without the store rule ("one live connection per account", Q6) blocking it. Stores keep that rule.
3. **Discovery is not part of this task.** A connection made now finds no accounts until 3-04; Google Ads stays switched off until the phase is done.

**Blocked:** Step 0 (3-01), as before.

**Next task:** 3-04 — discovery:
- direct accounts and each manager's hierarchy;
- one linkable entry per advertiser account, with its name, currency, time zone and manager path;
- manager and cancelled accounts shown but not linkable (Q-3-3).

---

## 3-04 — Finding ad accounts and the linking rules (2026-10-16)

**Completed**
- **Every account the sign-in can reach is found:**
  - the accounts the person was invited to directly;
  - every account under a manager (MCC), however deep. Each manager's list is read through the top manager, as Google's access rules require.
- **Advertiser accounts are listed** with their name, currency, time zone and the managers above them (for example "Agency > Retail clients").
  - Manager accounts are not listed themselves; they appear only as that path (Q-3-3).
  - An account the person can also reach directly is listed once.
- **Accounts that cannot be used are listed with the reason, and cannot be linked:**
  - cancelled, suspended or closed;
  - a real account while AdVegaX's developer token still has Test access only;
  - no access;
  - missing currency or time zone.

  Trying to link one gives a clear message (`RESOURCE_UNAVAILABLE`, with the reason).
- **Checking again** ("Check for new accounts") updates reasons and paths. An already linked account that is later cancelled stays linked, so its data remains readable; its health message comes in 3-07.
- **Robust:**
  - a manager that cannot be read hides only its own accounts;
  - loops in a hierarchy are read once;
  - limits (500 direct accounts, 200 managers, 5,000 accounts) protect the shared daily allowance;
  - unreadable rows are skipped;
  - a person with no Google Ads account simply finds none.
- **Cost:** one request to list accounts, plus one per account or manager read (4 for the sample hierarchy).

**Files changed** (14)
- New (2): `app/providers/google_ads/queries.py`, `tests/api/test_google_ads_discovery.py` (13 tests).
- Modified (12):
  - `app/providers/google_ads/provider.py`;
  - `app/domains/integrations/{jobs,service,schemas}.py` (store and show the reasons and paths; refuse linking);
  - `tests/google_ads_sim.py` (manager hierarchies answered like Google);
  - `tests/api/test_google_ads_connect.py`, `tests/providers/test_google_ads_provider.py`;
  - frontend `lib/api/errors.ts` (message for the new code), `lib/api/openapi.json`, `lib/api/schema.d.ts` (regenerated);
  - docs `API_SPECIFICATION.md`, `INTEGRATION_GUIDES.md`, this report.
- Deleted: none. No migration (the columns came with 0012).

**Tests**
- **13 new.** They cover:
  - direct and manager accounts with their details and path;
  - each manager read once through the top manager;
  - an account reached two ways, listed once;
  - linking available accounts, and refusing unavailable ones with the reason;
  - rediscovery updating reasons and keeping links;
  - a person without Google Ads;
  - an unreadable manager;
  - a Test token and a real account;
  - missing time zone or currency;
  - a loop in the hierarchy;
  - the limits;
  - unreadable rows.
- Google Ads provider coverage 99 %.
- **Backend `make check`: 936 passed**, coverage 97 %. **Frontend `npm run check`: 343 passed**, build passes. **E2E: 11 passed.**

**Security**
- The manager used to reach an account (`access_hint`) is kept internally and not shown by the API.
- Discovery only reads, through the three allowed calls.

**Deviations**
1. **Cancelled or suspended accounts stay linked if they were linked before.** Their data stays readable, and the account page will say why it no longer updates (3-07). The plan only said such accounts cannot be linked.
2. **A new reason, `account_details_missing`**, for an account Google returns without a currency or with a time zone AdVegaX cannot use. Figures could not be shown correctly for it.

**Blocked:** Step 0 (3-01). The JSON shape of the hierarchy answers (camelCase keys, numbers as text) is to be confirmed there.

**Next task:** 3-05 — structure import:
- linking an ad account creates it in AdVegaX;
- campaigns, budgets, ad groups and ads are imported, removed ones included so history stays readable.

---

## 3-05 — Importing campaigns, budgets, ad groups and ads (2026-10-18)

**Completed**
- **Linking an ad account creates it in AdVegaX** and starts its import, which runs as short background steps, one at a time:
  - name, currency and time zone;
  - Google's status for the account;
  - 13 months of history to come.

  Linking it again later reuses the same account; nothing is duplicated.
- **Structure is imported:**
  - **Budgets:** daily, or a total for the campaign's run; shared or not. The amount is exact, in the account's currency, and empty (never 0) when Google gives none.
  - **Campaigns:** status, type (Search, Performance Max …), bidding strategy, start and end dates, and budget.
  - **Ad groups and ads:** status and type.
  - **Removed items are imported and kept**, so their history stays readable. Items Google stops listing are left as they are, never deleted.
  - A row with a status AdVegaX does not recognise is skipped and counted, never guessed.
- **Cost:** five requests to Google per account (the account and the four structure lists), each through the account's manager when it has one.
- **Problems with one account stay with that account.** The connection is never marked:
  - an account that is cancelled, suspended or closed shows **"account not enabled"** and is not imported;
  - lost access to one account shows **"no account access"**;
  - a permanent problem (for example, a query Google refuses) ends the import with its code and is not retried;
  - temporary problems are retried.
- **Safety:**
  - a duplicated background step stops at once;
  - a change of currency or time zone reported by Google is recorded as a warning, never applied silently.

**Files changed** (19)
- New (4): `app/domains/advertising/importer.py`, `app/providers/google_ads/mapping.py`, `tests/api/test_google_ads_structure.py` (10 tests), `tests/providers/test_google_ads_mapping.py` (22 tests).
- Modified (15):
  - `app/providers/google_ads/{provider,queries,client}.py`;
  - `app/providers/base/errors.py`: a new kind of error for "one account cannot be used", which never marks the connection;
  - `app/domains/integrations/service.py`: linking starts the import;
  - `app/workers/job_tasks.py`, `app/core/settings.py` (`ADS_HISTORY_WINDOW`, 13 months);
  - `tests/google_ads_sim.py` (accounts and structure answered like Google);
  - `tests/providers/test_google_ads_{client,provider}.py`;
  - docs `INTEGRATION_GUIDES.md`, `PROJECT_STATUS.md`, this report.
- Deleted: none. No migration (the tables came with 0012).

**Tests**
- **32 new.** They cover:
  - the full structure of a sample account (exact budgets, statuses, dates, removed items kept, an unknown status skipped);
  - five requests through the manager, or none through a manager for a direct account;
  - a new import updating and never deleting;
  - a cancelled or closed account;
  - lost access never marking the connection;
  - a permanent error not retried;
  - relinking reusing the account;
  - a duplicated step;
  - money, ids, dates and statuses read exactly;
  - odd answers from Google.
- **Backend `make check`: 968 passed**, coverage 97 %. **Frontend `npm run check`: 343 passed** (unchanged). **E2E: 11 passed.**

**Security**
- Only reads, through the allowed `searchStream` call.
- Tenant isolation: every row is written in the organization's own context, with row-level security.

**Deviations**
1. **Campaign dates use Google's newer date fields** (`start_date_time` / `end_date_time`, since v23). The older ones the plan research assumed were removed. Only the date part is kept, in the account's time zone.
2. **Per-account problems use a new error kind.** It never marks the connection: one cancelled or inaccessible account must not make the whole Google connection show a problem.
3. **No ad texts or names beyond what Google stores on the ad**, as agreed (Q-3-4). Many Google ads have no name.

**Blocked:** Step 0 (3-01). The answer shapes are to be confirmed there.

**Next task:** 3-06 — daily figures:
- 13 months of daily figures at account, campaign, ad group and ad level, read in monthly slices;
- impressions, clicks, exact cost, conversions and conversion value, in the account's time zone.

## 3-06 — Importing 13 months of daily figures (2026-10-18)

**Completed**
- **After the structure, the import reads 13 months of daily figures** for each linked account:
  - four levels: account, campaign, ad group and ad;
  - impressions, clicks, cost, conversions and conversion value;
  - one calendar month per background step (4 requests a month, about 56 for a first import), so a long import is resumable and never one huge request.
- **Exact and in the account's own terms:**
  - cost is exact to the millionth, in the account's currency (from Google's micros);
  - fractional conversions are kept;
  - days are the **account's own days** (an account in Los Angeles is still on 13 October when Sydney is on the 14th).
- **Zero only where Google says zero:** Google sends nothing for a day without activity; the account total then gets a real 0 for that day, so every day of the 13 months is present. Lower levels have no row for a quiet day.
- **Corrections overwrite:** every month read replaces what was stored for its days, so a cost Google later corrects, or activity it removes, never leaves an old number behind.
- **Nothing is lost or invented:**
  - figures for a campaign AdVegaX could not store (unknown status) are kept, just not linked;
  - Performance Max campaigns have campaign figures without ad groups; levels are never added together;
  - a row Google sends twice is stored once; an unreadable row is skipped and counted.
- **Problems:** a temporary error repeats the same month; a permanent one ends the import with its code (the structure stays); lost access marks only the account. When the per-connection limit is reached, the step simply waits and continues.

**Files changed** (11)
- New (1): `tests/api/test_google_ads_performance.py` (23 tests).
- Modified (10):
  - `app/providers/google_ads/{queries,mapping,provider}.py`: the daily-figures query, exact reading of Google's rows, and `read_performance`;
  - `app/domains/advertising/importer.py`: monthly slices, replacing stored days, zero days, links, progress;
  - `tests/google_ads_sim.py`: daily figures answered like Google (zero metrics left out);
  - `tests/providers/test_google_ads_{mapping,provider}.py`, `tests/api/test_google_ads_structure.py`;
  - docs `INTEGRATION_GUIDES.md`, `DATABASE_SCHEMA.md`, `PROJECT_STATUS.md`, this report.
- Deleted: none. No migration (the table came with 0012).

**Tests**
- **40 new** (23 import + 17 reading). They cover:
  - every day of 13 months present, exact figures on active days, real zeros on quiet days;
  - 14 monthly slices with no gap or overlap, 4 levels each, through the manager;
  - the account's own time zone;
  - corrections replacing old figures;
  - unlinked figures kept, duplicates stored once;
  - a failed month repeated, a permanent error, lost access, the per-connection limit;
  - month boundaries (leap year, year end) and Google's row formats.
- **Backend `make check`: 1,008 passed**, coverage 97 %. **Frontend `npm run check`: 343 passed** (unchanged). E2E not rerun: no web or API change.

**Security**
- Only reads, through the allowed `searchStream` call; no new endpoint.
- Every row is written in the organization's own context, with row-level security.

**Deviations**
1. **An ad's figures are keyed by ad group and ad** (`2101~90001`). Google identifies an ad within its ad group, so this keeps two ad groups' figures apart.
2. **Values too large to store are skipped**, not cut: conversions and values above 14 digits before the point, which Google should never send.
3. **Until 3-07, a new import of an already-imported account re-reads the full 13 months.** The shorter nightly (30 days) and weekly (90 days) re-reads come with 3-07.
4. **When the per-connection limit pauses a month, the levels already read for it are read again.** That costs at most three extra requests in that case; the shared daily allowance (3-07) will keep this in check.

**Blocked:** Step 0 (3-01). The answer shapes are to be confirmed there.

**Next task:** 3-07 — staying up to date:
- every 3 hours: today and yesterday, plus structure changes;
- nightly: the last 30 days; weekly: the last 90 days;
- "Sync now", the shared daily allowance, and account health.

## 3-07 — Keeping ad accounts up to date (2026-10-18)

**Completed**
- **Linked accounts now stay up to date by themselves.** A scheduler checks every 5 minutes which run each account is due for:
  - **every 3 hours:** campaigns, budgets, ad groups and ads (so new or renamed campaigns appear), plus today's and yesterday's figures: 9 requests;
  - **every night:** the last 30 days are read again: 4 requests;
  - **every week:** the last 90 days are read again: 4 requests.
- **Corrections are picked up.** Google changes past days (late conversions, removed invalid clicks); each re-read replaces the days it covers and never touches older days.
- **The shared Google allowance is protected.** One Google Ads developer token serves every AdVegaX customer, so every request is counted in one shared counter (last 24 hours):
  - at 80 % used, the nightly and weekly re-reads wait, so first imports, 3-hour updates and "Sync now" keep working;
  - at 100 %, every run waits 15 minutes and continues by itself; nothing is marked as broken and no retry is used up;
  - if Google says "too many requests", every account waits for the time Google gives.
- **"Sync now" is ready behind the scenes:** campaigns plus the last 30 days, at most 6 times an hour per account, never held back by the 80 % rule. It is refused while a run is going or when the account is not linked. If the first import had failed, it starts it again. The button and its web address come with 3-08 / 3-09.
- **Health clears itself:** when an account that had lost access answers again, the warning disappears. A currency or time-zone change at Google stays flagged.
- **Fix found while testing:** sign-in problems that appeared in the middle of reading campaigns or figures were not marking the connection. They now do.

**Files changed** (20)
- New (3): `app/domains/advertising/quota.py` (the shared counter), migration `0013_ad_sync_schedule.py`, `tests/api/test_google_ads_sync.py` (30 tests).
- Modified (17):
  - `app/domains/advertising/importer.py`: run modes, schedule, "Sync now", waiting for the allowance, health;
  - `app/providers/base/{errors,interfaces,registry}.py`, `app/providers/google_ads/{client,provider}.py`: the allowance and its cost per request;
  - `app/core/settings.py`, `app/workers/{celery_app,job_tasks}.py`: the schedule;
  - `frontend/lib/api/errors.ts`: one new message; "already being updated" now fits stores and ad accounts;
  - `tests/api/test_google_ads_performance.py`: a re-link now reads 30 days again, not 13 months;
  - docs `INTEGRATION_GUIDES.md`, `DATABASE_SCHEMA.md`, `SECURITY.md`, `ARCHITECTURE.md`, `PROJECT_STATUS.md`, this report.
- Deleted: none.

**Tests**
- **30 new.** They cover:
  - nothing due right after the first import;
  - the 3-hour run (structure changes, the account's own two days);
  - a correction missed by the 3-hour run and picked up nightly; the weekly 90 days;
  - which run comes first; unlinked accounts and stale runs;
  - the 80 % and 100 % limits; Google's "too many requests" holding every account; Google's wait time;
  - "Sync now": its window, the limit per account, a run already going, an unlinked account, a failed first import;
  - health clearing; the scheduler reading only four columns of other organizations' accounts.
- **Backend `make check`: 1,038 passed**, coverage 97 %. **Frontend `npm run check`: 343 passed.** E2E not rerun: no page changed.

**Security**
- The scheduler's system access is limited to **four columns** of the ad accounts table: id, organization, platform, and when the first import finished. It can never read names or figures (tested).
- The counter's key names only the platform, never the developer token.
- Everything else runs under each organization's own context with row-level security. Only reads to Google.

**Migration:** `0013` adds that four-column read permission. It is additive; downgrade removes it.

**Deviations**
1. **The "Sync now" web address comes in 3-08** with the other ad account addresses, so permissions and errors are set up in one place. The logic, limits and tests are done here.
2. **"Nightly" means 24 hours after the last nightly run**, not a fixed time of night; accounts therefore spread over the day.
3. **Corrections remove an entity's row for a day instead of writing zeros** (the plan says zeros). Totals are the same, and it matches how the first import stores quiet days. The account level always has a row for every day.
4. **The 3-hour run uses 9 requests, not 8**: the account's own details (status, name) are read with the structure, so health stays current.

**Blocked:** Step 0 (3-01) still needs network access to Google and your Google credentials.

**Next task:** 3-08 — the ad account API:
- ad account list and detail, with sync status and health;
- daily totals, campaigns with period figures, and one campaign with its ad groups and ads;
- the "Sync now" address.

## 3-08 — The ad account API (2026-10-18)

**Completed**
- **Six new addresses** for the web app (built in 3-09), all inside the organization:
  - **ad accounts:** the list and one account, with status, Google's own status, currency, time zone, the managers above it, sync status (including "waiting for the shared allowance") and health;
  - **daily figures** for an account: impressions, clicks, cost, conversions and conversion value per day and in total, for any period (the last 30 days by default);
  - **campaigns** of an account with their budget and figures for the period (removed ones included, so history stays readable);
  - **one campaign** with its ad groups and ads, each with its own figures;
  - **"Sync now"**.
- **Rates are worked out when asked for:** click-through rate, cost per click, cost per conversion, and conversion value per cost. When one can't be worked out (for example, no clicks), it says why instead of showing 0.
- **Honest figures:**
  - every answer says the figures are **reported by Google Ads**;
  - days not read yet say "not synchronized"; quiet days show real zeros;
  - the last 3 days are marked **"may still change"**;
  - account totals come from the account's own figures, campaign totals from the campaign's; levels are never added together.
- **Who can do what:** every member can read; owners, admins and managers can "Sync now". Another organization's account or campaign is "not found".

**Files changed** (16)
- New (4): `app/domains/advertising/{schemas,read_service,router}.py`, `tests/api/test_ad_accounts_api.py` (18 tests).
- Modified (12): `app/api/router.py`, `app/domains/organizations/permissions.py` (`ads.view`, `ads.manage`), `app/core/settings.py` (`ADS_UNSETTLED_DAYS`), `tests/security/test_tenant_isolation.py` (the generated sweep now covers the new addresses), `frontend/lib/api/{openapi.json,schema.d.ts}` (regenerated), docs `API_SPECIFICATION.md` (§19B), `PROJECT_STATUS.md`, this report.
- Deleted: none. No migration.

**Tests**
- **18 new.** They cover:
  - the account list and detail;
  - exact money and rates, real zeros and the reasons for missing rates, "may still change" days;
  - days never read, invalid periods, an account whose first import failed;
  - campaigns, removed ones, Performance Max without ad groups, one campaign with ad groups and ads;
  - "Sync now": success, viewer refused, the hourly limit, an unlinked account, a run already going;
  - other organizations, and no token or secret in any answer.
- The generated security sweeps now include the six addresses (sign-in required, CSRF on "Sync now", 404 for non-members).
- **Backend `make check`: 1,056 passed**, coverage 97 %. **Frontend `npm run check`: 343 passed.** E2E not rerun: no page changed yet.

**Security**
- Read-only; organization filters plus row-level security on every query.
- No tokens, secrets or platform error messages in any answer (tested).

**Deviations**
1. **"Sync now" is `…/resync`**, as for stores and as in the plan. The old outline in the API specification said `…/sync`; it now points to the as-built section.
2. **Campaigns are listed per ad account** (`/ad-accounts/{id}/campaigns`), as in the plan. The old outline's organization-wide campaign list with filters is not built in Phase 3.
3. **Rates use six decimals**, rounded half-to-even; the web app rounds for display.

**Blocked:** Step 0 (3-01) still needs network access to Google and your Google credentials.

**Next task:** 3-09 — the web app:
- "Connect Google Ads", with discovered accounts grouped under their manager;
- the Advertising tab, the account page (daily totals, rates, date range, campaign table, health, "Sync now") and the campaign page;
- every page labelled "reported by Google Ads" and checked for accessibility.

