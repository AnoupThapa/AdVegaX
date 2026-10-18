"""Importing a linked Google Ads account's structure (task 3-05, PLAN §8-§9).

Linking an advertiser account creates it in AdVegaX and starts its import chain: the account's
own details, then budgets, campaigns, ad groups and ads (removed ones kept so history stays
readable). An account that is cancelled or no longer reachable ends the chain with a plain
code on the account, never on the connection.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.advertising.importer import start_import
from app.domains.advertising.models import AdAccount
from sqlalchemy import text

from tests.google_ads_sim import GoogleAdsSim, build_provider, sample_hierarchy, sample_structure

SUB = "108000000000000000001"
AU = "1000000001"  # under Agency > Retail clients


@pytest.fixture
def sim(runtime, clock):
    s = sample_hierarchy(GoogleAdsSim(clock=clock))
    sample_structure(s.customers[AU])
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def owner(make_client, sim):
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


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _link(owner, external_id=AU):
    response = owner.post(
        f"/organizations/{owner.org}/resources/{owner.resources[external_id]['id']}/link"
    )
    assert response.status_code == 201, response.text


def test_linking_creates_the_account_and_imports_its_structure(owner, sim, admin_engine, clock):
    _link(owner)
    (account,) = _rows(
        admin_engine,
        "SELECT name, currency, timezone, status, platform_status, history_from, "
        "first_import_completed_at, health_code FROM ad_accounts",
    )
    today = clock.now().date()
    assert (account["name"], account["currency"], account["timezone"]) == (
        "Eve Zone AU",
        "AUD",
        "Australia/Sydney",
    )
    assert (account["status"], account["platform_status"], account["health_code"]) == (
        "active",
        "active",
        None,
    )
    assert account["first_import_completed_at"] is not None
    assert 394 <= (today - account["history_from"]).days <= 396  # 13 months (Q-3-6)

    budgets = _rows(
        admin_engine,
        "SELECT external_budget_id, name, period, amount, currency, shared FROM ad_budgets "
        "ORDER BY 1",
    )
    assert budgets == [
        {
            "external_budget_id": "501",
            "name": "Gloves daily",
            "period": "daily",
            "amount": Decimal("50.000000"),
            "currency": "AUD",
            "shared": True,
        },
        {
            "external_budget_id": "502",
            "name": "Spring push",
            "period": "lifetime",
            "amount": Decimal("1234.560000"),
            "currency": "AUD",
            "shared": False,
        },
    ]
    campaigns = _rows(
        admin_engine,
        "SELECT c.external_campaign_id AS id, c.name, c.status, c.platform_type, "
        "c.bidding_strategy_type, c.start_date, c.end_date, b.external_budget_id AS budget "
        "FROM ad_campaigns c LEFT JOIN ad_budgets b ON b.id = c.budget_id ORDER BY 1",
    )
    assert [(c["id"], c["status"], c["budget"]) for c in campaigns] == [
        ("11", "active", "501"),
        ("12", "paused", "502"),
        ("13", "removed", None),  # kept: its history stays readable
    ]  # "14" has a status AdVegaX does not know: skipped, never guessed
    pmax = campaigns[1]
    assert (pmax["platform_type"], pmax["start_date"], pmax["end_date"]) == (
        "PERFORMANCE_MAX",
        date(2026, 3, 1),
        date(2026, 5, 31),
    )
    assert campaigns[0]["end_date"] is None  # runs indefinitely
    groups = _rows(
        admin_engine, "SELECT external_ad_group_id, status, platform_type FROM ad_groups ORDER BY 1"
    )
    assert groups == [
        {"external_ad_group_id": "2101", "status": "active", "platform_type": "SEARCH_STANDARD"},
        {"external_ad_group_id": "2102", "status": "removed", "platform_type": "SEARCH_STANDARD"},
    ]
    ads = _rows(admin_engine, "SELECT external_ad_id, name, status FROM ads ORDER BY 1")
    assert ads == [
        {"external_ad_id": "90001", "name": None, "status": "active"},
        {"external_ad_id": "90002", "name": "Vinyl RSA", "status": "paused"},
    ]
    (state,) = _rows(
        admin_engine, "SELECT import_progress, import_job_id, last_error_code FROM ad_sync_state"
    )
    assert state == {"import_progress": 100, "import_job_id": None, "last_error_code": None}
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    for expected in (
        "ad_account.import_started",
        "ad_account.structure_imported",
        "ad_account.import_completed",
    ):
        assert expected in actions


def test_the_structure_reads_through_the_manager_and_costs_five_operations(owner, sim):
    before = len(sim.calls("googleAds:searchStream"))
    _link(owner)
    calls = sim.calls("googleAds:searchStream")[before:]
    structure = [c for c in calls if b"segments.date" not in c.content]  # figures: 3-06
    assert len(structure) == 5  # account, budgets, campaigns, ad groups, ads
    assert {c.url.path.split("/")[3] for c in calls} == {AU}
    assert {c.headers.get("login-customer-id") for c in calls} == {"9000000001"}
    assert not [r for r in sim.requests if r.url.path.endswith(":search")]  # streamed reads only


def test_a_new_import_updates_and_never_deletes(owner, sim, runtime, admin_engine):
    _link(owner)
    customer = sim.customers[AU]
    customer.campaigns[0]["campaign"]["name"] = "Gloves - Search (AU)"
    customer.campaigns[1]["campaign"]["status"] = "REMOVED"
    customer.campaigns = customer.campaigns[:2]  # campaign 13 no longer listed
    customer.budgets[0]["campaignBudget"]["amountMicros"] = "75500000"
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        account = session.query(AdAccount).one()
        start_import(session, runtime, account, requested_by=None)
    campaigns = {
        r["external_campaign_id"]: r
        for r in _rows(admin_engine, "SELECT external_campaign_id, name, status FROM ad_campaigns")
    }
    assert campaigns["11"]["name"] == "Gloves - Search (AU)"
    assert campaigns["12"]["status"] == "removed"
    assert campaigns["13"]["status"] == "removed"  # still there
    (budget,) = _rows(
        admin_engine, "SELECT amount FROM ad_budgets WHERE external_budget_id = '501'"
    )
    assert budget["amount"] == Decimal("75.500000")
    assert len(_rows(admin_engine, "SELECT id FROM ad_campaigns")) == 3


def test_a_directly_accessible_account_is_read_without_a_manager(owner, sim):
    sample_structure(sim.customers["1000000003"])
    before = len(sim.calls("googleAds:searchStream"))
    _link(owner, "1000000003")
    calls = sim.calls("googleAds:searchStream")[before:]
    assert {c.headers.get("login-customer-id") for c in calls} == {None}


def test_an_account_cancelled_after_linking_says_so_and_the_connection_stays(
    owner, sim, admin_engine
):
    sim.customers[AU].status = "CANCELED"
    _link(owner)
    (account,) = _rows(admin_engine, "SELECT status, health_code FROM ad_accounts")
    assert account == {"status": "error", "health_code": "account_not_enabled"}
    (state,) = _rows(admin_engine, "SELECT last_error_code FROM ad_sync_state")
    assert state["last_error_code"] == "account_not_enabled"
    assert _rows(admin_engine, "SELECT id FROM ad_campaigns") == []
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("active", None)


def test_an_account_whose_status_is_reported_as_closed_is_not_imported(owner, sim, admin_engine):
    original = sim.account_row

    def closing(customer):
        row = original(customer)
        row["customer"]["status"] = "CLOSED"
        return row

    sim.account_row = closing
    _link(owner)
    (account,) = _rows(admin_engine, "SELECT platform_status, health_code FROM ad_accounts")
    assert account == {"platform_status": "closed", "health_code": "account_not_enabled"}


def test_losing_access_to_one_account_never_marks_the_connection(owner, sim, admin_engine):
    sim.fail_next.append((403, {"authorizationError": "USER_PERMISSION_DENIED"}))
    _link(owner)
    (account,) = _rows(admin_engine, "SELECT status, health_code FROM ad_accounts")
    assert account == {"status": "error", "health_code": "no_account_access"}
    detail = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert detail["status"] == "active"


def test_a_permanent_error_ends_the_chain_with_its_code(owner, sim, admin_engine):
    calls = {"n": 0}
    real = sim.handler

    def refuse_the_campaign_query(request):
        if b"campaign.start_date_time" in request.content:
            calls["n"] += 1
            return sim.failure(400, {"queryError": "UNRECOGNIZED_FIELD"})
        return real(request)

    sim.handler = refuse_the_campaign_query
    _link(owner)
    assert calls["n"] == 1  # not retried: a bad query stays bad
    (account,) = _rows(admin_engine, "SELECT status FROM ad_accounts")
    (state,) = _rows(admin_engine, "SELECT last_error_code, import_job_id FROM ad_sync_state")
    assert account["status"] == "error"
    assert state == {"last_error_code": "bad_query", "import_job_id": None}


def test_relinking_an_imported_account_reuses_it(owner, sim, admin_engine):
    _link(owner)
    resource = owner.resources[AU]["id"]
    assert owner.post(f"/organizations/{owner.org}/resources/{resource}/unlink").status_code == 200
    _link(owner)
    assert len(_rows(admin_engine, "SELECT id FROM ad_accounts")) == 1
    assert len(_rows(admin_engine, "SELECT id FROM ad_campaigns")) == 3


def test_a_duplicated_step_message_stops_at_once(owner, sim, runtime):
    from app.domains.advertising import importer
    from app.domains.jobs.service import ClaimedJob

    _link(owner)
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        account_id = session.query(AdAccount).one().id
    before = len(sim.requests)
    importer.import_step(
        runtime,
        ClaimedJob(
            id=uuid.uuid4(),
            organization_id=uuid.UUID(owner.org),
            job_type=importer.JOB_AD_IMPORT_STEP,
            subject_id=str(account_id),
            attempts=1,
            max_attempts=5,
            requested_by_user_id=None,
            correlation_id=None,
        ),
    )
    assert len(sim.requests) == before
