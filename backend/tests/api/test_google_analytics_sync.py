"""Keeping GA4 properties up to date (task 5-06, PLAN §9, Q-5-6, Q-5-7, §6.5).

After the first import, every property gets a 3-hour run (today and yesterday), a nightly run
(the last 14 days: Google's late data and changing key-event credit) and a weekly run (90
days). "Sync now" re-reads 14 days. Each run reads the property first, so access problems show
on the property. Google's remaining allowance paces each property: below a quarter the next
step waits a little, below a tenth the run pauses until the next full hour and continues by
itself, without using a retry; other properties carry on.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.core.errors import RateLimited
from app.domains.analytics import importer
from app.domains.analytics.importer import (
    AnalyticsPropertyNotSyncing,
    AnalyticsSyncInProgress,
    SyncMode,
    due_mode,
    enqueue_analytics_syncs,
    request_sync,
)
from app.domains.analytics.models import AnalyticsProperty, AnalyticsSyncState
from app.domains.jobs.service import ClaimedJob
from sqlalchemy import text

from tests.ga4_sim import GA4Sim, Visit, build_provider

SUB = "108000000000000000001"
AU, US = "111", "211"
TODAY = date(2026, 10, 14)  # the test clock (00:00 UTC) is 11:00 in Sydney
HOURS = timedelta(hours=1)


@pytest.fixture
def sim(runtime, clock):
    s = GA4Sim(clock=clock)
    s.add_account("900", "Eve Zone")
    au = s.add_property(AU, "900", SUB, display_name="Eve Zone AU")
    s.add_property(
        US, "900", SUB, display_name="Eve Zone US", currency="USD", time_zone="America/Los_Angeles"
    )
    au.traffic = [Visit(date(2026, 10, 4)), Visit(TODAY)]
    runtime.providers.register(build_provider(s))
    return s


def _connect(make_client, sim):
    c = make_client()
    c.signup(f"ga-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    started = c.post(
        f"/organizations/{c.org}/connections/google_analytics/start", {"params": {}}
    ).json()["data"]["authorize_url"]
    response = c.http.get(
        "/api/v1/connections/google_analytics/callback",
        params=sim.approve(started, SUB),
        follow_redirects=False,
    )
    c.conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    resources = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    c.resources = {r["external_id"]: r for r in resources}
    return c


@pytest.fixture
def owner(make_client, sim):
    """A connected organization with the Sydney property linked and imported."""
    c = _connect(make_client, sim)
    _link(c)
    return c


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _link(owner, external_id=AU):
    response = owner.post(
        f"/organizations/{owner.org}/resources/{owner.resources[external_id]['id']}/link"
    )
    assert response.status_code == 201, response.text


def _state(admin_engine, external_id=AU):
    (row,) = _rows(
        admin_engine,
        "SELECT p.id, p.status, p.health_code, s.* FROM analytics_properties p "
        "JOIN analytics_sync_state s ON s.property_id = p.id WHERE p.external_property_id = :e",
        e=external_id,
    )
    return row


def _ranges(sim, before=0):
    found = []
    for call in sim.calls(":batchRunReports")[before:]:
        (span,) = json.loads(call.content)["requests"][0]["dateRanges"]
        found.append((date.fromisoformat(span["startDate"]), date.fromisoformat(span["endDate"])))
    return found


def _details(sim):
    return [c for c in sim.calls("/v1beta/properties/111") if c.method == "GET"]


def _sessions(admin_engine, day, external_id=AU):
    (row,) = _rows(
        admin_engine,
        "SELECT d.sessions FROM analytics_daily d JOIN analytics_properties p "
        "ON p.id = d.property_id WHERE d.breakdown = 'total' AND d.day = :d "
        "AND p.external_property_id = :e",
        d=day,
        e=external_id,
    )
    return row["sessions"]


def _user_id(admin_engine):
    (row,) = _rows(admin_engine, "SELECT id FROM users")
    return row["id"]


def _job(admin_engine, job_id):
    (row,) = _rows(
        admin_engine,
        "SELECT status, attempts, EXTRACT(EPOCH FROM next_attempt_at - now()) AS wait "
        "FROM job_runs WHERE id = :id",
        id=job_id,
    )
    return row


def _run_waiting_step(runtime, owner, state):
    importer.import_step(
        runtime,
        ClaimedJob(
            state["import_job_id"],
            uuid.UUID(owner.org),
            importer.JOB_ANALYTICS_IMPORT_STEP,
            str(state["id"]),
            1,
            5,
            None,
            None,
        ),
    )


def _finish_chain(runtime, owner, admin_engine, clock, external_id=AU, step=timedelta(hours=1)):
    for _ in range(40):
        state = _state(admin_engine, external_id)
        if state["import_job_id"] is None:
            return state
        clock.advance(step)
        _run_waiting_step(runtime, owner, state)
    raise AssertionError("the chain did not finish")


# ------------------------------------------------------------------ the schedule
def test_nothing_is_due_right_after_the_first_import(owner, runtime, clock):
    assert enqueue_analytics_syncs(runtime) == 0
    clock.advance(2 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 0


def test_the_3_hour_run_reads_the_property_today_and_yesterday(
    owner, sim, runtime, admin_engine, clock
):
    clock.advance(3 * HOURS)  # 14:00 in Sydney
    before_reports, before_details = len(sim.calls(":batchRunReports")), len(_details(sim))
    assert enqueue_analytics_syncs(runtime) == 1
    assert _ranges(sim, before_reports) == [(date(2026, 10, 13), TODAY)]  # one call
    assert len(_details(sim)) == before_details + 1  # the property is read first
    state = _state(admin_engine)
    assert (state["status"], state["import_job_id"], state["last_quick_at"]) == (
        "active",
        None,
        clock.now(),
    )
    assert enqueue_analytics_syncs(runtime) == 0  # not due again for 3 hours


def test_a_late_correction_is_picked_up_by_the_nightly_run(
    owner, sim, runtime, admin_engine, clock
):
    sim.properties[AU].traffic[0] = Visit(date(2026, 10, 4), sessions=99)  # Google revised it
    clock.advance(3 * HOURS)
    enqueue_analytics_syncs(runtime)  # 3-hour run: 13 and 14 October only
    assert _sessions(admin_engine, date(2026, 10, 4)) == 10
    clock.advance(21 * HOURS)  # 24 hours after the import
    before = len(sim.calls(":batchRunReports"))
    assert enqueue_analytics_syncs(runtime) == 1
    assert _ranges(sim, before) == [(date(2026, 10, 2), date(2026, 10, 15))]  # 14 days
    assert _sessions(admin_engine, date(2026, 10, 4)) == 99
    assert _state(admin_engine)["last_nightly_at"] == clock.now()


def test_the_weekly_run_reads_90_days(owner, sim, runtime, admin_engine, clock):
    clock.advance(7 * 24 * HOURS)
    before = len(sim.calls(":batchRunReports"))
    assert enqueue_analytics_syncs(runtime) == 1
    assert _ranges(sim, before) == [(date(2026, 7, 24), date(2026, 10, 21))]  # one call
    state = _state(admin_engine)
    assert state["last_weekly_at"] == state["last_nightly_at"] == clock.now()
    assert enqueue_analytics_syncs(runtime) == 1  # the 3-hour run is still due: it comes next


@pytest.mark.parametrize(
    ("ago", "expected"),
    [
        ({"quick": 1, "nightly": 1, "weekly": 1}, None),
        ({"quick": 3, "nightly": 3, "weekly": 3}, SyncMode.QUICK),
        ({"quick": 1, "nightly": 24, "weekly": 24}, SyncMode.NIGHTLY),
        ({"quick": 1, "nightly": 1, "weekly": 24 * 7}, SyncMode.WEEKLY),
        ({"quick": None, "nightly": None, "weekly": None}, SyncMode.WEEKLY),
    ],
)
def test_which_run_is_due(runtime, clock, ago, expected):
    def at(hours):
        return None if hours is None else clock.now() - hours * HOURS

    state = AnalyticsSyncState(
        last_quick_at=at(ago["quick"]),
        last_nightly_at=at(ago["nightly"]),
        last_weekly_at=at(ago["weekly"]),
    )
    assert due_mode(runtime, state) is expected
    assert due_mode(runtime, None) is SyncMode.WEEKLY


def test_unlinked_properties_and_ended_connections_are_not_synced(
    owner, sim, runtime, admin_engine, clock
):
    unlinked = owner.post(
        f"/organizations/{owner.org}/resources/{owner.resources[AU]['id']}/unlink"
    )
    assert unlinked.status_code == 200
    clock.advance(3 * HOURS)
    before = len(sim.requests)
    assert enqueue_analytics_syncs(runtime) == 0
    assert len(sim.requests) == before


def test_a_disconnected_google_account_is_not_synced(owner, sim, runtime, clock):
    response = owner.post(f"/organizations/{owner.org}/connections/{owner.conn}/disconnect")
    assert response.json()["data"]["status"] == "revoked"
    clock.advance(3 * HOURS)
    before = len(sim.calls(":batchRunReports"))
    assert enqueue_analytics_syncs(runtime) == 0
    assert len(sim.calls(":batchRunReports")) == before


def test_a_running_chain_is_left_alone_until_it_goes_silent(owner, runtime, admin_engine, clock):
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE analytics_sync_state SET import_job_id = :j, updated_at = :t"),
            {"j": uuid.uuid4(), "t": clock.now()},
        )
    clock.advance(3 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 0
    clock.advance(4 * HOURS)  # silent for 7 hours (ANALYTICS_CHAIN_STALE_AFTER is 6)
    assert enqueue_analytics_syncs(runtime) == 1


def test_a_first_import_still_running_is_not_scheduled(make_client, sim, runtime, clock):
    c = _connect(make_client, sim)
    sim.day_used[AU] = 200_000  # the first import pauses on its first report
    _link(c)
    clock.advance(3 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 0


def test_the_scheduler_task_runs_once_per_tick(runtime):
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule["analytics-sync"]
    assert schedule["task"] == "advegax.schedule.analytics_sync"
    assert schedule["schedule"] == runtime.settings.SCHEDULE_ANALYTICS_SYNC_TICK.total_seconds()


def test_the_scheduler_reads_only_four_columns_of_other_tenants(owner, runtime):
    with runtime.db.transaction(system=True) as session:
        count = session.execute(text("SELECT count(id) FROM analytics_properties")).scalar_one()
        assert count == 1
    with (
        pytest.raises(Exception, match="permission denied"),
        runtime.db.transaction(system=True) as session,
    ):
        session.execute(text("SELECT name FROM analytics_properties")).all()


def test_the_scheduler_skips_a_platform_not_offered_here(owner, runtime, clock):
    runtime.providers._providers.pop("google_analytics")
    clock.advance(3 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 0


# ------------------------------------------------------------------ pacing (Q-5-7)
def test_with_plenty_left_nothing_waits(make_client, sim, admin_engine):
    c = _connect(make_client, sim)
    _link(c)
    state = _state(admin_engine)
    assert (state["import_progress"], state["last_error_code"]) == (100, None)


def test_with_little_left_each_step_waits_a_little(make_client, sim, runtime, admin_engine, clock):
    c = _connect(make_client, sim)
    sim.hour_used[AU] = 11_000  # AdVegaX's share of the hour: 3,000 of 14,000 left (21 %)
    _link(c)
    state = _state(admin_engine)
    assert (state["status"], state["import_progress"]) == ("importing", 5 + 95 * 17 // 396)
    assert (state["last_error_code"], state["health_code"]) == (None, None)  # slower, not paused
    job = _job(admin_engine, state["import_job_id"])
    assert (job["status"], job["attempts"]) == ("queued", 0)
    assert 110 <= job["wait"] <= 125  # two minutes
    sim.hour_used[AU] = 0
    done = _finish_chain(runtime, c, admin_engine, clock, step=timedelta(minutes=3))
    assert (done["import_progress"], done["status"]) == (100, "active")


@pytest.mark.parametrize(
    ("used", "kind"),
    [
        ({"hour_used": 13_000}, "AdVegaX's share of the hour"),  # 1,000 of 14,000 left
        ({"hour_used": 37_000}, "the property's hour"),  # project share also low
        ({"day_used": 190_000}, "the property's day"),  # 10,000 of 200,000 left (5 %)
    ],
)
def test_with_almost_nothing_left_the_property_pauses_until_the_next_hour(
    make_client, sim, runtime, admin_engine, clock, used, kind
):
    c = _connect(make_client, sim)
    for name, value in used.items():
        getattr(sim, name)[AU] = value
    before = len(sim.calls(":batchRunReports"))
    _link(c)
    assert len(sim.calls(":batchRunReports")) - before == 1, kind  # then AdVegaX stops asking
    state = _state(admin_engine)
    assert (state["status"], state["last_error_code"], state["health_code"]) == (
        "importing",
        "quota_waiting",
        "rate_limited",  # "Google is limiting how much AdVegaX can read"
    )
    job = _job(admin_engine, state["import_job_id"])
    assert (job["status"], job["attempts"]) == ("queued", 0)  # no retry attempt used
    assert 3640 <= job["wait"] <= 3665  # 01:01 UTC, just after the hour is renewed

    _link(c, US)  # another property carries on
    assert _state(admin_engine, US)["status"] == "active"

    sim.hour_used[AU] = sim.day_used[AU] = 0  # Google renewed the tokens
    done = _finish_chain(runtime, c, admin_engine, clock)
    assert (done["import_progress"], done["last_error_code"], done["health_code"]) == (
        100,
        None,
        None,
    )


def test_googles_quota_answer_pauses_a_scheduled_run(owner, sim, runtime, admin_engine, clock):
    clock.advance(3 * HOURS)
    sim.day_used[AU] = 200_000
    enqueue_analytics_syncs(runtime)
    state = _state(admin_engine)
    assert (state["status"], state["last_error_code"], state["health_code"]) == (
        "active",  # the figures already imported stay available
        "quota_waiting",
        "rate_limited",
    )
    assert 880 <= _job(admin_engine, state["import_job_id"])["wait"] <= 905
    sim.day_used[AU] = 0
    done = _finish_chain(runtime, owner, admin_engine, clock, step=timedelta(minutes=16))
    assert (done["last_error_code"], done["health_code"], done["last_quick_at"]) == (
        None,
        None,
        clock.now(),
    )


def test_the_last_step_never_waits(owner, sim, runtime, admin_engine, clock):
    clock.advance(3 * HOURS)
    sim.hour_used[AU] = 13_500  # one report later almost nothing is left
    enqueue_analytics_syncs(runtime)  # one slice: nothing follows that calls Google
    state = _state(admin_engine)
    assert (state["import_job_id"], state["health_code"]) == (None, None)


# ------------------------------------------------------------------ health
def test_a_removed_permission_shows_on_the_property_and_clears_when_it_returns(
    owner, sim, runtime, admin_engine, clock
):
    sim.property_errors[AU] = (403, "PERMISSION_DENIED", None)
    clock.advance(3 * HOURS)
    enqueue_analytics_syncs(runtime)
    state = _state(admin_engine)
    assert (state["status"], state["health_code"], state["last_error_code"]) == (
        "active",  # imported figures stay; the property says why it is not updating
        "no_property_access",
        "no_property_access",
    )
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"
    del sim.property_errors[AU]
    clock.advance(3 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 1
    assert _state(admin_engine)["health_code"] is None


def test_a_property_deleted_later_says_so(owner, sim, runtime, admin_engine, clock):
    sim.properties[AU].deleted = True
    clock.advance(3 * HOURS)
    enqueue_analytics_syncs(runtime)
    state = _state(admin_engine)
    assert (state["status"], state["health_code"]) == ("active", "property_deleted")
    (prop,) = _rows(admin_engine, "SELECT platform_status FROM analytics_properties")
    assert prop["platform_status"] == "deleted"


def test_a_sign_in_google_no_longer_accepts_needs_reconnecting(
    owner, sim, runtime, admin_engine, clock
):
    sim.refresh_tokens.clear()  # the person removed AdVegaX in their Google account
    clock.advance(3 * HOURS)  # the access token has expired too
    enqueue_analytics_syncs(runtime)
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("expired", "google_sign_in_rejected")
    clock.advance(3 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 0  # nothing more until reconnected


# ------------------------------------------------------------------ "Sync now"
def _sync_now(runtime, owner, admin_engine, external_id=AU):
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        prop = session.query(AnalyticsProperty).filter_by(external_property_id=external_id).one()
        return request_sync(session, runtime, prop, requested_by=_user_id(admin_engine))


def test_sync_now_rereads_14_days(owner, sim, runtime, admin_engine, clock):
    clock.advance(HOURS)
    before = len(sim.calls(":batchRunReports"))
    _, mode = _sync_now(runtime, owner, admin_engine)
    assert mode is SyncMode.NIGHTLY
    assert _ranges(sim, before) == [(date(2026, 10, 1), TODAY)]
    assert _state(admin_engine)["last_nightly_at"] == clock.now()
    (audit,) = _rows(
        admin_engine,
        "SELECT actor_type, metadata FROM audit_logs "
        "WHERE action = 'analytics_property.sync_started'",
    )
    assert audit["actor_type"] == "user" and audit["metadata"]["mode"] == "nightly"


def test_sync_now_while_a_run_is_going_is_refused(owner, runtime, admin_engine, clock):
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE analytics_sync_state SET import_job_id = :j, updated_at = :t"),
            {"j": uuid.uuid4(), "t": clock.now()},
        )
    with pytest.raises(AnalyticsSyncInProgress):
        _sync_now(runtime, owner, admin_engine)


def test_sync_now_is_limited_per_property(owner, runtime, admin_engine):
    for _ in range(runtime.settings.THROTTLE_ANALYTICS_PROPERTY_RESYNC_PER_HOUR):
        _sync_now(runtime, owner, admin_engine)
    with pytest.raises(RateLimited):
        _sync_now(runtime, owner, admin_engine)


def test_sync_now_needs_a_linked_property(owner, runtime, admin_engine):
    unlinked = owner.post(
        f"/organizations/{owner.org}/resources/{owner.resources[AU]['id']}/unlink"
    )
    assert unlinked.status_code == 200
    with pytest.raises(AnalyticsPropertyNotSyncing):
        _sync_now(runtime, owner, admin_engine)


def test_sync_now_restarts_a_first_import_that_failed(make_client, sim, runtime, admin_engine):
    c = _connect(make_client, sim)
    sim.property_errors[US] = (403, "PERMISSION_DENIED", None)
    _link(c, US)
    assert _state(admin_engine, US)["status"] == "error"
    del sim.property_errors[US]
    _, mode = _sync_now(runtime, c, admin_engine, US)
    assert mode is SyncMode.INITIAL
    state = _state(admin_engine, US)
    assert (state["status"], state["import_progress"], state["health_code"]) == (
        "active",
        100,
        None,
    )
