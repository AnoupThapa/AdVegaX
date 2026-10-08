# Phase 8 — AI Campaign Planner

**Status:** Not started · **Depends on:** 2A, 6 · **Milestone:** M3

## Goal
Generate structured, schema-validated campaign strategies grounded in deterministic product and performance data. AI never creates campaigns.

## Prerequisite decisions
LLM provider(s) and model; data-processing terms; per-plan AI usage limits (can start with a fixed internal limit).

## Milestones
1. **AI platform** — model adapter interface, prompt/version registry, `ai_models`, `prompt_versions`, `ai_runs` (tokens, cost, latency)
2. **Context builder** — normalized data only, no PII, untrusted text clearly delimited (prompt-injection defence)
3. **Strategy schema** — strict Pydantic/JSON schema, enums, numeric ranges; budget allocation as intent, amounts computed deterministically
4. **Validation chain** — schema → resource existence in tenant → business rules → budget sanity
5. **Strategy workflow** — `campaign_strategies`/drafts; user edits; audit
6. **Cost controls** — per-org quota, timeouts, capped retries
7. **Evaluation set** — golden prompts; malformed/hostile output tests

## Exit criteria
Invalid or out-of-policy AI output is always rejected; every strategy is traceable to its AI run, prompt version and data snapshot.
