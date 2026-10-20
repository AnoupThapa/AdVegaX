# Phase 6 — Progress (unified analytics and financial engine)

Plan: `PHASE_06_PLAN.md` (approved 2026-10-20, A24, all recommendations; completes Q7). One task at a time, a report after each.

| Task | Status |
|---|---|
| 6-01 Step 0: live ECB and NRB feeds | ⏸ Waiting for network access to `data-api.ecb.europa.eu` and `www.nrb.org.np` |
| 6-02 Migration 0016, reporting settings, store assignment | ✅ Done — awaiting review |
| 6-03 Exchange rates: clients, daily job, conversion rules | ✅ Done — awaiting review |
| 6-04 Metric registry `analytics-v1` and its inputs | ✅ Done — awaiting review |
| 6-05 Overview and channels API | Not started |
| 6-06 Campaigns (with GA4 match) and products API | Not started |
| 6-07 Web app: Overview, settings | Not started |
| 6-08 Web app: channels, campaigns, products, "how is this calculated?" | Not started |
| 6-09 Golden datasets, performance check, browser test, `PHASE_06_REPORT.md` | Not started |

## 6-01 — Step 0 (2026-10-20)

**Blocked:** the ECB and Nepal Rastra Bank addresses are not allowed from this environment (the network refuses the connection). Phase 6 is built against recorded copies of their answers; Step 0 checks the live feeds (plan §4.2) once both addresses are allowed in Claude's network settings.

## 6-02 — Migration 0016, reporting settings, store assignment (2026-10-20)

**Completed**
- **Migration 0016** (additive):
  - **`fx_rates`**: published exchange rates, one per source (ECB or Nepal Rastra Bank), currency pair and day, exactly as published, with the source's own unit (NRB quotes JPY per 10 and INR per 100). It is shared reference data, not any organization's: the application can only read it; only the system role (the daily job in 6-03) can write it, and nobody but the migrator can delete from it.
  - **`store_id` on ad accounts and analytics properties** (Q-6-1): which store an account's spend or a property's visits belong to when an organization has several stores. The store must be the organization's own (a composite key enforces it in the database too); removing a store only clears the reference.
- **Store assignment** for owners and admins: `PUT …/ad-accounts/{id}/store` and `PUT …/analytics-properties/{id}/store` with a store or `null` (the whole organization). Recorded in the audit log only when it changes. Managers, analysts and viewers can read the assignment but not change it. Every ad account and property answer now includes `store_id`.
- **Reporting currency and time zone** (Q-6-2) are the organization's existing currency and time zone settings, which owners and admins can already change.

**Files changed** (19)
- New (5): `alembic/versions/0016_unified_analytics.py`, `app/domains/fx/{__init__,models}.py`, `app/domains/metrics/{__init__,assignment}.py`, `tests/api/test_store_assignment.py` (21 tests).
- Modified (14): `app/db/models.py`, `app/domains/advertising/{models,schemas,read_service,router}.py`, `app/domains/analytics/{models,schemas,read_service,router}.py`, `tests/helpers.py` (`put`), `tests/security/test_tenant_isolation.py` (the two new routes are swept), `frontend/lib/api/{openapi.json,schema.d.ts}` (generated), docs `DATABASE_SCHEMA.md` (§13A), `API_SPECIFICATION.md` (§19D), this report, `PROJECT_STATUS.md`.
- Deleted: none.

**Tests**
- **21 new**; the tenant-isolation sweep covers the two new routes.
- **Backend `make check`: 1,509 passed**, coverage 97 %. **Frontend `npm run check`: 387 passed** (types regenerated).

**Security**
- Exchange rates hold no tenant data; the application role cannot write them (tested), the system role cannot delete them (tested).
- Assignments: owners and admins only (tested for manager, analyst, viewer); another organization's store is refused by the API (422) and by the database (tested).

**Migration:** `0016_unified_analytics` — new table `fx_rates`, two nullable columns with foreign keys. Downgrade removes them.

**Deviations**
1. **No `organization_reporting` table** (plan §7): the organization already has a currency and a time zone, chosen when it is created and editable in Settings, so those are the reporting settings. The plan's "defaults to the first store's" becomes "the currency and time zone chosen when the organization was created" — a store in another currency is converted (6-03). Changing it is one setting.

**Blocked:** Step 0 (6-01) — network access to the two rate feeds.

**Next task:** 6-03 — exchange rates: the ECB and Nepal Rastra Bank clients (recorded answers in tests), the daily job, and the one conversion function (each day's rate, the last published rate on weekends and holidays, cross rates through EUR, "not available" without a rate).

## 6-03 — Exchange rates: reading, storing, converting (2026-10-20)

**Completed**
- **Reading the two sources** (built against their documented formats; Step 0 confirms them live):
  - **European Central Bank:** every currency against the euro for a period, as a table read by its column names (so a change in column order does not matter). A period without rates (a weekend, a holiday) is simply empty.
  - **Nepal Rastra Bank:** NPR buy and sell rates per day, page by page. AdVegaX keeps the middle of the two with NRB's unit (it quotes the yen per 10 and the Indian rupee per 100).
  - Rows that cannot be read are skipped and counted; an answer in another format stops only that source; a temporary error is tried again at the next run.
- **A scheduled task every 6 hours** (once switched on with `FX_ENABLED`): the first run reads 400 days (13 months of figures plus margin) in 92-day pieces; later runs read again from 10 days before the newest stored day, so a corrected rate replaces the old one. One bank failing never stops the other.
- **One conversion function** for the whole product:
  - each figure uses **its own day's rate**; on a weekend or holiday the **last published** rate (Friday's for Saturday and Sunday), at most 7 days old;
  - currencies the ECB publishes convert **through the euro** on the same ECB day (AUD → USD = USD rate ÷ AUD rate);
  - **NPR** converts with Nepal Rastra Bank's rate, or **through the US dollar** when NRB does not quote the other currency (e.g. NPR → NZD);
  - a currency without any rate is "not available", never guessed;
  - exact decimals (34 significant digits); rounding only for display, as everywhere.
- **Read-only, one gate:** the code has exactly one request, a GET, after a check that the address is one of the two banks' (static test). No credentials, no redirects followed.

**Files changed** (11)
- New (4): `app/domains/fx/{sources,service}.py`, `tests/fx_sim.py` (recorded-format answers for both banks), `tests/api/test_fx_rates.py` (24 tests).
- Modified (7): `app/core/settings.py` (`FX_*`, `SCHEDULE_FX_INTERVAL`), `app/workers/{job_tasks,celery_app}.py` (the scheduled task), `tests/conftest.py` (rates cleared between tests), `tests/security/test_static_rules.py` (1 rule), `.env.example`, docs `INTEGRATION_GUIDES.md`, `SECURITY.md`, this report, `PROJECT_STATUS.md`.
- Deleted: none. No migration.

**Tests**
- **25 new.**
- **Backend `make check`: 1,534 passed**, coverage 96 % (exchange rates 92–100 %).
- Frontend: no changes.

**Security**
- Two fixed public addresses, GET only, nothing sent that identifies an organization; written by the system role only.

**Deviations**
1. **Off by default** (`FX_ENABLED=false`), like the platforms: the deployment switches it on once the two addresses are allowed. Until then conversions say "not available — no exchange rate".
2. **The ECB is read through its Data Portal as CSV** (plan §4.1 named the SDMX series); the daily XML files are an alternative if Step 0 finds the CSV unsuitable.

**Blocked:** Step 0 (6-01) — network access to the two rate feeds.

**Next task:** 6-04 — the metric registry `analytics-v1`: every unified figure defined once (inputs, formula, unit, availability rules, sources), reading store, advertising and Google Analytics daily figures and converting them to the reporting currency.

## 6-04 — The metric registry `analytics-v1` and its inputs (2026-10-20)

**Completed**
- **One registry** (`app/domains/metrics/registry.py`) defines every unified figure once, with its label, unit, formula in plain words and the sources it needs. The API (6-05) and the "How is this calculated?" text (6-08) come from it; no page has its own formula. 18 figures:
  - from the stores: net sales, orders, product cost, gross profit, gross margin;
  - from the ad platforms: ad spend (Google Ads and Meta together);
  - combined: profit after ad spend (named "before shipping costs and payment fees"), blended ROAS, cost per order, ad spend share of sales;
  - from Google Analytics: sessions, purchases and purchase revenue (never added to store figures), and the store conversion rate (store orders ÷ sessions, only when every store has a property);
  - not provided yet, and saying so: shipping cost, payment fees, contribution profit, customer acquisition cost.
- **The calculation** (`engine.py`) reads what the earlier phases store — the stores' daily finance-v1 figures, each ad account's daily account-level spend, each property's daily total — converts every source's day with that day's exchange rate (6-03), then applies the formulas for a day or a period. Computed on read, so a late refund, a platform correction or a cost edit shows at once.
- **Honest gaps, never 0:** a day a source has not read yet makes the period "not synchronized"; an uncosted product makes product cost and every profit "not available — some products have no cost" (never a partial profit); orders in another currency, a missing exchange rate, or nothing connected of a kind ("no ad account", "no Google Analytics property") each say so; a zero divisor names itself ("no orders", "no ad spend").
- **Scope (Q-6-1):** the whole organization, or one store. With one store, every ad account and property counts for it; with several, only what is assigned to that store, and unassigned ones count for the whole organization.

**Golden dataset** (worked out by hand, in the test file's header): an AUD store, Google Ads in AUD and Meta in USD (ECB rates 1.6 and 1.5 AUD per USD, the second also used for the next day as on a holiday), and a Google Analytics property — net sales A$1,500.50, product cost A$600.20, gross profit A$900.30, ad spend A$204.50, profit after ad spend A$695.80, blended ROAS 7.337408, cost per order A$13.633333, store conversion rate 0.025. Reproduced to the cent, and in USD as the reporting currency.

**Files changed** (5)
- New (3): `app/domains/metrics/{registry,engine}.py`, `tests/api/test_metrics_engine.py` (15 tests).
- Modified (2): docs (this report, `PROJECT_STATUS.md`).
- Deleted: none. No migration. Frontend: no changes.

**Tests**
- **15 new**, including another organization's figures never being included.
- **Backend `make check`: 1,549 passed**, coverage 96 % (metrics 97–100 %).

**Security:** reads only, under the organization's own row-level security; exchange rates are shared read-only data.

**Deviations:** none. (Budget use, Q-6-11, is a per-campaign figure and comes with the campaigns answer in 6-06.)

**Blocked:** Step 0 (6-01) — network access to the two rate feeds.

**Next task:** 6-05 — the overview and channels API: `GET /analytics/overview` (every registry figure for a period, by day and in total, with definition version, reporting currency, sources and their freshness, conversions used) and `GET /analytics/channels` (per ad platform with its own reported figures, and per Google Analytics channel).
