# Phase 7 — Implementation Report (funnel intelligence)

**Date:** 2026-10-23 · **Branch:** `feature/phase-1a` · **Status:** Implemented against the GA4 and Meta simulators — awaiting product-owner review. **Step 0 (7-01) is still pending**: it needs the Phase 4 and 5 live access (a GA4 property sending ecommerce events, a Meta ad account with a pixel) and network access to Google and Meta.
**Plan:** `PHASE_07_PLAN.md` (approved 2026-10-22, A25, all recommendations Q-7-1 … Q-7-9) · Task-by-task reports: `PHASE_07_PROGRESS.md` (7-02 … 7-08).

---

## 1. Summary

An organization can now see **where buyers drop out**, from the first ad impression to the purchase:

> impressions → clicks → landing page views → product views → adds to cart → checkouts started → purchases

- **Every stage says where its number comes from:** impressions and clicks from Google Ads and Meta; landing page views (visits), product views, adds to cart and checkouts from Google Analytics; purchases from **the store's orders**, with Google Analytics' own purchases shown beside them — never added to them.
- **A rate only between stages of the same source.** Ad clicks → website visits says "Different sources — no rate", because the two are counted differently; the one approved cross-source figure is the store conversion rate (orders per visit, from Phase 6).
- **Events, not people:** one shopper who views three products counts three times; the page says so.
- **Five views:**
  - the **whole business**;
  - **each ad platform's own funnel** — Meta reports every stage (impressions → link clicks → landing page views → content views → adds to cart → checkouts → purchases); Google Ads only impressions → clicks → conversions, the rest "Not provided by the platform";
  - **each Google Analytics channel** (Organic Search, Paid Search, …);
  - **each campaign** — its platform's own figures and Google Analytics' funnel for the campaign of exactly the same name, then **Other traffic** and the **Website**, which they always add up to;
  - **each landing page** (paths only — no query strings are stored).
- **"Where buyers drop out"** — findings by fixed rules, no AI: a business is compared with itself. A step is flagged when it is **at least 25 % lower** than in the previous period of the same length, **below its own 90-day average**, and had **at least 200 events** before it. Written in plain words, e.g. "Adds to cart fell from 25.0% to 15.0% of product views, compared with 30 Sep to 6 Oct. It is also below its usual 25.0%." Never on missing data; the three numbers are settings. Phase 8 and 11 can read the same findings.
- **New figures imported for the funnel's middle:**
  - from **Google Analytics**: product views (`view_item`), adds to cart, checkouts, and a fourth view by landing page — in the same single request per slice;
  - from **Meta**: landing page views, content views, adds to cart, checkouts initiated — from the same `actions` list already read for purchases (no extra request);
  - properties and Meta accounts imported before Phase 7 are **read once more** over their history, in the background, only when no regular update is due; until then those figures say "not synced yet".

The promises of every earlier phase hold:

- **Missing data is never shown as 0.** A day not read is "Not synced yet"; a stage a platform does not report is "Not provided"; a Google Analytics property that reports visits but **no ecommerce events at all** says "No events reported — check your Google Analytics ecommerce set-up".
- **Read-only.** No new permission at Google or Meta; the funnel code only reads (a static check).
- **Computed on read** (Q-7-8): a late correction shows at once. Measured: a 90-day funnel with its findings for a large organization (5 stores, 10 ad accounts, 5 properties) answers in about **0.3 s**.
- **Tenant isolation.** The new routes are covered by the tenant sweeps; another organization's data or store is "not found".

---

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 7-01 | ⏸ Step 0 — waits for live access (§9) |
| 7-02 | Migration **0017**; GA4 import: `itemViewEvents`, `addToCarts`, `checkouts` and the `landingPage` view (paths only); one-time re-read (sync mode `reread`) |
| 7-03 | Meta import: `landing_page_view`, `omni_view_content`, `omni_add_to_cart`, `omni_initiated_checkout`; one-time re-read; Google Ads never re-read for them |
| 7-04 | Funnel registry `funnel-v1` (stages with sources, step kinds, platform and channel funnels) and engine |
| 7-05 | Drop-off findings (Q-7-7) |
| 7-06 | `GET /analytics/funnel`, `/analytics/funnel/campaigns`, `/analytics/funnel/landing-pages` |
| 7-07 | Web app: the Funnel page |
| 7-08 | Golden datasets, property checks, reconciliation, performance, this report |

---

## 3. Acceptance criteria (plan §13)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Every stage with its source; equals the golden values | ✅ | `test_funnel_engine.py::test_the_golden_funnel`, `test_funnel_api.py` (4,800 → 140 → 500 → 200 → 50 → 20; store orders 15) |
| 2 | Not provided / not synced, never 0 | ✅ | Engine tests (days not read, figures not re-read, no events reported, nothing connected); page tests |
| 3 | No rate between different sources, except the store conversion rate | ✅ | Registry test; `different_sources` steps have `rate: null`; the page says "Different sources — no rate" |
| 4 | Campaign rows plus Other traffic add up to the website | ✅ | `test_campaigns_and_other_traffic_always_add_up_to_the_website` (random data, shared matches counted once) |
| 5 | Findings follow Q-7-7; small volumes never flagged | ✅ | `tests/unit/test_funnel_findings.py` (11 cases); `test_a_real_drop_off_is_found_through_the_api` |
| 6 | Funnel totals reconcile with the property page and the Overview | ✅ | `test_the_funnel_reconciles_with_the_overview_and_the_property_page` (visits, orders, GA purchases, Meta impressions and clicks) |
| 7 | All suites pass, no network calls in CI | ✅ | §5 |

---

## 4. Security controls — how each is verified

| Control | Verified by |
|---|---|
| Still read-only at Google and Meta; same report methods, same insights request | Phase 4/5 gate tests unchanged and passing |
| No personal data in landing pages: paths only, anything after `?` or `#` dropped | `test_landing_pages_are_kept_as_paths` |
| The funnel code only reads, calls nothing outside, nothing platform-specific | `test_the_funnel_only_reads` (static) |
| New routes respect tenant isolation; a foreign store is "not found" | Tenant sweep; `test_every_member_can_read_and_outsiders_cannot` |
| No page computes a figure | Static check now covers `features/funnel` |

---

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, pytest) | **1,627 passed**, coverage 97 % |
| Frontend `npm run check` | **411 passed**, coverage 96 % |
| Browser tests (Playwright + axe) | **15 passed**; the four-platform test opens the Funnel (whole, by platform, by landing page) with accessibility checks |

Golden datasets: the funnel of 7-04 (worked out by hand), and the **drop-off dataset** — 120 days of a steady funnel, then a week in which adds to cart fall from 25 % to 15 % of product views: found through the API with its numbers; the week before has no finding. Property checks: stage totals equal the sum of their days; campaigns plus other traffic equal the website (seeded random data).

---

## 6. Database

Migration **0017** (additive, reversible): three nullable counts and the `landing_page` view on `analytics_daily`; four nullable funnel actions on `ad_performance_daily`; `funnel_reread_at` on `analytics_properties` and `ad_accounts`; sync mode `reread`. No new tables; `funnel_daily` is marked superseded (computed on read).

---

## 7. Defects found during Phase 7 (all fixed)

1. A loop variable reused for two types in the funnel engine (mypy).
2. The first static read-only rule was too broad (it caught `set.update`) — it now checks database write imports precisely.
3. Random test data produced duplicate Google Analytics rows, which Google never sends — the generator now keeps one row per source, medium, campaign and day.

---

## 8. Deviations from the plan

1. "No events reported" is decided over the whole period (visits, but zero product views, adds to cart or checkouts).
2. The "own 90-day average" is the 90 days **before** the period (so the period is never compared with itself), including the previous period.
3. The campaign table shows the three stages every platform reports and three Google Analytics stages; Meta's full funnel is in "By ad platform".

---

## 9. Not verified in this environment

- **Step 0 (7-01):** the GA4 metric and dimension names (`itemViewEvents`, `addToCarts`, `checkouts`, `landingPage`) and Meta's action types (`landing_page_view`, `omni_view_content`, `omni_add_to_cart`, `omni_initiated_checkout`) against live accounts, and a week of AdVegaX's funnel against the platforms' own screens. Built from the documentation; Meta's reference page was not readable from here, and third-party connector documentation lists the same names.
- The pending Step 0 checks of Phases 2A–6.

---

## 10. Known limitations and remaining risks

| Limitation / risk | Mitigation |
|---|---|
| A store's Google Analytics does not send ecommerce events | "No events reported" with how to fix it; never 0 |
| Merchants compare ad clicks with visits | "Different sources — no rate", with the reason |
| No per-product funnel yet (Q-7-6) | Needs Google Analytics' item reports and a reliable item-to-product match; planned later |
| Drop-off rules can flag normal seasonality | Two conditions, minimum volume, adjustable settings |
| Live field names may differ | Step 0; unknown values stay unknown, never guessed |

---

## 11. Rollback

Phase 7 adds read-only views and nullable columns. Migration 0017 is additive and reversible. Removing the Funnel page leaves Phase 6 unchanged; the extra imported figures are simply unused.

---

## 12. Next

1. **Your review** of Phase 7 (this report and `PHASE_07_PROGRESS.md`).
2. **Step 0** checks (Phases 2A–7) when access allows.
3. Then **Phase 8 — AI campaign planner** (plan to be written and approved first; it needs your choice of AI provider and scope, Q12).
