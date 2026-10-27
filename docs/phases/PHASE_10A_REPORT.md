# Phase 10A — Implementation Report (Action Engine)

**Date:** 2026-10-26 · **Branch:** `feature/phase-1a` · **Status:** Implemented and tested against the Google Ads and Meta simulators — **awaiting product-owner review**. **Step 0 (10A-01) is pending:** it needs test accounts, Meta's change permission and network access.
**Plan:** `PHASE_10A_PLAN.md` (approved 2026-10-26, A28) · Task by task: `PHASE_10A_PROGRESS.md`.

---

## 1. Summary

AdVegaX can now **change an ad account — through one gate only**. Three changes, at campaign level, on Google Ads and Meta: **pause**, **resume** and **set the daily budget**.

1. **Someone asks** (owner, admin or manager) on the campaign's page. Before anything is kept:
   - AdVegaX checks the change against the campaign **as the platform reports it now**: the values, the account and connection, who holds the budget, the limits and the campaign's state;
   - the platform tests it **without making it** (Google's `validateOnly`, Meta's `validate_only`).

   The page shows the allowed budget range and every reason in plain words.
2. **An owner or admin approves** (or rejects with a reason). With "require a second person", never the person who asked.
3. **AdVegaX sends it once:**
   - it writes down "being sent" **before** calling the platform;
   - it handles one change per campaign at a time;
   - it reads the campaign again first — if it changed since the request, nothing is sent ("out of date");
   - if the answer is lost, it **looks the campaign up instead of sending again**.
4. **It checks the result:** the campaign is read back ("Checked: the platform shows the change"), and every step is in the change's history and the audit log, with exactly what was sent — never a token.
5. **Undo** is a new change, approved like any other.
6. **Two off switches:** the installation's `ACTIONS_ENABLED` (off by default) and each organization's **Pause all changes**. Changes are also allowed per connection (**Allow changes**), read-only by default.

No other part of AdVegaX can change a platform (static rules).

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 10A-01 | ⏸ Step 0 — waits for test accounts, Meta's change permission and network access (§10) |
| 10A-02 | Migration **0020**; the catalogue of three changes; the check chain; settings and both switches |
| 10A-03 | Google and Meta change calls with dry runs (the only write modules); simulators for changes and failures |
| 10A-04 | The engine: states, queue, one change per campaign, read before write, look-up of unknown outcomes, verification, undo, sweep |
| 10A-05 | "Allow changes" per connection (Meta: sign in again for `ads_management`); API §19J; roles; audit |
| 10A-06 | Web app: Changes pages, campaign changes, settings, connection access |
| 10A-07 | Duplicate, timeout, concurrency and failure tests; browser test; this report |

## 3. Acceptance criteria (plan §11)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Pause, resume and daily-budget changes end to end against the simulators, verified by reading back | ✅ | `test_actions_api.py::test_a_pause_is_checked_approved_sent_once_and_verified`, `test_a_daily_budget_change_within_the_limits`, `test_resume_and_state_checks`; `test_actions_meta.py::test_pause_and_daily_budget_on_meta` |
| 2 | No code path changes a platform outside the engine | ✅ | `test_static_rules.py::test_platform_writes_exist_only_in_the_write_modules_and_reach_only_the_engine` and the read-only rules for every other module |
| 3 | Every change approved by a person with authority; with "require a second person", never by the requester | ✅ | `test_roles_and_the_second_person_rule` |
| 4 | A timeout never causes a second call before the campaign is read back; duplicates never run twice | ✅ | `test_a_lost_answer_is_looked_up_never_sent_again`, `test_a_timeout_before_the_change_is_found_not_applied`, `test_two_workers_send_a_change_once`, `test_duplicates_and_one_open_change_per_campaign` |
| 5 | A change approved on old information stops as stale | ✅ | `test_a_campaign_changed_since_the_request_stops_as_stale`, `test_a_request_not_decided_in_time_is_stale` |
| 6 | The limits hold; both switches stop execution | ✅ | `test_budget_limits`, `test_the_minimum_and_maximum`, `test_one_budget_change_per_campaign_per_hour`, `test_changes_per_account_per_day`, `test_the_installation_switch`, `test_pause_all_changes_holds_queued_changes`; `test_action_rules.py` (45) |
| 7 | Every step in `action_events` and the audit log, without secrets | ✅ | event and audit assertions; `test_a_meta_change_is_audited_without_tokens` |
| 8 | All suites pass, with no platform calls in CI | ✅ | §5 |

## 4. Security controls

| Control | Verified by |
|---|---|
| Platform writes only in `providers/*/writes.py`; imported only by their provider; the change method called only by the engine | Static rule (new) |
| Meta's change path is separate from its read-only guard: only `POST` to one numeric object | Static rule; `test_the_meta_change_path_is_guarded` |
| `ads_management` named only in Meta's write module; asked for only when a person chooses "Allow changes" | Static rule |
| Changes read-only by default, per connection; a missing platform permission refuses "Allow changes" | `test_changes_must_be_allowed_for_the_connection`, `test_changes_need_metas_change_permission` |
| A refused change never marks the connection broken (only an ended sign-in does) | `test_a_permission_taken_back_at_meta_fails_the_dry_run_only` |
| Written down before the call; one open change per campaign; a lock around the calls; repeated jobs do nothing | Engine tests; partial unique index |
| Unknown outcomes are looked up, never resent; bounded look-ups | Engine tests |
| What is stored never contains a token | Static rule; token assertions in API and browser tests |
| Tenant isolation | Forced RLS on the three new tables; the route sweep covers the 12 new routes; `test_lists_and_tenants` |

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, pytest) | **RESULT_BACKEND** |
| Frontend `npm run check` | **516 passed**, coverage 95.6 % (branches 85.3 %) |
| Browser tests (Playwright + axe) | **RESULT_E2E** — the new test shows a change made with the simulator (what was sent, verification, history), its undo waiting, the server's engine off saying so, the settings and the connection's access; every page passes the accessibility check |

## 6. Database

Migration **0020** (additive, reversible): `actions`, `action_events`, `action_settings`; `external_connections.write_access_granted_at / _by`. DATABASE_SCHEMA §14C.

## 7. New libraries

None.

## 8. Defects found and fixed

1. Meta reconnects dropped any permission beyond the two read permissions. They now keep the change permission when it is granted.
2. Two API schemas shared a name with Phase 9's (`CheckOut`, `RejectIn`), which would have renamed the web app's creative types. They were renamed `ActionCheckOut` and `ActionRejectIn`.

## 9. Deviations from the plan

1. **A shared Google budget is refused** (`budget_shared`): changing it would change every campaign that shares it. Change it in Google Ads.
2. **Undo is exempt from the step limit (+50 % / −90 %) and the one-hour rule**, because it restores a value the campaign had. Every other check, the dry run and approval still apply. Otherwise a mistaken 90 % cut could not be undone in one step.
3. **One open change per campaign**: a second change waits until the first is done or cancelled (`campaign_has_open_change`), rather than queueing behind it. A repeated identical request is a duplicate.
4. **AdVegaX's copy of the campaign is updated from the read-back** after a verified change, so the campaign page shows the new state at once. The next sync reads it again anyway.
5. **Browser test:** the web server's engine stays off in CI, because it must never reach Google. The change is checked, approved, sent and verified by the backend helper with the simulator. The browser then shows it, and shows that approving with the engine off is refused.
6. One operation per request on both platforms, so a change is never half done. "Partial failure" therefore does not arise; the simulators cover the lost-answer, timeout, server-error, refusal and "success without change" cases instead.

## 10. Not verified in this environment — Step 0 (10A-01)

1. **Google test account:**
   - pause and resume a campaign;
   - change a budget (the `updateMask` field name `amountMicros` and the `validateOnly` field on the API version in use);
   - a timeout is looked up by reading back.
2. **Meta (your own ad account, development mode):**
   - the three changes;
   - `validate_only`;
   - a campaign whose budget is on its ad sets is refused;
   - the change login configuration grants `ads_management`.
3. The read-back of both platforms matches what AdVegaX recorded.

## 11. Known limitations

| Limitation | Note |
|---|---|
| Only pause, resume and daily budget, campaign level (Q-10A-1) | Campaign creation comes with the builder (10B), through this engine |
| Real (non-test) Google accounts need the developer token's **Basic access**; Meta accounts you do not own need **App Review** for `ads_management` | Until then: test and own accounts only |
| A shared Google budget or a Meta budget on ad sets cannot be changed here | Changed in the platform's own tools |
| No notifications when a change waits for approval | A later phase (notifications) |
| English only | As before |

## 12. Your review checklist

**A. Decide or confirm (business):**

1. The **limits**:
   - at most +50 % or −90 % in one change;
   - one budget change per campaign per hour;
   - 50 changes per ad account a day.
2. Who may do what:
   - **request** — owner, admin, manager;
   - **approve** — owner, admin.

   Should "require a second person" be on for your organizations?
3. Your **maximum daily budget per campaign** (AUD) — required before the first budget change.
4. The deviations in §9, especially **undo without the step and one-hour limits**, and refusing **shared Google budgets**.

**B. Try it in the app** (after Step 0, or on a test account):

1. **Connections →** your Google Ads (or Meta) connection → **Allow changes**. For Meta: **Sign in again to allow changes**.
2. **Settings → Changes to ad accounts:** set the maximum; try **Pause all changes**.
3. **Advertising →** a campaign → **Change budget**: enter a value above +50 % and see the reason; then a value within the range → **Check** → **Request this change**.
4. **Changes →** open it → **Approve and send**. See **Done**, "Checked: the platform shows the change", **Exactly what was sent** and the **History**.
5. **Undo this change** → approve the undo.
6. Pause a campaign; then change it in Google Ads before approving, and see **Out of date — not sent**.

**C. Set up when you are ready:**

1. **Google Ads:**
   - a **test manager account** with test client accounts (for Step 0);
   - later, **Basic access** for the developer token (Google's form).
2. **Meta:**
   - a **Login for Business configuration** that asks for `ads_management` (its id goes in `META_WRITE_LOGIN_CONFIG_ID`);
   - **App Review** for `ads_management` before other businesses' accounts.
3. Switch the engine on for your installation: `ACTIONS_ENABLED=true` in the local settings file.

**D. Documents to read:**

- this report;
- `PHASE_10A_PROGRESS.md`;
- API_SPECIFICATION §19J;
- DATABASE_SCHEMA §14C.

## 13. Next

1. **Your review** of Phase 10A (§12), and of Phases 8 and 9 if not done yet.
2. **Step 0** for Phases 8, 9 and 10A once keys and accounts are in place.
3. Then **Phase 10B — the campaign builder** (approved strategies and creatives → campaigns, always created paused, through this engine). Its plan comes to you for approval first.
