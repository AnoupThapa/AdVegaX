# Phase 9 — Creative engine: Implementation Plan

**Status:** ✅ **Approved by the product owner (2026-10-26, A27: "Approve all") with all §2 recommendations (Q-9-1 … Q-9-11; settles Q12 for Phase 9) and the libraries Pillow, python-multipart and boto3.** Implementation authorized for Phase 9 only; one report at the end of the phase. **Implemented 2026-10-26 — see `PHASE_09_REPORT.md`.** · **Date:** 2026-10-26

> **Live data:** like Phase 8, Phase 9 is built and tested against the **AI simulator** (no AI calls in CI). Step 0 (9-01) makes a few real calls once your Anthropic API key is in place, and checks the platforms' current text limits.

**Depends on:** Phase 8 (strategies, the AI platform). · **Followed by:** Phase 10B (campaign builder), which may only use **approved** creatives.
**Governing documents:** MASTER_SPECIFICATION §8 (AI philosophy), D16 (human approval), A12 (AI data boundary); DISCOVERY_REPORT Q12 (creative scope), Q15 (languages); `phases/PHASE_09_CREATIVE_ENGINE.md` (outline); API_SPECIFICATION §10, §12; DATABASE_SCHEMA `creatives`.

---

## 1. Objective

From a strategy you have marked **ready**, AdVegaX drafts the **ad copy** for each platform in it, and you approve the versions you want to use:

- **Google Ads:** responsive search ad text — headlines, descriptions and the two display-path fields.
- **Meta:** primary texts, headlines, descriptions and a call-to-action button.
- **Your own images** (uploaded, checked, cleaned) can be attached to a Meta creative.

Every creative:

- follows the platform's **text limits**, checked by AdVegaX, not trusted from the AI;
- passes **fixed policy checks** before it can be approved (no prohibited claims, no phone numbers in Google text, no shouting, prices that match your catalogue, …);
- is **versioned**: an edit makes a new version, older ones are kept;
- has a **rationale** and **compliance notes**, which are advice only — the fixed checks decide;
- is **approved or rejected by a person**, with the reason, and every decision is audited.

**Only approved creatives can be chosen by the campaign builder** (exit criterion). Nothing is sent to Google or Meta in Phase 9.

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all of them at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-9-1** (Q12) | What does the creative engine make? | **Ad copy only, plus images you upload.** No AI-generated images or video in Phase 9. | Copy is where AI is reliable and checkable; generated images bring rights, likeness and quality risks — a later phase. |
| **Q-9-2** | Where do creatives start from? | From a strategy marked **ready** (Phase 8): its platforms, campaign types, angles and audience, plus the same AdVegaX figures and the product's own text (still **untrusted**, sealed as in Phase 8). | Creatives follow a plan you already approved. |
| **Q-9-3** | How many drafts? | Per platform in the strategy, **3 concepts** (one per angle where possible), each a complete ad: Google — 10 headlines and 4 descriptions; Meta — 3 primary texts, 3 headlines, 2 descriptions and a call to action. Numbers are settings. | Enough variety to choose from and to let the platforms rotate text, without flooding you. |
| **Q-9-4** | Text limits | The platforms' published limits, as AdVegaX settings and checked on every save: **Google responsive search ads** 3–15 headlines of ≤ 30 characters, 2–4 descriptions of ≤ 90, two paths of ≤ 15 (wide CJK characters count as 2) — from Google's help page; **Meta** up to 5 primary texts, 5 headlines and 5 descriptions, using Meta's **recommended** lengths as AdVegaX's limits (primary text ≤ 125, headline ≤ 40, description ≤ 30) so text is not cut off, and the call to action from a fixed list (Shop now, Learn more, Order now, Get quote, Contact us, Sign up). Step 0 re-checks the numbers against the platforms' current documentation. | Text that is too long is rejected by Google, or cut off by Meta. |
| **Q-9-5** | Fixed policy checks (before approval) | Deterministic, explainable, no AI: lengths and counts; no duplicate lines; no phone numbers, e-mail addresses or web addresses in the text (Google); no emoji in Google text; no words in ALL CAPS (except short brand words you list) and no "!!"/"??"; **prohibited terms** — an AdVegaX base list for health and medical claims (e.g. "cure", "100% effective", "guaranteed protection", "kills COVID"), relevant to healthcare and PPE products, plus **your own list** per organization; **prices** — any price in the text must equal one of the product's catalogue prices; a superlative ("best", "#1", "cheapest") is flagged for your attention but not blocked. | Platforms reject or limit ads for these; health claims carry legal risk (e.g. Australia's TGA advertising rules). The AI's own "compliance notes" are only advice. |
| **Q-9-6** | Who approves? | Drafting and editing: everyone but viewers (as strategies). **Approve / reject: owner, admin or manager.** A rejection needs a reason. Approving needs every fixed check to pass; a flag (superlative) needs a tick "I have checked this". | A person with authority signs off what goes public (D16). |
| **Q-9-7** | Versions | An edit never changes an approved creative: it creates a **new draft version**; the approved one stays approved until you approve the new one or archive it. Versions are kept, never deleted. | You can always see what was approved and when. |
| **Q-9-8** | Images you upload | JPEG, PNG or WebP, up to **10 MB** and at least 600 × 600 pixels (settings). AdVegaX **opens and re-saves every image** (which removes hidden data such as GPS location and anything that is not a picture), never trusts the file name or type you send, and stores it under a random name. Images are **private to your organization** and shown through short-lived links. No virus scanner in v1 (re-saving the picture removes non-image content); a scanner can be added later. Needs two new libraries: **Pillow** (images) and **python-multipart** (uploads). | Uploads are the riskiest input: decoding and re-encoding is the strongest simple defence. |
| **Q-9-9** | Where are images stored? | Behind an AdVegaX **storage interface**: a **local folder** for development and tests now, and an **S3-compatible** store (AWS S3, Cloudflare R2, Backblaze B2 — your choice at the production-readiness gate) through **boto3**, tested against an in-process fake. | Keeps the provider your decision later; nothing is locked in. |
| **Q-9-10** | AI use | One creative set (all platforms of a strategy) = **one AI run**, counted in the same daily limit as strategies (20 a day by default), one retry, 60-second limit. | One predictable budget for AI use. |
| **Q-9-11** | Language | **English**, as Phase 8 (Q-8-9). | One language to evaluate well first. |

## 2A. What you need to set up

1. The **Anthropic API key** from Phase 8 (for Step 0 and real use).
2. Optionally, **your own prohibited or brand words** (Settings → Creative rules) — you can add them later.
3. At the production-readiness gate: the **storage provider** for images (Q-9-9).

## 3. Scope

| Area | In Phase 9 |
|---|---|
| Creative specs | `app/domains/creative/specs.py`: per platform and format, the fields, counts and limits (settings), character counting with wide characters |
| Policy checks | `app/domains/creative/policy.py`: the fixed checks of Q-9-5; base prohibited-terms list; per-organization terms |
| Generation | Prompt `creative_copy` v1; answer schema per platform (structured outputs, no money, no URLs); validation chain (shape → existence → specs → policy); one run per set |
| Workflow | `creative_sets` and `creatives` (versions): generate, read, edit (new version), approve, reject, archive; audit |
| Assets | `creative_assets`: upload (multipart), validate, re-encode, store; list; archive; attach to a Meta creative; short-lived signed links |
| Storage | `app/core/storage/`: interface, local driver, S3-compatible driver (boto3) |
| API | `POST /ai/creative-sets` (generate from a strategy), `GET /creative-sets[/{id}]`, `GET/PATCH /creatives/{id}`, `POST /creatives/{id}/approve | reject | archive`, `GET /creatives?status=approved` (what the builder may use), `POST/GET /creative-assets`, `GET /creative-assets/{id}/content`, `GET/PUT /creative-rules` |
| Web app | From a ready strategy: **Make creatives**; a Creatives page per strategy with a **preview** per platform (how the text roughly appears), the checks and their results, edit, approve / reject with reason, versions; an image library; Settings → Creative rules |
| Data | Migration **0019** |

## 3A. Non-goals

- AI images, video, or editing your images (cropping, text on images).
- Sending anything to Google or Meta (Phase 10A/10B); the platforms' own policy review.
- Performance-based creative recommendations (Phase 11).
- Languages other than English.

## 4. Facts and Step 0

### 4.1 Facts (checked 2026-10-26)

1. **Google responsive search ads:** at least 3 and up to 15 headlines of up to 30 characters; at least 2 and up to 4 descriptions of up to 90 characters; display-path fields of up to 15 characters; double-width characters (Chinese, Japanese, Korean) count as 2 — Google Ads Help, "About responsive search ads".
2. **Meta:** Meta's Ads Guide gives **recommended** lengths (primary text about 125 characters, headline about 40, description about 25–30) and allows several text options per ad. Meta's own pages were not readable from this environment; the figures come from a third-party summary of the Ads Guide — **Step 0 confirms them** against Meta's current guide and the Marketing API's call-to-action list.

### 4.2 Step 0 — live checks (task 9-01)

1. The configured model answers one creative request with AdVegaX's schema; the answer passes the checks.
2. The Google and Meta limits and Meta's call-to-action names against their current documentation (Meta's pages, and the Marketing API reference).
3. The golden evaluation set (§9) once live; a hostile product title does not change the behaviour.

## 5. Proposed structure

```
app/core/storage/            interface, local driver, S3-compatible driver
app/domains/creative/        specs, policy, assets (validation, re-encoding), context, schema,
                             prompt, validation, service, router
frontend/features/creatives/ Creatives page, preview, image library, creative rules
tests/storage_fake.py        in-process S3-compatible fake
```

## 6. Data model (migration 0019)

- **`creative_sets`** (tenant-owned, forced RLS): organization, strategy (composite FK), AI run, created by, created.
- **`creatives`** (tenant-owned, forced RLS): organization, set, platform, format (`google_rsa` | `meta_single`), concept (angle), **version** and the version it replaces, status (`draft` | `approved` | `rejected` | `archived`), content (JSON: the texts), rationale, compliance notes, check results (JSON), asset (Meta, optional), decided by / at, decision reason, created by, created. One approved version per concept at a time.
- **`creative_assets`** (tenant-owned, forced RLS): organization, storage key (random), content type (as re-encoded), width, height, bytes, SHA-256, original name (shown only, never used as a path), status (`active` | `archived`), uploaded by, created.
- **`creative_rules`** (tenant-owned, forced RLS): organization, prohibited terms, allowed capitalised words, updated by / at.

## 7. API

As §3. Errors: the Phase 8 AI errors (`AI_LIMIT_REACHED`, `AI_UNAVAILABLE`, `AI_ANSWER_REJECTED`); `STRATEGY_NOT_READY` (only ready strategies make creatives); `CREATIVE_CHECKS_FAILED` (approve refused, with each failed check); `CREATIVE_NOT_EDITABLE` (archived or replaced); `ASSET_INVALID` (type, size, dimensions, not an image) and `PAYLOAD_TOO_LARGE`.

## 8. Security and privacy

- The AI sees the strategy and AdVegaX's figures only (Phase 8 boundary, A12); store text sealed as untrusted; no tools; every answer validated.
- Uploads: size limit before reading the whole body; the type decided by decoding, not by the name or header; decompression-bomb limit (maximum pixels); re-encoded without metadata; random storage names; per-organization prefixes; links signed and short-lived; no public bucket.
- Storage credentials (production) in settings only, never logged.
- Tenant isolation: RLS on the four tables; route sweeps; an asset or creative of another organization is "not found".
- Approval is a person's decision, audited with the version approved; only approved creatives are offered to Phase 10B.

## 9. Testing

- Specs and policy: every limit and check, wide characters, prices against the catalogue, prohibited and organization terms.
- Uploads: valid images; a script renamed to `.png`; a huge image ("decompression bomb"); metadata (GPS) removed after re-encoding; size and dimension limits.
- Storage: local driver; S3-compatible driver against the fake.
- **Evaluation set** (against the simulator): golden — a healthcare product, a product with a price in its title, a strategy with both platforms, a Google-only strategy; hostile — too-long lines, a phone number or URL in a headline, a health claim, a wrong price, a hidden instruction in the product title, money amounts, platforms not in the strategy.
- API sweeps; page tests; one browser test with accessibility checks (make creatives from a ready strategy, edit, approve, reject, upload an image).

## 10. Tasks (one at a time; one report for the whole phase)

| Task | Content |
|---|---|
| 9-01 | Step 0 (§4.2) — waits for your API key |
| 9-02 | Migration 0019; storage interface and drivers; asset upload pipeline |
| 9-03 | Platform specs and fixed policy checks; creative rules |
| 9-04 | Creative generation: context, schema, prompt `creative_copy` v1, validation, task |
| 9-05 | Workflow and API: sets, versions, approve / reject / archive, assets, rules; audit |
| 9-06 | Web app: Creatives page with previews, image library, creative rules |
| 9-07 | Evaluation set, browser test, `PHASE_09_REPORT.md` with your review checklist |

## 11. Acceptance criteria

1. From a ready strategy, creatives are drafted for each of its platforms, within every text limit.
2. A creative that fails any fixed check cannot be approved; the checks say what failed in plain words.
3. Only a person with authority approves or rejects; every decision (with the version and reason) is in the audit log.
4. Edits create new versions; approved versions never change.
5. Only approved creatives are returned to the campaign builder.
6. Uploaded images are validated by decoding, re-encoded without metadata, stored privately, and served only through short-lived links.
7. No personal data or secret reaches the AI or a log; hostile store text does not change the rules.
8. All suites pass, with no AI or storage-provider calls in CI.

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Health or product claims that break advertising rules | HIGH (healthcare and PPE) | Prohibited-terms list, prices checked, human approval, the platforms' own review later |
| Malicious or oversized uploads | MEDIUM | Size and pixel limits, decode and re-encode, random names, private storage |
| Prompt injection through product text | MEDIUM | Sealed untrusted text, no tools, all output validated, hostile tests |
| Platform limits change | LOW | Limits are settings; Step 0; Phase 10B validates again before launch |
| AI cost | LOW | One run per set, shared daily limit |

## 13. Rollback

Phase 9 adds tables, an upload route and pages. Migration 0019 is reversible. Turning `AI_ENABLED` off stops drafting; approved creatives and images stay readable.

## 14. Approval checklist

Approve or change **Q-9-1 … Q-9-11**, the two new libraries (**Pillow**, **python-multipart**) and **boto3** for S3-compatible storage (Q-9-8, Q-9-9), the Step 0 (§4.2), the data model (§6) and delivery 9-01 … 9-07 with **one report at the end of the phase** (your instruction of 2026-10-26).
