"""Importing a linked Meta ad account's daily figures (task 4-05, PLAN §9, Q-4-5 … Q-4-7).

After the structure, the first import reads 13 months of daily figures at four levels
(account, campaign, ad set, ad), one calendar month per step, using each ad set's own
attribution setting. Purchases and purchase value are Meta's combined ``omni_purchase``.
Archived and deleted objects are asked for explicitly, so their days stay readable; account
totals come from Meta's account rows (which include deleted ads). When Meta says a request
is too large, that slice is read through an asynchronous report.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from itertools import pairwise
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.advertising import importer
from app.domains.advertising.importer import start_import
from app.domains.advertising.models import AdAccount
from app.domains.jobs.service import ClaimedJob
from app.providers.base.errors import RetryableError
from sqlalchemy import text

from tests.meta_sim import MetaSim, build_provider, insight, sample_insights, sample_structure

USER = "10160000000000001"
AU = "act_1001"
SALE_DAY, OLD_DAY = "2026-10-01", "2026-04-10"
TODAY = date(2026, 10, 14)  # the test clock (00:00 UTC) is 11:00 in Sydney
HISTORY_FROM = date(2025, 9, 14)
DAYS = (TODAY - HISTORY_FROM).days + 1


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def sim(runtime, clock, sleeps):
    s = MetaSim(clock=clock)
    s.add_user(USER)
    account = s.add_account(
        AU, USER, name="Eve Zone AU", currency="AUD", timezone_name="Australia/Sydney"
    )
    sample_insights(sample_structure(account), SALE_DAY, OLD_DAY)
    runtime.providers.register(build_provider(s, sleeps=sleeps))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup(f"meta-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    started = c.post(f"/organizations/{c.org}/connections/meta_ads/start", {"params": {}}).json()[
        "data"
    ]["authorize_url"]
    response = c.http.get(
        "/api/v1/connections/meta_ads/callback",
        params=sim.approve(started, USER),
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


def _insight_calls(sim, method="GET"):
    return [
        r for r in sim.requests if r.url.path.endswith(f"/{AU}/insights") and r.method == method
    ]


# ------------------------------------------------------------------ the first import
def test_linking_imports_13_months_of_daily_figures(owner, sim, admin_engine):
    _link(owner)
    account = _perf(admin_engine, "account")
    assert len(account) == DAYS  # every day, none missing and none twice
    assert (account[0]["day"], account[-1]["day"]) == (HISTORY_FROM, TODAY)
    by_day = {r["day"]: r for r in account}
    sale = by_day[date(2026, 10, 1)]
    assert (sale["impressions"], sale["clicks"]) == (2100, 36)
    assert sale["cost"] == Decimal("48.750000")  # Meta's account row, deleted ad included
    assert (sale["conversions"], sale["conversion_value"]) == (
        Decimal("2.000000"),
        Decimal("159.900000"),
    )
    assert (sale["currency"], sale["source"]) == ("AUD", "platform_reported")
    quiet = by_day[date(2026, 1, 1)]  # Meta sent nothing: a real zero, never missing
    assert (quiet["impressions"], quiet["clicks"], quiet["cost"], quiet["conversions"]) == (
        0,
        0,
        Decimal(0),
        Decimal(0),
    )

    campaigns = [r for r in _perf(admin_engine, "campaign") if r["day"] == date(2026, 10, 1)]
    assert [(r["entity_key"], r["campaign"], r["cost"]) for r in campaigns] == [
        ("120001", "120001", Decimal("40.000000")),
        ("120002", "120002", Decimal("7.500000")),
        ("120004", "120004", Decimal("1.250000")),  # deleted, still readable
    ]
    sets = [r for r in _perf(admin_engine, "ad_group") if r["day"] == date(2026, 10, 1)]
    assert [(r["entity_key"], r["campaign"], r["ad_group"]) for r in sets] == [
        ("230001", "120001", "230001"),
        ("230002", "120002", "230002"),
        ("230003", "120004", "230003"),
    ]
    ads = [r for r in _perf(admin_engine, "ad") if r["day"] == date(2026, 10, 1)]
    assert [(r["entity_key"], r["ad_group"], r["ad"]) for r in ads] == [
        ("230001~340001", "230001", "340001"),
        ("230002~340003", "230002", "340003"),
        ("230003~340004", "230003", "340004"),
    ]
    seller, quiet_ad = ads[0], ads[1]
    assert (seller["conversions"], seller["conversion_value"]) == (
        Decimal("2.000000"),
        Decimal("159.900000"),
    )
    assert (quiet_ad["conversions"], quiet_ad["conversion_value"]) == (Decimal(0), Decimal(0))

    (state,) = _rows(
        admin_engine,
        "SELECT import_progress, import_cursor, import_job_id, last_error_code FROM ad_sync_state",
    )
    assert state == {
        "import_progress": 100,
        "import_cursor": None,
        "import_job_id": None,
        "last_error_code": None,
    }
    (row,) = _rows(admin_engine, "SELECT status, first_import_completed_at FROM ad_accounts")
    assert row["status"] == "active" and row["first_import_completed_at"] is not None


def test_the_figures_are_read_in_calendar_months_four_levels_each(owner, sim):
    _link(owner)
    calls = _insight_calls(sim)
    assert len(calls) == 14 * 4
    queries = [{k: v[0] for k, v in parse_qs(c.url.query.decode()).items()} for c in calls]
    assert [q["level"] for q in queries[:4]] == ["account", "campaign", "adset", "ad"]
    ranges = [tuple(json.loads(q["time_range"]).values()) for q in queries[::4]]
    ranges = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in ranges]
    assert ranges[0] == (HISTORY_FROM, date(2025, 9, 30))
    assert ranges[5] == (date(2026, 2, 1), date(2026, 2, 28))
    assert ranges[-1] == (date(2026, 10, 1), TODAY)
    for (_, end), (start, _) in pairwise(ranges):
        assert start.toordinal() == end.toordinal() + 1  # no gap, no overlap
    for q in queries:
        assert (q["time_increment"], q["use_unified_attribution_setting"]) == ("1", "true")
        assert "access_token" not in q and "omni_purchase" not in q["fields"]
        assert {"spend", "impressions", "inline_link_clicks", "actions"} <= set(
            q["fields"].split(",")
        )
    assert "filtering" not in queries[0]  # the account row already includes everything
    for q in queries[1:4]:
        (rule,) = json.loads(q["filtering"])
        assert rule["field"] == f"{q['level']}.effective_status"
        assert {"ARCHIVED", "DELETED"} <= set(rule["value"])
    assert _insight_calls(sim, "POST") == []  # no report jobs unless needed


def test_days_are_the_accounts_own_days(make_client, sim, admin_engine):
    """At 00:00 UTC on 14 October it is still 13 October in Los Angeles."""
    sim.accounts[AU].timezone_name = "America/Los_Angeles"
    owner = make_client()
    owner.signup(f"meta-{uuid.uuid4().hex[:6]}@example.com")
    owner.org = owner.create_org("LA")["id"]
    started = owner.post(
        f"/organizations/{owner.org}/connections/meta_ads/start", {"params": {}}
    ).json()["data"]["authorize_url"]
    response = owner.http.get(
        "/api/v1/connections/meta_ads/callback",
        params=sim.approve(started, USER),
        follow_redirects=False,
    )
    owner.conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    resources = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}/resources")
    owner.resources = {r["external_id"]: r for r in resources.json()["data"]}
    _link(owner)
    assert _perf(admin_engine, "account")[-1]["day"] == date(2026, 10, 13)


def test_a_new_import_replaces_the_figures_of_the_days_it_reads(owner, sim, runtime, admin_engine):
    _link(owner)
    rows = sim.accounts[AU].insights["account"]
    corrected = next(r for r in rows if r["date_start"] == SALE_DAY)
    corrected["spend"] = "49.10"  # Meta corrects figures for up to 28 days
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        start_import(session, runtime, session.query(AdAccount).one(), requested_by=None)
    by_day = {r["day"]: r for r in _perf(admin_engine, "account")}
    assert by_day[date(2026, 10, 1)]["cost"] == Decimal("49.100000")
    assert len(by_day) == DAYS


def test_a_duplicated_row_from_meta_is_stored_once(owner, sim, admin_engine):
    rows = sim.accounts[AU].insights["campaign"]
    rows.append(dict(next(r for r in rows if r["date_start"] == SALE_DAY)))
    _link(owner)
    oct_1 = [r for r in _perf(admin_engine, "campaign") if r["day"] == date(2026, 10, 1)]
    assert [r["entity_key"] for r in oct_1].count("120001") == 1
    assert oct_1[0]["cost"] == Decimal("40.000000")  # never summed


def test_unreadable_rows_are_skipped_never_guessed(owner, sim, admin_engine):
    rows = sim.accounts[AU].insights["ad"]
    rows.append(
        insight("2026-10-02", ad_id="340001", adset_id="230001", campaign_id="120001", spend="x")
    )
    rows.append(insight("2026-10-03", ad_id="340001", campaign_id="120001"))  # no ad set
    _link(owner)
    days = {r["day"] for r in _perf(admin_engine, "ad")}
    assert date(2026, 10, 2) not in days and date(2026, 10, 3) not in days


# ------------------------------------------------------------------ too much data
def test_a_slice_meta_finds_too_large_is_read_as_a_report(owner, sim, admin_engine, sleeps):
    sim.too_large = {"ad"}
    _link(owner)
    starts = _insight_calls(sim, "POST")
    assert len(starts) == 14  # one report per monthly slice, ad level only
    form = {k: v[0] for k, v in parse_qs(starts[0].content.decode()).items()}
    assert (form["level"], form["time_increment"], form["use_unified_attribution_setting"]) == (
        "ad",
        "1",
        "true",
    )
    assert "access_token" not in form and "limit" not in form
    assert not starts[0].url.query.decode().count("access_token")
    assert sleeps == [5.0] * (14 * 3)  # checked every 5 seconds until done
    ads = [r for r in _perf(admin_engine, "ad") if r["day"] == date(2026, 10, 1)]
    assert [r["ad"] for r in ads] == ["340001", "340003", "340004"]
    (state,) = _rows(admin_engine, "SELECT import_progress, last_error_code FROM ad_sync_state")
    assert state == {"import_progress": 100, "last_error_code": None}


def test_a_report_meta_cannot_finish_is_retried_then_ends_the_chain(
    owner, sim, runtime, admin_engine
):
    sim.too_large = {"campaign"}
    sim.report_outcome = "Job Failed"
    _link(owner)
    (state,) = _rows(
        admin_engine,
        "SELECT ad_account_id, import_job_id, import_cursor, last_error_code FROM ad_sync_state",
    )
    assert state["import_job_id"] is not None  # a temporary problem: retried later
    assert state["import_cursor"] == f"perf:{HISTORY_FROM}:{TODAY}"
    assert state["last_error_code"] is None
    with pytest.raises(RetryableError):  # the last attempt gives up with a plain code
        importer.import_step(
            runtime,
            ClaimedJob(
                state["import_job_id"],
                uuid.UUID(owner.org),
                importer.JOB_AD_IMPORT_STEP,
                str(state["ad_account_id"]),
                5,
                5,
                None,
                None,
            ),
        )
    (state,) = _rows(admin_engine, "SELECT last_error_code, import_job_id FROM ad_sync_state")
    assert state == {"last_error_code": "report_failed", "import_job_id": None}
    (account,) = _rows(admin_engine, "SELECT status FROM ad_accounts")
    assert account["status"] == "error"
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"  # Meta's problem with one report, not the sign-in


def test_the_api_serves_meta_figures(owner, sim):
    _link(owner)
    (account,) = owner.get(f"/organizations/{owner.org}/ad-accounts").json()["data"]
    assert (account["provider"], account["source"], account["status"]) == (
        "meta_ads",
        "platform_reported",
        "active",
    )
    response = owner.get(
        f"/organizations/{owner.org}/ad-accounts/{account['id']}/metrics/daily",
        params={"from": "2026-10-01", "to": "2026-10-01"},
    )
    assert response.status_code == 200, response.text
    assert SALE_DAY in response.text
