"""Ad accounts, campaigns and figures over the API (task 3-08, PLAN §10-§11).

Same rules as the store API: every member reads, managers and above "Sync now", other
organizations' data is a 404, money is an exact decimal string, every figure is labelled as
reported by Google Ads, rates are derived on read and say why when they cannot be, and days
not read are "not synchronized" — never 0.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_EVEN, Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import text

from tests.google_ads_sim import (
    CLIENT_SECRET,
    DEVELOPER_TOKEN,
    GoogleAdsSim,
    build_provider,
    sample_hierarchy,
    sample_performance,
    sample_structure,
)

SUB = "108000000000000000001"
AU = "1000000001"
SEARCH_DAY, PMAX_DAY = "2026-10-01", "2026-04-10"
SIX = Decimal("0.000001")


@pytest.fixture
def sim(runtime, clock):
    s = sample_hierarchy(GoogleAdsSim(clock=clock))
    sample_performance(sample_structure(s.customers[AU]), SEARCH_DAY, PMAX_DAY)
    runtime.providers.register(build_provider(s))
    return s


def _connect(make_client, sim, name="Eve Zone", email=None):
    c = make_client()
    c.email = email or f"ads-{uuid.uuid4().hex[:6]}@example.com"
    c.signup(c.email)
    c.org = c.create_org(name)["id"]
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
    assert c.post(f"/organizations/{c.org}/resources/{c.resource['id']}/link").status_code == 201
    accounts = c.get(f"/organizations/{c.org}/ad-accounts").json()["data"]
    c.account = accounts[0]["id"] if accounts else None
    return c


@pytest.fixture
def owner(make_client, sim):
    return _connect(make_client, sim)


@pytest.fixture
def viewer(make_client, owner):
    c = make_client()
    c.signup("ads-viewer@example.com")
    owner.invite_and_join(owner.org, c, "ads-viewer@example.com", "viewer")
    c.org, c.account = owner.org, owner.account
    return c


def _base(c):
    return f"/organizations/{c.org}/ad-accounts/{c.account}"


def _data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _rate(numerator, denominator):
    return str((Decimal(numerator) / Decimal(denominator)).quantize(SIX, ROUND_HALF_EVEN))


# ------------------------------------------------------------------ accounts
def test_ad_accounts_are_listed_with_sync_status_and_health(owner):
    (account,) = _data(owner.get(f"/organizations/{owner.org}/ad-accounts"))
    assert account["id"] == owner.account
    assert (account["provider"], account["source"], account["external_account_id"]) == (
        "google_ads",
        "platform_reported",
        AU,
    )
    assert (account["name"], account["currency"], account["currency_minor_units"]) == (
        "Eve Zone AU",
        "AUD",
        2,
    )
    assert (account["timezone"], account["status"], account["platform_status"]) == (
        "Australia/Sydney",
        "active",
        "active",
    )
    assert (account["linked"], account["connection_status"]) == (True, "active")
    assert account["group_path"]  # the managers above it, for display
    assert account["history_from"] == "2025-09-14"
    sync = account["sync"]
    assert (sync["running"], sync["mode"], sync["progress"], sync["waiting_for_allowance"]) == (
        False,
        None,
        None,
        False,
    )
    assert sync["last_quick_at"] and sync["last_nightly_at"] and sync["last_weekly_at"]
    assert account["health"]["code"] is None and account["health"]["checked_at"]
    assert _data(owner.get(_base(owner))) == account


def test_an_ad_account_of_another_organization_is_not_found(owner, make_client, sim):
    other = make_client()
    other.signup("ads-other@example.com")
    other.org = other.create_org("Other Co")["id"]
    assert _data(other.get(f"/organizations/{other.org}/ad-accounts")) == []
    for path in (
        f"/organizations/{other.org}/ad-accounts/{owner.account}",
        f"/organizations/{other.org}/ad-accounts/{owner.account}/metrics/daily",
        f"/organizations/{other.org}/ad-accounts/{owner.account}/campaigns",
        f"/organizations/{owner.org}/ad-accounts/{owner.account}",  # not a member there
    ):
        assert other.get(path).status_code == 404, path
    assert owner.get(f"/organizations/{owner.org}/ad-accounts/{uuid.uuid4()}").status_code == 404


def test_a_waiting_run_says_so_without_an_error(owner, admin_engine, clock):
    with admin_engine.begin() as db:
        db.execute(
            text(
                "UPDATE ad_sync_state SET import_job_id = :j, updated_at = :t, "
                "sync_mode = 'nightly', last_error_code = 'quota_waiting', last_error_at = :t"
            ),
            {"j": uuid.uuid4(), "t": clock.now()},
        )
    sync = _data(owner.get(_base(owner)))["sync"]
    assert (sync["running"], sync["mode"], sync["waiting_for_allowance"]) == (
        True,
        "nightly",
        True,
    )
    assert (sync["last_error_code"], sync["last_error_at"]) == (None, None)


# ------------------------------------------------------------------ daily figures
def test_daily_figures_default_to_30_days_with_exact_money_and_derived_rates(owner):
    body = _data(owner.get(f"{_base(owner)}/metrics/daily"))
    assert (body["source"], body["currency"], body["currency_minor_units"]) == (
        "platform_reported",
        "AUD",
        2,
    )
    assert (body["from_day"], body["to_day"], body["timezone"]) == (
        "2026-09-15",
        "2026-10-14",
        "Australia/Sydney",
    )
    assert (body["synced_from"], body["settled_until"]) == ("2025-09-14", "2026-10-11")
    days = {d["day"]: d for d in body["days"]}
    assert len(days) == 30
    search = days[SEARCH_DAY]
    assert search["availability"] == "available" and search["settled"] is True
    assert (search["impressions"], search["clicks"]) == (1200, 34)
    assert (search["cost"], search["conversions"], search["conversion_value"]) == (
        "12.345678",
        "1.500000",
        "89.900000",
    )
    assert search["click_through_rate"] == {
        "value": _rate(34, 1200),
        "availability": "available",
        "reason": None,
    }
    assert search["cost_per_click"]["value"] == _rate("12.345678", 34)
    assert search["cost_per_conversion"]["value"] == _rate("12.345678", "1.5")
    assert search["conversion_value_per_cost"]["value"] == _rate("89.9", "12.345678")
    quiet = days["2026-10-05"]
    assert (quiet["availability"], quiet["impressions"], quiet["cost"]) == (
        "available",
        0,
        "0.000000",
    )  # read, no activity: a real zero
    assert quiet["click_through_rate"] == {
        "value": None,
        "availability": "unavailable",
        "reason": "no_impressions",
    }
    assert quiet["cost_per_click"]["reason"] == "no_clicks"
    assert quiet["cost_per_conversion"]["reason"] == "no_conversions"
    assert quiet["conversion_value_per_cost"]["reason"] == "no_cost"
    assert [d["day"] for d in body["days"] if not d["settled"]] == [
        "2026-10-12",
        "2026-10-13",
        "2026-10-14",
    ]  # Google may still change these
    totals = body["totals"]
    assert totals["availability"] == "available"
    assert (totals["impressions"], totals["clicks"], totals["cost"]) == (1200, 34, "12.345678")
    assert totals["cost_per_click"]["value"] == _rate("12.345678", 34)


def test_days_not_read_are_not_synchronized_never_zero(owner):
    body = _data(owner.get(f"{_base(owner)}/metrics/daily?from=2025-09-10&to=2025-09-20"))
    days = {d["day"]: d for d in body["days"]}
    before = days["2025-09-13"]
    assert (before["availability"], before["reason"], before["impressions"], before["cost"]) == (
        "not_synchronized",
        "not_synchronized",
        None,
        None,
    )
    assert before["click_through_rate"]["availability"] == "not_synchronized"
    assert days["2025-09-14"]["availability"] == "available"
    assert body["totals"]["availability"] == "not_synchronized"  # part of it was never read
    assert body["totals"]["cost"] is None
    future = _data(owner.get(f"{_base(owner)}/metrics/daily?from=2026-10-10&to=2026-10-20"))
    assert {d["day"]: d["availability"] for d in future["days"]}["2026-10-15"] == (
        "not_synchronized"
    )


@pytest.mark.parametrize(
    "query", ["from=2026-10-10&to=2026-10-01", "from=2024-01-01&to=2026-10-14", "from=x"]
)
def test_invalid_periods_are_refused(owner, query):
    assert owner.get(f"{_base(owner)}/metrics/daily?{query}").status_code == 422
    assert owner.get(f"{_base(owner)}/campaigns?{query}").status_code == 422


def test_an_account_whose_first_import_did_not_finish_has_no_figures(make_client, sim):
    real = sim.handler

    def no_access(request):
        if f"/customers/{AU}/" in request.url.path:
            return sim.failure(403, {"authorizationError": "USER_PERMISSION_DENIED"})
        return real(request)

    sim.handler = no_access
    c = _connect(make_client, sim)
    account = _data(c.get(_base(c)))
    assert (account["status"], account["health"]["code"]) == ("error", "no_account_access")
    assert account["sync"]["last_error_code"] == "no_account_access"
    body = _data(c.get(f"{_base(c)}/metrics/daily"))
    assert body["synced_from"] is None
    assert {d["availability"] for d in body["days"]} == {"not_synchronized"}
    (campaigns,) = [_data(c.get(f"{_base(c)}/campaigns"))["items"]]
    assert campaigns == []


# ------------------------------------------------------------------ campaigns
def test_campaigns_have_their_own_period_figures(owner):
    body = _data(owner.get(f"{_base(owner)}/campaigns?from=2026-04-01&to=2026-10-14"))
    assert (body["source"], body["from_day"], body["to_day"]) == (
        "platform_reported",
        "2026-04-01",
        "2026-10-14",
    )
    items = {c["external_id"]: c for c in body["items"]}
    assert [c["name"] for c in body["items"]] == ["Gloves - Search", "Old test", "Spring - PMax"]
    search, removed, pmax = items["11"], items["13"], items["12"]
    assert (search["status"], search["platform_type"], search["start_date"]) == (
        "active",
        "SEARCH",
        "2026-01-15",
    )
    assert search["budget"] == {
        "name": "Gloves daily",
        "period": "daily",
        "amount": "50.000000",
        "currency": "AUD",
        "shared": True,
    }
    assert (search["figures"]["cost"], search["figures"]["clicks"]) == ("12.345678", 34)
    assert (pmax["figures"]["impressions"], pmax["figures"]["cost"]) == (500, "0.000000")
    assert pmax["budget"]["period"] == "lifetime" and pmax["end_date"] == "2026-05-31"
    assert removed["status"] == "removed" and removed["budget"] is None
    assert (removed["figures"]["availability"], removed["figures"]["impressions"]) == (
        "available",
        0,
    )  # kept, so its history stays readable; no activity in the period
    default = {c["external_id"]: c for c in _data(owner.get(f"{_base(owner)}/campaigns"))["items"]}
    assert default["12"]["figures"]["impressions"] == 0  # April is outside the last 30 days


def test_campaign_figures_for_a_period_not_read_are_not_synchronized(owner):
    body = _data(owner.get(f"{_base(owner)}/campaigns?from=2025-01-01&to=2025-12-31"))
    assert {c["figures"]["availability"] for c in body["items"]} == {"not_synchronized"}


def test_one_campaign_with_its_ad_groups_and_ads(owner):
    items = _data(owner.get(f"{_base(owner)}/campaigns"))["items"]
    search_id = next(c["id"] for c in items if c["external_id"] == "11")
    body = _data(owner.get(f"/organizations/{owner.org}/campaigns/{search_id}"))
    assert (body["name"], body["source"], body["currency"]) == (
        "Gloves - Search",
        "platform_reported",
        "AUD",
    )
    assert body["figures"]["cost"] == "12.345678"
    groups = {g["external_id"]: g for g in body["ad_groups"]}
    assert list(groups) == ["2101", "2102"]
    assert groups["2101"]["figures"]["clicks"] == 34
    assert (groups["2102"]["status"], groups["2102"]["figures"]["clicks"]) == ("removed", 0)
    (ad,) = groups["2101"]["ads"]
    assert (ad["external_id"], ad["status"], ad["name"]) == ("90001", "active", None)
    assert (ad["figures"]["cost"], ad["figures"]["conversions"]) == ("12.345678", "1.500000")
    (other_ad,) = groups["2102"]["ads"]
    assert (other_ad["name"], other_ad["figures"]["impressions"]) == ("Vinyl RSA", 0)

    pmax_id = next(c["id"] for c in items if c["external_id"] == "12")
    pmax = _data(
        owner.get(f"/organizations/{owner.org}/campaigns/{pmax_id}?from=2026-04-01&to=2026-04-30")
    )
    assert pmax["ad_groups"] == []  # Performance Max: figures without ad groups
    assert pmax["figures"]["impressions"] == 500


def test_a_campaign_of_another_organization_is_not_found(owner, make_client):
    items = _data(owner.get(f"{_base(owner)}/campaigns"))["items"]
    other = make_client()
    other.signup("ads-other2@example.com")
    other.org = other.create_org("Other Co")["id"]
    path = f"/organizations/{other.org}/campaigns/{items[0]['id']}"
    assert other.get(path).status_code == 404
    assert owner.get(f"/organizations/{owner.org}/campaigns/{uuid.uuid4()}").status_code == 404


# ------------------------------------------------------------------ "Sync now"
def test_sync_now_starts_a_30_day_reread(owner, admin_engine):
    response = owner.post(f"{_base(owner)}/resync")
    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert (body["ad_account_id"], body["mode"]) == (owner.account, "nightly")
    assert uuid.UUID(body["job_id"])


def test_viewers_can_read_but_not_sync(viewer):
    assert viewer.get(f"/organizations/{viewer.org}/ad-accounts").status_code == 200
    assert viewer.get(f"{_base(viewer)}/metrics/daily").status_code == 200
    assert viewer.get(f"{_base(viewer)}/campaigns").status_code == 200
    response = viewer.post(f"{_base(viewer)}/resync")
    assert response.status_code == 403


def test_sync_now_is_limited_and_needs_a_link(owner, runtime):
    for _ in range(runtime.settings.THROTTLE_AD_ACCOUNT_RESYNC_PER_HOUR):
        assert owner.post(f"{_base(owner)}/resync").status_code == 202
    limited = owner.post(f"{_base(owner)}/resync")
    assert limited.status_code == 429
    unlinked = owner.post(f"/organizations/{owner.org}/resources/{owner.resource['id']}/unlink")
    assert unlinked.status_code == 200
    refused = owner.post(f"{_base(owner)}/resync")
    assert (refused.status_code, refused.json()["error"]["code"]) == (
        409,
        "AD_ACCOUNT_NOT_SYNCING",
    )
    account = _data(owner.get(_base(owner)))
    assert account["linked"] is False  # still readable after unlinking


def test_sync_now_while_a_run_is_going_is_refused(owner, admin_engine, clock):
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE ad_sync_state SET import_job_id = :j, updated_at = :t"),
            {"j": uuid.uuid4(), "t": clock.now()},
        )
    response = owner.post(f"{_base(owner)}/resync")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "SYNC_IN_PROGRESS")


# ------------------------------------------------------------------ secrets
def test_no_token_or_secret_appears_in_any_answer(owner, sim):
    items = _data(owner.get(f"{_base(owner)}/campaigns"))["items"]
    answers = [
        owner.get(f"/organizations/{owner.org}/ad-accounts").text,
        owner.get(_base(owner)).text,
        owner.get(f"{_base(owner)}/metrics/daily").text,
        owner.get(f"{_base(owner)}/campaigns").text,
        owner.get(f"/organizations/{owner.org}/campaigns/{items[0]['id']}").text,
        owner.post(f"{_base(owner)}/resync").text,
    ]
    secrets = [DEVELOPER_TOKEN, CLIENT_SECRET, *sim.access_tokens, *sim.refresh_tokens]
    for answer in answers:
        for secret in secrets:
            assert secret not in answer
