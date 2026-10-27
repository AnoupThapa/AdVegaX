# Phase 11 — Optimization Engine: Implementation Plan

**Status:** Waiting for your approval · **Date:** 2026-10-27

> AdVegaX starts **recommending** changes to running campaigns. **It never changes anything by itself.** Every recommendation is a proposal; when you approve it, it becomes an ordinary Phase 10A change, checked again and sent by the Action Engine. Built and tested against the simulators and the AI simulator (no platform or AI calls in CI).

**Depends on:**
- Phase 6 — the figures and the profit calculations (the source of truth);
- Phase 7 — the funnel drop-off findings;
- Phase 8 — the AI layer (model adapter, schema-checked answers, daily limits, run records);
- Phase 10A — the Action Engine.

**Followed by:** Phase 12 (controlled autopilot: some approved kinds of change made within hard limits).

**Governing documents:** MASTER_SPECIFICATION §9 (recommendation lifecycle); D16, D17 (AI never the source of truth or of actions); A2, A12 (AI data boundary); `phases/PHASE_11_OPTIMIZATION.md` (outline); PHASE_08_PLAN; PHASE_10A_PLAN.

---

## 1. Objective

Every day, AdVegaX looks at each running campaign's figures with **fixed rules** and finds the few things worth acting on — for example spend with no sales, a campaign losing money, or a profitable campaign held back by its budget. For each one it prepares a **recommendation**: what it noticed (with the figures), what it proposes, why, how confident it is, its assumptions and risks, and until when it is valid. The AI **explains and ranks**; it never invents the figures or the change.

You approve or reject each one. **Approved → an Action Engine change** (checked again with today's figures and limits). **Rejected → a reason is kept**, and the same advice is not repeated for a while. Afterwards AdVegaX records what happened to the campaign, so recommendations can be judged later.

**Every change made from a recommendation is traceable end to end:** the figures, what the AI said, who approved, every check, what was sent and the result.

## 2. Decisions needed from you (plain language)

Each question has a recommendation. You can approve them all at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-11-1** | What does AdVegaX look for? | Five **fixed rules** per campaign, comparing the **last 7 days** with the campaign's own past (no benchmarks from other businesses):<br>1. **Spend without results** — spent at least the minimum (Q-11-3) with no conversions.<br>2. **Losing money** — the platform's conversion value is below the **break-even** level from your gross margin (Phase 6), for example a 40 % margin needs at least $2.50 back for every $1.<br>3. **Held back by budget** — uses ≥ 95 % of its daily budget while clearly above break-even.<br>4. **Cost per conversion jumped** — at least 30 % higher than its own previous 28 days.<br>5. **Funnel drop-off** — Phase 7's findings, shown as information.<br>A rule never fires on a missing figure (never treated as 0). | Simple, explainable, based only on AdVegaX's own numbers (D17). |
| **Q-11-2** | What can a recommendation propose? | Only what the Action Engine already does: **pause** or **change the daily budget** (an increase of **+20 %**, a decrease of **−20 %**, always within the 10A limits and your maximum). Or **"look into it"** — information with no change (e.g. a funnel drop-off, a campaign with a shared budget). | No new kind of change at the platforms in this phase; 10A's checks protect every one. |
| **Q-11-3** | When is there enough data? | A campaign is judged only with at least **7 full days** of figures, **at least AUD 50 spent** in the 7 days (in your reporting currency; a setting) and, for rules 2–4, at least **5 conversions** in the previous 28 days. Profit rules (2, 3) need a known gross margin for at least 80 % of sales; otherwise they are skipped and the page says why. | Small numbers never trigger advice. |
| **Q-11-4** | What does the AI do? | It receives only the recommendations AdVegaX found and their figures (no personal data, no tokens). It writes the **explanation**, **confidence** (low / medium / high), **assumptions** and **risks**, and **ranks** them. It **cannot** add a campaign, a figure or a different change: the answer is checked against AdVegaX's list and anything else is refused (Phase 8 schema checks). **Without AI** (switched off, no key, daily limit reached), the recommendations still appear with a plain explanation written by AdVegaX, marked "Rules only". | AI explains; deterministic logic decides (D16). Useful even before you add an Anthropic key. |
| **Q-11-5** | How often? | **Once a day per organization**, after the nightly import. Plus **"Look again now"** (owners, admins, managers), at most 3 times a day. Each AI run counts toward the daily AI limit from Phase 8. | Fresh enough for daily figures; keeps AI cost low. |
| **Q-11-6** | How long is a recommendation valid? | **72 hours**, or until the next day's look replaces it, whichever is first. At approval, AdVegaX checks it again: still valid, the campaign's status and budget unchanged since the recommendation, and the rule still true with the latest figures. Otherwise it is marked **out of date** and nothing is sent. | No change based on old numbers. |
| **Q-11-7** | Approving | **Owner or admin: "Approve and send"** creates the change and approves it in one step (the 10A checks and the platform's test run; with "require a second person", it waits for another owner or admin). **Manager: "Request this change"** creates it waiting for approval in Changes. **Analyst:** reads only. | One click for those who may approve; same rules as 10A. |
| **Q-11-8** | Rejecting | A reason from a short list (not relevant / I disagree with the figures / wrong time / other) plus an optional note. The same advice for the same campaign is **not shown again for 14 days** unless the figures get much worse (the loss doubles). | Your "no" is respected and teaches AdVegaX nothing wrong. |
| **Q-11-9** | Outcomes | **7 and 14 days** after a change made from a recommendation, AdVegaX records the campaign's spend, conversions, cost per conversion and conversion value before and after. Shown as **"what happened since"** — not a claim that the change caused it. | Lets you and later phases judge the advice honestly. |
| **Q-11-10** | Where do you see them? | A **Recommendations** page (open, done, rejected, out of date), a count on the **Overview**, and on each **campaign** page. No emails in this phase. | In the places you already look. |
| **Q-11-11** | Which campaigns? | Campaigns imported from your linked Google Ads and Meta accounts that are **running**, with their own daily budget for budget advice (as 10A: not shared Google budgets, not Meta ad-set budgets — those get "look into it"). | The same campaigns the Action Engine can change. |
| **Q-11-12** | Delivery | Tasks 11-01 … 11-08 (§9), **one report at the end** with your review checklist. | As agreed for every phase. |

## 2A. What you need to set up (for Step 0 and real use)

1. An **Anthropic API key** (as Phase 8) — optional: without it you get "Rules only" recommendations.
2. Phase 10A's set-up, to make the approved changes (Google test account, Meta change permission, `ACTIONS_ENABLED=true`).
3. Some weeks of real figures in a linked account, to check the rules give sensible advice.

## 3. Scope

| Area | In Phase 11 |
|---|---|
| Signals | `app/domains/optimization/signals.py`: the five rules over Phase 6 campaign figures and Phase 7 findings; thresholds as settings; every result keeps its figures and why it fired (or why a rule was skipped). |
| Candidates | Each signal maps to one proposed change (or "look into it"), with the exact values (e.g. budget AUD 50.00 → AUD 60.00) computed by AdVegaX and pre-checked with the 10A checks. |
| AI | A new prompt version ("optimizer-v1") with a fixed schema: per candidate id — explanation, confidence, assumptions, risks, rank. Validation refuses unknown ids, changed values, figures not given. An evaluation set as in Phase 8. |
| Lifecycle | `open → approved (→ the change) | rejected | expired | out_of_date | superseded`; the change's own result (done, failed) is shown with it. |
| Engine | `actions.source = recommendation` and `actions.recommendation_id`; nothing else changes in the engine. |
| API | `GET /recommendations`, `GET /recommendations/{id}`, `POST /recommendations/{id}/approve`, `POST /recommendations/{id}/reject`, `POST /recommendations/refresh`; settings for the thresholds (owners, admins). |
| Web app | Recommendations page and detail (the figures, the explanation, confidence, assumptions, risks, what will change, valid until); Overview count; campaign page section; settings. |
| Data | Migration **0022** (§5). |

## 3A. Non-goals

- Making any change without approval (Phase 12).
- New kinds of change: bids, keywords, audiences, creatives, schedules, moving budget between campaigns or platforms.
- Recommendations from other businesses' benchmarks.
- Emails or phone notifications.
- Claims that a change caused an outcome.

## 4. Facts and Step 0

### 4.1 Facts (checked 2026-10-27)

No new platform API is used: recommendations read AdVegaX's own figures, and approved changes use the Phase 10A calls already built and documented (Google `campaigns:mutate`, `campaignBudgets:mutate`; Meta `POST /<campaign id>`). The AI call uses the Phase 8 adapter and Anthropic's structured outputs, as built.

### 4.2 Step 0 — live checks (task 11-01)

1. With your Anthropic key: run the evaluation set; check explanations are accurate, cite only the given figures and never change a proposed value.
2. On a real linked account (read-only is enough): review a week of recommendations with you — are the rules sensible for your stores and margins? Adjust the thresholds.
3. Approve one budget recommendation on a Google test account and see it through Changes.

## 5. Data model (migration 0022)

**`recommendations`** — tenant-owned, forced RLS, never deleted:
- `kind` (`spend_without_results` | `losing_money` | `budget_limited` | `cost_jump` | `funnel_drop`);
- `campaign_id` (optional — none for a business-wide funnel finding), `ad_account_id`;
- `signal` (JSONB: the figures and periods behind it), `proposal` (JSONB: change type and values, or `none`), `campaign_state` (status and budget when it was made);
- `explanation`, `confidence`, `assumptions[]`, `risks[]`, `rank`, `explained_by` (`ai` | `rules`), `ai_run_id`;
- `status`, `expires_at`, `fingerprint` (campaign + kind: one open recommendation each);
- `decided_by`, `decided_at`, `decision_reason`, `decision_note`, `action_id`;
- timestamps.

**`recommendation_outcomes`** — `recommendation_id`, `after_days` (7 | 14), `before` / `after` (JSONB figures), `created_at`.

**Other tables:** `actions` gains `recommendation_id`; organization settings gain the thresholds.

## 6. API

As §3. New errors:
- `RECOMMENDATION_OUT_OF_DATE` (409, with the reason);
- `RECOMMENDATION_CLOSED` (409: already decided or expired);
- `REFRESH_LIMIT` (429).

Plus 10A's errors when the change itself is refused.

## 7. Security

- The AI gets only the candidates and their figures: no personal data, store text delimited and cleaned as in Phase 8, no tokens; its answer cannot add or alter a change (A12).
- Approval goes through the same permissions, second-person rule, limits, switches and platform test as any 10A change; the engine stays the only way to change a platform.
- Every recommendation, decision and resulting change is audited (`recommendation.created | approved | rejected | expired | out_of_date`), with `actor_type = ai_recommendation` where the AI wrote the explanation.
- Tenant isolation: forced RLS; the route sweep covers every new route.

## 8. Testing

- **Rules:** each of the five fires on the right figures and never on missing figures, small numbers or unknown margins; thresholds respected.
- **Candidates:** exact values, 10A limits applied, shared budgets → "look into it".
- **AI (simulator):** a valid answer; an answer with an unknown id, a changed value or an invented figure is refused and retried once; AI off → "Rules only".
- **Lifecycle:** expiry, replacement by the next day, out of date when the campaign changed, the 14-day quiet period after a rejection, one open recommendation per campaign and kind.
- **Approval:** owner one-step, manager request, analyst refused, second-person rule, a 10A refusal shown plainly; never sent twice.
- **Outcomes:** recorded at 7 and 14 days, missing figures shown as not available.
- **Web app and browser:** page tests, and one browser test with accessibility checks: a recommendation appears with its figures and explanation, one is rejected with a reason, one is approved and the change appears under Changes.

## 9. Tasks (one report for the whole phase)

| Task | Content |
|---|---|
| 11-01 | Step 0 (§4.2) — needs your Anthropic key and a linked account |
| 11-02 | Migration 0022; signals (the five rules); thresholds |
| 11-03 | Candidates and their pre-checks |
| 11-04 | AI explanation and ranking: prompt, schema, validation, evaluation set, "Rules only" |
| 11-05 | Lifecycle: daily run, refresh, expiry, out of date, rejection quiet period; outcomes |
| 11-06 | API; approval into the Action Engine; roles; audit |
| 11-07 | Web app: Recommendations, detail, Overview count, campaign section, settings |
| 11-08 | Tests, browser test, `PHASE_11_REPORT.md` with your review checklist |

## 10. Acceptance criteria

1. Each day AdVegaX finds the campaigns that match the rules, with their figures, and never on missing or too-small figures.
2. Every recommendation shows what was noticed, the proposed change with exact values, the explanation, confidence, assumptions, risks and validity.
3. Nothing changes at a platform without an approval; approval creates a 10A change, checked again.
4. An out-of-date or expired recommendation sends nothing.
5. Rejections keep the reason and are respected.
6. Outcomes are recorded at 7 and 14 days.
7. Every executed recommendation is traceable end to end; all suites pass, with no platform or AI calls in CI.

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Bad advice wastes money | HIGH | Fixed rules on your own figures; small steps (±20 %); 10A limits; approval required; outcomes recorded |
| The AI misstates figures | MEDIUM | It cannot change values or add figures (validated); the figures shown come from AdVegaX, not the AI |
| Too many recommendations | MEDIUM | One per campaign and kind; minimum spend and data; ranking; quiet period after a rejection |
| Platform attribution is wrong | MEDIUM | Platform conversions are labelled as the platform's; profit rules need a known margin; "look into it" where unsure |

## 12. Rollback

Set the recommendations switch off (`OPTIMIZATION_ENABLED=false`) to stop new recommendations; existing changes are untouched. `ACTIONS_ENABLED=false` still stops all sending. Migration 0022 is reversible.

## 13. Approval checklist

Approve or change:
- **Q-11-1 … Q-11-12**;
- Step 0 (§4.2);
- the data model (§5);
- delivery 11-01 … 11-08, with one report at the end of the phase.

No new library is needed.
