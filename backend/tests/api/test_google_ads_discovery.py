"""Finding the Google Ads accounts a sign-in can reach (task 3-04, PLAN §6.4, Q-3-3).

Google lists only accounts with direct access; accounts under managers come from each
manager's hierarchy, read with the top manager as ``login-customer-id``. Advertiser accounts
become linkable resources with their name, currency, time zone and manager path; managers
appear only as that path; accounts that cannot be used are listed with a plain reason and
cannot be linked.
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from app.providers.google_ads import provider as google_provider

from tests.google_ads_sim import GoogleAdsSim, build_provider, sample_hierarchy

SUB = "108000000000000000001"


@pytest.fixture
def sim(runtime, clock):
    s = sample_hierarchy(GoogleAdsSim(clock=clock))
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup(f"ads-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    return c


def _connect(client, sim, sub=SUB):
    started = client.post(
        f"/organizations/{client.org}/connections/google_ads/start", {"params": {}}
    ).json()["data"]["authorize_url"]
    response = client.http.get(
        "/api/v1/connections/google_ads/callback",
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


def test_accounts_are_found_directly_and_under_managers(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    assert sorted(found) == ["1000000001", "1000000002", "1000000003", "1000000004"]  # no managers
    au, nz, direct, cancelled = (found[k] for k in sorted(found))
    assert (au["display_name"], au["currency"], au["timezone"], au["kind"]) == (
        "Eve Zone AU",
        "AUD",
        "Australia/Sydney",
        "ad_account",
    )
    assert (nz["currency"], nz["timezone"]) == ("NZD", "Pacific/Auckland")
    assert au["group_path"] == nz["group_path"] == "Agency > Retail clients"
    assert direct["group_path"] is None and direct["unavailable_reason"] is None
    assert cancelled["unavailable_reason"] == "account_not_enabled"
    assert all("access_hint" not in r for r in found.values())  # internal only


def test_each_manager_is_read_once_through_the_top_manager(owner, sim):
    _connect(owner, sim)
    calls = sim.calls("googleAds:searchStream")
    targets = [c.url.path.split("/")[3] for c in calls]
    assert sorted(targets) == ["1000000003", "1000000004", "9000000001", "9000000002"]
    logins = {c.url.path.split("/")[3]: c.headers.get("login-customer-id") for c in calls}
    assert logins["9000000002"] == "9000000001"  # the sub-manager is reached via the top one
    assert logins["1000000003"] == "1000000003"
    assert len(sim.calls("listAccessibleCustomers")) == 1


def test_an_account_with_direct_access_is_listed_once_without_a_manager_path(owner, sim):
    sim.users[SUB].direct.append("1000000001")  # also invited directly
    _connect(owner, sim)
    found = _resources(owner)
    assert list(found).count("1000000001") == 1
    assert found["1000000001"]["group_path"] is None


def test_available_accounts_can_be_linked_and_unavailable_ones_cannot(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    ok = owner.post(f"/organizations/{owner.org}/resources/{found['1000000001']['id']}/link")
    assert ok.status_code == 201, ok.text
    refused = owner.post(f"/organizations/{owner.org}/resources/{found['1000000004']['id']}/link")
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert (error["code"], error["details"]) == (
        "RESOURCE_UNAVAILABLE",
        [{"reason": "account_not_enabled"}],
    )


def test_rediscovery_updates_reasons_and_paths_but_keeps_links(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    owner.post(f"/organizations/{owner.org}/resources/{found['1000000001']['id']}/link")
    sim.customers["1000000001"].status = "SUSPENDED"
    sim.customers["9000000002"].name = "Retail"
    rediscover = owner.post(f"/organizations/{owner.org}/connections/{owner.conn}/rediscover")
    assert rediscover.status_code == 202
    again = _resources(owner)
    assert again["1000000001"]["unavailable_reason"] == "account_not_enabled"
    assert again["1000000002"]["group_path"] == "Agency > Retail"
    assert again["1000000001"]["linked"] is True  # its data stays readable


def test_a_person_without_google_ads_finds_no_accounts(owner, sim):
    sim.add_user("108000000000000000002")
    _connect(owner, sim, sub="108000000000000000002")
    assert _resources(owner) == {}
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("active", None)


def test_a_manager_that_cannot_be_read_hides_only_its_own_accounts(owner, sim):
    original = sim.handler

    def refuse_sub_manager(request):
        if "/customers/9000000002/" in request.url.path:
            return sim.failure(403, {"authorizationError": "USER_PERMISSION_DENIED"})
        return original(request)

    sim.handler = refuse_sub_manager
    _connect(owner, sim)
    assert sorted(_resources(owner)) == ["1000000003", "1000000004"]


def test_a_test_token_explains_real_accounts(owner, sim):
    sim.customers["1000000003"].test = False  # a real account; the token has Test access only
    _connect(owner, sim)
    assert _resources(owner)["1000000003"]["unavailable_reason"] == "developer_token_not_approved"


@pytest.mark.parametrize(("field", "value"), [("timezone", "Mars/Olympus"), ("currency", "")])
def test_accounts_without_usable_details_cannot_be_linked(owner, sim, field, value):
    setattr(sim.customers["1000000003"], field, value)
    _connect(owner, sim)
    assert _resources(owner)["1000000003"]["unavailable_reason"] == "account_details_missing"


def test_hierarchies_that_loop_are_read_once(owner, sim):
    sim.customers["9000000002"].children.append("9000000001")  # a cycle
    _connect(owner, sim)
    targets = [c.url.path.split("/")[3] for c in sim.calls("googleAds:searchStream")]
    assert targets.count("9000000001") == 1 and targets.count("9000000002") == 1


def test_discovery_stops_at_its_limits(owner, sim, monkeypatch):
    monkeypatch.setattr(google_provider, "MAX_MANAGERS", 1)
    _connect(owner, sim)
    assert "1000000001" not in _resources(owner)  # behind the second manager
    monkeypatch.setattr(google_provider, "MAX_MANAGERS", 200)
    monkeypatch.setattr(google_provider, "MAX_ACCOUNTS", 1)
    owner.post(f"/organizations/{owner.org}/connections/{owner.conn}/rediscover")
    assert len([r for r in _resources(owner).values() if r["accessible"]]) == 1


def test_unreadable_rows_are_skipped(owner, sim):
    original = sim.hierarchy_rows

    def with_noise(customer_id):
        return [{"other": 1}, {"customerClient": {"id": "x", "level": "1"}}, *original(customer_id)]

    sim.hierarchy_rows = with_noise
    _connect(owner, sim)
    assert "1000000001" in _resources(owner)
