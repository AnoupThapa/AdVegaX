# Phase 9 — Progress (creative engine)

Plan: `PHASE_09_PLAN.md` (approved 2026-10-26, A27, all recommendations Q-9-1 … Q-9-11 and the libraries Pillow, python-multipart, boto3). Built task by task; **one report for the whole phase** (`PHASE_09_REPORT.md`, your instruction of 2026-10-26).

| Task | Status |
|---|---|
| 9-01 Step 0: live checks (model, platform limits, Meta's call-to-action names) | ⏸ Waiting for the Anthropic API key and access to the platforms' documentation |
| 9-02 Migration 0019; storage interface and drivers; image upload pipeline | ✅ Done |
| 9-03 Platform specs, fixed policy checks, creative rules | ✅ Done |
| 9-04 Creative generation: context, schema, prompt `creative_copy` v1, validation | ✅ Done |
| 9-05 Workflow and API: sets, versions, approve / reject / archive, images, rules; audit | ✅ Done |
| 9-06 Web app: Creatives pages, previews, image library, creative rules, "Make creatives" | ✅ Done |
| 9-07 Evaluation set, browser test, `PHASE_09_REPORT.md` | ✅ Done — Phase 9 awaiting review |

## 9-01 — Step 0

**Blocked:** needs the Anthropic API key (as Phase 8) for one live drafting run, and the platforms' current documentation for the Meta limits and call-to-action names, which were not readable from this environment (Google's limits were read from Google's help page).

## 9-02 — Migration 0019, storage, images

- **Migration 0019** (additive, reversible): `creative_sets`, `creatives` (versions; at most one approved version per concept), `creative_assets`, `creative_rules` — all tenant-owned with forced RLS, read / add / change only, never deleted. `campaign_strategies` gains unique (organization, id); `ai_runs.task` also allows `creative_copy`.
- **Storage** (`app/core/storage`): a local folder (development, tests, one server) and an S3-compatible driver (boto3), tested against an in-process fake. Keys are random, under the organization's prefix, and checked against a strict pattern; files are written atomically with private permissions. Store errors never repeat the provider's text.
- **Images** (`creative/images.py`):
  - the size is checked first;
  - the type comes from decoding (JPEG, PNG, WebP only), not from the file name or what the browser says;
  - the pixel count is checked before decoding, so a "decompression bomb" is refused;
  - the picture is fully decoded (a broken file is refused), turned the right way up, and re-saved, which removes EXIF/GPS data, comments and anything appended (tested with a script appended to a picture);
  - the smallest side must be at least 600 pixels.

## 9-03 — Platform specs and fixed checks

- **Google responsive search ads:** 3–15 headlines of up to 30 characters; 2–4 descriptions of up to 90; two display paths of up to 15, one word each. Wide (CJK) characters count as 2.
- **Meta:** up to 5 primary texts (125), headlines (40) and descriptions (30), and a call to action from a fixed list.
- **Checks** (`creative/policy.py`):
  - shape and limits;
  - no duplicate lines;
  - Google only: no phone numbers, e-mail or web addresses, no emoji;
  - no words in capitals (except the organization's allowed words) and no "!!" or "??";
  - prohibited terms — AdVegaX's base list of health and medical claims (e.g. "cure", "100% effective", "kills viruses", "TGA approved") plus the organization's own, matched as whole words;
  - every stated price must be one of the catalogue prices;
  - superlatives are **flagged** (not blocked).

## 9-04 — Generation

- **Context** (`creative/context.py`): built from a **ready** strategy only. It contains:
  - the approved brief (objective, positioning, angles; per platform, the campaign type and audience) — never budget amounts;
  - the catalogue prices in the store's currency;
  - the product's text.

  Both the brief and the product text are sealed as data blocks that cannot be closed from inside.
- **Answer schema:** only the strategy's platforms, each a list of complete concepts, within structured-output limits; no money or link fields.
- **Validation:** every concept must pass every blocking check; each platform must have 1 to `CREATIVE_CONCEPTS` concepts. A failure is retried once with the reasons, then rejected; nothing is kept.
- **Prompt `creative_copy` v1** (versioned, hashed). It gives the limits and rules, says no health claims and no invented prices, and treats the brief and product text as data.

## 9-05 — Workflow and API (API_SPECIFICATION §19I)

- **Draft:** one AI run per set, counted in the shared daily limit. Each concept is kept as version 1 with its check results.
- **Edit:** only the newest version, and never one that is archived. An edit creates a new draft version; older versions, approved or not, never change.
- **Approve** (owner, admin, manager): the checks run again with today's rules and catalogue prices. Approval is refused if any blocking check fails; flagged wording needs a confirmation. The concept's previously approved version is archived.
- **Reject:** needs a reason. **Archive:** the creative is kept.
- **Images:**
  - upload through the only multipart route, with its own size limit (CSRF and Origin still apply);
  - read back only through the API, by members;
  - archived, never deleted;
  - attached to Meta creatives only.
- **Rules:** owners and admins.
- **Audit:** every change — versions, statuses and reasons, never the ad text.
- `GET /creatives?status=approved` is what the campaign builder (Phase 10B) will use.

## 9-06 — Web app

- **Creatives** in the menu.
- **A set page:** for each concept, a preview of the ad:
  - Google: the headlines and display path as an ad shows them, with all lines listed;
  - Meta: the primary text, image, headline, description and call-to-action button.

  It also shows the checks in plain words (what to fix, what to check), the rationale and the AI's notes (advice only), and the version and status. From there you can:
  - edit — one line per line, choose the image, save as a new version;
  - approve, after ticking a confirmation for flagged wording;
  - reject with a reason;
  - archive.
- **Image library:** upload, archive, and see why a file was refused (e.g. "too small: at least 600 × 600 pixels").
- **On a ready strategy:** "Make creatives", with progress and plain-language reasons when the AI's answer was rejected.
- **Settings → Creative rules:** your prohibited words and allowed capitals (owners and admins edit).
- **How images are shown:** they are read through the API with your session and shown from a private `blob:` address, so the page's security policy needs no new image source and no image is ever on a public link.

## 9-07 — Evaluation set, browser test, report

- **Evaluation set** (`tests/api/test_creative_evaluation.py`):
  - **golden:** a healthcare product on both platforms; a price in the title used only as data; a Google-only strategy; several catalogue prices;
  - **hostile:** too long, phone number, web address, health claim, wrong price, shouting, a money field, a platform not in the strategy, an unknown call to action, no concepts, an instruction hidden in the title;
  - no personal data or budget amounts reach the copywriter.
- **Browser test:** the four-platform organization marks a strategy ready, asks for creatives while the planner is off (a plain "not available" message), then opens a set drafted with the simulator. It approves the Google creative, rejects the Meta one with a reason, uploads an image to the library and opens the creative rules in Settings — with accessibility checks on every page.
- `PHASE_09_REPORT.md` with your review checklist.

**Tests (whole phase):** backend `make check` **1,857 passed** (coverage 97 %), frontend `npm run check` **479 passed**, browser tests **15 passed**. The browser helpers that sign in several times a minute as the same person run with a higher sign-in limit for themselves only (the app's own limit is unchanged).
