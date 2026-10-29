# Phase 17 — UI/UX redesign and completion: audit and plan

**Status:** Audit done (2026-10-29) · plan **awaiting product-owner approval** · no redesign code written yet.
**Scope source:** the "Master prompt: complete web application design, development and optimisation".
**Rules that apply:** `PROJECT_RULES.md` (no changes to approved behaviour, security or business rules without approval; every change tested; stop on conflicts).

## 1. How the audit was done

- Ran the real stack locally (PostgreSQL 16, Redis, API, web build) with the Phase 16 demo data.
- Signed in as `demo@advegax.local`, opened **21 routes** at **360 × 780**, **820 × 1180** and **1440 × 900**, took screenshots and measured horizontal overflow, small touch targets, headings, page titles and console errors.
- Read the frontend structure, design tokens and shared components.
- **Not yet measured:** Core Web Vitals (Lighthouse), automated accessibility scan of every route (the repository's Playwright + axe suite exists; not re-run), keyboard walk-through, the remaining detail pages (campaign, store/products, strategy detail, creative set, builder, connect flow), and the signed-out and error screens beyond sign-in/sign-up/404.

## 2. What exists

| Area | Finding |
|---|---|
| Stack | Next.js 16 (App Router), React 19, TanStack Query, openapi-fetch, **CSS Modules**, no UI library, no icon library, no chart library, system font stack |
| Size | 285 frontend files; 41 `page.tsx` routes; 18 feature folders; 7 shared UI components (`Alert`, `Button`, `ConfirmDialog`, `PageCard`, `PageHeading`, `SelectField`, `TextField`); about 1,460 lines of CSS in total |
| Tokens | `app/globals.css`: 12 colours with light and dark schemes, 5 font sizes, 7 spacing steps, 2 radii, one container width. **No** elevation, status background colours, table, tab, badge, breadcrumb, skeleton, toast or icon definitions |
| Existing quality | Skip link, visible focus ring, reduced-motion handling, dark scheme, AA colour contrast, titles per page ("Reports · AdVegaX"), tests: 591 frontend unit tests, 21 browser tests (as reported in `PHASE_16_REPORT.md`) |
| SEO | Root metadata only. No `robots`, sitemap, Open Graph or canonical set-up found |

## 3. Problems found (with evidence)

**P1 — high**
1. **The public home page tells a visitor nothing.** Signed out, `/` is the product name, one sentence and a sign-in box. No explanation of what AdVegaX does, no screenshots, no pricing, help or legal links. Signed in, `/` is an organization list.
2. **Mobile navigation is a wall of links.** At 360 px the 13-item organization menu stacks above every page and pushes the content below the fold (about 340 px of menu before the page title).
3. **Horizontal overflow on Settings at 360 px** (172 px wider than the screen) for every organization, and 2 px on Members at 820 px.
4. **The Overview dashboard repeats one card pattern for every figure**, each with its own "How is this calculated?" disclosure. Where data is incomplete, the headline slot shows a sentence ("Some products have no cost") instead of a value, which makes cards uneven. There are no charts or trends anywhere in the interface, although the product is about performance over time.
5. **Per-org pages share one visual structure** (heading plus cards or lists), so a table-heavy page (members, changes, reports) looks the same as a form page (settings).

**P2 — medium**
6. Small touch targets (< 24 px) on most pages (1–9 per page), typically text links in the header and inline actions.
7. No design-system pieces for status (only an ad-hoc "Up to date" badge), tables, tabs, breadcrumbs, empty states, skeletons or toasts. Pages build their own CSS (about 1,270 lines spread over 10+ module files).
8. Header shows "Admin" as an ordinary text link to every administrator; the user's name is a link without clear affordance.
9. The 404 page's title is just "AdVegaX" (other pages use "<Page> · AdVegaX").
10. Page titles for the organization root are "Organization · AdVegaX" rather than the organization name.

**P3 — low**
11. System font only; fine for performance, but typography has little hierarchy beyond size.
12. Dark scheme exists but has not been reviewed visually for every page.

**Not found as problems:** console errors on normal pages (the only error in the crawl is the expected 404 response); broken routes (all 21 routes loaded); missing page titles on the routes checked.

## 4. Proposed approach (kept inside the approved architecture)

The backend, API contracts, permissions and business rules stay as they are. This phase is a **frontend** phase, plus two small backend items listed in §6.

**17A — Design system (no visual change to pages yet)**
- Extend tokens: type scale with weights, 4 px spacing scale, radii, elevation, status colours (success, warning, danger, info, neutral) with AA-checked light and dark values, z-index and motion tokens.
- Choose one icon set (inline SVG, no emoji) and add: `Badge`, `Table` (sortable, responsive), `Tabs`, `Breadcrumbs`, `EmptyState`, `Skeleton`, `Toast`, `Dialog` (existing `ConfirmDialog` kept), `Card` variants, `StatTile`, `PageHeader` with actions.
- Add a small chart component (inline SVG sparkline and bar chart, no library) for trends the API already returns.
- Document it in `docs/DESIGN_SYSTEM.md`.

**17B — Application shell**
- Mobile: collapsible navigation drawer with the organization switcher; desktop: grouped sidebar (Performance, Marketing, Operations, Settings) instead of a flat list of 13 links.
- Fix overflow on Settings and Members; raise touch targets to at least 44 px on touch screens.
- Account menu in the header (profile, security, admin for administrators, sign out).

**17C — Public pages**
- Real home page for signed-out visitors using only true statements about the product from `MASTER_SPECIFICATION.md`, with a real screenshot taken from the demo organization, a "how it works" sequence from the actual workflow (connect, review, approve, audited change), and links to sign in, sign up and legal pages. **No** invented customers, logos, testimonials, statistics or prices. Pricing appears only if Phase 13's plans are approved for public display.
- SEO for public pages only: titles, descriptions, canonical, Open Graph, `robots.txt`, sitemap; private areas set to `noindex`.

**17D — Page-by-page**
In priority order: Overview, Reports, Recommendations, Changes, Advertising and detail pages, Analytics, Funnel, Strategies and builder, Creatives, Stores and products, Billing, Members and Settings, Connections, Clients (agency), Admin, account security, sign-in/up and reset flows, error pages. Each gets the layout that suits its task (dashboard, list with filters, detail, form, settings, report) plus loading, empty, error and permission-denied states.

**17E — Verification**
- Re-run the 21-route crawl at 320, 360, 390, 768, 1024, 1280, 1440 and 1600 px; zero horizontal overflow; screenshots compared before and after.
- Playwright + axe on every route; manual keyboard and screen-reader spot checks (reported as spot checks, not full audits).
- Lighthouse on staging-like production build: LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 reported as measured numbers.
- Existing 591 + 21 tests must keep passing; new component tests added.

## 5. Out of scope for this phase unless you add it

- Real-device touch testing (needs a physical phone; I can only emulate touch).
- Changing financial definitions, permissions, billing rules or AI behaviour.
- New product features (for example new report types) that need backend work.
- Replacing Next.js, React or the CSS Modules approach.

## 6. Backend items found while auditing (small, separate)

1. `scripts/windows/start.ps1` reports success even when the API never became ready, which misled the first desktop run. Proposed: fail with the log path if the API is not ready after 120 seconds. (Redis-via-WSL fallback and the `start-standalone.mjs` Windows fix were already added on this branch.)
2. The desktop installer assumes the PostgreSQL superuser password is `postgres` and that Memurai installs from winget; on your PC neither held. Proposed: detect and report both clearly in `setup.ps1`.

## 7. Risks

| Risk | Mitigation |
|---|---|
| A broad restyle breaks working flows | Change by route in small commits; the existing test suites run after each stage |
| "Distinctive" design drifts from the approved architecture and rules | No new dependencies without approval; tokens and components only; plan-first for each stage |
| Measured performance gains are small because the app is already light | Report real numbers before and after; don't claim improvement that wasn't measured |
| Screenshots with demo data show modest figures | Say so on the page and in the report; no fabricated data |

## 8. Decisions requested with approval

| # | Item | Proposed default |
|---|---|---|
| 1 | Scope | 17A → 17E as above, one stage at a time, each stage reported before the next |
| 2 | Public home page content | Only product facts from the specification; real demo screenshot; no pricing until Phase 13 plans are public |
| 3 | Icons and charts | Inline SVG, no new dependencies |
| 4 | Brand | Keep the name and blue accent; the logo mark and any new brand colours are your decision (default: wordmark only) |
| 5 | Navigation | Grouped sidebar plus mobile drawer |
| 6 | Desktop script fixes (§6) | Include in Phase 17A |
