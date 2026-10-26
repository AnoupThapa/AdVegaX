# Phase 8 — Progress (AI campaign planner)

Plan: `PHASE_08_PLAN.md` (approved 2026-10-25, A26, all recommendations Q-8-1 … Q-8-10). One task at a time, a report after each.

| Task | Status |
|---|---|
| 8-01 Step 0: live check of the Claude API with AdVegaX's key | ⏸ Waiting for an Anthropic API key in the local settings file |
| 8-02 Migration 0018; AI platform: adapter, Anthropic adapter, prompts, runs, simulator | ✅ Done — awaiting review |
| 8-03 Context builder | ✅ Done — awaiting review |
| 8-04 Strategy schema, validation chain, budget | ✅ Done — awaiting review |
| 8-05 Workflow, API, limits | ✅ Done — awaiting review |
| 8-06 Web app: Strategies page | ✅ Done — awaiting review |
| 8-07 Evaluation, browser test, `PHASE_08_REPORT.md` | ⏳ Next |

## 8-01 — Step 0 (2026-10-25)

**Blocked:** needs an Anthropic API key, created by you in the Claude Console and placed only in the local, untracked settings file as `ANTHROPIC_API_KEY` (never in a chat or the repository). The Messages API address is reachable from here (it answers "unauthenticated" without a key). Step 0 then sends one small request with structured outputs, checks the answer's shape, usage figures and the model name against the simulator, and records the result. Until then everything is built and tested against the simulator, from Anthropic's documentation (checked 2026-10-25).

## 8-02 — Migration 0018; AI platform (2026-10-25)

**Completed**
- **Migration 0018** (additive, reversible) — four tables:
  - `ai_models`, `prompt_versions`: which model and which prompt version a run used (shared reference data; the application can only read and add rows);
  - `ai_runs`: every model call (tenant-owned, forced row-level security; read and insert only — a run is never changed or deleted);
  - `campaign_strategies`: the validated strategies with their budget (tenant-owned, forced RLS; used from 8-05).
- **The model adapter:** the planner asks for one answer constrained to a JSON schema; the model gets **no tools** (it can only answer with data, A12). Swappable (D19).
- **Anthropic's adapter:** `POST https://api.anthropic.com/v1/messages` with structured outputs (`output_config.format` = JSON schema), through the SSRF-safe client, no redirects, the key only in the `x-api-key` header. Plain outcomes:
  - a refused answer, a cut-off answer and an answer that is not JSON each say so;
  - a refused key → "not configured"; rate limit, overload (529) or provider error → "unavailable"; the time limit → "timed out".
- **Versioned prompts:** each prompt has a name, a version and a hash of its text; a text changed without a new version is refused, both in code and against the stored hash.
- **Runs (`run_task`)** — the only way AdVegaX calls a model:
  - off unless `AI_ENABLED`; without a key nothing is called;
  - **daily limit** per organization (`AI_DAILY_RUNS`, 20, per UTC day; every recorded call counts);
  - an unusable or rejected answer is asked for **once more** (`AI_MAX_RETRIES`, 1) with the plain reasons added; provider failures are not retried;
  - **every call is recorded**: model, prompt version and hash, the data snapshot sent, outcome, reasons, attempts, tokens, estimated cost (from configured prices, otherwise "no price", never 0) and time;
  - the model call runs outside any database transaction;
  - errors for the API: `AI_LIMIT_REACHED` (429), `AI_UNAVAILABLE` (503), `AI_ANSWER_REJECTED` (422, with reasons). Messages added to the web app.
- **Settings:** `AI_ENABLED`, `ANTHROPIC_API_KEY`, `AI_MODEL` (`claude-sonnet-5-5`), `AI_MAX_OUTPUT_TOKENS`, `AI_TIMEOUT` (60 s), `AI_DAILY_RUNS`, `AI_MAX_RETRIES`, `AI_PRICE_INPUT_PER_MTOK`, `AI_PRICE_OUTPUT_PER_MTOK`; documented in `.env.example`.
- **Simulator** `tests/ai_sim.py`: answers in the Messages API's documented format behind the real HTTP client; checks the key, the version header and that structured outputs are asked for and no tools are offered.

**Files changed** (21)
- New (9): `app/domains/ai/{__init__,models,adapter,anthropic,prompts,runs}.py`, `alembic/versions/0018_ai_planner.py`, `tests/ai_sim.py`, `tests/unit/test_ai_adapter.py`, `tests/api/test_ai_runs.py`, this file.
- Modified (12): `frontend/package.json`, `frontend/package-lock.json` (security patch, below), `app/core/settings.py`, `app/core/errors.py`, `app/db/models.py`, `tests/conftest.py`, `tests/security/test_static_rules.py`, `frontend/lib/api/errors.ts`, `.env.example`, `docs/DATABASE_SCHEMA.md` (§14A; §14 outlines superseded), `PHASE_08_PLAN.md` (approved), `PROJECT_STATUS.md`.
- Deleted: none.

**Tests**
- **New:** 17 adapter and prompt tests, 17 run tests, 1 static rule.
- Covered: request shape; every answer and failure kind; one retry with the reasons; reference rows shared; changed prompt refused; cost; daily limit per organization and UTC day; tenant isolation of runs; the key never in records or logs.
- Migration up/down/up and models-match-migrations pass; the RLS sweep covers both new tenant tables.
- **Backend `make check`: 1,662 passed**, coverage 97 %. **Frontend `npm run check`: 411 passed**, coverage 96 %. **Browser tests: 15 passed.**

**Security**
- The key lives only in settings (a secret value), is read in one place, travels only in one header and is masked by the client. It never appears in runs, logs or errors (tested).
- One fixed address, POST only, no redirects (static rule). No tools for the model.
- Runs record AdVegaX's own figures only; reasons are plain message keys, never the model's text.
- Tenant isolation: forced RLS on both new tenant tables. Runs cannot be changed or deleted by the application.

**Deviations**
0. **Security patch outside the task:** the frontend's dependency check found new critical advisories against Next.js 16.4.0 (remote code execution in image optimization and in `use cache`, a Server Actions denial of service). Next.js and its lint config were moved to the patched **16.4.3**; all frontend and browser tests pass on it.
1. Runs and reference rows are written after the call, in one short transaction. The daily-limit check is a count, so two requests at the same instant could pass it together (an overrun of at most one run per concurrent request). This is acceptable for a cost cap, and simpler than a lock.
2. A refused key (HTTP 401/403) is recorded as a failed run with reason `ai_key_refused`; a missing key calls nothing and records nothing.

**Blocked:** 8-01 (Step 0) waits for the API key.

**Next task:** 8-03 — the context builder (the product's figures from Phases 2–7, delimited and minimized, as the data snapshot).

## 8-03 — Context builder (2026-10-26)

**Completed**
- **`app/domains/strategy/context.py`** builds what the planner shows the model for one product, **only from AdVegaX's own figures** (Q-8-2). It covers the product's store and the ad accounts and Google Analytics property assigned to it.
- **Period:** the last **90 complete days** (`PLANNER_CONTEXT_DAYS`), plus a recent window of **30 days** (`PLANNER_RECENT_DAYS`). If a source started later, the period is shortened to the days every source has fully read. A source still importing says "not synced" instead.
- **Evidence figures** — each has a key the model must cite (checked in 8-04), with its label, unit, currency and value. A figure AdVegaX doesn't have shows "unknown" with its reason, never 0:
  - the product: units, net sales, product cost, gross profit and margin, for the period and recently; lowest and highest price and unit cost; units in stock; variants out of stock;
  - the business (the product's store): net sales, orders, gross profit and margin, ad spend, profit after ad spend, blended ROAS, sessions, store conversion rate;
  - each connected ad platform: spend, clicks, impressions, conversions, conversion value, platform ROAS, cost per click, cost per conversion;
  - the funnel's stages and same-source rates (Phase 7).
- **Facts:** the reporting currency, the period, the product's status, the store platform, the connected ad platforms (codes only), the number of variants and whether stock is tracked.
- **Funnel drop-offs:** findings (Q-7-7) for the whole business and each ad platform. Channel findings are left out, because channel names can be free text.
- **Store text is untrusted:** the product's title, type, vendor and variant names are:
  - stripped of control and invisible characters (including right-to-left overrides) and shortened;
  - sent in their own `<store_text>` block, where `<` and `>` are escaped, so a title containing `</store_text>` or "SYSTEM: ignore every rule" stays data inside the block.
- **Snapshot:** the snapshot (what `ai_runs` records) is exactly what is sent. It holds no customers, orders, emails, addresses, account or campaign names, IDs or secrets.

**Files changed** (7)
- New (3): `app/domains/strategy/{__init__,context}.py`, `tests/api/test_strategy_context.py` (11 tests).
- Modified (4): `app/core/settings.py`, `.env.example`, `tests/security/test_static_rules.py` (1 new rule), this file.
- Deleted: none.

**Tests**
- **New (11 + 1 static rule):**
  - the golden context, worked out by hand;
  - unknown figures stay unknown, never 0;
  - a product with no sales has real zeros, and its margin says why it has none;
  - no price, cost or stock tracking each say why;
  - oversold stock counts as out of stock;
  - the period is shortened for a new source; a source still importing says "not synced";
  - another organization's product is "not found";
  - hostile store text stays inside its block;
  - no personal data, account names, IDs or secrets are sent;
  - the snapshot equals what is sent.
- The static rule checks that the context builder only reads, calls nothing outside, and names no customer, contact or credential field.
- **Backend `make check`: 1,674 passed**, coverage 97 % (context builder 97 %). No frontend change.

**Security:** follows A12 — only aggregated figures and catalogue facts. Store text is delimited and neutralized. The builder only reads (static rule). Tenant isolation: everything is read inside the organization's row-level security context.

**Deviations**
1. Product price and unit cost are today's catalogue values, converted at the last day's exchange rate. Past price changes aren't shown.
2. The window is the product's **store** scope (its assigned ad accounts and property), not the whole organization: the plan is for that store's product.

**Next task:** 8-04 — strategy schema, validation chain (schema → existence → business rules → budget) and budget amounts, plus the versioned planner prompt.

## 8-04 — Strategy schema, validation chain, budget amounts, prompt (2026-10-26)

**Completed**
- **Strategy shape** (`strategy/schema.py`, Q-8-4):
  - an objective (sales, leads or awareness), a summary and positioning;
  - one entry per platform, each with its campaign type (Google Ads: Search, Performance Max, Shopping; Meta: Advantage+ shopping, Sales), its **share** of the budget as a percentage, the audience in words, its reasoning and evidence;
  - creative angles with evidence;
  - targets as ranges (ROAS, cost per order, cost per click, cost per conversion) with evidence;
  - risks with a code (margin unknown or negative, low stock, limited history, tracking gap, competition, seasonality, other), and assumptions.
  - The answer schema sent to the model uses only what structured outputs support (tested). **It has no field for a money amount** (tested).
- **Validation chain** (`strategy/validation.py`, Q-8-6), run on every answer and later on every edit, one stage at a time:
  1. **shape:** exact fields and types, allowed values, lengths and counts (which the schema can't express), the campaign type exists on its platform, one entry per platform and target, shares with at most 2 decimals, target ranges 0 ≤ low ≤ high;
  2. **existence:** exactly the requested platforms, each connected; the requested objective; every evidence key one of AdVegaX's figures, with a known value;
  3. **business rules:**
     - an unknown or negative margin, stock below recent sales, and a history under 30 days must each be named as a risk;
     - the margin comes from sales, or else from today's price and cost (highest cost against lowest price);
     - targets must overlap the organization's own figures, within 3 times either way (`PLANNER_TARGET_FACTOR`), where AdVegaX has them;
  4. **budget:** shares are positive and add up to 100 % (0.01 tolerance); each platform's daily amount meets its minimum.
- **Before asking the model:** an inactive or out-of-stock product, or no connected ad platform, is not planned (used by 8-05 as `PRODUCT_NOT_PLANNABLE`). A total too small for every platform's minimum is also refused before any model call.
- **Budget amounts** (`strategy/budget.py`, Q-8-5):
  - AdVegaX turns the shares into amounts in the currency's smallest unit (cents; 0 decimals for yen, 3 for dinar) with the largest-remainder method, so **the amounts always add up to your total exactly** (tested on 500 random budgets);
  - monthly amounts are compared as daily (÷ 30.4);
  - each platform's minimum is a setting in US dollars (default 1), converted with the latest rate; an unknown minimum is never assumed to be met.
- **Prompt `campaign_strategy` v1** (`strategy/prompt.py`), versioned and hashed. It contains the rules — cite figures by key, no amounts, only the requested platforms, required risks, English — and says that catalogue text is data, never instructions. AdVegaX does not rely on the prompt: every answer is validated regardless.
- **Planning task** (`strategy/task.py`): the context, the prompt, the schema, the recorded snapshot (now including the request) and the validation chain, ready for 8-05.

**Files changed** (11)
- New (8): `app/domains/strategy/{schema,validation,budget,prompt,task}.py`, `tests/unit/test_strategy_validation.py` (28 tests), `tests/unit/test_strategy_budget.py` (14 tests), `tests/api/test_strategy_task.py` (3 tests).
- Modified (3): `app/core/settings.py`, `.env.example`, this file.
- Deleted: none.

**Tests**
- **New (45):**
  - every validation rule, and the order of the stages;
  - golden budget amounts (AUD, JPY, KWD) and a random check that amounts always add up;
  - the schema's limits, and that it has no money field;
  - the prompt is registered;
  - end to end against the simulator: a valid strategy for the golden context, with its snapshot recorded; an answer citing figures AdVegaX lacks, rejected after one retry with the reasons; a hostile product title that can't close its block, and an answer that follows it (100 % / 0 %) rejected.
- **Backend `make check`: 1,719 passed**, coverage 97 % (strategy domain 97–100 %). No frontend change.

**Security:**
- The model can't set an amount (no such field, tested).
- Its answer is data and passes four checks before anyone sees it.
- Store text can't escape its block.
- No change to what the model sees.

**Deviations**
1. Risks are given as codes plus text (the plan said "risks"), so the business rules can be checked reliably rather than by searching the text.
2. Cost-per-click and cost-per-conversion targets are compared with each requested platform's own figure (never added across platforms); ROAS uses the business's blended ROAS; cost per order uses ad spend ÷ orders.
3. The platform minimum daily budgets are AdVegaX settings (1 USD each by default), because the platforms' real minimums depend on currency and bidding. Step 0 compares them with the platforms' figures.

**Next task:** 8-05 — the strategy workflow and API (generate, read, edit with re-validation, draft, mark ready, archive, audit), daily limits and the usage view.

## 8-05 — Strategy workflow and API; limits and usage (2026-10-26)

**Completed**
- **API** under `/organizations/{id}/ai` (API_SPECIFICATION §19H):
  - `POST /campaign-strategies` — generate;
  - `GET /campaign-strategies` (paged; archived only when asked for) and `GET …/{id}`;
  - `PATCH …/{id}` — edit;
  - `POST …/{id}/ready`, `POST …/{id}/archive`;
  - `GET /usage`.
- **Generate:**
  1. AdVegaX first checks the request: platforms (1–2, distinct, connected), objective, and a budget in the reporting currency with no more decimals than it has.
  2. It checks the product can be planned: active, in stock, a connected ad platform, and a total that covers every platform's minimum (1 USD a day each, converted with the latest ECB rate). Otherwise `PRODUCT_NOT_PLANNABLE`, with the reasons — **the model is never called**.
  3. One model call: daily limit, time limit, one retry.
  4. The validated answer is kept as a **draft**, with the amounts AdVegaX computed.
- **Read:** each strategy shows:
  - its budget and amounts per platform (for the period, and per day);
  - its **evidence**, resolved to the figures' labels and values as the planner saw them (from the run's snapshot);
  - its AI run, model and prompt version.
- **Edit:** the whole strategy and/or the budget.
  - It is **re-validated with the same four checks** as the model's answers, against today's figures, and the amounts are recomputed.
  - An edited strategy goes back to draft, so it is reviewed again before it is ready.
  - Control characters (and the NUL character, which the database refuses) are rejected in any text.
- **Ready / archive:** archived strategies are kept and can no longer be changed (`STRATEGY_ARCHIVED`, 409). Repeating an action changes nothing.
- **Who can do what:**
  - every member can read;
  - owner, admin, manager and analyst can generate, edit, mark ready and archive (`strategies.manage`);
  - usage is for owners and admins (`ai_usage.view`).
- **Audit:** every change is audited — the status, objective, platforms and budget, **never the strategy text**.
- **Usage:**
  - the daily limit, runs today and runs left;
  - today and the last 30 days: runs by outcome, tokens, and the estimated cost in US dollars;
  - "unknown" (null) unless every run in the period has a price — never 0 by default.
- New error messages in the web app: `PRODUCT_NOT_PLANNABLE`, `STRATEGY_ARCHIVED`. The API types for the web app are regenerated.

**Files changed** (17)
- New (4): `app/domains/strategy/{schemas,service,router}.py`, `tests/api/test_strategies_api.py` (27 tests).
- Modified (13): `app/api/router.py`, `app/core/errors.py`, `app/domains/organizations/permissions.py`, `app/domains/strategy/validation.py` (text check), `tests/security/test_tenant_isolation.py` (the new routes in the sweep), `tests/unit/test_domain_rules.py`, `frontend/lib/api/{errors.ts,openapi.json,schema.d.ts}`, `docs/API_SPECIFICATION.md` (§19H; §11 marked superseded), this file, `PROJECT_STATUS.md`.
- Deleted: none.

**Tests**
- **New (27):**
  - generate (golden amounts daily and monthly, evidence, AI run, audit without text);
  - every "cannot be planned" reason, with no model call;
  - bad requests;
  - another organization's product;
  - each AI error (answer rejected, provider down, daily limit, switched off), with nothing kept;
  - list and read, edit with re-validation and recomputed amounts;
  - five invalid edits, a budget below the minimum;
  - ready and archive;
  - roles (a viewer cannot change anything; an analyst can generate; usage only for owners and admins);
  - outsiders see nothing;
  - usage counts and cost.
- The tenant sweep now covers the seven new routes.
- **Backend `make check`: 1,746 passed**, coverage 97 % (strategy service 98 %, router 100 %). **Frontend `npm run check`: 411 passed.**

**Security**
- Tenant isolation: row-level security on strategies and runs, and the route sweep.
- Deny by default for viewers.
- No strategy text in the audit.
- The model is still only called after every check AdVegaX can make itself.

**Deviations**
1. Generating waits for the answer (up to the 60-second limit, twice with the retry) instead of running as a background job. This is simpler for v1, and the page shows progress; it can move to a job later without changing the API's result.
2. Evidence is shown from the run's snapshot (the figures the planner saw). A key added by an edit that is not in that snapshot shows as unknown. Edits are still validated against today's figures.
3. Editing a strategy that was ready returns it to draft (the plan didn't say), so a changed plan is always reviewed before the campaign builder uses it.

**Next task:** 8-06 — the Strategies page in the web app.

## 8-06 — Web app: the Strategies page (2026-10-26)

**Completed**
- **Strategies** in the organization's menu (after Funnel).
- **New strategy** (every role but viewer):
  - choose the store (when there are several), find and pick an active product, tick Google Ads and/or Meta;
  - choose an objective or let the planner choose;
  - enter the budget in the reporting currency, per day or per month.
  - Missing choices are explained before anything is sent. While the planner works, the page says it can take up to a minute; the strategy then opens.
  - If the product can't be planned, or the AI's answer was rejected, the page explains why in plain words (e.g. "The product is out of stock.", "It cited a figure AdVegaX does not have (product.reviews).").
- **The list:** product, platforms, objective, budget, status (Draft / Ready for the campaign builder / Archived), last changed; filter by status.
- **One strategy:**
  - the summary, objective, positioning and budget;
  - each platform with its campaign type, **its amount** (and per day for a monthly budget), its share, who to reach and why;
  - under every point, **the AdVegaX figures it is based on**, with their values — an unknown figure says why (e.g. "No Google Analytics property"), never 0;
  - angles, targets as ranges (ROAS as ×, costs in money), risks and assumptions;
  - which model and prompt version drafted it and when, and that AdVegaX checked it and nothing was created at Google or Meta.
- **Edit:**
  - the summary, positioning, and each platform's campaign type, share, audience and reasoning, plus the budget;
  - the same checks run again, and any failure is listed in plain words.
- **Mark ready**, and **Archive** after confirming. Viewers see no actions.
- **Settings → AI planner use** (owners and admins):
  - the daily limit and what is left today;
  - for today and the last 30 days: runs (accepted, rejected by AdVegaX's checks, failed), tokens, and the estimated cost — "unknown (no price set)", never 0.
- The page computes nothing: amounts and checks come from the API. The static "no formula" rule now covers the strategies pages too.

**Files changed** (21)
- New (10): `features/strategies/{api.ts,labels.ts,StrategiesPage.tsx,StrategyDetail.tsx,AiUsage.tsx,strategies.module.css}`, `app/orgs/[organizationId]/strategies/page.tsx`, `…/strategies/[strategyId]/page.tsx`, `tests/features/strategies.test.tsx` (48 tests).
- Modified (11):
  - frontend: `features/organizations/{OrganizationShell,OrganizationSettings,permissions}.tsx/ts`, `features/stores/api.ts` (products only once a store is known), `lib/api/errors.ts` (`field` and `issue` details), `lib/format/money.ts` (stock and price reasons), `lib/api/{openapi.json,schema.d.ts}`, `tests/support/organizations.ts`, `tests/static/source-rules.test.ts`;
  - backend: `strategy/{schemas,service}.py` (the budget carries its currency's minor units) and its test;
  - this file.
- Deleted: none.

**Tests**
- **Frontend `npm run check`: 459 passed** (48 new).
- **Browser tests: 15 passed** (the menu's new link, with accessibility checks, on every page). A browser test of the Strategies page itself comes in 8-07.
- **Backend `make check`: 1,746 passed**, coverage 97 %.

**Security:**
- Buttons follow the roles (viewers read only); the API still authorizes every action.
- The model's text is shown as text (React escapes it), never as HTML.
- No figure is computed in the browser.

**Deviations**
1. Targets, risks and assumptions are shown but not editable in this version; everything else is. The API accepts edits to all of them, so they can be added to the form later.
2. The usage panel is in Settings (as planned), not on the Strategies page.

**Next task:** 8-07 — the evaluation set (golden and hostile cases against the simulator), a browser test of the Strategies page, and `PHASE_08_REPORT.md`.
