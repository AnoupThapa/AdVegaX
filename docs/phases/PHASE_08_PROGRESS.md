# Phase 8 — Progress (AI campaign planner)

Plan: `PHASE_08_PLAN.md` (approved 2026-10-25, A26, all recommendations Q-8-1 … Q-8-10). One task at a time, a report after each.

| Task | Status |
|---|---|
| 8-01 Step 0: live check of the Claude API with AdVegaX's key | ⏸ Waiting for an Anthropic API key in the local settings file |
| 8-02 Migration 0018; AI platform: adapter, Anthropic adapter, prompts, runs, simulator | ✅ Done — awaiting review |
| 8-03 Context builder | ✅ Done — awaiting review |
| 8-04 Strategy schema, validation chain, budget | ⏳ Next |
| 8-05 Workflow, API, limits | — |
| 8-06 Web app: Strategies page | — |
| 8-07 Evaluation, browser test, `PHASE_08_REPORT.md` | — |

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
