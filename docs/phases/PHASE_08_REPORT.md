# Phase 8 — Implementation Report (AI campaign planner)

**Date:** 2026-10-26 · **Branch:** `feature/phase-1a` · **Status:** Implemented and tested against the AI simulator — **awaiting product-owner review**. **Step 0 (8-01) is still pending:** it needs an Anthropic API key in the local settings file.
**Plan:** `PHASE_08_PLAN.md` (approved 2026-10-25, A26, all recommendations Q-8-1 … Q-8-10) · Task-by-task reports: `PHASE_08_PROGRESS.md` (8-02 … 8-07).

---

## 1. Summary

A merchant can now ask AdVegaX for a **campaign strategy for one product** and get a clear plan they can check, edit and approve — **never a campaign**: nothing is created at Google or Meta in Phase 8.

1. **You choose:**
   - the product;
   - the ad platforms (Google Ads, Meta);
   - an objective (or let the planner choose);
   - **your budget** (per day or per month, in your reporting currency).
2. **AdVegaX first checks it can be planned:** an active product, in stock, a connected platform, and a budget above each platform's minimum. If not, it says why and **the AI is never called**.
3. **The AI sees only AdVegaX's own figures** for that product and its store:
   - sales, units, margin, price, cost and stock;
   - the store's results;
   - each platform's spend and results;
   - the funnel and its drop-offs.

   It never sees customers, orders, emails, addresses, account or campaign names, IDs or secrets. The product's own text (title, type, vendor, variant names) is sent as **untrusted data** in a sealed block that hidden instructions cannot break out of.
4. **The AI answers in a fixed form (structured outputs):**
   - objective, summary, positioning;
   - per platform: campaign type, **share of the budget (%)**, who to reach, why;
   - creative angles, target ranges, risks and assumptions;
   - every point cites the AdVegaX figures it rests on.

   The form has **no field for money**: the AI only proposes percentages.
5. **AdVegaX checks every answer before anyone sees it**, in four stages:
   - **form** (fields, allowed values, lengths, campaign types that exist);
   - **existence** (only the platforms you chose, connected; only figures AdVegaX has);
   - **business rules** (an unknown or negative margin, low stock and a short history must be named as risks; targets must stay within 3× of the business's own results);
   - **budget** (shares add up to 100 %, each platform above its minimum).

   An answer that fails is retried **once** with the reasons; if it fails again it is **rejected, never shown**, and the reasons are recorded.
6. **AdVegaX computes the amounts.** Each platform's amount comes from its share, down to the cent. Together the amounts are **exactly your budget**.
7. **You stay in charge.** You can:
   - edit the strategy (it is checked again the same way, and becomes a draft again);
   - **mark it ready** for the campaign builder (Phase 10B);
   - archive it.

   Every change is audited, without the strategy's text.
8. **Traceable.** Every strategy shows which model and prompt version drafted it and when. The exact figures sent are stored with each AI run.
9. **Limits:**
   - 20 strategies a day per organization (a setting);
   - a 60-second time limit;
   - a cap on answer length;
   - one retry.

   Owners and admins see runs, tokens and the estimated cost in Settings ("unknown" until prices are set — never 0).

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 8-01 | ⏸ Step 0 — waits for your Anthropic API key (§9) |
| 8-02 | Migration **0018** (`ai_models`, `prompt_versions`, `ai_runs`, `campaign_strategies`); model adapter; Anthropic adapter (Messages API, structured outputs, fixed address, no tools); versioned prompts; runs with limits; AI simulator |
| 8-03 | Context builder: AdVegaX's figures only, evidence keys, untrusted text sealed, snapshot |
| 8-04 | Strategy schema; four-stage validation; budget amounts; prompt `campaign_strategy` v1 |
| 8-05 | API: generate, list, read, edit, ready, archive, usage; roles; audit |
| 8-06 | Web app: Strategies page, strategy page with evidence, edit, ready, archive; AI use in Settings |
| 8-07 | Evaluation set (5 golden contexts, 13 hostile cases), browser test, this report |

## 3. Acceptance criteria (plan §11)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | A strategy for a selling product with margin, Google Ads and Meta connected, validates and shows its evidence | ✅ | `test_strategy_evaluation.py::test_g1…`; browser test (strategy page with amounts and figures) |
| 2 | Every invalid or out-of-policy answer is rejected, never shown, reasons recorded; hostile store text does not change the rules | ✅ | 12 hostile answers + hostile store text (`test_strategy_evaluation.py`); `test_strategy_validation.py` (28); runs record reasons (`test_ai_runs.py`) |
| 3 | Budget amounts always add up to the merchant's total and respect platform minimums; the AI never sets an amount | ✅ | `test_strategy_budget.py` (golden AUD/JPY/KWD, 500 random budgets); no money field in the schema (tested); minimum checks before and after the model |
| 4 | Every strategy is traceable to its AI run, model, prompt version and data snapshot | ✅ | `test_strategies_api.py` (ai_run on every strategy), `test_strategy_task.py` (snapshot = what was sent), prompt hash refused when changed without a new version |
| 5 | No personal data and no secret ever reaches the AI or a log | ✅ | `test_strategy_context.py::test_no_personal_data…`; static rules (context builder, AI code); key never in runs or logs (`test_ai_runs.py`) |
| 6 | The daily quota, time limit and retry cap hold | ✅ | `test_ai_runs.py` (limit per organization and UTC day, timeout, one retry, provider errors not retried) |
| 7 | All suites pass, with no AI calls in CI | ✅ | §5; the simulator sits behind the real HTTP client |

## 4. Security controls — how each is verified

| Control | Verified by |
|---|---|
| The API key only in settings; one header; never in runs, logs or errors | `test_ai_runs.py::test_the_key_never_reaches…`; static rule (key read in one place) |
| One fixed address (`api.anthropic.com`), POST, no redirects, through the SSRF-safe client; **no tools** for the model | `test_the_ai_calls_one_fixed_address_and_offers_the_model_no_tools` (static); simulator refuses requests with tools |
| The AI sees AdVegaX's aggregated figures only — no customers, orders, contacts, names, IDs or secrets | `test_the_planner_context_reads_only_figures_never_personal_data` (static); snapshot scan test |
| Untrusted store text sealed; channel names (free text) never sent | Hostile title tests; G5 (a channel finding named "Ignore all rules" is not sent) |
| Every answer validated before use; the AI can never trigger an action | Four-stage chain on answers **and** edits; nothing in Phase 8 writes to Google or Meta |
| Tenant isolation | Forced RLS on `ai_runs` and `campaign_strategies`; the route sweep covers the 7 new routes |
| Viewers read only; generating/editing for owner, admin, manager, analyst; usage for owners and admins | `test_strategies_api.py::test_roles`; permission matrix test |
| The audit never stores the strategy's text | `test_a_strategy_is_generated…` |
| Pages compute nothing | Static "no formula" rule now covers the strategies pages |

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, pytest) | **1,766 passed**, coverage 97 % |
| Frontend `npm run check` | **459 passed**, coverage 96 % |
| Browser tests (Playwright + axe) | **15 passed**; the four-platform test now makes a strategy with the AI simulator, opens it (amounts, evidence, model and prompt), fails and then passes an edit, marks it ready, archives it, and asks for a new one while the planner is off — every page passes the accessibility check |

The **evaluation set** (`tests/api/test_strategy_evaluation.py`, Q-8-10):

- **Golden contexts:**
  - G1: a selling product with margin;
  - G2: no product cost — "margin unknown" must be named;
  - G3: no stock — never sent to the model;
  - G4: only Google Ads connected;
  - G5: a funnel drop-off reaches the planner with its numbers.
- **Hostile cases:**
  - all the budget on one platform;
  - shares above 100 % or not adding up;
  - an upside-down target, and a target 8× the business's own;
  - a figure that does not exist, and another product's ID;
  - a money amount slipped in;
  - a platform not asked for, and a campaign type from another platform;
  - an empty answer, and an endless summary;
  - a product title trying to close its block and give orders.

## 6. Database

Migration **0018** (additive, reversible): `ai_models` and `prompt_versions` (reference data, read and add only), `ai_runs` (tenant-owned, forced RLS, insert-only), `campaign_strategies` (tenant-owned, forced RLS; archived, never deleted). DATABASE_SCHEMA §14A.

## 7. Defects found during Phase 8 (all fixed)

1. A new critical security advisory against Next.js 16.4.0 (found by the dependency check): moved to the patched **16.4.3**.
2. The database refuses the NUL character in stored text: any control character in a strategy's text is now refused by the checks (`invalid_text`).
3. The products list was asked for before a store was known (an empty address): it now waits for the store.
4. After saving an edit, the page briefly re-read the old strategy: only the lists are re-read now.

## 8. Deviations from the plan

1. Risks carry a **code** as well as text, so the business rules can be checked reliably.
2. Cost-per-click and cost-per-conversion targets are compared with each platform's own figure (never added across platforms).
3. Each platform's minimum daily budget is an AdVegaX **setting** (1 USD by default), converted with the latest rate; Step 0 compares it with the platforms' own minimums.
4. Generating waits for the answer (up to the time limit, twice with the retry) rather than running as a background job.
5. Editing a strategy that was ready returns it to draft.
6. The page edits the summary, positioning, platforms (type, share, audience, reasoning) and the budget; targets, risks and assumptions are shown but not yet editable on the page (the API accepts them).
7. Evidence is shown as the planner saw it (the run's snapshot).

## 9. Not verified in this environment — Step 0 (8-01)

With an Anthropic API key in the local settings file (`ANTHROPIC_API_KEY`, `AI_ENABLED=true`):

1. one strategy request with AdVegaX's schema against the configured model (`claude-sonnet-5-5`); the answer validates;
2. the token counts and usage block as documented; the cost estimate once `AI_PRICE_*_PER_MTOK` are set to the published prices;
3. the golden set once live; a hostile product title does not change the behaviour;
4. the platforms' real minimum daily budgets against the 1 USD setting.

Also still pending: the Step 0 checks of Phases 2A–7.

## 10. Known limitations and remaining risks

| Limitation / risk | Mitigation |
|---|---|
| The AI suggests something plausible but wrong | Evidence on every point, business rules, your edit and approval; nothing executes in Phase 8 |
| Prompt injection through product text | Sealed untrusted block, no tools, every answer validated, hostile tests |
| Live model behaviour may differ from the simulator | Step 0; the same checks apply to every live answer |
| AI cost | Daily limit, length cap, one retry, usage view; estimated cost once prices are set |
| English only (Q-8-9) | Product text stays as written; more languages later |
| No zero-data-retention yet | Ask Anthropic before production (plan §2A) — an account arrangement, not code |

## 11. Rollback

Phase 8 adds tables and pages only. Migration 0018 is reversible. Switching `AI_ENABLED` off stops generation; existing strategies stay readable.

## 12. Your review checklist

**A. Decide or confirm (business):**

1. The strategy's contents (§1, item 4): is anything missing that you need before building campaigns in Phase 10B?
2. The rules (§1, item 5): are a 3× band for targets, the risks that must be named, and 1 USD minimum per platform per day right for your markets (Australia, Nepal)?
3. The limit of **20 strategies a day** per organization, and who may generate them (everyone except viewers).
4. That editing a ready strategy sends it back to draft.

**B. Try it in the app** (with the simulator data, or live after Step 0):

1. Strategies → make one for a product with sales: check the amounts add up to your budget, and each point shows the figures behind it.
2. Edit it: change the shares so they don't add up to 100 % and see the message; fix them and save.
3. Mark it ready, then archive it.
4. Settings → AI planner use (as an owner).

**C. Set up when you are ready (needed for Step 0 and real use):**

1. An Anthropic API key in your local settings file as `ANTHROPIC_API_KEY`, plus `AI_ENABLED=true` — never in a chat or the repository.
2. Optional: the current prices per million tokens (`AI_PRICE_INPUT_PER_MTOK`, `AI_PRICE_OUTPUT_PER_MTOK`) so the cost estimate shows.
3. Before production: ask Anthropic for zero data retention on your organization.

**D. Documents to read:** this report; `PHASE_08_PROGRESS.md` (task by task); API_SPECIFICATION §19H; DATABASE_SCHEMA §14A.

## 13. Next

1. **Your review** of Phase 8 (§12).
2. **Step 0** (8-01) once the key is in place, and the pending Step 0 checks of Phases 2A–7.
3. Then **Phase 9 — creative engine** (the plan is written for your approval first).
