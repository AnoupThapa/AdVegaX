# Phase 21 — Maximalism in the brand's colours

**Requested 2026-11-22:** "Design all pages and sections into maximalism design", covering the home page, admin, customer and company pages.

**Approved choices:**

- **Direction:** "Market stall".
- **Depth:** "Full shell, calm data".
- **Motion:** "Lively but purposeful".

While I was syncing, I found that the Phase 20 brand (logo, navy and gold, Cormorant Garamond and Montserrat) had already been made in another session. The owner then chose **"Maximalism in brand colours"**: keep the logo, palette and fonts, and make them maximal. The first market-stall build, with its own palette and Sora, was never merged. It is kept only on the local branch `stall-maximal`.

## What changed

| Area | Change | Where |
| --- | --- | --- |
| Tokens (added; brand tokens unchanged) | **Outlines and shadows:** navy outlines (ivory in dark mode) and hard offset shadows.<br>**Fills:** bright gold, the brand terracotta, and pale sky, blush and sage tints; text on them is navy (`--color-on-pop`), or ivory on terracotta.<br>**Patterns:** navy-and-gold awning, ledger dots, Admin hazard stripe.<br>**Type:** weight 800 and size 4xl tokens.<br>**Contrast:** lowest measured pair is 6.1:1. | `app/globals.css` |
| Shared parts | **Buttons:** keep the brand's square corners, outlined, lift on hover and press in on click.<br>**Inputs, cards, dialogs, toasts, empty states and table frames:** outlined with a hard shadow.<br>**Badges:** outlined tags.<br>**Page titles:** larger. | `components/ui/*`, `data-table`, `toast` |
| Header and menu | **Header:** navy-and-gold awning edge on top, heavy rule below.<br>**Menu:** the navy sidebar sits on a gold shadow; group tabs are tinted (sky, blush, sage, gold); the current page is a gold tag.<br>**Switcher and account menu:** match. | `SiteHeader`, `OrganizationNav`, `OrganizationSwitcher`, `AccountMenu` |
| Home page | **Hero:** dot texture, bigger headline, awning edge.<br>**Hero flow:** tinted source tickets; the panel sits tilted on a gold shadow.<br>**New gold ticker strip:** what AdVegaX reads and promises; no figures.<br>**Sections:** "How it works" is four tinted boards with the brand's Roman numerals; controls are outlined boards with stamped icons; platforms are tilted tags.<br>**Closing:** the navy closing block gets an awning edge.<br>**Screenshots:** retaken. | `Landing.tsx`, `landing.module.css`, `hero-flow.module.css`, `public/product/*.webp` |
| Customer pages | **Overview:** the key figures are four tinted tags; figures in the summary sentence are marked in gold.<br>**Boards and lists:** dashboard boards, panels, list cards and tiles are outlined.<br>**Section titles:** get a gold bar.<br>**Tables:** always on white. | `overview`, `dashboard`, `advertising`, `organizations`, `stores`, `connections`, `account` modules |
| Admin portal | **Band:** navy, with a gold-and-navy "staff only" hazard edge.<br>**Sections:** titles are gold tabs; counts are outlined boards.<br>**Switches:** chunky, sage when on. | `admin.module.css` |
| Company and agency pages | **Shared styles:** they use the organization and advertising styles above.<br>**Organization list** (signed-in home): tickets that turn gold on hover. | same |

## Rules kept

- **Packages:** no new ones.
- **Brand:** the brand's logo, palette and fonts are unchanged.
- **Styles:** tokens only (the static test passes), no inline styles (CSP).
- **Text on fills:** always navy or ivory.
- **Colour and meaning:** meaning never depends on colour alone.
- **Reduced motion:** motion is off when asked; the ticker stands still.
- **Figures:** the browser works out no figures.

## Checks

| Check | Result |
| --- | --- |
| Web: lint, types, format, unit tests with coverage, `npm audit` | **Pass.** 657 tests (ticker test added).<br>Branches 85.9%.<br>Audit: 0 vulnerabilities. |
| Browser end-to-end + axe | **21 / 21** |
| Screens | **Widths:** 390 and 1440 px.<br>**Pages:** home, Overview, Reports, Advertising, Recommendations.<br>**Result:** no sideways scroll. |

## Follow-ups

- **Admin portal:** not screenshotted, because it needs the operator's two-step code. axe covers it in the end-to-end suite.
- **Demo data:** it stops on 19 November, so run `reset-demo` for recent days.

## For the owner

1. Rebuild the desktop app: Ctrl+Alt+S, then `setup.ps1`, then Ctrl+Alt+A.
2. Open the home page signed out, and an organization signed in. Then switch Windows to dark mode and look again.
3. Push to GitHub from the desktop folder.
