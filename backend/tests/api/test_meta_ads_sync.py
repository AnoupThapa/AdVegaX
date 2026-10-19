"""Ongoing Meta sync: pacing, pauses, sign-in expiry and health (task 4-06, Q-4-2, Q-4-12).

* Meta's usage headers are read on every answer: above 75 % each call waits a little; at
  the limit, or when Meta names a wait, that ad account's run pauses (no retry attempt is
  used) and continues by itself. Meta's limit for AdVegaX's whole app pauses every account.
* The sign-in lasts about 60 days and cannot be renewed without the person: a warning is
  recorded 14 and 3 days before the end, and at the end the connection shows "Needs
  reconnecting" without AdVegaX calling Meta. Reconnecting starts a new 60 days.
* An ad account with an unpaid balance or under review says so in plain words.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.advertising import importer
from app.domains.advertising.importer import QUOTA_WAITING, SyncMode, start_sync
from app.domains.advertising.models import AdAccount
from app.domains.integrations import jobs as integration_jobs
from app.domains.jobs.service import ClaimedJob
from app.providers.base.capabilities import Capability, ProviderCapabilities
from sqlalchemy import text

from tests.meta_sim import MetaSim, build_provider, sample_insights, sample_structure, usage

USER = "10160000000000001"
AU, NZ = "act_1001", "act_1002"


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def sim(runtime, clock, sleeps):
    s = MetaSim(clock=clock)
    s.add_user(USER)
    for account_id, money, zone in (
        (AU, "AUD", "Australia/Sydney"),
        (NZ, "NZD", "Pacific/Auckland"),
    ):
        account = s.add_account(account_id, USER, currency=money, timezone_name=zone)
        sample_insights(sample_structure(account), "2026-10-01")
    runtime.providers.register(build_provider(s, sleeps=sleeps))
    return s


def _connect(client, sim):
    started = client.post(
        f"/organizations/{client.org}/connections/meta_ads/start", {"params": {}}
    ).json()["data"]["authorize_url"]
    response = client.http.get(
        "/api/v1/connections/meta_ads/callback",
        params=sim.approve(started, USER),
        follow_redirects=False,
    )
    query = {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}
    assert query["status"] == "connected", query
    client.conn = query["connection_id"]


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.email = f"meta-{uuid.uuid4().hex[:6]}@example.com"
    c.signup(c.email)
    c.org = c.create_org("Eve Zone")["id"]
    _connect(c, sim)
    resources = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    c.resources = {r["external_id"]: r for r in resources}
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
        "SELECT s.ad_account_id, s.import_job_id, s.import_cursor, s.import_progress, "
        "s.last_error_code FROM ad_sync_state s JOIN ad_accounts a ON a.id = s.ad_account_id "
        "WHERE a.external_account_id = :id",
        id=external_id,
    )
    return row


def _run_waiting_step(runtime, owner, state):
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


def _finish_chain(runtime, owner, admin_engine, clock, external_id=AU, step=timedelta(minutes=1)):
    for _ in range(60):
        state = _state(admin_engine, external_id)
        if state["import_job_id"] is None:
            return state
        clock.advance(step)
        _run_waiting_step(runtime, owner, state)
    raise AssertionError("the chain did not finish")


def _job(admin_engine, job_id):
    (row,) = _rows(
        admin_engine,
        "SELECT status, attempts, last_error_code, "
        "EXTRACT(EPOCH FROM next_attempt_at - now()) AS wait FROM job_runs WHERE id = :id",
        id=job_id,
    )
    return row


# ------------------------------------------------------------------ pacing
def test_below_75_percent_nothing_waits(owner, sim, sleeps, admin_engine):
    sim.usage_headers = usage(60)
    _link(owner)
    assert sleeps == []
    assert _state(admin_engine)["import_progress"] == 100


def test_above_75_percent_each_call_waits_a_little(owner, sim, sleeps, admin_engine):
    sim.usage_headers = usage(85)
    _link(owner)
    assert sleeps and set(sleeps) == {5.0}  # halfway from 75 % to 95 %: 5 of 10 seconds
    assert _state(admin_engine)["import_progress"] == 100  # slower, never stopped


def test_at_the_limit_the_account_pauses_and_continues_by_itself(
    owner, sim, runtime, admin_engine, clock
):
    sim.usage_headers = usage(97, regain_minutes=7)
    before = len(sim.requests)
    _link(owner)
    assert len(sim.requests) - before == 1  # the account read; then AdVegaX stops calling
    state = _state(admin_engine)
    assert state["last_error_code"] == QUOTA_WAITING  # waiting, not failed
    job = _job(admin_engine, state["import_job_id"])
    assert (job["status"], job["attempts"]) == ("queued", 0)  # no retry attempt used
    assert 400 <= job["wait"] <= 425  # Meta's own estimate: 7 minutes
    (account,) = _rows(admin_engine, "SELECT status FROM ad_accounts")
    assert account["status"] == "importing"
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"

    _run_waiting_step(runtime, owner, state)  # too early: still paused, Meta is not called
    assert len(sim.requests) - before == 1
    sim.usage_headers = usage(20)
    clock.advance(timedelta(minutes=8))
    done = _finish_chain(runtime, owner, admin_engine, clock)
    assert (done["import_progress"], done["last_error_code"]) == (100, None)


def test_metas_too_many_calls_error_pauses_only_that_account(
    owner, sim, runtime, admin_engine, clock
):
    sim.fail_next.append((400, 80004, 2446079))  # ads management: too many calls
    _link(owner)
    state = _state(admin_engine)
    assert state["last_error_code"] == QUOTA_WAITING
    assert _job(admin_engine, state["import_job_id"])["attempts"] == 0
    _link(owner, NZ)  # another ad account carries on
    assert _state(admin_engine, NZ)["import_progress"] == 100
    clock.advance(timedelta(minutes=11))  # no estimate from Meta: 10 minutes
    assert _finish_chain(runtime, owner, admin_engine, clock)["import_progress"] == 100


def test_metas_limit_for_the_whole_app_pauses_every_account(
    owner, sim, runtime, admin_engine, clock
):
    sim.fail_next.append((400, 4, 1504022))
    _link(owner)
    assert _state(admin_engine)["last_error_code"] == QUOTA_WAITING
    before = len(sim.requests)
    _link(owner, NZ)
    assert len(sim.requests) == before  # every Meta account waits: nothing is sent
    assert _state(admin_engine, NZ)["last_error_code"] == QUOTA_WAITING
    clock.advance(timedelta(minutes=11))
    for account_id in (AU, NZ):
        done = _finish_chain(runtime, owner, admin_engine, clock, account_id)
        assert done["import_progress"] == 100


# ------------------------------------------------------------------ sign-in expiry
def _audit(admin_engine, action):
    return _rows(
        admin_engine,
        "SELECT metadata AS metadata_json FROM audit_logs WHERE action = :action "
        "ORDER BY created_at",
        action=action,
    )


def _connection(admin_engine):
    (row,) = _rows(admin_engine, "SELECT status, last_error_code FROM external_connections")
    return row


def test_warnings_14_and_3_days_before_the_end_then_needs_reconnecting(
    owner, sim, runtime, admin_engine, clock
):
    assert integration_jobs.check_sign_in_expiry(runtime) == 0  # 60 days left
    clock.advance(timedelta(days=47))  # 13 days left
    assert integration_jobs.check_sign_in_expiry(runtime) == 1
    assert integration_jobs.check_sign_in_expiry(runtime) == 0  # once per warning
    clock.advance(timedelta(days=10))  # 3 days left
    assert integration_jobs.check_sign_in_expiry(runtime) == 1
    warnings = [r["metadata_json"] for r in _audit(admin_engine, "connection.sign_in_expiring")]
    assert [w["days"] for w in warnings] == [14, 3]
    assert len({w["ends_at"] for w in warnings}) == 1
    assert _connection(admin_engine)["status"] == "active"

    clock.advance(timedelta(days=3, minutes=1))
    assert integration_jobs.check_sign_in_expiry(runtime) == 1
    assert _connection(admin_engine) == {"status": "expired", "last_error_code": "sign_in_expired"}
    assert integration_jobs.check_sign_in_expiry(runtime) == 0  # no longer active


def test_an_ended_sign_in_is_never_sent_to_meta(owner, sim, runtime, admin_engine, clock):
    _link(owner)
    clock.advance(timedelta(days=61))
    before = len(sim.requests)
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        start_sync(session, runtime, session.query(AdAccount).one(), SyncMode.QUICK)
    assert len(sim.requests) == before
    assert _connection(admin_engine) == {"status": "expired", "last_error_code": "sign_in_expired"}


def test_reconnecting_starts_a_new_sign_in_with_new_warnings(
    owner, sim, runtime, admin_engine, clock, make_client
):
    clock.advance(timedelta(days=50))
    assert integration_jobs.check_sign_in_expiry(runtime) == 1
    owner.login(owner.email)  # the earlier session ended while the clock moved on
    owner.refresh_csrf()
    _connect(owner, sim)  # the same Facebook account: the same connection, a new token
    assert _connection(admin_engine)["status"] == "active"
    assert integration_jobs.check_sign_in_expiry(runtime) == 0  # 60 days again
    clock.advance(timedelta(days=47))
    assert integration_jobs.check_sign_in_expiry(runtime) == 1
    ends = {
        r["metadata_json"]["ends_at"] for r in _audit(admin_engine, "connection.sign_in_expiring")
    }
    assert len(ends) == 2  # one warning per sign-in


def test_sign_ins_that_renew_themselves_get_no_warning(owner, sim, runtime, admin_engine, clock):
    provider = runtime.providers.get("meta_ads")
    provider.capabilities = ProviderCapabilities(frozenset({Capability.TOKEN_REFRESH}))
    clock.advance(timedelta(days=59))
    assert integration_jobs.check_sign_in_expiry(runtime) == 0
    assert _audit(admin_engine, "connection.sign_in_expiring") == []


@pytest.mark.parametrize(
    ("left", "expected"),
    [
        (timedelta(days=20), None),
        (timedelta(days=14), 14),
        (timedelta(days=5), 14),
        (timedelta(days=3), 3),
        (timedelta(hours=1), 3),
        (timedelta(0), 0),
        (-timedelta(days=1), 0),
    ],
)
def test_sign_in_warning(clock, left, expected):
    now = clock.now()
    assert integration_jobs.sign_in_warning(now + left, now, (14, 3)) == expected
    assert integration_jobs.sign_in_warning(None, now, (14, 3)) is None


# ------------------------------------------------------------------ health
@pytest.mark.parametrize(
    ("status", "reason"),
    [(3, "account_unsettled"), (7, "account_under_review"), (2, "account_not_enabled")],
)
def test_an_account_that_cannot_be_read_says_why(owner, sim, admin_engine, status, reason):
    sim.accounts[AU].account_status = status  # changed in Meta after discovery
    _link(owner)
    (account,) = _rows(admin_engine, "SELECT status, health_code FROM ad_accounts")
    assert account == {"status": "error", "health_code": reason}
    assert _state(admin_engine)["last_error_code"] == reason
    assert _connection(admin_engine)["status"] == "active"
