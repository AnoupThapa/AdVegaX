# Phase 8 — AI campaign planner: Implementation Plan

**Status:** ✅ **Approved by the product owner (2026-10-25, A26: "Approve all") with all §2 recommendations (Q-8-1 … Q-8-10; settles Q12 for Phase 8).** Implementation authorized for Phase 8 only. **Implemented 2026-10-26 — see `PHASE_08_REPORT.md`.** · **Date:** 2026-10-25

> **Live data:** Phase 8 is the first phase that calls an AI model. It is built and tested against an **AI simulator** (recorded-format answers, no network in CI); Step 0 (8-01) makes a few real calls once you add an API key. `api.anthropic.com` is reachable from this environment.

**Depends on:** Phase 2A/2B (products), Phase 6 (unified figures, registry), Phase 7 (funnel and findings). · **Followed by:** Phase 9 (creative engine), Phase 10B (campaign builder), which turn an approved strategy into creatives and campaigns.
**Governing documents:** MASTER_SPECIFICATION §8 (AI philosophy), §9 (recommendation lifecycle), §20 D16, A12 (AI data boundary); DISCOVERY_REPORT Q12; `phases/PHASE_08_AI_PLANNER.md` (outline); API_SPECIFICATION §11; DATABASE_SCHEMA §14.

---

## 1. Objective

Let a merchant ask for a **campaign strategy for a product** and get a clear, checkable plan — never a campaign:

- which **platform(s)** to use (Google Ads, Meta), the **campaign type**, who to reach, the **angles** to lead with, how to **split a budget the merchant sets**, the **targets** to watch, and the **risks and assumptions** — each point tied to the figures it was based on;
- **grounded in AdVegaX's own deterministic figures** (Phase 6 and 7: sales, margins, stock, ad spend, platform results, funnel and drop-offs), never in data the AI makes up;
- **checked before anyone sees it:** the AI's answer must match a strict schema, refer only to the organization's own products and connected platforms, respect business rules and stay inside the budget — otherwise it is rejected, never shown;
- **traceable:** every strategy records which model, which prompt version and which data snapshot produced it;
- **the merchant stays in charge:** they can edit any part, save it as a draft, and mark it ready for the campaign builder (Phase 10B). Nothing is created at Google or Meta in Phase 8.

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all of them at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-8-1** (Q12) | Which AI provider and model? | **Anthropic's Claude API**, using its **structured outputs** (the answer is constrained to AdVegaX's JSON schema), behind an AdVegaX **model adapter** so another provider can be added later without changing the planner. The model name is a **setting** (a current Claude Sonnet-class model by default — capable and affordable for planning); Step 0 confirms it. | Structured outputs remove most malformed answers; the adapter keeps AdVegaX independent of one vendor (D19). |
| **Q-8-2** | What data does the AI see? | **Only AdVegaX's normalized, aggregated figures** for the chosen product and the organization: the product's title, type, price, cost and margin, stock, recent units and sales (Phase 6), the connected platforms and their recent spend and results, the funnel and its findings (Phase 7), the reporting currency. **No customer data, no orders, no emails, no addresses, no tokens.** Product titles and descriptions are **untrusted text**, clearly marked so instructions hidden in them are ignored. | The AI data boundary (A12): the AI reasons over validated figures, nothing else. Marking store text as untrusted defends against prompt injection. |
| **Q-8-3** | What is kept, and where? | AdVegaX stores, per run: model, prompt version, the **data snapshot** sent (AdVegaX's own figures — no personal data), the validated answer, tokens, cost, time and outcome. Anthropic's commercial terms: API data is **not used for training**; you can ask Anthropic for **zero data retention** before going live (recommended for production; not needed for development). | Traceability (exit criterion); ZDR is an account arrangement with Anthropic, not code. |
| **Q-8-4** | What does a strategy contain? | A fixed schema: **objective** (sales, leads, awareness — from a list), **platforms** and per platform a **campaign type** (Google Ads: Search, Performance Max, Shopping; Meta: Advantage+ shopping, Sales — from a list), **audience** in words (no personal data), **positioning and creative angles** (short texts), **budget split** as percentages, **targets** (e.g. cost per order, ROAS) as ranges, **risks**, **assumptions**, and **evidence**: which AdVegaX figures each recommendation relies on (by their keys). | A schema the backend can check; evidence lets you see why. Creative copy itself is Phase 9. |
| **Q-8-5** | Who decides the budget? | **You do.** You enter a total (daily or monthly, in your reporting currency); the AI only proposes **percentages**; AdVegaX computes the amounts, checks they add up to your total and respect each platform's minimum daily budget (settings), and rejects anything else. | Budget numbers are never left to the AI (D16, budget validation). |
| **Q-8-6** | What makes an answer invalid? | **Schema** (types, lists, ranges) → **existence** (the product, ad platforms and accounts are the organization's own and connected) → **business rules** (no strategy for a product with no stock; a product with negative or unknown margin must say so in its risks; targets must be consistent with the organization's own history ranges) → **budget** (Q-8-5). An invalid answer is **retried once** with the errors explained to the model, then rejected with the reasons logged — never shown. | Invalid or out-of-policy output is always rejected (exit criterion). |
| **Q-8-7** | What can people do with a strategy? | **Generate**, **read**, **edit** any field (re-validated), **save as draft**, **mark ready** for the campaign builder (Phase 10B), **archive**. Every change is audited. Generating needs **owner, admin, manager or analyst** (the role table in API_SPECIFICATION); viewers can read. | Human approval before anything executes (D16); the role table already says who may generate. |
| **Q-8-8** | How much AI use? | Per organization **20 strategies a day** (a setting; billing plans come in Phase 13), **60-second** time limit, a cap on answer length, at most **one retry**. Usage (runs, tokens, estimated cost) is visible in Settings to owners and admins. | Predictable cost; protects against loops. |
| **Q-8-9** | Language | **English** answers in v1; the product's own text stays as written. | One language to evaluate well first; more later (Q15). |
| **Q-8-10** | How is quality checked? | An **evaluation set**: golden contexts (a well-selling product with margin, a product with no cost, a product with no stock, an organization with only Google Ads, a product with a funnel drop-off) with expected properties; **hostile cases** (instructions hidden in a product title, out-of-range numbers, unknown product ids, budgets that do not add up) that must be rejected. CI runs them against the simulator; Step 0 runs the golden set once live. | Repeatable checks without calling the AI in CI. |

## 2A. What you need to set up

1. **An Anthropic API key** (console.anthropic.com → API keys), put **only in your local settings file** (`ANTHROPIC_API_KEY`) — never in chat or the repository, like the platform secrets.
2. **Optional, before production:** ask Anthropic's sales team for **zero data retention** on that organization.
3. **Your budget per strategy** when you generate one.

## 3. Scope

| Area | In Phase 8 |
|---|---|
| AI platform | `app/domains/ai/`: model adapter interface, the Anthropic adapter (Messages API, structured outputs; SSRF-safe client, one fixed host), prompt registry with versions, `ai_runs` with tokens, cost and latency; an **AI simulator** for tests |
| Context builder | From Phase 6/7 figures only; untrusted text delimited; a stored snapshot per run |
| Strategy | Strict schema; validation chain (Q-8-6); deterministic budget amounts (Q-8-5) |
| Workflow | `campaign_strategies`: generate, edit, draft, ready, archive; audit |
| Limits | Per-organization daily quota, time limit, retry cap, usage view |
| API | `POST /ai/campaign-strategies`, `GET /ai/campaign-strategies[/{id}]`, `PATCH /ai/campaign-strategies/{id}`, `POST …/{id}/ready`, `POST …/{id}/archive`, `GET /ai/usage` |
| Web app | A **Strategies** page: pick a product, platforms, objective and budget; see the strategy with its evidence; edit; mark ready |
| Data | Migration **0018**: `ai_models`, `prompt_versions`, `ai_runs`, `campaign_strategies` (forced RLS where tenant-owned) |

## 3A. Non-goals

- Creating or changing anything at Google or Meta (Phase 10A/10B).
- Ad copy, headlines, images (Phase 9).
- Recommendations about running campaigns (Phase 11); autopilot (Phase 12).
- AI access to raw tables, platform APIs, the internet or tools (A12).
- Billing per AI use (Phase 13).

## 4. Facts and Step 0

### 4.1 Facts (checked 2026-10-25)

1. **Anthropic API data handling:** retained data is not used for model training without express permission; zero data retention is available per organization on request and covers the Messages API; **structured outputs** are ZDR-eligible (only the JSON schema is cached for up to 24 hours).
2. The Messages API constrains answers to a JSON schema with **structured outputs** (or strict tool use); AdVegaX still validates every answer itself.

### 4.2 Step 0 — live calls (task 8-01)

1. The configured model answers one strategy request with AdVegaX's schema; the answer validates.
2. Token counts and the usage block are read as documented; cost per run is estimated from the published prices (a setting).
3. The golden evaluation set (Q-8-10) passes live; a hostile product title does not change the answer's behaviour.

## 5. Proposed structure

```
app/domains/ai/          adapter interface, anthropic adapter, prompts (versioned), runs, limits
app/domains/strategy/    context builder, schema, validation chain, budget, service, router
frontend/features/strategies/   Strategies page
tests/ai_sim.py          AI simulator (recorded-format answers, hostile answers)
```

The AI domain talks to one fixed host through the SSRF-safe client; it never receives database access, tokens or tools (A12).

## 6. Data model (migration 0018)

- **`ai_models`** (reference data): provider, model name, active, price per million input/output tokens (for estimates).
- **`prompt_versions`** (reference data): name, version, template hash, status.
- **`ai_runs`** (tenant-owned, forced RLS): organization, user, model, prompt version, task (`campaign_strategy`), context snapshot (JSON, AdVegaX figures only), status (`succeeded` | `rejected` | `failed` | `timed_out`), rejection reasons, input/output tokens, estimated cost, latency, created.
- **`campaign_strategies`** (tenant-owned, forced RLS): organization, product, status (`draft` | `ready` | `archived`), the validated strategy (JSON), budget (amount, period, currency) and computed amounts, the AI run it came from, edited by / at, created.

## 7. API

As §3. Every strategy answer carries its `ai_run` (model, prompt version, created), its `evidence` resolved to the figures' labels and values, and its validation state. Errors: `AI_LIMIT_REACHED` (daily quota), `AI_UNAVAILABLE` (provider down / time limit), `AI_ANSWER_REJECTED` (invalid twice, with plain-language reasons), `PRODUCT_NOT_PLANNABLE` (e.g. no stock).

## 8. Security and privacy

- The API key lives only in settings; never logged, never in answers, audit or AI context (static and log tests, as for platform secrets).
- Context: aggregated AdVegaX figures only; a static test forbids personal-data fields in the context builder; store text is delimited as untrusted.
- The model has **no tools**; its answer is data, validated before use; it can never trigger an action.
- One fixed outbound host (`api.anthropic.com`) through the SSRF-safe client.
- Tenant isolation: RLS on runs and strategies; route sweeps.

## 9. Testing

- AI simulator: valid answers, malformed JSON, schema violations, unknown ids, budgets not adding up, hostile instructions, timeouts, provider errors.
- Validation chain unit tests for every rule; budget amount golden values.
- Evaluation set (Q-8-10) in CI against the simulator.
- API sweeps; page tests; one browser test with accessibility checks.

## 10. Tasks (one at a time, report after each)

| Task | Content |
|---|---|
| 8-01 | Step 0: live calls (§4.2) — waits for your API key |
| 8-02 | Migration 0018; AI platform: adapter interface, Anthropic adapter, prompt registry, runs, simulator |
| 8-03 | Context builder (Phase 6/7 figures, untrusted text, snapshot) |
| 8-04 | Strategy schema, validation chain, budget amounts |
| 8-05 | Strategy workflow and API; limits and usage |
| 8-06 | Web app: Strategies page |
| 8-07 | Evaluation set, browser test, `PHASE_08_REPORT.md` |

## 11. Acceptance criteria

1. A strategy for a selling product with margin, Google Ads and Meta connected, validates and shows its evidence.
2. Every invalid or out-of-policy answer is rejected (never shown), with reasons recorded; hostile store text does not change the rules.
3. Budget amounts always add up to the merchant's total and respect platform minimums; the AI never sets an amount.
4. Every strategy is traceable to its AI run, model, prompt version and data snapshot.
5. No personal data and no secret ever reaches the AI or a log.
6. The daily quota, time limit and retry cap hold.
7. All suites pass, with no AI calls in CI.

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| The AI suggests something plausible but wrong | MEDIUM | Evidence per point, business rules, human edit and approval; nothing executes in Phase 8 |
| Prompt injection through product text | MEDIUM | Untrusted text delimited, no tools, schema + rules after the answer, hostile tests |
| AI cost grows | LOW | Daily quota, length cap, one retry, usage view |
| Provider outage or model change | LOW | Adapter, model as a setting, clear "AI unavailable" message |

## 13. Rollback

Phase 8 adds new tables and pages only. Migration 0018 is reversible. Switching `AI_ENABLED` off hides generation; existing strategies stay readable.

## 14. Approval checklist

Approve or change **Q-8-1 … Q-8-10** (they settle Q12 for Phase 8), the Step 0 (§4.2), the data model (§6) and task-by-task delivery 8-01 … 8-07. One new runtime dependency is **not** needed: the Anthropic adapter uses AdVegaX's existing SSRF-safe HTTP client.
