# Phase 11 — Progress (Optimization Engine)

Plan: `PHASE_11_PLAN.md` (approved 2026-10-27, A30, all recommendations Q-11-1 … Q-11-12). Built task by task; **one report for the whole phase** (`PHASE_11_REPORT.md`).

| Task | Status |
|---|---|
| 11-01 Step 0: the evaluation with your Anthropic key; a week of advice on a real account; one approved change on a Google test account | ⏸ Waiting for the key, a linked account and the 10A set-up |
| 11-02 Migration 0022; signals (the five rules); thresholds | ✅ Done |
| 11-03 Proposals and their pre-checks | ✅ Done |
| 11-04 AI explanation and ranking; "Rules only" | ✅ Done |
| 11-05 Lifecycle: daily look, Look again now, expiry, out of date, quiet period; outcomes | ✅ Done |
| 11-06 API; approval into the Action Engine; roles; audit | ✅ Done |
| 11-07 Web app: Recommendations, detail, Overview count, campaign section, settings | ✅ Done |
| 11-08 Tests, browser test, `PHASE_11_REPORT.md` | ✅ Done — Phase 11 awaiting review |

## 11-01 — Step 0

**Blocked:** needs an Anthropic API key (as Phase 8), a linked account with some weeks of real figures, and the Phase 10A set-up to send an approved change (plan §2A, §4.2).

## 11-02 — Data and the rules

- **Migration 0022** (additive, reversible): `recommendations`, `recommendation_outcomes`, `optimization_settings` (tenant-owned, forced RLS, never deleted); one open recommendation per campaign and kind; `actions.recommendation_id` (set exactly when the change came from advice); `ai_runs.task` allows `optimization`.
- **The five rules** (`optimization/signals.py`) compare each running campaign's last 7 full days with the 28 before them, on AdVegaX's own figures in the reporting currency: spend without results; losing money (conversion value per 1 spent below `1 / gross margin`); held back by budget (≥ 95 % of the daily budget used while at least 1.2 × the break-even level); cost per conversion up at least 30 %; and Phase 7's funnel drop-offs. Never on a missing figure, below the minimum spend (AUD 50) or — for rules 2 to 4 — with fewer than 5 conversions in the 28 days. The gross margin comes from the products sold in the same 7 days, and is used only when product costs are known for at least 80 % of net sales.

## 11-03 — Proposals

Spend without results → pause; losing money → daily budget −20 %; held back → +20 % (never above your maximum, never below the platform minimum, rounded to the currency); the others → "look into it". Budgets only for a campaign's own, unshared daily budget; otherwise "look into it" with the reason. Each proposal is pre-checked with the 10A checks on AdVegaX's copy of the campaign. A campaign with a change already open gets no advice.

## 11-04 — Explanations

The AI receives only the advice (ids `c1`, `c2` …, the figures written out, the proposed change, the periods) — no campaign names, no people, no tokens. Its answer is refused when an id is missing, unknown or repeated, the ranks are not 1…n, a text is too long, or a text has a number that is not among that item's figures; one retry, then AdVegaX's own plain explanation ("Rules only"). Without the AI, the advice is the same, explained by AdVegaX.

## 11-05 — Lifecycle

The scheduler starts one look per organization a day after 06:00 in its reporting time zone; "Look again now" is allowed 3 times a day. Each look supersedes the open advice and keeps the new advice for 72 hours. Rejected advice is not shown again for 14 days unless the loss at least doubled; approved advice not for 7 days. Outcomes: 7 and 14 days after a change made from advice, the campaign's figures over that many days before and after.

## 11-06 — API, approval, audit

`/recommendations` (list with the last look's summary, one, approve, reject, done, refresh) and `/optimization-settings` (API_SPECIFICATION §19L). Approval is checked again (still open and valid; the campaign's status and budget unchanged; the rule still true with today's figures), then becomes a 10A change with `source = recommendation`; an owner or admin's change is approved in the same step unless the organization requires a second person. Every step is audited.

## 11-07 — Web app

**Recommendations** in the menu: the last look (how many campaigns, whether the profit rules were used and why not, who explained), **Look again now**, the advice with its explanation, confidence and proposed change. A recommendation's page: the figures, the periods, the proposed change and its checks, assumptions, risks, **Approve and send** (owner, admin) or **Request this change** (manager), **Reject** with a reason and a note, **Mark as looked into**, the resulting change and **What happened since**. The **Overview** shows the number of open advice; a **campaign** shows its own; **Settings → Recommendations** holds the thresholds.

## 11-08 — Tests and report

Unit tests of every rule, proposal and AI check; API tests against the Google Ads and AI simulators; page tests; the browser test (`e2e/recommendations.spec.ts`); the report.
