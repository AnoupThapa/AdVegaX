# ruff: noqa: F401, F811 (fixtures shared with test_funnel_engine / test_unified_analytics_api)
"""The funnel API (task 7-06, PLAN §8, Q-7-1 … Q-7-9).

The golden funnel of ``test_funnel_engine.py`` read through the API, plus campaigns (with their
Google Analytics match and "Other traffic") and landing pages.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.api.test_funnel_engine import D5, D6, golden, org
from tests.api.test_unified_analytics_api import rates
from tests.helpers import connected

PERIOD = f"?from={D5}&to={D6}"


@pytest.fixture
def owner(golden, rates):
    return golden


def _get(c, path="", query=PERIOD):
    response = c.get(f"/organizations/{c.org}/analytics/funnel{path}{query}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _v(figure):
    return None if figure["value"] is None else Decimal(figure["value"])


# ------------------------------------------------------------------ the funnel
def test_the_funnel_with_its_sources_steps_and_context(owner):
    data = _get(owner)
    assert data["definition_version"] == "funnel-v1"
    assert [_v(data["stages"][k]) for k in data["stages"]] == [
        Decimal(4800),
        Decimal(140),
        Decimal(500),
        Decimal(200),
        Decimal(50),
        Decimal(20),
        Decimal(15),
        Decimal(10),
    ]
    steps = {(s["from_stage"], s["to_stage"]): s for s in data["steps"]}
    assert steps[("clicks", "landing_page_views")] == {
        "from_stage": "clicks",
        "to_stage": "landing_page_views",
        "kind": "different_sources",
        "rate": None,
    }
    assert steps[("adds_to_cart", "checkouts")]["rate"]["value"] == "0.400000"
    assert steps[("landing_page_views", "purchases")]["kind"] == "store_conversion"
    sources = {d["key"]: d["sources"] for d in data["definitions"]}
    assert sources["impressions"] == ["ads"] and sources["purchases"] == ["stores"]
    google, meta = data["platforms"]
    assert (google["provider"], google["source"]) == ("google_ads", "platform_reported")
    assert google["stages"]["adds_to_cart"]["reason"] == "not_provided_by_platform"
    assert _v(meta["stages"]["checkouts"]) == Decimal(6)
    assert {d["key"] for d in data["platform_definitions"]} == set(meta["stages"])
    assert [c["channel"] for c in data["channels"]] == ["Organic Search", "Paid Search"]
    assert data["channels_missing"] is None
    assert data["findings"] == []  # the history before 5 October was not read: never judged
    rules = data["rules"]
    assert (rules["min_events"], rules["baseline_days"]) == (200, 90)
    assert (rules["previous_from"], rules["previous_to"]) == ("2026-10-03", "2026-10-04")
    assert {s["kind"] for s in data["sources"]} == {"store", "ad_account", "analytics_property"}


def test_an_empty_organization_says_what_is_missing(make_client):
    c = make_client()
    c.signup(f"empty-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Empty")["id"]
    data = _get(c, query="")
    assert data["stages"]["impressions"]["reason"] == "no_ad_account"
    assert data["stages"]["landing_page_views"]["reason"] == "no_analytics_property"
    assert data["stages"]["purchases"]["reason"] == "no_store"
    assert (data["platforms"], data["channels"]) == ([], [])
    assert data["channels_missing"]["reason"] == "no_analytics_property"


# ------------------------------------------------------------------ campaigns
def _campaign(db, org, account, name, rows):
    cid = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO ad_campaigns (id, organization_id, ad_account_id, external_campaign_id, "
            "name, status) VALUES (:id, :org, :acc, :ext, :name, 'active')"
        ),
        {"id": cid, "ext": cid, "org": org, "acc": account, "name": name},
    )
    for day, impressions, clicks, buys, funnel in rows:
        lpv, views, carts, checkouts = funnel or (None, None, None, None)
        db.execute(
            text(
                "INSERT INTO ad_performance_daily (id, organization_id, ad_account_id, level, "
                "entity_key, campaign_id, day, impressions, clicks, cost, conversions, "
                "conversion_value, landing_page_views, content_views, adds_to_cart, "
                "checkouts_initiated, currency, fetched_at) SELECT gen_random_uuid(), :org, :acc, "
                "'campaign', :key, :cid, :day, :imp, :clk, 1, :buys, 0, :lpv, :views, :carts, "
                ":checkouts, currency, now() FROM ad_accounts WHERE id = :acc"
            ),
            {
                "org": org,
                "acc": account,
                "key": cid,
                "cid": cid,
                "day": day,
                "imp": impressions,
                "clk": clicks,
                "buys": Decimal(buys),
                "lpv": lpv,
                "views": views,
                "carts": carts,
                "checkouts": checkouts,
            },
        )
    return cid


def _source_row(db, prop, day, source, medium, campaign, n, views, carts, checkouts, buys):
    db.execute(
        text(
            "INSERT INTO analytics_daily (id, organization_id, property_id, day, breakdown, "
            "dimension_key, traffic_source, traffic_medium, campaign, sessions, engaged_sessions, "
            "total_users, new_users, key_events, purchases, purchase_revenue, item_view_events, "
            "add_to_carts, checkouts, currency, fetched_at) SELECT gen_random_uuid(), "
            "organization_id, id, :day, 'source', :key, :src, :med, :camp, :n, 0, 0, 0, 0, :b, 0, "
            ":v, :c, :k, currency, now() FROM analytics_properties WHERE id = :prop"
        ),
        {
            "prop": prop,
            "day": day,
            "key": f"{source}|{medium}|{campaign}",
            "src": source,
            "med": medium,
            "camp": campaign,
            "n": n,
            "v": views,
            "c": carts,
            "k": checkouts,
            "b": buys,
        },
    )


def _ids(admin_engine, org):
    with admin_engine.begin() as db:
        accounts = dict(
            db.execute(
                text("SELECT provider, id FROM ad_accounts WHERE organization_id = :o"), {"o": org}
            ).all()
        )
    return {k: str(v) for k, v in accounts.items()}


def test_campaign_funnels_with_their_match_and_other_traffic(owner, admin_engine):
    accounts = _ids(admin_engine, owner.org)
    with admin_engine.begin() as db:
        _campaign(db, owner.org, accounts["meta_ads"], "Gloves", [(D5, 900, 20, 2, (15, 10, 4, 2))])
        _campaign(db, owner.org, accounts["google_ads"], "Brand", [(D5, 500, 25, 1, None)])
        _source_row(db, owner.prop, D5, "facebook", "paid", "Gloves", 18, 9, 3, 2, 1)
        _source_row(db, owner.prop, D6, "instagram", "paid", "Gloves", 2, 1, 1, 0, 0)
        _source_row(db, owner.prop, D5, "google", "organic", "(organic)", 100, 40, 10, 5, 2)
    data = _get(owner, "/campaigns")
    items = {c["name"]: c for c in data["items"]}
    gloves, brand = items["Gloves"], items["Brand"]
    assert (gloves["provider"], gloves["source"], gloves["shared_match"]) == (
        "meta_ads",
        "platform_reported",
        False,
    )
    assert [_v(gloves["stages"][k]) for k in gloves["stages"]] == [
        Decimal(900),
        Decimal(20),
        Decimal(15),
        Decimal(10),
        Decimal(4),
        Decimal(2),
        Decimal(2),
    ]
    ga = gloves["analytics"]
    assert (_v(ga["landing_page_views"]), _v(ga["adds_to_cart"])) == (Decimal(20), Decimal(4))
    assert gloves["analytics_steps"][0]["rate"]["value"] == "0.500000"  # 10 views / 20 visits
    assert set(brand["stages"]) == {"impressions", "clicks", "purchases"}  # Google Ads' own
    assert brand["steps"][1]["rate"]["value"] == "0.040000"  # 1 conversion / 25 clicks
    assert brand["analytics"]["landing_page_views"]["reason"] == "no_match"
    # campaigns + other traffic = the website (the source view)
    other, website = data["other_traffic"], data["website"]
    for key in website:
        assert _v(website[key]) == _v(ga[key]) + _v(other[key]), key
    assert _v(other["landing_page_views"]) == Decimal(100)
    assert data["analytics_missing"] is None


def test_two_campaigns_of_the_same_name_share_one_match(owner, admin_engine, make_client):
    accounts = _ids(admin_engine, owner.org)
    with admin_engine.begin() as db:
        _campaign(db, owner.org, accounts["meta_ads"], "Sale", [])
        _campaign(db, owner.org, accounts["meta_ads"], "Sale", [])
        _source_row(db, owner.prop, D5, "facebook", "paid", "Sale", 10, 5, 2, 1, 1)
    data = _get(owner, "/campaigns")
    sales = [c for c in data["items"] if c["name"] == "Sale"]
    assert [c["shared_match"] for c in sales] == [True, True]
    assert _v(data["website"]["landing_page_views"]) == Decimal(10)  # counted once
    assert _v(data["other_traffic"]["landing_page_views"]) == Decimal(0)


def test_campaigns_for_a_period_not_read(owner):
    data = _get(owner, "/campaigns", "?from=2025-09-01&to=2025-09-30")
    assert data["analytics_missing"]["availability"] == "not_synchronized"
    assert (data["other_traffic"], data["website"]) == (None, None)


# ------------------------------------------------------------------ landing pages
def _page(db, prop, day, page, n, views, carts, checkouts, buys):
    db.execute(
        text(
            "INSERT INTO analytics_daily (id, organization_id, property_id, day, breakdown, "
            "dimension_key, landing_page, sessions, engaged_sessions, total_users, new_users, "
            "key_events, purchases, purchase_revenue, item_view_events, add_to_carts, checkouts, "
            "currency, fetched_at) SELECT gen_random_uuid(), organization_id, id, :day, "
            "'landing_page', :page, :page, :n, 0, 0, 0, 0, :b, 0, :v, :c, :k, currency, now() "
            "FROM analytics_properties WHERE id = :prop"
        ),
        {
            "prop": prop,
            "day": day,
            "page": page,
            "n": n,
            "v": views,
            "c": carts,
            "k": checkouts,
            "b": buys,
        },
    )


def test_landing_pages_most_visits_first(owner, admin_engine):
    with admin_engine.begin() as db:
        _page(db, owner.prop, D5, "/products/gloves", 60, 50, 20, 8, 4)
        _page(db, owner.prop, D6, "/products/gloves", 40, 30, 10, 4, 2)
        _page(db, owner.prop, D5, "/", 150, 30, 5, 2, 1)
    data = _get(owner, "/landing-pages")
    assert [p["landing_page"] for p in data["items"]] == ["/", "/products/gloves"]
    gloves = data["items"][1]
    assert (_v(gloves["stages"]["landing_page_views"]), _v(gloves["stages"]["adds_to_cart"])) == (
        Decimal(100),
        Decimal(30),
    )
    assert gloves["steps"][0]["rate"]["value"] == "0.800000"
    assert (data["item_count"], data["items_missing"]) == (2, None)


def test_landing_pages_wait_for_the_reread(owner, admin_engine):
    with admin_engine.begin() as db:
        db.execute(text("UPDATE analytics_daily SET add_to_carts = NULL WHERE breakdown = 'total'"))
    data = _get(owner, "/landing-pages")
    assert (data["items"], data["items_missing"]["availability"]) == ([], "not_synchronized")


# ------------------------------------------------------------------ access
def test_every_member_can_read_and_outsiders_cannot(owner, make_client):
    viewer = make_client()
    email = f"v-{uuid.uuid4().hex[:6]}@example.com"
    viewer.signup(email)
    owner.invite_and_join(owner.org, viewer, email, "viewer")
    viewer.org = owner.org
    assert _get(viewer)["stages"]["impressions"]["value"] is not None
    outsider = make_client()
    outsider.signup(f"x-{uuid.uuid4().hex[:6]}@example.com")
    for path in ("", "/campaigns", "/landing-pages"):
        url = f"/organizations/{owner.org}/analytics/funnel{path}"
        assert outsider.get(url).status_code == 404
        assert owner.get(f"{url}?store_id={uuid.uuid4()}").status_code == 404
        assert owner.get(f"{url}?from=2026-10-07&to=2026-10-05").status_code == 422
