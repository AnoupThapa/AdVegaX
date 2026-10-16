# Phase 3 — Task Reports

Plan: `PHASE_03_PLAN.md` (approved 2026-10-15, A21, all recommendations). One report per task; `PHASE_03_REPORT.md` follows task 3-10.

| Task | Status |
|---|---|
| 3-01 Step 0 on the test manager account | ⏸ Waiting — needs the developer token, the Google Cloud OAuth client and network access to Google's API (Q-3-10, option C) |
| 3-02 Advertising model + migration 0012; read interface; read-only guard | ✅ Done |
| 3-03 Google sign-in, token refresh and revocation, REST client, simulator | ✅ Done — awaiting review |
| 3-04 Discovery and linking rules | Not started |
| 3-05 Structure import | Not started |
| 3-06 Performance import | Not started |
| 3-07 Ongoing sync, corrections, shared quota, Sync now, health | Not started |
| 3-08 Read API | Not started |
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

