# Phase 6 — Implementation Report (unified analytics and financial engine)

**Date:** 2026-10-21 · **Branch:** `feature/phase-1a` · **Status:** Implemented against recorded exchange-rate answers — awaiting product-owner review. **Step 0 on the live rate feeds (6-01) is still pending**: it needs network access to `data-api.ecb.europa.eu` (European Central Bank) and `www.nrb.org.np` (Nepal Rastra Bank).
**Plan:** `PHASE_06_PLAN.md` (approved 2026-10-20, A24, all recommendations Q-6-1 … Q-6-13; completes Q7) · Task-by-task reports: `PHASE_06_PROGRESS.md` (6-02 … 6-09).

---

## 1. Summary

For the first time an organization sees its **stores' sales, its Google Ads and Meta spend and its Google Analytics visits together**, in one currency, with the profit that follows. Concretely:

- **The Overview is the organization's home page.** For the last 7, 30 or 90 days, for all stores or one store, it shows:
  - **sales and profit:** net sales, orders, product cost, gross profit, gross margin;
  - **advertising:** ad spend, **profit after ad spend (before shipping costs and payment fees)**, blended ROAS, cost per order, ad spend as a share of sales;
  - **visits:** sessions, purchases and revenue as Google Analytics reports them, and the store conversion rate;
  - **not included yet**, each with why: shipping cost and payment fees (not provided by Shopify or WooCommerce), contribution profit (needs those costs), customer acquisition cost (new customers are not identified yet);
  - a **day-by-day table**, newest first.
- **Reports** show the same period as **Channels** (each platform's own figures, and Google Analytics' channels), **Campaigns** (platform figures, budget use, and Google Analytics' figures for the campaign of exactly the same name) and **Products** (units, net sales, cost, gross profit, margin).
- **Every figure says how it is calculated.** "How is this calculated?" sits on every Overview tile and under every report table. The text comes from one place — the metric registry `analytics-v1` — never from a page, and a static check fails the build if a page does arithmetic on a figure.
- **Every answer says where its numbers come from:** each store, ad account and property used, with its currency, time zone, first day and last update; which currencies were converted, with which bank's rates and their dates; how many days had no rate; and a note when sources use different time zones.
- **One reporting currency and time zone** — the organization's own, chosen when it is created and editable in Settings. Amounts in other currencies are converted **with each day's own rate**:
  - the **European Central Bank**'s reference rates (through the euro);
  - **Nepal Rastra Bank**'s rates for the Nepalese rupee (middle of buy and sell, per its unit), through the US dollar when NRB has no rate for a currency;
  - weekends and holidays use the **last published rate, at most 7 days old**; with no rate the figure is "not available — no exchange rate", never guessed.
- **Several stores:** Settings let owners and admins say which store each ad account and Google Analytics property belongs to (or "all stores"). With one store everything counts for it.
- **Always current.** Figures are **computed when they are read** from the stored daily figures and rates, so a late refund, a Google correction or a product cost edit changes every report at once — there is nothing to recompute (Q-6-13). Measured: a 390-day Overview for 5 stores, 10 ad accounts and 5 properties answers in about **0.5 s**, so no summary table is needed.

The promises of every earlier phase hold:

- **Missing data is never shown as 0.** A day not read is "Not synced yet"; a missing cost, rate or connection says so; a zero divisor names itself ("No ad spend", "No orders").
- **Figures from different sources are never mixed where they should not be.** Blended ROAS (store sales ÷ ad spend) and each platform's own ROAS are separate figures; platform conversions and their value are **never added across platforms**; Google Analytics figures are **never added** to store or ad figures; users are never added across days.
- **Read-only.** Phase 6 reads what Phases 2–5 imported. The two rate clients make only GET requests to two fixed public hosts, through the SSRF-safe client, with no credentials.
- **Tenant isolation.** Every new route is covered by the tenant sweeps; another organization's data or store is "not found".

---

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 6-01 | ⏸ Step 0 on the live feeds — waits for network access (§9) |
| 6-02 | Migration **0016**: `fx_rates` (global, read-only to tenants), `store_id` on ad accounts and analytics properties; store assignment routes (owner/admin, audited) |
| 6-03 | ECB and NRB clients (recorded-format tests), the daily rate task (`FX_ENABLED`, first read 400 days, then the last 10), the conversion table with the 7-day rule |
| 6-04 | The registry `analytics-v1` (18 figures) and the engine: inputs per source and day, conversion, availability, ratios (six decimals, half-even) |
| 6-05 | `GET /analytics/overview` and `GET /analytics/channels` |
| 6-06 | `GET /analytics/campaigns` (budget use, Google Analytics match) and `GET /analytics/products` |
| 6-07 | Web app: Overview as the home page; Settings: stores for ad accounts and properties |
| 6-08 | Web app: Reports (channels, campaigns, products); "How is this calculated?" everywhere; the registry's table definitions (`TABLES`) in every answer |
| 6-09 | Golden datasets (Nepal, Christmas, refund day, stale rate), property checks, correction check, performance check, browser test with real data, this report |

---

## 3. Acceptance criteria (plan §13)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | AUD store, Google Ads in AUD, Meta in USD, GA4: the overview's figures equal the golden values to the cent | ✅ | `test_metrics_engine.py::test_golden_values_to_the_cent`, `test_unified_analytics_api.py` (A$1,500.50 · A$204.50 · A$695.80 · 7.337408 · 13.633333); a second golden dataset in NPR (`test_metrics_golden.py`) |
| 2 | Each day's published rate; weekends and holidays use the last one; no rate is "not available" | ✅ | Christmas and weekend days use the 24 December rates; a rate 8 days old is not used; NZD converted in the browser test |
| 3 | A late refund, a Google correction or a cost edit changes every affected report at once | ✅ | `test_a_correction_changes_every_report_at_once` (computed on read) |
| 4 | Platform conversion values never added across platforms; GA4 never added to store or ad figures; users never added across days | ✅ | `test_each_platform_reports_its_own_figures_never_added_across`; the registry has no such sum; Reports say so |
| 5 | Every figure shows its definition version, sources and freshness; no page computes a formula | ✅ | Every answer carries `definition_version`, `sources[]`, `definitions[]`; static check `unified analytics pages compute no formula` |
| 6 | Missing inputs are "not available" or "not provided" with a reason, never 0 | ✅ | Engine, API and page tests; the browser test checks "Some products have no cost" and "Not provided by the platform" |
| 7 | All suites pass, with no network calls in CI | ✅ | §5; rates come from recorded answers (`tests/fx_sim.py`, `tests/e2e_fx_rates.py`) |

---

## 4. Security controls — how each is verified

| Control | Verified by |
|---|---|
| Rate clients: GET only, two fixed hosts, SSRF-safe client, no credentials | `test_fx_rates.py`; static rule (fx code is read-only) |
| `fx_rates` holds no tenant data; tenants can read, never write | Migration grants; `test_store_assignment.py::test_exchange_rates_are_read_only_to_the_application` |
| New routes respect tenant isolation | `tests/security/test_tenant_isolation.py` sweep (overview, channels, campaigns, products, both store routes) |
| A store of another organization is "not found" | `test_one_store_and_a_store_of_another_organization` |
| Store assignment: owners and admins only, CSRF, audited | `test_store_assignment.py`; web app tests |
| No platform token reaches a page | Browser test checks every page's HTML |
| No new personal data; customer acquisition cost stays unavailable rather than collecting customer keys (Q-6-8) | Registry; no new personal columns in 0016 |

---

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, pytest) | **1,580 passed**, coverage 97 % |
| Frontend `npm run check` (prettier, eslint, types, vitest) | **404 passed**, coverage 96 % |
| Browser tests (Playwright + axe) | **15 passed** (new: `unified-analytics.spec.ts`; the journey also opens Reports) |

Golden datasets: the AUD dataset of 6-04; the **Nepal dataset** (NPR store, Meta in USD, Google Ads in EUR through USD, Christmas, a weekend and a refund day, worked out by hand to the paisa); an **AUD business over Christmas**; a **stale rate**; an uncosted product; orders in another currency; a period starting before history. Property checks over seeded random data: **totals equal the sum of their days** for every sub-period; **converting and converting back** stays within one minor unit (2,000 cases, four currency pairs).

---

## 6. Database

Migration **0016** (additive, reversible): `fx_rates` (source, base, quote, day, rate, unit; the app role reads, the system role writes) and an optional `store_id` on `ad_accounts` and `analytics_properties` (same-organization foreign keys, set to null if the store is removed). No change to stored figures; nothing is precomputed.

---

## 7. Defects found during Phase 6 (all fixed)

1. A test helper reused one SQL parameter for a uuid and a text column (Postgres refused it) — separate parameters.
2. Test order lines without a cost source broke a database rule — the helper now sets it.
3. A literal one-day `timedelta` in the campaigns code broke the "durations only in settings" rule — ordinal day arithmetic.
4. Two answer types were both called `ProductOut` in the API types — renamed the new one `ProductFiguresOut`.
5. **Found by the browser test:** report tables that scroll sideways on narrow screens could not be scrolled with the keyboard (axe "scrollable region must be focusable") — they are now focusable, labelled regions.
6. **Found by the browser test:** two ad accounts with a campaign of the same name gave two identical rows — each row now names its ad account.

---

## 8. Deviations from the plan

1. **No `organization_reporting` table** (§7): the organization's own currency and time zone are the reporting settings (6-02).
2. **Rates off by default** (`FX_ENABLED=false`) until the deployment allows the two hosts; the ECB is read as CSV from its Data Portal (6-03).
3. The answer type `ProductFiguresOut` (6-06).
4. The day-by-day figures are a **table** (6-07); a chart can be added.
5. "How is this calculated?" for table columns is **one list under each table** rather than one per cell (6-08).
6. Property checks use **seeded random data in plain tests** rather than a property-testing library, so no new package was needed.

---

## 9. Not verified in this environment

- **Step 0 (6-01):** the live ECB and NRB feeds — the exact formats, a holiday, NRB's `unit` and a Saturday, and a week converted by AdVegaX against a hand calculation from the two published tables. The clients are built from the documented formats and tested against recorded copies.
- Step 0 of Phases 2A, 2B, 3, 4 and 5 (live platforms) is still pending as reported in those phases; the Overview's figures come from those imports.

---

## 10. Known limitations and remaining risks

| Limitation / risk | Mitigation |
|---|---|
| Profit does not include shipping costs or payment fees | The figure's name says so; entering those costs is ready to plan (Q-6-7) |
| Budget use uses today's budget for every day | Said next to the figure; budget history can come later (Q-6-11) |
| Google Analytics campaign match is by exact name only | "No matching Google Analytics campaign" otherwise; no guessing (Q-6-9) |
| Sources in different time zones count their own days | A visible note; single-time-zone businesses are unaffected (Q-6-4) |
| A rate feed is late or changes format | Last published rate for up to 7 days, then "not available"; Step 0 |
| Computing on read for very large organizations | Measured at ~0.5 s for 390 days × 20 sources; a summary table only if needed |

---

## 11. Rollback

Phase 6 adds read-only views over existing data. Migration 0016 is additive and reversible. Removing the Overview and Reports leaves stores, advertising and analytics pages unchanged; switching `FX_ENABLED` off stops reading rates (conversions then say "not available").

---

## 12. Next

1. **Your review** of Phase 6 (this report and `PHASE_06_PROGRESS.md`).
2. **Step 0 (6-01)** when the two rate hosts are allowed, together with the pending Step 0 checks of Phases 2A–5.
3. Then **Phase 7 — Funnel intelligence** (plan to be written and approved first).
