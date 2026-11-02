# Phase 12 — Controlled Autopilot: Implementation Plan

**Status:** ✅ **Approved 2026-10-27 (A31, "Approve all": Q-12-1 … Q-12-12).** In progress — see `PHASE_12_PROGRESS.md`. · **Date:** 2026-10-27

> For the first time, AdVegaX could make a change **without a person approving that change**. So autopilot is **off by default at every level**, limited to changes that **only lower spend**, bounded by hard limits in AdVegaX's own code, stopped by one click, and switched off by itself when anything looks wrong. Built and tested against the simulators (no platform or AI calls in CI).

**Depends on:**
- Phase 10A — the Action Engine (every automatic change goes through it, with every check);
- Phase 11 — recommendations (autopilot acts only on advice AdVegaX's rules found).

**Prerequisite (ROADMAP principle 5, "assisted mode proven first"):** the code can be built now, but an organization can switch autopilot on only after AdVegaX has **made and verified changes approved by people** for it (Q-12-5), and only if the installation allows it (Q-12-11). Step 0 for 10A and 11 should be done before any real use.

**Governing documents:** MASTER_SPECIFICATION ("Autopilot: only approved action classes within hard limits"); D16; A2; DISCOVERY_REPORT risk 3 (overspend, compounding changes) and Q13; `phases/PHASE_12_AUTOPILOT.md` (outline); PHASE_10A_PLAN; PHASE_11_PLAN.

---

## 1. Objective

An owner can let AdVegaX **act on its own** on a small, named set of recommendations — within limits they can see and change, for the ad accounts they choose — and stop it at any moment. Every automatic change is an ordinary Action Engine change, recorded with **the policy that allowed it**, shown under Changes as "Made by autopilot", can be undone, and is emailed to the owners the same day.

**Autopilot never raises a budget, never resumes a campaign and never creates anything.**

## 2. Decisions needed from you (plain language)

Each question has a recommendation. You can approve them all at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-12-1** (Q13) | Which changes may run by themselves? | Only two kinds, both of which **lower** spend:<br>1. **Pause** a campaign that spent without results (Phase 11 rule 1).<br>2. **Lower the daily budget** of a campaign that is losing money (rule 2).<br>Raising budgets, resuming and everything else always needs a person. You can allow one, both or neither. | The worst an automatic change can do is reduce spend for a while. |
| **Q-12-2** | Who may switch it on? | **Owners only**, by typing the organization's name to confirm. Admins and managers can see the settings; **anyone** with change rights (owner, admin, manager) can **stop** it. | A standing approval is the owner's decision. |
| **Q-12-3** | Where does it act? | Only on the **ad accounts the owner picks**; any campaign can be **excluded**. New ad accounts are not included automatically. | Start small; nothing is included by surprise. |
| **Q-12-4** | Hard limits (defaults, owners can lower them; only the installation can raise the ceilings) | • at most **5** automatic changes per organization a day;<br>• at most **1** per campaign in **7 days**;<br>• a budget lowered by at most **20 %** at a time and **50 %** in total over **30 days** (no compounding);<br>• only campaigns running for at least **14 days**;<br>• the Phase 11 data thresholds (minimum spend and conversions) apply;<br>• all 10A limits apply on top. | Bounded even if the rules misfire every day. |
| **Q-12-5** | When may it be switched on at all? | Only after AdVegaX has made at least **5 changes from recommendations approved by a person** for this organization, all **verified** on the platform, none mismatched. | "Assisted mode proven first" — measured, not assumed. |
| **Q-12-6** | How does it run? | Right after the daily look: each new recommendation of an allowed kind, in an included account, within every limit, is **approved by "Autopilot"** through the same path as a person's approval (checked again, platform test, read back, verified). Anything that does not fit stays as normal advice for a person. | One path for every change; nothing new can bypass a check. |
| **Q-12-7** | How will you know? | Under Changes: **"Made by autopilot"** with the policy that allowed it; the advice shows it; an **email to the owners** after each run that changed something (what, why, and an Undo link); the Overview shows autopilot's state. | No silent changes. |
| **Q-12-8** | Stopping | **"Stop autopilot"** — one click, no confirmation, takes effect immediately. Also stopped by "Pause all changes" (10A) and the installation switch. Changes already sent are not undone automatically (each has Undo). | Stopping must be easier than starting. |
| **Q-12-9** | Stopping itself | Autopilot **switches itself off** for the organization (and emails the owners) when: an automatic change fails, is not verified or its outcome is unknown; the platform refuses; a connection needs attention; or the day's limit is reached twice in 7 days. An owner must switch it on again. | A surprise means a person should look. |
| **Q-12-10** | Undo | Every automatic change can be undone from Changes, as in 10A (the undo needs a person's approval). | Same safety net as every change. |
| **Q-12-11** | Rollout | The installation switch **`AUTOPILOT_ENABLED`** (off by default) and an **allow-list of organizations** (`AUTOPILOT_ORGANIZATIONS`): your own businesses first, others later. | Staged, as the outline requires. |
| **Q-12-12** | Delivery | Tasks 12-01 … 12-07 (§9), **one report at the end** with your review checklist. | As agreed for every phase. |

## 2A. What you need to set up (for Step 0 and real use)

1. Phase 10A and 11 set-up and Step 0 (test accounts, "Allow changes", your maximum daily budget).
2. At least 5 approved, verified changes from recommendations on the account (Q-12-5).
3. Your organization's id in `AUTOPILOT_ORGANIZATIONS`, and `AUTOPILOT_ENABLED=true`.

## 3. Scope

| Area | In Phase 12 |
|---|---|
| Policy | `app/domains/autopilot/`: one policy per organization — on/off, who switched it on and when, allowed kinds, included ad accounts, excluded campaigns, the limits; stopped by whom or why. |
| Gate | The readiness check (Q-12-5), the allow-list and switches (Q-12-11). |
| Runner | After each daily look: the eligible advice, every limit (including the 30-day cumulative decrease), then approval as "Autopilot" through `RecommendationService` → Action Engine. A per-organization lock so two runs never overlap. |
| Watchdog | After each automatic change settles (and in the 10A sweep): the self-stop rules (Q-12-9). |
| Engine | `actions.source` gains `autopilot`; `actions.policy` keeps the policy snapshot that allowed it; audit actor `autopilot`. |
| Notifications | An email to the owners after a run that changed something, and when autopilot stops itself (Phase 1 email outbox). |
| API | `GET/PUT /autopilot` (policy), `POST /autopilot/enable` (owner, with the typed confirmation), `POST /autopilot/stop`, `GET /autopilot/runs`. |
| Web app | Settings → **Autopilot** (readiness, kinds, accounts, exclusions, limits, enable with confirmation, Stop); "Made by autopilot" under Changes and on advice; the Overview state. |
| Data | Migration **0023** (§5). |

## 3A. Non-goals

- Automatic budget increases, resumes, creation, keyword/ad/bid changes.
- Automatic undo of automatic changes.
- Autopilot without Phase 11's rules (no AI-decided changes; the AI still only explains).
- Spend guarantees: platforms can spend more than the daily budget on a given day; "limits" limit what AdVegaX sets and does.

## 4. Facts and Step 0

### 4.1 Facts (checked 2026-10-27)

1. No new platform API: automatic changes use the Phase 10A calls already built.
2. **Google Ads** ("Manage your spend in Google Ads", support.google.com/google-ads/answer/1704424): a campaign can spend up to **twice** its average daily budget on a given day, while not charging more than the daily budget × the average days in a month over the month.
3. **Meta**: practitioner write-ups (e.g. Jon Loomer, "Updates to Meta Ads Budgeting") report that Meta may spend up to **75 %** more than a daily budget on a given day while keeping the weekly total within 7 × the daily budget; confirmed against Meta's own help pages in Step 0.

So AdVegaX presents its limits as limits on **what it changes**, never as a guarantee of a day's spend — as the outline notes.

### 4.2 Step 0 — live checks (task 12-01)

1. On a Google test account and your own Meta account: switch autopilot on for one account, let it pause a campaign that spent without results, check the email, the "Made by autopilot" change and its Undo.
2. Force a failure (remove "Allow changes") and see autopilot stop itself and email you.
3. Review the limits with you after a week.

## 5. Data model (migration 0023)

**`autopilot_policies`** — tenant-owned, forced RLS, one row per organization:
- `enabled`, `enabled_by`, `enabled_at`, `stopped_by`, `stopped_at`, `stopped_reason`;
- `kinds` (allowed: `spend_without_results`, `losing_money`), `ad_account_ids` (included), `excluded_campaign_ids`;
- `max_changes_per_day`, `campaign_cooldown_days`, `max_decrease_percent`, `max_cumulative_decrease_percent`, `cumulative_window_days`, `min_campaign_age_days`;
- `updated_by`, `updated_at`.

**`autopilot_runs`** — tenant-owned, forced RLS, never deleted: when, considered, made (action ids), skipped (recommendation id and reason), stopped (reason).

**Other tables:** `actions.source` allows `autopilot`; `actions.policy` (JSONB snapshot); audit actor `autopilot`.

## 6. API

As §3. New errors:
- `AUTOPILOT_NOT_READY` (409, with what is missing: allow-list, switch, verified changes);
- `AUTOPILOT_CONFIRMATION` (422: the typed name does not match).

Plus 10A's and 11's errors.

## 7. Security

- Every automatic change goes through the Action Engine with every check, the platform test, read-back and verification; the policy and limits are checked in AdVegaX's code before and again under the organization's lock.
- Only spend-reducing changes; no path in the code can make an automatic increase (tested).
- Only owners enable; anyone with change rights stops; every enable, stop, policy change and automatic change is audited with the policy snapshot.
- Tenant isolation: forced RLS; the route sweep covers every new route.

## 8. Testing

- **Limits:** day limit, campaign cooldown, per-change and 30-day cumulative decrease, campaign age, excluded campaigns and accounts, the 10A limits — each refused at its edge.
- **Gate:** not ready (no allow-list, switch off, too few verified changes, a mismatch) → cannot enable.
- **Kill switch:** Stop, "Pause all changes", the installation switch — no automatic change after any of them, including a run already started.
- **Self-stop:** failure, not verified, unknown outcome, platform refusal, connection needing attention, the day limit twice.
- **Never an increase:** a "held back by budget" or any other kind is never approved by autopilot.
- **Concurrency:** two runs at once make each change once.
- **Notifications:** emails after a run with changes and after a self-stop; none after a run with no changes.
- **Web app and browser:** page tests, and one browser test with accessibility checks: readiness, enabling with confirmation, a change made by autopilot under Changes, Stop.

## 9. Tasks (one report for the whole phase)

| Task | Content |
|---|---|
| 12-01 | Step 0 (§4.2) — needs the 10A/11 set-up and verified changes |
| 12-02 | Migration 0023; policy, gate, switches |
| 12-03 | Runner: eligibility, limits (including cumulative), approval as "Autopilot"; lock |
| 12-04 | Watchdog and self-stop; notifications |
| 12-05 | API; roles; audit |
| 12-06 | Web app: Settings → Autopilot, "Made by autopilot", Overview |
| 12-07 | Tests, browser test, `PHASE_12_REPORT.md` with your review checklist |

## 10. Acceptance criteria

1. Autopilot is off unless the installation, the allow-list, readiness and an owner's confirmed choice all allow it.
2. It acts only on allowed kinds of advice, in included accounts, within every limit, through the Action Engine.
3. It never raises spend.
4. Stop, "Pause all changes" and the installation switch stop it at once.
5. It stops itself on any failure or surprise and tells the owners.
6. Every automatic change is audited with the policy that allowed it, emailed, and can be undone.
7. Limit-breach, cooldown and kill-switch tests pass; all suites pass, with no platform calls in CI.

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| A rule misfires repeatedly and pauses good campaigns | HIGH | Only after proven assisted changes; small daily and per-campaign limits; owners emailed each time; Undo; self-stop |
| Compounding budget cuts | HIGH | Per-change and 30-day cumulative limits; cooldown |
| A platform over-delivers | MEDIUM | Autopilot only lowers spend; limits are on AdVegaX's changes, stated as such |
| An owner forgets it is on | MEDIUM | Overview state, emails, Settings banner |

## 12. Rollback

"Stop autopilot", `AUTOPILOT_ENABLED=false`, or removing the organization from `AUTOPILOT_ORGANIZATIONS`. Migration 0023 is reversible. Phases 10A and 11 are unaffected.

## 13. Approval checklist

Approve or change:
- **Q-12-1 … Q-12-12**;
- Step 0 (§4.2);
- the data model (§5);
- delivery 12-01 … 12-07, with one report at the end of the phase.

No new library is needed.
