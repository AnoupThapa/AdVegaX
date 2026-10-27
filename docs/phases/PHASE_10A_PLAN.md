# Phase 10A — Action Engine: Implementation Plan

**Status:** ✅ **Approved 2026-10-26 (A28, "Approve all": Q-10A-1 … Q-10A-11).** Implemented — see `PHASE_10A_PROGRESS.md` and `PHASE_10A_REPORT.md`. · **Date:** 2026-10-26

> **This is the first phase that can change something at Google or Meta.** Everything is built and tested against the platform **simulators** (no calls in CI). Changes reach a real account only after Step 0, after you switch the engine on for this installation, **and** after you allow changes for a specific connection.

**Depends on:** Phase 1 (audit, roles, jobs), 3 (Google Ads), 4 (Meta). · **Followed by:** 10B (campaign builder) and 11 (optimization), which may change an ad account **only through this engine** (A13).
**Governing documents:** MASTER_SPECIFICATION §9, D16, A2 ("the Action Engine is mandatory before any campaign/account change"), A12, A13; `phases/PHASE_10A_ACTION_ENGINE.md` (outline); API_SPECIFICATION §14; DATABASE_SCHEMA §15.

---

## 1. Objective

One gate — and only one — through which AdVegaX ever changes an ad account:

- a **closed list** of changes, each with typed values and limits;
- every change **checked**, **approved by a person**, written down **before** the platform is called, executed **once** (never twice by accident), **verified** by reading the account back, and **audited** end to end;
- a change whose outcome is unknown (a timeout) is **looked up, never blindly retried**;
- an **undo** is just another change through the same gate;
- **two switches** stop everything: one for the installation, one per organization.

No other code path may call a platform's write methods (a static rule, as today's read-only rules).

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all of them at once, or change any.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-10A-1** | Which changes in this phase? | Three, at **campaign level**, on Google Ads and Meta: **pause**, **resume**, **set the daily budget**. Creating campaigns (always paused first) comes with the campaign builder (10B), through this same engine. On Meta, the daily budget is changed only on campaigns that hold the budget (Advantage campaign budget); a budget held by ad sets is refused with a clear message. | Small, reversible, high-value changes prove the engine before anything is created. |
| **Q-10A-2** | Access at the platforms | Read-only stays the default. Changes need a separate, explicit **"Allow changes"** step per connection: for **Meta**, signing in again to grant **`ads_management`** (needs Meta App Review / Advanced Access for accounts you do not own); for **Google Ads**, the same sign-in scope covers changes, but the **developer token** needs **Basic access** for real (non-test) accounts. Until then, changes work only on test accounts. | You decide, per connection, whether AdVegaX may change anything. |
| **Q-10A-3** | Who may request and approve? | **Request:** owner, admin, manager. **Approve:** owner or admin. An organization setting **"require a second person"** (off by default, recommended once you have staff) refuses approval by the person who asked. AI recommendations (Phase 11) can only *request*. | A person with authority signs off every change (D16). |
| **Q-10A-4** | Limits (fixed rules) | **Budget:** one change at most **+50 %** or **−90 %** of the current daily budget; never below the platform minimum (Phase 8's setting) or above the organization's **maximum daily budget per campaign** (a setting you choose; required before the first budget change); **at most one budget change per campaign per hour**. **Volume:** at most **50 changes per ad account per day**. All are settings. | Stops costly mistakes and loops before they happen. |
| **Q-10A-5** | Checks, in order | **Shape** (the change and its values) → **resource** (the campaign is yours, linked, and its account allows changes) → **business rules** (Q-10A-4) → **state** (the campaign is in a state where the change makes sense: you cannot pause a paused campaign) → **platform dry run** (Google's `validateOnly`, Meta's `validate_only`) → **authorization** → **idempotency** (an identical open request is refused as a duplicate). | The platform's own dry run catches what AdVegaX cannot know. |
| **Q-10A-6** | Execution | On approval, the change is **queued** and run by the worker: the record moves `approved → submitting` **before** the call; the campaign is **locked** (one change at a time); the campaign is **read again** right before the call, and if it changed since approval (another person, or the platform), the change **stops as stale** and must be approved again. | Never acts on old information; never two changes racing. |
| **Q-10A-7** | Timeouts and failures | A timeout or lost answer makes the change **`unknown`**: the worker **reads the campaign** to find out what happened (the change took effect → `succeeded`; it did not → `failed`, and you may retry by approving again). **Never a blind retry.** Platform refusals are `failed` with the platform's reason in plain words. | The only safe answer to "did it happen?" is to look. |
| **Q-10A-8** | Verification and undo | After the call, the campaign is read back and the result compared with the request (`verified` or `mismatch`). **Undo** proposes the opposite change (previous status or budget) as a **new request**, approved like any other. | Proof that it happened; reversals are audited too. |
| **Q-10A-9** | Off switches | **`ACTIONS_ENABLED`** for the installation (off by default) and **"Pause all changes"** per organization (owners and admins). With either off, nothing is executed; queued changes wait. | You can stop everything in one click. |
| **Q-10A-10** | Audit | Every step is recorded: who asked, who approved, the checks and their results, the exact change sent, the platform and account, the platform's answer (without secrets), verification. Plus the existing audit log entries. | Complete trace (A2, MASTER §9). |
| **Q-10A-11** | Web app | A **Changes** page (pending, approved, done, failed) with approve / reject / undo; on each campaign row: **Pause**, **Resume**, **Change budget** (shows the limits and the platform's dry-run result before you send it); Settings → Changes (pause all, second-person rule, maximum daily budget). | Requests and decisions in one place. |

## 2A. What you need to set up (for Step 0 and real use)

1. **Google Ads:** a **test manager account** with test client accounts (changes are free there) — and later **Basic access** for the developer token (Google's application form).
2. **Meta:** in development mode the app can change **your own** ad accounts with `ads_management`; for other businesses, **App Review** for `ads_management`.
3. Network access to Google and Meta from the place Step 0 runs.
4. Your **maximum daily budget per campaign** (Q-10A-4).

## 3. Scope

| Area | In Phase 10A |
|---|---|
| Catalogue | `app/domains/actions/catalogue.py`: `campaign.pause`, `campaign.resume`, `campaign.set_daily_budget` — typed values, bounds, the provider capability each needs |
| Checks | `actions/validation.py`: the chain of Q-10A-5 |
| Engine | `actions/engine.py`: state machine, queueing, locks, precondition re-read, execution, unknown-outcome reconciliation, verification, undo |
| Provider writes | `providers/google_ads/writes.py`, `providers/meta_ads/writes.py`: the only modules allowed to call write methods; dry-run support; simulators extended for writes, timeouts and partial failures |
| Access | Per-connection "Allow changes" (Meta re-consent with `ads_management`; Google flag); capability checks |
| Switches and limits | `ACTIONS_ENABLED`, organization action settings |
| API | `POST /actions/validate` (dry run, nothing stored), `POST /actions` (request), `GET /actions[/{id}]`, `POST /actions/{id}/approve | reject | cancel | undo`, `GET/PUT /action-settings`, `POST /connections/{id}/write-access` |
| Web app | Changes page; campaign actions; settings |
| Data | Migration **0020**: `actions`, `action_events`, `action_settings`; connection write-access fields |

## 3A. Non-goals

- Creating campaigns, ad groups, ads or keywords (10B).
- Automatic changes without a person's approval (Phase 12, autopilot).
- AI recommendations (Phase 11) — the engine accepts their requests later.
- Bids, targeting, schedules, ad-level changes.

## 4. Facts and Step 0

### 4.1 Facts (checked 2026-10-26)

1. **Google Ads API (REST):** changes are `POST https://googleads.googleapis.com/vNN/customers/{customer_id}/{resources}:mutate` with `operations[]` of `create` / `update` (+ `updateMask`) / `remove`; e.g. pausing a campaign is `update {resourceName, status: "PAUSED"}` with `updateMask: "status"` (Google Ads API, "Mutating resources"). A daily budget is the campaign's **campaign budget** (`amountMicros`, changed through `campaignBudgets:mutate`). The `adwords` OAuth scope AdVegaX already uses covers writes; the **developer token's access level** decides which accounts can be changed. Requests also accept `validateOnly` (Step 0 confirms the field on the version in use).
2. **Meta Marketing API:** a campaign or ad set is changed by `POST` to its ID with `status` (`ACTIVE`, `PAUSED`) or `daily_budget` **in the account currency's minor units** (cents); `execution_options=["validate_only"]` performs a dry run (Meta's Ads CLI reference); changes need the **`ads_management`** permission.

### 4.2 Step 0 — live checks (task 10A-01)

1. Google test account: pause and resume a campaign; change a budget; `validateOnly` answers without changing anything; a timeout is reconciled by reading back.
2. Meta (own ad account, development mode): the same three changes; `validate_only`; a campaign whose budget is on ad sets is refused as planned.
3. The read-back of both platforms matches what AdVegaX recorded.

## 5. Proposed structure

```
app/domains/actions/       catalogue, validation, engine (state machine, locks, execution,
                           reconciliation, verification, undo), settings, service, router
app/providers/google_ads/writes.py   the only Google write calls
app/providers/meta_ads/writes.py     the only Meta write calls
frontend/features/changes/           Changes page, campaign actions, settings
```

## 6. Data model (migration 0020)

- **`actions`** (tenant-owned, forced RLS): organization, `action_type`, provider, ad account, campaign (composite FKs), `params` (JSON: e.g. the new daily budget in the account currency), `previous` (JSON: the state read at request time), `status` (`pending` | `approved` | `rejected` | `cancelled` | `queued` | `submitting` | `unknown` | `succeeded` | `failed` | `stale`), `idempotency_key` (unique per organization), checks and their results, dry-run result, platform request and answer (without secrets), `verification` (`verified` | `mismatch` | null), requested by, approved / rejected by and when, reason, `undo_of`, source (`user` | later `recommendation`), timestamps.
- **`action_events`** (tenant-owned, forced RLS, insert-only): every status change with time, actor (user or worker) and detail.
- **`action_settings`** (tenant-owned): `paused`, `require_second_person`, `max_daily_budget` (reporting currency), updated by / at.
- **`external_connections`**: write access granted (when, by whom; the scopes now held).

## 7. API

As §3. Errors: `ACTIONS_DISABLED` (installation or organization switch), `ACTION_INVALID` (with each failed check), `ACTION_DUPLICATE` (an identical open request), `ACTION_NOT_ALLOWED` (no write access on the connection), `ACTION_STALE` (the campaign changed since approval), `SECOND_PERSON_REQUIRED`.

## 8. Security

- **Write calls exist only** in `providers/*/writes.py`, which only `app/domains/actions` may import (static rule); today's read-only rules stay for all other provider code.
- Tokens never leave the token store; platform answers are stored without tokens or secrets.
- Each change runs as the organization (RLS) with the connection's own token; a change for another organization's campaign is "not found".
- Idempotency: unique key per organization and a one-change-per-campaign lock; queued jobs are safe to run twice (the record's status decides).
- Off switches checked at request, approval and right before the call.

## 9. Testing

- Catalogue and validation: every check and bound.
- Engine (against the simulators): success; platform refusal; **timeout → unknown → reconciled** both ways; **duplicate request**; **two workers on the same change** (runs once); **two changes on one campaign** (second waits or is refused); **stale** (campaign changed between approval and execution); Meta **budget on ad sets** refused; verification mismatch; undo.
- Static rule: no write method called outside `writes.py`; `writes.py` imported only by the engine.
- API sweeps (roles, tenants), page tests, one browser test with accessibility checks (request a budget change, see the dry run, approve, see it done and verified, undo).

## 10. Tasks (one report for the whole phase)

| Task | Content |
|---|---|
| 10A-01 | Step 0 (§4.2) — needs the test accounts and network access |
| 10A-02 | Migration 0020; catalogue; validation chain; settings and switches |
| 10A-03 | Provider write adapters (Google, Meta) with dry runs; simulators for writes, timeouts, partial failures |
| 10A-04 | Engine: state machine, queue, locks, precondition re-read, reconciliation, verification, undo |
| 10A-05 | Write access per connection; API; audit |
| 10A-06 | Web app: Changes page, campaign actions, settings |
| 10A-07 | Duplicate / timeout / partial-failure / concurrency tests, browser test, `PHASE_10A_REPORT.md` with your review checklist |

## 11. Acceptance criteria

1. Pause, resume and daily-budget changes run end to end against the simulators, verified by reading back.
2. No code path changes a platform outside the engine (static rule).
3. Every change is approved by a person with authority; with "require a second person", never by the requester.
4. A timeout never causes a second call before the campaign is read back; duplicates never execute twice.
5. A change approved on old information stops as stale.
6. The limits of Q-10A-4 hold; both off switches stop execution.
7. Every step is in `action_events` and the audit log, without secrets.
8. All suites pass, with no platform calls in CI.

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| A wrong change costs money | HIGH | Closed catalogue, limits, dry run, human approval, read-before-write, verification, undo, off switches |
| Double execution | HIGH | Status machine persisted first, per-campaign lock, idempotency key, never blind retry |
| Platform access not granted in time (App Review, Basic access) | MEDIUM | Built and tested against simulators; works on test/own accounts first |
| API changes | LOW | Versions as settings; Step 0; dry runs surface errors early |

## 13. Rollback

`ACTIONS_ENABLED=false` stops everything at once; migration 0020 is reversible; read-only features are unaffected.

## 14. Approval checklist

Approve or change **Q-10A-1 … Q-10A-11**, the Step 0 (§4.2), the data model (§6) and delivery 10A-01 … 10A-07 with one report at the end of the phase. No new library is needed.
