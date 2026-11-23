# Phase 11 — Implementation Report (Optimization Engine)

**Status:** Implemented — awaiting your review. Step 0 (live checks, 11-01) waits for your Anthropic key, a linked account with real figures and the 10A set-up.
**Plan:** `PHASE_11_PLAN.md`, approved 2026-10-27 (A30, all recommendations).
**Progress log:** `PHASE_11_PROGRESS.md`.

## 1. Summary

Every day AdVegaX looks at each running Google Ads and Meta campaign with **five fixed rules**, comparing its last 7 days with the 28 before them, on AdVegaX's own figures:

1. **Spend without results** → pause it.
2. **Losing money** (the platform's conversion value is below what your gross margin needs to break even) → daily budget −20 %.
3. **Held back by budget** (uses its whole budget while clearly profitable) → daily budget +20 %.
4. **Cost per conversion jumped** (≥ 30 %) → look into it.
5. **Drop in the funnel** (Phase 7) → look into it.

Each piece of advice shows **what was noticed** (the figures), **the proposed change** with exact values, an **explanation**, **confidence**, **assumptions**, **risks** and **until when** it is valid. The AI only explains and ranks; it cannot invent figures or change the proposal. Without the AI you get the same advice in AdVegaX's own words ("Rules only").

**Nothing changes without you.** Approving creates an ordinary Phase 10A change, checked again (the campaign must be unchanged and the rule still true), tested by the platform and — for an owner or admin — sent at once, unless your organization requires a second person. Rejections keep their reason. 7 and 14 days after a change, AdVegaX records what happened to the campaign.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 11-01 | ⏸ Step 0 — waiting (§10) |
| 11-02 | Migration 0022; the five rules and their thresholds |
| 11-03 | Proposals with exact values; 10A pre-checks; budget limits and rounding |
| 11-04 | The AI prompt (`optimization` v1), its schema and checks (including invented figures); "Rules only" |
| 11-05 | Daily look (scheduler), Look again now, expiry, out of date, quiet period, outcomes |
| 11-06 | `/recommendations` and `/optimization-settings` API (§19L); approval into the Action Engine; roles; audit |
| 11-07 | Recommendations page and detail, Overview count, campaign section, Settings → Recommendations |
| 11-08 | Tests (§5), browser test, this report |

## 3. Acceptance criteria (plan §10)

| # | Criterion | Result |
|---|---|---|
| 1 | Each day the matching campaigns are found with their figures, never on missing or too-small figures | ✅ |
| 2 | Each recommendation shows what was noticed, the exact change, explanation, confidence, assumptions, risks and validity | ✅ |
| 3 | Nothing changes without approval; approval creates a 10A change, checked again | ✅ |
| 4 | Out-of-date or expired advice sends nothing | ✅ |
| 5 | Rejections keep the reason and are respected | ✅ (14-day quiet period) |
| 6 | Outcomes recorded at 7 and 14 days | ✅ |
| 7 | Traceable end to end; all suites pass, no platform or AI calls in CI | ✅ (§5) |

## 4. Security controls

- **AI boundary (A12):** the model receives only ids, written-out figures and the proposed change — no campaign names (free text), no personal data, no tokens. Its answer cannot add advice or change a value; a number not among the figures given is refused.
- **Changes:** only through the Action Engine, with every 10A check, limit, switch, the platform's test and the second-person rule.
- **Tenants:** all three tables forced RLS; the cross-tenant route sweep covers every new route.
- **Audit:** created (by `ai_recommendation` or `system`), approved, rejected, looked into, out of date, refresh, settings.

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, static rules, pytest) | ✅ 2,053 passed, coverage 95.5 % |
| Frontend `npm run check` (types, lint, format, Vitest) | ✅ 556 passed (branch coverage 85.4 %) |
| Browser (Playwright + accessibility) | ✅ 18 passed (new: `recommendations.spec.ts`) |

New: `tests/unit/test_optimization_rules.py`, `tests/api/test_recommendations_api.py`, `tests/api/test_e2e_recommendations_seed.py`, `frontend/tests/features/recommendations.test.tsx`, `frontend/e2e/recommendations.spec.ts`.

## 6. Database

Migration **0022** (additive, reversible): `recommendations`, `recommendation_outcomes`, `optimization_settings`; `actions.recommendation_id`; `ai_runs.task` allows `optimization`. DATABASE_SCHEMA §14E.

## 7. New libraries

None.

## 8. Defects found and fixed

- Two schemas shared the name `RejectIn` (changes and recommendations), which broke the generated web app types; the new one is `RecommendationRejectIn`.
- A fixed "Settings" text appeared twice once the new settings section was added; the older page test now looks inside its own form.

## 9. Deviations from the plan

1. **"Cost per conversion jumped" proposes no change** ("look into it"): cutting the budget of a campaign that may still be profitable would be the wrong default. Only rules 1–3 propose a change.
2. **"Mark as looked into"** — a decision for advice without a change (status "Looked into").
3. **Approved advice is not repeated for 7 days**, so a just-made change is given time.
4. **The gross margin is the business's**, from the products sold in the same 7 days (AdVegaX does not yet know which products a campaign sold).
5. **The approval re-check uses AdVegaX's latest copy** of the campaign and today's figures; the platform itself is then read by the 10A request before anything is sent.
6. **Managers may reject** advice as well as request it (owners and admins approve the change).

## 10. Not verified in this environment — Step 0 (11-01)

1. With your Anthropic key: the evaluation — accurate explanations, only the given figures, values never changed.
2. A week of advice on a real account reviewed with you; thresholds adjusted.
3. One approved budget recommendation on a Google test account, through Changes.

## 11. Known limitations

- Advice per campaign only; no keyword, ad, audience or bid advice; no moving budget between campaigns.
- Platform conversions use the platform's attribution.
- No emails or notifications about new advice yet.

## 12. Your review checklist

**A. Decide or confirm (business):**

1. The **thresholds** (Settings → Recommendations): at least AUD 50 spent in 7 days; at least 5 conversions in the 28 days before; budget step 20 %; cost jump 30 %.
2. The fixed rule values: "held back" at 95 % of the budget and 1.2 × break-even; the margin used only when costs are known for 80 % of sales.
3. The deviations in §9, especially **1** (no change proposed for a cost jump) and **4** (the business's margin).
4. Advice valid for **72 hours**; rejected advice quiet for **14 days**.

**B. Try it in the app** (after Step 0, or on a test account):

1. **Recommendations →** read the last look and the advice; open one.
2. Check the figures against **Reports**; read the explanation, assumptions and risks.
3. **Approve and send** a pause or budget change; follow it under **Changes**.
4. **Reject** another with a reason; it does not come back the next day.
5. **Look again now**; see the Overview count and the campaign's own advice.
6. A week later: **What happened since** on the approved advice.

**C. Set up when you are ready:**

1. Your **Anthropic API key** (as Phase 8) for AI explanations — optional.
2. Phase 10A's set-up to send approved changes (`ACTIONS_ENABLED=true`, "Allow changes", your maximum daily budget).
3. Product **costs** in your store, so the profit rules can be used.

**D. Documents to read:**

- this report;
- `PHASE_11_PROGRESS.md`;
- API_SPECIFICATION §19L;
- DATABASE_SCHEMA §14E.

## 13. Next

1. **Your review** of Phase 11 (§12), and of Phases 8 – 10B if not done yet.
2. **Step 0** for Phases 8 – 11 once keys and accounts are in place.
3. Then **Phase 12 — controlled autopilot** (some approved kinds of change made within hard limits, with a kill switch). Its plan comes to you for approval first.
