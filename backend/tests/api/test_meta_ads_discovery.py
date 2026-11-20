"""Finding the Meta ad accounts a sign-in can reach (task 4-03, PLAN §6, Q-4-3).

``me/adaccounts`` lists every ad account the person can use — their own and those reached
through a business — with its name, currency, time zone, status and owning business. Accounts
become linkable resources grouped by business; accounts that cannot be used (disabled, an
unpaid balance, under review, closed, unknown status, missing details) are listed with a plain
reason and cannot be linked. Pages are followed with the ``after`` cursor, never ``next``.
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from app.providers.meta_ads import provider as meta_provider

from tests.meta_sim import MetaSim, build_provider

USER = "10160000000000001"


@pytest.fixture
def sim(runtime, clock):
    s = MetaSim(clock=clock)
    s.add_user(USER)
    s.add_account("act_1001", USER, name="Eve Zone DE")
    s.add_account(
        "act_1002", USER, name="Eve Zone US", currency="USD", timezone_name="America/New_York"
    )
    s.add_account("act_1003", USER, name="Own account", business=None)
    s.add_account("act_1004", USER, name="Old shop", account_status=101)
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup(f"meta-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    return c


def _connect(client, sim, user=USER):
    started = client.post(
        f"/organizations/{client.org}/connections/meta_ads/start", {"params": {}}
    ).json()["data"]["authorize_url"]
    response = client.http.get(
        "/api/v1/connections/meta_ads/callback",
        params=sim.approve(started, user),
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


def test_accounts_are_found_with_their_details_and_business(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    assert sorted(found) == ["act_1001", "act_1002", "act_1003", "act_1004"]
    de, us, own, old = (found[k] for k in sorted(found))
    assert (de["display_name"], de["currency"], de["timezone"], de["kind"]) == (
        "Eve Zone DE",
        "EUR",
        "Europe/Berlin",
        "ad_account",
    )
    assert (us["currency"], us["timezone"]) == ("USD", "America/New_York")
    assert de["group_path"] == us["group_path"] == "Eve Zone Business"
    assert own["group_path"] is None and own["unavailable_reason"] is None
    assert old["unavailable_reason"] == "account_not_enabled"
    (call,) = sim.calls("/me/adaccounts")
    query = parse_qs(call.url.query.decode())
    assert "account_status" in query["fields"][0] and "business{id,name}" in query["fields"][0]
    assert "access_token" not in query  # the token is in the header


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (1, None),
        (9, None),  # grace period: still delivering
        (2, "account_not_enabled"),
        (3, "account_unsettled"),
        (8, "account_unsettled"),
        (7, "account_under_review"),
        (100, "account_not_enabled"),
        (101, "account_not_enabled"),
        (999, "account_not_enabled"),  # unknown: never treated as usable
    ],
)
def test_each_status_gets_a_plain_reason(owner, sim, status, reason):
    sim.accounts["act_1001"].account_status = status
    _connect(owner, sim)
    assert _resources(owner)["act_1001"]["unavailable_reason"] == reason


@pytest.mark.parametrize(
    ("field", "value"),
    [("currency", None), ("currency", "eur"), ("timezone_name", None), ("timezone_name", "Nope/X")],
)
def test_accounts_without_usable_details_cannot_be_linked(owner, sim, field, value):
    setattr(sim.accounts["act_1001"], field, value)
    _connect(owner, sim)
    account = _resources(owner)["act_1001"]
    assert account["unavailable_reason"] == "account_details_missing"
    link = owner.post(f"/organizations/{owner.org}/resources/{account['id']}/link")
    assert (link.status_code, link.json()["error"]["details"]) == (
        409,
        [{"reason": "account_details_missing"}],
    )


def test_available_accounts_can_be_linked_and_unavailable_ones_cannot(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    ok = owner.post(f"/organizations/{owner.org}/resources/{found['act_1001']['id']}/link")
    assert ok.status_code == 201, ok.text
    refused = owner.post(f"/organizations/{owner.org}/resources/{found['act_1004']['id']}/link")
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert (error["code"], error["details"]) == (
        "RESOURCE_UNAVAILABLE",
        [{"reason": "account_not_enabled"}],
    )
    accounts = owner.get(f"/organizations/{owner.org}/ad-accounts").json()["data"]
    assert [
        (a["provider"], a["external_account_id"], a["currency"], a["timezone"], a["group_path"])
        for a in accounts
    ] == [("meta_ads", "act_1001", "EUR", "Europe/Berlin", "Eve Zone Business")]


def test_many_accounts_are_read_page_by_page_with_the_cursor(owner, sim):
    for n in range(450):
        sim.add_account(f"act_{2000 + n}", USER, name=f"Store {n}")
    _connect(owner, sim)
    assert len(_resources(owner)) == 454
    pages = sim.calls("/me/adaccounts")
    assert len(pages) == 3
    afters = [parse_qs(p.url.query.decode()).get("after") for p in pages]
    assert afters == [None, ["cur200"], ["cur400"]]


def test_rediscovery_updates_reasons_and_businesses_but_keeps_links(owner, sim):
    _connect(owner, sim)
    found = _resources(owner)
    owner.post(f"/organizations/{owner.org}/resources/{found['act_1001']['id']}/link")
    sim.accounts["act_1001"].account_status = 3
    sim.accounts["act_1002"].business = ("555000111", "Eve Zone Group")
    _rediscover(owner)
    again = _resources(owner)
    assert again["act_1001"]["unavailable_reason"] == "account_unsettled"
    assert again["act_1002"]["group_path"] == "Eve Zone Group"
    assert again["act_1001"]["linked"] is True  # its data stays readable


def test_a_person_without_ad_accounts_finds_none(owner, sim):
    sim.add_user("10160000000000002")
    _connect(owner, sim, user="10160000000000002")
    assert _resources(owner) == {}
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("active", None)


def test_unreadable_rows_are_skipped(owner, sim):
    sim.extra_rows = [{"id": "1234"}, {"name": "no id"}, {"id": "act_x"}]
    _connect(owner, sim)
    assert sorted(_resources(owner)) == ["act_1001", "act_1002", "act_1003", "act_1004"]


def test_the_same_account_twice_is_listed_once(owner, sim):
    sim.extra_rows = [sim.accounts["act_1001"].row()]
    _connect(owner, sim)
    assert list(_resources(owner)).count("act_1001") == 1


def test_discovery_stops_at_its_limit(owner, sim, monkeypatch):
    monkeypatch.setattr(meta_provider, "MAX_ACCOUNTS", 2)
    _connect(owner, sim)
    assert len([r for r in _resources(owner).values() if r["accessible"]]) == 2


def test_a_token_meta_no_longer_accepts_asks_to_reconnect(owner, sim):
    _connect(owner, sim)
    sim.tokens.clear()
    _rediscover(owner)
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "expired"  # shown as "Needs reconnecting"
    assert detail["last_error_code"] == "meta_sign_in_rejected"
