# Phase 7 — Progress (funnel intelligence)

Plan: `PHASE_07_PLAN.md` (approved 2026-10-22, A25, all recommendations Q-7-1 … Q-7-9). One task at a time, a report after each.

| Task | Status |
|---|---|
| 7-01 Step 0: live GA4 and Meta checks | ⏸ Waiting for access to Google Analytics, Meta and the network |
| 7-02 Migration 0017; GA4 import: new metrics, landing-page view, one-time re-read | ✅ Done — awaiting review |
| 7-03 Meta import: four action types, one-time re-read | ✅ Done — awaiting review |
| 7-04 Funnel registry `funnel-v1` and engine | ✅ Done — awaiting review |
| 7-05 Drop-off findings | ✅ Done — awaiting review |
| 7-06 Funnel API | ✅ Done — awaiting review |
| 7-07 Web app: Funnel page | ✅ Done — awaiting review |
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

## 7-04 — The funnel registry `funnel-v1` and engine (2026-10-22)

**Completed**
- **`app/domains/funnel/registry.py`** — the one place the funnel is defined:
  - the seven stages of the whole business with **their source** (Q-7-1): impressions and clicks from Google Ads and Meta; landing page views (sessions), product views, adds to cart and checkouts from Google Analytics; purchases = **store orders**, with Google Analytics' purchases beside them (never added to them);
  - the steps and their kind (Q-7-2): **same source** (with a rate), **different sources** (ad clicks → website visits: no rate) and the one approved cross-source ratio, the **store conversion rate** (orders ÷ sessions);
  - each ad platform's own funnel: Meta reports every stage (impressions → link clicks → landing page views → content views → adds to cart → checkouts → purchases); Google Ads only impressions → clicks → conversions — the rest is "not provided by the platform";
  - each Google Analytics channel's funnel (sessions → product views → adds to cart → checkouts → purchases).
- **`app/domains/funnel/engine.py`** — reads the stored daily figures of every source in scope (the Phase 6 scope: whole organization or one store) and applies the registry to any period or day. Store orders come from the Phase 6 inputs, so the funnel's purchases are exactly the Overview's orders. Computed on read (Q-7-8); events, not people (Q-7-5).
- **Never 0 for missing data:** a day not read — or not yet re-read with the funnel figures — is "not synced yet"; nothing connected of a kind says so; a property that reports visits but **no ecommerce events at all** says "no events reported" (its Google Analytics set-up does not send them) instead of 0; a step whose earlier stage is 0 names it ("no impressions").
- A new static check: the funnel code never writes, never calls out and uses nothing platform-specific (D19).

**Golden funnel** (by hand, in the test file): impressions 4,800 → clicks 140 (CTR 2.9 %) → *different sources* → landing page views 500 → product views 200 (40 %) → adds to cart 50 (25 %) → checkouts 20 (40 %) → Google Analytics purchases 10 (50 %); store orders 15, store conversion 3 %. Per platform: Google Ads 1,800 → 80 → 3; Meta 3,000 → 60 → 45 → 30 → 12 → 6 → 4.

**Files changed** (6)
- New (4): `app/domains/funnel/{__init__,registry,engine}.py`, `tests/api/test_funnel_engine.py` (10 tests).
- Modified (2): `tests/security/test_static_rules.py` (1 rule); this report (and `PROJECT_STATUS.md`).
- Deleted: none. No migration.

**Tests**
- **11 new**.
- **Backend `make check`: 1,603 passed**, coverage 96 % (the run also counted the not-yet-tested draft of 7-05's findings file).

**Security:** reads only; tenant scope from Phase 6 (row-level security plus explicit organization filters).

**Deviations:** "no events reported" (plan §2A, item 3) is decided over the whole period: visits reported but zero product views, adds to cart or checkouts.

**Blocked:** Step 0 (7-01) — live GA4 and Meta checks.

**Next task:** 7-05 — drop-off findings (Q-7-7): a same-source step at least 25 % below the previous equal period **and** below its own 90-day average, with at least 200 events before it, written in plain words.

## 7-05 — Drop-off findings (2026-10-22)

**Completed**
- **`app/domains/funnel/findings.py`** — fixed rules, no AI, a business compared **with itself** (Q-7-7). A step is flagged only when:
  1. both its stages come from the same source (ad clicks → website visits is never judged);
  2. its earlier stage had **at least 200 events** in the period (small numbers never alarm);
  3. its rate is **at least 25 % lower** than in the previous period of equal length; **and**
  4. its rate is **below its own average over the 90 days before the period**.
- Every rate involved must be available: a missing day, a stage not provided, a zero divisor or a business with less history than needed is **never** flagged.
- Applied to the whole business, **each ad platform's own funnel** and **each Google Analytics channel**; findings are listed largest fall first.
- Each finding carries its numbers — the step, its rate now, in the previous period and on average, the events before it and the change — so the web app can say it in plain words ("Adds to cart fell from 25 % to 15 % of product views, compared with the previous 7 days") and Phase 8/11 can read it later.
- The three numbers are settings: `FUNNEL_DROP_SHARE` (0.25), `FUNNEL_MIN_EVENTS` (200), `FUNNEL_BASELINE_DAYS` (90).

**Files changed** (5)
- New (2): `app/domains/funnel/findings.py`, `tests/unit/test_funnel_findings.py` (11 tests).
- Modified (3): `app/core/settings.py`; this report, `PROJECT_STATUS.md`.
- Deleted: none. No migration.

**Tests**
- **11 new**: a clear drop with its numbers, a steady funnel, a small drop, small numbers, a fall that stays above the usual level, a platform's own drop, missing days, too little history, ordering, settings.
- **Backend `make check`: 1,614 passed**, coverage 97 %.

**Security:** computation only; the funnel's read-only static check covers this file.

**Deviations:** the "own 90-day average" is the 90 days **before** the period (so the period is never compared with itself), and it includes the previous period.

**Blocked:** Step 0 (7-01) — live GA4 and Meta checks.

**Next task:** 7-06 — the funnel API: `GET /analytics/funnel` (whole business, per platform, per channel, with findings), `/analytics/funnel/campaigns` (with "Other traffic") and `/analytics/funnel/landing-pages`.

## 7-06 — Funnel API (2026-10-22)

**Completed**
- **`GET /analytics/funnel`** — for a period (30 days by default, in your reporting time zone), the whole organization or one store:
  - the **seven stages with their source** and Google Analytics' purchases beside the store orders; the **steps** with their rate, or "different sources — no rate", or the store conversion rate;
  - **each ad platform's own funnel** (Meta: every stage; Google Ads: impressions → clicks → conversions, the rest "not provided"), labelled "platform reported";
  - **each Google Analytics channel's funnel**, most visits first;
  - the **drop-off findings** of 7-05, with the rules used and the previous period's dates;
  - as every analytics answer: definitions version `funnel-v1`, sources with freshness, currencies, notes, and the stages' definitions for "How is this calculated?".
- **`GET /analytics/funnel/campaigns`** — each campaign's own funnel as its platform reports it, and Google Analytics' funnel for the campaign of **exactly the same name**; visits that match no campaign are **"Other traffic"**, and the answer includes the **website** total, so campaigns plus other traffic always add up (two campaigns of the same name share their match, counted once, and say so).
- **`GET /analytics/funnel/landing-pages`** — Google Analytics' funnel for each landing page (paths only), most visits first, at most 100; "not synced yet" until the property's one-time re-read is done.
- Every member can read; another organization's data or store is "not found"; invalid periods are refused.

**Files changed** (13)
- New (6): `app/domains/funnel/{breakdowns,schemas,read_service,router}.py`, `tests/api/test_funnel_api.py` (9 tests), docs `API_SPECIFICATION.md` §19G.
- Modified (7): `app/domains/funnel/{engine,findings}.py` (two helpers made public), `app/api/router.py`, `tests/security/test_static_rules.py` (the read-only rule now checks database write imports precisely), `frontend/lib/api/{openapi.json,schema.d.ts}` (generated); this report and `PROJECT_STATUS.md`.
- Deleted: none. No migration.

**Tests**
- **9 new**; the tenant-isolation sweep covers the three new routes.
- **Backend `make check`: 1,622 passed**, coverage 97 %. **Frontend `npm run check`: 404 passed** (types regenerated).

**Security:** reads only; membership on the server; row-level security plus explicit organization filters; a foreign `store_id` is a 404.

**Deviations:** none.

**Blocked:** Step 0 (7-01) — live GA4 and Meta checks.

**Next task:** 7-07 — web app: the Funnel page (stages as bars with their source, steps with rates or "different sources", findings in plain words, views per platform, channel, campaign and landing page, "How is this calculated?").

## 7-07 — Web app: the Funnel page (2026-10-22)

**Completed**
- **A Funnel page** (in the menu after Reports), with the same period and store choice as the Overview and Reports, and a "Show" choice:
  - **Whole business:** the seven stages as **bars with their counts and where each number comes from** ("Google Ads and Meta", "Google Analytics", "Your stores"), "How is this calculated?" on every stage, and the **steps** with their rate — or "Different sources — no rate. Ad clicks and website visits are counted differently." — and the store conversion rate by its own name;
  - **By ad platform:** each platform's own funnel, "Reported by Google Ads / Meta" with its number of ad accounts; stages a platform does not report say "Not provided by the platform";
  - **By Google Analytics channel:** a table of each channel's stages and step rates;
  - **By campaign:** each campaign's own impressions, clicks and purchases and Google Analytics' visits, adds to cart and purchases for the campaign of the same name ("No matching Google Analytics campaign" otherwise), each row naming its platform, ad account and status (and when it shares its match), then **Other traffic** and the **Website** row that they add up to;
  - **By landing page:** each page's funnel, most visits first ("Not synced yet" until the property's one-time re-read is done).
- **"Where buyers drop out"** at the top: the findings in plain words — e.g. "Adds to cart fell from 25.0% to 15.0% of product views, compared with 15 Sep to 14 Oct. It is also below its usual 24.0%." — or, when nothing dropped, the rules that were applied.
- The bars are drawn by the browser against the largest stage (`<meter>`); the page itself calculates nothing — the static check now covers the funnel pages too.
- "Where the numbers come from" (sources, currencies, notes, definitions version) on every view.

**Files changed** (13)
- New (7): `frontend/features/funnel/{api.ts,labels.ts,FunnelPage.tsx,funnel.module.css}`, `frontend/app/orgs/[organizationId]/funnel/page.tsx`, `frontend/tests/features/funnel.test.tsx` (7 tests), this report section.
- Modified (6): `features/organizations/OrganizationShell.tsx` (menu), `lib/format/money.ts` (funnel reasons), `tests/static/source-rules.test.ts`, `e2e/unified-analytics.spec.ts` (the Funnel page with accessibility checks); `PROJECT_STATUS.md`.
- Deleted: none. No backend change, no migration.

**Tests**
- **Frontend `npm run check`: 411 passed** (7 new), coverage 96 %.
- **Browser tests: 15 passed**; the four-platform test now opens the Funnel (whole, by platform, by landing page) with accessibility checks.
- Backend unchanged since 7-06 (1,622 passed).

**Security:** the page reads only through the API; no data kept in the browser.

**Deviations:** the campaign table shows the three stages every platform reports (impressions, clicks, purchases) and three Google Analytics stages, to stay readable; Meta's full per-platform funnel is in "By ad platform".

**Blocked:** Step 0 (7-01) — live GA4 and Meta checks.

**Next task:** 7-08 — golden datasets (a real drop-off over several weeks through the API), property checks (campaigns + other traffic = website; stage totals = sum of days), reconciliation with the Phase 5 property page and the Phase 6 Overview, and `PHASE_07_REPORT.md`.
