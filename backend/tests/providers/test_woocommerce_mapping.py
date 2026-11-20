"""WooCommerce → commerce records, edge cases (task 2B-05). The journey through the API is in
``tests/api/test_woocommerce_import.py``; these pin down the mapping rules themselves."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.providers.base.types import (
    CommerceOrderRecord,
    CommerceSaleRecord,
    CommerceVariantRecord,
)
from app.providers.woocommerce import mapping


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("19.90", Decimal("19.90")),
        (5, Decimal(5)),
        (1.1, Decimal("1.1")),
        ("", None),
        (None, None),
        ("abc", None),
        ("NaN", None),
        ("Infinity", None),
        (True, None),
    ],
)
def test_money(value, expected):
    assert mapping.money(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-05T01:30:00", datetime(2026, 10, 5, 1, 30, tzinfo=UTC)),
        ("2026-10-05T01:30:00Z", datetime(2026, 10, 5, 1, 30, tzinfo=UTC)),
        ("2026-10-05T11:30:00+10:00", datetime(2026, 10, 5, 1, 30, tzinfo=UTC)),
        ("", None),
        ("yesterday", None),
        (None, None),
    ],
)
def test_gmt_dates(value, expected):
    assert mapping.gmt(value) == expected


def _variant(records):
    return next(r for r in records if isinstance(r, CommerceVariantRecord))


def test_simple_products_are_their_own_variant_and_other_types_have_none():
    simple = {
        "id": 5,
        "name": "Mask",
        "type": "simple",
        "status": "publish",
        "price": "2",
        "manage_stock": True,
        "stock_quantity": 7,
    }
    variant = _variant(mapping.product_records(simple, "AUD"))
    assert (variant.external_id, variant.product_external_id) == ("5", "5")
    assert (variant.inventory_tracked, variant.inventory_available) == (True, 7)
    grouped = {"id": 6, "name": "Kit", "type": "grouped", "status": "draft"}
    records = mapping.product_records(grouped, "AUD")
    assert len(records) == 1 and records[0].status == "draft"


def test_untitled_and_unknown_status_products():
    (product,) = mapping.product_records({"id": 7, "type": "external", "status": "odd"}, "AUD")
    assert (product.title, product.status) == ("Product 7", "draft")


def test_variations_inheriting_stock_from_their_product():
    variation = {"id": 11, "manage_stock": "parent", "stock_quantity": 4, "attributes": []}
    record = mapping.variation_record(variation, "10", "AUD")
    assert (record.inventory_tracked, record.inventory_available, record.title) == (True, 4, None)
    untracked = mapping.variation_record(
        {"id": 12, "manage_stock": False, "stock_quantity": 9}, "10", "AUD"
    )
    assert (untracked.inventory_tracked, untracked.inventory_available) == (False, None)


def _order(**extra):
    base = {
        "id": 1,
        "status": "processing",
        "currency": "AUD",
        "date_created_gmt": "2026-10-05T00:00:00",
        "line_items": [],
        "shipping_lines": [],
        "fee_lines": [],
        "refunds": [],
    }
    return {**base, **extra}


def test_fee_lines_and_negative_fees_are_sales():
    order = _order(
        fee_lines=[
            {"id": 3, "total": "4.00", "total_tax": "0.40"},
            {"id": 4, "total": "-2.00", "total_tax": "0"},
        ]
    )
    fees = [r for r in mapping.order_records(order, "AUD") if isinstance(r, CommerceSaleRecord)]
    assert [(f.external_id, f.line_type, f.amount, f.tax_amount) for f in fees] == [
        ("fee:3", "fee", Decimal("4.40"), Decimal("0.40")),
        ("fee:4", "fee", Decimal("-2.00"), Decimal("0")),
    ]


def test_order_line_cost_is_per_unit_and_absent_cost_stays_absent():
    order = _order(
        line_items=[
            {
                "id": 9,
                "product_id": 5,
                "quantity": 4,
                "total": "20",
                "subtotal": "20",
                "total_tax": "0",
                "cost_of_goods_sold": {"value": 10},
            },
            {
                "id": 10,
                "product_id": 5,
                "quantity": 0,
                "total": "0",
                "subtotal": "0",
                "total_tax": "0",
                "cost_of_goods_sold": {"value": 10},
            },
        ]
    )
    lines = [r for r in mapping.order_records(order, "AUD") if hasattr(r, "cost_from_platform")]
    assert [(line.unit_cost, line.cost_from_platform) for line in lines] == [
        (Decimal("2.5"), True),
        (None, True),  # nothing sold: no unit cost
    ]


@pytest.mark.parametrize(
    ("status", "currency", "reason"),
    [
        ("processing", "AUD", None),
        ("completed", "AUD", None),
        ("on-hold", "AUD", None),
        ("refunded", "AUD", None),
        ("pending", "AUD", "status"),
        ("failed", "AUD", "status"),
        ("cancelled", "AUD", "status"),
        ("checkout-draft", "AUD", "status"),
        ("trash", "AUD", "status"),
        ("completed", "USD", "other_currency"),
        ("cancelled", "USD", "status"),
    ],
)
def test_which_orders_count(status, currency, reason):
    (order, *_) = mapping.order_records(_order(status=status, currency=currency), "AUD")
    assert isinstance(order, CommerceOrderRecord) and order.excluded_reason == reason


def test_refund_shipping_lines_and_partly_explained_refunds():
    refund = {
        "id": 7,
        "parent_id": 1,
        "date_created_gmt": "2026-10-06T00:00:00",
        "amount": "15.00",
        "line_items": [
            {
                "id": 8,
                "total": "-9.00",
                "total_tax": "-0.90",
                "quantity": -1,
                "meta_data": [{"key": "other", "value": 1}],
            }
        ],
        "shipping_lines": [{"id": 9, "total": "-2.00", "total_tax": "-0.20"}],
    }
    sales = {
        r.external_id: r
        for r in mapping.refund_records(refund, "AUD")
        if isinstance(r, CommerceSaleRecord)
    }
    assert sales["refund-line:7:8"].line_item_external_id is None  # no refunded-item link
    assert sales["refund-shipping:7:9"].amount == Decimal("-2.20")
    assert sales["refund-amount:7"].amount == Decimal("-2.90")  # 15.00 - 9.90 - 2.20
    assert sales["refund-amount:7"].line_type == "adjustment"


def test_records_that_cannot_be_read_are_skipped():
    items = [_order(id=2), "not an object", _order(id=-1), _order(id=3, date_created_gmt="x")]
    records, skipped = mapping.safe_map(items, mapping.order_records, "AUD")
    assert skipped == 3
    assert [r.external_id for r in records if isinstance(r, CommerceOrderRecord)] == ["2"]
    refunds, skipped = mapping.safe_map([{"id": 1, "parent_id": 1}], mapping.refund_records, "AUD")
    assert (refunds, skipped) == ([], 1)
