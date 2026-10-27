"""The campaign builder against the Google Ads and Meta simulators (Phase 10B, 10B-02 … 10B-07).

The golden shop (``test_strategy_context``) with a strategy marked ready for Google Ads and
Meta and its creatives drafted with the AI simulator and approved; plus a Google Ads test
account (AUD, Sydney) and a Meta ad account (AUD) connected through the simulators, both
with "Allow changes". The organization's maximum is AUD 500.00; the platform minimum AUD 1.60.

Covers PLAN §8 and §10: drafts and every builder check, the platform's test, launch through
the Action Engine with approval, everything created **paused**, Go live as a second approved
change, a stop part-way (Meta) left paused and cleaned up, a lost answer looked up by the
reference and never sent twice, the second-person rule, roles and tenants.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.integrations.tokens import account_lock
from app.domains.jobs.service import JobOutcome
from sqlalchemy import text

from tests.api.test_actions_api import gsim, held, rates, rows, run  # noqa: F401  (fixtures)
from tests.api.test_actions_meta import USER as META_USER
from tests.api.test_actions_meta import msim  # noqa: F401  (fixture)
from tests.api.test_creatives_api import _draft, _one, _png, maker  # noqa: F401  (fixtures)
from tests.api.test_strategies_api import owner  # noqa: F401  (fixture)
from tests.api.test_strategy_context import shop  # noqa: F401  (fixture)

SUB = "108000000000000000001"
AU = "1000000001"
META_AU = "act_1001"


def _link(c, provider, approve, external, params=None):
    started = c.post(
        f"/organizations/{c.org}/connections/{provider}/start", {"params": params or {}}
    )
    assert started.status_code == 200, started.text
    response = c.http.get(
        f"/api/v1/connections/{provider}/callback",
        params=approve(started.json()["data"]["authorize_url"]),
        follow_redirects=False,
    )
    conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    if external is not None:
        resources = c.get(f"/organizations/{c.org}/connections/{conn}/resources").json()["data"]
        found = {r["external_id"]: r for r in resources}
        assert (
            c.post(f"/organizations/{c.org}/resources/{found[external]['id']}/link").status_code
            == 201
        )
    return conn


@pytest.fixture
def builder(maker, gsim, msim, runtime, admin_engine):  # noqa: F811
    c = maker
    rates(admin_engine)
    runtime.settings = runtime.settings.model_copy(update={"ACTIONS_ENABLED": True})
    c.gconn = _link(c, "google_ads", lambda url: gsim.approve(url, SUB), AU)
    c.mconn = _link(c, "meta_ads", lambda url: msim.approve(url, META_USER), META_AU)
    _link(c, "meta_ads", lambda url: msim.approve(url, META_USER), None, {"access": "changes"})
    for conn in (c.gconn, c.mconn):
        assert (
            c.put(
                f"/organizations/{c.org}/connections/{conn}/write-access", {"allowed": True}
            ).status_code
            == 200
        )
    c.put(
        f"/organizations/{c.org}/action-settings",
        {"paused": False, "require_second_person": False, "max_daily_budget": "500.00"},
    )
    accounts = {
        a["external_account_id"]: a["id"]
        for a in c.get(f"/organizations/{c.org}/ad-accounts").json()["data"]
    }
    c.g_account, c.m_account = accounts[AU], accounts[META_AU]
    data = _draft(c)
    google, meta = _one(data, "google_ads"), _one(data, "meta_ads")
    asset = c.upload(c.assets, "gloves.png", _png()).json()["data"]
    meta = c.patch(f"{c.creatives}/{meta['id']}", {"asset_id": asset["id"]}).json()["data"]
    for creative in (google, meta):
        approved = c.post(f"{c.creatives}/{creative['id']}/approve", {"confirm_flags": True})
        assert approved.status_code == 200, approved.text
    c.drafts = f"/organizations/{c.org}/campaign-drafts"
    c.actions = f"/organizations/{c.org}/actions"
    c.gsim, c.msim = gsim, msim
    return c


def _new(b, platform="google_ads", **more):
    account = b.g_account if platform == "google_ads" else b.m_account
    response = b.post(
        b.drafts,
        {"strategy_id": b.strategy, "platform": platform, "ad_account_id": account, **more},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _ready(b, platform="google_ads"):
    draft = _new(b, platform)
    changes: dict = {"confirm_declarations": True}
    if platform == "google_ads":
        changes["keywords"] = [
            {"text": "nitrile gloves"},
            {"text": "bulk gloves", "match": "exact"},
        ]
    else:
        changes["meta_page_id"] = "1122334455"
    response = b.patch(f"{b.drafts}/{draft['id']}", changes)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _launch(b, draft):
    response = b.post(f"{b.drafts}/{draft['id']}/launch")
    assert response.status_code == 201, response.text
    return response.json()["data"]


def reasons(response):
    return [d.get("reason") for d in response.json()["error"]["details"]]


def gcampaign(sim, reference):
    return next(
        r["campaign"]
        for r in sim.customers[AU].campaigns
        if reference in r["campaign"].get("name", "")
    )


# ------------------------------------------------------------------ drafts
def test_a_draft_is_filled_in_from_the_strategy(builder):
    draft = _new(builder)
    assert draft["platform"] == "google_ads" and draft["status"] == "draft"
    assert draft["creative"]["status"] == "approved"
    assert draft["reference"].startswith("AVX-") and draft["reference"] in draft["name"]
    assert draft["currency"] == "AUD" and draft["locations"] == ["AU"]
    assert Decimal(draft["daily_budget"]) > 0
    assert draft["landing_url"].startswith("https://") and draft["editable"] is True
    assert draft["bidding"] == "maximize_clicks"  # the sim account reports no conversions
    assert draft["declarations_confirmed"] is False


def test_the_builder_checks(builder):
    draft = _new(builder)
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    failed = [(c["check"], c["reason"]) for c in preview["checks"] if c["result"] == "failed"]
    assert failed == [("keywords", "keywords_required")]
    bad = builder.patch(
        f"{builder.drafts}/{draft['id']}",
        {
            "keywords": [{"text": "gloves!!"}, {"text": "cure for germs"}],
            "locations": ["AU", "ZZ"],
            "landing_url": "http://elsewhere.example/x",
            "daily_budget": "900",
        },
    ).json()["data"]
    assert bad["version"] == 2
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    failed = [(c["check"], c["reason"]) for c in preview["checks"] if c["result"] == "failed"]
    assert failed == [
        ("keywords", "keyword_characters:0"),
        ("keywords", "keyword_prohibited:1"),
    ]
    builder.patch(
        f"{builder.drafts}/{draft['id']}",
        {"keywords": [{"text": "nitrile gloves"}]},
    )
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    failed = [(c["check"], c["reason"]) for c in preview["checks"] if c["result"] == "failed"]
    assert failed == [("targeting", "location_not_supported")]
    builder.patch(f"{builder.drafts}/{draft['id']}", {"locations": ["AU"]})
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    failed = [c["reason"] for c in preview["checks"] if c["result"] == "failed"]
    assert failed == ["landing_url_not_https"]
    builder.patch(f"{builder.drafts}/{draft['id']}", {"landing_url": "https://elsewhere.example/x"})
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    assert [c["reason"] for c in preview["checks"] if c["result"] == "failed"] == [
        "landing_url_not_store"
    ]
    store = draft["landing_url"]
    builder.patch(f"{builder.drafts}/{draft['id']}", {"landing_url": store})
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    assert [c["reason"] for c in preview["checks"] if c["result"] == "failed"] == ["above_maximum"]
    builder.patch(f"{builder.drafts}/{draft['id']}", {"daily_budget": "20"})
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    assert [c["reason"] for c in preview["checks"] if c["result"] == "failed"] == [
        "declaration_required"
    ]
    builder.patch(f"{builder.drafts}/{draft['id']}", {"confirm_declarations": True})
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    assert preview["passed"] is True and preview["dry_run"]["result"] == "passed"
    assert preview["budget_limits"] == {
        "platform_minimum": "1.60",
        "organization_maximum": "500.00",
    }
    assert builder.gsim.mutations == []  # the test changed nothing
    sent = json.loads(
        [r for r in builder.gsim.requests if r.url.path.endswith("googleAds:mutate")][-1].content
    )
    assert sent["validateOnly"] is True


def test_the_organizations_own_web_address_is_allowed(builder):
    draft = _ready(builder)
    builder.patch(
        f"{builder.drafts}/{draft['id']}", {"landing_url": "https://www.evezone.com.au/p"}
    )
    preview = builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]
    assert "landing_url_not_store" in [c["reason"] for c in preview["checks"]]
    settings = f"/organizations/{builder.org}/action-settings"
    assert (
        builder.put(
            settings,
            {
                "paused": False,
                "require_second_person": False,
                "max_daily_budget": "500",
                "landing_domains": ["bad domain"],
            },
        ).status_code
        == 422
    )
    builder.put(
        settings,
        {
            "paused": False,
            "require_second_person": False,
            "max_daily_budget": "500",
            "landing_domains": ["EveZone.com.au"],
        },
    )
    builder.patch(f"{builder.drafts}/{draft['id']}", {"confirm_declarations": True})
    assert builder.post(f"{builder.drafts}/{draft['id']}/validate").json()["data"]["passed"] is True


def test_only_approved_creatives_and_ready_strategies(builder, admin_engine):
    with admin_engine.begin() as db:
        db.execute(text("UPDATE creatives SET status = 'archived' WHERE platform = 'google_ads'"))
    refused = builder.post(
        builder.drafts,
        {
            "strategy_id": builder.strategy,
            "platform": "google_ads",
            "ad_account_id": builder.g_account,
        },
    )
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "CREATIVE_NOT_APPROVED")
    with admin_engine.begin() as db:
        db.execute(text("UPDATE campaign_strategies SET status = 'draft'"))
    refused = builder.post(
        builder.drafts,
        {
            "strategy_id": builder.strategy,
            "platform": "meta_ads",
            "ad_account_id": builder.m_account,
        },
    )
    assert reasons(refused) == ["strategy_not_ready"]


def test_two_google_accounts_need_a_choice(builder):
    response = builder.post(
        builder.drafts, {"strategy_id": builder.strategy, "platform": "google_ads"}
    )
    assert response.status_code == 422  # the golden shop's own account and the linked one
    assert reasons(response) == ["choose_ad_account"]


# ------------------------------------------------------------------ Google launch
def test_a_google_campaign_is_created_paused_then_goes_live(builder, admin_engine):
    draft = _ready(builder)
    action = _launch(builder, draft)
    assert action["action_type"] == "campaign.create" and action["status"] == "pending"
    assert action["campaign"] is None and action["draft"]["id"] == draft["id"]
    assert builder.gsim.mutations == []
    done = builder.post(f"{builder.actions}/{action['id']}/approve").json()["data"]
    assert (done["status"], done["verification"]) == ("succeeded", "verified")  # paused
    campaign = gcampaign(builder.gsim, draft["reference"])
    assert campaign["status"] == "PAUSED" and campaign["advertisingChannelType"] == "SEARCH"
    assert campaign["containsEuPoliticalAdvertising"] == "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"
    assert "targetSpend" in campaign  # maximize clicks
    keywords = [k["keyword"] for k in builder.gsim.customers[AU].criteria if "keyword" in k]
    assert keywords == [
        {"text": "nitrile gloves", "matchType": "PHRASE"},
        {"text": "bulk gloves", "matchType": "EXACT"},
    ]
    after = builder.get(f"{builder.drafts}/{draft['id']}").json()["data"]
    assert after["status"] == "created" and after["created_ids"]["campaign"] == campaign["id"]
    assert after["campaign_id"] is not None  # the quick sync read it into Advertising
    assert after["editable"] is False
    assert builder.patch(f"{builder.drafts}/{draft['id']}", {"name": "x"}).status_code == 409

    live = builder.post(f"{builder.drafts}/{draft['id']}/go-live")
    assert live.status_code == 201, live.text
    assert gcampaign(builder.gsim, draft["reference"])["status"] == "PAUSED"  # not yet
    builder.post(f"{builder.actions}/{live.json()['data']['id']}/approve")
    assert gcampaign(builder.gsim, draft["reference"])["status"] == "ENABLED"
    assert builder.get(f"{builder.drafts}/{draft['id']}").json()["data"]["status"] == "live"
    audit = [
        r["action"]
        for r in rows(
            admin_engine,
            "SELECT action FROM audit_logs WHERE resource_type IN "
            "('action', 'campaign_draft') ORDER BY created_at",
        )
    ]
    assert audit[:2] == ["campaign_draft.created", "campaign_draft.edited"]
    assert "action.succeeded" in audit


def test_a_refused_google_launch_creates_nothing(builder, held, runtime):  # noqa: F811
    draft = _ready(builder)
    action = _launch(builder, draft)
    builder.post(f"{builder.actions}/{action['id']}/approve")
    builder.gsim.change_outcomes = ["refuse"]
    run(runtime, held.pop())
    data = builder.get(f"{builder.actions}/{action['id']}").json()["data"]
    assert (data["status"], data["error_code"]) == ("failed", "invalid_request")
    after = builder.get(f"{builder.drafts}/{draft['id']}").json()["data"]
    assert (after["status"], after["created_ids"]) == ("draft", {})  # fix it and launch again
    assert not any(
        draft["reference"] in r["campaign"].get("name", "")
        for r in builder.gsim.customers[AU].campaigns
    )


def test_a_lost_google_answer_is_found_by_the_reference(builder, held, runtime):  # noqa: F811
    draft = _ready(builder)
    action = _launch(builder, draft)
    builder.post(f"{builder.actions}/{action['id']}/approve")
    builder.gsim.change_outcomes = ["lose_answer"]
    run(runtime, held.pop())
    assert builder.get(f"{builder.actions}/{action['id']}").json()["data"]["status"] == "unknown"
    run(runtime, held.pop())
    data = builder.get(f"{builder.actions}/{action['id']}").json()["data"]
    assert (data["status"], data["events"][-1]["detail"]) == ("succeeded", {"found_by": "look_up"})
    creates = [m for m in builder.gsim.mutations if m["resources"] == "googleAds"]
    assert len(creates) == 1  # never sent twice
    assert builder.get(f"{builder.drafts}/{draft['id']}").json()["data"]["status"] == "created"


def test_an_existing_campaign_with_the_reference_is_never_created_again(builder, held, runtime):  # noqa: F811
    draft = _ready(builder)
    first = _launch(builder, draft)
    builder.post(f"{builder.actions}/{first['id']}/approve")
    builder.gsim.change_outcomes = ["timeout"]  # it was not made
    run(runtime, held.pop())
    run(runtime, held.pop())
    data = builder.get(f"{builder.actions}/{first['id']}").json()["data"]
    assert (data["status"], data["error_code"]) == ("failed", "not_applied")
    again = builder.post(f"{builder.drafts}/{draft['id']}/launch").json()["data"]
    builder.post(f"{builder.actions}/{again['id']}/approve")
    # Before the worker sends it, the campaign appears at Google with the draft's reference
    # (e.g. made by an earlier attempt): the worker finds it and creates nothing.
    builder.gsim.customers[AU].campaigns.append(
        {
            "campaign": {
                "id": "990",
                "name": draft["name"],
                "status": "PAUSED",
                "resourceName": f"customers/{AU}/campaigns/990",
            }
        }
    )
    run(runtime, held.pop())
    data = builder.get(f"{builder.actions}/{again['id']}").json()["data"]
    assert (data["status"], data["events"][-1]["detail"]) == ("succeeded", {"found_by": "look_up"})
    assert [m for m in builder.gsim.mutations if m["resources"] == "googleAds"] == []


# ------------------------------------------------------------------ Meta launch
def test_a_meta_campaign_is_created_paused_step_by_step(builder):
    draft = _ready(builder, "meta_ads")
    assert draft["bidding"] == "link_clicks"
    action = _launch(builder, draft)
    done = builder.post(f"{builder.actions}/{action['id']}/approve").json()["data"]
    assert (done["status"], done["verification"]) == ("succeeded", "verified")
    assert [m["create"] for m in builder.msim.mutations] == [
        "adimages",
        "campaigns",
        "adsets",
        "adcreatives",
        "ads",
    ]
    account = builder.msim.accounts[META_AU]
    made = [
        r
        for r in [*account.campaigns, *account.adsets, *account.ads]
        if draft["reference"] in r.get("name", "")
    ]
    assert len(made) == 3 and all(r["status"] == "PAUSED" for r in made)
    campaign = next(r for r in account.campaigns if draft["reference"] in r["name"])
    assert campaign["objective"] == "OUTCOME_SALES" and campaign["special_ad_categories"] == "[]"
    adset = next(r for r in account.adsets if draft["reference"] in r["name"])
    assert json.loads(adset["targeting"]) == {
        "geo_locations": {"countries": ["AU"]},
        "age_min": 18,
        "age_max": 65,
    }
    live = builder.post(f"{builder.drafts}/{draft['id']}/go-live").json()["data"]
    builder.post(f"{builder.actions}/{live['id']}/approve")
    assert all(r["status"] == "ACTIVE" for r in made)


def test_a_meta_launch_stopped_part_way_is_left_paused_and_cleaned_up(builder, held, runtime):  # noqa: F811
    draft = _ready(builder, "meta_ads")
    action = _launch(builder, draft)
    builder.post(f"{builder.actions}/{action['id']}/approve")
    builder.msim.change_outcomes = ["ok", "ok", "refuse"]  # image, campaign, then the ad set
    run(runtime, held.pop())
    data = builder.get(f"{builder.actions}/{action['id']}").json()["data"]
    assert data["status"] == "failed"
    after = builder.get(f"{builder.drafts}/{draft['id']}").json()["data"]
    assert after["status"] == "failed" and set(after["created_ids"]) == {"image", "campaign"}
    campaign = next(
        r for r in builder.msim.accounts[META_AU].campaigns if draft["reference"] in r["name"]
    )
    assert campaign["status"] == "PAUSED"  # nothing runs
    clean = builder.post(f"{builder.drafts}/{draft['id']}/clean-up")
    assert clean.status_code == 201, clean.text
    builder.post(f"{builder.actions}/{clean.json()['data']['id']}/approve")
    run(runtime, held.pop())
    assert campaign["status"] == "DELETED"
    after = builder.get(f"{builder.drafts}/{draft['id']}").json()["data"]
    assert (after["status"], after["created_ids"]) == ("draft", {})


def test_a_lost_meta_answer_is_looked_up(builder, held, runtime):  # noqa: F811
    draft = _ready(builder, "meta_ads")
    action = _launch(builder, draft)
    builder.post(f"{builder.actions}/{action['id']}/approve")
    builder.msim.change_outcomes = ["ok", "ok", "ok", "ok", "lose_answer"]  # the ad's answer
    run(runtime, held.pop())
    assert builder.get(f"{builder.actions}/{action['id']}").json()["data"]["status"] == "unknown"
    run(runtime, held.pop())
    data = builder.get(f"{builder.actions}/{action['id']}").json()["data"]
    assert data["status"] == "succeeded"
    assert len([m for m in builder.msim.mutations if m["create"] == "ads"]) == 1


def test_meta_pages_and_pixels(builder):
    base = f"/organizations/{builder.org}/ad-accounts/{builder.m_account}"
    assert builder.get(f"{base}/meta-pages").json()["data"] == [
        {"id": "1122334455", "name": "Eve Zone"}
    ]
    builder.msim.accounts[META_AU].pixels = [{"id": "5566778899", "name": "Eve Zone pixel"}]
    assert builder.get(f"{base}/meta-pixels").json()["data"][0]["id"] == "5566778899"
    draft = _ready(builder, "meta_ads")
    out = builder.patch(f"{builder.drafts}/{draft['id']}", {"meta_pixel_id": "5566778899"}).json()[
        "data"
    ]
    assert out["bidding"] == "purchases"
    google = f"/organizations/{builder.org}/ad-accounts/{builder.g_account}/meta-pages"
    assert builder.get(google).status_code == 404


# ------------------------------------------------------------------ rules
def test_one_launch_at_a_time_and_the_switches(builder, runtime, held):  # noqa: F811
    draft = _ready(builder)
    _launch(builder, draft)
    twice = builder.post(f"{builder.drafts}/{draft['id']}/launch")
    assert twice.status_code == 409
    assert builder.patch(f"{builder.drafts}/{draft['id']}", {"name": "x"}).status_code == 409
    runtime.settings = runtime.settings.model_copy(update={"ACTIONS_ENABLED": False})
    other = _ready(builder, "meta_ads")
    off = builder.post(f"{builder.drafts}/{other['id']}/launch")
    assert off.json()["error"]["code"] == "ACTIONS_DISABLED"


def test_go_live_needs_a_created_campaign_and_a_busy_draft_waits(builder, held, runtime):  # noqa: F811
    draft = _ready(builder)
    early = builder.post(f"{builder.drafts}/{draft['id']}/go-live")
    assert reasons(early) == ["draft_not_created"]
    action = _launch(builder, draft)
    builder.post(f"{builder.actions}/{action['id']}/approve")
    with account_lock(runtime.redis, f"action-draft:{draft['id']}", wait_seconds=0):
        assert run(runtime, held.pop()) is JobOutcome.RETRY
    assert builder.gsim.mutations == []


def test_a_draft_changed_after_the_request_is_not_approved(builder, admin_engine):
    draft = _ready(builder)
    action = _launch(builder, draft)
    with admin_engine.begin() as db:
        db.execute(text("UPDATE campaign_drafts SET version = version + 1"))
    refused = builder.post(f"{builder.actions}/{action['id']}/approve")
    assert reasons(refused) == ["draft_changed"]


def test_roles_and_tenants(builder, make_client):
    draft = _new(builder)
    analyst = make_client()
    email = f"analyst-{uuid.uuid4().hex[:6]}@example.com"
    analyst.signup(email)
    builder.invite_and_join(builder.org, analyst, email, "analyst")
    assert analyst.get(f"{builder.drafts}/{draft['id']}").status_code == 200
    assert analyst.patch(f"{builder.drafts}/{draft['id']}", {"name": "x"}).status_code == 403
    assert analyst.post(f"{builder.drafts}/{draft['id']}/launch").status_code == 403
    other = make_client()
    other.signup(f"other-{uuid.uuid4().hex[:6]}@example.com")
    org = other.create_org("Other")["id"]
    assert other.get(f"/organizations/{org}/campaign-drafts/{draft['id']}").status_code == 404
    archived = builder.post(f"{builder.drafts}/{draft['id']}/archive").json()["data"]
    assert archived["status"] == "archived"
    assert builder.get(builder.drafts).json()["data"] == []
