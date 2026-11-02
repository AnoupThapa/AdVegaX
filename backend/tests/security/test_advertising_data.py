"""Tenant isolation and integrity of the Phase 3 advertising tables (PHASE_03_PLAN §8, §13).

Rows are written as the runtime role with a tenant context, exactly as application code will,
so these tests exercise Row-Level Security, composite tenant keys and the grants together.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.security.test_rls import _ctx, app_engine, seeded  # noqa: F401  (fixtures)

AD_TABLES = (
    "ad_accounts",
    "ad_budgets",
    "ad_campaigns",
    "ad_groups",
    "ads",
    "ad_performance_daily",
    "ad_sync_state",
)

PERFORMANCE = (
    "INSERT INTO ad_performance_daily (id, organization_id, ad_account_id, level, entity_key, "
    "campaign_id, ad_group_id, ad_id, day, impressions, clicks, cost, conversions, "
    "conversion_value, currency, fetched_at) VALUES (gen_random_uuid(), :org, :account, :level, "
    ":entity, :campaign, :group, :ad, :day, :impressions, :clicks, :cost, :conversions, :value, "
    "'AUD', now())"
)


def _ad_resource(conn, org: str) -> str:
    _ctx(conn, org=org)
    return str(
        conn.execute(
            text("SELECT id FROM external_resources WHERE kind = 'ad_account' LIMIT 1")
        ).scalar_one()
    )


def _row(ids: dict[str, str], **values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "org": ids["org"],
        "account": ids["account"],
        "level": "account",
        "entity": "account",
        "campaign": None,
        "group": None,
        "ad": None,
        "day": "2026-10-05",
        "impressions": 1000,
        "clicks": 40,
        "cost": Decimal("12.345678"),
        "conversions": Decimal("2.5"),
        "value": Decimal("99.900000"),
    }
    return {**base, **values}


def _seed_account(conn, org: str, tag: str) -> dict[str, str]:
    """One ad account with a budget, campaign, ad group, ad, daily rows and sync state."""
    resource = _ad_resource(conn, org)
    ids = {k: str(uuid.uuid4()) for k in ("account", "budget", "campaign", "group", "ad")}
    params = {**ids, "org": org, "resource": resource, "tag": tag}
    for sql in (
        "INSERT INTO ad_accounts (id, organization_id, external_resource_id, provider, "
        "external_account_id, name, currency, timezone, platform_status) VALUES "
        "(:account, :org, :resource, 'fake', :tag, 'Ads', 'AUD', 'Australia/Sydney', 'active')",
        "INSERT INTO ad_budgets (id, organization_id, ad_account_id, external_budget_id, level, "
        "period, amount, currency) VALUES (:budget, :org, :account, 'b1', 'campaign', 'daily', "
        "50, 'AUD')",
        "INSERT INTO ad_campaigns (id, organization_id, ad_account_id, external_campaign_id, "
        "name, status, platform_type, budget_id) VALUES (:campaign, :org, :account, 'c1', "
        "'Gloves', 'active', 'SEARCH', :budget)",
        "INSERT INTO ad_groups (id, organization_id, campaign_id, external_ad_group_id, name, "
        "status) VALUES (:group, :org, :campaign, 'g1', 'Nitrile', 'active')",
        "INSERT INTO ads (id, organization_id, ad_group_id, external_ad_id, status) "
        "VALUES (:ad, :org, :group, 'a1', 'active')",
        "INSERT INTO ad_sync_state (ad_account_id, organization_id, import_progress) "
        "VALUES (:account, :org, 100)",
    ):
        conn.execute(text(sql), params)
    conn.execute(text(PERFORMANCE), _row({**ids, "org": org}))
    conn.execute(
        text(PERFORMANCE),
        _row({**ids, "org": org}, level="campaign", entity="c1", campaign=ids["campaign"]),
    )
    return ids


@pytest.fixture
def ads(seeded, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        a = _seed_account(conn, seeded["org_a"], "acct-a")
    with app_engine.begin() as conn:
        b = _seed_account(conn, seeded["org_b"], "acct-b")
    return {**seeded, "a": {**a, "org": seeded["org_a"]}, "b": {**b, "org": seeded["org_b"]}}


def test_no_context_sees_no_advertising_rows(ads, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        for table in AD_TABLES:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table


def test_each_tenant_sees_only_its_own_advertising_rows(ads, app_engine):  # noqa: F811
    for side in ("a", "b"):
        with app_engine.begin() as conn:
            _ctx(conn, org=ads[side]["org"])
            for table in AD_TABLES:
                orgs = conn.execute(text(f"SELECT DISTINCT organization_id FROM {table}")).all()
                assert [str(o[0]) for o in orgs] == [ads[side]["org"]], table


def test_cannot_change_or_delete_another_tenants_rows(ads, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=ads["org_a"])
        for table in AD_TABLES:
            column = "ad_account_id" if table == "ad_sync_state" else "id"
            changed = conn.execute(
                text(
                    f"UPDATE {table} SET organization_id = organization_id "
                    f"WHERE {column} = ANY(:ids)"
                ),
                {"ids": [uuid.UUID(v) for k, v in ads["b"].items() if k != "org"]},
            ).rowcount
            assert changed == 0, table
            deleted = conn.execute(
                text(f"DELETE FROM {table} WHERE organization_id = :b"), {"b": ads["org_b"]}
            ).rowcount
            assert deleted == 0, table


def test_cannot_insert_rows_for_another_tenant(ads, app_engine):  # noqa: F811
    with pytest.raises(DBAPIError, match="row-level security"), app_engine.begin() as conn:
        _ctx(conn, org=ads["org_a"])
        conn.execute(text(PERFORMANCE), _row(ads["b"], day="2026-10-06"))


@pytest.mark.parametrize(
    ("sql", "parent"),
    [
        (
            "INSERT INTO ad_campaigns (id, organization_id, ad_account_id, external_campaign_id, "
            "name, status) VALUES (gen_random_uuid(), :a, :p, 'x', 'x', 'active')",
            "account",
        ),
        (
            "INSERT INTO ad_campaigns (id, organization_id, ad_account_id, external_campaign_id, "
            "name, status, budget_id) VALUES (gen_random_uuid(), :a, :own, 'y', 'y', 'active', :p)",
            "budget",
        ),
        (
            "INSERT INTO ad_groups (id, organization_id, campaign_id, external_ad_group_id, name, "
            "status) VALUES (gen_random_uuid(), :a, :p, 'x', 'x', 'active')",
            "campaign",
        ),
        (
            "INSERT INTO ads (id, organization_id, ad_group_id, external_ad_id, status) "
            "VALUES (gen_random_uuid(), :a, :p, 'x', 'active')",
            "group",
        ),
    ],
)
def test_composite_keys_block_cross_tenant_references(ads, admin_engine, sql, parent):
    """Even a superuser bypassing RLS cannot attach org A rows to org B's parents."""
    with pytest.raises(IntegrityError), admin_engine.begin() as conn:
        conn.execute(
            text(sql), {"a": ads["org_a"], "p": ads["b"][parent], "own": ads["a"]["account"]}
        )


def test_money_and_conversions_are_exact_decimals(ads, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=ads["org_a"])
        cost, conversions = conn.execute(
            text("SELECT cost, conversions FROM ad_performance_daily WHERE level = 'account'")
        ).one()
    assert (cost, conversions) == (Decimal("12.345678"), Decimal("2.500000"))


def test_a_measure_the_platform_did_not_provide_is_null_not_zero(ads, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=ads["org_a"])
        conn.execute(text(PERFORMANCE), _row(ads["a"], day="2026-10-06", value=None))
        value = conn.execute(
            text("SELECT conversion_value FROM ad_performance_daily WHERE day = '2026-10-06'")
        ).scalar_one()
    assert value is None


def test_one_row_per_account_level_entity_and_day(ads, app_engine):  # noqa: F811
    with pytest.raises(IntegrityError), app_engine.begin() as conn:
        _ctx(conn, org=ads["org_a"])
        conn.execute(text(PERFORMANCE), _row(ads["a"]))  # same account row for 2026-10-05


@pytest.mark.parametrize(
    "values",
    [
        {
            "level": "campaign",
            "entity": "account",
        },  # entity key "account" is the account level only
        {"level": "account", "entity": "c1"},
        {"level": "keyword"},  # not a level
        {"impressions": -1},
        {"clicks": -5},
    ],
)
def test_invalid_performance_rows_are_refused(ads, app_engine, values):  # noqa: F811
    with pytest.raises(IntegrityError), app_engine.begin() as conn:
        _ctx(conn, org=ads["org_a"])
        conn.execute(text(PERFORMANCE), _row(ads["a"], day="2026-10-07", **values))


def test_removing_a_campaign_keeps_its_daily_rows(ads, app_engine):  # noqa: F811
    """History is never silently deleted: the daily row's link is optional and non-cascading."""
    with pytest.raises(IntegrityError), app_engine.begin() as conn:
        _ctx(conn, org=ads["org_a"])
        conn.execute(text("DELETE FROM ad_campaigns WHERE id = :c"), {"c": ads["a"]["campaign"]})


def test_unlinking_removes_an_accounts_data(ads, app_engine):  # noqa: F811
    """Deleting the ad account (erasure) removes everything below it in one step."""
    with app_engine.begin() as conn:
        _ctx(conn, org=ads["org_a"])
        conn.execute(text("UPDATE ad_campaigns SET budget_id = NULL"))
        conn.execute(text("UPDATE ad_performance_daily SET campaign_id = NULL"))
        conn.execute(text("DELETE FROM ad_accounts WHERE id = :a"), {"a": ads["a"]["account"]})
        for table in AD_TABLES:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
