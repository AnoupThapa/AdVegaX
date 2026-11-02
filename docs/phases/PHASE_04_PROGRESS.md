# Phase 4 — Task Reports

Plan: `PHASE_04_PLAN.md` (approved 2026-10-18, A22, all recommendations). One report per task; `PHASE_04_REPORT.md` follows task 4-08.

| Task | Status |
|---|---|
| 4-01 Step 0 on the sandbox and one real account | ⏸ Waiting — needs the Meta app, a sandbox ad account and network access to Meta's API (Q-4-10, option C) |
| 4-02 Meta sign-in, Graph client, simulator, read-only guard | ✅ Done — awaiting review |
| 4-03 Discovery and linking rules | ✅ Done — awaiting review |
| 4-04 Structure import | ✅ Done — awaiting review |
| 4-05 Insights import | ✅ Done — awaiting review |
| 4-06 Ongoing sync, rate limits, token expiry | ✅ Done — awaiting review |
| 4-07 API additions and web app | ✅ Done — awaiting review |
| 4-08 Journey test, browser test, docs, report | ✅ Done — awaiting review |

---

## 4-01 — Step 0 on the sandbox and one real account

Waiting. Step 0 needs:
- the AdVegaX Meta business portfolio and developer app (Marketing API and Facebook Login for Business, with a configuration asking for `ads_read` and `business_management`);
- a sandbox ad account, and one real ad account for the figures comparison;
- the app ID and app secret in the local untracked settings file;
- network access to `graph.facebook.com` and `www.facebook.com`.

Until then, work follows option C: build against Meta's documentation and a simulator. Everything Step 0 would confirm is marked "to confirm live".

---

## 4-02 — Meta sign-in, Graph client, simulator and read-only guard (2026-10-18)

**Completed**
- **"Connect Meta" works end to end** (against the simulator):
  - the person is sent to Meta's own login page with AdVegaX's **Login for Business configuration**, which asks for read-only ads access (`ads_read`) and business details, with PKCE and a single-use state;
  - back at AdVegaX, the code is exchanged **on the server** for a token, then for the **long-lived token** (about 60 days); its end date is stored, encrypted with the token;
  - AdVegaX checks who signed in and which permissions they granted. If ads access was unticked, the connection is refused with a plain message;
  - declining on Meta's page connects nothing; a code Meta refuses connects nothing;
  - reconnecting with the same Facebook account reuses the connection; another Facebook account is a second connection; the same Facebook account may also serve another organization (Q-4-11);
  - disconnect asks Meta to remove AdVegaX's permission and always deletes our copy, even when Meta cannot be reached.
- **Secrets never travel in an address.**
  - The token goes in the `Authorization` header; the app secret only in the body of the token exchange.
  - Every call carries `appsecret_proof`, so a stolen token alone cannot be used against AdVegaX's app.
- **A Graph client** that:
  - follows Meta's paging cursor (never Meta's `next` link, which repeats the token);
  - turns Meta's error codes into plain codes (sign-in rejected, permission missing, rate limited with Meta's own wait time, too much data, no access);
  - reads Meta's usage headers on every answer, for pacing in 4-06.
- **Read-only guard:**
  - every request goes through one gate that allows reading, plus three documented calls that change nothing in an ad account (the token exchange, starting a report, removing AdVegaX's own permission);
  - anything else, such as creating a campaign, is refused before it is sent;
  - static tests check that the gate is the only way out and that `ads_management` is never requested.
- **A Meta simulator** for tests, which refuses tokens in addresses, wrong proofs and expired tokens.
- **Problem found and fixed while testing:** the plan's token check (`debug_token`) puts the token in the web address, and the HTTP library's request log would have recorded it. The person and permissions now come from `/me` and `/me/permissions`, with the token in the header. The test scans that log too.

**Files changed** (13)
- New (6): `app/providers/meta_ads/{__init__,client,provider}.py`, `tests/meta_sim.py`, `tests/providers/test_meta_ads_client.py` (83 tests), `tests/api/test_meta_ads_connect.py` (15 tests).
- Modified (7): `app/core/settings.py` (`META_ADS_ENABLED`, `META_APP_ID`, `META_APP_SECRET`, `META_LOGIN_CONFIG_ID`, `META_API_VERSION`), `app/providers/base/registry.py`, `tests/security/test_static_rules.py` (2 new rules), `.env.example` (Google Ads and Meta entries), docs `INTEGRATION_GUIDES.md`, `SECURITY.md`, this report.
- Deleted: none. No migration.

**Tests**
- **100 new.**
- **Backend `make check`: 1,162 passed**, coverage 97 % (Meta provider 98–99 %).
- **Frontend `npm run check`: 358 passed** (unchanged).

**Security**
- Read-only gate plus static tests.
- Tokens are encrypted, with their end date. No secret is ever placed in a URL; the tests scan responses, the audit log and the logs, including the HTTP request log.
- No Facebook name, email or picture is requested or stored.

**Deviations**
1. **No `debug_token`.** `/me` and `/me/permissions` are used instead (see above). `appsecret_proof` makes Meta itself confirm the token belongs to AdVegaX's app.
2. **The token exchange is a POST with the secret in the body.** Meta documents it as a GET with the secret in the address; to confirm in Step 0 that Meta accepts the POST form.
3. **The provider code is `meta_ads`** (the Phase 3 static test listed `meta`; updated).

**Blocked:** Step 0 (4-01): needs the Meta app, a sandbox ad account and network access to Meta.

**Next task:** 4-03 — discovery:
- the person's ad accounts, grouped by the business that owns them;
- status, currency and time zone;
- which accounts cannot be linked, and why.

## 4-03 — Discovery and linking rules (2026-10-19)

**Completed**
- **Finding ad accounts:** after connecting, AdVegaX lists every ad account the person can use (Meta's `me/adaccounts`), page by page with Meta's cursor, up to 5,000 accounts.
- **Each account shows** its name, currency, time zone and the business that owns it ("grouped by business"; a personal account has no group). The same account listed twice appears once.
- **Accounts that cannot be linked are still listed, with a plain reason:**
  - disabled, closed, closing, or a status AdVegaX does not recognise → "not enabled";
  - an unpaid balance → `account_unsettled` (new reason);
  - under Meta's review → `account_under_review` (new reason);
  - missing or unreadable currency or time zone → "details missing".
  - Linking one of these is refused (409 `RESOURCE_UNAVAILABLE` with the reason).
- **Linking** reads the account once (`GET /act_<id>`), checks that Meta answered about the same account, and creates the ad account with its currency and time zone. An account the person can no longer reach gives `no_account_access`.
- **Rediscovery** updates reasons and businesses and keeps existing links; a token Meta no longer accepts marks the connection "Needs reconnecting".
- Rows AdVegaX cannot read are skipped and counted in the logs, never guessed.

**Files changed** (7)
- New (2): `app/providers/meta_ads/mapping.py`, `tests/api/test_meta_ads_discovery.py` (22 tests).
- Modified (5): `app/providers/meta_ads/provider.py`, `tests/meta_sim.py` (ad accounts, `me/adaccounts` paging, `GET /act_<id>`), `tests/providers/test_meta_ads_client.py` (6 new tests; the 4-02 placeholder test now expects a token), `docs/INTEGRATION_GUIDES.md`, this report.
- Deleted: none. No migration.

**Tests**
- **28 new.**
- **Backend `make check`: 1,190 passed**, coverage 97 % (Meta mapping 100 %, provider 99 %).
- **Frontend `npm run check`: 358 passed** (unchanged).

**Security**
- Account ids are checked (`act_<digits>`) before they enter any address; the token stays in the header (the tests check the address).
- Only ad-account fields are requested; no people, pages or payment details.
- Tenant isolation unchanged: discovered accounts belong to the connection's organization.

**Deviations**
1. **Linking a Meta account now starts the import, which stops with `unsupported`** until campaigns are read (4-04). Expected; nothing is shown as 0.
2. **The web app does not yet have words for the two new reasons** (`account_unsettled`, `account_under_review`); they are added with the other Meta wording in 4-07, as planned.

**Blocked:** Step 0 (4-01): needs the Meta app, a sandbox ad account and network access to Meta.

**Next task:** 4-04 — structure import: campaigns, ad sets and ads (including archived and deleted), with budgets converted using each currency's offset.

## 4-04 — Structure import (2026-10-19)

**Completed**
- **Linking a Meta ad account now imports its campaigns, ad sets and ads.** Ad sets are stored as AdVegaX's ad groups, as planned.
- **Archived and deleted items are kept.** Meta leaves them out unless they are asked for by status, so every read asks for them explicitly. Their history stays readable.
- **What is kept** (only what the plan approved):
  - campaigns: name, objective, bid strategy, buying type, start and end dates;
  - ad sets: name, optimization goal, bid strategy;
  - ads: name and the creative's id and name only (no texts, images or audiences).
- **Statuses:**
  - Meta's effective status is shown, so a paused campaign shows its ad sets and ads as paused too.
  - "Disapproved", "in review" and similar delivery states are kept as Meta's own detail beside an active item; they are never turned into a different status.
- **Budgets:**
  - Each budget belongs to the campaign or to the ad set, and is daily or lifetime.
  - Meta sends amounts in cents for most currencies, so 5000 AUD cents becomes A$50.00. For 11 currencies (JPY, KRW, IDR, VND and others) Meta counts whole units, so ¥5000 stays ¥5000.
  - Tested for all 11 whole-unit currencies and 7 cent currencies, plus AUD and JPY accounts end to end.
  - A budget of "0" means the budget sits at the other level; it is stored as no budget, never as 0.
  - When a budget moves from a campaign to its ad sets, the next import follows it.
- **Efficiency:** large accounts are read 500 items a page. The currency comes from the account read the importer already makes, so there is no second call.
- **Robustness:**
  - A later import updates names, statuses and budgets and never deletes anything.
  - An account the person can no longer reach, or one disabled after linking, stops with a plain reason on the account; the connection stays fine.
  - A request Meta refuses as malformed is not retried.

**Files changed** (8)
- New (1): `tests/api/test_meta_ads_structure.py` (11 tests).
- Modified (7): `app/providers/meta_ads/mapping.py` (status, money, date and structure rules), `app/providers/meta_ads/provider.py` (`read_structure`), `tests/meta_sim.py` (campaign, ad set and ad lists that hide archived and deleted items unless asked; sample structure), `tests/providers/test_meta_ads_client.py` (42 new tests; the 4-02 placeholder now expects a sign-in), `docs/INTEGRATION_GUIDES.md`, this report, `PROJECT_STATUS.md`.
- Deleted: none. No migration (the Phase 3 tables hold Meta as planned).

**Tests**
- **53 new.**
- **Backend `make check`: 1,243 passed**, coverage 97 % (Meta mapping and client 100 %, provider 98 %).
- **Frontend:** no changes (358 passed at 4-03).

**Security**
- Read-only: only GET requests to the account's own lists; the read-only gate and its static test are unchanged and pass.
- Ids are checked before they enter any address; the token stays in the header.
- No creative texts, images, audiences or targeting are read.

**Deviations**
1. **The import still stops after the structure, with `unsupported`**, until daily figures are read (4-05). Expected; nothing is shown as 0.
2. **A status Meta might add in future is not in the request filter,** so such items would not be returned until it is added. Step 0 checks the live list of statuses.
3. **Meta has no shared budgets** (as Google does), so every Meta budget is unshared and named by its holder (`campaign:<id>` or `adset:<id>`).

**Blocked:** Step 0 (4-01): needs the Meta app, a sandbox ad account and network access to Meta.

**Next task:** 4-05 — daily figures: 13 months of history at four levels (account, campaign, ad set, ad); purchases using each ad set's own attribution setting; exact money in the account's time zone; Meta's report jobs for slices that are too large.

## 4-05 — Daily figures import (2026-10-19)

**Completed**
- **Linking a Meta ad account now imports 13 months of daily figures**, so the first import finishes completely: the account shows as active with its history.
- **Four levels**, as for Google Ads: account, campaign, ad set and ad. One calendar month is read per step (14 steps for 13 months), one row per day.
- **Measures:** impressions, link clicks, spend, purchases and purchase value.
  - **Spend** is exact, in the account's currency, as Meta reports it (Meta's figures are not in cents, so no conversion).
  - **Purchases** are Meta's combined website, app and offline figure (`omni_purchase`), the same as the "Purchases" column in Ads Manager. Other purchase rows in Meta's list are ignored, so nothing is counted twice.
  - **Attribution:** each ad set's own setting, so figures match what you see in Ads Manager.
- **Days** are the account's own days (its time zone). A day with no activity is a real zero at account level, never missing.
- **Deleted and archived campaigns, ad sets and ads** keep their figures for the days they ran. Account totals come from Meta's account rows, which include them.
- **Large reads:** when Meta answers that a request is too large, the same request runs as one of Meta's report jobs: started, checked every 5 seconds, then read. If Meta can't finish the report, the step is retried later, then stops with a plain reason on the account (the connection stays fine). Report ids are never stored.
- **A later import replaces the figures of the days it reads**, so Meta's corrections (up to 28 days) are picked up. A duplicated row is stored once, never added up. Rows AdVegaX can't read are skipped and counted.

**Files changed** (8)
- New (1): `tests/api/test_meta_ads_performance.py` (9 tests).
- Modified (7): `app/providers/meta_ads/mapping.py` (figures rules), `app/providers/meta_ads/client.py` (starting a report; `report_failed` and `report_pending`), `app/providers/meta_ads/provider.py` (`read_performance`), `tests/meta_sim.py` (daily figures, "too much data", report jobs, sample figures), `tests/providers/test_meta_ads_client.py` (19 new tests; the 4-02 placeholder now expects a sign-in), `docs/INTEGRATION_GUIDES.md`, this report and `PROJECT_STATUS.md`.
- Deleted: none. No migration.

**Tests**
- **28 new.**
- **Backend `make check`: 1,271 passed**, coverage 97 % (Meta client 100 %, provider 98 %, mapping 97 %).
- **Frontend:** no changes (358 passed at 4-03).

**Security**
- Read-only: figures are GET requests. The one POST starts a report, which changes nothing in the account; it is the documented exception in the read-only gate, and the gate's static test passes.
- The report request carries the token in the header and the settings in the body; nothing secret is in an address (tested).
- Report ids are checked to be digits before they enter an address.

**Deviations**
1. **Clicks are Meta's link clicks (`inline_link_clicks`)**, not "all clicks", which also counts likes, comments and profile clicks. Link clicks are what Google Ads counts as clicks, so click-through rate and cost per click compare fairly. It can be switched if you prefer.
2. **Report jobs are checked within one step** (every 5 seconds, up to 5 minutes) rather than as separate queued steps. Simpler, and nothing is kept between steps; if a report takes longer, the next attempt starts a new one.
3. **The web app does not yet have Meta wording** for the new reasons (`report_failed`, `report_pending`, `too_much_data`); added in 4-07 with the other Meta wording.

**Blocked:** Step 0 (4-01): needs the Meta app, a sandbox ad account, one of your real ad accounts for figures, and network access to Meta.

**Next task:** 4-06 — ongoing sync: pacing from Meta's usage headers (slow down above 75 %, pause when Meta says so), sign-in expiry warnings at 14 and 3 days, and account health.

## 4-06 — Ongoing sync, Meta's limits, sign-in expiry and health (2026-10-19)

**Completed**
- **Ongoing sync:** Meta accounts follow the same schedule as Google Ads (every 3 hours, nightly 30 days, weekly 90 days). Nothing new was needed for that; it is covered by the tests.
- **Pacing from Meta's usage figures**, which arrive with every answer:
  - from 75 % of a limit, each call to that ad account waits a little (up to 10 seconds);
  - from 95 %, or while Meta says how long to wait, AdVegaX stops calling that account. Its import **pauses and continues by itself** when the time has passed. A pause is not a failure: no retry attempt is used, and the connection stays fine;
  - Meta's "too many calls" errors for one ad account pause only that account; other accounts carry on;
  - Meta's limit for AdVegaX's whole app pauses every Meta account, using the Phase 3 platform-wide wait.
- **Sign-in expiry** (Meta sign-ins last about 60 days and cannot be renewed without the person):
  - an hourly check records a warning **14 days** and **3 days** before the end, once each per sign-in (the web app shows it in 4-07);
  - at the end, the connection shows **"Needs reconnecting"**, even if no sync runs;
  - an ended sign-in is never sent to Meta;
  - reconnecting with the same Facebook account starts a new 60 days, with new warnings.
- **Health in plain words:** an ad account with an unpaid balance now says so (`account_unsettled`), as does one under Meta's review (`account_under_review`), instead of the general "not enabled".
- **Fixed on the way:** Meta's app-wide limit would not have paused the other Meta accounts, because the shared wait was only checked for platforms with a daily allowance (Google). It is now checked for every step that calls a platform.

**Files changed** (14)
- New (1): `tests/api/test_meta_ads_sync.py` (19 tests).
- Modified (13):
  - core (platform-neutral): `app/providers/base/errors.py` (`AccountBusyError`, `SignInExpiredError`), `app/providers/base/types.py` (an account's reason when it cannot be read), `app/core/settings.py` (`ADS_ACCOUNT_BUSY_WAIT`, `SIGN_IN_WARNING_DAYS`), `app/domains/advertising/importer.py` (pause one account; platform-wide wait for every calling step; the platform's reason), `app/domains/integrations/tokens.py` (an ended sign-in is not used), `app/domains/integrations/jobs.py` (expiry check and warnings), `app/workers/job_tasks.py` (runs it hourly with the token keep-alive);
  - Meta: `app/providers/meta_ads/client.py` (usage per app and account, pacing, two kinds of limit), `app/providers/meta_ads/provider.py`;
  - tests and docs: `tests/providers/test_meta_ads_client.py` (5 new; code 4 is now the app limit), `docs/INTEGRATION_GUIDES.md`, this report, `PROJECT_STATUS.md`.
- Deleted: none. No migration (the warnings are audit events; no new column).

**Tests**
- **24 new.**
- **Backend `make check`: 1,295 passed**, coverage 97 % (Meta client 99 %, provider 98 %).
- **Frontend:** no changes (358 passed at 4-03).

**Security**
- The expiry check reads ids and dates only; no token is decrypted.
- Warnings are recorded in the organization's own audit log (tenant context); nothing about one organization reaches another. The usage figures kept in memory are percentages per ad account, never tokens.
- An ended sign-in is never sent anywhere.

**Deviations**
1. **Warnings are recorded as audit events and shown by the web app (4-07); no email is sent.** The plan asked for in-app warnings. An email to the organization's owners could be added later with the existing email system, if you'd like.
2. **Usage figures are remembered per worker process**, not shared between workers. Each Meta answer carries fresh figures, so a worker learns them on its first call; if needed later, they can be shared through Redis.
3. **The web app has no wording yet** for `sign_in_expired`, `account_unsettled` and `account_under_review` (added in 4-07 with the other Meta wording).

**Blocked:** Step 0 (4-01): needs the Meta app, a sandbox ad account, one of your real ad accounts, and network access to Meta.

**Next task:** 4-07 — API additions and web app: Meta wording ("ad set", "Purchases", "Reported by Meta"), accounts grouped by business on the Connections page, the sign-in end date and its warning, Meta's reasons in plain words, and both platforms on the Advertising tab.

## 4-07 — API additions and web app (2026-10-19)

**Completed**
- **API (no new routes, two additive fields):**
  - `connection_expires_at` on each ad account: when the sign-in behind it ends (Meta); empty for Google Ads, whose sign-in renews itself;
  - `sign_in_expires_at` on connections (list and detail), for the Connections pages.
- **Advertising tab:** Google Ads and Meta accounts together, each labelled with its platform; Meta accounts also show their business.
- **Account and campaign pages speak each platform's language:**
  - for Meta: "Ad sets" instead of "Ad groups", "Purchases", "Purchase value", "Cost per purchase" and "Link clicks", "Objective" (e.g. "Sales") and "Business";
  - "Reported by Meta" on every set of figures, and a short note that purchases need the Meta Pixel or Conversions API;
  - Google Ads pages read exactly as before.
- **Sign-in ending:**
  - the account page shows when the Meta sign-in ends;
  - from 14 days before, a notice with a **"Reconnect Meta"** link (urgent from 3 days); viewers are told to ask an owner or admin;
  - the Connections list and the connection page show the end date and the same notice.
- **Connections pages:**
  - "Connect Meta", with a note that AdVegaX only reads and never changes campaigns, budgets or ads, and that sign-ins last about 60 days;
  - discovered ad accounts grouped under "Business: …", with personal accounts under "Not in a business";
  - Meta's reasons in plain words: "Has an unpaid balance in Meta", "Under review by Meta", "Disabled or closed in Meta";
  - disconnecting explains that AdVegaX also asks Meta to remove its access.
- **Health in Meta's terms:** "The ad account has an unpaid balance in Meta", "Meta is reviewing this ad account", "Meta disabled or closed this ad account", "Meta is limiting how much AdVegaX can read — figures will update later", each with its fix.
- **Wording for every new Meta code** (sign-in rejected, permission missing, sign-in ended, report failed or not ready, too much data).
- **Fixed on the way:** while an account waited for a platform's limit, its summary line also said "Something went wrong with the platform". It now only says it is waiting.

**Files changed** (26)
- Backend (8): `app/domains/advertising/{read_service,schemas}.py`, `app/domains/integrations/{schemas,service,tokens}.py` (`sign_in_ends_at`), `app/providers/meta_ads/mapping.py` (the status list written so the web app's error-code scan does not mistake it for error codes), `tests/api/test_meta_ads_sync.py` (1 new test), `tests/api/test_connections.py` (the connection's field list now includes `sign_in_expires_at`).
- Web app (16): `features/advertising/{labels.ts,Figures.tsx,AdAccountPage.tsx,AdAccountsPage.tsx,CampaignPage.tsx}`, `features/connections/{labels.ts,ConnectionsPage.tsx,ConnectionDetailPage.tsx,ResourceRow.tsx,connect-fields.ts,connections.module.css}`, `lib/api/{openapi.json,schema.d.ts}` (regenerated), `tests/features/{advertising,connections}.test.tsx` (12 new tests).
- Docs (2): `API_SPECIFICATION.md`, this report (and `PROJECT_STATUS.md`).
- Deleted: none. No migration.

**Tests**
- **13 new** (1 backend, 12 web app).
- **Backend `make check`: 1,296 passed**, coverage 97 %. (The first run flagged one existing test that lists a connection's fields exactly; the new field was added to that list and the test passes.)
- **Frontend `npm run check`: 370 passed** (types, lint, unit, coverage 96.8 %); no vulnerabilities.
- **Browser tests (Playwright + axe): 12 passed**, including the Google Ads advertising pages, which keep their wording. Meta's browser test and accessibility check come in 4-08.

**Security**
- The new fields are dates only. The end date is withheld once a connection is disconnected.
- Nothing about the sign-in itself (tokens, Facebook ids) reaches the web app.
- Tenant isolation unchanged: the existing routes and their sweeps.

**Deviations**
1. **The notice is worked out in the web app from the end date** (14 and 3 days, as in the hourly check). It needs no extra API field, and it always matches the date shown.
2. **The "Reconnect" link opens the Connections page's "Connect a platform" section.** Connecting Meta again with the same Facebook account reuses the connection, so links and imported data stay.

**Blocked:** Step 0 (4-01): needs the Meta app, a sandbox ad account, one of your real ad accounts, and network access to Meta.

**Next task:** 4-08 — journey test (connect → discover → link → import → sync → limits → expiry warning → reconnect → disconnect), a browser test of the Meta pages with an accessibility check, and `PHASE_04_REPORT.md`.

## 4-08 — Journey test, browser test, docs and report (2026-10-19)

**Completed**
- **Whole-journey test** (`test_meta_ads_journey.py`), one organization start to finish through the real API, database, job runner and the Meta simulator:
  1. connect, and find ad accounts by business (an account with an unpaid balance cannot be linked);
  2. link an AUD and a JPY account, which import their structure and 13 months of figures (A$50.00 from 5,000 cents; ¥5,000 stays ¥5,000);
  3. the 3-hour run picks up a renamed campaign;
  4. Meta corrects a past day and the nightly run picks it up;
  5. Meta's usage hits its limit: every account pauses and then continues by itself;
  6. a warning is recorded 14 days before the sign-in ends;
  7. the person removes AdVegaX in Facebook ("Needs reconnecting"; figures still readable);
  8. reconnecting with the same Facebook account keeps the connection, links and data, and starts a new 60 days;
  9. "Sync now", which viewers cannot use;
  10. disconnect: permission removed at Meta, links ended, figures still readable.

  It also checks that every call to Meta was a read (except the token exchanges and the removal), and that no token or the app secret ever appeared in a response, the audit log or the logs.
- **Browser test** (`e2e/meta.spec.ts`) with a simulated Meta account, through a helper process (`tests/e2e_meta_ads.py`, 4 tests of its own):
  - the Connections page offers Meta as read-only and shows the sign-in's end date and notice;
  - the connection page groups accounts by business ("Has an unpaid balance in Meta");
  - the Advertising tab and the account page use Meta's words (Purchases, Link clicks, "Reported by Meta", "Reconnect Meta");
  - the campaign page shows ad sets and ads;
  - all five pages pass the accessibility check, and no Meta token reaches a page.
- **CI:** the browser job switches Meta on with placeholder settings only, to show the pages; nothing ever calls Meta.
- **Docs:** `PHASE_04_REPORT.md`; `SECURITY.md` (expiry, limits, no personal data, data-deletion URL before real customers, test helpers never ship); `INTEGRATION_GUIDES.md` (status); `PROJECT_STATUS.md`, `ROADMAP.md`.

**Files changed** (12)
- New (5): `backend/tests/api/test_meta_ads_journey.py`, `backend/tests/e2e_meta_ads.py`, `frontend/e2e/meta.spec.ts`, `frontend/e2e/support/meta_ads.ts`, `docs/phases/PHASE_04_REPORT.md`.
- Modified (7): `backend/tests/api/test_e2e_seed.py` (4 new tests), `.github/workflows/ci.yml` (Meta placeholders for the browser job), `docs/SECURITY.md`, `docs/INTEGRATION_GUIDES.md`, `docs/PROJECT_STATUS.md`, `docs/ROADMAP.md`, and this report.
- Deleted: none. No migration.

**Tests**
- **6 new** (journey 1, helper 4, browser 1).
- **Backend `make check`: 1,301 passed**, coverage 97 %.
- **Frontend `npm run check`: 370 passed** (no web-app code changed in this task).
- **Browser tests (Playwright + axe): 13 passed.**

**Deviations**
1. **In the journey, Meta's limit pauses every account.** The usage headers sent put AdVegaX's whole app at 97 %, which is the app-wide case; the one-account case is covered in `test_meta_ads_sync.py`.

**Blocked:** Step 0 (4-01): needs the Meta app, a sandbox ad account, one of your real ad accounts, and network access to Meta.

**Next:** product-owner review of `PHASE_04_REPORT.md`; the Meta set-up for Step 0 (report §12).

