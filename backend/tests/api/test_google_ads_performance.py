"""Importing a linked Google Ads account's daily figures (task 3-06, PLAN §9).

After the structure, the first import reads 13 months of daily figures at four levels
(account, campaign, ad group, ad), one calendar month per job step. Money stays exact in the
account currency, days are the account's own days, each slice replaces what was stored for
its days, and the account level has a real zero for every day Google reports no activity.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.advertising import importer
from app.domains.advertising.importer import month_slice, performance_cursor, start_import
from app.domains.advertising.models import AdAccount
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
AU = "1000000001"  # under Agency > Retail clients; Australia/Sydney, AUD
DIRECT = "1000000003"
SEARCH_DAY, PMAX_DAY = "2026-10-01", "2026-04-10"
TODAY = date(2026, 10, 14)  # the test clock (00:00 UTC) is 11:00 in Sydney
HISTORY_FROM = date(2025, 9, 14)  # 395 days earlier (Q-3-6)
DAYS = (TODAY - HISTORY_FROM).days + 1
BETWEEN = re.compile(rb"BETWEEN '([0-9-]{10})' AND '([0-9-]{10})'")


@pytest.fixture
def sim(runtime, clock):
    s = sample_hierarchy(GoogleAdsSim(clock=clock))
    for customer_id in (AU, DIRECT):
        sample_performance(sample_structure(s.customers[customer_id]), SEARCH_DAY, PMAX_DAY)
    runtime.providers.register(build_provider(s))
    return s


def _connect(make_client, sim):
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
    c.resources = {r["external_id"]: r for r in resources}
    return c


@pytest.fixture
def owner(make_client, sim):
    return _connect(make_client, sim)


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _link(owner, external_id=AU):
    response = owner.post(
        f"/organizations/{owner.org}/resources/{owner.resources[external_id]['id']}/link"
    )
    assert response.status_code == 201, response.text


def _perf(admin_engine, level):
    return _rows(
        admin_engine,
        "SELECT p.entity_key, p.day, p.impressions, p.clicks, p.cost, p.conversions, "
        "p.conversion_value, p.currency, p.source, c.external_campaign_id AS campaign, "
        "g.external_ad_group_id AS ad_group, a.external_ad_id AS ad "
        "FROM ad_performance_daily p LEFT JOIN ad_campaigns c ON c.id = p.campaign_id "
        "LEFT JOIN ad_groups g ON g.id = p.ad_group_id LEFT JOIN ads a ON a.id = p.ad_id "
        "WHERE p.level = :level ORDER BY p.day, p.entity_key",
        level=level,
    )


def _perf_calls(sim, before=0):
    return [
        r for r in sim.calls("googleAds:searchStream")[before:] if b"segments.date" in r.content
    ]


# ------------------------------------------------------------------ the first import
def test_linking_imports_13_months_of_daily_figures(owner, sim, admin_engine):
    _link(owner)
    account = _perf(admin_engine, "account")
    assert len(account) == DAYS  # every day, none missing and none twice
    assert (account[0]["day"], account[-1]["day"]) == (HISTORY_FROM, TODAY)
    by_day = {r["day"]: r for r in account}
    search = by_day[date(2026, 10, 1)]
    assert (search["impressions"], search["clicks"]) == (1200, 34)
    assert search["cost"] == Decimal("12.345678")  # exact, from micros
    assert (search["conversions"], search["conversion_value"]) == (
        Decimal("1.500000"),
        Decimal("89.900000"),
    )
    assert (search["currency"], search["source"]) == ("AUD", "platform_reported")
    pmax = by_day[date(2026, 4, 10)]
    assert (pmax["impressions"], pmax["clicks"], pmax["cost"]) == (500, 0, Decimal(0))
    quiet = by_day[date(2026, 1, 1)]  # Google sent nothing: a real zero, never missing
    assert (quiet["impressions"], quiet["clicks"], quiet["cost"], quiet["conversions"]) == (
        0,
        0,
        Decimal(0),
        Decimal(0),
    )

    campaigns = _perf(admin_engine, "campaign")
    assert [(r["entity_key"], r["day"], r["campaign"]) for r in campaigns] == [
        ("12", date(2026, 4, 10), "12"),  # Performance Max: no ad groups, figures still kept
        ("11", date(2026, 10, 1), "11"),
    ]
    (group,) = _perf(admin_engine, "ad_group")
    assert (group["entity_key"], group["campaign"], group["ad_group"]) == ("2101", "11", "2101")
    (ad,) = _perf(admin_engine, "ad")
    assert (ad["entity_key"], ad["campaign"], ad["ad_group"], ad["ad"]) == (
        "2101~90001",
        "11",
        "2101",
        "90001",
    )
    assert ad["cost"] == Decimal("12.345678")

    (state,) = _rows(
        admin_engine, "SELECT import_progress, import_cursor, import_job_id FROM ad_sync_state"
    )
    assert state == {"import_progress": 100, "import_cursor": None, "import_job_id": None}
    (row,) = _rows(admin_engine, "SELECT status, first_import_completed_at FROM ad_accounts")
    assert row["status"] == "active" and row["first_import_completed_at"] is not None


def test_the_figures_are_read_in_calendar_months_four_levels_each(owner, sim):
    before = len(sim.calls("googleAds:searchStream"))
    _link(owner)
    calls = _perf_calls(sim, before)
    assert len(calls) == 14 * 4  # 14 calendar months (part of Sep 2025 … part of Oct 2026)
    ranges = []
    for call in calls[::4]:
        found = BETWEEN.search(call.content)
        assert found is not None
        ranges.append(tuple(date.fromisoformat(v.decode()) for v in found.groups()))
    assert ranges[0] == (HISTORY_FROM, date(2025, 9, 30))
    assert ranges[1] == (date(2025, 10, 1), date(2025, 10, 31))
    assert ranges[5] == (date(2026, 2, 1), date(2026, 2, 28))
    assert ranges[-1] == (date(2026, 10, 1), TODAY)
    for (_, end), (start, _) in pairwise(ranges):
        assert start.toordinal() == end.toordinal() + 1  # no gap, no overlap
    resources = [re.search(rb"FROM (\w+)", c.content).group(1) for c in calls[:4]]
    assert resources == [b"customer", b"campaign", b"ad_group", b"ad_group_ad"]
    assert {c.headers.get("login-customer-id") for c in calls} == {"9000000001"}
    assert len(sim.calls("googleAds:searchStream")) - before == 5 + 56  # structure + figures


def test_days_are_the_accounts_own_days(make_client, sim, admin_engine):
    """At 00:00 UTC on 14 October it is still 13 October in Los Angeles."""
    sim.customers[DIRECT].timezone = "America/Los_Angeles"
    owner = _connect(make_client, sim)
    before = len(sim.calls("googleAds:searchStream"))
    _link(owner, DIRECT)
    last = BETWEEN.search(_perf_calls(sim, before)[-1].content)
    assert last is not None and last.group(2) == b"2026-10-13"
    account = _perf(admin_engine, "account")
    assert account[-1]["day"] == date(2026, 10, 13)
    assert len(account) == (date(2026, 10, 13) - date(2025, 9, 13)).days + 1


# ------------------------------------------------------------------ corrections
def test_a_new_import_replaces_the_figures_of_the_days_it_reads(owner, sim, runtime, admin_engine):
    _link(owner)
    customer = sim.customers[AU]
    # Google corrected the Search day (invalid clicks removed) and the PMax day's activity
    # was removed entirely.
    corrected = perf_row(
        SEARCH_DAY, campaign="11", impressions=1200, clicks=30, cost_micros=9_000_000
    )
    customer.performance = {
        "account": [perf_row(SEARCH_DAY, impressions=1200, clicks=30, cost_micros=9_000_000)],
        "campaign": [corrected],
        "ad_group": [],
        "ad": [],
    }
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        start_import(session, runtime, session.query(AdAccount).one(), requested_by=None)
    by_day = {r["day"]: r for r in _perf(admin_engine, "account")}
    assert len(by_day) == DAYS
    assert (by_day[date(2026, 10, 1)]["clicks"], by_day[date(2026, 10, 1)]["cost"]) == (
        30,
        Decimal("9.000000"),
    )
    assert by_day[date(2026, 4, 10)]["impressions"] == 0  # no stale 500 left behind
    assert [(r["entity_key"], r["clicks"]) for r in _perf(admin_engine, "campaign")] == [("11", 30)]
    assert _perf(admin_engine, "ad_group") == [] and _perf(admin_engine, "ad") == []


def test_figures_of_entities_not_in_the_structure_are_kept_unlinked(owner, sim, admin_engine):
    """Campaign 14 has a status AdVegaX cannot read, so it is not stored; its spend is still
    real and stays in the figures, unlinked, rather than being dropped."""
    sim.customers[AU].performance["campaign"].append(
        perf_row(SEARCH_DAY, campaign="14", impressions=7, cost_micros=1_000_000)
    )
    sim.customers[AU].performance["ad_group"].append(
        perf_row(SEARCH_DAY, campaign="14", ad_group="7777", impressions=7)
    )
    _link(owner)
    unknown = [r for r in _perf(admin_engine, "campaign") if r["entity_key"] == "14"]
    assert [(r["campaign"], r["cost"]) for r in unknown] == [(None, Decimal("1.000000"))]
    groups = {r["entity_key"]: r for r in _perf(admin_engine, "ad_group")}
    assert (groups["7777"]["campaign"], groups["7777"]["ad_group"]) == (None, None)


def test_a_duplicated_row_from_google_is_stored_once(owner, sim, admin_engine):
    rows = sim.customers[AU].performance["campaign"]
    rows.append(dict(rows[1]))
    _link(owner)
    assert len([r for r in _perf(admin_engine, "campaign") if r["entity_key"] == "11"]) == 1


# ------------------------------------------------------------------ failures
def _failing_perf_call(sim, number, status, error):
    seen = {"n": 0}
    real = sim.handler

    def handler(request):
        if b"segments.date" in request.content:
            seen["n"] += 1
            if seen["n"] == number:
                return sim.failure(status, error)
        return real(request)

    sim.handler = handler
    return seen


def test_a_failed_slice_is_retried_from_the_same_month(owner, sim, runtime, admin_engine):
    _failing_perf_call(sim, 10, 500, {"internalError": "INTERNAL_ERROR"})  # 3rd month, 2nd level
    _link(owner)
    (state,) = _rows(
        admin_engine,
        "SELECT ad_account_id, import_job_id, import_cursor, import_progress FROM ad_sync_state",
    )
    assert state["import_job_id"] is not None
    assert state["import_cursor"] == "perf:2025-11-01:2026-10-14"
    assert 50 < state["import_progress"] < 100
    importer.import_step(
        runtime,
        ClaimedJob(
            state["import_job_id"],
            uuid.UUID(owner.org),
            importer.JOB_AD_IMPORT_STEP,
            str(state["ad_account_id"]),
            2,
            5,
            None,
            None,
        ),
    )
    assert len(_perf(admin_engine, "account")) == DAYS  # nothing duplicated or lost
    (done,) = _rows(admin_engine, "SELECT import_progress FROM ad_sync_state")
    assert done["import_progress"] == 100


def test_the_per_connection_limit_pauses_the_chain_and_it_resumes(
    owner, sim, runtime, admin_engine, clock
):
    """With the real burst of 10 calls (5 a second), the third month is held back: its step
    is queued again with the wait, keeps its place, and finishes once time has passed."""
    runtime.providers.get("google_ads").rate_limit = (5.0, 10)  # the real limit
    runtime.redis.delete(f"provider-rate:google_ads:{owner.conn}")  # a full bucket
    _link(owner)  # 2 structure calls + 2 months x 4 levels = 10
    (state,) = _rows(
        admin_engine,
        "SELECT ad_account_id, import_job_id, import_cursor, last_error_code FROM ad_sync_state",
    )
    assert state["import_cursor"] == "perf:2025-11-01:2026-10-14"
    (job,) = _rows(
        admin_engine,
        "SELECT status, last_error_code FROM job_runs WHERE id = :id",
        id=state["import_job_id"],
    )
    assert job == {"status": "queued", "last_error_code": "rate_limited"}
    assert state["last_error_code"] is None  # a pause, not a failure
    for _ in range(30):
        (state,) = _rows(admin_engine, "SELECT ad_account_id, import_job_id FROM ad_sync_state")
        if state["import_job_id"] is None:
            break
        clock.advance(timedelta(seconds=1))
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
    assert state["import_job_id"] is None
    assert len(_perf(admin_engine, "account")) == DAYS


def test_a_permanent_error_while_reading_figures_ends_the_chain(owner, sim, admin_engine):
    _failing_perf_call(sim, 1, 400, {"queryError": "UNRECOGNIZED_FIELD"})
    _link(owner)
    (account,) = _rows(admin_engine, "SELECT status FROM ad_accounts")
    (state,) = _rows(
        admin_engine, "SELECT last_error_code, import_cursor, import_job_id FROM ad_sync_state"
    )
    assert account["status"] == "error"
    assert state == {"last_error_code": "bad_query", "import_cursor": None, "import_job_id": None}
    assert len(_rows(admin_engine, "SELECT id FROM ad_campaigns")) == 3  # structure kept
    assert _perf(admin_engine, "account") == []


def test_losing_access_while_reading_figures_marks_only_the_account(owner, sim, admin_engine):
    _failing_perf_call(sim, 5, 403, {"authorizationError": "USER_PERMISSION_DENIED"})
    _link(owner)
    (account,) = _rows(admin_engine, "SELECT status, health_code FROM ad_accounts")
    assert account == {"status": "error", "health_code": "no_account_access"}
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"


# ------------------------------------------------------------------ slicing rules
@pytest.mark.parametrize(
    ("first", "last", "end"),
    [
        (date(2025, 9, 14), date(2026, 10, 14), date(2025, 9, 30)),
        (date(2026, 2, 1), date(2026, 10, 14), date(2026, 2, 28)),
        (date(2028, 2, 3), date(2028, 12, 1), date(2028, 2, 29)),  # leap year
        (date(2025, 12, 5), date(2026, 3, 1), date(2025, 12, 31)),  # across the year end
        (date(2026, 10, 1), date(2026, 10, 14), date(2026, 10, 14)),  # stops at the last day
        (date(2026, 10, 14), date(2026, 10, 14), date(2026, 10, 14)),
    ],
)
def test_month_slices(first, last, end):
    assert month_slice(first, last) == end


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        ("perf:2025-09-14:2026-10-14", (date(2025, 9, 14), date(2026, 10, 14))),
        ("perf:2026-10-14:2026-10-14", (date(2026, 10, 14), date(2026, 10, 14))),
        ("perf:2026-10-15:2026-10-14", None),  # nothing left
        ("perf:2026-13-01:2026-10-14", None),
        ("perf:2026-10-01", None),
        ("structure", None),
        ("done", None),
    ],
)
def test_performance_cursors(cursor, expected):
    assert performance_cursor(cursor) == expected
