"""Google Ads rows → advertising records: money, ids, dates, statuses (task 3-05)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
from app.providers.base.types import AdAccountRef, AdEntityStatus
from app.providers.google_ads import mapping
from app.providers.google_ads.client import UnexpectedResponseError

from tests.google_ads_sim import GoogleAdsSim, build_provider, sample_hierarchy


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
