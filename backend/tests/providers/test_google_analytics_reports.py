"""GA4 daily reports through the provider (task 5-05, PLAN §4.1, §9, Q-5-4, Q-5-8).

One ``batchRunReports`` call holds the three views of a date range; a view with more rows than a
page is read on with ``runReport`` and ``offset``. Values arrive as strings and are read exactly;
anything unreadable is left unknown (None), never 0. Google's data-quality signals travel with
every row.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from app.providers.base.types import AnalyticsBreakdown, AnalyticsPropertyRef
from app.providers.google.oauth import UnexpectedResponseError
from app.providers.google_analytics import mapping
from app.providers.google_analytics import provider as ga_provider

from tests.ga4_sim import ANALYTICS_SCOPE, GA4Sim, Visit, build_provider

SUB = "108000000000000000001"
FIRST, LAST = date(2026, 10, 1), date(2026, 10, 31)
PROP = AnalyticsPropertyRef("111")


@pytest.fixture
def sim(clock):
    s = GA4Sim(clock=clock)
    prop = s.add_property("111", "900", SUB, display_name="Eve Zone AU")
    prop.traffic = [
        Visit(date(2026, 10, 1)),
        Visit(
            date(2026, 10, 1),
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
        Visit(date(2026, 10, 3), purchases=0, revenue=Decimal("-30.00")),  # a refund day
    ]
    prop.day_users[date(2026, 10, 1)] = 11  # Google's distinct users for the whole day
    return s


@pytest.fixture
def provider(sim):
    return build_provider(sim)


@pytest.fixture
def secrets(sim):
    """A signed-in Google account with ``analytics.readonly``."""
    sim.refresh_tokens["1//sim-refresh-test"] = SUB
    sim.refresh_scopes["1//sim-refresh-test"] = f"{ANALYTICS_SCOPE} openid"
    return {"access_token": sim._new_access(SUB)}


def _read(provider, secrets, first=FIRST, last=LAST):
    return list(provider.read_daily(secrets, PROP, first, last))


def _by(records, view):
    return [r for r in records if r.breakdown is view]


def test_one_call_holds_the_four_views(provider, sim, secrets):
    _read(provider, secrets)
    (call,) = sim.calls(":batchRunReports")
    assert sim.calls(":runReport") == []
    sent = json.loads(call.content)["requests"]
    assert [[d["name"] for d in r["dimensions"]] for r in sent] == [
        ["date"],
        ["date", "sessionDefaultChannelGroup"],
        ["date", "sessionSource", "sessionMedium", "sessionCampaignName"],
        ["date", "landingPage"],
    ]
    for request in sent:
        assert request["dateRanges"] == [{"startDate": "2026-10-01", "endDate": "2026-10-31"}]
        assert [m["name"] for m in request["metrics"]] == list(mapping.METRICS)
        assert [o["dimension"]["dimensionName"] for o in request["orderBys"]] == [
            d["name"] for d in request["dimensions"]
        ]
        assert request["returnPropertyQuota"] is True and "offset" not in request
    assert "/v1beta/properties/111:batchRunReports" in str(call.url)


def test_values_are_read_exactly_and_users_come_from_google(provider, secrets):
    records = _read(provider, secrets)
    (total,) = [r for r in _by(records, AnalyticsBreakdown.TOTAL) if r.day == FIRST]
    assert (total.sessions, total.engaged_sessions, total.new_users) == (15, 10, 5)
    assert total.total_users == 11  # Google's distinct count, not 8 + 4
    assert (total.key_events, total.purchases) == (Decimal("3.5"), 3)
    assert total.purchase_revenue == Decimal("170.45")
    channels = {r.channel_group: r for r in _by(records, AnalyticsBreakdown.CHANNEL)}
    assert channels["Paid Search"].total_users == 4
    assert channels["Paid Search"].day == FIRST
    paid = next(r for r in _by(records, AnalyticsBreakdown.SOURCE) if r.medium == "cpc")
    assert (paid.source, paid.campaign, paid.purchase_revenue) == (
        "google",
        "Spring Sale",
        Decimal("120.50"),
    )


def test_refunds_can_make_revenue_negative(provider, secrets):
    (refund,) = [
        r for r in _by(_read(provider, secrets), AnalyticsBreakdown.TOTAL) if r.day.day == 3
    ]
    assert refund.purchase_revenue == Decimal("-30.00")


def _answer(rows, dims=("date",), count=None, metadata=None, metrics=mapping.METRICS):
    return {
        "dimensionHeaders": [{"name": d} for d in dims],
        "metricHeaders": [{"name": m} for m in metrics],
        "rows": [
            {
                "dimensionValues": [{"value": v} for v in dv],
                "metricValues": [{"value": v} for v in mv],
            }
            for dv, mv in rows
        ],
        "rowCount": len(rows) if count is None else count,
        "metadata": metadata or {},
    }


def test_unreadable_values_are_unknown_never_zero():
    values = ["12", "", "-3", "x", "1.25", "9", "1e3", "4", "-1", ""]
    parsed = mapping.parse_report(
        AnalyticsBreakdown.TOTAL, _answer([(["20261001"], values)]), FIRST, LAST
    )
    assert parsed is not None
    (r,) = parsed.records
    assert r.sessions == 12
    assert (r.engaged_sessions, r.total_users, r.new_users) == (None, None, None)
    assert (r.key_events, r.purchases, r.purchase_revenue) == (Decimal("1.25"), 9, None)
    assert (r.item_view_events, r.add_to_carts, r.checkouts) == (4, None, None)


def test_rows_that_cannot_be_read_are_skipped_and_counted():
    rows = [
        (["20261001"], ["1"] * 10),
        (["2026-10-02"], ["1"] * 10),  # not Google's date format
        (["20261302"], ["1"] * 10),  # no such day
        (["20260930"], ["1"] * 10),  # outside the range asked for
        (["20261004"], ["1"] * 9),  # a value missing
    ]
    parsed = mapping.parse_report(AnalyticsBreakdown.TOTAL, _answer(rows), FIRST, LAST)
    assert parsed is not None
    assert ([r.day for r in parsed.records], parsed.skipped, parsed.rows_seen) == (
        [FIRST],
        4,
        5,
    )


@pytest.mark.parametrize(
    "report",
    [
        _answer([(["20261001"], ["1"] * 10)], dims=("date", "country")),
        _answer([(["20261001"], ["1"] * 9)], metrics=mapping.METRICS[:-1]),
        {"rows": "nope", "rowCount": 1},
        {"rows": [], "rowCount": "1"},
    ],
)
def test_a_report_that_is_not_what_was_asked_for_is_refused(report):
    assert mapping.parse_report(AnalyticsBreakdown.TOTAL, report, FIRST, LAST) is None


def test_an_unexpected_report_stops_the_read(provider, sim, secrets):
    sim.report_handler = lambda s, pid, req: _answer(
        [(["20261001", "x"], ["1"] * 10)], ("date", "x")
    )
    with pytest.raises(UnexpectedResponseError):
        _read(provider, secrets)


def test_googles_data_quality_signals_travel_with_every_row(provider, sim, secrets):
    prop = sim.properties["111"]
    prop.metadata = {
        "total": {"subjectToThresholding": True, "samplingMetadatas": [{"samplesReadCount": "1"}]},
        "source": {"dataLossFromOtherRow": True, "dataTruncationReasons": ["ROW_LIMIT"]},
    }
    prop.traffic.append(Visit(date(2026, 10, 2), channel="(other)", source="(other)"))
    records = _read(provider, secrets)
    totals = _by(records, AnalyticsBreakdown.TOTAL)
    assert all(r.quality.thresholded and r.quality.sampled for r in totals)
    assert not any(r.quality.other_row or r.quality.truncated for r in totals)
    sources = _by(records, AnalyticsBreakdown.SOURCE)
    assert all(r.quality.other_row and r.quality.truncated for r in sources)
    channels = _by(records, AnalyticsBreakdown.CHANNEL)
    other = [r for r in channels if r.channel_group == "(other)"]
    assert [r.quality.other_row for r in channels] == [r in other for r in channels]


def test_large_views_are_read_page_by_page(provider, sim, secrets, monkeypatch):
    monkeypatch.setattr(mapping, "PAGE_ROWS", 2)
    prop = sim.properties["111"]
    prop.traffic += [Visit(date(2026, 10, 5), source=f"site{n}.example") for n in range(5)]
    records = _read(provider, secrets)
    assert len(_by(records, AnalyticsBreakdown.SOURCE)) == 8
    offsets = [json.loads(c.content).get("offset") for c in sim.calls(":runReport")]
    # total (3 rows), channel (4) and landing page (3): one more page each; source (8): three
    assert offsets == ["2", "2", "2", "4", "6", "2"]
    assert not any(r.quality.truncated for r in records)


def test_a_view_beyond_the_page_limit_is_marked_truncated(provider, sim, secrets, monkeypatch):
    monkeypatch.setattr(mapping, "PAGE_ROWS", 2)
    monkeypatch.setattr(ga_provider, "MAX_REPORT_PAGES", 2)
    sim.properties["111"].traffic += [
        Visit(date(2026, 10, 5), source=f"site{n}.example") for n in range(5)
    ]
    sources = _by(_read(provider, secrets), AnalyticsBreakdown.SOURCE)
    assert len(sources) == 4 and all(r.quality.truncated for r in sources)


def test_an_empty_period_reads_nothing(provider, sim, secrets):
    sim.properties["111"].traffic.clear()
    assert _read(provider, secrets) == []


def test_reversed_days_are_refused(provider, secrets):
    with pytest.raises(ValueError, match="first_day"):
        _read(provider, secrets, LAST, FIRST)


def test_what_is_left_of_the_propertys_allowance_is_kept_per_property(provider, sim, secrets):
    assert provider.quota_left(PROP) is None  # nothing read yet
    sim.hour_used["111"], sim.day_used["111"] = 6_970, 49_970
    _read(provider, secrets)  # Google's block on the batch: after its first 10-token report
    left = provider.quota_left(PROP)
    assert left.hour == pytest.approx(7_020 / 14_000)  # AdVegaX's share of the hour is smaller
    assert left.day == pytest.approx(150_020 / 200_000)
    assert provider.quota_left(AnalyticsPropertyRef("211")) is None


def test_larger_allowances_count_as_fully_available():
    from app.providers.google_analytics.client import Quota

    class Client:
        def quota_for(self, _pid):
            return Quota(day_remaining=2_000_000, hour_remaining=None, project_hour_remaining=None)

    provider = ga_provider.GoogleAnalyticsProvider.__new__(ga_provider.GoogleAnalyticsProvider)
    provider.analytics = Client()
    left = provider.quota_left(PROP)
    assert (left.hour, left.day) == (None, 1.0)
