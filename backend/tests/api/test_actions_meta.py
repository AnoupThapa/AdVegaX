"""The Action Engine against the Meta simulator (Phase 10A, tasks 10A-03 … 10A-07).

A linked Meta ad account (AUD, Sydney) with the sample structure: campaign 120001 holds its
own daily budget (Advantage campaign budget, AUD 50.00); campaign 120002's ad sets hold theirs.
Changes need Meta's ``ads_management`` permission, granted by signing in again through the
change configuration ("Allow changes", Q-10A-2).
"""

from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import text

from tests.api.test_actions_api import (
    body,
    campaign_id,
    enable,
    held,  # noqa: F401  (fixture)
    rates,
    reasons,
    rows,
    run,
)
from tests.meta_sim import WRITE_CONFIG_ID, MetaSim, build_provider, sample_structure

USER = "10160000000000001"
AU = "act_1001"


@pytest.fixture
def msim(runtime, clock):
    s = MetaSim(clock=clock)
    s.add_user(USER)
    sample_structure(
        s.add_account(
            AU, USER, name="Eve Zone AU", currency="AUD", timezone_name="Australia/Sydney"
        )
    )
    runtime.providers.register(build_provider(s, write_config=True))
    return s


def _connect(c, sim, params):
    started = c.post(f"/organizations/{c.org}/connections/meta_ads/start", {"params": params})
    assert started.status_code == 200, started.text
    url = started.json()["data"]["authorize_url"]
    response = c.http.get(
        "/api/v1/connections/meta_ads/callback",
        params=sim.approve(url, USER),
        follow_redirects=False,
    )
    return url, parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]


@pytest.fixture
def meta(make_client, msim, runtime, admin_engine):
    rates(admin_engine)
    enable(runtime)
    c = make_client()
    c.signup(f"meta-actions-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    _, c.conn = _connect(c, msim, {})
    resources = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    found = {r["external_id"]: r for r in resources}
    assert c.post(f"/organizations/{c.org}/resources/{found[AU]['id']}/link").status_code == 201
    c.base = f"/organizations/{c.org}/actions"
    c.access = f"/organizations/{c.org}/connections/{c.conn}/write-access"
    c.put(
        f"/organizations/{c.org}/action-settings",
        {"paused": False, "require_second_person": False, "max_daily_budget": "500.00"},
    )
    c.cbo = campaign_id(admin_engine, "120001")
    c.adset_budget = campaign_id(admin_engine, "120002")
    return c


@pytest.fixture
def allowed(meta, msim):
    url, again = _connect(meta, msim, {"access": "changes"})
    assert parse_qs(urlsplit(url).query)["config_id"] == [WRITE_CONFIG_ID]
    assert again == meta.conn  # the same connection, now with the change permission
    response = meta.put(meta.access, {"allowed": True})
    assert response.status_code == 200, response.text
    return meta


def _row(sim, campaign):
    return next(r for r in sim.accounts[AU].campaigns if r["id"] == campaign)


def _posts(sim):
    return [
        {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
        for r in sim.requests
        if r.method == "POST" and r.url.path.rsplit("/", 1)[-1].isdigit()
    ]


def test_changes_need_metas_change_permission(meta, msim):
    access = meta.get(meta.access).json()["data"]
    assert access["allowed"] is False and access["missing_permissions"] == ["ads_management"]
    assert access["can_request_permission"] is True
    refused = meta.put(meta.access, {"allowed": True})
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "ACTION_NOT_ALLOWED")
    assert reasons(refused) == ["permission_missing"]
    asked = meta.post(meta.base, body(meta.cbo))
    assert reasons(asked) == ["permission_missing"]
    assert (
        meta.post(
            f"/organizations/{meta.org}/connections/meta_ads/start", {"params": {"access": "all"}}
        ).status_code
        == 422
    )


def test_pause_and_daily_budget_on_meta(allowed, msim):
    paused = allowed.post(allowed.base, body(allowed.cbo)).json()["data"]
    done = allowed.post(f"{allowed.base}/{paused['id']}/approve").json()["data"]
    assert (done["status"], done["verification"]) == ("succeeded", "verified")
    assert _row(msim, "120001")["status"] == "PAUSED"
    posts = _posts(msim)
    assert posts[0] == {"status": "PAUSED", "execution_options": json.dumps(["validate_only"])}
    assert posts[-1] == {"status": "PAUSED"}

    change = allowed.post(
        allowed.base, body(allowed.cbo, "campaign.set_daily_budget", daily_budget="62.50")
    ).json()["data"]
    assert change["previous"]["daily_budget"] == "50.00"
    done = allowed.post(f"{allowed.base}/{change['id']}/approve").json()["data"]
    assert (done["status"], done["verification"]) == ("succeeded", "verified")
    assert _row(msim, "120001")["daily_budget"] == "6250"  # cents
    assert _posts(msim)[-1] == {"daily_budget": "6250"}


def test_a_budget_held_by_the_ad_sets_is_refused(allowed):
    response = allowed.post(
        allowed.base, body(allowed.adset_budget, "campaign.set_daily_budget", daily_budget="20")
    )
    assert reasons(response) == ["budget_on_ad_sets"]


def test_a_permission_taken_back_at_meta_fails_the_dry_run_only(allowed, msim, admin_engine):
    msim.users[USER].granted.remove("ads_management")
    response = allowed.post(allowed.base, body(allowed.cbo))
    assert response.json()["error"]["code"] == "ACTION_INVALID"
    assert response.json()["error"]["details"] == [
        {"check": "dry_run", "reason": "meta_permission_missing"}
    ]
    (connection,) = rows(admin_engine, "SELECT status FROM external_connections")
    assert connection["status"] == "active"  # reading still works: the connection is fine


def test_a_lost_meta_answer_is_looked_up(allowed, msim, held, runtime):  # noqa: F811
    action = allowed.post(allowed.base, body(allowed.cbo)).json()["data"]
    allowed.post(f"{allowed.base}/{action['id']}/approve")
    msim.change_outcomes = ["lose_answer"]
    run(runtime, held.pop())
    assert allowed.get(f"{allowed.base}/{action['id']}").json()["data"]["status"] == "unknown"
    run(runtime, held.pop())
    data = allowed.get(f"{allowed.base}/{action['id']}").json()["data"]
    assert (data["status"], data["verification"]) == ("succeeded", "verified")
    assert len(msim.mutations) == 1


def test_a_meta_change_is_audited_without_tokens(allowed, admin_engine):
    action = allowed.post(allowed.base, body(allowed.cbo)).json()["data"]
    allowed.post(f"{allowed.base}/{action['id']}/approve")
    with admin_engine.connect() as db:
        stored = db.execute(
            text("SELECT platform_request, platform_answer, previous, observed FROM actions")
        ).one()
        audit = db.execute(text("SELECT before_json, after_json, metadata FROM audit_logs")).all()
    blob = json.dumps([list(stored), [list(a) for a in audit]], default=str)
    assert "EAAsim" not in blob and "appsecret" not in blob
