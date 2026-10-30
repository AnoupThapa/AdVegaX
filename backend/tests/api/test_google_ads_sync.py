"""Keeping linked Google Ads accounts up to date (task 3-07, PLAN §9, Q-3-2, Q-3-5).

After the first import, every account gets a 3-hour run (structure + today and yesterday), a
nightly run (the last 30 days) and a weekly run (the last 90 days); each re-read replaces the
days it covers. Runs reserve their operations in the allowance shared by every customer: at
80 % the nightly and weekly re-reads wait, at 100 % every step waits, and when Google itself
says the allowance is used up every account waits. "Sync now" reads the structure and the
last 30 days, limited per account.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.core.errors import RateLimited
from app.domains.advertising import importer
from app.domains.advertising.importer import (
    AdAccountNotSyncing,
    AdSyncInProgress,
    SyncMode,
    due_mode,
    enqueue_ad_syncs,
    request_sync,
)
from app.domains.advertising.models import AdAccount, AdSyncState
from app.domains.advertising.quota import SharedQuota
from app.domains.jobs.service import ClaimedJob
from sqlalchemy import text

from tests.google_ads_sim import (
    GoogleAdsSim,
    build_provider,
    perf_row,
    sample_hierarchy,
    sample_performance,
    sample_structure,
)

SUB = "108000000000000000001"
AU = "1000000001"  # Australia/Sydney: the test clock's 00:00 UTC is 11:00 there
SEARCH_DAY, PMAX_DAY = "2026-10-01", "2026-04-10"
BETWEEN = re.compile(rb"BETWEEN '([0-9-]{10})' AND '([0-9-]{10})'")
HOURS = timedelta(hours=1)


@pytest.fixture
def sim(runtime, clock):
    s = sample_hierarchy(GoogleAdsSim(clock=clock))
    sample_performance(sample_structure(s.customers[AU]), SEARCH_DAY, PMAX_DAY)
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def provider(runtime, sim):
    return runtime.providers.get("google_ads")


def _connect(make_client, sim):
    """Sign in with Google, discover the accounts and link the AU account."""
    c = make_client()
    c.signup(f"ads-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    started = c.post(f"/organizations/{c.org}/connections/google_ads/start", {"params": {}}).json()[
        "data"
    ]["authorize_url"]
    response = c.http.get(
        "/api/v1/connections/google_ads/callback",
        params=sim.approve(started, SUB),
        follow_redirects=False,
    )
    c.conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    resources = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    c.resource = next(r for r in resources if r["external_id"] == AU)
    linked = c.post(f"/organizations/{c.org}/resources/{c.resource['id']}/link")
    assert linked.status_code == 201, linked.text
    return c


@pytest.fixture
def owner(make_client, sim):
    return _connect(make_client, sim)


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _state(admin_engine):
    (state,) = _rows(
        admin_engine,
        "SELECT ad_account_id, import_job_id, import_cursor, sync_mode, last_quick_at, "
        "last_nightly_at, last_weekly_at, last_error_code FROM ad_sync_state",
    )
    return state


def _streams(sim, before):
    return sim.calls("googleAds:searchStream")[before:]


def _ranges(calls):
    found = [BETWEEN.search(c.content) for c in calls if b"segments.date" in c.content]
    return {tuple(date.fromisoformat(v.decode()) for v in f.groups()) for f in found if f}


def _account_day(admin_engine, day):
    (row,) = _rows(
        admin_engine,
        "SELECT clicks, cost FROM ad_performance_daily WHERE level = 'account' AND day = :d",
        d=day,
    )
    return row


def _user_id(admin_engine):
    (row,) = _rows(admin_engine, "SELECT id FROM users")
    return row["id"]


def _run_waiting_step(runtime, owner, admin_engine):
    state = _state(admin_engine)
    importer.import_step(
        runtime,
        ClaimedJob(
            state["import_job_id"],
            uuid.UUID(owner.org),
            importer.JOB_AD_IMPORT_STEP,
            str(state["ad_account_id"]),
            1,
            5,
            None,
            None,
        ),
    )


# ------------------------------------------------------------------ the schedule
def test_nothing_is_due_right_after_the_first_import(owner, sim, runtime, admin_engine):
    state = _state(admin_engine)
    assert state["last_quick_at"] == state["last_nightly_at"] == state["last_weekly_at"]
    assert state["last_quick_at"] is not None  # the first import covered every run
    before = len(sim.requests)
    assert enqueue_ad_syncs(runtime) == 0
    assert len(sim.requests) == before


def test_the_3_hour_run_reads_the_structure_and_the_last_two_days(
    owner, sim, runtime, admin_engine, clock
):
    sim.customers[AU].campaigns[0]["campaign"]["name"] = "Gloves - Search (new)"
    first = _state(admin_engine)
    clock.advance(3 * HOURS)
    before = len(sim.calls("googleAds:searchStream"))
    assert enqueue_ad_syncs(runtime) == 1
    calls = _streams(sim, before)
    assert len(calls) == 5 + 4  # account + 4 structure lists, then 4 levels
    assert _ranges(calls) == {(date(2026, 10, 13), date(2026, 10, 14))}  # Sydney's days
    (campaign,) = _rows(
        admin_engine, "SELECT name FROM ad_campaigns WHERE external_campaign_id = '11'"
    )
    assert campaign["name"] == "Gloves - Search (new)"  # structure changes are picked up
    state = _state(admin_engine)
    assert state["last_quick_at"] > first["last_quick_at"]
    assert state["last_nightly_at"] == first["last_nightly_at"]
    assert (state["import_job_id"], state["sync_mode"], state["last_error_code"]) == (
        None,
        None,
        None,
    )
    assert enqueue_ad_syncs(runtime) == 0  # not due again for 3 hours


def test_a_correction_is_picked_up_by_the_nightly_run_not_the_3_hour_run(
    owner, sim, runtime, admin_engine, clock
):
    """Google credits conversions and removes invalid clicks days later (PLAN §2 item 8)."""
    customer = sim.customers[AU]
    customer.performance["account"][0] = perf_row(
        SEARCH_DAY, impressions=1200, clicks=30, cost_micros=9_000_000
    )
    clock.advance(3 * HOURS)
    enqueue_ad_syncs(runtime)  # 3-hour run: 13 and 14 October only
    assert _account_day(admin_engine, date(2026, 10, 1))["clicks"] == 34
    clock.advance(21 * HOURS)
    before = len(sim.calls("googleAds:searchStream"))
    assert enqueue_ad_syncs(runtime) == 1
    calls = _streams(sim, before)
    assert len(calls) == 4  # figures only: the 3-hour runs keep the structure current
    assert _ranges(calls) == {(date(2026, 9, 16), date(2026, 10, 15))}  # 30 days
    assert _account_day(admin_engine, date(2026, 10, 1)) == {"clicks": 30, "cost": 9}
    assert _account_day(admin_engine, date(2026, 4, 10))["clicks"] == 0  # outside: untouched
    state = _state(admin_engine)
    assert state["last_nightly_at"] == clock.now()


def test_the_weekly_run_reads_90_days(owner, sim, runtime, admin_engine, clock):
    clock.advance(timedelta(days=7))
    before = len(sim.calls("googleAds:searchStream"))
    assert enqueue_ad_syncs(runtime) == 1
    calls = _streams(sim, before)
    assert len(calls) == 4
    assert _ranges(calls) == {(date(2026, 7, 24), date(2026, 10, 21))}
    state = _state(admin_engine)
    assert state["last_weekly_at"] == state["last_nightly_at"] == clock.now()
    assert enqueue_ad_syncs(runtime) == 1  # the 3-hour run is still due: it comes next
    assert _state(admin_engine)["last_quick_at"] == clock.now()


@pytest.mark.parametrize(
    ("ago", "defer", "expected"),
    [
        ({}, False, SyncMode.WEEKLY),  # never run
        ({"weekly": 8 * 24, "nightly": 25, "quick": 4}, False, SyncMode.WEEKLY),
        ({"weekly": 24, "nightly": 25, "quick": 4}, False, SyncMode.NIGHTLY),
        ({"weekly": 24, "nightly": 23, "quick": 4}, False, SyncMode.QUICK),
        ({"weekly": 24, "nightly": 23, "quick": 2}, False, None),
        ({"weekly": 8 * 24, "nightly": 25, "quick": 4}, True, SyncMode.QUICK),
        ({"weekly": 8 * 24, "nightly": 25, "quick": 2}, True, None),
    ],
)
def test_which_run_is_due(runtime, clock, ago, defer, expected):
    now = clock.now()
    state = None
    if ago:
        state = AdSyncState(
            ad_account_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            last_weekly_at=now - ago["weekly"] * HOURS,
            last_nightly_at=now - ago["nightly"] * HOURS,
            last_quick_at=now - ago["quick"] * HOURS,
        )
    assert due_mode(runtime, state, defer_rereads=defer) is expected


def test_unlinked_accounts_and_ended_connections_are_not_synced(
    owner, sim, runtime, admin_engine, clock
):
    unlinked = owner.post(f"/organizations/{owner.org}/resources/{owner.resource['id']}/unlink")
    assert unlinked.status_code == 200
    clock.advance(3 * HOURS)
    before = len(sim.requests)
    assert enqueue_ad_syncs(runtime) == 0
    assert len(sim.requests) == before


def test_a_running_chain_is_left_alone_until_it_goes_silent(
    owner, sim, runtime, admin_engine, clock
):
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE ad_sync_state SET import_job_id = :j, updated_at = :t"),
            {"j": uuid.uuid4(), "t": clock.now()},
        )
    clock.advance(3 * HOURS)
    assert enqueue_ad_syncs(runtime) == 0
    clock.advance(4 * HOURS)  # silent for 7 hours (ADS_CHAIN_STALE_AFTER is 6)
    assert enqueue_ad_syncs(runtime) == 1


def test_the_scheduler_task_runs_once_per_tick(runtime):
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule["ads-sync"]
    assert schedule["task"] == "advegax.schedule.ads_sync"
    assert schedule["schedule"] == runtime.settings.SCHEDULE_ADS_SYNC_TICK.total_seconds()


def test_the_scheduler_reads_only_four_columns_of_other_tenants(owner, runtime):
    with runtime.db.transaction(system=True) as session:
        assert session.execute(text("SELECT count(id) FROM ad_accounts")).scalar_one() == 1
    with (
        pytest.raises(Exception, match="permission denied"),
        runtime.db.transaction(system=True) as session,
    ):
        session.execute(text("SELECT name FROM ad_accounts")).all()


# ------------------------------------------------------------------ the shared allowance
def _used(runtime, count):
    quota = SharedQuota(runtime.redis, runtime.clock)
    assert quota.reserve("google_ads", count, ceiling=count, window_seconds=86400)


def test_rereads_wait_when_most_of_the_allowance_is_used(
    owner, sim, runtime, admin_engine, clock, provider
):
    provider.shared_daily_operations = 100
    clock.advance(timedelta(days=7))
    _used(runtime, 80)  # 80 %: nightly and weekly wait, the 3-hour run goes ahead
    first = _state(admin_engine)
    assert enqueue_ad_syncs(runtime) == 1
    state = _state(admin_engine)
    assert state["last_quick_at"] == clock.now()
    assert state["last_nightly_at"] == first["last_nightly_at"]
    assert state["last_weekly_at"] == first["last_weekly_at"]
    used = SharedQuota(runtime.redis, runtime.clock).used("google_ads", window_seconds=86400)
    assert used == 80 + 9


def test_a_step_that_does_not_fit_waits_and_continues_later(
    owner, sim, runtime, admin_engine, clock, provider
):
    provider.shared_daily_operations = 100
    _used(runtime, 97)
    clock.advance(3 * HOURS)
    before = len(sim.requests)
    assert enqueue_ad_syncs(runtime) == 1
    assert [r for r in sim.requests[before:] if "googleAds" in r.url.path] == []
    state = _state(admin_engine)
    assert state["last_error_code"] == "quota_waiting"
    assert state["import_cursor"] == "structure"
    (job,) = _rows(
        admin_engine,
        "SELECT status, attempts, next_attempt_at > now() AS later FROM job_runs WHERE id = :i",
        i=state["import_job_id"],
    )
    assert job == {"status": "queued", "attempts": 0, "later": True}  # no attempt used
    clock.advance(25 * HOURS)  # the old operations have left the 24-hour window
    _run_waiting_step(runtime, owner, admin_engine)
    state = _state(admin_engine)
    assert (state["import_job_id"], state["last_error_code"]) == (None, None)
    assert state["last_quick_at"] == clock.now()


def test_googles_quota_answer_holds_every_account(owner, sim, runtime, admin_engine, clock):
    sim.fail_next.append((429, {"quotaError": "RESOURCE_EXHAUSTED"}))
    clock.advance(3 * HOURS)
    enqueue_ad_syncs(runtime)
    state = _state(admin_engine)
    assert state["last_error_code"] == "quota_waiting"
    quota = SharedQuota(runtime.redis, runtime.clock)
    assert 0 < quota.blocked_for("google_ads") <= 15 * 60
    before = len(sim.requests)
    _run_waiting_step(runtime, owner, admin_engine)  # still blocked: no call to Google
    assert [r for r in sim.requests[before:] if "googleAds" in r.url.path] == []
    (account,) = _rows(admin_engine, "SELECT status, health_code FROM ad_accounts")
    assert account == {"status": "active", "health_code": None}  # nothing is marked
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert "ad_account.import_failed" not in actions
    clock.advance(16 * timedelta(minutes=1))
    _run_waiting_step(runtime, owner, admin_engine)
    assert _state(admin_engine)["last_quick_at"] == clock.now()


def test_googles_retry_delay_is_used_when_given(owner, sim, runtime, clock):
    real = sim.handler
    answered = {"done": False}

    def slow_down(request):
        if "googleAds" in request.url.path and not answered["done"]:
            answered["done"] = True
            body = (
                b'{"error":{"code":429,"details":[{"errors":[{"errorCode":{"quotaError":'
                b'"RESOURCE_TEMPORARILY_EXHAUSTED"},"details":{"quotaErrorDetails":'
                b'{"retryDelay":"30s"}}}]}]}}'
            )
            import httpx

            return httpx.Response(429, content=body)
        return real(request)

    sim.handler = slow_down
    clock.advance(3 * HOURS)
    enqueue_ad_syncs(runtime)
    assert 29 <= SharedQuota(runtime.redis, runtime.clock).blocked_for("google_ads") <= 30


# ------------------------------------------------------------------ "Sync now"
def _sync_now(runtime, owner, admin_engine):
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        account = session.query(AdAccount).one()
        return request_sync(session, runtime, account, requested_by=_user_id(admin_engine))


def test_sync_now_reads_the_structure_and_30_days(owner, sim, runtime, admin_engine, clock):
    clock.advance(HOURS)
    before = len(sim.calls("googleAds:searchStream"))
    _, mode = _sync_now(runtime, owner, admin_engine)
    assert mode is SyncMode.NIGHTLY
    calls = _streams(sim, before)
    assert len(calls) == 9
    assert _ranges(calls) == {(date(2026, 9, 15), date(2026, 10, 14))}
    assert _state(admin_engine)["last_nightly_at"] == clock.now()
    (audit,) = _rows(
        admin_engine,
        "SELECT actor_type, metadata FROM audit_logs WHERE action = 'ad_account.sync_started'",
    )
    assert audit["actor_type"] == "user" and audit["metadata"]["mode"] == "nightly"


def test_sync_now_does_not_wait_for_the_rereads_share(owner, sim, runtime, admin_engine, provider):
    provider.shared_daily_operations = 100
    _used(runtime, 85)  # over 80 %: a scheduled nightly would wait, a person's request not
    _sync_now(runtime, owner, admin_engine)
    assert _state(admin_engine)["last_error_code"] is None


def test_sync_now_while_a_run_is_going_is_refused(owner, runtime, admin_engine, clock):
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE ad_sync_state SET import_job_id = :j, updated_at = :t"),
            {"j": uuid.uuid4(), "t": clock.now()},
        )
    with pytest.raises(AdSyncInProgress):
        _sync_now(runtime, owner, admin_engine)


def test_sync_now_is_limited_per_account(owner, runtime, admin_engine):
    for _ in range(runtime.settings.THROTTLE_AD_ACCOUNT_RESYNC_PER_HOUR):
        _sync_now(runtime, owner, admin_engine)
    with pytest.raises(RateLimited):
        _sync_now(runtime, owner, admin_engine)


def test_sync_now_needs_a_linked_account(owner, runtime, admin_engine):
    assert (
        owner.post(
            f"/organizations/{owner.org}/resources/{owner.resource['id']}/unlink"
        ).status_code
        == 200
    )
    with pytest.raises(AdAccountNotSyncing):
        _sync_now(runtime, owner, admin_engine)


def test_sync_now_restarts_a_first_import_that_failed(make_client, sim, runtime, admin_engine):
    real = sim.handler
    refuse = {"on": True}

    def no_access_yet(request):  # access to the account is granted only later
        if refuse["on"] and f"/customers/{AU}/" in request.url.path:
            return sim.failure(403, {"authorizationError": "USER_PERMISSION_DENIED"})
        return real(request)

    sim.handler = no_access_yet
    c = _connect(make_client, sim)
    (account,) = _rows(admin_engine, "SELECT status, first_import_completed_at FROM ad_accounts")
    assert account == {"status": "error", "first_import_completed_at": None}
    refuse["on"] = False
    _, mode = _sync_now(runtime, c, admin_engine)
    assert mode is SyncMode.INITIAL
    (account,) = _rows(admin_engine, "SELECT status, health_code FROM ad_accounts")
    assert account == {"status": "active", "health_code": None}


# ------------------------------------------------------------------ health
def test_an_access_problem_clears_when_the_account_answers_again(
    owner, sim, runtime, admin_engine, clock
):
    sim.fail_next.append((403, {"authorizationError": "USER_PERMISSION_DENIED"}))
    clock.advance(3 * HOURS)
    enqueue_ad_syncs(runtime)
    (account,) = _rows(admin_engine, "SELECT status, health_code FROM ad_accounts")
    assert account == {"status": "active", "health_code": "no_account_access"}  # still shown
    assert _state(admin_engine)["last_error_code"] == "no_account_access"
    clock.advance(3 * HOURS)
    assert enqueue_ad_syncs(runtime) == 1
    (account,) = _rows(admin_engine, "SELECT health_code FROM ad_accounts")
    assert account["health_code"] is None
    assert _state(admin_engine)["last_error_code"] is None


def test_a_changed_currency_stays_flagged(owner, sim, runtime, admin_engine, clock):
    sim.customers[AU].currency = "USD"
    clock.advance(3 * HOURS)
    enqueue_ad_syncs(runtime)
    (account,) = _rows(admin_engine, "SELECT currency, health_code FROM ad_accounts")
    assert account == {"currency": "AUD", "health_code": "account_details_changed"}


# ------------------------------------------------------------------ the counter itself
def test_the_counter_slides_and_never_names_a_secret(runtime, clock):
    quota = SharedQuota(runtime.redis, clock)
    assert quota.reserve("google_ads", 0, ceiling=0, window_seconds=60)  # nothing to count
    assert quota.reserve("google_ads", 3, ceiling=4, window_seconds=60)
    assert not quota.reserve("google_ads", 2, ceiling=4, window_seconds=60)  # 5 > 4
    assert quota.used("google_ads", window_seconds=60) == 3
    clock.advance(timedelta(seconds=61))
    assert quota.reserve("google_ads", 4, ceiling=4, window_seconds=60)  # the 3 slid out
    assert runtime.redis.keys("ads-quota*") == [b"ads-quota:google_ads"]


def test_a_block_ends_on_time_and_odd_values_are_ignored(runtime, clock):
    quota = SharedQuota(runtime.redis, clock)
    assert quota.blocked_for("google_ads") == 0
    quota.block("google_ads", 30)
    assert quota.blocked_for("google_ads") == 30
    clock.advance(timedelta(seconds=31))
    assert quota.blocked_for("google_ads") == 0
    runtime.redis.set("ads-quota-blocked:google_ads", "soon")
    assert quota.blocked_for("google_ads") == 0


def test_an_unreachable_counter_is_a_temporary_error(clock):
    import redis
    from app.providers.base.errors import RetryableError

    broken = SharedQuota(redis.Redis(host="127.0.0.1", port=1, socket_timeout=0.2), clock)
    for call in (
        lambda: broken.reserve("google_ads", 1, ceiling=5, window_seconds=60),
        lambda: broken.used("google_ads", window_seconds=60),
        lambda: broken.block("google_ads", 5),
        lambda: broken.blocked_for("google_ads"),
    ):
        with pytest.raises(RetryableError):
            call()
