"""Daily store figures built from imported sales records (task 2A-08), end to end.

The sample store (Australia/Sydney) has one order on 5 Oct (12:30 local) with two product
lines and shipping, and a refund processed on 8 Oct (14:00 local). Expected figures are
calculated by hand from ``finance-v1``:

5 Oct  gross 39.80 + 11.01 = 50.81, discounts 2.00, net 48.81, shipping 10.00 - 0.92 = 9.08,
       taxes 3.78 + 1.10 + 0.92 = 5.80, total 63.69, 1 order; one line has no cost
       (a custom line) -> COGS not available, costed net sales 37.80.
8 Oct  reversal: net -20.79 - (-1.89) = -18.90 -> reversals 18.90, taxes -1.89,
       total -20.79, COGS -7.25 (the returned unit's cost).
"""

from __future__ import annotations

import copy
import uuid
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.commerce.importer import SyncMode, enqueue_reconciliations
from app.domains.finance.service import recompute_since
from sqlalchemy import text

from tests.shopify_sim import (
    ShopifySim,
    build_provider,
    callback_params,
    money,
    sample_catalogue,
    sample_orders,
    webhook_request,
)

SHOP = "eve-zone.myshopify.com"


@pytest.fixture
def sim(runtime, clock):
    s = ShopifySim()
    s.add_shop(SHOP, catalogue=sample_catalogue(), orders=sample_orders())
    runtime.providers.register(build_provider(s, clock))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup("finance-owner@example.com")
    c.org = c.create_org("Finance Co")["id"]
    started = c.post(
        f"/organizations/{c.org}/connections/shopify/start", {"params": {"shop_domain": SHOP}}
    ).json()["data"]["authorize_url"]
    response = c.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    (resource,) = c.get(f"/organizations/{c.org}/connections/{conn}/resources").json()["data"]
    c.post(f"/organizations/{c.org}/resources/{resource['id']}/link")
    return c


def _days(admin_engine):
    with admin_engine.begin() as db:
        rows = db.execute(text("SELECT * FROM financial_daily ORDER BY day")).mappings().all()
    return {r["day"]: r for r in rows}


def _deliver(client, clock, topic, payload):
    headers, body = webhook_request(
        topic,
        payload,
        shop=SHOP,
        webhook_id=str(uuid.uuid4()),
        triggered_at=clock.now().isoformat(),
    )
    assert (
        client.http.post("/api/v1/webhooks/shopify", content=body, headers=headers).status_code
        == 200
    )


def test_import_builds_the_daily_figures(owner, admin_engine):
    days = _days(admin_engine)
    assert set(days) == {date(2026, 10, 5), date(2026, 10, 8)}
    order_day = days[date(2026, 10, 5)]
    expected = {
        "currency": "AUD",
        "definition_version": "finance-v1",
        "gross_sales": Decimal("50.81"),
        "discounts": Decimal("2.00"),
        "sales_reversals": Decimal("0"),
        "net_sales": Decimal("48.81"),
        "shipping": Decimal("9.08"),
        "taxes": Decimal("5.80"),
        "duties": Decimal("0"),
        "fees": Decimal("0"),
        "total_sales": Decimal("63.69"),
        "orders_count": 1,
        "cogs": None,
        "costed_net_sales": Decimal("37.80"),
        "uncosted_lines": 1,
    }
    assert {k: order_day[k] for k in expected} == expected
    refund_day = days[date(2026, 10, 8)]
    assert (
        refund_day["sales_reversals"],
        refund_day["net_sales"],
        refund_day["taxes"],
        refund_day["total_sales"],
        refund_day["cogs"],
        refund_day["orders_count"],
    ) == (
        Decimal("18.90"),
        Decimal("-18.90"),
        Decimal("-1.89"),
        Decimal("-20.79"),
        Decimal("-7.25"),
        0,
    )


def test_recomputing_is_idempotent(owner, runtime, clock, admin_engine):
    before = _days(admin_engine)
    org = uuid.UUID(owner.org)
    with admin_engine.begin() as db:
        store_id = db.execute(text("SELECT id FROM stores")).scalar_one()
    rows = recompute_since(runtime, org, store_id, clock.now() - timedelta(days=60))
    after = _days(admin_engine)
    assert rows == 2
    strip = lambda d: {k: v for k, v in d.items() if k not in ("id", "computed_at")}  # noqa: E731
    assert {k: strip(v) for k, v in after.items()} == {k: strip(v) for k, v in before.items()}


def test_a_refund_webhook_updates_the_refund_day(owner, client, sim, clock, admin_engine):
    nodes = sim.shops[SHOP].orders
    order = next(n for n in nodes if n["id"] == "gid://shopify/Order/500")
    order["updatedAt"] = "2026-10-12T00:00:00Z"
    nodes.append(
        {
            "id": "gid://shopify/SalesAgreement/702",
            "happenedAt": "2026-10-12T00:00:00Z",  # 11:00 on 12 Oct in Sydney
            "reason": "REFUND",
            "__parentId": "gid://shopify/Order/500",
        }
    )
    nodes.append(
        {
            "id": "gid://shopify/Sale/805",
            "actionType": "RETURN",
            "lineType": "SHIPPING",
            "quantity": None,
            "totalAmount": money("-10.00"),
            "totalDiscountAmountBeforeTaxes": money("0.00"),
            "totalTaxAmount": money("-0.92"),
            "__parentId": "gid://shopify/SalesAgreement/702",
        }
    )
    _deliver(client, clock, "refunds/create", {"id": 902, "order_id": 500})
    day = _days(admin_engine)[date(2026, 10, 12)]
    assert (day["shipping"], day["taxes"], day["total_sales"]) == (
        Decimal("-9.08"),
        Decimal("-0.92"),
        Decimal("-10.00"),
    )


def test_a_deleted_order_disappears_from_the_figures(owner, client, clock, admin_engine):
    _deliver(client, clock, "orders/delete", {"id": 500})
    assert _days(admin_engine) == {}


def test_a_new_order_by_webhook_adds_to_its_day(owner, client, sim, clock, admin_engine):
    template = next(n for n in sim.shops[SHOP].orders if n["id"] == "gid://shopify/Order/500")
    order = copy.deepcopy(template)
    order.update(
        id="gid://shopify/Order/510",
        name="#1010",
        processedAt="2026-10-05T03:00:00Z",
        updatedAt="2026-10-05T03:00:00Z",
        refunds=[],
    )
    sim.shops[SHOP].orders.extend(
        [
            order,
            {
                "id": "gid://shopify/SalesAgreement/710",
                "happenedAt": "2026-10-05T03:00:00Z",
                "reason": "ORDER",
                "__parentId": "gid://shopify/Order/510",
            },
            {
                "id": "gid://shopify/Sale/810",
                "actionType": "ORDER",
                "lineType": "PRODUCT",
                "quantity": 1,
                "totalAmount": money("22.00"),
                "totalDiscountAmountBeforeTaxes": money("0.00"),
                "totalTaxAmount": money("2.00"),
                "__parentId": "gid://shopify/SalesAgreement/710",
            },
        ]
    )
    _deliver(client, clock, "orders/create", {"id": 510})
    day = _days(admin_engine)[date(2026, 10, 5)]
    assert (day["orders_count"], day["net_sales"], day["uncosted_lines"]) == (
        2,
        Decimal("68.81"),  # 48.81 + 20.00
        2,  # the new sale has no order line: its cost is unknown
    )


def test_reconciliation_refreshes_recent_days(owner, sim, clock, runtime, admin_engine):
    sale = next(n for n in sim.shops[SHOP].orders if n["id"] == "gid://shopify/Sale/803")
    sale["totalAmount"] = money("12.00")
    order = next(n for n in sim.shops[SHOP].orders if n["id"] == "gid://shopify/Order/500")
    order["updatedAt"] = "2026-10-13T00:00:00Z"
    clock.advance(timedelta(hours=1))
    # Hourly reconciliation rebuilds only from its window; the deep check covers 30 days.
    assert enqueue_reconciliations(runtime, SyncMode.DEEP) == 1
    day = _days(admin_engine)[date(2026, 10, 5)]
    assert day["shipping"] == Decimal("11.08")


def test_recompute_helpers(owner, runtime, admin_engine):
    from types import SimpleNamespace

    from app.domains.commerce.models import Store
    from app.domains.finance.service import order_days, recompute_days, recompute_span, store_zone

    assert str(store_zone(SimpleNamespace(timezone="Not/AZone", id=uuid.uuid4()))) == "UTC"
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        store = session.query(Store).one()
        assert recompute_span(session, runtime, store, date(2026, 10, 9), date(2026, 10, 8)) == 0
        assert order_days(session, store, []) == set()
        # Non-consecutive days are rebuilt as separate runs; untouched days keep their rows.
        written = recompute_days(
            session, runtime, store, [date(2026, 10, 8), date(2026, 10, 5), date(2026, 10, 6)]
        )
    assert written == 2
    assert set(_days(admin_engine)) == {date(2026, 10, 5), date(2026, 10, 8)}


def test_unknown_line_types_are_logged_not_counted(owner, client, sim, clock, admin_engine, caplog):
    import logging

    caplog.set_level(logging.WARNING)
    nodes = sim.shops[SHOP].orders
    next(n for n in nodes if n["id"] == "gid://shopify/Order/500")["updatedAt"] = (
        "2026-10-12T00:00:00Z"
    )
    nodes.append(
        {
            "id": "gid://shopify/Sale/890",
            "actionType": "ORDER",
            "lineType": "SOMETHING_NEW",
            "quantity": 1,
            "totalAmount": money("5.00"),
            "totalDiscountAmountBeforeTaxes": money("0.00"),
            "totalTaxAmount": money("0.00"),
            "__parentId": "gid://shopify/SalesAgreement/700",
        }
    )
    _deliver(client, clock, "orders/updated", {"id": 500})
    assert _days(admin_engine)[date(2026, 10, 5)]["total_sales"] == Decimal("63.69")
    assert "finance_lines_not_counted" in caplog.text
