"""The overview and channels API (task 6-05, PLAN §8, Q-6-1 … Q-6-6).

The golden dataset of ``test_metrics_engine.py`` (an AUD store, Google Ads in AUD, Meta in USD,
a Google Analytics property; 5 to 7 October 2026), read through the API with the exchange rates
stored as the daily task stores them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.api.test_metrics_engine import D5, D6, D7, Seed
from tests.helpers import connected

PERIOD = "?from=2026-10-05&to=2026-10-07"


@pytest.fixture
def rates(admin_engine):
    with admin_engine.begin() as db:
        for day, aud, usd in ((D5, "1.6", "1.0"), (D6, "1.65", "1.1")):
            for quote, rate in (("AUD", aud), ("USD", usd)):
                db.execute(
                    text(
                        "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                        "VALUES ('ecb', 'EUR', :q, :d, :r, now())"
                    ),
                    {"q": quote, "d": day, "r": Decimal(rate)},
                )


@pytest.fixture
def owner(make_client, admin_engine, rates):
    c = make_client()
    c.signup(f"overview-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    c.seed = Seed(admin_engine, c.org, connected(c, c.org))
    c.store_id = c.seed.store(days={D5: ("1000.00", 10, "400.00"), D6: ("500.50", 5, "200.20")})
    c.seed.ad_account("google_ads", "AUD", {D5: "100.00", D6: "50.00", D7: "0"})
    c.seed.ad_account("meta_ads", "USD", {D5: "20.00", D6: "10.00", D7: "5.00"})
    c.seed.analytics_property({D5: 300, D6: 200, D7: 100})
    return c


def _get(c, path, query=PERIOD):
    response = c.get(f"/organizations/{c.org}/analytics/{path}{query}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _value(fig):
    return None if fig["value"] is None else Decimal(fig["value"])


# ------------------------------------------------------------------ the overview
def test_the_overview_gives_the_golden_figures_with_their_context(owner):
    data = _get(owner, "overview")
    assert (data["definition_version"], data["reporting_currency"], data["reporting_timezone"]) == (
        "analytics-v1",
        "AUD",
        "Australia/Sydney",
    )
    assert (data["from_day"], data["to_day"], data["store_id"]) == (
        "2026-10-05",
        "2026-10-07",
        None,
    )
    t = data["totals"]
    assert _value(t["net_sales"]) == Decimal("1500.50")
    assert _value(t["ad_spend"]) == Decimal("204.50")
    assert _value(t["gross_profit"]) == Decimal("900.30")
    assert _value(t["profit_after_ad_spend"]) == Decimal("695.80")
    assert t["blended_roas"]["value"] == "7.337408"
    assert t["cost_per_order"]["value"] == "13.633333"
    assert t["store_conversion_rate"]["value"] == "0.025000"
    assert t["shipping_cost"] == {
        "value": None,
        "availability": "unsupported",
        "reason": "not_provided_by_platform",
    }
    assert [d["day"] for d in data["days"]] == ["2026-10-05", "2026-10-06", "2026-10-07"]
    assert _value(data["days"][2]["figures"]["ad_spend"]) == Decimal("7.50")
    kinds = sorted((s["kind"], s["provider"]) for s in data["sources"])
    assert kinds == [
        ("ad_account", "google_ads"),
        ("ad_account", "meta_ads"),
        ("analytics_property", "fake"),
        ("store", "fake"),
    ]
    assert all(s["updated_at"] for s in data["sources"])
    assert data["conversions"] == [
        {
            "currency": "USD",
            "rate_sources": ["ecb"],
            "first_rate_date": "2026-10-05",
            "last_rate_date": "2026-10-06",  # the 7th uses the 6th's rate
            "days_without_rate": 0,
        }
    ]
    assert data["notes"] == []
    keys = {d["key"] for d in data["definitions"]}
    assert keys == set(t) and "net_sales" in keys
    definition = next(d for d in data["definitions"] if d["key"] == "profit_after_ad_spend")
    assert definition["note"].startswith("Before shipping costs")


def test_another_reporting_currency_converts_everything(owner):
    owner.patch(f"/organizations/{owner.org}", {"default_currency": "USD"})
    data = _get(owner, "overview", "?from=2026-10-05&to=2026-10-05")
    assert data["reporting_currency"] == "USD"
    assert _value(data["totals"]["net_sales"]) == Decimal("625")
    assert [c["currency"] for c in data["conversions"]] == ["AUD"]


def test_a_missing_rate_is_named_and_counted(owner):
    data = _get(owner, "overview", "?from=2026-10-05&to=2026-10-20")
    assert data["totals"]["ad_spend"]["availability"] in ("not_synchronized", "unavailable")
    (usd,) = data["conversions"]
    assert usd["days_without_rate"] > 0  # more than 7 days after the last published rate


def test_differing_time_zones_are_noted(owner):
    owner.patch(f"/organizations/{owner.org}", {"default_timezone": "America/Los_Angeles"})
    assert _get(owner, "overview")["notes"] == ["time_zones_differ"]


def test_the_default_period_is_the_last_30_days(owner):
    data = _get(owner, "overview", "")
    assert (data["from_day"], data["to_day"]) == ("2026-09-15", "2026-10-14")
    assert len(data["days"]) == 30


@pytest.mark.parametrize(
    "query", ["?from=2026-10-07&to=2026-10-05", "?from=2020-01-01&to=2026-10-05", "?from=x"]
)
def test_invalid_periods_are_refused(owner, query):
    for path in ("overview", "channels"):
        assert owner.get(f"/organizations/{owner.org}/analytics/{path}{query}").status_code == 422


def test_one_store_and_a_store_of_another_organization(owner, make_client, admin_engine):
    data = _get(owner, "overview", f"{PERIOD}&store_id={owner.store_id}")
    assert data["store_id"] == owner.store_id
    assert _value(data["totals"]["ad_spend"]) == Decimal("204.50")  # the only store
    other = make_client()
    other.signup(f"o-{uuid.uuid4().hex[:6]}@example.com")
    other.org = other.create_org("Other")["id"]
    foreign = Seed(admin_engine, other.org, connected(other, other.org)).store()
    for store in (foreign, str(uuid.uuid4())):
        response = owner.get(f"/organizations/{owner.org}/analytics/overview?store_id={store}")
        assert response.status_code == 404


def test_every_member_can_read_and_outsiders_cannot(owner, make_client):
    viewer = make_client()
    email = f"v-{uuid.uuid4().hex[:6]}@example.com"
    viewer.signup(email)
    owner.invite_and_join(owner.org, viewer, email, "viewer")
    viewer.org = owner.org
    assert _get(viewer, "overview")["totals"]["net_sales"]["value"] is not None
    outsider = make_client()
    outsider.signup(f"x-{uuid.uuid4().hex[:6]}@example.com")
    for path in ("overview", "channels"):
        assert outsider.get(f"/organizations/{owner.org}/analytics/{path}").status_code == 404


def test_an_empty_organization_says_what_is_missing(make_client):
    c = make_client()
    c.signup(f"empty-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Empty")["id"]
    t = _get(c, "overview")["totals"]
    assert t["net_sales"] == {"value": None, "availability": "unavailable", "reason": "no_store"}
    assert t["ad_spend"]["reason"] == "no_ad_account"
    assert t["sessions"]["reason"] == "no_analytics_property"


# ------------------------------------------------------------------ channels
def test_each_platform_reports_its_own_figures_never_added_across(owner, admin_engine):
    with admin_engine.begin() as db:  # the platforms' own conversions and values
        db.execute(
            text(
                "UPDATE ad_performance_daily SET clicks = 10, impressions = 1000, conversions = 2, "
                "conversion_value = 80 WHERE day = :d"
            ),
            {"d": D5},
        )
    data = _get(owner, "channels")
    assert _value(data["ad_spend"]) == Decimal("204.50")
    google, meta = data["platforms"]
    assert (google["provider"], google["source"], google["ad_accounts"]) == (
        "google_ads",
        "platform_reported",
        1,
    )
    assert _value(google["figures"]["spend"]) == Decimal("150.00")
    assert _value(google["figures"]["conversion_value"]) == Decimal("80")
    assert google["figures"]["platform_roas"]["value"] == "0.533333"  # 80 / 150
    assert _value(meta["figures"]["spend"]) == Decimal("54.50")
    assert _value(meta["figures"]["conversion_value"]) == Decimal("128.0")  # 80 USD x 1.6
    assert _value(meta["figures"]["conversions"]) == Decimal(2)
    # No total of platform conversions or values across platforms ("conversions" lists FX).
    assert not {"conversion_value", "platform_roas"} & set(data)
    assert all("currency" in c for c in data["conversions"])


def test_google_analytics_channels_most_sessions_first(owner, admin_engine):
    with admin_engine.begin() as db:
        prop = db.execute(text("SELECT id, organization_id FROM analytics_properties")).one()
        for day, channel, sessions in (
            (D5, "Organic Search", 200),
            (D5, "Paid Search", 100),
            (D6, "Organic Search", 120),
            (D7, "Paid Search", 300),
        ):
            db.execute(
                text(
                    "INSERT INTO analytics_daily (id, organization_id, property_id, day, "
                    "breakdown, dimension_key, channel_group, sessions, engaged_sessions, "
                    "total_users, new_users, key_events, purchases, purchase_revenue, currency, "
                    "fetched_at) VALUES (gen_random_uuid(), :org, :prop, :day, 'channel', :ch, "
                    ":ch, :n, 10, 5, 1, 1, 1, 10, 'AUD', now())"
                ),
                {
                    "org": prop.organization_id,
                    "prop": prop.id,
                    "day": day,
                    "ch": channel,
                    "n": sessions,
                },
            )
    data = _get(owner, "channels")
    assert [c["channel"] for c in data["analytics_channels"]] == ["Paid Search", "Organic Search"]
    paid = data["analytics_channels"][0]["figures"]
    assert (_value(paid["sessions"]), _value(paid["purchase_revenue"])) == (
        Decimal(400),
        Decimal(20),
    )
    assert paid["engagement_rate"]["value"] == "0.050000"
    assert data["analytics_channels_missing"] is None
    keys = {d["key"] for d in data["definitions"]}
    assert keys == set(data["platforms"][0]["figures"]) | set(paid)


def test_channels_for_a_period_not_read_say_so(owner):
    data = _get(owner, "channels", "?from=2025-09-01&to=2025-09-30")
    assert data["analytics_channels"] == []
    assert data["analytics_channels_missing"]["availability"] == "not_synchronized"
    google, _meta = data["platforms"]
    assert google["figures"]["spend"]["availability"] == "not_synchronized"


def test_no_platforms_and_no_property(make_client):
    c = make_client()
    c.signup(f"none-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("None")["id"]
    data = _get(c, "channels")
    assert (data["platforms"], data["analytics_channels"]) == ([], [])
    assert data["analytics_channels_missing"]["reason"] == "no_analytics_property"
    assert data["ad_spend"]["reason"] == "no_ad_account"
