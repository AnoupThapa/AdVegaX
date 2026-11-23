# UI, UX and accessibility audit

## Method

- **Rendered sweep:** 22 pages × 9 widths (320, 375, 390, 430, 768, 1024, 1280, 1440 and 1920 px), 198 page loads, using the production build, Chromium, demo data and reduced motion. For each load the sweep measured horizontal overflow, controls under 24 px, clipped text, and console and page errors.
- **axe-core** (WCAG 2.0/2.1/2.2 A and AA rules) at 390 and 1440 px on every page.
- **Accessibility checks inside the 21 end-to-end journeys**, including a keyboard-only journey.
- **Manual review** of screenshots and of the design-system rules (`docs/DESIGN_SYSTEM.md`, `tests/static/design-tokens.test.ts`).

Pages swept: landing, sign-in, sign-up, forgot password, organizations home, Overview, Reports, Funnel, Analytics, Advertising, Strategies, Creatives, Recommendations, Changes, Stores, Connections, Members, Settings, Billing, Account security, New organization, Admin.

## Results

| Check                            | Result                                                                                                                                                                      |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Horizontal overflow, any width   | **0 of 198**                                                                                                                                                                |
| axe violations (390 and 1440 px) | **0**                                                                                                                                                                       |
| Clipped text                     | 0. The two hits were intentionally visually-hidden labels.                                                                                                                  |
| Console and page errors          | One 401 on the first, signed-out page load (the session check). Expected.                                                                                                   |
| Controls under 24 px             | "How is this calculated?" disclosures (18 px; pass via the WCAG 2.5.8 spacing exception), the Creatives file input (21 px), inline footnote links (QA-014)                  |
| Keyboard                         | The e2e `keyboard` journey passes: skip link, menus, forms and dialogs                                                                                                      |
| Reduced motion                   | A global rule cuts all animation and transition to 0.01 ms                                                                                                                  |
| Contrast                         | Token pairs are documented at ≥ 4.5:1 in light and dark modes. axe agrees once animations have finished, but **during** the Overview's fade-in one reading failed (QA-010). |

## Visual consistency

**Strengths:**

- One token system enforced by a test. Colour literals and off-scale sizes, weights, radii, spacing and z-index values are all rejected, as is `!important`.
- One family pair: Sora for headings, IBM Plex Sans for text.
- A restricted palette (slate, cobalt, terracotta, sage) where colour is never the only signal; badges always carry words.

**Weaknesses:**

- Older pages (Reports, Funnel, Advertising, Settings) still use the earlier boxed-panel style.
- The Overview and Admin pages use the newer ruled, open layout, so the two styles sit side by side (P4, cosmetic).
- Long setting pages (Settings, Admin keys) are long single columns. They are usable, but slow to scan on a phone (P4).

## Interaction quality

- Loading states exist on every data page, and empty states say what to do next.
- Errors are specific: the API error codes map to plain messages (`lib/api/errors`).
- Rejecting advice or a change is a two-step flow that asks for a reason. Other destructive actions were not each checked for confirmation. **Confirmed gap:** in the Admin portal, "Suspend <organization>" acts on a single click, with no confirmation and no undo prompt (QA-018).
- When the API is unreachable, a signed-in page waits up to about 20 s before saying so (QA-015).
- No dead controls were found in the sweep. Every visible button in the e2e journeys performs its labelled action.

## Not verified

- Screen readers on real devices (NVDA, VoiceOver).
- Browsers other than Chromium.
- Windows high-contrast mode.
- 200% and 400% zoom, beyond the 320 px reflow check.
- Real touch devices.
