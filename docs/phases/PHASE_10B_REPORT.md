# Phase 10B — Implementation Report (Campaign Builder)

**Status:** Implemented — awaiting your review. Step 0 (live checks, 10B-01) waits for accounts and permissions.
**Plan:** `PHASE_10B_PLAN.md`, approved 2026-10-27 (A29, all recommendations).
**Progress log:** `PHASE_10B_PROGRESS.md`.

## 1. Summary

A strategy marked ready, with an approved creative, now becomes a real campaign:

- **Google Ads:** a Search campaign with one ad group, your keywords and the approved responsive search ad.
- **Meta:** a Sales campaign with one ad set and the approved single-image ad, run as the Facebook Page you choose, optimized for purchases with your pixel or for link clicks without one.

You review exactly what will be created. AdVegaX checks it and the platform tests it. Then it goes through the Phase 10A Action Engine:

1. **Create (paused)** — approved by an owner or admin. Everything is created **paused**.
2. **Go live** — a separate change, approved again.

Nothing is spent until step 2 is approved. Every campaign carries a reference (`AVX-XXXXXX`) in its name. The platform is searched for that reference before sending and after a lost answer, so **a campaign is never created twice**. If Meta stops part-way, only paused objects remain; they are listed and can be removed with one approved change.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 10B-01 | ⏸ Step 0 — waiting (§10) |
| 10B-02 | Migration 0021; campaign drafts filled in from the strategy; the builder checks |
| 10B-03 | Google one-request create (`googleAds:mutate`), Meta create sequence, Pages and pixels, find by reference, Go live, clean-up; both simulators extended |
| 10B-04 | Three new Action Engine changes; look-up by reference; read back paused; link and quick sync |
| 10B-05 | `/campaign-drafts` API (§19K), Meta Pages and pixels, roles, audit |
| 10B-06 | Strategy → Campaigns, Build campaign, the campaign page (review, edit, Check, Request launch, Go live, clean-up), landing domains in Settings |
| 10B-07 | Tests (§5), browser test, this report |

## 3. Acceptance criteria (plan §10)

| # | Criterion | Result |
|---|---|---|
| 1 | A ready strategy and an approved creative produce a complete Google Search or Meta Sales campaign; the review shows exactly what will be created | ✅ (simulators) |
| 2 | Every launch is checked, tested by the platform and approved by an owner or admin | ✅ |
| 3 | Everything is created paused; nothing runs until Go live is approved | ✅ — read back and checked paused |
| 4 | A failed launch leaves nothing running, lists what was created and can clean it up | ✅ (Meta stop part-way tests) |
| 5 | A lost answer never creates a second campaign | ✅ — looked up by the reference |
| 6 | The new campaign is linked to its strategy and creative and appears under Advertising | ✅ — via the draft; a quick sync is scheduled (see §9.2) |
| 7 | Every step audited without secrets; all suites pass with no platform calls in CI | ✅ (§5) |

## 4. Security controls

- **Money:** created paused; Go live is a second approved change; every Phase 10A limit (platform minimum, your maximum, daily changes per account); the installation switch and "Pause all changes" apply.
- **Never twice:** one open change per draft (database index) and a lock per draft; the reference is searched before any create and after any lost answer.
- **Landing pages:** https only, your store's domain (or one you added), port 443 only, no user name or password in the address.
- **Writes:** only `providers/google_ads/writes.py` and `providers/meta_ads/writes.py` change anything at a platform; only the engine calls them (static rules, extended).
- **Tenants:** drafts are tenant-owned with forced RLS; the cross-tenant tests include every new route.
- **No secrets:** tokens never appear in drafts, changes, audit, errors or pages (checked in the browser test).

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, static rules, pytest) | ✅ 2,011 passed, coverage 95.5 %. Two settings tests failed in the first run only because this machine's helper script raised the sign-in limits for the browser tests; rerun with the normal settings, both pass |
| Frontend `npm run check` (types, lint, format, Vitest) | ✅ 534 passed (branch coverage 85.1 %) |
| Browser (Playwright + accessibility) | ✅ 17 passed (new: `builder.spec.ts`) |

New: `tests/api/test_builder_api.py` (drafts, every check, launch, Go live, never twice, lost answers, stop part-way and clean-up, second person, roles), `tests/unit/test_builder_checks.py` (every check and the exact requests), `tests/api/test_e2e_builder_seed.py`, `frontend/tests/features/builder.test.tsx`, `frontend/e2e/builder.spec.ts`. No call reaches Google, Meta or a bank.

## 6. Database

Migration **0021** (additive, reversible): `campaign_drafts`; `actions.draft_id`, `actions.campaign_id` optional, three new change types, one open change per draft; `action_settings.landing_domains`. DATABASE_SCHEMA §14D.

## 7. New libraries

None.

## 8. Defects found and fixed

- A relaunch whose platform test saw the first campaign's name failed the test; the "never twice" test now creates the campaign after approval, as it happens in practice.
- A static rule matched the new router's `go_live`; the rule was narrowed to the provider modules.
- The browser test found the page title checked before it followed a client-side navigation; the test now waits for the title.
- Two failure reasons (`build_incomplete`, `platform_unavailable`) had no plain-words text in the web app; added.

## 9. Deviations from the plan

1. **Landing domains setting.** Shopify stores often answer on `*.myshopify.com` while the shop uses its own domain. The landing page may use the store's domain, its subdomains, its site address, **or a domain you add** in Settings → Changes to ad accounts (up to 10).
2. **No `ad_campaigns.draft_id` column.** The link from a draft to its campaign under Advertising is found from the platform ids the draft recorded. Nothing is lost; one column fewer.
3. **Meta platform test checks the campaign object only.** Meta's `validate_only` cannot test an ad set or ad whose campaign does not exist yet; the full sequence is checked by AdVegaX and then created paused.
4. **One match type for all keywords in the web app.** The API accepts a match type per keyword; the screen offers one for the list (phrase by default).
5. **Fixed country list:** Australia, New Zealand, Nepal, India, United States, United Kingdom, Canada, Ireland, Singapore. More can be added.
6. **Meta Pages and pixels** are at `/ad-accounts/{id}/meta-pages` and `…/meta-pixels` (the plan said `/meta/pages`), so they belong to the chosen ad account.

## 10. Not verified in this environment — Step 0 (10B-01)

1. Google test account: a Search campaign with `validateOnly`, then for real; paused, budget and ad correct.
2. Meta, your own account: image, campaign, ad set, creative, ad, all paused; then Go live and pause again.
3. A forced stop in the middle of a Meta launch leaves only paused objects; clean-up removes them.
4. Google's **Required Minimum Functionality** list, before other businesses' accounts.

## 11. Known limitations

- Performance Max, Shopping and Advantage+ shopping campaigns come later (plan non-goals).
- No AI keyword suggestions yet; you type the keywords.
- One ad group / ad set and one ad per campaign.
- Removing a campaign after it went live is done at the platform (or pause it through Changes).

## 12. Your review checklist

**A. Decide or confirm (business):**

1. The deviations in §9, especially **extra landing domains** (1) and the **Meta test of the campaign only** (3).
2. The supported **countries** (§9.5): any to add?
3. The default **name** of a campaign: "{product} - Search - AVX-XXXXXX" (or "- Sales -" for Meta). It can be edited before launch; the reference must stay.
4. **Bidding:** Google Maximize conversions when the account recorded conversions in the last 30 days, else Maximize clicks; Meta purchases with a pixel, else link clicks.

**B. Try it in the app** (after Step 0, or on a test account):

1. **Strategies →** a ready strategy with an approved creative → **Campaigns → Build campaign** (choose the platform and ad account).
2. On the campaign page: add keywords (Google), or choose the **Facebook Page** and optionally a **pixel** (Meta). Tick the declarations → **Save**.
3. **Check:** see each check and the platform's test. Try a landing page on another domain and see the reason.
4. **Request launch →** open the change → **Approve and send**. The campaign shows **Created — paused**; find it under **Advertising**, paused.
5. **Request Go live →** approve it. The campaign runs.
6. Check at Google Ads / Meta Ads Manager that the campaign, budget and ad match, and that it was paused until step 5.

**C. Set up when you are ready:**

1. Everything in Phase 10A §12 C (Google test manager account; Meta change permission; `ACTIONS_ENABLED=true`).
2. **Meta:** a Facebook **Page** connected to your business; add **`pages_show_list`** to the change login configuration; optionally a **pixel**.
3. **Google:** review the **Required Minimum Functionality** list before offering campaign creation to other businesses.

**D. Documents to read:**

- this report;
- `PHASE_10B_PROGRESS.md`;
- API_SPECIFICATION §19K;
- DATABASE_SCHEMA §14D.

## 13. Next

1. **Your review** of Phase 10B (§12), and of Phases 8, 9 and 10A if not done yet.
2. **Step 0** for Phases 8 – 10B once keys and accounts are in place.
3. Then the next phase on the roadmap (Phase 11 — the optimization engine: AI recommendations, approved, carried out through the Action Engine). Its plan comes to you for approval first.
