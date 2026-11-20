# Phase 20 — The AdVegaX brand across the web app

Requested by the product owner on 2026-11-20 (A36): use the new logo, its colours and its fonts, and bring the look of the design canvas ("AdVegaX — Product Design") into the project.

## 1. What changed

| Area | Change | Where |
| --- | --- | --- |
| Palette | The slate-and-cobalt palette is replaced by the logo's: **Vega navy** `#05182d` for text, actions and dark bands; **ivory paper** `#f7f3ea` for the ground; **Growth gold** `#c9944a` for rules, marks and the primary action on navy; **ledger bronze** `#8a5a1c` for links and focus on paper. The dark scheme swaps the roles: navy ground, gold actions. Token names are unchanged, so every page changed at once. Two tokens were added: `--color-gold` (with `--color-on-gold`) and `--color-link`. | `frontend/app/globals.css` |
| Type | **Cormorant Garamond** (headings and large figures, matching the wordmark) and **Montserrat** (everything else, matching the tagline) replace Sora and IBM Plex Sans. Both are SIL OFL and bundled, as before. h1 and h2 are serif bold; h3 and panel titles stay in the sans, because Cormorant is too fine below 24 px. The h1 and h2 sizes went up a step (32→40 px, 24→28 px) because Cormorant sets small for its size. Headings use lining figures. | `globals.css`, `app/layout.tsx`, `package.json`; 7 module stylesheets (`font-family: var(--font-sans)` on small titles) |
| Shape | Near-square corners (2 px; 4 px for large images) and hairline rules instead of soft shadows. Menus and toasts keep a shadow because they float. | `globals.css` |
| Logo | A new `BrandLogo` component shows the mark and wordmark in the header. It switches to the ivory files in dark mode with a `<picture>` source (no script). The wordmark gives the link its name, "AdVegaX". The landing's closing block shows the stacked logo with the tagline. The favicon and home-screen icon are the mark on a navy square. | `components/layout/BrandLogo.tsx` (+ CSS), `SiteHeader.tsx`, `public/brand/*`, `app/icon.png`, `app/apple-icon.png` |
| Sidebar | The organization menu is a navy panel on every screen size. Group labels are spaced capitals. The current page is a raised row with a gold underline, as on the canvas. | `features/organizations/OrganizationNav.module.css`, `organizations.module.css` (sidebar 13 → 15 rem) |
| Landing | The tagline "Advertise smarter. Grow faster." opens the hero after a gold rule. The primary action on navy is gold. "How it works" is numbered I.–IV. in bronze serif under one navy rule. The two product screenshots were retaken from the demo organization in the new look. | `features/home/Landing.tsx`, `landing.module.css`, `public/product/*.webp` |
| Sign-in and other single-card pages | The card has a gold top rule and more room. | `components/ui/ui.module.css` |
| Design system | Colour, type, radius, elevation and navigation sections rewritten. Contrast is measured for both schemes (the lowest text pair is 5.3:1). There is a new §2.6 on brand assets and their rules. | `docs/DESIGN_SYSTEM.md` |

**Deleted:** `frontend/app/icon.svg` (the old blue "A"). It was replaced by `app/icon.png`, and nothing else referenced it.
**Dependencies:** removed `@fontsource-variable/sora` and `@fontsource-variable/ibm-plex-sans`; added `@fontsource-variable/cormorant-garamond` 5.3.0 and `@fontsource-variable/montserrat` 5.3.0 (exact versions, OFL).
**Backend:** unchanged.

## 2. Rules kept

- **Tokens only.** No colour, size or radius literals in page stylesheets; the token test passes.
- **CSP.** No inline styles, and the logo is served from this app.
- **Honest data.** The browser still works out no figures.
- **No made-up numbers on the public page.** The canvas's "ROAS 4.0× vs profit −$200" example was **not** added to the landing page for this reason (see §5).
- **WCAG 2.2 AA in light and dark.** Contrast was measured. Gold is never used for text on paper, because it is only 2.3:1 on ivory.

## 3. Checks

| Check | Result |
| --- | --- |
| Web: lint, Prettier, strict types, unit tests with coverage, `npm audit` (`npm run check`) | Pass. **656 tests** (1 new: `BrandLogo` name, decorative mark, dark-mode sources). Branches 85.9% (minimum 85%). Audit: 0 vulnerabilities. |
| Production build (`npm run build`, standalone server) | Pass |
| Browser end-to-end + axe (no serious or critical violations) | **21 / 21 pass.** Run against a local stack: PostgreSQL 16, Redis, API and worker with the CI settings. Two stand-ins: a small local stand-in for Mailpit, and Chromium 1243 via `PLAYWRIGHT_CHROMIUM_EXECUTABLE`. |
| Screens checked (demo data) | At 1440 px, light and dark: home, sign-in, Overview, Recommendations, Advertising, Funnel, Settings, Billing, Connections. At 390 px: home and Overview. No sideways scroll. The sidebar collapses to a navy menu button on phones. |

## 4. Known limitations

- **The logo is a raster cut.** The files come from the PNG master, at 3× header size. A vector (SVG) master would be sharper at every size.
- **Cormorant Garamond is the closest free match** to the wordmark's serif, not the same font. If the logo's actual font is known and licensed for the web, swapping it is one token (`--font-display`) and one package.
- **Feature-specific stylesheets still use the old shapes in a few places,** for example the 3 px top rule on dashboard panels, now navy. They read as intended, but a finer pass per page could follow the canvas more closely.

## 5. Not in this phase — the canvas's new page layouts

The design canvas also proposes new screens and data views. They need new API data or a product decision, so this phase does not build them. Each would be its own planned task:

| Canvas idea | Needs |
| --- | --- |
| Overview "profit bridge" (revenue → product cost → ad spend → fees → net profit) | The API to return each step; the browser must not subtract |
| Campaign verdicts (Scale / Hold / Fix / Cut) | Rules in the optimization engine, plus a product decision on the wording |
| Products "margin map" (margin × ad spend) | A per-product ad-spend attribution endpoint |
| Recommendation as a "memo", with a checks timeline | The validation steps exposed per recommendation |
| Automation page: guardrail usage meters ("64% of today's cap") | Today's usage from the autopilot API |
| Creative studio feed-ad preview | A preview component for the Phase 9 creative sets |
| Landing "ROAS vs profit" worked example | Your approval to show illustrative numbers, clearly labelled, on the public page |

## 6. Review checklist for the product owner

1. Run `setup.ps1` again (the font packages changed), then `start.ps1`.
2. Open the home page signed out. Check the logo in the header, the gold tagline line, the gold "Create an account" button and the stacked logo at the bottom.
3. Sign in as `demo@advegax.local`. Open Eve Zone and check the navy sidebar: the gold underline should follow the page you are on.
4. Switch Windows to dark mode and reload. You should see a navy page, gold buttons and the ivory logo.
5. Look at the browser tab icon. It should show the mark on a navy square.
6. On your phone or a narrow window, tap the navy menu button above the page title.
7. Decide on §5: which of the canvas's new screens should be planned next, and whether the landing may show a labelled illustrative example.
8. If you approve, merge this branch, as with earlier phases.
