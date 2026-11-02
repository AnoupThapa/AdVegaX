# Phase 10A — Progress (Action Engine)

Plan: `PHASE_10A_PLAN.md` (approved 2026-10-26, A28, all recommendations Q-10A-1 … Q-10A-11). Built task by task; **one report for the whole phase** (`PHASE_10A_REPORT.md`).

| Task | Status |
|---|---|
| 10A-01 Step 0: live checks on a Google test account and an own Meta ad account | ⏸ Waiting for the test accounts, Meta's change permission and network access |
| 10A-02 Migration 0020; catalogue; validation chain; settings and switches | ✅ Done |
| 10A-03 Provider write adapters (Google, Meta) with dry runs; simulators for writes and failures | ✅ Done |
| 10A-04 Engine: state machine, queue, locks, read-before-write, look-up of unknown outcomes, verification, undo, sweep | ✅ Done |
| 10A-05 Write access per connection; API; audit | ✅ Done |
| 10A-06 Web app: Changes pages, campaign changes, settings, "Allow changes" | ✅ Done |
| 10A-07 Duplicate / timeout / concurrency tests, browser test, `PHASE_10A_REPORT.md` | ✅ Done — Phase 10A awaiting review |

## 10A-01 — Step 0

**Blocked:** needs a Google Ads **test manager account** with test client accounts, a Meta ad account of your own with the app's **change permission** (`ads_management`, and a Login for Business configuration that asks for it), and network access to Google and Meta from where Step 0 runs (plan §4.2).

## 10A-02 — Migration 0020, catalogue, checks, settings

- **Migration 0020** (additive, reversible): `actions`, `action_events` (insert-only, numbered steps), `action_settings`; `external_connections` gains who allowed changes and when. All tenant-owned with forced RLS; nothing is deleted. **At most one open change per campaign** (partial unique index). The scheduler may read four columns of `actions` (id, organization, status, last change).
- **Catalogue** (`actions/catalogue.py`): `campaign.pause`, `campaign.resume`, `campaign.set_daily_budget` — typed values (a budget in the account currency, with the currency's decimals only), the states each applies to, its opposite (undo), and the comparisons the worker needs.
- **Checks** (`actions/validation.py`), in order, every result recorded:
  1. **shape** — the values;
  2. **resource** — the platform can be changed, the account is linked and active, the connection is active, the campaign is not removed, no other open change;
  3. **budget** — the campaign holds its own **daily** budget (not its ad sets, not a total), not shared with other campaigns, and the value changes;
  4. **limits** — at most +50 % / −90 % in one change, at least the platform minimum, at most the organization's maximum (which must be chosen first), one budget change per campaign per hour, 50 changes per ad account a day;
  5. **state** — e.g. you cannot pause a paused campaign.
- **Switches:** `ACTIONS_ENABLED` (off by default) and each organization's "Pause all changes".

## 10A-03 — The platforms' change calls

- **Only two modules call a platform to change something:** `providers/google_ads/writes.py` and `providers/meta_ads/writes.py`. Only their own provider imports them, and only the Action Engine calls the provider's change method (static rules).
- **Google:** one `update` operation with `updateMask` — `campaigns:mutate` (status) or `campaignBudgets:mutate` (`amountMicros`); `validateOnly` for the dry run; a campaign is read with its budget in one query.
- **Meta:** `POST /<campaign id>` with `status` or `daily_budget` in the currency's smallest unit; `execution_options=["validate_only"]` for the dry run; the change path is separate from the read-only guard and accepts only `POST` to one numeric object.
- **Outcomes:** a timeout, a lost or unreadable answer, or a server error is **unknown** (looked up, never resent); a rate limit or any refusal means "not made".
- **Simulators** (both platforms): the change calls, the dry run, Meta's change permission, and the outcomes a worker must survive — the answer lost after the change was made, a timeout before it, a server error, a refusal, a "success" that changed nothing.

## 10A-04 — The engine

- `pending → approved → queued → submitting → succeeded | failed | unknown`; `unknown → succeeded | failed`; `stale`, `rejected`, `cancelled`. Every move is an event and an audit entry.
- **Written down before the call:** `submitting` is committed before anything is sent.
- **One at a time:** one open change per campaign (database) and a lock around the platform calls; a job delivered twice does nothing the second time.
- **Read before write:** right before sending, the campaign is read again; if it changed since the request, the change stops as **stale**.
- **Unknown outcomes are looked up:** made → `succeeded` (verified); still as before → `failed` (`not_applied`, safe to request again); something else → `failed` (`changed_elsewhere`); unreadable → looked up again a limited number of times, then "check the campaign at the platform".
- **Verification:** after a success the campaign is read back (`verified` / `mismatch`); AdVegaX's copy of the campaign shows what the platform reported.
- **Sweep** every 5 minutes: a queued change whose message was lost is sent; a change left `submitting` by a worker that stopped becomes unknown and is looked up.

## 10A-05 — Access, API, audit (API_SPECIFICATION §19J)

- **"Allow changes" per connection** (owners, admins), read-only by default. Meta also needs `ads_management`: "Sign in again to allow changes" uses the change login configuration (`META_WRITE_LOGIN_CONFIG_ID`). A permission taken back at Meta fails the dry run without marking the connection broken.
- **Roles:** request — owner, admin, manager; approve / reject — owner, admin; cancel — the requester or an approver; settings and access — owner, admin. "Require a second person" refuses approval by the requester.
- **Undo** requests the opposite change, approved like any other; it restores an earlier value, so the step and one-hour limits do not apply to it.
- Requests older than 7 days can no longer be approved (stale).
- **Audit:** every step, with what was sent and the platform's answer — never a token.

## 10A-06 — Web app

- **Changes** in the menu: what waits or is on its way, what was done, what was not made; each change shows what it does in words, the checks, the platform's test, **exactly what was sent**, the read-back and verification, and its history. Owners and admins approve or reject (with a reason); the requester or an approver cancels; undo.
- **On a campaign's page:** Pause / Resume / Change budget. AdVegaX checks first and shows the allowed budget range (computed by AdVegaX), the reasons in plain words and the platform's test; then "Request this change". A change in progress is shown instead of the buttons.
- **Settings → Changes to ad accounts:** pause all, require a second person, maximum daily budget per campaign, and the limits.
- **Connection page:** "Changes through this connection" — Allow / Stop allowing, or sign in again for the missing permission.

## 10A-07 — Tests and report

- API (Google and Meta simulators): end-to-end pause, resume and budget changes; every limit; duplicates; roles and the second-person rule; both switches; stale; lost answer and timeout looked up, never resent; bounded look-ups; refusal; mismatch; two workers; a busy campaign; the sweep; undo; tenants.
- Unit: the catalogue and every check and bound; the platforms' change calls and outcomes.
- Web app: lists, decisions, campaign changes, settings, connection access.
- Browser test: a change made with the simulator, shown with what was sent, its verification and history; its undo waiting; the server's engine off says so; settings and connection; accessibility on every page.
