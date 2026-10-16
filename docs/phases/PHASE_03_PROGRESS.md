# Phase 3 — Task Reports

Plan: `PHASE_03_PLAN.md` (approved 2026-10-15, A21, all recommendations). One report per task; `PHASE_03_REPORT.md` follows task 3-10.

| Task | Status |
|---|---|
| 3-01 Step 0 on the test manager account | ⏸ Waiting — needs the developer token, the Google Cloud OAuth client and network access to Google's API (Q-3-10, option C) |
| 3-02 Advertising model + migration 0012; read interface; read-only guard | ✅ Done — awaiting review |
| 3-03 Google sign-in, token refresh and revocation, REST client, simulator | Not started |
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
