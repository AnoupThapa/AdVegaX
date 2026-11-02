# Phase 10B — Progress (Campaign Builder)

Plan: `PHASE_10B_PLAN.md` (approved 2026-10-27, A29, all recommendations Q-10B-1 … Q-10B-12). Built task by task; **one report for the whole phase** (`PHASE_10B_REPORT.md`).

| Task | Status |
|---|---|
| 10B-01 Step 0: live checks on a Google test account and an own Meta ad account | ⏸ Waiting for the test accounts, a Facebook Page, Meta's permissions and network access |
| 10B-02 Migration 0021; drafts; builder checks | ✅ Done |
| 10B-03 Provider writes: Google bulk create, Meta create sequence, Pages and pixels, clean-up; simulators | ✅ Done |
| 10B-04 Engine: `campaign.create`, `campaign.go_live`, `campaign.remove_draft_objects`; look-up by reference; linking and first sync | ✅ Done |
| 10B-05 API; roles; audit | ✅ Done |
| 10B-06 Web app: Build campaign, review screen, launch and Go live | ✅ Done |
| 10B-07 Failure, duplicate and concurrency tests; browser test; `PHASE_10B_REPORT.md` | ✅ Done — Phase 10B awaiting review |

## 10B-01 — Step 0

**Blocked:** needs everything 10A Step 0 needs, plus a Facebook **Page** connected to your business, `pages_show_list` in the change login configuration, and optionally a pixel (plan §2A, §4.2).

## 10B-02 — Drafts and checks

- **Migration 0021** (additive, reversible): `campaign_drafts` (tenant-owned, forced RLS, never deleted); `actions` gains `draft_id`, `campaign_id` becomes optional, the three new change types, and **at most one open change per draft**; `action_settings` gains `landing_domains`.
- **A draft** is made from a ready strategy and its approved creative for one platform and one ad account. It is filled in from the strategy: the daily amount (converted to the account currency), the country of the currency, the product's page on the store and a name with a unique reference (`AVX-XXXXXX`). It can be edited until launch; every edit raises its version and clears the declarations.
- **Builder checks** (`builder/checks.py`), each result recorded: the strategy and creative; keywords (Google: 1–20, Google's length and word limits, allowed characters, no duplicates, none of your prohibited words); targeting (supported countries; Meta ages); the landing page (https, your store's domain or a domain you added, no other port, no user name); the budget (with every Phase 10A limit); Meta's Page and pixel; the declarations; the daily change limit.

## 10B-03 — The platforms' create calls

- **Google:** one all-or-nothing `googleAds:mutate` with temporary ids: the budget, the campaign (**PAUSED**, "no EU political advertising", Maximize conversions or Maximize clicks, Search network only), its countries, one ad group, the keywords and the responsive search ad. `validateOnly` for the platform's test. Finding a campaign by its reference, and removing a failed build, use the same module.
- **Meta:** in order: the image (`adimages`), the campaign (Sales, **PAUSED**, no special ad category), the ad set (purchases with a pixel, else link clicks), the creative and the ad — each **PAUSED**. A stop part-way reports what was made. Pages (`/me/accounts`) and pixels are read for the choices.
- Still only `providers/*/writes.py` changes anything at a platform (static rules).
- **Simulators** for both platforms create, find, switch on and remove, with lost answers and stops part-way.

## 10B-04 — The engine

- **`campaign.create`:** under the draft's lock, the platform is first **searched for the reference**: if the campaign is already there it is recorded, never sent again. Otherwise everything is created paused, read back and checked to be paused; a quick sync is scheduled so the campaign appears under Advertising.
- **A lost answer** is looked up by the reference — never resent.
- **A stop part-way** (Meta) leaves only paused objects, listed on the draft; **`campaign.remove_draft_objects`** removes them after approval.
- **`campaign.go_live`:** Google switches the campaign on; Meta switches the ad, the ad set and the campaign on.
- Approval checks again and refuses when the draft was edited after the request.

## 10B-05 — API, roles, audit

`/campaign-drafts` (create, list, read, edit, archive, check, launch, Go live, clean-up) and the Meta Pages and pixels of an ad account (API_SPECIFICATION §19K). Owners, admins and managers prepare and request; owners and admins approve (with the second-person rule). Every step is in the change history and the audit log, never a token.

## 10B-06 — Web app

- **Strategy → Campaigns:** the campaigns built from it, and **Build campaign** (platform and ad account).
- **The campaign page:** what will be created (the ad, keywords, countries, ages, landing page, budget per day and per month, bidding), the edit form, **Check** (every check and the platform's test) and **Request launch**. After the launch: **Created — paused**, **Request Go live**, or for a stop part-way **Request removal of what was created**.
- **Changes** shows the three new kinds of change, linked to the campaign draft.
- **Settings → Changes to ad accounts:** other domains your landing pages may use.

## 10B-07 — Tests and report

Backend API tests against both simulators (launch, paused, Go live, never twice, lost answers, stops part-way, clean-up, second person, roles, tenants), unit tests of every check and of the requests sent, the browser test (`e2e/builder.spec.ts`) and the report.
