"""Importing a linked Meta ad account's structure (task 4-04, PLAN §4.1 items 7-8, Q-4-4, Q-4-8).

Linking creates the account and starts its import chain: the account's own details, then
campaigns, ad sets and ads. Archived and deleted objects are asked for explicitly (Meta hides
them by default) and kept, so history stays readable. A budget belongs to the campaign or to
the ad set and arrives in the currency's smallest unit — cents for most currencies, whole
units for 11 such as JPY — and is stored as an exact amount.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.advertising.importer import start_import
from app.domains.advertising.models import AdAccount
from sqlalchemy import text

from tests.meta_sim import MetaSim, build_provider, sample_structure

USER = "10160000000000001"
AU = "act_1001"
JP = "act_1002"


@pytest.fixture
def sim(runtime, clock):
    s = MetaSim(clock=clock)
    s.add_user(USER)
    sample_structure(
        s.add_account(
            AU, USER, name="Eve Zone AU", currency="AUD", timezone_name="Australia/Sydney"
        )
    )
    sample_structure(
        s.add_account(JP, USER, name="Eve Zone JP", currency="JPY", timezone_name="Asia/Tokyo")
    )
    runtime.providers.register(build_provider(s))
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


def _budgets(admin_engine):
    return _rows(
        admin_engine,
        "SELECT b.external_budget_id AS id, b.level, b.period, b.amount, b.currency, b.shared "
        "FROM ad_budgets b ORDER BY 1",
    )


def test_linking_imports_campaigns_ad_sets_and_ads(owner, sim, admin_engine):
    _link(owner)
    (account,) = _rows(admin_engine, "SELECT name, currency, timezone FROM ad_accounts")
    assert account == {"name": "Eve Zone AU", "currency": "AUD", "timezone": "Australia/Sydney"}
    campaigns = _rows(
        admin_engine,
        "SELECT c.external_campaign_id AS id, c.name, c.status, c.platform_type, "
        "c.bidding_strategy_type, c.start_date, c.end_date, c.provider_extensions, "
        "b.external_budget_id AS budget "
        "FROM ad_campaigns c LEFT JOIN ad_budgets b ON b.id = c.budget_id ORDER BY 1",
    )
    assert [(c["id"], c["status"], c["budget"]) for c in campaigns] == [
        ("120001", "active", "campaign:120001"),
        ("120002", "paused", None),  # its ad set holds the budget
        ("120003", "archived", None),
        ("120004", "removed", None),  # deleted: kept, its history stays readable
    ]  # 120005: a status outside the filter is never returned
    sales, spring = campaigns[0], campaigns[1]
    assert (sales["platform_type"], sales["bidding_strategy_type"]) == (
        "OUTCOME_SALES",
        "LOWEST_COST_WITHOUT_CAP",
    )
    assert sales["provider_extensions"] == {"buying_type": "AUCTION"}
    assert (sales["start_date"], sales["end_date"]) == (date(2026, 3, 1), None)
    assert (spring["start_date"], spring["end_date"]) == (date(2026, 3, 1), date(2026, 5, 31))

    groups = _rows(
        admin_engine,
        "SELECT g.external_ad_group_id AS id, c.external_campaign_id AS campaign, g.status, "
        "g.platform_type, g.provider_extensions, b.external_budget_id AS budget "
        "FROM ad_groups g JOIN ad_campaigns c ON c.id = g.campaign_id "
        "LEFT JOIN ad_budgets b ON b.id = g.budget_id ORDER BY 1",
    )
    assert groups == [
        {
            "id": "230001",
            "campaign": "120001",
            "status": "active",
            "platform_type": "OFFSITE_CONVERSIONS",
            "provider_extensions": None,
            "budget": None,
        },
        {
            "id": "230002",
            "campaign": "120002",
            "status": "paused",  # the campaign's pause passes down
            "platform_type": "LINK_CLICKS",
            "provider_extensions": {"bid_strategy": "COST_CAP"},
            "budget": "adset:230002",
        },
        {
            "id": "230003",
            "campaign": "120004",
            "status": "removed",
            "platform_type": None,
            "provider_extensions": None,
            "budget": None,
        },
    ]
    ads = _rows(
        admin_engine, "SELECT external_ad_id, name, status, provider_extensions FROM ads ORDER BY 1"
    )
    assert ads == [
        {
            "external_ad_id": "340001",
            "name": "Vinyl gloves video",
            "status": "active",
            "provider_extensions": {"creative_id": "450001", "creative_name": "Gloves 15s"},
        },
        {
            "external_ad_id": "340002",
            "name": "Nitrile carousel",
            "status": "active",
            "provider_extensions": {"delivery": "DISAPPROVED"},  # shown as Meta reports it
        },
        {
            "external_ad_id": "340003",
            "name": "Spring banner",
            "status": "paused",
            "provider_extensions": None,
        },
        {
            "external_ad_id": "340004",
            "name": None,
            "status": "removed",
            "provider_extensions": None,
        },
    ]
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert "ad_account.structure_imported" in actions


def test_budgets_in_cents_are_converted_exactly(owner, admin_engine):
    _link(owner)
    assert _budgets(admin_engine) == [
        {
            "id": "adset:230002",
            "level": "ad_group",
            "period": "lifetime",
            "amount": Decimal("1234.560000"),
            "currency": "AUD",
            "shared": False,
        },
        {
            "id": "campaign:120001",
            "level": "campaign",
            "period": "daily",
            "amount": Decimal("50.000000"),
            "currency": "AUD",
            "shared": False,
        },
    ]


def test_budgets_in_whole_yen_are_not_divided(owner, admin_engine):
    _link(owner, JP)
    amounts = {b["id"]: (b["amount"], b["currency"]) for b in _budgets(admin_engine)}
    assert amounts == {
        "campaign:120001": (Decimal("5000.000000"), "JPY"),  # not 50
        "adset:230002": (Decimal("123456.000000"), "JPY"),
    }


def test_archived_and_deleted_objects_are_asked_for_explicitly(owner, sim):
    _link(owner)
    edges = [r for r in sim.requests if r.url.path.split("/")[-1] in {"campaigns", "adsets", "ads"}]
    assert [r.url.path.split("/")[-1] for r in edges] == ["campaigns", "adsets", "ads"]
    for request in edges:
        query = parse_qs(request.url.query.decode())
        (rule,) = json.loads(query["filtering"][0])
        assert rule["field"] == "effective_status" and {"ARCHIVED", "DELETED"} <= set(rule["value"])
        assert query["limit"] == ["500"] and "access_token" not in query
        assert request.method == "GET"


def test_the_account_is_read_once_per_import(owner, sim):
    _link(owner)
    assert len([r for r in sim.requests if r.url.path.endswith(f"/{AU}")]) == 1


def test_large_accounts_are_read_page_by_page(owner, sim, admin_engine):
    account = sim.accounts[AU]
    account.ads += [
        {
            "id": str(350000 + n),
            "name": f"Ad {n}",
            "adset_id": "230001",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
        }
        for n in range(1100)
    ]
    _link(owner)
    assert len(_rows(admin_engine, "SELECT id FROM ads")) == 1104
    assert len([r for r in sim.requests if r.url.path.endswith("/ads")]) == 3


def test_a_new_import_updates_and_never_deletes(owner, sim, runtime, admin_engine):
    _link(owner)
    account = sim.accounts[AU]
    account.campaigns[0]["name"] = "Gloves - Sales (AU)"
    account.campaigns[0]["daily_budget"] = "7550"
    account.campaigns[1].update(status="DELETED", effective_status="DELETED")
    account.campaigns = account.campaigns[:2]  # 120003 and 120004 no longer listed
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        start_import(session, runtime, session.query(AdAccount).one(), requested_by=None)
    campaigns = {
        r["external_campaign_id"]: r
        for r in _rows(admin_engine, "SELECT external_campaign_id, name, status FROM ad_campaigns")
    }
    assert campaigns["120001"]["name"] == "Gloves - Sales (AU)"
    assert campaigns["120002"]["status"] == "removed"
    assert campaigns["120003"]["status"] == "archived"  # still there
    assert len(campaigns) == 4
    amounts = {b["id"]: b["amount"] for b in _budgets(admin_engine)}
    assert amounts["campaign:120001"] == Decimal("75.500000")


def test_a_budget_moving_from_campaign_to_ad_set_follows(owner, sim, runtime, admin_engine):
    _link(owner)
    account = sim.accounts[AU]
    account.campaigns[0]["daily_budget"] = "0"
    account.adsets[0]["daily_budget"] = "2500"
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        start_import(session, runtime, session.query(AdAccount).one(), requested_by=None)
    (campaign,) = _rows(
        admin_engine, "SELECT budget_id FROM ad_campaigns WHERE external_campaign_id = '120001'"
    )
    assert campaign["budget_id"] is None
    (group,) = _rows(
        admin_engine,
        "SELECT b.amount FROM ad_groups g JOIN ad_budgets b ON b.id = g.budget_id "
        "WHERE g.external_ad_group_id = '230001'",
    )
    assert group["amount"] == Decimal("25.000000")


def test_losing_access_to_one_account_never_marks_the_connection(owner, sim, admin_engine):
    sim.accounts[AU].users.clear()
    _link(owner)
    (account,) = _rows(admin_engine, "SELECT status, health_code FROM ad_accounts")
    assert account == {"status": "error", "health_code": "no_account_access"}
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"


def test_an_account_disabled_after_linking_is_not_imported(owner, sim, admin_engine):
    sim.accounts[AU].account_status = 2
    _link(owner)  # discovered while active; disabled since
    (account,) = _rows(admin_engine, "SELECT status, platform_status, health_code FROM ad_accounts")
    assert account == {
        "status": "error",
        "platform_status": "suspended",
        "health_code": "account_not_enabled",
    }
    assert _rows(admin_engine, "SELECT id FROM ad_campaigns") == []


def test_a_bad_query_ends_the_chain_with_its_code(owner, sim, admin_engine):
    calls = {"n": 0}

    def refuse(s, request, user_id):
        calls["n"] += 1
        return s.error(400, 100)

    sim.routes[f"GET /{AU}/adsets"] = refuse
    _link(owner)
    assert calls["n"] == 1  # not retried: a bad query stays bad
    (state,) = _rows(admin_engine, "SELECT last_error_code, import_job_id FROM ad_sync_state")
    assert state == {"last_error_code": "bad_query", "import_job_id": None}
