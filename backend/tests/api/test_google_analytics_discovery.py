"""Finding the GA4 properties a Google sign-in can reach (task 5-04, PLAN §6, Q-5-3).

``accountSummaries`` lists every Analytics account and its properties; ``properties.get``
gives each property's currency and time zone. Properties become linkable resources grouped
by Analytics account; a property AdVegaX cannot read or use is listed with a plain reason and
cannot be linked.
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from app.providers.google_analytics import provider as ga_provider

from tests.ga4_sim import GA4Sim, build_provider

SUB = "108000000000000000001"


@pytest.fixture
def sim(runtime, clock):
    s = GA4Sim(clock=clock)
    s.add_account("900", "Eve Zone")
    s.add_account("901", "Mediflex")
    s.add_property("111", "900", SUB, display_name="Eve Zone AU")
    s.add_property(
        "112", "900", SUB, display_name="Eve Zone NZ", currency="NZD", time_zone="Pacific/Auckland"
    )
    s.add_property(
        "211", "901", SUB, display_name="Mediflex", currency="USD", time_zone="America/Los_Angeles"
    )
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup(f"ga-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    return c


def _connect(client, sim, sub=SUB):
    started = client.post(
        f"/organizations/{client.org}/connections/google_analytics/start", {"params": {}}
    ).json()["data"]["authorize_url"]
    response = client.http.get(
        "/api/v1/connections/google_analytics/callback",
        params=sim.approve(started, sub),
        follow_redirects=False,
    )
    query = {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}
    assert query["status"] == "connected", query
    client.conn = query["connection_id"]
    return client.conn


def _resources(client):
    response = client.get(f"/organizations/{client.org}/connections/{client.conn}/resources")
    assert response.status_code == 200
    return {r["external_id"]: r for r in response.json()["data"]}


def _rediscover(client):
    response = client.post(f"/organizations/{client.org}/connections/{client.conn}/rediscover")
    assert response.status_code == 202


def test_properties_are_found_with_their_details_and_account(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    assert sorted(found) == ["111", "112", "211"]
    au, nz, med = found["111"], found["112"], found["211"]
    assert (au["display_name"], au["currency"], au["timezone"], au["kind"]) == (
        "Eve Zone AU",
        "AUD",
        "Australia/Sydney",
        "analytics_property",
    )
    assert (nz["currency"], nz["timezone"]) == ("NZD", "Pacific/Auckland")
    assert au["group_path"] == nz["group_path"] == "Eve Zone"
    assert med["group_path"] == "Mediflex"
    assert all(r["unavailable_reason"] is None for r in found.values())
    assert len(sim.calls("/accountSummaries")) == 1
    assert len(sim.calls("/properties/")) == 3  # one details read per property


@pytest.mark.parametrize(
    ("field", "value"),
    [("currency", None), ("currency", "aud"), ("time_zone", None), ("time_zone", "Mars/Base")],
)
def test_properties_without_usable_details_cannot_be_linked(owner, sim, field, value):
    setattr(sim.properties["111"], field, value)
    _connect(owner, sim)
    prop = _resources(owner)["111"]
    assert prop["unavailable_reason"] == "property_details_missing"
    link = owner.post(f"/organizations/{owner.org}/resources/{prop['id']}/link")
    assert (link.status_code, link.json()["error"]["details"]) == (
        409,
        [{"reason": "property_details_missing"}],
    )


def test_a_property_that_cannot_be_read_says_so_and_the_others_carry_on(owner, sim):
    sim.property_errors["112"] = (403, "PERMISSION_DENIED", None)
    _connect(owner, sim)
    found = _resources(owner)
    assert found["112"]["unavailable_reason"] == "no_property_access"
    assert found["112"]["display_name"] == "Eve Zone NZ"  # the name from the summary
    assert found["111"]["unavailable_reason"] is None


def test_available_properties_can_be_linked(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    ok = owner.post(f"/organizations/{owner.org}/resources/{found['111']['id']}/link")
    assert ok.status_code == 201, ok.text
    assert _resources(owner)["111"]["linked"] is True


def test_many_accounts_are_read_page_by_page(owner, sim):
    for n in range(450):
        sim.add_property(str(5000 + n), str(7000 + n), SUB, display_name=f"Shop {n}")
    _connect(owner, sim)
    assert len(_resources(owner)) == 453
    pages = sim.calls("/accountSummaries")
    assert len(pages) == 3  # 200 accounts a page
    assert parse_qs(pages[0].url.query.decode())["pageSize"] == ["200"]


def test_rediscovery_updates_names_and_reasons_but_keeps_links(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    owner.post(f"/organizations/{owner.org}/resources/{found['111']['id']}/link")
    sim.accounts["900"].display_name = "Eve Zone Group"
    sim.properties["112"].currency = None
    _rediscover(owner)
    again = _resources(owner)
    assert again["111"]["group_path"] == "Eve Zone Group"
    assert again["112"]["unavailable_reason"] == "property_details_missing"
    assert again["111"]["linked"] is True


def test_a_property_no_longer_listed_is_marked_inaccessible(owner, sim):
    _connect(owner, sim)
    sim.properties["211"].users.clear()  # access removed in Google Analytics
    _rediscover(owner)
    assert _resources(owner)["211"]["accessible"] is False


def test_a_person_without_analytics_finds_no_properties(owner, sim):
    _connect(owner, sim, sub="108000000000000000002")
    assert _resources(owner) == {}
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("active", None)


def test_discovery_stops_at_its_limit(owner, sim, monkeypatch):
    monkeypatch.setattr(ga_provider, "MAX_PROPERTIES", 2)
    _connect(owner, sim)
    assert len([r for r in _resources(owner).values() if r["accessible"]]) == 2


def test_the_analytics_apis_not_enabled_is_reported_on_the_connection(owner, sim):
    _connect(owner, sim)
    sim.api_enabled = False
    _rediscover(owner)
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("error", "analytics_api_disabled")


def test_a_sign_in_google_no_longer_accepts_needs_reconnecting(owner, sim):
    _connect(owner, sim)
    sim.access_tokens.clear()
    _rediscover(owner)
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("expired", "google_sign_in_rejected")
