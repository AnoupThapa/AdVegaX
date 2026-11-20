# Phase 9 — Implementation Report (creative engine)

**Date:** 2026-10-26 · **Branch:** `feature/phase-1a` · **Status:** Implemented and tested against the AI simulator — **awaiting product-owner review**. **Step 0 (9-01) is pending:** it needs the Anthropic API key and the platforms' current documentation.
**Plan:** `PHASE_09_PLAN.md` (approved 2026-10-26, A27) · Task by task: `PHASE_09_PROGRESS.md`.

---

## 1. Summary

From a strategy you marked **ready**, AdVegaX drafts the **ad copy** for each of its platforms, and a person approves what may be used:

1. **Make creatives** on the strategy. One AI run writes, per platform, complete ads in the platform's own fields:
   - **Google Ads:** headlines, descriptions and the two display-path words;
   - **Meta:** primary texts, headlines, descriptions and a call-to-action button.

   The AI sees the approved brief (objective, positioning, angles, audiences), the product's **catalogue prices** and its text — sealed as data. It never sees budget amounts, customers, orders or IDs.
2. **AdVegaX checks every line itself**, before and after:
   - the platforms' text limits;
   - no repeated lines;
   - no phone numbers, e-mail or web addresses, or emoji in Google text;
   - no words in capitals (except your brand words) and no "!!" or "??";
   - **no health or medical claims** ("cure", "100% effective", "kills viruses", "TGA approved", … plus your own words);
   - **every price must be one of the product's catalogue prices**;
   - superlatives ("best", "#1") are flagged for you to confirm.

   A draft that breaks a rule is retried once, then refused; nothing is kept.
3. **You review each creative** on its page:
   - a preview of how the ad looks;
   - the checks in plain words;
   - the AI's rationale and notes (advice only).

   You can then:
   - **edit** — this makes a **new version**; older versions never change;
   - **approve** (owner, admin or manager) — refused if any check fails, and flagged wording needs a tick;
   - **reject** with a reason;
   - **archive**.

   One approved version per concept.
4. **Your images** for Meta ads:
   - uploaded to a private library and checked by decoding;
   - re-saved, which removes hidden data such as GPS location;
   - stored under random names, shown only to your organization's members.
5. **Only approved creatives** are offered to the campaign builder (Phase 10B). Nothing is sent to Google or Meta in Phase 9. Every decision is audited, with the version and reason — never the ad text.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 9-01 | ⏸ Step 0 — waits for the API key and the platforms' documentation (§9) |
| 9-02 | Migration **0019**; storage (local folder, S3-compatible); image checks and cleaning |
| 9-03 | Platform specs (Google responsive search ads, Meta); fixed checks; organization rules |
| 9-04 | Creative context; answer schema; prompt `creative_copy` v1; validation |
| 9-05 | API: sets, versions, approve / reject / archive, images, rules; roles; audit |
| 9-06 | Web app: Creatives, previews, edit, decisions, image library, creative rules, "Make creatives" |
| 9-07 | Evaluation set (4 golden, 11 hostile), browser test, this report |

## 3. Acceptance criteria (plan §11)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Creatives drafted from a ready strategy for each of its platforms, within every limit | ✅ | `test_creatives_api.py::test_drafts_come_from_a_ready_strategy…`; G1, G3 (Google only); browser test |
| 2 | A creative failing any fixed check cannot be approved; the checks say what failed | ✅ | `test_approval_needs_every_check_to_pass`; `test_creative_policy.py` (34); page tests |
| 3 | Only authorized people approve or reject; every decision (version, reason) audited | ✅ | `test_roles`, `test_reject_needs_a_reason…`, audit assertions |
| 4 | Edits create new versions; approved versions never change | ✅ | `test_an_edit_makes_a_new_version…`, `test_one_approved_version_per_concept` |
| 5 | Only approved creatives returned to the campaign builder | ✅ | `GET /creatives?status=approved` (`test_one_approved_version_per_concept`) |
| 6 | Images validated by decoding, re-encoded without metadata, stored privately, served only through the API | ✅ | `test_creative_images.py` (16), `test_an_image_is_cleaned_stored_privately…` |
| 7 | No personal data or secret reaches the AI or a log; hostile store text changes nothing | ✅ | `test_creative_evaluation.py`; static rule |
| 8 | All suites pass, with no AI or storage-provider calls in CI | ✅ | §5 |

## 4. Security controls

| Control | Verified by |
|---|---|
| Uploads: size first, type from decoding, pixel limit before decoding, full decode, re-encode (EXIF/GPS and appended data removed), minimum size | `test_creative_images.py` |
| Random storage keys under the organization's prefix, strict key pattern, atomic private writes; provider errors never repeated | `test_creative_images.py` (storage), static rule (keys only from `new_key`) |
| The only multipart route has its own size limit; CSRF and Origin still apply; JSON elsewhere | Middleware; `test_multipart_is_only_accepted_for_uploads`; route sweeps |
| Images only through the API for members (`private` cache, `nosniff`); a foreign image is "not found" | `test_an_image_is_cleaned…` |
| The AI sees the brief, catalogue prices and sealed product text only — no amounts, customers, orders, IDs | `test_no_personal_data_or_amounts_reach_the_copywriter`; static rule |
| Every AI answer validated; the creative domain calls nothing outside | Validation chain; static rule (`.request(`, `httpx`, `boto3`, providers) |
| Tenant isolation | Forced RLS on the four new tables; the route sweep covers the 15 new routes |
| Audit without ad text | `test_approval_needs_every_check_to_pass` |

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, pytest) | **1,857 passed**, coverage 97 % |
| Frontend `npm run check` | **479 passed**, coverage 95 % |
| Browser tests (Playwright + axe) | **15 passed** — the four-platform test now marks a strategy ready, asks for creatives while the planner is off, approves and rejects simulator-drafted creatives, uploads an image, and opens the creative rules; every page passes the accessibility check |

## 6. Database

Migration **0019** (additive, reversible): `creative_sets`, `creatives`, `creative_assets`, `creative_rules`; unique (organization, id) on `campaign_strategies`; `ai_runs.task` allows `creative_copy`. DATABASE_SCHEMA §14B.

## 7. New libraries (approved, A27)

**Pillow** (image decoding and re-encoding), **python-multipart** (uploads), **boto3** (S3-compatible storage; loaded only when `STORAGE_BACKEND=s3`).

## 8. Defects found and fixed

1. Phase 8: a strategy's "last changed" time was not updated by edits, ready or archive — fixed (lists now sort correctly after a change).
2. Catalogue prices were sent with the database's extra decimals ("50.0000") — now in the currency's own decimals.
3. The web app's test helper could not read upload bodies — fixed in the test support.

## 9. Deviations from the plan

1. Images are shown **through the API with your session** (read into a private `blob:` address) rather than through short-lived links: no link exists that could be passed on, and the page's security policy needs no new image source.
2. A drafted answer must pass **every** blocking check in every concept (otherwise it is retried, then refused), rather than keeping the passing concepts — simpler and safer.
3. Phone numbers and web addresses are blocked in **Google** text only (Google's rule); Meta text may contain them.
4. Approving a rejected version is not possible; editing it creates a new draft version that can be approved.
5. Display paths must be one word (letters, digits, hyphens).

## 10. Not verified in this environment — Step 0 (9-01)

1. One drafting run against the configured model with AdVegaX's schema.
2. Meta's limits and call-to-action names against Meta's current Ads Guide and Marketing API reference (Google's were read from Google's help page).
3. The golden set once live.

## 11. Known limitations

| Limitation | Note |
|---|---|
| No AI images or video (Q-9-1) | A later phase |
| No virus scanner for uploads | Decoding and re-saving removes non-picture content; a scanner can be added |
| Storage provider for production not chosen (Q-9-9) | Decided at the production-readiness gate |
| The base prohibited-terms list is a starting point, not legal advice | Your own words can be added; the platforms' own review still applies when campaigns launch |
| English only | As Phase 8 |

## 12. Your review checklist

**A. Decide or confirm (business):**

1. The **prohibited claims list** (Settings → Creative rules shows it): is it right for Eve Zone and Mediflex products? Which words should be added for your markets (Australia, Nepal)?
2. Who approves: **owner, admin or manager** (analysts can draft and edit).
3. **3 concepts per platform**, with 10 Google headlines and 4 descriptions, and 3 Meta primary texts and 3 headlines.
4. Image rules: JPEG, PNG or WebP, at least 600 × 600 pixels, up to 10 MB.

**B. Try it in the app:**

1. Open a strategy, mark it ready, choose **Make creatives** (live after Step 0; in tests the simulator drafts them).
2. On the creatives page: check the previews and the check messages. Edit a headline to add "Call 1300 …" and save — see it blocked. Fix it and approve.
3. Reject one with a reason.
4. **Creatives → Images:** upload a product photo and attach it to a Meta creative (Edit → Image).
5. **Settings → Creative rules:** add a word and see a creative using it blocked at approval.

**C. Set up when you are ready:**

1. The Anthropic API key (as Phase 8) — then I run Step 0 for Phases 8 and 9.
2. At the production-readiness gate: choose where images are stored (AWS S3, Cloudflare R2, Backblaze B2, …).

**D. Documents to read:** this report; `PHASE_09_PROGRESS.md`; API_SPECIFICATION §19I; DATABASE_SCHEMA §14B.

## 13. Next

1. **Your review** of Phase 9 (§12) — and of Phase 8 if not done yet.
2. **Step 0** for Phases 8 and 9 once the key is in place.
3. Then **Phase 10A — the Action Engine** (the single, audited gate for any change at Google or Meta) — its plan is written for your approval first.
