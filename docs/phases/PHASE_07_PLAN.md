# Phase 7 — Funnel intelligence: Implementation Plan

**Status:** 📝 **Draft — awaiting product-owner approval.** No Phase 7 code is written until you approve. · **Date:** 2026-10-21

> **Live data:** Phase 7 reads what Phases 2A–6 store, plus a few more figures from Google Analytics and Meta that the funnel needs (§4). Those are built and tested against the simulators; Step 0 (7-01) checks the exact names with Google and Meta once access allows.

**Depends on:** Phase 6 (the registry, conversion, store assignment, the Overview), Phase 5 (GA4 import), Phase 4 (Meta import), Phase 3 (Google Ads import), Phases 2A/2B (store orders). · **Followed by:** Phase 8 (AI planner) and Phase 11 (optimization), which read the funnel and its findings.
**Governing documents:** MASTER_SPECIFICATION §6 (funnel model), §20 D18, D19; A10; DISCOVERY_REPORT §11; `phases/PHASE_07_FUNNEL.md` (outline); API_SPECIFICATION §15–§16; DATABASE_SCHEMA `funnel_daily`.

---

## 1. Objective

Show **where buyers drop out**, from the first ad impression to the purchase, using only figures the platforms really report:

> impression → click → landing page view → product view → add to cart → checkout started → purchase

- **Every stage says where its number comes from** (Google Ads / Meta, Google Analytics, or the store), and every step's conversion rate says whether its two numbers come from the same source.
- **For the whole business, per ad platform, per Google Analytics channel, per campaign and per landing page**, for any period, in the Overview's period and store choice.
- **Drop-offs are found by fixed rules** (no AI yet): a step whose rate fell clearly below its own recent level, with enough volume to mean something — written in plain words, and stored in a form Phase 8/11 can read later.
- **A stage no connected platform reports is "not provided", a day not read is "not synced yet" — never 0** (D18, A10). Revenue → profit stay where they are (Phase 6), shown after the funnel, not as stages.

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all of them at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-7-1** | Where does each stage come from? | **Impressions and clicks:** Google Ads and Meta (added up — both are counts of real ad events). **Landing page view:** Google Analytics sessions (every visit starts on a landing page); Meta's own "landing page views" shown in Meta's funnel. **Product view, add to cart, checkout started:** Google Analytics' ecommerce events (`view_item`, `add_to_cart`, `begin_checkout`). **Purchase:** store orders (the business truth), with Google Analytics' purchases shown beside them. | Each stage uses the source that measures it best. The store is right about purchases; Google Analytics is the only source that sees the whole website. |
| **Q-7-2** | Rates between stages from different sources (e.g. ad clicks → website visits) | **A step's rate is shown only when both stages come from the same source**, or the step is a well-understood ratio (store orders ÷ sessions, as in Phase 6). A step across sources shows both numbers and says "different sources — no rate". | Ad clicks and website sessions are counted differently (a click can fail to load the page; sessions include organic visitors). A rate between them would look precise and be wrong. |
| **Q-7-3** | Extra Google Analytics figures | Add **product views, add to carts and checkouts** to the GA4 import (Data API metrics `itemViewEvents`, `addToCarts`, `checkouts`, all event-scoped, compatible with the date / channel / source views) and a **fourth view by landing page** (`landingPage`, the largest 500 per day plus "(other)", like the source view). Existing properties re-read their 13 months once, in the background, at the usual pace. | The funnel's middle is only visible in Google Analytics. Re-reading is automatic and uses the existing quota rules; days not re-read yet say "not synced yet". |
| **Q-7-4** | Extra Meta figures | Add Meta's own funnel actions to the import: **landing page views** (`landing_page_view`), **content views** (`omni_view_content`), **adds to cart** (`omni_add_to_cart`) and **checkouts initiated** (`omni_initiated_checkout`), like Phase 4's `omni_purchase`. Meta accounts re-read their 13 months once. Google Ads has no such stages: "not provided by Google Ads". | Meta's funnel per campaign is what merchants already look at in Ads Manager; it is labelled "Reported by Meta" and never added to Google Analytics' counts. |
| **Q-7-5** | Events or people? | **Events, labelled as events** ("adds to cart", not "people who added to cart"), as the platforms report them. A shopper who adds two products counts twice. | Unique people per stage are not available from the daily reports and cannot be added across days (Q-5-5). Saying "events" keeps the numbers honest. |
| **Q-7-6** | Breakdowns | **Whole business, per ad platform, per GA4 channel, per campaign** (Google Analytics part matched by exact campaign name, as Q-6-9) **and per landing page.** **Per product: not in v1** — it needs Google Analytics' item-level reports and a reliable match of GA's item ids to store products, which differs per store setup; planned as a later addition. | Campaign and landing-page funnels answer "which ad or page loses buyers". Product matching would be a guess today. |
| **Q-7-7** | How are drop-offs found? | **Fixed rules, no AI:** a same-source step is flagged when, for the period, its rate is **at least 25 % lower than the same step in the previous period of equal length** *and* lower than its **own 90-day average**, and the earlier stage had **at least 200 events** (both numbers are settings). A stage that is "not provided" is never flagged. No industry benchmarks. | Comparing a business with itself is fair and explainable; minimum volume avoids alarms on small numbers. Phase 11 can later add AI explanations on top of these findings. |
| **Q-7-8** | Store the funnel or compute it? | **Computed on read**, like Phase 6 (measured at about 0.5 s for a year of a large organization). The planned `funnel_daily` table is marked superseded in DATABASE_SCHEMA. Findings are computed on read too. | Always current after late corrections; no summary to go stale. |
| **Q-7-9** | Unattributed traffic | Visits that match no campaign are shown as **"Other traffic"** in the campaign view, so campaign rows plus "Other traffic" add up to the whole website. | The merchant sees how much of the funnel the campaigns explain, with nothing hidden. |

## 2A. What you need to set up

1. **Nothing new in Google, Meta or the stores.** The same read-only permissions already approved are enough (`analytics.readonly`; Meta `ads_read`).
2. **For Step 0 (7-01):** the Phase 5 and Phase 4 Step 0 access (a GA4 property with ecommerce events, a Meta ad account with a pixel), and network access to Google and Meta, when available.
3. **For the funnel to be complete:** your stores' Google Analytics should send the standard ecommerce events (`view_item`, `add_to_cart`, `begin_checkout`, `purchase`). Shopify's and WooCommerce's Google integrations do. If they are missing, those stages show "no events reported" — the page says how to fix it.

## 3. Scope

| Area | In Phase 7 |
|---|---|
| GA4 import | Three more metrics on every view; a fourth view by landing page; a one-time background re-read of existing properties (Q-7-3) |
| Meta import | Four more action types on every level; a one-time background re-read (Q-7-4) |
| Funnel registry | `funnel-v1`: each stage's source and definition; each step's rate rule (Q-7-1, Q-7-2), in the Phase 6 registry style |
| Findings | Deterministic drop-off rules (Q-7-7), in plain words, with the numbers behind them |
| API | `GET /analytics/funnel` (whole business, per platform, per channel), `/analytics/funnel/campaigns`, `/analytics/funnel/landing-pages`; same period, store, currency, sources and definitions as Phase 6 |
| Web app | A **Funnel** page (in the menu after Reports): the funnel with source labels, rates and "different sources" steps; per platform / channel / campaign / landing page; findings; "How is this calculated?" |
| Data | Migration **0017**: the new columns on `analytics_daily` and `ad_performance_daily` (nullable: unknown until re-read); the `landing_page` view |

## 3A. Non-goals

- Unique people per stage, cohorts, session paths or user journeys.
- Product-level funnel (Q-7-6), on-site event tracking by AdVegaX, a pixel or tag of its own.
- Any attribution model; Google Ads conversion actions per stage.
- AI explanations or recommendations (Phases 8 and 11); alerts or emails.
- Changing anything at any platform.

## 4. Facts and Step 0

### 4.1 Facts (from the documentation, checked 2026-10-21)

1. **GA4 Data API:** `addToCarts` and `checkouts` are event-scoped ecommerce metrics; `itemViews` was renamed **`itemViewEvents`** (the count of `view_item` events). Item-scoped dimensions (item id, name) are **not** compatible with event-scoped metrics, so a product-level funnel needs separate item-scoped reports (item-scoped metrics such as `itemsPurchased`) — one reason Q-7-6 defers it. The `landingPage` dimension gives the path a session started on (exact name and behaviour confirmed in Step 0).
2. **Meta Insights API:** the `actions` list carries action types including `landing_page_view` and the cross-channel `omni_*` types (`omni_add_to_cart`, `omni_initiated_checkout`, `omni_view_content`; `omni_purchase` is used since Phase 4). Meta's reference was not directly readable from this environment; third-party connector documentation lists the same names — Step 0 confirms them.
3. **Google Ads** reports impressions, clicks and conversions per campaign; it has no landing-page or cart stages (its conversion actions are the merchant's own definitions).

### 4.2 Step 0 — live checks (task 7-01)

1. GA4: one report with `itemViewEvents`, `addToCarts`, `checkouts` by date and by channel; one by `landingPage`; how "(not set)" and "(other)" appear; that the numbers match the GA4 interface's funnel exploration for the same days.
2. Meta: one day's insights for an account with a pixel: the four action types, and that they match Ads Manager's columns.
3. One week of AdVegaX's funnel equals a hand calculation from the platforms' own screens.

## 5. Proposed structure

```
app/providers/google_analytics/   + metrics, + landing_page view
app/providers/meta_ads/           + four action types
app/domains/funnel/               registry (funnel-v1), engine, findings, read service, router, schemas
frontend/features/funnel/         Funnel page, breakdowns, findings
```

The funnel domain reads only AdVegaX's normalized tables — nothing platform-specific (D19).

## 6. Definitions (`funnel-v1`)

| Stage | Definition | Source |
|---|---|---|
| Impressions | Σ ad impressions | Google Ads, Meta |
| Clicks | Σ ad clicks (Google Ads clicks; Meta link clicks) | Google Ads, Meta |
| Landing page views | Σ GA4 sessions | Google Analytics |
| Product views | Σ GA4 `view_item` events | Google Analytics |
| Adds to cart | Σ GA4 `add_to_cart` events | Google Analytics |
| Checkouts started | Σ GA4 `begin_checkout` events | Google Analytics |
| Purchases | Σ store orders (GA4 purchases beside them) | Stores (Google Analytics) |

| Step | Rate | Shown |
|---|---|---|
| Impressions → clicks | clicks ÷ impressions (click-through rate) | Same source |
| Clicks → landing page views | — | "Different sources — no rate" |
| Landing page views → product views → adds to cart → checkouts | each ÷ the one before | Same source (Google Analytics) |
| Checkouts → purchases (GA4) | GA4 purchases ÷ checkouts | Same source |
| Landing page views → purchases (store) | store orders ÷ sessions (Phase 6's store conversion rate) | The one approved cross-source ratio |

Per platform (Meta): impressions → link clicks → landing page views → content views → adds to cart → checkouts → purchases, all "Reported by Meta". Google Ads: impressions → clicks → conversions; other stages "not provided by Google Ads".

## 7. Data model (migration 0017, additive)

- `analytics_daily`: `item_view_events`, `add_to_carts`, `checkouts` (nullable integers: null = not read yet); the `breakdown` value **`landing_page`** with `landing_page` as its dimension.
- `ad_performance_daily`: `landing_page_views`, `content_views`, `adds_to_cart`, `checkouts_initiated` (nullable decimals, as Meta reports; null for Google Ads = not provided).
- A per-source **re-read marker** so the background re-read happens once.
- No new tenant tables; forced RLS unchanged. DATABASE_SCHEMA `funnel_daily` marked superseded (Q-7-8).

## 8. API (API_SPECIFICATION §15–§16, made concrete)

- `GET /analytics/funnel?from&to&store_id&view=total|platform|channel` — stages, steps (rate or "different sources"), findings.
- `GET /analytics/funnel/campaigns?from&to&store_id` — each campaign's funnel (platform part + GA4 part by exact name) and "Other traffic".
- `GET /analytics/funnel/landing-pages?from&to&store_id` — the largest landing pages with their funnel.
- Every answer: `definition_version` (`funnel-v1`), reporting currency and time zone, sources with freshness, definitions, availability on every figure. `analytics.view` for every member.

## 9. Web app

- **Funnel** page: the stages as a bar list (each bar labelled with its source and count, never 0 for missing), step rates between them or "different sources", the purchases with revenue and profit from Phase 6 after them.
- Views: whole business · per platform · per channel · campaigns · landing pages.
- **Findings** at the top in plain words ("Adds to cart → checkouts fell from 42 % to 28 % compared with the previous 30 days").
- "How is this calculated?" from the registry; accessibility checked.

## 10. Security and privacy

- No new permission at Google or Meta; the read-only gates are extended only with the new field names (static tests).
- Landing pages are stored as paths **without query strings** (`landingPage`, not `landingPagePlusQueryString`), so no personal data in URLs is kept.
- Tenant sweeps cover the new routes; no new personal data.

## 11. Testing

- Simulators extended with the new metrics, the landing-page view and the Meta actions; re-read tested.
- **Golden funnel** worked out by hand: one store, Google Ads, Meta and GA4 over two periods, including a real drop-off, a stage not provided, a day not read and small volumes that must not be flagged.
- Property checks: stage totals equal the sum of their days; campaign rows plus "Other traffic" equal the whole website.
- API sweeps; page tests; one browser test with accessibility checks.

## 12. Tasks (one at a time, report after each)

| Task | Content |
|---|---|
| 7-01 | Step 0: live GA4 and Meta checks (§4.2) — waits for access |
| 7-02 | Migration 0017; GA4 import: new metrics and the landing-page view; the one-time re-read |
| 7-03 | Meta import: the four action types; the one-time re-read |
| 7-04 | Funnel registry `funnel-v1` and engine (stages, steps, sources, availability) |
| 7-05 | Drop-off findings (Q-7-7) |
| 7-06 | Funnel API (total / platform / channel, campaigns, landing pages) |
| 7-07 | Web app: Funnel page |
| 7-08 | Golden datasets, browser test, `PHASE_07_REPORT.md` |

## 13. Acceptance criteria

1. With a store, Google Ads, Meta and GA4, the funnel shows every stage with its source and equals the golden values.
2. A stage no connected platform reports is "not provided"; a day not read is "not synced yet"; never 0.
3. No rate is shown between stages of different sources, except the approved store conversion rate.
4. Campaign rows plus "Other traffic" add up to the whole website's figures.
5. Findings follow Q-7-7 exactly; small volumes are never flagged.
6. Funnel totals reconcile with the source figures shown elsewhere (Phase 5 property page, Phase 6 Overview).
7. All suites pass, with no network calls in CI.

## 14. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| A store's Google Analytics does not send ecommerce events | MEDIUM | Those stages say "no events reported" with how to fix it; never 0 |
| Merchants compare ad clicks with sessions | MEDIUM | "Different sources — no rate", with a short explanation (Q-7-2) |
| GA4 or Meta field names differ live | LOW | Step 0; recorded-format tests; unknown fields are null, never guessed |
| The re-read uses GA4 quota | LOW | Existing pacing and quota rules; runs in the background, day by day |
| Drop-off rules flag normal seasonality | LOW | Two conditions (previous period and 90-day average), minimum volume, settings adjustable |

## 15. Rollback

Phase 7 adds read-only views and nullable columns. Migration 0017 is additive and reversible. Removing the Funnel page leaves Phase 6 unchanged; the extra imported figures are simply unused.

## 16. Approval checklist

Approve or change **Q-7-1 … Q-7-9**, the Step 0 (§4.2), the data model (§7) and task-by-task delivery 7-01 … 7-08. No new runtime packages are proposed.
