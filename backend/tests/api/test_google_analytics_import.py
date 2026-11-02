"""Importing a linked GA4 property (task 5-05, PLAN §8, §9, Q-5-4, Q-5-5, Q-5-8).

Linking creates the analytics property and starts its first import: the property's details,
then 13 months of daily figures, one calendar month per job step, each step one Google call
holding the three views (total, channel, source / medium / campaign). Money stays exact in the
property's currency, days are the property's own days, users are never added up, each slice
replaces what was stored for its days, and the total view has a real zero for every day Google
reports no activity.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.analytics import importer
from app.domains.jobs.service import ClaimedJob
from sqlalchemy import text

from tests.ga4_sim import DAY_TOKENS, GA4Sim, Visit, build_provider

SUB = "108000000000000000001"
AU, US = "111", "211"
TODAY = date(2026, 10, 14)  # the test clock (00:00 UTC) is 11:00 in Sydney
HISTORY_FROM = date(2025, 9, 14)  # 395 days earlier
DAYS = (TODAY - HISTORY_FROM).days + 1
BUSY_DAY = date(2026, 10, 1)


@pytest.fixture
def sim(runtime, clock):
    s = GA4Sim(clock=clock)
    s.add_account("900", "Eve Zone")
    au = s.add_property(AU, "900", SUB, display_name="Eve Zone AU")
    s.add_property(
        US, "900", SUB, display_name="Eve Zone US", currency="USD", time_zone="America/Los_Angeles"
    )
    au.traffic = [
        Visit(
            HISTORY_FROM,
            sessions=3,
            engaged=1,
            users=3,
            new_users=3,
            purchases=0,
            revenue=Decimal("0"),
            key_events=Decimal("0"),
        ),
        Visit(BUSY_DAY),
        Visit(
            BUSY_DAY,
            channel="Paid Search",
            source="google",
            medium="cpc",
            campaign="Spring Sale",
            sessions=5,
            engaged=4,
            users=4,
            new_users=2,
            key_events=Decimal("1.5"),
            purchases=2,
            revenue=Decimal("120.50"),
        ),
        Visit(date(2026, 4, 10), purchases=0, revenue=Decimal("-30.00")),  # refunds
        Visit(TODAY, sessions=2, engaged=2, users=2, new_users=1),
    ]
    au.day_users[BUSY_DAY] = 11  # Google's distinct users for the day, not 8 + 4
    s.properties[US].traffic = [Visit(date(2026, 10, 13)), Visit(TODAY)]
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def owner(make_client, sim):
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


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _link(owner, external_id=AU):
    response = owner.post(
        f"/organizations/{owner.org}/resources/{owner.resources[external_id]['id']}/link"
    )
    assert response.status_code == 201, response.text


def _unlink(owner, external_id=AU):
    response = owner.post(
        f"/organizations/{owner.org}/resources/{owner.resources[external_id]['id']}/unlink"
    )
    assert response.status_code == 200, response.text


def _daily(admin_engine, breakdown, external_id=AU):
    return _rows(
        admin_engine,
        "SELECT d.* FROM analytics_daily d JOIN analytics_properties p ON p.id = d.property_id "
        "WHERE d.breakdown = :b AND p.external_property_id = :ext "
        "ORDER BY d.day, d.dimension_key",
        b=breakdown,
        ext=external_id,
    )


def _property(admin_engine, external_id=AU):
    (row,) = _rows(
        admin_engine,
        "SELECT p.*, s.import_progress, s.import_job_id, s.import_cursor, s.sync_mode, "
        "s.last_error_code, s.last_nightly_at FROM analytics_properties p "
        "JOIN analytics_sync_state s ON s.property_id = p.id WHERE p.external_property_id = :ext",
        ext=external_id,
    )
    return row


def _ranges(sim, before=0):
    calls = sim.calls(":batchRunReports")[before:]
    spans = []
    for call in calls:
        requests = json.loads(call.content)["requests"]
        assert len(requests) == 4  # the four views in one call (landing pages: Phase 7)
        assert len({json.dumps(r["dateRanges"]) for r in requests}) == 1
        (span,) = requests[0]["dateRanges"]
        spans.append((date.fromisoformat(span["startDate"]), date.fromisoformat(span["endDate"])))
    return spans


# ------------------------------------------------------------------ the first import
def test_linking_imports_13_months_in_monthly_slices(owner, sim, admin_engine):
    _link(owner)
    prop = _property(admin_engine)
    assert (prop["status"], prop["platform_status"], prop["import_progress"]) == (
        "active",
        "active",
        100,
    )
    assert (prop["name"], prop["account_name"], prop["currency"], prop["timezone"]) == (
        "Eve Zone AU",
        "Eve Zone",
        "AUD",
        "Australia/Sydney",
    )
    assert prop["history_from"] == HISTORY_FROM
    assert prop["first_import_completed_at"] is not None
    assert (prop["import_job_id"], prop["import_cursor"], prop["sync_mode"]) == (None,) * 3
    spans = _ranges(sim)
    assert spans[0] == (HISTORY_FROM, date(2025, 9, 30))
    assert spans[-1] == (date(2026, 10, 1), TODAY)
    assert len(spans) == 14  # September 2025 … October 2026, one call each
    assert all(b[0] == a[1] + timedelta(days=1) for a, b in pairwise(spans))
    assert all(a[0].month == a[1].month for a in spans)
    assert sim.calls(":runReport") == []  # every view fitted in one page
    totals = _daily(admin_engine, "total")
    assert len(totals) == DAYS  # every day once
    assert (totals[0]["day"], totals[-1]["day"]) == (HISTORY_FROM, TODAY)


def test_figures_are_exact_and_users_are_never_added_up(owner, admin_engine):
    _link(owner)
    total = next(r for r in _daily(admin_engine, "total") if r["day"] == BUSY_DAY)
    assert (total["sessions"], total["engaged_sessions"], total["new_users"]) == (15, 10, 5)
    assert total["total_users"] == 11  # Google's count for the day
    assert (total["key_events"], total["purchases"]) == (Decimal("3.500000"), 3)
    assert total["purchase_revenue"] == Decimal("170.450000")
    assert (total["currency"], total["source"], total["dimension_key"]) == (
        "AUD",
        "platform_reported",
        "total",
    )
    channels = {
        r["channel_group"]: r for r in _daily(admin_engine, "channel") if r["day"] == BUSY_DAY
    }
    assert sorted(channels) == ["Organic Search", "Paid Search"]
    assert (channels["Paid Search"]["total_users"], channels["Paid Search"]["dimension_key"]) == (
        4,
        "Paid Search",
    )
    sources = [r for r in _daily(admin_engine, "source") if r["day"] == BUSY_DAY]
    paid = next(r for r in sources if r["traffic_medium"] == "cpc")
    assert (paid["traffic_source"], paid["campaign"], paid["dimension_key"]) == (
        "google",
        "Spring Sale",
        "google|cpc|Spring Sale",
    )
    assert paid["purchase_revenue"] == Decimal("120.500000")


def test_days_without_activity_are_real_zeros_in_the_total_only(owner, admin_engine):
    _link(owner)
    quiet = next(r for r in _daily(admin_engine, "total") if r["day"] == date(2026, 1, 5))
    assert (quiet["sessions"], quiet["total_users"], quiet["purchases"]) == (0, 0, 0)
    assert (quiet["key_events"], quiet["purchase_revenue"]) == (Decimal(0), Decimal(0))
    for view in ("channel", "source"):
        assert {r["day"] for r in _daily(admin_engine, view)} == {
            HISTORY_FROM,
            BUSY_DAY,
            date(2026, 4, 10),
            TODAY,
        }


def test_refunds_can_make_a_days_revenue_negative(owner, admin_engine):
    _link(owner)
    refund = next(r for r in _daily(admin_engine, "total") if r["day"] == date(2026, 4, 10))
    assert refund["purchase_revenue"] == Decimal("-30.000000")


def test_days_and_money_are_the_propertys_own(owner, sim, admin_engine):
    _link(owner, US)  # Los Angeles: still 13 October when it is 14 October in Sydney
    prop = _property(admin_engine, US)
    assert (prop["currency"], prop["timezone"]) == ("USD", "America/Los_Angeles")
    assert prop["history_from"] == date(2025, 9, 13)
    totals = _daily(admin_engine, "total", US)
    assert totals[-1]["day"] == date(2026, 10, 13)
    assert {r["currency"] for r in totals} == {"USD"}
    assert _ranges(sim)[-1] == (date(2026, 10, 1), date(2026, 10, 13))


def test_googles_data_quality_signals_are_kept(owner, sim, admin_engine):
    au = sim.properties[AU]
    au.metadata = {
        "total": {"subjectToThresholding": True},
        "source": {"dataLossFromOtherRow": True, "samplingMetadatas": [{"samplesReadCount": "9"}]},
    }
    au.traffic.append(
        Visit(
            BUSY_DAY,
            channel="(other)",
            source="(other)",
            medium="(other)",
            campaign="(other)",
            sessions=1,
        )
    )
    _link(owner)
    totals = _daily(admin_engine, "total")
    october = [r for r in totals if r["day"] >= date(2026, 10, 1)]
    # The real zeros of a read carry what Google said about that read's total view.
    assert len(october) == 14 and all(r["thresholded"] for r in october)
    assert not any(r["other_row"] or r["sampled"] or r["truncated"] for r in totals)
    sources = _daily(admin_engine, "source")
    assert all(r["other_row"] and r["sampled"] for r in sources)
    channels = _daily(admin_engine, "channel")
    assert [r["channel_group"] for r in channels if r["other_row"]] == ["(other)"]


def test_rare_sources_are_combined_into_one_marked_other_row(owner, sim, runtime, admin_engine):
    runtime.settings = runtime.settings.model_copy(update={"ANALYTICS_SOURCE_ROWS_PER_DAY": 10})
    day = date(2026, 10, 2)
    sim.properties[AU].traffic += [
        Visit(
            day,
            source=f"site{n:02}.example",
            medium="referral",
            sessions=100 - n,
            users=5,
            new_users=1,
            revenue=Decimal("1.10"),
        )
        for n in range(15)
    ]
    _link(owner)
    rows = {r["traffic_source"]: r for r in _daily(admin_engine, "source") if r["day"] == day}
    assert len(rows) == 10
    assert {f"site{n:02}.example" for n in range(9)} <= set(rows)  # the most sessions kept
    other = rows["(other)"]
    assert (other["other_row"], other["dimension_key"]) == (True, "(other)|(other)|(other)")
    assert other["sessions"] == sum(100 - n for n in range(9, 15))
    assert other["purchase_revenue"] == Decimal("6.600000")
    assert (other["total_users"], other["new_users"]) == (None, None)  # never added up
    total = next(r for r in _daily(admin_engine, "total") if r["day"] == day)
    assert total["total_users"] == 75  # the day's own count is untouched


def test_audit_and_logs_record_the_import_without_secrets(owner, sim, admin_engine, caplog):
    caplog.set_level("INFO")
    _link(owner)
    actions = [
        r["action"]
        for r in _rows(admin_engine, "SELECT action FROM audit_logs ORDER BY created_at")
    ]
    assert "analytics_property.import_started" in actions
    assert "analytics_property.import_completed" in actions
    audit = json.dumps(_rows(admin_engine, "SELECT * FROM audit_logs"), default=str)
    lines = [r.getMessage() for r in caplog.records]
    for secret in (*sim.refresh_tokens, *sim.access_tokens):
        assert secret not in audit
        assert all(secret not in line for line in lines)


# ------------------------------------------------------------------ linking again
def test_linking_again_rereads_the_last_14_days_and_replaces_them(owner, sim, admin_engine):
    _link(owner)
    _unlink(owner)
    before = len(sim.calls(":batchRunReports"))
    sim.properties[AU].traffic[1] = Visit(BUSY_DAY, sessions=40, users=30)  # Google revised it
    sim.properties[AU].traffic[0] = Visit(HISTORY_FROM, sessions=99)  # outside the window
    _link(owner)
    assert _ranges(sim, before) == [(date(2026, 10, 1), TODAY)]  # 14 days, one call
    assert len(_rows(admin_engine, "SELECT id FROM analytics_properties")) == 1
    totals = {r["day"]: r for r in _daily(admin_engine, "total")}
    assert totals[BUSY_DAY]["sessions"] == 45
    assert totals[HISTORY_FROM]["sessions"] == 3  # not re-read: kept as imported
    organic = [
        r
        for r in _daily(admin_engine, "channel")
        if r["day"] == BUSY_DAY and r["channel_group"] == "Organic Search"
    ]
    assert [r["sessions"] for r in organic] == [40]  # replaced, never added to the old row
    prop = _property(admin_engine)
    assert (prop["status"], prop["last_nightly_at"] is not None) == ("active", True)
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert "analytics_property.sync_started" in actions


# ------------------------------------------------------------------ problems
def test_a_property_deleted_in_google_analytics_stops_with_a_plain_reason(owner, sim, admin_engine):
    sim.properties[AU].deleted = True  # moved to the bin after AdVegaX found it
    sim.properties[AU].users.add(SUB)
    _link(owner)
    prop = _property(admin_engine)
    assert (prop["status"], prop["platform_status"], prop["health_code"]) == (
        "error",
        "deleted",
        "property_deleted",
    )
    assert prop["last_error_code"] == "property_deleted"
    assert sim.calls(":batchRunReports") == []
    assert _daily(admin_engine, "total") == []


def test_a_property_no_longer_readable_stops_with_a_plain_reason(owner, sim, admin_engine):
    sim.property_errors[AU] = (403, "PERMISSION_DENIED", None)
    _link(owner)
    prop = _property(admin_engine)
    assert (prop["status"], prop["health_code"]) == ("error", "no_property_access")
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"  # the sign-in is fine; only this property is affected


def test_a_change_of_currency_or_time_zone_is_recorded_not_applied(owner, sim, admin_engine):
    sim.properties[AU].currency = "NZD"
    _link(owner)
    prop = _property(admin_engine)
    assert (prop["currency"], prop["health_code"], prop["status"]) == (
        "AUD",
        "property_details_changed",
        "active",
    )
    assert {r["currency"] for r in _daily(admin_engine, "total")} == {"AUD"}


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


def test_a_used_up_quota_pauses_only_this_property_and_continues(
    owner, sim, runtime, admin_engine, clock
):
    sim.day_used[AU] = DAY_TOKENS  # Google: this property's tokens for today are used up
    _link(owner)
    prop = _property(admin_engine)
    assert (prop["status"], prop["last_error_code"]) == ("importing", "quota_waiting")
    job = _job(admin_engine, prop["import_job_id"])
    assert (job["status"], job["attempts"]) == ("queued", 0)  # no retry attempt used
    assert 880 <= job["wait"] <= 905  # 15 minutes
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"
    _link(owner, US)  # another property carries on
    assert _property(admin_engine, US)["status"] == "active"

    sim.day_used[AU] = 0
    for _ in range(30):
        state = _property(admin_engine)
        if state["import_job_id"] is None:
            break
        clock.advance(timedelta(minutes=16))
        _run_waiting_step(runtime, owner, state)
    done = _property(admin_engine)
    assert (done["status"], done["import_progress"], done["last_error_code"]) == (
        "active",
        100,
        None,
    )
