# Phase 19 — A dashboard Overview, a home page with motion, one look across the app

The scope was approved on 2026-11-19:

- an Overview dashboard with a trend chart, "Where the money went", "Campaigns that spent most" and a funnel snapshot;
- a "Data flowing in" motion on the home page;
- the whole customer app brought into the same design;
- checks on phone, tablet and desktop.

## What changed

| Area | Change | Where |
| --- | --- | --- |
| Overview | A dashboard between the key figures and "Waiting for you". **Sales, ad spend and profit by day** is an SVG chart with a day readout, which works by pointer or keyboard. Missing days are gaps, never zeros. **Where the money went** shows spend by platform and visits by channel. **From first view to purchase** shows the funnel stages, the API's step rates and "Below usual" findings. **Campaigns that spent most** shows the top 5 by spend, linked. | `features/overview/Dashboard.tsx`, `dashboard.module.css`, `OverviewFigures.tsx` |
| Home page | **Data flowing in**: the four sources draw lines into one "Profit after ad spend" panel. It runs once (about 2 s), is static for reduced motion and shows no numbers. On phones it becomes a 2 × 2 grid with no lines. The real Overview screenshot moved to a new section, "The whole picture, every morning". | `features/home/HeroFlow.tsx`, `hero-flow.module.css`, `Landing.tsx` |
| Whole app | Panels now match the dashboard: a 3 px top rule and roomier padding. Table headings are small and muted, rows highlight on hover, and section headings use one size. Advertising account cards sit side by side on wide screens. Small list cards get a hover border. Page titles are tighter. Done centrally, so every page changes together. | `advertising.module.css` (used by 25 features), `organizations.module.css`, `stores`, `connections`, `account` modules, `ui.module.css` |
| Demo data | `reset-demo` now loads **60 days** of simulated orders (with product costs), Google Ads and Google Analytics, from a fixed seed, so the charts have something to show. The test helpers keep their small exact samples unless `ADVEGAX_DEMO_DAYS` is set. | `backend/demo/rich.py`, `demo/seed.py`, `tests/e2e_*.py` |
| Security upgrade | **Next.js 15 → 16.4.6** (and `eslint-config-next`). The build flagged two moderate advisories, GHSA-mfr8-8qww-v76h and GHSA-vc7v-qv4w-wrv8. `npm audit` now reports 0. | `frontend/package.json`, lockfile |

## Rules kept

- The browser still works out no figures. Every number shown comes from the API. Bar lengths and axis ticks are drawing only. The static test (no `.reduce(`, no arithmetic on `.value`) passes.
- No inline styles (CSP). Bars are SVG `rect`s.
- Colours and sizes come from tokens only (token test passes).
- No made-up numbers on the public page.

## Checks

| Check | Result |
| --- | --- |
| Web: lint, types, format, unit tests with coverage | 655 tests pass. Branches 85.8% (minimum 85%). |
| New tests | `tests/features/dashboard.test.tsx` covers: chart readout by keyboard and pointer, gaps, no "-A$0", money breakdown order, funnel finding, top campaigns, empty states, and that the hero shows no numbers. |
| Backend: ruff, format, mypy (as CI runs it) | Pass |
| Browser end-to-end + axe | See the summary below |
| Screens checked | 390, 768, 1024 and 1440 px: Overview, Reports, Advertising, Recommendations, Changes, Connections, Billing, Settings and the home page. No sideways page scroll. Wide tables scroll inside their own box. |

Fixed during the screen checks:

- The y-axis read "-A$0".
- The campaigns table was cut off at tablet width; it now becomes cards under 64rem.

## Follow-ups

- The key figures' "Up x% on the previous 30 days" (Phase 17) works out a ratio in the browser. That goes against "the API calculates". The API should return the change.
- "Connections" shows the title and "Your connections" one after the other. A copy tidy-up is needed.

## For the owner

1. Run `setup.ps1` again: Next.js was upgraded.
2. Run `reset-demo` to load the 60-day demo data.
3. Push to GitHub from the desktop folder.
