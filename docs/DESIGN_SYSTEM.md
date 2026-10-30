# AdVegaX — Design system

**Status:** living document · first version 2026-10-30 (Phase 17) · owner: product owner; changes follow §9.
**Where it lives in code:** tokens in `frontend/app/globals.css`; shared components in `frontend/components/`; rules enforced by `frontend/tests/static/design-tokens.test.ts`.

The aim is one look across the whole product: a small palette, one type scale, one spacing scale, a few layout containers, and a short list of components. Pages are composed from these; they do not invent their own values.

---

## 1. Principles

1. **Restricted palette.** Neutrals, one accent (blue) and four status colours. Nothing else. Colour never carries meaning alone: statuses always have a text label.
2. **Tokens, not values.** Pages and components reference tokens (`var(--space-4)`), never raw numbers or colours. A test enforces this (§9.3).
3. **Consistency from the system, not from identical pages.** A table-heavy page and a form page share tokens and components but not a layout.
4. **Accessible by default.** WCAG 2.2 AA is the floor: contrast, 24 px minimum targets (44 px for primary controls), visible focus, labelled controls, keyboard operation, reduced motion respected.
5. **Honest data.** Missing data is shown as missing (amber, with the reason), never as zero.
6. **Light and dark.** Every colour token has both values; components never pick a colour per theme.
7. **Small.** A new component or variant needs a use in three places (§9.1). Prefer composing what exists.

---

## 2. Foundations

### 2.1 Colour (restricted palette)

Three tiers: **reference** values live only in `globals.css`; **semantic** tokens (below) are what the rest of the code uses; **component** styles combine semantic tokens.

| Token                 | Light     | Dark      |
| --------------------- | --------- | --------- |
| `color-bg`            | `#f7f8fa` | `#0f1116` |
| `color-surface`       | `#ffffff` | `#171a21` |
| `color-surface-2`     | `#f1f3f6` | `#1d212a` |
| `color-text`          | `#14171f` | `#eef0f4` |
| `color-text-muted`    | `#4a5160` | `#b4bac6` |
| `color-border`        | `#d5d9e0` | `#2f3542` |
| `color-border-strong` | `#aab1bd` | `#4a5263` |
| `color-accent`        | `#1f5fd1` | `#7aa7ff` |
| `color-accent-text`   | `#1a4fb0` | `#9bbcff` |
| `color-accent-bg`     | `#e8f0fd` | `#14284f` |
| `color-danger`        | `#b42318` | `#ff8a80` |
| `color-success`       | `#1e7a3c` | `#6fd18f` |
| `color-warning`       | `#8a5a00` | `#f2c14e` |

Status colours come in foreground/background pairs: `--status-success-*`, `--status-warning-*`, `--status-danger-*`, `--status-info-*`, `--status-neutral-*` (each `-fg` and `-bg`).

| Meaning             | Use for                                                                    | Never for                                          |
| ------------------- | -------------------------------------------------------------------------- | -------------------------------------------------- |
| **Accent** (blue)   | The one primary action per view, links, the current navigation item, focus | Decoration, status                                 |
| **Success** (green) | Completed, connected, up to date                                           | "Good" numbers (metrics are not coloured by value) |
| **Warning** (amber) | Needs attention; **a figure that cannot be shown yet**                     | Errors                                             |
| **Danger** (red)    | Errors, destructive actions                                                | Emphasis                                           |
| **Info / neutral**  | Plain information, inactive states                                         | —                                                  |

**Contrast, measured** (WCAG AA needs 4.5:1 for text; lowest here is 5.4:1):

| Pair                      | Tokens                                     | Light  | Dark   |
| ------------------------- | ------------------------------------------ | ------ | ------ |
| Body text                 | `color-text` on `color-bg`                 | 16.9:1 | 16.6:1 |
| Body text on cards        | `color-text` on `color-surface`            | 17.9:1 | 15.3:1 |
| Muted text                | `color-text-muted` on `color-bg`           | 7.5:1  | 9.7:1  |
| Muted text on tinted rows | `color-text-muted` on `color-surface-2`    | 7.2:1  | 8.3:1  |
| Link / accent text        | `color-accent` on `color-surface`          | 5.8:1  | 7.3:1  |
| Accent text on its tint   | `color-accent-text` on `color-accent-bg`   | 6.6:1  | 7.6:1  |
| Primary button label      | `color-accent-contrast` on `color-accent`  | 5.8:1  | 7.9:1  |
| Danger button label       | `color-danger-contrast` on `color-danger`  | 6.6:1  | 8.3:1  |
| Success badge             | `status-success-fg` on `status-success-bg` | 6.5:1  | 8.6:1  |
| Warning badge             | `status-warning-fg` on `status-warning-bg` | 6.4:1  | 9.2:1  |
| Danger badge              | `status-danger-fg` on `status-danger-bg`   | 6.8:1  | 8.1:1  |
| Info badge                | `status-info-fg` on `status-info-bg`       | 6.6:1  | 7.6:1  |
| Neutral badge             | `status-neutral-fg` on `status-neutral-bg` | 8.4:1  | 8.9:1  |
| Error text                | `color-danger` on `color-surface`          | 6.6:1  | 7.6:1  |
| Success text              | `color-success` on `color-surface`         | 5.4:1  | 9.3:1  |

**Control borders.** Form controls and secondary buttons use `--color-control-border` (about 3.8:1 light, 3.7:1 dark) so their edges are visible (WCAG 1.4.11, 3:1). `--color-border` is for decoration such as card edges and dividers and is deliberately lighter.

### 2.2 Typography

One family (`--font-sans`, the system UI font: no download, no layout shift). Sizes and weights come from tokens only.

| Role                       | Token                              | Size  | Weight                       | Used for                                 |
| -------------------------- | ---------------------------------- | ----- | ---------------------------- | ---------------------------------------- |
| Display                    | `--font-size-3xl` (fluid 32–52 px) | fluid | bold                         | Public home page headline only           |
| Page title (h1)            | `--font-size-2xl`                  | 32 px | semibold–bold                | One per page                             |
| Section (h2)               | `--font-size-xl`                   | 24 px | semibold                     | Page sections                            |
| Subsection (h3), lead text | `--font-size-lg`                   | 18 px | semibold                     | Cards, groups                            |
| Body                       | `--font-size-md`                   | 16 px | regular                      | Everything else                          |
| Small                      | `--font-size-sm`                   | 14 px | regular / medium             | Hints, table headers, captions, metadata |
| Extra small                | `--font-size-xs`                   | 12 px | semibold, uppercase, tracked | Group labels in navigation               |

Weights: `--font-weight-regular` 400, `-medium` 500, `-semibold` 600, `-bold` 700. Rules:

- **One h1 per page**, then h2, h3 in order; never skip a level for looks. Headings use `--line-height-tight` (1.2) and balanced wrapping; body text uses `--line-height` (1.5).
- **Prose is capped at `--measure` (65 characters).** Long paragraphs do not span a wide screen.
- **Numbers in tables and tiles use tabular figures** (equal-width digits) so columns line up; money, counts and percentages are right-aligned in tables.
- Body text is never smaller than 14 px; nothing is set in capitals except the extra-small group labels.
- Links are underlined and use the accent colour; muted text (`--color-text-muted`) is for secondary information only, never for required instructions.

### 2.3 Spacing

A 4 px scale: `--space-1` 4, `-2` 8, `-3` 12, `-4` 16, `-5` 20, `-6` 24, `-8` 32, `-10` 40, `-12` 48, `-16` 64, `-24` 96. `padding`, `margin` and `gap` may only use these (or `0`, `auto`, percentages, or an expression built from them).

Rhythm: 8 px inside compact groups, 16 px between related blocks, 24–32 px between sections, 40–64 px between page bands on the public page.

### 2.4 Radius, elevation, layers

- Radius: `--radius-sm` 4 px (inputs, badges), `-md` 8 px (cards, buttons, menus), `-lg` 12 px (large images), `-pill` (rare), `50%` (avatars).
- Elevation: `--shadow-sm` (cards, optional), `--shadow-md` (floating images), `--shadow-lg` (menus, toasts). In dark mode shadows are stronger or removed because they are barely visible.
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

### 2.6 Motion and icons

- Motion is short (about 150 ms), used only to explain change (a toast sliding in, a loading shimmer), and disabled when the person prefers reduced motion (global rule).
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

| Component              | Purpose                                                                           | Notes                                                                                                                                                               |
| ---------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SiteHeader`           | Brand, organization switcher, account menu, sign out                              | Built on `Container`                                                                                                                                                |
| `OrganizationNav`      | Sections of one organization                                                      | Grouped (Performance, Marketing, Data, Organization); a sidebar from 48 rem; a collapsible menu with `aria-expanded` below; current page marked with `aria-current` |
| `AccountMenu`          | The person's name and email, Account security, Admin portal (administrators only) | Disclosure button; Escape and outside click close it; spans the header on phones                                                                                    |
| `OrganizationSwitcher` | Switch organization                                                               | Same disclosure pattern                                                                                                                                             |

### 3.6 Data display

| Component                             | Purpose                                 | Notes                                                                                                         |
| ------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Tiles (`styles.tiles`, `styles.tile`) | One headline figure with its definition | Large value; a figure that cannot be shown uses the warning colour and states the reason; trend line optional |
| `Sparkline`                           | Trend of one figure over the period     | Decorative (`aria-hidden`); the same numbers are in the table; gaps are drawn as gaps                         |

---

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
