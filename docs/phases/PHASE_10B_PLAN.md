# Phase 10B — Campaign Builder: Implementation Plan

**Status:** ✅ **Approved 2026-10-27 (A29, "Approve all": Q-10B-1 … Q-10B-12).** In progress — see `PHASE_10B_PROGRESS.md`. · **Date:** 2026-10-27

> **This is the first phase that can create campaigns at Google or Meta.** Everything is built and tested against the platform **simulators** (no calls in CI). It goes **only through the Action Engine** (Phase 10A, A13): every campaign is checked, tested by the platform, **approved by a person**, created **paused**, and goes live only on a second, separate approval.

**Depends on:**
- Phase 8 — a strategy marked ready;
- Phase 9 — approved creatives;
- Phase 10A — the Action Engine.

**Followed by:** Phase 11 (optimization recommendations).

**Governing documents:** MASTER_SPECIFICATION §9; D16; A2 (no change outside the engine); A13; `phases/PHASE_10B_CAMPAIGN_BUILDER.md` (outline); PHASE_10A_PLAN.

---

## 1. Objective

From a **ready strategy** and its **approved creatives**, AdVegaX prepares a complete, platform-specific campaign. It shows you exactly what will be created and creates it **paused** after approval. The campaign goes live only when you approve **"Go live"**.

**No spend without an explicit, approved launch. A launch that fails leaves nothing running.**

## 2. Decisions needed from you (plain language)

Each question has a recommendation. You can approve them all at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-10B-1** | Which campaigns? | One campaign per platform:<br>• **Google:** a **Search** campaign (one ad group, your keywords, the approved responsive search ad).<br>• **Meta:** a **Sales** campaign (one ad set, the approved single-image ad).<br>Performance Max, Shopping and Advantage+ shopping campaigns need asset groups or a product feed, so they come later. A strategy that chose one of them is offered Search or Sales instead, with a note saying so. | These match exactly what Phase 9 drafts (responsive search ads, single-image Meta ads). |
| **Q-10B-2** | Where do keywords come from? | **You type them** (up to 20, one per line; phrase match by default, exact or broad optional). AdVegaX checks them: no duplicates, Google's length and character limits, and none of your prohibited words. AI keyword suggestions come later. | Keywords decide where money is spent; you choose them. |
| **Q-10B-3** | Targeting | **Locations:** countries, defaulting to the store's country (e.g. Australia). **Language** (Google): automatic, since Search no longer accepts manual language targeting. **Age** (Meta): 18–65+ by default, can be narrowed. No interest targeting in this phase (Meta's Advantage+ audience decides). | Simple, safe defaults you can see and change. |
| **Q-10B-4** | Bidding and optimization | **Google:** "Maximize conversions" when the account recorded conversions in the last 30 days, otherwise "Maximize clicks".<br>**Meta:** optimize for **purchases** with the Meta pixel (dataset) you choose; if you have none, optimize for **link clicks**, with a note. | No manual bids to set; works with or without tracking. |
| **Q-10B-5** | Budget | The **daily** amount the strategy computed for that platform, converted to the ad account's currency, editable. Every Phase 10A limit applies: the platform minimum and your maximum per campaign. | One source of truth for money (D16). |
| **Q-10B-6** | Landing page | Pre-filled with the product's page on your store. It must be **https** and on **your store's own domain**. You can edit it within that domain. | Stops typos and sending traffic elsewhere. |
| **Q-10B-7** | Meta page and pixel | You choose the **Facebook Page** the ad runs as, and optionally a **pixel**, from lists read from Meta. Reading Pages needs the `pages_show_list` permission, asked for with "Allow changes". | Meta requires a Page for every ad. |
| **Q-10B-8** | Launch in two approved steps | 1. **Create (paused):** after approval, the worker creates everything paused — Google in one all-or-nothing request; Meta in order: image, campaign, ad set, creative, ad, each paused. If any step fails, what was created stays paused, is listed, and can be removed with one approved action.<br>2. **Go live:** a separate change, approved again, switches the campaign (and Meta's ad set and ad) on. | Matches "launches only on explicit user action" and "failed launches leave nothing active". |
| **Q-10B-9** | Never twice | Each launch has a unique AdVegaX reference in the campaign name (e.g. "Gloves – Search · AVX-7F3A"). An unknown outcome (a timeout) is looked up **by that reference** before anything is sent again, as in 10A. | No duplicate campaigns, even when an answer is lost. |
| **Q-10B-10** | Declarations | **Google:** every campaign says it contains no EU political advertising (a required field). **Meta:** "special ad categories" is empty (none of housing, employment, credit or social issues), and you tick a box confirming this before requesting. | Both platforms require these answers; you confirm them. |
| **Q-10B-11** | Who | **Prepare:** owner, admin or manager. **Approve create and Go live:** owner or admin (with the second-person rule from 10A). | Same roles as 10A. |
| **Q-10B-12** | After creation | The new campaign's IDs are recorded and linked to the strategy and creatives. A quick sync is scheduled, so it appears under Advertising with its figures. | The whole history in one place. |

## 2A. What you need to set up (for Step 0 and real use)

1. Everything in 10A §2A: a Google test manager account; Meta change permission; network access.
2. **Meta:**
   - a Facebook **Page** connected to your business;
   - `pages_show_list` added to the change login configuration;
   - optionally a **pixel** (dataset).
3. **Google Required Minimum Functionality (RMF):** before AdVegaX creates campaigns for other businesses, Google requires it to offer certain management features (Step 0 reviews the list). Your own accounts are not affected.

## 3. Scope

| Area | In Phase 10B |
|---|---|
| Drafts | `app/domains/builder/`: a **campaign draft** per platform, from a ready strategy + one approved creative. It holds keywords, locations, age, landing page, budget, Page/pixel, declarations; it is editable until launch and versioned on every change. |
| Checks | Builder checks, then the Phase 10A checks (budget limits, write access, switches), then the platform's dry run of the **whole** campaign (Google `validateOnly` on the bulk request; Meta `validate_only` on each object). |
| Engine | New catalogue entries:<br>• `campaign.create` — everything paused;<br>• `campaign.go_live` — campaign, ad set and ad switched on;<br>• `campaign.remove_draft_objects` — clean up after a failed create.<br>All use 10A's state machine, approval, lock, look-up and audit. |
| Provider writes | `google_ads/writes.py`: one `googleAds:mutate` with temporary IDs (budget, campaign, ad group, keywords, ad).<br>`meta_ads/writes.py`: `adimages`, `campaigns`, `adsets`, `adcreatives`, `ads`, all `status=PAUSED`; Pages and pixels read.<br>Simulators extended for both. |
| API | `POST/GET/PATCH /campaign-drafts`, `POST /campaign-drafts/{id}/validate`, `POST /campaign-drafts/{id}/launch` (→ an action), `POST /campaign-drafts/{id}/go-live` (→ an action), `GET /meta/pages`, `GET /meta/pixels` |
| Web app | **Build campaign** on a ready strategy. The review screen shows exactly what will be created: the ad preview, keywords, targeting, budget per day and per month, the landing page, the declarations and the platform's test. Then launch and Go live through Changes. |
| Data | Migration **0021**: `campaign_drafts`; `actions` gains `draft_id` and the three new action types; `ad_campaigns` gains `draft_id` (the link back). |

## 3A. Non-goals

- Performance Max, Shopping, Advantage+ shopping, video, carousel.
- AI keyword or audience suggestions; bid adjustments; schedules; interest targeting.
- Automatic launch without approval (Phase 12).
- Editing a launched campaign's ads or keywords: changes after launch stay the 10A changes (pause, resume, budget).

## 4. Facts and Step 0

### 4.1 Facts (checked 2026-10-27)

1. **Google Ads API, "Get started with Search campaigns":**
   - **Budget** — `amount_micros`, delivery `STANDARD`.
   - **Campaign** — `advertising_channel_type: SEARCH`; status; a bidding strategy (e.g. `maximize_conversions`); `network_settings`; and the now-required `contains_eu_political_advertising`.
   - **Ad group** — `SEARCH_STANDARD`.
   - **Keywords** — ad group criteria with text and match type.
   - **Responsive search ad** — 3–15 headlines, 2–4 descriptions, `final_urls`, optional `path1`/`path2`.
   - **One request** — `GoogleAdsService.Mutate` creates them all atomically, with temporary resource names (`campaignBudgets/-1`, `campaigns/-2`, …), parents before children; `validate_only` checks without applying.
   - **Language** — manual language targeting is not supported on Search campaigns.
2. **Meta Marketing API (Meta's Ads CLI announcement, 2026-04-29):**
   - **Created paused** — resources are created PAUSED unless asked otherwise.
   - **Campaign** — name, objective (`OUTCOME_SALES`), daily budget in the account currency's smallest unit.
   - **Ad set** — campaign, optimization goal, billing event, target countries.
   - **Creative** — Page, image, body, title, link, call to action.
   - **Ad** — ad set and creative.

   Special ad categories, `promoted_object` (pixel and event) and the image upload (`/adimages` → hash) are confirmed in Step 0.

### 4.2 Step 0 — live checks (task 10B-01)

1. **Google test account:** create a Search campaign with `validateOnly`, then for real, and check it is paused, the budget amount and the ad.
2. **Meta, your own account:** upload an image, create campaign → ad set → creative → ad (all paused); then Go live and pause again.
3. A forced failure in the middle of a Meta launch leaves only paused objects, and cleanup removes them.
4. Review Google's **Required Minimum Functionality** list and note what is needed before other businesses' accounts.

## 5. Data model (migration 0021)

**`campaign_drafts`** — tenant-owned, forced RLS:
- `strategy_id`, `creative_id` (an approved version), `platform`, `ad_account_id`;
- `name`, `daily_budget` (account currency), `locations`, `age_min`/`age_max`, `keywords`, `landing_url`;
- `meta_page_id`, `meta_pixel_id`;
- `declarations` (confirmed by whom and when);
- `reference` (the AdVegaX tag), `version`, `status` (`draft` | `launching` | `created` | `live` | `failed` | `archived`);
- `created_ids` (the platform IDs created so far);
- created and updated by, timestamps.

**Other tables:**
- **`actions`:** `draft_id` (optional), three new action types.
- **`ad_campaigns`:** `draft_id`.

## 6. API

As §3. New errors:
- `DRAFT_INVALID` (with each failed check);
- `DRAFT_NOT_EDITABLE` (launched or launching);
- `CREATIVE_NOT_APPROVED`.

Plus 10A's errors.

## 7. Security

- Created objects are always paused first; only `campaign.go_live` switches anything on, and it needs its own approval.
- Write calls stay only in `providers/*/writes.py` (static rules extended to the new methods).
- The landing page is restricted to the store's own domain over https. Keyword and text checks reuse Phase 9's prohibited terms.
- Meta Pages and pixels are read with the connection's own token. IDs are validated before they enter a path.
- Tenant isolation: forced RLS; the route sweep covers every new route.

## 8. Testing

- **Builder checks:** keywords, locations, age, landing page, budget, declarations, creative approved and unchanged.
- **Google (simulator):**
  - the one bulk request with temporary IDs, `validateOnly`, all paused;
  - an atomic failure creates nothing;
  - a lost answer is found by the reference.
- **Meta (simulator):**
  - each step paused;
  - a failure mid-way leaves only paused objects, then cleanup;
  - a lost answer is looked up by the reference;
  - Go live switches campaign, ad set and ad.
- **No spend without Go live:** after create, nothing is active on either platform.
- **Duplicates and concurrency:** one launch per draft; two workers create once.
- **Web app and browser:** a page test of the review screen, and one browser test with accessibility checks: build, review, launch (simulator), created paused, Go live waiting.

## 9. Tasks (one report for the whole phase)

| Task | Content |
|---|---|
| 10B-01 | Step 0 (§4.2) — needs the accounts, Page and permissions |
| 10B-02 | Migration 0021; drafts; builder checks |
| 10B-03 | Provider writes: Google bulk create, Meta create sequence, Pages and pixels, cleanup; simulators |
| 10B-04 | Engine: `campaign.create`, `campaign.go_live`, `campaign.remove_draft_objects`; look-up by reference; linking and first sync |
| 10B-05 | API; roles; audit |
| 10B-06 | Web app: Build campaign, review screen, launch and Go live |
| 10B-07 | Failure, duplicate and concurrency tests; browser test; `PHASE_10B_REPORT.md` with your review checklist |

## 10. Acceptance criteria

1. A ready strategy and an approved creative produce a complete Google Search or Meta Sales campaign. The review screen shows exactly what will be created.
2. Every launch is checked, dry-run by the platform and approved by an owner or admin.
3. Everything is created **paused**; nothing runs until "Go live" is approved.
4. A failed launch leaves nothing running, lists what was created, and can clean it up.
5. A lost answer never creates a second campaign.
6. The new campaign is linked to its strategy and creative and appears under Advertising.
7. All steps are audited, without secrets. All suites pass, with no platform calls in CI.

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Money spent unintentionally | HIGH | Created paused; a separate approved Go live; limits; dry run; switches |
| Half-built Meta campaigns | MEDIUM | Each object paused as it is created; IDs recorded step by step; cleanup action |
| Duplicate campaigns | HIGH | One launch per draft; reference tag; look up before any resend |
| Platform rules (RMF, App Review, special categories) | MEDIUM | Step 0; own and test accounts first; your declaration |

## 12. Rollback

`ACTIONS_ENABLED=false` (or "Pause all changes") stops everything. Migration 0021 is reversible. Phase 10A's changes and the read-only features are unaffected.

## 13. Approval checklist

Approve or change:
- **Q-10B-1 … Q-10B-12**;
- Step 0 (§4.2);
- the data model (§5);
- delivery 10B-01 … 10B-07, with one report at the end of the phase.

No new library is needed.
