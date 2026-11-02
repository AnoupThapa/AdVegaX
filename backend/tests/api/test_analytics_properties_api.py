"""Analytics properties and their figures over the API (task 5-07, PLAN §10-§11).

Same rules as the store and ad account APIs: every member reads, managers and above "Sync
now", other organizations' data is a 404, money is an exact decimal string, every figure is
labelled as reported by the platform, rates are derived on read and say why when they cannot
be, days not read are "not synchronized" — never 0 — and **users are given per day only**
(Q-5-5). Golden values in two currencies and time zones (AUD / Sydney, USD / Los Angeles).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import text

from tests.ga4_sim import GA4Sim, Visit, build_provider
from tests.google_oauth_sim import CLIENT_SECRET

SUB = "108000000000000000001"
AU, US = "111", "211"
TODAY = date(2026, 10, 14)  # the test clock (00:00 UTC) is 11:00 in Sydney
BUSY = date(2026, 10, 1)
SIX = Decimal("0.000001")


def _sydney_traffic():
    return [
        Visit(BUSY),  # Organic Search · google / organic: 10 sessions, 49.95
        Visit(
            BUSY,
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
        Visit(
            date(2026, 10, 2),
            sessions=4,
            engaged=1,
            users=3,
            new_users=1,
            purchases=0,
            revenue=Decimal("0"),
            key_events=Decimal("0"),
        ),
        Visit(date(2026, 10, 3), purchases=0, revenue=Decimal("-30.00")),  # refunds
        Visit(
            TODAY,
            sessions=2,
            engaged=2,
            users=2,
            new_users=1,
            purchases=0,
            revenue=Decimal("0"),
            key_events=Decimal("1"),
        ),
    ]


@pytest.fixture
def sim(runtime, clock):
    s = GA4Sim(clock=clock)
    s.add_account("900", "Eve Zone")
    au = s.add_property(AU, "900", SUB, display_name="Eve Zone AU")
    us = s.add_property(
        US, "900", SUB, display_name="Eve Zone US", currency="USD", time_zone="America/Los_Angeles"
    )
    au.traffic = _sydney_traffic()
    au.day_users[BUSY] = 11  # Google's distinct users for the day, not 8 + 4
    us.traffic = [
        Visit(
            date(2026, 10, 13),
            sessions=7,
            engaged=7,
            users=6,
            new_users=6,
            purchases=1,
            revenue=Decimal("19.99"),
            key_events=Decimal("1"),
        ),
    ]
    runtime.providers.register(build_provider(s))
    return s


def _connect(make_client, sim, link=(AU,)):
    c = make_client()
    c.email = f"ga-{uuid.uuid4().hex[:6]}@example.com"
    c.signup(c.email)
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
    for external_id in link:
        linked = c.post(f"/organizations/{c.org}/resources/{c.resources[external_id]['id']}/link")
        assert linked.status_code == 201
    found = c.get(f"/organizations/{c.org}/analytics-properties").json()["data"]
    c.props = {p["external_property_id"]: p["id"] for p in found}
    c.prop = c.props.get(AU)
    return c


@pytest.fixture
def owner(make_client, sim):
    return _connect(make_client, sim, link=(AU, US))


@pytest.fixture
def viewer(make_client, owner):
    c = make_client()
    c.signup("ga-viewer@example.com")
    owner.invite_and_join(owner.org, c, "ga-viewer@example.com", "viewer")
    c.org, c.prop = owner.org, owner.prop
    return c


def _base(c, prop=None):
    return f"/organizations/{c.org}/analytics-properties/{prop or c.prop}"


def _data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _rate(numerator, denominator):
    return str((Decimal(numerator) / Decimal(denominator)).quantize(SIX, ROUND_HALF_EVEN))


def _metrics(c, query="", prop=None):
    return _data(c.get(f"{_base(c, prop)}/metrics/daily{query}"))


# ------------------------------------------------------------------ properties
def test_properties_are_listed_with_sync_status_and_health(owner):
    found = _data(owner.get(f"/organizations/{owner.org}/analytics-properties"))
    assert [p["external_property_id"] for p in found] == [AU, US]
    au = found[0]
    assert (au["provider"], au["source"], au["name"], au["account_name"]) == (
        "google_analytics",
        "platform_reported",
        "Eve Zone AU",
        "Eve Zone",
    )
    assert (au["currency"], au["currency_minor_units"], au["timezone"]) == (
        "AUD",
        2,
        "Australia/Sydney",
    )
    assert (au["status"], au["platform_status"], au["linked"], au["connection_status"]) == (
        "active",
        "active",
        True,
        "active",
    )
    assert au["history_from"] == "2025-09-14" and au["first_import_completed_at"]
    sync = au["sync"]
    assert (sync["running"], sync["progress"], sync["waiting_for_allowance"]) == (
        False,
        None,
        False,
    )
    assert sync["last_nightly_at"] and sync["last_error_code"] is None
    assert au["health"]["code"] is None and au["health"]["checked_at"]
    assert _data(owner.get(_base(owner))) == au


def test_a_property_of_another_organization_is_not_found(owner, make_client, sim):
    other = _connect(make_client, sim, link=())
    assert _data(other.get(f"/organizations/{other.org}/analytics-properties")) == []
    for path in (
        _base(other, owner.prop),
        f"{_base(other, owner.prop)}/metrics/daily",
    ):
        assert other.get(path).status_code == 404, path
    assert other.post(f"{_base(other, owner.prop)}/resync").status_code == 404
    assert owner.get(_base(owner, uuid.uuid4())).status_code == 404


def test_a_paused_run_says_google_is_limiting_reads_without_an_error(owner, admin_engine, clock):
    with admin_engine.begin() as db:
        db.execute(
            text(
                "UPDATE analytics_sync_state SET import_job_id = :j, updated_at = :t, "
                "sync_mode = 'nightly', last_error_code = 'quota_waiting', last_error_at = :t"
            ),
            {"j": uuid.uuid4(), "t": clock.now()},
        )
        db.execute(text("UPDATE analytics_properties SET health_code = 'rate_limited'"))
    prop = _data(owner.get(_base(owner)))
    assert (prop["sync"]["running"], prop["sync"]["mode"]) == (True, "nightly")
    assert prop["sync"]["waiting_for_allowance"] is True
    assert prop["sync"]["last_error_code"] is None  # waiting is not an error
    assert prop["health"]["code"] == "rate_limited"


# ------------------------------------------------------------------ the total view
def test_daily_figures_default_to_30_days_with_exact_money_and_derived_rates(owner):
    body = _metrics(owner)
    assert (body["source"], body["breakdown"], body["currency"], body["timezone"]) == (
        "platform_reported",
        "total",
        "AUD",
        "Australia/Sydney",
    )
    assert (body["from_day"], body["to_day"]) == ("2026-09-15", "2026-10-14")
    assert body["synced_from"] == "2025-09-14"
    assert body["processing_from"] == "2026-10-12"  # the last three days
    assert (body["items"], body["item_count"]) == ([], 0)
    days = {d["day"]: d for d in body["days"]}
    assert len(days) == 30
    assert [d["processing"] for d in body["days"]][-4:] == [False, True, True, True]
    busy = days["2026-10-01"]
    assert (busy["availability"], busy["sessions"], busy["engaged_sessions"]) == (
        "available",
        15,
        10,
    )
    assert busy["total_users"] == {"value": "11", "availability": "available", "reason": None}
    assert (busy["new_users"], busy["key_events"], busy["purchases"]) == (5, "3.500000", 3)
    assert busy["purchase_revenue"] == "170.450000"
    assert busy["engagement_rate"]["value"] == _rate(10, 15)
    assert busy["key_events_per_session"]["value"] == _rate("3.5", 15)
    assert busy["purchase_conversion_rate"]["value"] == _rate(3, 15)
    assert busy["revenue_per_session"]["value"] == _rate("170.45", 15)
    quiet = days["2026-09-20"]  # a day without activity: real zeros, rates explained
    assert (quiet["sessions"], quiet["purchase_revenue"]) == (0, "0.000000")
    assert quiet["engagement_rate"] == {
        "value": None,
        "availability": "unavailable",
        "reason": "no_sessions",
    }
    assert days["2026-10-03"]["purchase_revenue"] == "-30.000000"  # refunds

    totals = body["totals"]
    assert (totals["availability"], totals["sessions"], totals["engaged_sessions"]) == (
        "available",
        31,
        19,
    )
    assert (totals["new_users"], totals["purchases"]) == (10, 3)
    assert totals["key_events"] == "6.500000"
    assert totals["purchase_revenue"] == "140.450000"  # 170.45 on 1 October, -30.00 on the 3rd
    assert totals["total_users"] == {
        "value": None,
        "availability": "unavailable",
        "reason": "users_per_day_only",  # never added across days
    }
    assert totals["engagement_rate"]["value"] == _rate(19, 31)


def test_one_day_gives_that_days_users(owner):
    body = _metrics(owner, "?from=2026-10-01&to=2026-10-01")
    assert body["totals"]["total_users"]["value"] == "11"
    assert len(body["days"]) == 1


def test_figures_are_in_the_propertys_own_currency_and_days(owner):
    body = _metrics(owner, prop=owner.props[US])
    assert (body["currency"], body["timezone"], body["to_day"]) == (
        "USD",
        "America/Los_Angeles",
        "2026-10-13",  # still 13 October in Los Angeles
    )
    day = {d["day"]: d for d in body["days"]}["2026-10-13"]
    assert (day["sessions"], day["purchase_revenue"]) == (7, "19.990000")
    assert body["processing_from"] == "2026-10-11"


def test_days_not_read_are_not_synchronized_never_zero(owner):
    body = _metrics(owner, "?from=2025-09-10&to=2025-09-20")
    days = {d["day"]: d for d in body["days"]}
    early = days["2025-09-13"]  # before the 13 months read
    assert (early["availability"], early["sessions"], early["purchase_revenue"]) == (
        "not_synchronized",
        None,
        None,
    )
    assert early["total_users"]["availability"] == "not_synchronized"
    assert days["2025-09-14"]["availability"] == "available"
    assert body["totals"]["availability"] == "not_synchronized"
    assert body["totals"]["sessions"] is None


def test_a_property_whose_first_import_did_not_finish_has_no_figures(make_client, sim):
    sim.day_used[AU] = 200_000  # Google: no tokens left today, the import pauses
    c = _connect(make_client, sim)
    prop = _data(c.get(_base(c)))
    assert (prop["status"], prop["sync"]["running"], prop["sync"]["progress"]) == (
        "importing",
        True,
        5,
    )
    assert prop["sync"]["waiting_for_allowance"] is True
    body = _metrics(c)
    assert body["synced_from"] is None
    assert {d["availability"] for d in body["days"]} == {"not_synchronized"}


@pytest.mark.parametrize(
    "query",
    [
        "?from=2026-10-10&to=2026-10-01",
        "?from=2020-01-01&to=2026-10-01",
        "?breakdown=page",
        "?breakdown=source&limit=0",
        "?breakdown=source&limit=501",
        "?from=yesterday",
    ],
)
def test_invalid_requests_are_refused(owner, query):
    assert owner.get(f"{_base(owner)}/metrics/daily{query}").status_code == 422


def test_data_quality_notes_travel_with_the_days_and_the_period(owner, admin_engine):
    with admin_engine.begin() as db:
        db.execute(
            text(
                "UPDATE analytics_daily SET thresholded = true, sampled = true "
                "WHERE breakdown = 'total' AND day = '2026-10-01'"
            )
        )
    body = _metrics(owner)
    days = {d["day"]: d for d in body["days"]}
    assert days["2026-10-01"]["quality"] == {
        "other_row": False,
        "thresholded": True,
        "sampled": True,
        "truncated": False,
    }
    assert days["2026-10-02"]["quality"]["thresholded"] is False
    assert body["totals"]["quality"]["thresholded"] is True  # the period says so too


# ------------------------------------------------------------------ breakdowns
def test_figures_by_channel_have_their_own_period_totals(owner):
    body = _metrics(owner, "?breakdown=channel")
    assert (body["breakdown"], body["days"], body["item_count"]) == ("channel", [], 2)
    organic, paid = body["items"]  # most sessions first
    assert (organic["key"], organic["channel_group"]) == ("Organic Search", "Organic Search")
    assert organic["figures"]["sessions"] == 26  # 10 + 4 + 10 + 2
    assert organic["figures"]["total_users"]["reason"] == "users_per_day_only"
    assert (paid["key"], paid["figures"]["sessions"], paid["figures"]["purchase_revenue"]) == (
        "Paid Search",
        5,
        "120.500000",
    )
    assert paid["figures"]["engagement_rate"]["value"] == _rate(4, 5)
    assert body["totals"]["sessions"] == 31  # the property's total, not added from channels


def test_figures_by_source_medium_and_campaign(owner):
    body = _metrics(owner, "?breakdown=source&from=2026-10-01&to=2026-10-01")
    by_key = {i["key"]: i for i in body["items"]}
    paid = by_key["google|cpc|Spring Sale"]
    assert (paid["source"], paid["medium"], paid["campaign"], paid["channel_group"]) == (
        "google",
        "cpc",
        "Spring Sale",
        None,
    )
    assert paid["figures"]["total_users"]["value"] == "4"  # one day: that value's users
    limited = _metrics(owner, "?breakdown=source&limit=1")
    assert (len(limited["items"]), limited["item_count"]) == (1, 2)


def test_a_breakdown_for_a_period_not_read_has_no_items(owner):
    body = _metrics(owner, "?breakdown=channel&from=2025-09-01&to=2025-09-30")
    assert (body["items"], body["item_count"]) == ([], 0)
    assert body["totals"]["availability"] == "not_synchronized"


# ------------------------------------------------------------------ "Sync now"
def test_sync_now_starts_a_14_day_reread(owner):
    response = owner.post(f"{_base(owner)}/resync")
    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert (body["property_id"], body["mode"]) == (owner.prop, "nightly")
    assert uuid.UUID(body["job_id"])


def test_viewers_can_read_but_not_sync(viewer):
    assert viewer.get(f"/organizations/{viewer.org}/analytics-properties").status_code == 200
    assert viewer.get(f"{_base(viewer)}/metrics/daily").status_code == 200
    assert viewer.get(f"{_base(viewer)}/metrics/daily?breakdown=source").status_code == 200
    assert viewer.post(f"{_base(viewer)}/resync").status_code == 403


def test_sync_now_is_limited_and_needs_a_link(owner, runtime):
    for _ in range(runtime.settings.THROTTLE_ANALYTICS_PROPERTY_RESYNC_PER_HOUR):
        assert owner.post(f"{_base(owner)}/resync").status_code == 202
    assert owner.post(f"{_base(owner)}/resync").status_code == 429
    resource = owner.resources[AU]["id"]
    assert owner.post(f"/organizations/{owner.org}/resources/{resource}/unlink").status_code == 200
    refused = owner.post(f"{_base(owner, owner.props[US])}/resync")
    assert refused.status_code == 202  # the other property is unaffected
    owner.post(f"/organizations/{owner.org}/resources/{owner.resources[US]['id']}/unlink")
    refused = owner.post(f"{_base(owner, owner.props[US])}/resync")
    assert (refused.status_code, refused.json()["error"]["code"]) == (
        409,
        "ANALYTICS_PROPERTY_NOT_SYNCING",
    )
    assert _data(owner.get(_base(owner)))["linked"] is False  # still readable after unlinking


def test_sync_now_while_a_run_is_going_is_refused(owner, admin_engine, clock):
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE analytics_sync_state SET import_job_id = :j, updated_at = :t"),
            {"j": uuid.uuid4(), "t": clock.now()},
        )
    response = owner.post(f"{_base(owner)}/resync")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "SYNC_IN_PROGRESS")


# ------------------------------------------------------------------ secrets
def test_no_token_or_secret_appears_in_any_answer(owner, sim, clock):
    clock.advance(timedelta(minutes=5))
    answers = [
        owner.get(f"/organizations/{owner.org}/analytics-properties").text,
        owner.get(_base(owner)).text,
        owner.get(f"{_base(owner)}/metrics/daily").text,
        owner.get(f"{_base(owner)}/metrics/daily?breakdown=channel").text,
        owner.get(f"{_base(owner)}/metrics/daily?breakdown=source").text,
        owner.post(f"{_base(owner)}/resync").text,
    ]
    for answer in answers:
        for secret in (CLIENT_SECRET, *sim.access_tokens, *sim.refresh_tokens):
            assert secret not in answer
