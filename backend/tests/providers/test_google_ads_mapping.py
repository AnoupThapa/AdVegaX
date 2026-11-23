"""Google Ads rows → advertising records: money, ids, dates, statuses (3-05), daily figures
(3-06)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
from app.providers.base.errors import InvalidRequestError
from app.providers.base.types import AdAccountRef, AdEntityStatus, AdLevel
from app.providers.google_ads import mapping
from app.providers.google_ads.client import UnexpectedResponseError

from tests.google_ads_sim import GoogleAdsSim, build_provider, perf_row, sample_hierarchy


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("50000000", Decimal("50")),
        (1234560000, Decimal("1234.56")),
        ("1", Decimal("0.000001")),
        ("0", Decimal("0")),
        (None, None),
        ("", None),
        ("abc", None),
        ("1.5", None),  # micros are whole numbers
        ("NaN", None),
    ],
)
def test_micros_become_exact_decimals(value, expected):
    assert mapping.money(value) == expected


def test_ids_and_resource_names():
    assert mapping.ident("123") == "123"
    assert mapping.ident("12a") is None and mapping.ident(None) is None
    assert mapping.resource_id("customers/1/campaigns/22") == "22"
    assert mapping.resource_id("22") is None and mapping.resource_id(22) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-01", date(2026, 10, 1)),
        ("2026-10-01 00:00:00", date(2026, 10, 1)),
        ("2026-13-01 00:00:00", None),
        ("2026", None),
        (None, None),
    ],
)
def test_dates(value, expected):
    assert mapping.day(value) == expected


def test_statuses():
    assert mapping.status("ENABLED") is AdEntityStatus.ACTIVE
    assert mapping.status("UNKNOWN") is None and mapping.status(None) is None


def test_budgets():
    assert mapping.budget({"campaignBudget": {"id": "1", "period": "WEEKLY"}}) is None
    assert mapping.budget({"campaignBudget": {"id": "x", "period": "DAILY"}}) is None
    assert mapping.budget({"other": {}}) is None
    fixed = mapping.budget({"campaignBudget": {"id": "1", "period": "FIXED_DAILY"}})
    assert fixed is not None and (fixed.period, fixed.amount) == ("daily", None)  # never 0


def test_campaign_rows():
    assert mapping.campaign({}) is None
    assert mapping.campaign({"campaign": {"id": "1", "name": "", "status": "ENABLED"}}) is None
    record = mapping.campaign(
        {
            "campaign": {
                "id": "1",
                "name": "x",
                "status": "ENABLED",
                "startDateTime": "2026-05-01 00:00:00",
                "endDateTime": "2026-04-01 23:59:59",  # before the start: ignored
            }
        }
    )
    assert record is not None and (record.start_date, record.end_date) == (date(2026, 5, 1), None)


def test_ad_group_and_ad_rows_need_their_parent():
    assert mapping.ad_group({}) is None
    assert mapping.ad_group({"adGroup": {"id": "1", "name": "g", "status": "ENABLED"}}) is None
    assert mapping.ad({}) is None
    assert mapping.ad({"adGroupAd": {"status": "ENABLED", "ad": "not-a-dict"}}) is None
    assert (
        mapping.ad({"adGroupAd": {"status": "ENABLED", "adGroup": "customers/1/adGroups/2"}})
        is None
    )


# ------------------------------------------------------------------ provider reads
@pytest.fixture
def provider_and_token(clock):
    sim = sample_hierarchy(GoogleAdsSim(clock=clock))
    return sim, build_provider(sim), sim._new_access("108000000000000000001")


def test_read_account_refuses_answers_without_currency_or_zone(provider_and_token):
    sim, provider, token = provider_and_token
    sim.customers["1000000003"].timezone = "Nowhere/Never"
    with pytest.raises(UnexpectedResponseError):
        provider.read_account({"access_token": token}, AdAccountRef("1000000003"))


def test_read_account_refuses_an_empty_answer(provider_and_token):
    sim, provider, token = provider_and_token
    real = sim.handler
    sim.handler = lambda r: (
        httpx.Response(200, json=[{"results": [{"other": 1}]}])
        if "searchStream" in r.url.path
        else real(r)
    )
    with pytest.raises(UnexpectedResponseError):
        provider.read_account({"access_token": token}, AdAccountRef("1000000003"))


def test_unknown_account_statuses_count_as_closed(provider_and_token):
    sim, provider, token = provider_and_token
    real = sim.account_row
    sim.account_row = lambda c: {"customer": {**real(c)["customer"], "status": "UNSPECIFIED"}}
    state = provider.read_account({"access_token": token}, AdAccountRef("1000000003"))
    assert state.platform_status == "closed"


# ------------------------------------------------------------------ daily figures (3-06)
def test_a_daily_row_keeps_exact_money_and_fractional_conversions():
    row = perf_row(
        "2026-10-01",
        campaign="11",
        ad_group="2101",
        ad="90001",
        impressions=1200,
        clicks=34,
        cost_micros=12_345_678,
        conversions="1.333333",
        conversions_value=89.9,
    )
    record = mapping.performance(row, AdLevel.AD)
    assert record is not None
    assert (record.day, record.entity_external_id) == (date(2026, 10, 1), "90001")
    assert (record.campaign_external_id, record.ad_group_external_id) == ("11", "2101")
    assert (record.impressions, record.clicks) == (1200, 34)
    assert record.cost == Decimal("12.345678")
    assert (record.conversions, record.conversion_value) == (Decimal("1.333333"), Decimal("89.9"))


def test_metrics_google_leaves_out_are_zero():
    """proto3 JSON omits zero values, so a selected metric missing from a returned row is 0."""
    record = mapping.performance(perf_row("2026-10-01", impressions=5), AdLevel.ACCOUNT)
    assert record is not None and record.entity_external_id is None
    assert (record.impressions, record.clicks, record.cost) == (5, 0, Decimal(0))
    assert (record.conversions, record.conversion_value) == (Decimal(0), Decimal(0))


def test_levels_name_their_own_entity():
    row = perf_row("2026-10-01", campaign="11", ad_group="2101")
    group = mapping.performance(row, AdLevel.AD_GROUP)
    campaign = mapping.performance(perf_row("2026-10-01", campaign="11"), AdLevel.CAMPAIGN)
    assert group is not None and campaign is not None
    assert (group.entity_external_id, group.campaign_external_id) == ("2101", "11")
    assert group.ad_group_external_id is None
    assert (campaign.entity_external_id, campaign.campaign_external_id) == ("11", None)


@pytest.mark.parametrize(
    ("row", "level"),
    [
        ({"metrics": {}}, AdLevel.ACCOUNT),  # no date
        ({"segments": {"date": "2026-13-01"}, "metrics": {}}, AdLevel.ACCOUNT),
        ({"segments": {"date": "2026-10-01"}}, AdLevel.ACCOUNT),  # no metrics
        (perf_row("2026-10-01"), AdLevel.CAMPAIGN),  # no campaign id
        (perf_row("2026-10-01", campaign="11"), AdLevel.AD),  # no ad id
        ({**perf_row("2026-10-01"), "metrics": {"impressions": "-1"}}, AdLevel.ACCOUNT),
        ({**perf_row("2026-10-01"), "metrics": {"clicks": "many"}}, AdLevel.ACCOUNT),
        ({**perf_row("2026-10-01"), "metrics": {"costMicros": "1.5"}}, AdLevel.ACCOUNT),
        ({**perf_row("2026-10-01"), "metrics": {"costMicros": "-100"}}, AdLevel.ACCOUNT),
        ({**perf_row("2026-10-01"), "metrics": {"conversions": "NaN"}}, AdLevel.ACCOUNT),
        ({**perf_row("2026-10-01"), "metrics": {"conversions": "x"}}, AdLevel.ACCOUNT),
        ({**perf_row("2026-10-01"), "metrics": {"conversionsValue": "1e20"}}, AdLevel.ACCOUNT),
        ({**perf_row("2026-10-01"), "metrics": {"conversionsValue": -2}}, AdLevel.ACCOUNT),
    ],
)
def test_unreadable_daily_rows_are_skipped_never_guessed(row, level):
    assert mapping.performance(row, level) is None


def test_read_performance_sends_one_query_per_level_and_drops_days_outside_it(
    provider_and_token,
):
    sim, provider, token = provider_and_token
    customer = sim.customers["1000000003"]
    customer.performance = {
        "account": [
            perf_row("2026-10-01", impressions=1),
            perf_row("2026-10-02", impressions=2),
            {"segments": {"date": "bad"}, "metrics": {}},
        ]
    }
    real = sim.performance_rows
    sim.performance_rows = lambda c, level, q: [  # a day Google should not have sent
        *real(c, level, q),
        perf_row("2026-11-05", impressions=9),
    ]
    found = list(
        provider.read_performance(
            {"access_token": token},
            AdAccountRef("1000000003"),
            AdLevel.ACCOUNT,
            date(2026, 10, 1),
            date(2026, 10, 1),
        )
    )
    assert [(r.day, r.impressions) for r in found] == [(date(2026, 10, 1), 1)]
    (request,) = sim.calls("googleAds:searchStream")
    assert b"FROM customer WHERE segments.date BETWEEN '2026-10-01' AND '2026-10-01'" in (
        request.content
    )
    with pytest.raises(InvalidRequestError):
        list(
            provider.read_performance(
                {"access_token": token},
                AdAccountRef("1000000003"),
                AdLevel.ACCOUNT,
                date(2026, 10, 2),
                date(2026, 10, 1),
            )
        )
