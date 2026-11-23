# AdVegaX — Design system

**Status:** living document · first version 2026-10-30 (Phase 17) · **brand identity 2026-11-20 (Phase 20)** · owner: product owner; changes follow §7.
**Where it lives in code:** tokens in `frontend/app/globals.css`; shared components in `frontend/components/`; rules enforced by `frontend/tests/static/design-tokens.test.ts`.

The aim is one look across the whole product: a small palette, one type scale, one spacing scale, a few layout containers, and a short list of components. Pages are composed from these; they do not invent their own values.

> **Phase 21 (2026-11-23): maximalism in the brand's colours.** This layers on top of the Phase 20 brand (navy, ivory, gold; Cormorant Garamond and Montserrat). Where this note and the sections below disagree, this note wins.
>
> - **Ink and shadows.** Boards, controls, tags, menus and table frames have a navy ink outline (`--border-ink`, `--border-ink-thick`; ivory in dark mode) and a hard offset shadow (`--shadow-pop-sm`, `--shadow-pop`, `--shadow-pop-lg`). On navy bands the shadow is gold. Buttons keep the brand's near-square corners, lift on hover and press into their shadow when clicked. Badges and platform names are outlined tags.
> - **Fills.** Bright gold (`--color-mustard`), the brand terracotta (`--color-tomato`), and three pale brand tints: sky (navy), pink (bronze) and mint (sage). Fills are never text colours. Text on them is `--color-on-pop` (navy, in both schemes), or `--color-on-tomato` on terracotta. Every pair was measured: the lowest is 6.1:1.
> - **Patterns.** `--pattern-awning` (navy and gold stripes) runs along the top of the header, the bottom of the hero and the top of the closing block. `--pattern-dots` sits on the public page, `--pattern-dots-on-slate` on navy bands, and `--pattern-hazard` marks the Admin portal's "staff only" edge.
> - **Type.** The brand fonts stay. Large headings are in Cormorant at bold, with only light tightening (-0.015em). Buttons, tags and small titles are in Montserrat.
> - **Calm data.** Tables, charts and figure lists sit on plain white inside their frames. The app's page background has no pattern.
> - **Colour coding.** Each menu group's tab has a tint: Performance sky, Marketing pink, Data mint, Organization gold. The current page is a gold tag. The Overview's four key figures are sky, pink, mint and gold tags, and their words still say up or down. Figures in the summary sentence are marked in gold.
> - **Motion.** The home page has the hero flow and a gold ticker strip that slides sideways. It stops on hover, and stands still for anyone who asks for less motion. In the app, motion only answers the person: lift on hover, press on click.

---

## 1. Principles

1. **Restricted palette, taken from the logo.** Vega navy, ivory paper, Growth gold (with ledger bronze for text) and four status colours. Nothing else. Colour never carries meaning alone: statuses always have a text label.
2. **Tokens, not values.** Pages and components reference tokens (`var(--space-4)`), never raw numbers or colours. A test enforces this (§9.3).
3. **Consistency from the system, not from identical pages.** A table-heavy page and a form page share tokens and components but not a layout.
4. **Accessible by default.** WCAG 2.2 AA is the floor: contrast, 24 px minimum targets (44 px for primary controls), visible focus, labelled controls, keyboard operation, reduced motion respected.
5. **Honest data.** Missing data is shown as missing (amber, with the reason), never as zero.
6. **Light and dark.** Every colour token has both values; components never pick a colour per theme.
7. **Small.** A new component or variant needs a use in three places (§9.1). Prefer composing what exists.

---

## 2. Foundations

### 2.1 Colour (restricted palette)

The palette comes from the AdVegaX logo (Phase 20).

- **Vega navy** (`color-text`, `color-accent`, `color-slate`) carries text, the primary action, the current navigation item and the always-dark bands.
- **Ivory paper** (`color-bg`, `color-surface`, `color-surface-2`) is the ground.
- **Growth gold** (`color-gold`) is the one brand accent: hairline rules, the current-item mark in the sidebar, the primary action on navy bands and the sign-in card's top rule. It is never used for text on paper, where it fails contrast.
- **Ledger bronze** (`color-link`, `color-focus`) is a gold dark enough for links and focus rings on paper.
- Green and red/terracotta only report results (`color-sage`, `color-terracotta`, the status pairs). No gradients.

The **navy band** (`color-slate`, `color-slate-2`, `color-on-slate*`) is used for the landing hero and closing block, the organization sidebar and the admin band. In the dark scheme the roles swap: navy becomes the ground and gold becomes the action colour. Every text pair below meets 4.5:1 in both schemes (measured with a script, not by eye).

Three tiers: **reference** values live only in `globals.css`; **semantic** tokens (below) are what the rest of the code uses; **component** styles combine semantic tokens.

| Token                   | Light     | Dark      | Role                                       |
| ----------------------- | --------- | --------- | ------------------------------------------ |
| `color-bg`              | `#f7f3ea` | `#04101e` | Page ground (ivory / deep navy)            |
| `color-surface`         | `#fffdf8` | `#0a1b30` | Cards, panels, inputs                      |
| `color-surface-2`       | `#f1ebdf` | `#0f233b` | Tinted rows, table heads                   |
| `color-text`            | `#05182d` | `#f2eee4` | Body text (Vega navy / ivory)              |
| `color-text-muted`      | `#4d5666` | `#b7bfcb` | Secondary text                             |
| `color-border`          | `#e2daca` | `#203655` | Dividers, card edges                       |
| `color-border-strong`   | `#b9b2a3` | `#3a5373` | Stronger dividers                          |
| `color-control-border`  | `#807868` | `#6f84a2` | Input and secondary-button edges (≥ 3:1)   |
| `color-accent`          | `#05182d` | `#d9a85c` | Primary action, current item, chart line   |
| `color-accent-contrast` | `#f7f3ea` | `#05182d` | Label on the primary action                |
| `color-accent-bg`       | `#f3e7d3` | `#2b2416` | Gold tint                                  |
| `color-accent-text`     | `#6e4511` | `#ebc583` | Text on the gold tint                      |
| `color-link`            | `#8a5a1c` | `#e2b05f` | Links (ledger bronze / gold)               |
| `color-focus`           | `#8a5a1c` | `#e2b05f` | Focus ring                                 |
| `color-gold`            | `#c9944a` | `#d9a85c` | Brand rules, marks, primary action on navy |
| `color-on-gold`         | `#05182d` | `#05182d` | Label on gold                              |
| `color-slate`           | `#05182d` | `#020b16` | Navy band, sidebar                         |
| `color-slate-2`         | `#0b2340` | `#071a2f` | Raised surface on the navy band            |
| `color-on-slate`        | `#f7f3ea` | `#f7f3ea` | Text on navy                               |
| `color-on-slate-muted`  | `#c8cfda` | `#c8cfda` | Secondary text on navy                     |
| `color-on-slate-accent` | `#e2b05f` | `#e2b05f` | Gold text and focus on navy                |
| `color-danger`          | `#a3231a` | `#ff8f84` | Errors, destructive actions                |
| `color-success`         | `#22573b` | `#8fcfa6` | Done, connected                            |
| `color-warning`         | `#8a3b12` | `#f0ae84` | Needs attention                            |

Status colours come in foreground/background pairs: `--status-success-*`, `--status-warning-*`, `--status-danger-*`, `--status-info-*`, `--status-neutral-*` (each `-fg` and `-bg`).

| Meaning                      | Use for                                                                 | Never for                                          |
| ---------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------- |
| **Accent** (navy; gold dark) | The one primary action per view, the current navigation item, charts    | Decoration, status                                 |
| **Gold**                     | Hairline rules, the current-item mark, the primary action on navy bands | Text or links on paper (fails contrast)            |
| **Link / focus** (bronze)    | Links and focus rings on paper                                          | Buttons                                            |
| **Success** (green)          | Completed, connected, up to date                                        | "Good" numbers (metrics are not coloured by value) |
| **Warning** (terracotta)     | Needs attention; **a figure that cannot be shown yet**                  | Errors                                             |
| **Danger** (red)             | Errors, destructive actions                                             | Emphasis                                           |
| **Info / neutral**           | Plain information, inactive states                                      | —                                                  |

**Contrast, measured** (WCAG AA needs 4.5:1 for text and 3:1 for control edges; the lowest text pair here is 5.3:1):

| Pair                      | Tokens                                     | Light  | Dark   |
| ------------------------- | ------------------------------------------ | ------ | ------ |
| Body text                 | `color-text` on `color-bg`                 | 16.1:1 | 16.5:1 |
| Body text on cards        | `color-text` on `color-surface`            | 17.6:1 | 15.0:1 |
| Muted text                | `color-text-muted` on `color-bg`           | 6.7:1  | 10.3:1 |
| Muted text on tinted rows | `color-text-muted` on `color-surface-2`    | 6.2:1  | 8.6:1  |
| Link                      | `color-link` on `color-bg`                 | 5.3:1  | 9.7:1  |
| Link on cards             | `color-link` on `color-surface`            | 5.8:1  | 8.8:1  |
| Gold-tint text            | `color-accent-text` on `color-accent-bg`   | 6.8:1  | 9.4:1  |
| Primary button label      | `color-accent-contrast` on `color-accent`  | 16.1:1 | 8.3:1  |
| Gold button label         | `color-on-gold` on `color-gold`            | 6.7:1  | 8.3:1  |
| Danger button label       | `color-danger-contrast` on `color-danger`  | 7.3:1  | 8.1:1  |
| Text on navy              | `color-on-slate` on `color-slate`          | 16.1:1 | 17.9:1 |
| Muted text on navy        | `color-on-slate-muted` on `color-slate-2`  | 10.1:1 | 11.2:1 |
| Gold text on navy         | `color-on-slate-accent` on `color-slate`   | 9.0:1  | 10.0:1 |
| Success badge             | `status-success-fg` on `status-success-bg` | 7.1:1  | 7.9:1  |
| Warning badge             | `status-warning-fg` on `status-warning-bg` | 6.3:1  | 7.9:1  |
| Danger badge              | `status-danger-fg` on `status-danger-bg`   | 6.9:1  | 8.1:1  |
| Info badge                | `status-info-fg` on `status-info-bg`       | 11.0:1 | 8.0:1  |
| Neutral badge             | `status-neutral-fg` on `status-neutral-bg` | 7.9:1  | 9.1:1  |
| Error text                | `color-danger` on `color-surface`          | 7.3:1  | 7.9:1  |
| Success text              | `color-success` on `color-surface`         | 8.3:1  | 9.6:1  |
| Control edge              | `color-control-border` on `color-surface`  | 4.3:1  | 4.5:1  |

**Control borders.** Form controls and secondary buttons use `--color-control-border` so their edges are visible (WCAG 1.4.11, 3:1). `--color-border` is for decoration such as card edges and dividers and is deliberately lighter.

### 2.2 Typography

Two families, both SIL OFL and bundled with the app (`@fontsource-variable/cormorant-garamond`, `@fontsource-variable/montserrat`), so nothing is fetched from another site. They are matched to the logo (Phase 20). **Cormorant Garamond** (`--font-display`, bold) echoes the high-contrast serif of the "AdVegaX" wordmark. It sets the page title (h1), section headings (h2) and the few large figures (key figures, admin counts), and is reserved for 24 px and up, where its fine strokes read well. **Montserrat** (`--font-sans`) echoes the tagline "Advertise smarter. Grow faster." and sets everything else: body, tables, controls, h3, small panel titles, and the spaced capital labels (navigation groups, the landing eyebrow). System serif and sans fonts are the fallbacks. Headings and tables use lining figures (Cormorant's default figures are old-style); tables, `.figures` and `[data-figure]` also use tabular figures so amounts line up. Sizes and weights come from tokens only.

| Role |
| ----------------------- | --------- | --------- | ------------------------------------------ |
| `color-bg` | `#f7f3ea` | `#04101e` | Page ground (ivory / deep navy) |
| `color-surface` | `#fffdf8` | `#0a1b30` | Cards, panels, inputs |
| `color-surface-2` | `#f1ebdf` | `#0f233b` | Tinted rows, table heads |
| `color-text` | `#05182d` | `#f2eee4` | Body text (Vega navy / ivory) |
| `color-text-muted` | `#4d5666` | `#b7bfcb` | Secondary text |
| `color-border` | `#e2daca` | `#203655` | Dividers, card edges |
| `color-border-strong` | `#b9b2a3` | `#3a5373` | Stronger dividers |
| `color-control-border` | `#807868` | `#6f84a2` | Input and secondary-button edges (≥ 3:1) |
| `color-accent` | `#05182d` | `#d9a85c` | Primary action, current item, chart line |
| `color-accent-contrast` | `#f7f3ea` | `#05182d` | Label on the primary action |
| `color-accent-bg` | `#f3e7d3` | `#2b2416` | Gold tint |
| `color-accent-text` | `#6e4511` | `#ebc583` | Text on the gold tint |
| `color-link` | `#8a5a1c` | `#e2b05f` | Links (ledger bronze / gold) |
| `color-focus` | `#8a5a1c` | `#e2b05f` | Focus ring |
| `color-gold` | `#c9944a` | `#d9a85c` | Brand rules, marks, primary action on navy |
| `color-on-gold` | `#05182d` | `#05182d` | Label on gold |
| `color-slate` | `#05182d` | `#020b16` | Navy band, sidebar |
| `color-slate-2` | `#0b2340` | `#071a2f` | Raised surface on the navy band |
| `color-on-slate` | `#f7f3ea` | `#f7f3ea` | Text on navy |
| `color-on-slate-muted` | `#c8cfda` | `#c8cfda` | Secondary text on navy |
| `color-on-slate-accent` | `#e2b05f` | `#e2b05f` | Gold text and focus on navy |
| `color-danger` | `#a3231a` | `#ff8f84` | Errors, destructive actions |
| `color-success` | `#22573b` | `#8fcfa6` | Done, connected |
| `color-warning` | `#8a3b12` | `#f0ae84` | Needs attention |

Status colours come in foreground/background pairs: `--status-success-*`, `--status-warning-*`, `--status-danger-*`, `--status-info-*`, `--status-neutral-*` (each `-fg` and `-bg`).

| Meaning                      | Use for                                                                 | Never for                                          |
| ---------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------- |
| **Accent** (navy; gold dark) | The one primary action per view, the current navigation item, charts    | Decoration, status                                 |
| **Gold**                     | Hairline rules, the current-item mark, the primary action on navy bands | Text or links on paper (fails contrast)            |
| **Link / focus** (bronze)    | Links and focus rings on paper                                          | Buttons                                            |
| **Success** (green)          | Completed, connected, up to date                                        | "Good" numbers (metrics are not coloured by value) |
| **Warning** (terracotta)     | Needs attention; **a figure that cannot be shown yet**                  | Errors                                             |
| **Danger** (red)             | Errors, destructive actions                                             | Emphasis                                           |
| **Info / neutral**           | Plain information, inactive states                                      | —                                                  |

**Contrast, measured** (WCAG AA needs 4.5:1 for text and 3:1 for control edges; the lowest text pair here is 5.3:1):

| Pair                      | Tokens                                     | Light  | Dark   |
| ------------------------- | ------------------------------------------ | ------ | ------ |
| Body text                 | `color-text` on `color-bg`                 | 16.1:1 | 16.5:1 |
| Body text on cards        | `color-text` on `color-surface`            | 17.6:1 | 15.0:1 |
| Muted text                | `color-text-muted` on `color-bg`           | 6.7:1  | 10.3:1 |
| Muted text on tinted rows | `color-text-muted` on `color-surface-2`    | 6.2:1  | 8.6:1  |
| Link                      | `color-link` on `color-bg`                 | 5.3:1  | 9.7:1  |
| Link on cards             | `color-link` on `color-surface`            | 5.8:1  | 8.8:1  |
| Gold-tint text            | `color-accent-text` on `color-accent-bg`   | 6.8:1  | 9.4:1  |
| Primary button label      | `color-accent-contrast` on `color-accent`  | 16.1:1 | 8.3:1  |
| Gold button label         | `color-on-gold` on `color-gold`            | 6.7:1  | 8.3:1  |
| Danger button label       | `color-danger-contrast` on `color-danger`  | 7.3:1  | 8.1:1  |
| Text on navy              | `color-on-slate` on `color-slate`          | 16.1:1 | 17.9:1 |
| Muted text on navy        | `color-on-slate-muted` on `color-slate-2`  | 10.1:1 | 11.2:1 |
| Gold text on navy         | `color-on-slate-accent` on `color-slate`   | 9.0:1  | 10.0:1 |
| Success badge             | `status-success-fg` on `status-success-bg` | 7.1:1  | 7.9:1  |
| Warning badge             | `status-warning-fg` on `status-warning-bg` | 6.3:1  | 7.9:1  |
| Danger badge              | `status-danger-fg` on `status-danger-bg`   | 6.9:1  | 8.1:1  |
| Info badge                | `status-info-fg` on `status-info-bg`       | 11.0:1 | 8.0:1  |
| Neutral badge             | `status-neutral-fg` on `status-neutral-bg` | 7.9:1  | 9.1:1  |
| Error text                | `color-danger` on `color-surface`          | 7.3:1  | 7.9:1  |
| Success text              | `color-success` on `color-surface`         | 8.3:1  | 9.6:1  |
| Control edge              | `color-control-border` on `color-surface`  | 4.3:1  | 4.5:1  |

**Control borders.** Form controls and secondary buttons use `--color-control-border` so their edges are visible (WCAG 1.4.11, 3:1). `--color-border` is for decoration such as card edges and dividers and is deliberately lighter.

### 2.2 Typography

Two families, both SIL OFL and bundled with the app (`@fontsource-variable/sora`, `@fontsource-variable/ibm-plex-sans`), so nothing is fetched from another site. **Sora** (`--font-display`) sets headings and the few large numbers (key figures, admin counts): its open, geometric-humanist shapes give the product its voice. **IBM Plex Sans** (`--font-sans`) sets everything else: plain, very legible at small sizes, with clear figures. System fonts are the fallback. Tables, `.figures` and `[data-figure]` use tabular, lining figures so amounts line up. Sizes and weights come from tokens only.

| Role                       | Token                              | Size  | Weight                  | Used for                                 |
| -------------------------- | ---------------------------------- | ----- | ----------------------- | ---------------------------------------- |
| Display                    | `--font-size-3xl` (fluid 40–72 px) | fluid | bold (serif)            | Public home page headline only           |
| Page title (h1)            | `--font-size-2xl`                  | 40 px | bold (serif)            | One per page                             |
| Section (h2)               | `--font-size-xl`                   | 28 px | bold (serif)            | Page sections                            |
| Subsection (h3), lead text | `--font-size-lg`                   | 18 px | semibold (sans)         | Cards, groups, panel titles              |
| Body                       | `--font-size-md`                   | 16 px | regular                 | Everything else                          |
| Small                      | `--font-size-sm`                   | 14 px | regular / medium        | Hints, table headers, captions, metadata |
| Extra small                | `--font-size-xs`                   | 12 px | semibold, sentence case | Small labels (navigation groups use sm)  |

Weights: `--font-weight-regular` 400, `-medium` 500, `-semibold` 600, `-bold` 700. Rules:

- **One h1 per page**, then h2, h3 in order; never skip a level for looks. Headings use `--line-height-tight` (1.2) and balanced wrapping; body text uses `--line-height` (1.5).
- **Prose is capped at `--measure` (65 characters).** Long paragraphs do not span a wide screen.
- **Numbers in tables and tiles use tabular figures** (equal-width digits) so columns line up; money, counts and percentages are right-aligned in tables.
- Body text is never smaller than 14 px; nothing is set in capitals except the extra-small spaced labels (navigation groups, the landing eyebrow), as in the logo's tagline.
- A heading smaller than `--font-size-xl` (panel and card titles) is set in the sans.
- Links are underlined and use the accent colour; muted text (`--color-text-muted`) is for secondary information only, never for required instructions.

### 2.3 Spacing

A 4 px scale: `--space-1` 4, `-2` 8, `-3` 12, `-4` 16, `-5` 20, `-6` 24, `-8` 32, `-10` 40, `-12` 48, `-16` 64, `-24` 96. `padding`, `margin` and `gap` may only use these (or `0`, `auto`, percentages, or an expression built from them).

Rhythm: 8 px inside compact groups, 16 px between related blocks, 24–32 px between sections, 40–64 px between page bands on the public page.

### 2.4 Radius, elevation, layers

- Radius (Phase 20: near-square, like a ledger): `--radius-sm` 2 px (inputs, badges), `-md` 2 px (cards, buttons, menus), `-lg` 4 px (large images), `-pill` (rare), `50%` (avatars).
- Elevation: hairline rules instead of shadows. `--shadow-sm` is none; `--shadow-md` is a 1 px hairline under floating images; `--shadow-lg` is kept for things that float over content (menus, toasts).
- Layers: `--z-dropdown` 10 < `--z-header` 20 < `--z-drawer` 30 < `--z-toast` 40 < `--z-skip` 100. Nothing else sets a z-index.

### 2.5 Layout

**Breakpoints** (min-width, mobile first): 40 rem (640 px) tablet, 48 rem (768 px) sidebar appears, 64 rem (1024 px) desktop. Content is capped at `--content-max-width` (72 rem, 1152 px).

**Responsive side padding** is one token, `--gutter`: 16 px on phones, 24 px from 40 rem, 32 px from 64 rem. Every page container uses it; no page chooses its own side padding.

**Layout primitives** (`components/layout/Layout.tsx`): compose pages from these instead of writing widths, padding and gaps.

| Primitive   | What it does                                                                                  | Use                                   |
| ----------- | --------------------------------------------------------------------------------------------- | ------------------------------------- |
| `Container` | Centres, caps width at `--content-max-width` (or `size="narrow"`, 40 rem), applies `--gutter` | The outer wrapper of a page or band   |
| `Stack`     | Children in a column with an even gap (`gap` 2, 3, 4, 6 or 8)                                 | Forms, sections, anything vertical    |
| `Cluster`   | Items in a row that **wraps** instead of overflowing; `spread`, `align`                       | Button rows, toolbars, header content |
| `Grid`      | Equal columns that wrap by width, never narrower than `min` (12, 16 or 20 rem)                | Card grids                            |

Robustness rules: grids use `minmax(0, 1fr)` so long content cannot widen the page; scrollable regions are bounded and keyboard-reachable; text wraps (`overflow-wrap`) instead of overflowing; nothing uses a fixed pixel width for content. Inline `style` attributes are not used: the Content-Security-Policy blocks them in server-rendered pages.

**Page types**, each with its own composition (consistency comes from the system, not from sameness):

| Page type            | Composition                                                              |
| -------------------- | ------------------------------------------------------------------------ |
| Organization page    | Sidebar navigation + one content column, page title first                |
| Dashboard (Overview) | Tiles grouped by question (sales, advertising), then detail              |
| List / table         | Caption or heading, filters in one `Cluster`, `DataTable`, empty state   |
| Detail               | Title and status, facts as a definition list, actions grouped at the end |
| Form / settings      | Narrow `Stack`; fields grouped by topic; one primary action              |
| Authentication       | Single centred card (`PageCard`), no sidebar                             |
| Public               | Full-width bands inside `Container`; each band has its own layout        |

### 2.6 Brand assets (Phase 20)

The logo files live in `frontend/public/brand/`. They are cut from the product owner's master logo (a raster image).

| File                             | What                                 | Used in                               |
| -------------------------------- | ------------------------------------ | ------------------------------------- |
| `mark.webp`                      | The mark, navy and gold, for paper   | `BrandLogo` (header)                  |
| `mark-dark.webp`                 | The mark, ivory and gold, for navy   | `BrandLogo` (dark scheme, navy bands) |
| `wordmark.webp`                  | "AdVegaX", navy with a gold X        | `BrandLogo`                           |
| `wordmark-dark.webp`             | "AdVegaX", ivory with a gold X       | `BrandLogo` (dark scheme, navy bands) |
| `logo-stacked-dark.webp`         | Mark, wordmark and tagline, for navy | Landing closing block                 |
| `app/icon.png`, `apple-icon.png` | The mark on a navy square            | Browser tab and home-screen icon      |

`components/layout/BrandLogo.tsx` renders the horizontal lockup (mark and wordmark). With `tone="auto"` it switches to the ivory files when the person's system is in dark mode (a `<picture>` source, no script). With `tone="onDark"` it always uses them. The wordmark image carries the accessible name "AdVegaX"; the mark is decorative.

Rules:

- Never recolour, stretch or redraw the logo.
- On paper use the navy files; on navy use the ivory files.
- Keep clear space of at least the mark's width around the stacked logo.
- Replace these raster cuts with a vector (SVG) master when one is available.

### 2.7 Motion and icons

- Motion uses the tokens `--duration-fast` (140 ms, hovers), `--duration-base` (240 ms, lists and state changes) and `--duration-slow` (600 ms, the one entrance per page), with `--ease-out` (a soft settle) or `--ease-spring`. It explains change or guides the eye once: the landing hero's lines rise in order, the Overview's key figures and lists arrive staggered by 40–50 ms, sparklines draw in once. No scroll-triggered effects, no motion on idle content, and everything is disabled when the person prefers reduced motion (global rule).
- Icons come from one set (`components/ui/Icon.tsx`: inline SVG, 24 px grid, 1.75 px stroke, `currentColor`). They are decorative (`aria-hidden`) unless they are the only content of a control, in which case the control has an accessible name. No emoji as icons.

---

## 3. Components

Each entry: purpose, variants, states, accessibility, tokens. Names describe structure, not content.

### 3.1 Controls

| Component                             | Purpose                                       | Variants                                                | Notes                                                                                                                                                      |
| ------------------------------------- | --------------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Button` (`components/ui/Button.tsx`) | An action                                     | `primary` (one per view), `secondary`, `danger`, `link` | 44 px high; `busy` shows progress and disables; disabled state at 65% opacity with `not-allowed` cursor                                                    |
| `TextField`, `SelectField`            | Labelled input with hint and error text       | —                                                       | Label always visible; hint and error linked with `aria-describedby`; invalid state `aria-invalid`; border `--color-control-border`; width capped at 40 rem |
| Checkbox / radio                      | Choice                                        | —                                                       | 24 px, accent colour; grouped in `<fieldset>` with a `<legend>`                                                                                            |
| `ConfirmDialog`                       | Confirms a destructive or irreversible action | —                                                       | Native `<dialog>`; focus is trapped and restored; says what will happen                                                                                    |

### 3.2 Feedback

| Component            | Purpose                                            | Use when                                                         | Do not use for                                     |
| -------------------- | -------------------------------------------------- | ---------------------------------------------------------------- | -------------------------------------------------- |
| `Alert`              | A message that stays on the page                   | Errors that need action, a persistent notice, a form-level error | Passing confirmations                              |
| `Toast` (`useToast`) | A short message about something that just happened | "Settings saved", "Invitation sent"                              | Errors in a form, anything that must be read later |
| `Badge`              | Short status label                                 | Statuses in tables and cards                                     | Counts or decoration                               |
| `EmptyState`         | Nothing here yet: why and what to do next          | Lists with no rows                                               | Errors                                             |
| `Skeleton`           | Placeholder while data loads                       | Paired with a live "Loading…" status                             | Long waits (show progress text)                    |
| Inline field error   | The fix for one field                              | Validation                                                       | —                                                  |

**Choosing feedback:** field problem → inline error · form or page problem → `Alert` (error) · done and fine → `Toast` (success) · destructive step → `ConfirmDialog` · nothing yet → `EmptyState`.

### 3.3 `DataTable` (`components/ui/DataTable.tsx`)

- **Purpose:** show rows of comparable data.
- **Anatomy:** scroll region (labelled, keyboard-reachable) › `table` › caption › column headers › rows (first column may be a row header).
- **Props:** `caption` (required; `captionHidden` to keep it for assistive technology only), `columns` (`key`, `header`, `cell`, `numeric`, `rowHeader`, `sortValue`), `rows`, `getRowKey`, `empty`, `layout`, `defaultSort`.
- **Variants:** `layout="scroll"` (default) keeps columns and scrolls sideways inside its own box, for wide numeric tables; `layout="stack"` turns each row into a labelled card on phones, for tables of few columns with long content.
- **Sorting:** a column with `sortValue` gets a button in its header and `aria-sort`; numbers sort numerically, text sorts naturally ("2" before "10"), rows with no value always come last, ties keep their order, the input is never mutated.
- **Rules:** money, counts and percentages are `numeric`; the cell that names the row is `rowHeader`; the table never fetches, filters or pages (the page does that and passes the rows); an empty list shows `empty`, not an empty table.
- **Tokens:** `--color-border`, `--color-surface(-2)`, `--font-size-sm`, `--space-3/4`, `--radius-md`, `--touch-target`.

### 3.4 `Toast` (`components/ui/Toast.tsx`)

- **Purpose:** confirm something that just happened without moving focus or covering the page.
- **Use:** wrap the app in `ToastProvider` (done in `app/providers.tsx`); call `useToast().show({ tone, message, title? , durationMs? })`.
- **Tones and timing:** `success` 5 s, `info` 6 s, `warning` 8 s, `danger` stays until dismissed. A custom `durationMs` or `null` overrides this.
- **Behaviour:** at most three at once (the oldest makes way); the timer pauses while the pointer or keyboard focus is on a toast; Escape or the close button dismisses; the region is fixed to the bottom (full width on phones, 26 rem column from 40 rem), respects the device safe area, and never blocks clicks on the page behind it.
- **Accessibility:** problems use `role="alert"` (announced immediately); everything else uses `role="status"` (announced politely). The region lives in `<body>` and exists before the first message so screen readers are already listening. Close button has the name "Dismiss notification" and a 44 px target.
- **Do not** put actions that are the only way to do something in a toast, because it disappears.

### 3.5 Navigation

| Component              | Purpose                                                                           | Notes                                                                                                                                                                                                                                                            |
| ---------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SiteHeader`           | Brand, organization switcher, account menu, sign out                              | Built on `Container`; the brand is `BrandLogo` (mark + wordmark), on the page ground                                                                                                                                                                             |
| `OrganizationNav`      | Sections of one organization                                                      | A navy panel (Phase 20). Grouped (Performance, Marketing, Data, Organization) under spaced-capital labels; a sidebar from 48 rem; a collapsible menu with `aria-expanded` below; current page marked with `aria-current`, a raised navy row and a gold underline |
| `AccountMenu`          | The person's name and email, Account security, Admin portal (administrators only) | Disclosure button; Escape and outside click close it; spans the header on phones                                                                                                                                                                                 |
| `OrganizationSwitcher` | Switch organization                                                               | Same disclosure pattern                                                                                                                                                                                                                                          |

### 3.6 Data display

| Component                             | Purpose                                 | Notes                                                                                                         |
| ------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Tiles (`styles.tiles`, `styles.tile`) | One headline figure with its definition | Large value; a figure that cannot be shown uses the warning colour and states the reason; trend line optional |
| `Sparkline`                           | Trend of one figure over the period     | Decorative (`aria-hidden`); the same numbers are in the table; gaps are drawn as gaps                         |

---

### 3.7 Client dashboard (Overview)

Top to bottom, in order of what a person needs first:

1. **Statement**: one sentence built from the real figures ("Eve Zone sold A$1,500.50 in 12 orders, and spent A$204.50 on ads. After ad spend, it kept A$695.80."). A missing figure is named, never shown as zero.
2. **Key figures**: net sales, ad spend, profit after ad spend and orders in one ruled strip (not cards), each compared in words with the period just before ("Up 12% on the previous 30 days"), with a sparkline. Sage marks a good rise, terracotta a bad fall; ad spend is never coloured, since more spend is neither good nor bad on its own. Missing figures say why.
3. **Dashboard** (Phase 19, `features/overview/Dashboard.tsx`): open cards with one 3 px rule on top (no shadow, rounded only at the bottom).
   - **Sales, ad spend and profit by day** spans the width: navy net-sales line (gold in dark mode), green profit line, terracotta ad-spend bars, a "round" y-axis (never "-A$0"), and a readout strip above the plot for the chosen day (pointer, or arrow keys / Home / End on the focusable chart). Missing days break the line; they are never drawn as zero.
   - **Where the money went**: ad spend by platform (terracotta bars, largest first) and visits by Google Analytics channel (navy bars). Bar lengths are drawing only, relative to the largest row; every number shown comes from the API.
   - **From first view to purchase**: the funnel stages in the API's order, a square-root bar scale (impressions and purchases differ a thousandfold), the API's step rate, and "Below usual" only where the API reports a finding.
   - **Campaigns that spent most**: the five with the most spend, linking to each campaign; on screens under 64rem each row becomes a labelled card.
   - SVG `rect` bars, not inline widths, because the CSP forbids inline styles. On wide screens the money and funnel cards sit side by side (7fr / 5fr).
4. **Work**: "Waiting for you" (open advice, linking straight to each decision) beside "Recent changes" (the latest changes with their state). Open columns under a rule; rows highlight on hover and focus.
5. **All figures**: the note "Why some figures are missing" (each reason once, numbered, with a link that fixes it), then the ledger (one table per group, amounts right-aligned, missing amounts link to their note), the day table and the sources.

### 3.7a Organization pages (Phase 19)

Every organization page uses the same parts as the Overview: the page title, then one muted line saying what the page is for (kept to the reading measure); panels with the 3 px top rule; table headings small and muted over a stronger rule; rows that light up under the pointer. Small repeated cards (accounts, connections, stores) stay light, with a hover border, so a list of them does not look heavy. Advertising account cards sit side by side on wide screens.

### 3.8 Admin portal

The operator area sits under the slate band that says customers never see it, so it cannot be mistaken for an organization page. A sticky side index lists the sections on desktop. Feature switches are `button role="switch"` with `aria-checked` and visible On/Off text. Keys show a status badge (the stored hint, or "Not set") and where the value comes from; changing one opens a small inline form. "System health" is a dense ruled grid: database, background jobs, restart needed and environment, then counts (organizations and how many are active, people and administrators, switches on, keys entered). Organizations and People are sortable tables with a search box (and a status filter for organizations) and a live "Showing X of Y" line; on phones each row becomes a labelled card.

### 3.9 Public landing page

A full-width navy block opens the page: the tagline "Advertise smarter. Grow faster." as a spaced-capital eyebrow after a gold rule, the headline (Cormorant Garamond, large, short measure), who it is for, two actions and three plain facts, beside **"Data flowing in"** (`features/home/HeroFlow.tsx`, Phase 19). The four sources (your store, Google Ads, Meta, Google Analytics) draw their lines into one white "Profit after ad spend" panel, whose bars grow and profit line draws. It is the page's one orchestrated moment: about two seconds, played once, static for reduced motion, and an illustration only: no figures. On phones the sources sit in a 2 × 2 grid above the panel, without lines. The real screenshot of the demo Overview (labelled as simulated data) follows in "The whole picture, every morning". The rest of the page sits on the page background: "How it works" is a sequence numbered I.–IV. in bronze serif numerals under one navy rule on wide screens (it really is a sequence), "Built so you stay in control" is a ruled two-column list, then the platforms and a navy closing block with the stacked logo and the same two actions (gold primary action). No invented customers, testimonials or statistics.

## 4. Content rules

- Plain language, present tense, no jargon without a "How is this calculated?" definition. Say what will happen before it happens.
- Buttons name the action ("Send invitation", "Save changes"), not "Submit" or "OK".
- Errors say what went wrong and what to do; they never blame the person and never show internal codes (platform names are shown as "Google Analytics", not `google_analytics`).
- Money is shown with its currency; ratios as percentages with one decimal; missing data as a reason ("Some products have no cost"), never `0`.
- Public text states only things the product does; no invented customers, logos or statistics.

---

## 5. Accessibility requirements (every component and page)

- Contrast: text 4.5:1 (large text 3:1); control boundaries and focus indicators 3:1.
- Focus: visible 3 px outline (`--color-focus`), never removed; logical order; focus moves to the page title after navigation; dialogs trap and restore focus.
- Targets: at least 24 px everywhere, 44 px (`--touch-target`) for buttons, menu items and nav links.
- Semantics: landmarks, one h1, real lists and tables, labels tied to inputs, errors tied with `aria-describedby`.
- Colour is never the only signal; status has text.
- Motion: respects `prefers-reduced-motion`.
- Verified with automated checks (axe, WCAG 2.2 A/AA tags) and tests; manual keyboard and screen-reader review is still needed (see §10).

---

## 6. Responsive rules

- Mobile first; no horizontal page scroll at 320 px.
- Tables: choose `scroll` or `stack` deliberately (§3.3).
- Menus and dialogs never extend past the viewport (`min(…, 100vw − gutter)` widths).
- Images are served at several widths (`srcset`) with fixed `width`/`height` to prevent layout shift.

---

## 7. Adding or changing things (governance)

### 7.1 A new token

1. Add it to `app/globals.css` with a light and a dark value (for colour) and a comment saying what it is for.
2. Check contrast (text 4.5:1, controls 3:1) and record it in §2.1.
3. Use it in at least one place in the same change.

### 7.2 A new component or variant

Accept only if it is needed in **three** places, has a stated purpose, meets §5, defines its responsive behaviour, and is documented here (purpose, props, states, accessibility, tokens). Name it by structure ("Badge", not "StatusPill"). More than five variants means it should be split.

### 7.3 Deprecating

Mark it here with the replacement, migrate usages, then delete it; the delete is listed in the change report (PROJECT_RULES §16).

---

## 8. Enforcement

`frontend/tests/static/design-tokens.test.ts` runs with the normal tests and fails if a stylesheet (outside `globals.css`) contains: a colour literal; a `font-size` or `font-weight` that is not a token; a `border-radius` that is not a token (or `0`, `50%`); `padding`, `margin` or `gap` built from anything but tokens; a `z-index` that is not a layer token; or `!important`. The inline-style ban is in `tests/static/source-rules.test.ts`.

---

## 9. Status and known gaps (2026-10-30)

**Done:** tokens, layout primitives, `Badge`, `EmptyState`, `Skeleton`, `Sparkline`, `Icon`, `DataTable`, `Toast`, grouped navigation, account menu, the public home page, status styling shared across Recommendations, Changes, Advertising, Stores and Connections; every stylesheet passes the token rules.

**Adoption not finished:**

- `DataTable` is used by **Billing (usage)** and **Changes**. These 18 files still build their own tables with the older shared CSS and should migrate, one at a time with their tests: `account/SessionsSection`, `admin/AdminPage`, `advertising/AdAccountPage`, `advertising/CampaignPage`, `advertising/Figures`, `agency/ClientsPage`, `analytics/Figures`, `autopilot/AutopilotSettings`, `connections/ConnectionDetailPage`, `funnel/FunnelPage`, `organizations/InvitationsSection`, `organizations/MembersTable`, `overview/OverviewFigures`, `overview/ReportsPage`, `recommendations/RecommendationsPages`, `stores/ProductsPage`, `stores/RevenueView`, `strategies/StrategiesPage`.
- `Toast` is used for "Settings saved", "No changes to save" and "Invitation sent". Other success messages still use inline `Alert`.
- Layout primitives are used by the site header; page containers still use their own classes (which do use `--gutter`).

**Not built yet:** `Tabs`, `Breadcrumbs`, a drawer for very small screens, a component gallery page.

**Not verified:** manual keyboard and screen-reader walk-through; real touch devices; the 2 frontend tests in `creatives.test.tsx` fail on Node 22 (the project requires Node 24), cause unconfirmed.
