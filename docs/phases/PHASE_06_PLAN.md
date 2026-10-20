# Phase 6 — Unified analytics and financial engine: Implementation Plan

**Status:** 📝 **Draft — awaiting product-owner approval.** Nothing is built until it is approved (PROJECT_RULES §18: signed-off metric definitions, Q7). · **Date:** 2026-10-20

> **Live data:** Phase 6 reads only what Phases 2A–5 already store. Its one new outside source is the exchange-rate feed (Q-6-3). It is built and tested against a recorded copy of that feed; Step 0 (6-01) fetches the live feed once network access is allowed.

**Depends on:** Phases 2A and 2B (stores and `financial_daily`), 3 and 4 (ad accounts and `ad_performance_daily`), 5 (GA4 properties and `analytics_daily`). · **Followed by:** Phase 7 (funnel intelligence) and Phase 8 (AI planner), which read the figures defined here.
**Governing documents:** MASTER_SPECIFICATION §4 (8), §7, §20 (D3, D17, D18); A5, A10; DISCOVERY_REPORT Q7, Q9; `phases/PHASE_06_UNIFIED_ANALYTICS_FINANCE.md` (outline); `phases/PHASE_02A_PLAN.md` §10 (finance-v1, the store half of Q7, approved); API_SPECIFICATION §15; DATABASE_SCHEMA §13.

---

## 1. Objective

Give an organization **one trustworthy view** of what it sells, what it spends on advertising and what is left, across its stores, Google Ads, Meta and Google Analytics:

- **overview** for a period: net sales, orders, ad spend (all platforms), gross profit, profit after ad spend, blended ROAS, cost per order, and the platform-reported figures beside them;
- **by channel**: Google Ads, Meta, and Google Analytics' channels (organic search, paid search, …);
- **by campaign**: every ad campaign's platform-reported figures, with Google Analytics' visits and revenue for the same campaign where they match;
- **by product**: net sales, units, product cost and gross profit per product;
- in **one reporting currency and time zone** chosen by the organization, with every converted figure saying so, and every original figure still available.

Every figure comes from **one registry of definitions** in the backend, carries its **definition version**, its **sources** and how **fresh** they are. No screen computes its own formula (MASTER §7). Missing inputs make a figure "not available" with a reason — never a partial number shown as complete (A10).

**Q7 (the remaining half)** is settled by this plan. The store half — net sales, refunds on the day they happen, product cost from the platform, the strict missing-cost rule — was approved in Phase 2A (`finance-v1`) and stays unchanged.

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all of them at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-6-1** | Which store do ad accounts and Google Analytics properties belong to? | **The organization's view combines everything it has linked.** If the organization has **one store**, every ad account and property counts for it automatically. With **several stores**, an owner or admin assigns each ad account and property to a store (or leaves it "whole organization"); store pages then show only their own. | Most businesses have one store; they should not have to configure anything. Agencies and multi-brand owners need the split. |
| **Q-6-2** | Which currency and time zone are reports in? | An **organization reporting currency and time zone**, set in Settings, defaulting to the first linked store's. Each source keeps its own figures; reports convert them. | One total needs one currency. Defaulting to the store keeps single-store businesses at zero set-up. |
| **Q-6-3** | Where do exchange rates come from? | The **European Central Bank's daily reference rates** (free, official, about 30 currencies incl. AUD, USD, NZD, GBP, EUR, JPY, INR), using **each day's own rate** (the last published rate for weekends and holidays). For **NPR**, which the ECB does not publish, the **Nepal Rastra Bank**'s daily rate (middle of its buy and sell rates). Any other currency is "not available — no exchange rate", never guessed. | Official, free, reproducible sources. A figure converted with each day's rate does not change when rates move later. NPR matters for your Nepal work. |
| **Q-6-4** | Days in different time zones (a Sydney store, a Los Angeles ad account) | **Each source's own days are used as they are**, labelled. A Sydney store's 5 October and a Los Angeles account's 5 October are put on the same report day. A note says when sources' time zones differ. | Platforms give daily figures only, so they cannot be moved to another time zone exactly. This is the same choice Google Ads, Meta and Shopify make when they show each other's numbers. |
| **Q-6-5** | Which revenue counts for blended figures? | **Net sales** from the store (after discounts and returns, before tax and shipping) — the same figure as the store page (`finance-v1`). | It is the money the business keeps from selling products; tax and shipping are passed on. |
| **Q-6-6** | ROAS: the platforms' or AdVegaX's? | **Both, side by side, never mixed.** *Blended ROAS* = net sales ÷ total ad spend (all platforms, converted). *Platform-reported ROAS* = each platform's conversion value ÷ its spend, labelled "Reported by Google Ads / Meta". AdVegaX never adds platform conversion values together (the same sale is often claimed by both). | Blended ROAS is the business truth (D3); platform ROAS is what people see in Ads Manager and must still be explainable. |
| **Q-6-7** | Profit after advertising | **Gross profit** (net sales − product cost; finance-v1's strict rule) and **profit after ad spend** (gross profit − ad spend). Shipping costs and payment fees are **not provided by Shopify or WooCommerce**, so v1 shows them as "not provided" and names the figure "profit after ad spend (before shipping costs and payment fees)". A true **contribution profit** comes when you approve a way to enter those costs (future option: your own fee % and shipping cost per order, labelled "estimated"). | Never present a profit as complete when costs are missing (A10). The name says exactly what is included. |
| **Q-6-8** | Cost per order and customer acquisition cost (CAC) | **Cost per order** (blended) = total ad spend ÷ store orders; the platforms' own cost per conversion stays beside it. **CAC** (ad spend ÷ new customers) is shown as "not available — new customers are not identified yet", because AdVegaX does not collect a customer key today (Q8 kept that out). | CAC needs new-customer counts; guessing them would be wrong. Turning on the hashed customer key is a separate privacy decision. |
| **Q-6-9** | Attribution | **No AdVegaX attribution model in v1.** Each platform's own attribution is shown as theirs; blended figures need none. On the campaign page, Google Analytics' sessions, purchases and revenue are shown for a campaign when GA4's source / medium / campaign **matches the campaign's name** exactly (google / cpc / *name* for Google Ads; facebook or instagram / paid or cpc / *name* for Meta), labelled "Reported by Google Analytics". | Attribution models are a product of their own (and guesswork without click ids). Name matching is transparent and lets the merchant see a second opinion. |
| **Q-6-10** | Products and ad spend | **Product profitability without ad spend in v1**: net sales, units, product cost, gross profit and margin per product, from the store. Ad spend per product is not shown, because Google Ads and Meta figures are imported per campaign, not per product. | Splitting campaign spend across products would be an invented number. Product-level ad data (Shopping / catalogue reports) can come later. |
| **Q-6-11** | Budget use | **Spend against the current daily budget** for campaigns with a daily budget, labelled "against today's budget" — AdVegaX does not keep budget history yet. Lifetime and shared budgets show spend only. | Useful for pacing now; the label avoids implying a historical comparison. |
| **Q-6-12** | Rounding | **Exact decimals everywhere**; conversion uses the full published rate; rounding half-even to the currency's minor unit **only for display** (as since Phase 2A). Rates and ratios: six decimals in the API. | Consistent with every earlier phase; totals never drift from their parts. |
| **Q-6-13** | When late data arrives (refunds, Google's corrections, a product cost edit) | **Computed on read** from the stored daily figures and rates, so every report is always current — nothing to recompute. A stored summary table is added only if pages become slow (measured in 6-09). | The daily tables are already corrected in place by the Phase 2–5 syncs; computing on read removes a whole class of "stale summary" bugs. |

## 2A. What you need to set up

1. **Nothing in Google, Meta or the stores.**
2. **Network access** for `data-api.ecb.europa.eu` (ECB rates) and `www.nrb.org.np` (NPR rates), when Step 0 runs. Both are public; no account or key is needed.
3. **Your reporting currency and time zone**, if not your first store's — in Settings once Phase 6 is built.

## 3. Scope

| Area | In Phase 6 |
|---|---|
| Exchange rates | `app/domains/fx/`: daily ECB rates (all published currencies) and NRB's NPR rate, stored once for all organizations; a daily job; the "last published rate" rule for weekends and holidays; cross rates through EUR, computed in one place |
| Settings | Organization reporting currency and time zone; ad account and property → store assignment (Q-6-1) |
| Metric registry | `app/domains/metrics/`: every unified metric defined once (`analytics-v1`): inputs, formula, unit, availability rules, sources; used by the API and by later phases (funnel, AI) |
| API | `GET /analytics/overview`, `/analytics/channels`, `/analytics/campaigns`, `/analytics/products` (API_SPECIFICATION §15), each with `definition_version`, `currency`, `sources[]` with freshness, and availability on every figure; Settings routes for reporting currency, time zone and assignments |
| Web app | An **Overview** page (replaces the organization's welcome page), channel, campaign and product tables, the reporting settings, and "how this is calculated" for every figure |
| Data | Migration **0016**: `fx_rates` (global, read-only to tenants), organization reporting settings, store assignment on `ad_accounts` and `analytics_properties` |

## 3A. Non-goals

- Any AdVegaX attribution model, data-driven or multi-touch; click-id matching.
- Ad spend per product; campaign-to-product mapping.
- Entering shipping costs or payment fees (a future option, Q-6-7). CAC from customer identification (Q-6-8).
- Funnels (Phase 7), recommendations or AI explanations (Phase 8).
- Forecasts, targets, alerts, scheduled email reports, exports.
- Changing anything at any platform.

## 4. Facts and Step 0

### 4.1 Exchange-rate sources (checked 2026-10-20)

1. **ECB euro foreign exchange reference rates:** about 30 currencies against the euro, set at 14:10 CET on every TARGET working day and published around 16:00 CET; no rates on weekends and TARGET holidays. The Russian rouble has been suspended since March 2022. Free, for information purposes. Machine-readable through the ECB Data Portal (SDMX series `EXR.D.<CUR>.EUR.SP00.A`).
2. **Nepal Rastra Bank daily rates:** NPR buy and sell rates for about 20 currencies, some per 10 or 100 units (`unit`), published daily; a public JSON API with date range and paging.
3. **Cross rates** (e.g. AUD → USD) are computed through EUR from the same day's two ECB rates; NPR → X through NRB's rate for X (or through USD where NRB has no X).

### 4.2 Step 0 — the live feeds (task 6-01)

1. ECB: one day and a date range for AUD, USD, NZD, GBP, JPY, INR; the exact response format; how a holiday looks.
2. NRB: one day's rates; the `unit` field (JPY per 10, INR per 100); the buy/sell values; a Saturday.
3. A fixed week converted by AdVegaX equals a hand calculation from the two published tables.

## 5. Proposed structure

```
app/domains/fx/        models, ecb + nrb clients (SSRF-safe, read-only), daily job, convert()
app/domains/metrics/   registry (analytics-v1), inputs from finance / advertising / analytics, read service, router, schemas
frontend/features/overview/   overview, channels, campaigns, products, "how this is calculated"
```

The exchange-rate clients reuse the SSRF-safe HTTP client with only the two fixed hosts allowed; nothing they fetch is ever personal or tenant data.

## 6. Definitions (`analytics-v1`)

All amounts in the **reporting currency**; each source's figure converted with its own day's rate (Q-6-3, Q-6-4). A figure is "not available" with a reason when any input is missing (product cost, an exchange rate, a day not synced), and "not provided" when no connected platform offers it.

| Metric | Definition | Sources |
|---|---|---|
| Net sales | Σ store `net_sales` (finance-v1) | Stores |
| Orders | Σ store `orders_count` | Stores |
| Product cost | Σ store `cogs` (finance-v1: not available if any line is uncosted) | Stores |
| Gross profit | net sales − product cost | Stores |
| Ad spend | Σ account-level `cost` of every linked ad account | Google Ads, Meta |
| Profit after ad spend (before shipping costs and payment fees) | gross profit − ad spend | Stores, ads |
| Blended ROAS | net sales ÷ ad spend ("no ad spend" when 0) | Stores, ads |
| Cost per order | ad spend ÷ orders ("no orders" when 0) | Stores, ads |
| Ad spend share of sales | ad spend ÷ net sales | Stores, ads |
| Platform-reported conversions, value, ROAS | each platform's own, **never added across platforms** | Google Ads, Meta |
| Sessions, purchases, revenue (GA4) | Σ GA4 `total` view; users per day only (Q-5-5) | Google Analytics |
| Store conversion rate (GA4) | store orders ÷ GA4 sessions, only when every linked store has a linked property | Stores, GA4 |
| Shipping cost, payment fees, contribution profit, CAC | "not provided" / "not available" in v1 (Q-6-7, Q-6-8) | — |
| Budget use | spend ÷ (current daily budget × days) for daily budgets (Q-6-11) | Google Ads, Meta |

## 7. Data model (migration 0016, additive)

- **`fx_rates`**: source (`ecb` | `nrb`), base, quote, rate date, rate (exact decimal, as published), unit, fetched time. Unique per source, base, quote and date. Not tenant data: readable by the app role, written only by the system role.
- **`organization_reporting`**: reporting currency and time zone per organization (forced RLS).
- **`ad_accounts.store_id`**, **`analytics_properties.store_id`**: optional, with composite tenant keys (Q-6-1).

## 8. API (API_SPECIFICATION §15, made concrete)

- `GET /analytics/overview?from&to&store_id` — the §6 metrics for the period, by day and in total.
- `GET /analytics/channels?from&to` — per ad platform and per GA4 channel.
- `GET /analytics/campaigns?from&to` — every campaign with platform-reported figures and matched GA4 figures (Q-6-9).
- `GET /analytics/products?from&to&store_id` — per product (Q-6-10).
- `GET/PUT /reporting-settings`; `PUT /ad-accounts/{id}/store`, `PUT /analytics-properties/{id}/store`.

Every answer: `definition_version`, `reporting_currency`, `reporting_timezone`, `sources[] {kind, id, name, currency, timezone, synced_through, freshness}`, `conversions[] {from, rate_source, first_day, last_day}`, and per figure `availability` + `reason`. `analytics.view` for every member; settings for owners and admins.

## 9. Web app

- **Overview** (the organization's home page): the period's key figures as tiles, a day-by-day table, "where the numbers come from" (sources and freshness), notes for converted currencies and differing time zones.
- **Channels**, **Campaigns** (with the GA4 match column) and **Products** tables.
- **"How is this calculated?"** next to every figure, generated from the registry, never hand-written per page.
- **Settings:** reporting currency and time zone; which store each ad account and property belongs to.
- Every page checked for accessibility.

## 10. Security and privacy

- Exchange-rate clients: two fixed public hosts through the SSRF-safe client, GET only, no credentials.
- `fx_rates` holds no tenant data; tenants can read but not write it.
- All other new data is tenant-owned with forced RLS; route sweeps cover the new routes.
- No new personal data; CAC stays unavailable rather than collecting customer keys (Q-6-8).

## 11. Testing

- **Golden datasets** reproducing hand-calculated results: one AUD store with Google Ads in AUD and Meta in USD, Google Analytics in AUD; one NPR store with ads in USD; weekends and an ECB holiday; a refund day; an uncosted product; a period starting before history.
- Recorded ECB and NRB answers for the clients (no network in CI).
- Property-based checks: totals equal the sum of their days; converting and converting back stays within one minor unit.
- API sweeps; page tests; one browser test with accessibility checks.

## 12. Tasks (one at a time, report after each)

| Task | Content |
|---|---|
| 6-01 | Step 0: live ECB and NRB feeds (§4.2) — waits for network access |
| 6-02 | Migration 0016, reporting settings, store assignment |
| 6-03 | Exchange rates: clients, daily job, conversion rules |
| 6-04 | Metric registry `analytics-v1` and its inputs |
| 6-05 | Overview and channels API |
| 6-06 | Campaigns (with GA4 match) and products API |
| 6-07 | Web app: Overview, settings |
| 6-08 | Web app: channels, campaigns, products, "how is this calculated?" |
| 6-09 | Golden datasets, performance check, browser test, `PHASE_06_REPORT.md` |

## 13. Acceptance criteria

1. With an AUD store, Google Ads in AUD, Meta in USD and GA4 linked, the overview shows net sales, ad spend, gross profit, profit after ad spend, blended ROAS and cost per order in the reporting currency, and they equal the golden values to the cent.
2. Converted figures use each day's published rate; weekends and holidays use the last published rate; a currency without a rate is "not available".
3. A late refund, a Google correction or a product cost edit changes every affected report at once, with no recomputation step.
4. Platform conversion values are never added across platforms; GA4 figures are never added to store or ad figures; users are never added across days.
5. Every figure shows its definition version, sources and freshness; no page computes a formula (static check on the web app).
6. Missing inputs are "not available" or "not provided" with a reason, never 0.
7. All suites pass, with no network calls in CI.

## 14. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Merchants expect a profit that includes shipping and fees | MEDIUM | The figure's name says what is excluded; the costs-entry option is ready to plan (Q-6-7) |
| Different time zones shift a day's figures between sources | MEDIUM | Each source's own days, a visible note; single-time-zone businesses are unaffected (Q-6-4) |
| A source of exchange rates is late or changes format | LOW | Last published rate with its date shown; recorded answers in tests; Step 0 |
| GA4 campaign names differ from ad campaign names (UTM tagging) | LOW | Exact match only, shown as "no match" otherwise; no guessing |
| Computing on read becomes slow for large organizations | LOW | Measured in 6-09; a summary table only if needed (Q-6-13) |

## 15. Rollback

Phase 6 adds read-only views over existing data. Migration 0016 is additive and reversible. Removing the Overview leaves stores, advertising and analytics pages unchanged.

## 16. Approval checklist

Approve or change **Q-6-1 … Q-6-13** (they complete Q7), the live-feed Step 0 (§4.2), the data model (§7) and task-by-task delivery 6-01 … 6-09. No new runtime packages are proposed.

## Sources (checked 2026-10-20)

- [ECB euro foreign exchange reference rates](https://www.ecb.europa.eu/stats/shared/pdf/eurofxref.pdf) and a daily table as republished by the [Banca d'Italia (3 August 2026)](https://www.bancaditalia.it/compiti/operazioni-cambi/cambio/cambi_rif_20260803) — 30 currencies, 14:10 CET reference time, rouble suspended
- [Nepal Rastra Bank — forex downloads](https://www.nrb.org.np/download-forex) and a [client library's description of the NRB rate API](https://github.com/remotemerge/nrb-forex-node/blob/main/README.md) (buy/sell, unit, date range, paging) — the exact endpoint is confirmed in Step 0
