"""The browser tests' simulated-store helper (task 2A-11) works and refuses deployed settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.core.settings import Environment

from tests import e2e_shopify_store as seed
from tests.api.test_strategy_context import shop  # noqa: F401  (fixture)


def test_connects_and_imports_a_simulated_store(make_client, admin_engine, capsys):
    owner = make_client()
    owner.signup("seed-owner@example.com")
    org = owner.create_org("Seed Co")["id"]
    code = seed.main(
        ["--email", "seed-owner@example.com", "--organization", org, "--shop", "E2E-1"]
    )
    assert code == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    (store,) = owner.get(f"/organizations/{org}/stores").json()["data"]
    assert store["id"] == out["store_id"]
    assert (store["domain"], store["status"], store["linked"]) == (
        "e2e-1.myshopify.com",
        "active",
        True,
    )
    products = owner.get(f"/organizations/{org}/stores/{store['id']}/products").json()["data"]
    assert len(products["items"]) == 2


def test_wrong_password_fails_cleanly(make_client, capsys):
    owner = make_client()
    owner.signup("seed-two@example.com")
    org = owner.create_org("Seed Two")["id"]
    args = ["--email", "seed-two@example.com", "--organization", org, "--shop", "e2e-2"]
    assert seed.main([*args, "--password", "wrong password here"]) == 1
    assert "sign-in failed" in capsys.readouterr().err


def test_refuses_deployed_environments(settings, monkeypatch, capsys):
    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(seed, "get_settings", lambda: deployed)
    assert seed.main(["--email", "a@example.com", "--organization", "x", "--shop", "s"]) == 1
    assert "deployed" in capsys.readouterr().err


def test_sample_orders_are_moved_to_recent_days():
    now = datetime(2027, 3, 10, 12, tzinfo=UTC)
    text = json.dumps(seed.recent_orders(now))
    assert seed.ORDER_AT not in text and seed.REFUND_AT not in text
    assert "2027-03-07T12:00:00Z" in text and "2027-03-09T12:00:00Z" in text


# ------------------------------------------------------------------ WooCommerce (2B-09)
def test_connects_and_imports_a_simulated_woocommerce_store(make_client, capsys):
    from tests import e2e_woocommerce_store as woo

    owner = make_client()
    owner.signup("seed-woo@example.com")
    org = owner.create_org("Seed Woo")["id"]
    args = ["--email", "seed-woo@example.com", "--organization", org, "--host", "E2E-W.example.com"]
    assert woo.main([*args, "--cogs-off"]) == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    (store,) = owner.get(f"/organizations/{org}/stores").json()["data"]
    assert store["id"] == out["store_id"]
    assert (store["provider"], store["site_url"], store["status"]) == (
        "woocommerce",
        "https://e2e-w.example.com",
        "active",
    )
    assert store["health"]["code"] == "cost_of_goods_off"
    products = owner.get(f"/organizations/{org}/stores/{store['id']}/products").json()["data"]
    assert len(products["items"]) == 2


def test_the_woocommerce_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_woocommerce_store as woo

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(woo, "get_settings", lambda: deployed)
    assert woo.main(["--email", "a@example.com", "--organization", "x", "--host", "h.com"]) == 1
    assert "deployed" in capsys.readouterr().err


def test_the_woocommerce_sample_is_moved_to_recent_days():
    from tests import e2e_woocommerce_store as woo
    from tests.woocommerce_sim import WooStore

    store = woo.recent_store(WooStore("s.example.com"), datetime(2027, 3, 10, 12, tzinfo=UTC))
    text = json.dumps([*store.orders, *store.refunds])
    assert woo.ORDER_AT not in text and woo.REFUND_AT not in text
    assert "2027-03-07T12:00:00" in text and "2027-03-09T12:00:00" in text


def test_the_woocommerce_seed_replaces_the_real_provider_when_switched_on(
    make_client, settings, monkeypatch, capsys
):
    from tests import e2e_woocommerce_store as woo

    monkeypatch.setattr(
        woo, "get_settings", lambda: settings.model_copy(update={"WOOCOMMERCE_ENABLED": True})
    )
    owner = make_client()
    owner.signup("seed-woo-on@example.com")
    org = owner.create_org("Seed Woo On")["id"]
    args = ["--email", "seed-woo-on@example.com", "--organization", org, "--host", "on.example.com"]
    assert woo.main(args) == 0, capsys.readouterr().err


# ------------------------------------------------------------------ Google Ads (3-10)
def test_connects_and_imports_simulated_google_ads_accounts(make_client, admin_engine, capsys):
    from tests import e2e_google_ads as ads

    owner = make_client()
    owner.signup("seed-ads@example.com")
    org = owner.create_org("Seed Ads")["id"]
    assert ads.main(["--email", "seed-ads@example.com", "--organization", org]) == 0, (
        capsys.readouterr().err
    )
    out = json.loads(capsys.readouterr().out)
    accounts = owner.get(f"/organizations/{org}/ad-accounts").json()["data"]
    assert {a["external_account_id"] for a in accounts} == {ads.AU, ads.NZ}
    au = next(a for a in accounts if a["id"] == out["ad_account_id"])
    assert (au["status"], au["linked"], au["external_account_id"]) == ("active", True, ads.AU)
    # The helper runs on the real clock (the test API on a fixed one): read its two days.
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    search_day, pmax_day = ads.recent_days(
        datetime.now(UTC).astimezone(ZoneInfo("Australia/Sydney")).date()
    )
    from sqlalchemy import text

    with admin_engine.begin() as db:
        rows = db.execute(
            text(
                "SELECT day, clicks, impressions FROM ad_performance_daily "
                "WHERE level = 'account' AND ad_account_id = :a AND (clicks > 0 OR impressions > 0)"
            ),
            {"a": au["id"]},
        ).all()
    assert {(str(d), c, i) for d, c, i in rows} == {(search_day, 34, 1200), (pmax_day, 0, 500)}


def test_the_google_ads_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_google_ads as ads

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(ads, "get_settings", lambda: deployed)
    assert ads.main(["--email", "a@example.com", "--organization", "x"]) == 1
    assert "deployed" in capsys.readouterr().err


def test_the_google_ads_sample_is_moved_to_recent_days():
    from datetime import date

    from tests import e2e_google_ads as ads

    assert ads.recent_days(date(2027, 3, 10)) == ("2027-03-07", "2027-02-18")


def test_the_google_ads_seed_replaces_the_real_provider_when_switched_on(
    make_client, settings, monkeypatch, capsys
):
    from pydantic import SecretStr

    from tests import e2e_google_ads as ads

    switched_on = settings.model_copy(
        update={
            "GOOGLE_ADS_ENABLED": True,
            "GOOGLE_ADS_CLIENT_ID": "ci-not-a-real-client.apps.googleusercontent.com",
            "GOOGLE_ADS_CLIENT_SECRET": SecretStr("ci-not-a-secret"),
            "GOOGLE_ADS_DEVELOPER_TOKEN": SecretStr("ci-not-a-token"),
        }
    )
    monkeypatch.setattr(ads, "get_settings", lambda: switched_on)
    owner = make_client()
    owner.signup("seed-ads-on@example.com")
    org = owner.create_org("Seed Ads On")["id"]
    assert ads.main(["--email", "seed-ads-on@example.com", "--organization", org]) == 0, (
        capsys.readouterr().err
    )


def test_the_google_ads_seed_reports_a_wrong_password(make_client, capsys):
    from tests import e2e_google_ads as ads

    owner = make_client()
    owner.signup("seed-ads-pw@example.com")
    org = owner.create_org("Seed Ads Pw")["id"]
    args = ["--email", "seed-ads-pw@example.com", "--organization", org]
    assert ads.main([*args, "--password", "wrong password here"]) == 1
    assert "sign-in failed" in capsys.readouterr().err


# ------------------------------------------------------------------ Meta (4-08)
def test_connects_and_imports_a_simulated_meta_ad_account(make_client, admin_engine, capsys):
    from datetime import UTC, date, datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import text

    from tests import e2e_meta_ads as meta

    owner = make_client()
    owner.signup("seed-meta@example.com")
    org = owner.create_org("Seed Meta")["id"]
    assert meta.main(["--email", "seed-meta@example.com", "--organization", org]) == 0, (
        capsys.readouterr().err
    )
    out = json.loads(capsys.readouterr().out)
    (account,) = owner.get(f"/organizations/{org}/ad-accounts").json()["data"]
    assert (account["id"], account["provider"], account["status"]) == (
        out["ad_account_id"],
        "meta_ads",
        "active",
    )
    resources = owner.get(f"/organizations/{org}/connections/{out['connection_id']}/resources")
    reasons = {r["external_id"]: r["unavailable_reason"] for r in resources.json()["data"]}
    assert reasons == {meta.AU: None, meta.OWN: None, meta.UNPAID: "account_unsettled"}
    # The helper runs on the real clock (the test API on a fixed one): read its day and the
    # sign-in's end date from the database.
    today = datetime.now(UTC).astimezone(ZoneInfo("Australia/Sydney")).date()
    sale_day = date.fromordinal(today.toordinal() - 3)
    with admin_engine.begin() as db:
        rows = db.execute(
            text(
                "SELECT day, clicks, impressions FROM ad_performance_daily "
                "WHERE level = 'account' AND ad_account_id = :a AND impressions > 0"
            ),
            {"a": account["id"]},
        ).all()
        (expires,) = db.execute(
            text("SELECT token_expires_at FROM external_connection_credentials")
        ).scalars()
    assert {(d, c, i) for d, c, i in rows} == {(sale_day, 36, 2100)}
    left = expires - datetime.now(UTC)
    assert meta.SIGN_IN_DAYS - 1 < left.total_seconds() / 86400 <= meta.SIGN_IN_DAYS


def test_the_meta_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_meta_ads as meta

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(meta, "get_settings", lambda: deployed)
    assert meta.main(["--email", "a@example.com", "--organization", "x"]) == 1
    assert "deployed" in capsys.readouterr().err


def test_the_meta_seed_replaces_the_real_provider_when_switched_on(
    make_client, settings, monkeypatch, capsys
):
    from pydantic import SecretStr

    from tests import e2e_meta_ads as meta

    switched_on = settings.model_copy(
        update={
            "META_ADS_ENABLED": True,
            "META_APP_ID": "1234567890",
            "META_APP_SECRET": SecretStr("ci-not-a-secret"),
            "META_LOGIN_CONFIG_ID": "555555555",
        }
    )
    monkeypatch.setattr(meta, "get_settings", lambda: switched_on)
    owner = make_client()
    owner.signup("seed-meta-on@example.com")
    org = owner.create_org("Seed Meta On")["id"]
    assert meta.main(["--email", "seed-meta-on@example.com", "--organization", org]) == 0, (
        capsys.readouterr().err
    )


def test_the_meta_seed_reports_a_wrong_password(make_client, capsys):
    from tests import e2e_meta_ads as meta

    owner = make_client()
    owner.signup("seed-meta-pw@example.com")
    org = owner.create_org("Seed Meta Pw")["id"]
    args = ["--email", "seed-meta-pw@example.com", "--organization", org]
    assert meta.main([*args, "--password", "wrong password here"]) == 1
    assert "sign-in failed" in capsys.readouterr().err


# ------------------------------------------------------------------ Google Analytics (5-09)
def test_connects_and_imports_a_simulated_ga4_property(make_client, admin_engine, capsys):
    from datetime import date
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    from sqlalchemy import text

    from tests import e2e_google_analytics as ga

    owner = make_client()
    owner.signup("seed-ga@example.com")
    org = owner.create_org("Seed GA")["id"]
    assert ga.main(["--email", "seed-ga@example.com", "--organization", org]) == 0, (
        capsys.readouterr().err
    )
    out = json.loads(capsys.readouterr().out)
    (prop,) = owner.get(f"/organizations/{org}/analytics-properties").json()["data"]
    assert (prop["id"], prop["provider"], prop["status"], prop["account_name"]) == (
        out["property_id"],
        "google_analytics",
        "active",
        "Eve Zone",
    )
    resources = owner.get(f"/organizations/{org}/connections/{out['connection_id']}/resources")
    reasons = {r["external_id"]: r["unavailable_reason"] for r in resources.json()["data"]}
    assert reasons == {ga.AU: None, ga.NZ: None, ga.NO_DETAILS: "property_details_missing"}
    # The helper runs on the real clock (the test API on a fixed one): read its day from the
    # database.
    today = datetime.now(UTC).astimezone(ZoneInfo("Australia/Sydney")).date()
    busy = date.fromordinal(today.toordinal() - 3)
    with admin_engine.begin() as db:
        (row,) = db.execute(
            text(
                "SELECT sessions, total_users, purchase_revenue, thresholded FROM analytics_daily "
                "WHERE breakdown = 'total' AND day = :d"
            ),
            {"d": busy},
        ).all()
    assert tuple(row) == (150, 118, Decimal("310.400000"), True)


def test_the_ga4_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_google_analytics as ga

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(ga, "get_settings", lambda: deployed)
    assert ga.main(["--email", "a@example.com", "--organization", "x"]) == 1
    assert "deployed" in capsys.readouterr().err


def test_the_ga4_seed_replaces_the_real_provider_when_switched_on(
    make_client, settings, monkeypatch, capsys
):
    from pydantic import SecretStr

    from tests import e2e_google_analytics as ga

    switched_on = settings.model_copy(
        update={
            "GOOGLE_ANALYTICS_ENABLED": True,
            "GOOGLE_ADS_CLIENT_ID": "ci-not-a-real-client.apps.googleusercontent.com",
            "GOOGLE_ADS_CLIENT_SECRET": SecretStr("ci-not-a-secret"),
        }
    )
    monkeypatch.setattr(ga, "get_settings", lambda: switched_on)
    owner = make_client()
    owner.signup("seed-ga-on@example.com")
    org = owner.create_org("Seed GA On")["id"]
    assert ga.main(["--email", "seed-ga-on@example.com", "--organization", org]) == 0, (
        capsys.readouterr().err
    )


def test_the_ga4_seed_reports_a_wrong_password(make_client, capsys):
    from tests import e2e_google_analytics as ga

    owner = make_client()
    owner.signup("seed-ga-pw@example.com")
    org = owner.create_org("Seed GA Pw")["id"]
    args = ["--email", "seed-ga-pw@example.com", "--organization", org]
    assert ga.main([*args, "--password", "wrong password here"]) == 1
    assert "sign-in failed" in capsys.readouterr().err


# ------------------------------------------------------------------ campaign strategy (8-07)
def test_makes_a_strategy_with_the_ai_simulator(shop, admin_engine, capsys):  # noqa: F811
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import text

    from tests import e2e_strategy as strategy_seed

    # The helper runs on the real clock: rates for its recent days (1 USD = 1.6 AUD).
    today = datetime.now(UTC).date()
    with admin_engine.begin() as db:
        for back in range(10):
            day = date.fromordinal(today.toordinal() - back)
            for quote, rate in (("AUD", "1.6"), ("USD", "1.0")):
                db.execute(
                    text(
                        "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                        "VALUES ('ecb', 'EUR', :q, :d, :r, now()) ON CONFLICT DO NOTHING"
                    ),
                    {"q": quote, "d": day, "r": Decimal(rate)},
                )
    args = ["--email", shop.email, "--organization", shop.org]
    assert strategy_seed.main(args) == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    data = shop.get(f"/organizations/{shop.org}/ai/campaign-strategies/{out['strategy_id']}")
    data = data.json()["data"]
    assert (data["status"], data["product_title"]) == ("draft", "Nitrile gloves")
    assert sorted(data["budget_amounts"]) == ["google_ads", "meta_ads"]
    assert all(e is not None and e["value"] is not None for e in data["evidence"].values())


def test_the_strategy_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_strategy as strategy_seed

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(strategy_seed, "get_settings", lambda: deployed)
    assert strategy_seed.main(["--email", "a@example.com", "--organization", "x"]) == 1
    assert "deployed" in capsys.readouterr().err
