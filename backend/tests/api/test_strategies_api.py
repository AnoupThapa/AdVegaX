"""The campaign strategy API (task 8-05, PLAN §7, Q-8-7, Q-8-8) against the AI simulator.

The golden shop of ``test_strategy_context`` (AUD, Google Ads and Meta); the ECB rates of 13
October make 1 USD = 1.60 AUD, so each platform's minimum daily budget is 1.60 AUD.
"""

from __future__ import annotations

import copy
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.ai_sim import AiSim
from tests.api.test_campaigns_products_api import _exec
from tests.api.test_strategy_context import LAST, shop  # noqa: F401  (fixture)
from tests.api.test_strategy_task import ANSWER


def _rates(admin_engine):
    with admin_engine.begin() as db:
        for quote, rate in (("AUD", "1.6"), ("USD", "1.0")):
            db.execute(
                text(
                    "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                    "VALUES ('ecb', 'EUR', :q, :d, :r, now())"
                ),
                {"q": quote, "d": LAST, "r": Decimal(rate)},
            )


@pytest.fixture
def owner(runtime, shop, admin_engine):  # noqa: F811
    _rates(admin_engine)
    shop.sim = AiSim()
    runtime.settings = runtime.settings.model_copy(update={"AI_ENABLED": True})
    runtime.extras["ai_adapter"] = shop.sim.adapter()
    shop.base = f"/organizations/{shop.org}/ai/campaign-strategies"
    return shop


def _body(owner, **changes):
    body = {
        "product_id": str(owner.product),
        "platforms": ["google_ads", "meta_ads"],
        "objective": "sales",
        "budget": {"amount": "40.00", "period": "daily"},
    }
    body.update(changes)
    return body


def _generate(owner, **changes):
    owner.sim.queue(ANSWER)
    response = owner.post(owner.base, _body(owner, **changes))
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _audit(admin_engine, org):
    with admin_engine.connect() as db:
        return [
            (r.action, r.after_json)
            for r in db.execute(
                text(
                    "SELECT action, after_json FROM audit_logs WHERE organization_id = :o "
                    "AND resource_type = 'campaign_strategy' ORDER BY created_at"
                ),
                {"o": org},
            )
        ]


# ------------------------------------------------------------------ generate
def test_a_strategy_is_generated_validated_and_kept_as_a_draft(owner, admin_engine):
    data = _generate(owner)
    assert data["status"] == "draft" and data["validated"] is True
    assert data["strategy"] == ANSWER
    assert data["product_title"] == "Nitrile gloves"
    assert data["budget"] == {
        "amount": "40.00",
        "period": "daily",
        "currency": "AUD",
        "currency_minor_units": 2,
    }
    assert data["budget_amounts"] == {
        "google_ads": {"amount": "28.00", "daily": "28.00"},
        "meta_ads": {"amount": "12.00", "daily": "12.00"},
    }
    margin = data["evidence"]["product.gross_margin"]
    assert (margin["label"], margin["unit"], Decimal(margin["value"])) == (
        "Gross margin",
        "ratio",
        Decimal("0.6"),
    )
    run = data["ai_run"]
    assert (run["provider"], run["model"], run["prompt_name"], run["prompt_version"]) == (
        "anthropic",
        "claude-sonnet-5-5",
        "campaign_strategy",
        "v1",
    )
    ((action, after),) = _audit(admin_engine, owner.org)
    assert action == "campaign_strategy.generated"
    assert after["platforms"] == ["google_ads", "meta_ads"]
    assert "summary" not in str(after)  # the audit keeps no strategy text


def test_a_monthly_budget(owner):
    data = _generate(owner, budget={"amount": "912.00", "period": "monthly"})
    assert data["budget_amounts"]["google_ads"] == {"amount": "638.40", "daily": "21.00"}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("UPDATE product_variants SET inventory_available = 0 WHERE id = :v", "out_of_stock"),
        ("UPDATE products SET status = 'draft' WHERE id = :p", "product_not_active"),
    ],
)
def test_what_cannot_be_planned_never_reaches_the_model(owner, admin_engine, change, reason):
    _exec(admin_engine, change, v=owner.variant, p=owner.product)
    owner.sim.queue(ANSWER)
    response = owner.post(owner.base, _body(owner))
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "PRODUCT_NOT_PLANNABLE"
    assert {"reason": reason} in error["details"]
    assert owner.sim.requests == []


def test_budgets_below_the_platform_minimums_are_refused(owner):
    response = owner.post(owner.base, _body(owner, budget={"amount": "3.00", "period": "daily"}))
    assert response.json()["error"]["details"] == [{"reason": "budget_too_small"}]
    assert owner.sim.requests == []


def test_a_platform_not_connected_is_refused(owner, admin_engine):
    _exec(admin_engine, "DELETE FROM ad_performance_daily WHERE ad_account_id = :a", a=owner.meta)
    _exec(admin_engine, "DELETE FROM ad_accounts WHERE id = :a", a=owner.meta)
    response = owner.post(owner.base, _body(owner))
    assert {"reason": "platform_not_connected:meta_ads"} in response.json()["error"]["details"]


@pytest.mark.parametrize(
    "change",
    [
        {"platforms": ["google_ads", "google_ads"]},
        {"platforms": []},
        {"platforms": ["tiktok"]},
        {"objective": "profit"},
        {"budget": {"amount": "40.001", "period": "daily"}},
        {"budget": {"amount": "0", "period": "daily"}},
        {"budget": {"amount": "40", "period": "weekly"}},
    ],
)
def test_bad_requests(owner, change):
    response = owner.post(owner.base, _body(owner, **change))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_another_organizations_product_is_not_found(owner):
    response = owner.post(owner.base, _body(owner, product_id=str(uuid.uuid4())))
    assert response.status_code == 404


def test_ai_errors(owner, runtime):
    bad = copy.deepcopy(ANSWER)
    bad["angles"][0]["evidence"] = ["product.reviews"]
    owner.sim.queue(bad, bad)
    response = owner.post(owner.base, _body(owner))
    assert (response.status_code, response.json()["error"]["code"]) == (422, "AI_ANSWER_REJECTED")
    assert response.json()["error"]["details"] == [{"reason": "unknown_evidence:product.reviews"}]
    owner.sim.queue(529)
    response = owner.post(owner.base, _body(owner))
    assert (response.status_code, response.json()["error"]["code"]) == (503, "AI_UNAVAILABLE")
    runtime.settings = runtime.settings.model_copy(update={"AI_DAILY_RUNS": 2})
    response = owner.post(owner.base, _body(owner))
    assert (response.status_code, response.json()["error"]["code"]) == (429, "AI_LIMIT_REACHED")
    runtime.settings = runtime.settings.model_copy(update={"AI_ENABLED": False})
    response = owner.post(owner.base, _body(owner))
    assert response.json()["error"]["code"] == "AI_UNAVAILABLE"
    assert owner.get(owner.base).json()["meta"]["total"] == 0  # nothing was kept


# ------------------------------------------------------------------ read, edit, ready, archive
def test_read_and_list(owner):
    first = _generate(owner)
    second = _generate(owner)
    assert owner.get(f"{owner.base}/{first['id']}").json()["data"] == first
    listed = owner.get(owner.base).json()
    assert [s["id"] for s in listed["data"]] == [second["id"], first["id"]]
    assert listed["data"][0]["platforms"] == ["google_ads", "meta_ads"]
    owner.post(f"{owner.base}/{first['id']}/archive")
    assert [s["id"] for s in owner.get(owner.base).json()["data"]] == [second["id"]]
    archived = owner.get(f"{owner.base}?status=archived").json()["data"]
    assert [s["id"] for s in archived] == [first["id"]]
    assert owner.get(f"{owner.base}/{uuid.uuid4()}").status_code == 404


def test_an_edit_is_revalidated_and_recomputed(owner, admin_engine):
    data = _generate(owner)
    owner.post(f"{owner.base}/{data['id']}/ready")
    edited = copy.deepcopy(data["strategy"])
    edited["platforms"][0]["budget_share_percent"] = 50
    edited["platforms"][1]["budget_share_percent"] = 50
    edited["summary"] = "Split evenly while we learn."
    response = owner.patch(
        f"{owner.base}/{data['id']}",
        {"strategy": edited, "budget": {"amount": "1000.00", "period": "monthly"}},
    )
    assert response.status_code == 200, response.text
    out = response.json()["data"]
    assert out["status"] == "draft"  # reviewed again before it is ready
    assert out["strategy"]["summary"] == "Split evenly while we learn."
    assert out["budget_amounts"]["meta_ads"] == {"amount": "500.00", "daily": "16.45"}
    assert out["edited_by"] is not None and out["edited_at"] is not None
    actions = [a for a, _ in _audit(admin_engine, owner.org)]
    assert actions == [
        "campaign_strategy.generated",
        "campaign_strategy.ready",
        "campaign_strategy.edited",
    ]


@pytest.mark.parametrize(
    ("change", "issue"),
    [
        (
            lambda s: s["angles"][0].update(evidence=["product.reviews"]),
            "unknown_evidence:product.reviews",
        ),
        (lambda s: s["platforms"][1].update(budget_share_percent=10), "shares_do_not_add_up"),
        (lambda s: s.update(summary="x" * 601), "too_long:summary"),
        (lambda s: s.update(summary="bad\u0000text"), "invalid_text:summary"),
        (
            lambda s: s["platforms"][0].update(campaign_type="sales"),
            "campaign_type_not_for_platform:google_ads",
        ),
    ],
)
def test_invalid_edits_are_refused(owner, change, issue):
    data = _generate(owner)
    edited = copy.deepcopy(data["strategy"])
    change(edited)
    response = owner.patch(f"{owner.base}/{data['id']}", {"strategy": edited})
    assert response.status_code == 422
    assert {"field": "strategy", "issue": issue} in response.json()["error"]["details"]
    assert owner.get(f"{owner.base}/{data['id']}").json()["data"]["strategy"] == ANSWER


def test_a_budget_below_the_minimum_cannot_be_set_by_editing(owner):
    data = _generate(owner)
    response = owner.patch(
        f"{owner.base}/{data['id']}", {"budget": {"amount": "5", "period": "daily"}}
    )
    assert {"field": "strategy", "issue": "below_platform_minimum:meta_ads"} in response.json()[
        "error"
    ]["details"]


def test_ready_and_archive(owner):
    data = _generate(owner)
    url = f"{owner.base}/{data['id']}"
    assert owner.post(f"{url}/ready").json()["data"]["status"] == "ready"
    assert owner.post(f"{url}/ready").json()["data"]["status"] == "ready"  # no change
    assert owner.post(f"{url}/archive").json()["data"]["status"] == "archived"
    assert owner.post(f"{url}/archive").status_code == 200
    for response in (
        owner.post(f"{url}/ready"),
        owner.patch(url, {"budget": {"amount": "50", "period": "daily"}}),
    ):
        assert (response.status_code, response.json()["error"]["code"]) == (
            409,
            "STRATEGY_ARCHIVED",
        )


# ------------------------------------------------------------------ roles, tenants, usage
def test_roles(owner, make_client):
    data = _generate(owner)
    url = f"{owner.base}/{data['id']}"
    viewer, analyst = make_client(), make_client()
    for client, role in ((viewer, "viewer"), (analyst, "analyst")):
        email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
        client.signup(email)
        owner.invite_and_join(owner.org, client, email, role)
    assert viewer.get(url).status_code == 200
    for response in (
        viewer.post(owner.base, _body(owner)),
        viewer.patch(url, {"budget": {"amount": "50", "period": "daily"}}),
        viewer.post(f"{url}/ready"),
        viewer.post(f"{url}/archive"),
        viewer.get(f"/organizations/{owner.org}/ai/usage"),
        analyst.get(f"/organizations/{owner.org}/ai/usage"),
    ):
        assert response.status_code == 403
    owner.sim.queue(ANSWER)
    assert analyst.post(owner.base, _body(owner)).status_code == 201
    assert analyst.post(f"{url}/ready").status_code == 200


def test_outsiders_see_nothing(owner, make_client):
    data = _generate(owner)
    outsider = make_client()
    outsider.signup(f"out-{uuid.uuid4().hex[:6]}@example.com")
    other = outsider.create_org("Other Co")["id"]
    assert outsider.get(f"{owner.base}/{data['id']}").status_code in (403, 404)
    foreign = f"/organizations/{other}/ai/campaign-strategies/{data['id']}"
    assert outsider.get(foreign).status_code == 404
    assert outsider.post(f"{foreign}/archive").status_code == 404
    assert outsider.get(f"/organizations/{other}/ai/campaign-strategies").json()["data"] == []


def test_usage(owner, runtime):
    usage = owner.get(f"/organizations/{owner.org}/ai/usage").json()["data"]
    assert usage["runs_today"] == 0 and usage["remaining_today"] == 20
    assert usage["today"]["estimated_cost_usd"] is None  # no price set: unknown, never 0
    _generate(owner)
    owner.sim.queue(529)
    owner.post(owner.base, _body(owner))
    usage = owner.get(f"/organizations/{owner.org}/ai/usage").json()["data"]
    assert (usage["runs_today"], usage["remaining_today"], usage["ai_enabled"]) == (2, 18, True)
    today = usage["today"]
    assert (today["runs"], today["succeeded"], today["failed"], today["rejected"]) == (2, 1, 1, 0)
    assert (today["input_tokens"], today["output_tokens"]) == (1200, 300)
    assert usage["last_30_days"]["runs"] == 2
    runtime.settings = runtime.settings.model_copy(
        update={"AI_PRICE_INPUT_PER_MTOK": Decimal(3), "AI_PRICE_OUTPUT_PER_MTOK": Decimal(15)}
    )
    _generate(owner)
    usage = owner.get(f"/organizations/{owner.org}/ai/usage").json()["data"]
    assert usage["today"]["estimated_cost_usd"] is None  # earlier runs have no price
