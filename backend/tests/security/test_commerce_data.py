"""Tenant isolation and integrity of the Phase 2A commerce tables (PHASE_02A_PLAN §8, §13).

Rows are written as the runtime role with a tenant context, exactly as application code will,
so these tests exercise Row-Level Security, composite tenant keys and the new grants together.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.security.test_rls import _ctx, app_engine, seeded  # noqa: F401  (fixtures)

COMMERCE_TABLES = (
    "stores",
    "products",
    "product_variants",
    "product_cost_history",
    "orders",
    "order_items",
    "sales_entries",
    "refunds",
    "refund_items",
    "commerce_sync_state",
    "financial_daily",
)


def _store_resource(conn, org: str) -> str:
    _ctx(conn, org=org)
    return str(
        conn.execute(
            text("SELECT id FROM external_resources WHERE kind = 'store' LIMIT 1")
        ).scalar_one()
    )


def _seed_store(conn, org: str, tag: str) -> dict[str, str]:
    """One store with a product, variant, cost, order, line, sale, refund and daily row."""
    resource = _store_resource(conn, org)
    ids = {k: str(uuid.uuid4()) for k in ("store", "product", "variant", "order", "item", "refund")}
    params = {**ids, "org": org, "resource": resource, "tag": tag, "domain": f"{tag}.example"}
    for sql in (
        "INSERT INTO stores (id, organization_id, external_resource_id, provider, "
        "external_store_id, domain, currency, timezone) VALUES "
        "(:store, :org, :resource, 'fake', :tag, :domain, 'AUD', 'Australia/Sydney')",
        "INSERT INTO products (id, organization_id, store_id, external_product_id, title, status) "
        "VALUES (:product, :org, :store, 'p1', 'Gloves', 'active')",
        "INSERT INTO product_variants (id, organization_id, store_id, product_id, "
        "external_variant_id, price) VALUES (:variant, :org, :store, :product, 'v1', 12.500000)",
        "INSERT INTO product_cost_history (id, organization_id, variant_id, unit_cost, currency, "
        "effective_from, source, recorded_at) VALUES "
        "(gen_random_uuid(), :org, :variant, 4.123456, 'AUD', now(), 'platform', now())",
        "INSERT INTO orders (id, organization_id, store_id, external_order_id, currency, "
        "ordered_at, total_amount) VALUES (:order, :org, :store, 'o1', 'AUD', now(), 25)",
        "INSERT INTO order_items (id, organization_id, order_id, variant_id, "
        "external_line_item_id, quantity, unit_price, unit_cost, cost_source) VALUES "
        "(:item, :org, :order, :variant, 'l1', 2, 12.5, 4.123456, 'order_time')",
        "INSERT INTO sales_entries (id, organization_id, store_id, order_id, order_item_id, "
        "external_agreement_id, external_sale_id, happened_at, action, line_type, quantity, "
        "amount, currency) VALUES (gen_random_uuid(), :org, :store, :order, :item, 'a1', 's1', "
        "now(), 'order', 'product', 2, 25, 'AUD')",
        "INSERT INTO refunds (id, organization_id, order_id, external_refund_id, processed_at, "
        "total_amount, currency) VALUES (:refund, :org, :order, 'r1', now(), 12.5, 'AUD')",
        "INSERT INTO refund_items (id, organization_id, refund_id, order_item_id, "
        "external_refund_line_id, quantity, subtotal) VALUES "
        "(gen_random_uuid(), :org, :refund, :item, 'rl1', 1, 12.5)",
        "INSERT INTO commerce_sync_state (store_id, organization_id, import_progress) "
        "VALUES (:store, :org, 100)",
        "INSERT INTO financial_daily (id, organization_id, store_id, day, currency, "
        "definition_version, gross_sales, discounts, sales_reversals, net_sales, shipping, taxes, "
        "duties, fees, total_sales, orders_count, cogs, costed_net_sales, uncosted_lines, "
        "computed_at) VALUES (gen_random_uuid(), :org, :store, current_date, 'AUD', 'finance-v1', "
        "25, 0, 0, 25, 0, 0, 0, 0, 25, 1, 8.246912, 25, 0, now())",
    ):
        conn.execute(text(sql), params)
    return ids


@pytest.fixture
def commerce(seeded, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        a = _seed_store(conn, seeded["org_a"], "store-a")
    with app_engine.begin() as conn:
        b = _seed_store(conn, seeded["org_b"], "store-b")
    return {**seeded, "a": a, "b": b}


def test_no_context_sees_no_commerce_rows(commerce, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        for table in COMMERCE_TABLES:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table


def test_each_tenant_sees_only_its_own_commerce_rows(commerce, app_engine):  # noqa: F811
    for org in ("org_a", "org_b"):
        with app_engine.begin() as conn:
            _ctx(conn, org=commerce[org])
            for table in COMMERCE_TABLES:
                orgs = {
                    str(r[0]) for r in conn.execute(text(f"SELECT organization_id FROM {table}"))
                }
                assert orgs == {commerce[org]}, table


def test_cannot_change_or_delete_another_tenants_rows(commerce, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_a"])
        for table in COMMERCE_TABLES:
            assert (
                conn.execute(
                    text(
                        f"UPDATE {table} SET organization_id = organization_id "
                        "WHERE organization_id = :b"
                    ),
                    {"b": commerce["org_b"]},
                ).rowcount
                == 0
            ), table
            assert (
                conn.execute(
                    text(f"DELETE FROM {table} WHERE organization_id = :b"),
                    {"b": commerce["org_b"]},
                ).rowcount
                == 0
            ), table
    with app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_b"])
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar_one() == 1


def test_cannot_insert_rows_for_another_tenant(commerce, app_engine):  # noqa: F811
    with pytest.raises(DBAPIError, match="row-level security"), app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_a"])
        conn.execute(
            text(
                "INSERT INTO orders (id, organization_id, store_id, external_order_id, currency, "
                "ordered_at) VALUES (gen_random_uuid(), :b, :store_b, 'x', 'AUD', now())"
            ),
            {"b": commerce["org_b"], "store_b": commerce["b"]["store"]},
        )


@pytest.mark.parametrize(
    ("sql", "parent"),
    [
        (
            "INSERT INTO orders (id, organization_id, store_id, external_order_id, currency, "
            "ordered_at) VALUES (gen_random_uuid(), :a, :p, 'x', 'AUD', now())",
            "store",
        ),
        (
            "INSERT INTO order_items (id, organization_id, order_id, external_line_item_id, "
            "quantity) VALUES (gen_random_uuid(), :a, :p, 'x', 1)",
            "order",
        ),
        (
            "INSERT INTO order_items (id, organization_id, order_id, variant_id, "
            "external_line_item_id, quantity) "
            "VALUES (gen_random_uuid(), :a, :own_order, :p, 'y', 1)",
            "variant",
        ),
        (
            "INSERT INTO product_cost_history (id, organization_id, variant_id, unit_cost, "
            "currency, effective_from, source, recorded_at) VALUES "
            "(gen_random_uuid(), :a, :p, 1, 'AUD', now(), 'platform', now())",
            "variant",
        ),
        (
            "INSERT INTO refund_items (id, organization_id, refund_id, external_refund_line_id, "
            "quantity) VALUES (gen_random_uuid(), :a, :p, 'x', 1)",
            "refund",
        ),
    ],
)
def test_composite_keys_block_cross_tenant_references(commerce, admin_engine, sql, parent):
    """Even a superuser bypassing RLS cannot attach org A rows to org B's parents."""
    with pytest.raises(IntegrityError), admin_engine.begin() as conn:
        conn.execute(
            text(sql),
            {
                "a": commerce["org_a"],
                "p": commerce["b"][parent],
                "own_order": commerce["a"]["order"],
            },
        )


def test_money_is_exact_decimal(commerce, app_engine):  # noqa: F811
    with app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_a"])
        cost = conn.execute(text("SELECT unit_cost FROM product_cost_history")).scalar_one()
        cogs = conn.execute(text("SELECT cogs FROM financial_daily")).scalar_one()
    assert cost == Decimal("4.123456")
    assert cogs == Decimal("8.246912")


def test_missing_cost_is_null_never_zero(commerce, app_engine):  # noqa: F811
    """financial_daily: COGS must be NULL exactly when some lines are uncosted (A10)."""
    bad = [
        ("8", "1"),  # a value although lines are uncosted
        ("NULL", "0"),  # no value although every line is costed
    ]
    for cogs, uncosted in bad:
        with pytest.raises(IntegrityError, match="cogs_availability"), app_engine.begin() as conn:
            _ctx(conn, org=commerce["org_a"])
            conn.execute(
                text(
                    "INSERT INTO financial_daily (id, organization_id, store_id, day, currency, "
                    "definition_version, gross_sales, discounts, sales_reversals, net_sales, "
                    "shipping, taxes, duties, fees, total_sales, orders_count, cogs, "
                    f"costed_net_sales, uncosted_lines, computed_at) VALUES (gen_random_uuid(), "
                    ":a, :s, current_date - 1, 'AUD', 'finance-v1', 1, 0, 0, 1, 0, 0, 0, 0, 1, 1, "
                    f"{cogs}, 0, {uncosted}, now())"
                ),
                {"a": commerce["org_a"], "s": commerce["a"]["store"]},
            )
    with pytest.raises(IntegrityError, match="cost_complete"), app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_a"])
        conn.execute(
            text(
                "INSERT INTO order_items (id, organization_id, order_id, external_line_item_id, "
                "quantity, unit_cost) VALUES (gen_random_uuid(), :a, :o, 'nc', 1, 3)"
            ),
            {"a": commerce["org_a"], "o": commerce["a"]["order"]},
        )


def test_order_history_survives_variant_deletion_attempt(commerce, app_engine):  # noqa: F811
    """Deleting a variant that order lines reference is refused — history is never lost."""
    with pytest.raises(IntegrityError), app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_a"])
        conn.execute(text("DELETE FROM product_variants"))


def test_store_erasure_removes_all_store_data(commerce, app_engine):  # noqa: F811
    """A ``shop/redact``-style erasure: deleting the store removes every dependent row."""
    with app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_a"])
        for table in ("sales_entries", "refund_items", "refunds", "order_items", "orders"):
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM stores"))
        for table in COMMERCE_TABLES:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
    with app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_b"])
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar_one() == 1


def test_one_live_connection_per_platform_account(commerce, app_engine):  # noqa: F811
    """Q6: the same platform account cannot be live in two organizations at once."""
    with app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_a"])
        conn.execute(
            text("UPDATE external_connections SET external_account_id = 'shop-1.myshopify.com'")
        )
    with (
        pytest.raises(IntegrityError, match="uq_external_connections_live_account"),
        app_engine.begin() as conn,
    ):
        _ctx(conn, org=commerce["org_b"])
        conn.execute(
            text("UPDATE external_connections SET external_account_id = 'shop-1.myshopify.com'")
        )
    with app_engine.begin() as conn:  # once A's connection is revoked, B may connect
        _ctx(conn, org=commerce["org_a"])
        conn.execute(text("UPDATE external_connections SET status = 'revoked'"))
    with app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_b"])
        conn.execute(
            text("UPDATE external_connections SET external_account_id = 'shop-1.myshopify.com'")
        )


def test_system_role_access_is_narrow(commerce, settings, app_engine):  # noqa: F811
    system = create_engine(settings.DATABASE_URL_SYSTEM.get_secret_value())
    try:
        with system.begin() as conn:  # webhook routing and the cross-org account check
            assert conn.execute(text("SELECT count(*) FROM stores")).scalar_one() == 2
            assert conn.execute(text("SELECT count(*) FROM external_connections")).scalar_one() == 2
        for table in ("orders", "order_items", "products", "sales_entries", "financial_daily"):
            with pytest.raises(DBAPIError, match="permission denied"), system.begin() as conn:
                conn.execute(text(f"SELECT * FROM {table}"))
        with pytest.raises(DBAPIError, match="permission denied"), system.begin() as conn:
            conn.execute(text("UPDATE stores SET name = 'x'"))
    finally:
        system.dispose()


def test_webhook_log_is_system_only_and_deduplicated(commerce, settings, app_engine):  # noqa: F811
    insert = text(
        "INSERT INTO webhook_events (id, provider, webhook_id, topic, external_account_id, "
        "received_at) VALUES (gen_random_uuid(), 'shopify', 'wh-1', 'orders/updated', "
        "'shop-1.myshopify.com', now())"
    )
    with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
        _ctx(conn, org=commerce["org_a"])
        conn.execute(text("SELECT * FROM webhook_events"))
    system = create_engine(settings.DATABASE_URL_SYSTEM.get_secret_value())
    try:
        with system.begin() as conn:
            conn.execute(insert)
        with pytest.raises(IntegrityError), system.begin() as conn:
            conn.execute(insert)  # the same delivery again
        with system.begin() as conn:
            columns = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'webhook_events'"
                    )
                )
            }
        assert not columns & {"body", "payload", "raw", "data"}, "bodies are never stored"
    finally:
        system.dispose()
