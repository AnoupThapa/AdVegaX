"""Tenant isolation and integrity of the Phase 5 analytics tables (PHASE_05_PLAN §8, §13).

Rows are written as the runtime role with a tenant context, exactly as application code will,
so these tests exercise Row-Level Security, composite tenant keys and the grants together. The
scheduler's system role reads four columns of ``analytics_properties`` and nothing else.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from tests.security.test_rls import _ctx, app_engine, seeded  # noqa: F401  (fixtures)

TABLES = ("analytics_properties", "analytics_daily", "analytics_sync_state")

DAILY = (
    "INSERT INTO analytics_daily (id, organization_id, property_id, day, breakdown, "
    "dimension_key, channel_group, sessions, engaged_sessions, total_users, new_users, "
    "key_events, purchases, purchase_revenue, currency, fetched_at) VALUES (gen_random_uuid(), "
    ":org, :property, :day, :breakdown, :key, :channel, :sessions, :engaged, :users, :new, "
    ":key_events, :purchases, :revenue, 'AUD', now())"
)


def _row(ids: dict[str, str], **values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "org": ids["org"],
        "property": ids["property"],
        "day": "2026-10-05",
        "breakdown": "total",
        "key": "total",
        "channel": None,
        "sessions": 120,
        "engaged": 80,
        "users": 95,
        "new": 40,
        "key_events": Decimal("7.5"),
        "purchases": 3,
        "revenue": Decimal("189.900000"),
    }
    return {**base, **values}


def _seed_property(conn, org: str, connection: str, tag: str) -> dict[str, str]:
    """One GA4-like property with a total and a channel row and its sync state."""
    _ctx(conn, org=org)
    ids = {"property": str(uuid.uuid4()), "resource": str(uuid.uuid4())}
    params = {**ids, "org": org, "conn": connection, "tag": tag}
    for sql in (
        "INSERT INTO external_resources (id, organization_id, connection_id, kind, provider, "
        "external_id, discovered_at, last_seen_at) VALUES (:resource, :org, :conn, "
        "'analytics_property', 'fake', :tag, now(), now())",
        "INSERT INTO analytics_properties (id, organization_id, external_resource_id, provider, "
        "external_property_id, name, account_name, currency, timezone, platform_status) VALUES "
        "(:property, :org, :resource, 'fake', :tag, 'Shop', 'Eve Zone', 'AUD', "
        "'Australia/Sydney', 'active')",
        "INSERT INTO analytics_sync_state (property_id, organization_id, import_progress) "
        "VALUES (:property, :org, 100)",
    ):
        conn.execute(text(sql), params)
    conn.execute(text(DAILY), _row({**ids, "org": org}))
    conn.execute(
        text(DAILY),
        _row({**ids, "org": org}, breakdown="channel", key="Paid Search", channel="Paid Search"),
    )
    return ids


@pytest.fixture
def analytics(seeded, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        a = _seed_property(conn, seeded["org_a"], seeded["conn_a"], "properties/111")
    with app_engine.begin() as conn:
        b = _seed_property(conn, seeded["org_b"], seeded["conn_b"], "properties/222")
    return {**seeded, "a": {**a, "org": seeded["org_a"]}, "b": {**b, "org": seeded["org_b"]}}


def test_no_context_sees_no_analytics_rows(analytics, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        for table in TABLES:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table


def test_each_tenant_sees_only_its_own_analytics_rows(analytics, app_engine):  # noqa: F811
    for side in ("a", "b"):
        with app_engine.begin() as conn:
            _ctx(conn, org=analytics[side]["org"])
            for table in TABLES:
                orgs = conn.execute(text(f"SELECT DISTINCT organization_id FROM {table}")).all()
                assert [str(o[0]) for o in orgs] == [analytics[side]["org"]], table


def test_cannot_change_or_delete_another_tenants_rows(analytics, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        for table in TABLES:
            column = "property_id" if table != "analytics_properties" else "id"
            changed = conn.execute(
                text(f"UPDATE {table} SET organization_id = organization_id WHERE {column} = :p"),
                {"p": analytics["b"]["property"]},
            ).rowcount
            assert changed == 0, table
            deleted = conn.execute(
                text(f"DELETE FROM {table} WHERE organization_id = :b"), {"b": analytics["org_b"]}
            ).rowcount
            assert deleted == 0, table


def test_cannot_insert_rows_for_another_tenant(analytics, app_engine):  # noqa: F811
    with pytest.raises(DBAPIError, match="row-level security"), app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        conn.execute(text(DAILY), _row({**analytics["b"], "org": analytics["org_b"]}))


def test_composite_keys_block_cross_tenant_references(analytics, app_engine):  # noqa: F811
    """Even inside its own tenant, A cannot attach rows to B's property."""
    with pytest.raises(IntegrityError), app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        conn.execute(
            text(DAILY),
            _row({"org": analytics["org_a"], "property": analytics["b"]["property"]}),
        )


def test_revenue_and_key_events_are_exact(analytics, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        revenue, key_events = conn.execute(
            text(
                "SELECT purchase_revenue, key_events FROM analytics_daily WHERE breakdown = 'total'"
            )
        ).one()
    assert (revenue, key_events) == (Decimal("189.900000"), Decimal("7.500000"))


def test_a_measure_the_platform_did_not_provide_is_null_not_zero(analytics, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        conn.execute(
            text(DAILY),
            _row({**analytics["a"], "org": analytics["org_a"]}, day="2026-10-06", revenue=None),
        )
        value = conn.execute(
            text("SELECT purchase_revenue FROM analytics_daily WHERE day = '2026-10-06'")
        ).scalar_one()
    assert value is None


def test_one_row_per_property_view_value_and_day(analytics, app_engine):  # noqa: F811
    with pytest.raises(IntegrityError), app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        conn.execute(text(DAILY), _row({**analytics["a"], "org": analytics["org_a"]}))


@pytest.mark.parametrize(
    "values",
    [
        {"breakdown": "page", "key": "x"},  # not a known view
        {"breakdown": "total", "key": "Paid Search"},  # a total must use the total key
        {"breakdown": "channel", "key": "total"},
        {"sessions": -1},
        {"users": -5},
        {"revenue": Decimal("-0.01")},
    ],
)
def test_invalid_daily_rows_are_refused(analytics, app_engine, values):  # noqa: F811
    with pytest.raises(IntegrityError), app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        conn.execute(
            text(DAILY),
            _row({**analytics["a"], "org": analytics["org_a"]}, day="2026-10-07", **values),
        )


def test_quality_flags_default_to_false(analytics, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        flags = conn.execute(
            text(
                "SELECT DISTINCT other_row, thresholded, sampled, truncated, source "
                "FROM analytics_daily"
            )
        ).all()
    assert flags == [(False, False, False, False, "platform_reported")]


def test_removing_a_property_removes_its_figures_and_state(analytics, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=analytics["org_a"])
        conn.execute(
            text("DELETE FROM analytics_properties WHERE id = :p"),
            {"p": analytics["a"]["property"]},
        )
        for table in TABLES:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table


def test_the_scheduler_reads_four_columns_of_properties_only(analytics, settings):
    system = create_engine(settings.DATABASE_URL_SYSTEM.get_secret_value())
    try:
        with system.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, organization_id, provider, first_import_completed_at "
                    "FROM analytics_properties"
                )
            ).all()
            assert len(rows) == 2  # every organization's, ids only
        for column in ("name", "currency", "account_name", "external_property_id"):
            with pytest.raises(ProgrammingError, match="permission denied"), system.begin() as conn:
                conn.execute(text(f"SELECT {column} FROM analytics_properties"))
        for table in ("analytics_daily", "analytics_sync_state"):
            with pytest.raises(ProgrammingError, match="permission denied"), system.begin() as conn:
                conn.execute(text(f"SELECT count(*) FROM {table}"))
    finally:
        system.dispose()
