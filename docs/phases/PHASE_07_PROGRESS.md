# Phase 7 — Progress (funnel intelligence)

Plan: `PHASE_07_PLAN.md` (approved 2026-10-22, A25, all recommendations Q-7-1 … Q-7-9). One task at a time, a report after each.

| Task | Status |
|---|---|
| 7-01 Step 0: live GA4 and Meta checks | ⏸ Waiting for access to Google Analytics, Meta and the network |
| 7-02 Migration 0017; GA4 import: new metrics, landing-page view, one-time re-read | ✅ Done — awaiting review |
| 7-03 Meta import: four action types, one-time re-read | ✅ Done — awaiting review |
| 7-04 Funnel registry `funnel-v1` and engine | Not started |
| 7-05 Drop-off findings | Not started |
| 7-06 Funnel API | Not started |
| 7-07 Web app: Funnel page | Not started |
| 7-08 Golden datasets, browser test, `PHASE_07_REPORT.md` | Not started |

## 7-01 — Step 0 (2026-10-22)

**Blocked:** this environment cannot reach Google or Meta, and the Phase 4/5 Step 0 access (a GA4 property with ecommerce events, a Meta ad account with a pixel) is not available yet. Phase 7 is built against the simulators, extended with the documented field names; Step 0 checks them live (plan §4.2) when access allows.

## 7-02 — Migration 0017; GA4 funnel figures, landing pages, one-time re-read (2026-10-22)

**Completed**
- **Migration 0017** (additive): product views, adds to cart and checkouts on every Google Analytics day; a fourth view **by landing page**; Meta's four funnel actions on the ad figures (read in 7-03); a "read with the funnel figures" date on each property and ad account; the `reread` sync mode.
- **The GA4 import** now asks for `itemViewEvents`, `addToCarts` and `checkouts` in every view (ten metrics, Google's limit per report) and reads a fourth view, `date` + `landingPage`, in the same single call per slice:
  - landing pages are kept as **paths only** — anything after `?` or `#` is dropped, so no personal data in web addresses is stored;
  - each day keeps the 500 largest landing pages plus one "(other)" row, like the source view;
  - a day without activity has real zeros for the new figures too; anything Google does not give stays unknown, never 0.
- **One-time re-read:** a property imported before Phase 7 is read once more over its 13 months, month by month and paced like the first import, **only when no regular run is due**; its figures stay readable meanwhile, and the new figures say "not synced yet" until their day is re-read. A new property's first import already includes everything.
- The property page keeps its three views; asking it for the landing-page view is refused.

**Files changed** (16)
- New (3): `alembic/versions/0017_funnel.py`, `tests/api/test_google_analytics_funnel_import.py` (8 tests), this report.
- Modified (13): `app/providers/base/types.py`, `app/providers/google_analytics/mapping.py`, `app/domains/analytics/{models,importer,read_service}.py`, `app/domains/advertising/models.py` (columns for 7-03), `tests/ga4_sim.py` (new metrics, landing pages, the 10-metric limit), `tests/api/test_google_analytics_import.py`, `tests/providers/test_google_analytics_reports.py`; docs `DATABASE_SCHEMA.md` (§13B; `funnel_daily` superseded), `INTEGRATION_GUIDES.md`, `PHASE_07_PLAN.md` (approved), `PROJECT_STATUS.md`.
- Deleted: none.

**Tests**
- **8 new**; 4 GA4 tests updated for the fourth view.
- **Backend `make check`: 1,588 passed**, coverage 97 %. Migration up/down tested.

**Security:** still read-only at Google (the same two report methods); no query strings stored; tenant isolation unchanged (no new tables).

**Deviations:** none.

**Blocked:** Step 0 (7-01) — live GA4 and Meta checks.

**Next task:** 7-03 — Meta import: landing page views, content views, adds to cart and checkouts initiated (`landing_page_view`, `omni_view_content`, `omni_add_to_cart`, `omni_initiated_checkout`), and the one-time re-read of Meta accounts.

## 7-03 — Meta funnel actions, one-time re-read (2026-10-22)

**Completed**
- **The Meta import** now also keeps, for every account, campaign, ad set and ad and every day, Meta's own **landing page views, content views, adds to cart and checkouts initiated** — taken from the same `actions` list Phase 4 already reads (`landing_page_view`, `omni_view_content`, `omni_add_to_cart`, `omni_initiated_checkout`), so no extra request is made.
  - No action listed means Meta recorded none: a real 0. An unreadable value leaves **only that figure** unknown; the row's spend, clicks and purchases are kept.
  - A day without activity gets zeros for these actions too — for Meta only.
- **One-time re-read:** a Meta account imported before Phase 7 is read once more over its 13 months (figures only, month by month), when no regular run is due and Meta's shared allowance is not mostly used — exactly like the nightly and weekly re-reads.
- **Google Ads** has no such actions: they stay "not provided by Google Ads" (never 0), and Google accounts are never re-read for them (they are simply marked as done).

**Files changed** (10)
- New (1): `tests/api/test_meta_ads_funnel_import.py` (4 tests).
- Modified (9): `app/providers/base/types.py`, `app/providers/meta_ads/{mapping,provider}.py`, `app/domains/advertising/importer.py`, `tests/meta_sim.py` (funnel actions in the sample figures); docs `INTEGRATION_GUIDES.md`, this report, `PROJECT_STATUS.md`.
- Deleted: none. No migration (the columns came with 0017 in 7-02).

**Tests**
- **4 new**; all Meta and Google Ads tests unchanged and passing.
- **Backend `make check`: 1,592 passed**, coverage 97 %.

**Security:** still read-only at Meta — the same insights request with the same fields; no new permission.

**Deviations:** none.

**Blocked:** Step 0 (7-01) — live GA4 and Meta checks.

**Next task:** 7-04 — the funnel registry `funnel-v1` and engine: each stage with its source, the steps and which have a rate (Q-7-1, Q-7-2), for the whole business, per platform and per channel, with availability on every figure.
