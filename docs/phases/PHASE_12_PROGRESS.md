# Phase 12 — Progress (Controlled Autopilot)

Plan: `PHASE_12_PLAN.md` (approved 2026-10-27, A31, all recommendations Q-12-1 … Q-12-12). Built task by task; **one report for the whole phase** (`PHASE_12_REPORT.md`).

| Task | Status |
|---|---|
| 12-01 Step 0: autopilot on a Google test account and your own Meta account; a forced failure; a week's review | ⏸ Waiting for the Phase 10A/11 set-up, Step 0 and verified changes |
| 12-02 Migration 0023; policy, gate, switches | ✅ Done |
| 12-03 Runner: eligibility, limits (including cumulative), approval as "Autopilot"; lock | ✅ Done |
| 12-04 Watchdog and self-stop; emails | ✅ Done |
| 12-05 API; roles; audit | ✅ Done |
| 12-06 Web app: Settings → Autopilot, "made by autopilot", Overview | ✅ Done |
| 12-07 Tests, browser test, `PHASE_12_REPORT.md` | ✅ Done — Phase 12 awaiting review |

## 12-01 — Step 0

**Blocked:** needs the Phase 10A and 11 set-up and Step 0, at least 5 verified changes from approved advice, your organization in `AUTOPILOT_ORGANIZATIONS` and `AUTOPILOT_ENABLED=true` (plan §2A, §4.2).

## 12-02 — Policy and gate

- **Migration 0023** (additive, reversible): `autopilot_policies` (one per organization), `autopilot_runs`; `actions.source` allows `autopilot` and `actions.policy` keeps the policy that allowed each automatic change; the audit log accepts the actor `autopilot`.
- **The gate:** the installation switch and allow-list; **readiness** — at least 5 changes from advice approved by a person, all verified, none mismatched; an owner's choice; the Action Engine's switches.
- **The policy:** the kinds (only "spend without results" → pause and "losing money" → a lower budget), the included ad accounts, excluded campaigns and six limits, which can only be stricter than the installation's ceilings.

## 12-03 — Runs

After each daily look (and "Look again now"), one run at a time per organization: each open advice of an allowed kind, by rank, in an included account and not excluded, within the day's limit, the campaign cooldown, the per-change and 30-day cumulative cut and the campaign age; checked again like a person's approval; then requested and approved by autopilot through the Action Engine (every 10A check, the platform's test, read-back, verification). A proposal that would not lower spend is refused by name (`not_a_decrease`). Everything skipped is recorded with its reason.

## 12-04 — Watchdog and emails

Autopilot stops itself when an automatic change fails, is refused, is not verified or its outcome is unknown, or when the day's limit was reached twice within 7 days. Owners get an email after each run that changed something (each change, with a link to Changes) and when it stops itself.

## 12-05 — API

`/autopilot` (read, policy, enable with the typed name, stop, runs) — API_SPECIFICATION §19M. Owners change the policy and switch it on; owners, admins and managers can stop it. The Action Engine gained a request and an approval without a signed-in person, used only by autopilot.

## 12-06 — Web app

**Settings → Autopilot:** on/off (and why it stopped), readiness in plain words, what it may do, which ad accounts and excluded campaigns, the limits and the installation's ceilings, **Switch autopilot on** (type the name), **Stop autopilot**, the recent runs. **Changes** marks "(made by autopilot)" and links each change to its advice. The **Overview** says when autopilot is on.

## 12-07 — Tests and report

API tests against the Google Ads simulator (gate, roles, ceilings, pause and cut, never an increase, every limit, Stop, "Pause all changes", self-stop, the day limit, emails), unit tests, page tests, the browser test (`e2e/autopilot.spec.ts`) and the report.
