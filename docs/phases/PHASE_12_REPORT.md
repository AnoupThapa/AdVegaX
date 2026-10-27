# Phase 12 — Implementation Report (Controlled Autopilot)

**Status:** Implemented — awaiting your review. Step 0 (live checks, 12-01) waits for the Phase 10A/11 set-up, verified changes and the installation switch.
**Plan:** `PHASE_12_PLAN.md`, approved 2026-10-27 (A31, all recommendations; answers Q13).
**Progress log:** `PHASE_12_PROGRESS.md`.

## 1. Summary

An owner can now let AdVegaX act **on its own** on two kinds of advice that only **lower** spend:

1. **Pause** a campaign that spent without results.
2. **Lower the daily budget** of a campaign that is losing money.

It never raises a budget, never resumes, never creates anything — a proposal that would not lower spend is refused by name.

Autopilot is **off at every level** until:

- the installation switches it on (`AUTOPILOT_ENABLED`) for listed organizations (`AUTOPILOT_ORGANIZATIONS`);
- the organization is **ready** — at least 5 changes from advice approved by a person, all verified on the platform;
- an **owner** includes ad accounts and switches it on by **typing the organization's name**.

Each automatic change is an ordinary Action Engine change — checked again, tested by the platform, read back, verified — recorded with **the policy that allowed it**, shown under Changes as "made by autopilot", emailed to the owners and can be **undone**.

**Hard limits** (owners may only make them stricter): 5 automatic changes a day; one per campaign per 7 days; a cut of at most 20 % at a time and 50 % over 30 days; campaigns running for at least 14 days. **Stop autopilot** is one click for owners, admins and managers; "Pause all changes" and the installation switch also stop it. It **stops itself** — and emails the owners — when a change fails, is refused, is not verified or its outcome is unknown, or when it reaches its daily limit twice in a week.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 12-01 | ⏸ Step 0 — waiting (§10) |
| 12-02 | Migration 0023; the policy, readiness, allow-list and switches |
| 12-03 | Runs after each look; every limit, including the cumulative cut; approval by autopilot through the Action Engine; one run at a time |
| 12-04 | Watchdog and self-stop; emails to owners |
| 12-05 | `/autopilot` API (§19M); owners only to switch on; audit with the actor `autopilot` |
| 12-06 | Settings → Autopilot; "made by autopilot" under Changes; Overview banner |
| 12-07 | Tests (§5), browser test, this report |

## 3. Acceptance criteria (plan §10)

| # | Criterion | Result |
|---|---|---|
| 1 | Off unless installation, allow-list, readiness and an owner's confirmed choice allow it | ✅ |
| 2 | Acts only on allowed kinds, included accounts, within every limit, through the Action Engine | ✅ |
| 3 | Never raises spend | ✅ (`not_a_decrease`; "held back by budget" never acted on — tested) |
| 4 | Stop, "Pause all changes" and the installation switch stop it at once | ✅ |
| 5 | Stops itself on any failure or surprise and tells the owners | ✅ |
| 6 | Every automatic change audited with its policy, emailed, can be undone | ✅ |
| 7 | Limit, cooldown and kill-switch tests pass; all suites pass, no platform calls in CI | ✅ (§5) |

## 4. Security controls

- **Same path as people:** autopilot's request and approval run every 10A check, limit and switch; the Action Engine stays the only way to change a platform.
- **Spend-reducing only**, checked in code before every change.
- **Owners only** change the policy or switch it on (new permission `autopilot.manage`); anyone with change rights stops it.
- **One run at a time** per organization (a lock); the policy snapshot is kept on each change.
- **Tenants:** both tables forced RLS; the route sweep covers every new route.
- **Audit:** enabled, policy updated, stopped (by whom or why), each run, each automatic request and approval (actor `autopilot`).

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, static rules, pytest) | ✅ 2,069 tests. The full run: 2,066 passed, coverage 95.4 %; one older email-template test lacked the new templates' fields — fixed and rerun with the two new browser-helper tests, all passing |
| Frontend `npm run check` (types, lint, format, Vitest) | ✅ 563 passed (branch coverage 85.2 %) |
| Browser (Playwright + accessibility) | ✅ 19 passed (new: `autopilot.spec.ts`). In the full run the Phase 1 journey hit a one-off page hydration warning (as seen before with WooCommerce); it passed twice on rerun |

New: `tests/api/test_autopilot_api.py`, `tests/unit/test_autopilot_rules.py`, `tests/api/test_e2e_autopilot_seed.py`, `frontend/tests/features/autopilot.test.tsx`, `frontend/e2e/autopilot.spec.ts`.

## 6. Database

Migration **0023** (additive, reversible): `autopilot_policies`, `autopilot_runs`; `actions.source` allows `autopilot`, `actions.policy`; `audit_logs.actor_type` allows `autopilot`. DATABASE_SCHEMA §14F.

## 7. New libraries

None.

## 8. Defects found and fixed

- An empty policy was stored as JSON `null` rather than no value, which the database refused for people's changes; it is now stored as no value.
- A run record was updated after it was written (runs are insert-only); the outcome is now decided before it is written.

## 9. Deviations from the plan

1. **The Action Engine gained a request and an approval without a signed-in person**, used only by autopilot; the code shared with people's requests is the same.
2. **Campaign age** is the platform's start date, or else the first day AdVegaX has figures for the campaign.
3. **The cumulative cut** is measured from the budget before the first automatic cut within the window.
4. **Emails** go to every active owner of the organization.
5. **Runs** follow each daily look and "Look again now" — no separate schedule.

## 10. Not verified in this environment — Step 0 (12-01)

1. On a Google test account and your own Meta account: autopilot pauses a campaign that spent without results; the email, "made by autopilot" and Undo.
2. A forced failure (remove "Allow changes") stops autopilot and emails you.
3. Your Meta budget behaviour (Meta's own pages on daily over-delivery), and a week's review of the limits.

## 11. Known limitations

- Only two kinds of change; no automatic budget increases (by design).
- Platforms can spend more than a daily budget on a single day; AdVegaX limits what it changes, not a day's spend.
- No phone notifications; emails only.

## 12. Your review checklist

**A. Decide or confirm (business):**

1. Only **pause** and **budget cuts** run automatically (Q-12-1).
2. The default **limits**: 5 a day; 1 per campaign per 7 days; 20 % per cut, 50 % over 30 days; campaigns at least 14 days old.
3. **Readiness:** 5 verified changes from approved advice.
4. **Owners only** switch it on; owners, admins and managers can stop it.
5. The deviations in §9.

**B. Try it in the app** (after Step 0, on a test account):

1. **Settings → Autopilot:** read the readiness list.
2. Choose what it may do and **one** ad account; Save.
3. Type the organization's name → **Switch autopilot on**; the Overview shows it is on.
4. After the next daily look (or **Look again now** on Recommendations): see the change under **Changes**, "made by autopilot", and your email.
5. **Undo** the change from Changes; then **Stop autopilot**.

**C. Set up when you are ready:**

1. Phase 10A and 11 set-up and Step 0.
2. Approve at least 5 recommendations yourself, and check each was verified.
3. Add your organization's id to `AUTOPILOT_ORGANIZATIONS` and set `AUTOPILOT_ENABLED=true` in the local settings file.

**D. Documents to read:**

- this report;
- `PHASE_12_PROGRESS.md`;
- API_SPECIFICATION §19M;
- DATABASE_SCHEMA §14F.

## 13. Next

1. **Your review** of Phase 12 (§12), and of Phases 8 – 11 if not done yet.
2. **Step 0** for Phases 8 – 12 once keys and accounts are in place.
3. Then **Phase 13 — Stripe billing**. Its plan comes to you for approval first.
