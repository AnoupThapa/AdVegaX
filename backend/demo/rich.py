"""Sixty days of simulated activity for the desktop demo (Phase 19).

The end-to-end helpers in ``tests/`` import a minimal, exact sample that their tests check line
by line. When ``ADVEGAX_DEMO_DAYS`` is set (only ``demo/seed.py`` sets it), the helpers ask this
module for a fuller, steadier history instead: daily orders for products that all have a cost,
and daily Google Ads and Google Analytics figures, so the Overview's charts have something to
show. Everything is generated from a fixed seed: the same demo every time. Never real data.
"""

from __future__ import annotations

import copy
import math
import os
import random
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

ENV = "ADVEGAX_DEMO_DAYS"
CENT = Decimal("0.01")


def demo_days() -> int:
    """How many days of history the demo wants (0: the helpers' own small sample)."""
    try:
        return max(0, min(120, int(os.environ.get(ENV, "0"))))
    except ValueError:
        return 0


def _money(amount: Decimal) -> dict[str, Any]:
    value = str(amount.quantize(CENT, rounding=ROUND_HALF_UP))
    return {"shopMoney": {"amount": value, "currencyCode": "AUD"}}


def _season(day_index: int, days: int) -> float:
    """A gentle rise over the period with a weekly rhythm (weekends quieter)."""
    trend = 0.75 + 0.5 * day_index / max(days - 1, 1)
    weekly = 1.0 + 0.18 * math.sin(day_index * 2 * math.pi / 7)
    return trend * weekly


# ------------------------------------------------------------------ Shopify
def demo_catalogue(catalogue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sample catalogue with a cost on every variant, so profit can be worked out."""
    items = copy.deepcopy(catalogue)
    for item in items:
        inventory = item.get("inventoryItem")
        if isinstance(inventory, dict) and "unitCost" not in inventory:
            inventory["unitCost"] = {"amount": "8.10", "currencyCode": "AUD"}
    return items


PRODUCTS = (  # variant id, title, sku, unit price
    ("gid://shopify/ProductVariant/11", "Nitrile Gloves - Medium", "NG-M", Decimal("19.90")),
    ("gid://shopify/ProductVariant/12", "Nitrile Gloves - Large", "NG-L", Decimal("21.90")),
)


def demo_orders(now: datetime, days: int) -> list[dict[str, Any]]:
    """Orders for each of the last ``days`` days, in Shopify's bulk-export shape."""
    rng = random.Random(1907)  # noqa: S311 - repeatable demo figures, not security
    rows: list[dict[str, Any]] = []
    number = 2000
    for i in range(days):
        day = (now - timedelta(days=days - i)).astimezone(UTC)
        for _ in range(max(1, round(rng.gauss(5, 1.5) * _season(i, days)))):
            number += 1
            moment = day.replace(hour=rng.randint(0, 22), minute=rng.randint(0, 59), second=0)
            stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
            order_id = f"gid://shopify/Order/{number}"
            lines = []
            subtotal = Decimal(0)
            for n, (variant, title, sku, price) in enumerate(PRODUCTS):
                if n and rng.random() > 0.45:
                    continue
                quantity = rng.choice((1, 2, 2, 3, 4, 6))
                amount = price * quantity
                subtotal += amount
                lines.append((f"{number}{n}", variant, title, sku, price, quantity, amount))
            shipping = Decimal("10.00") if subtotal < 80 else Decimal("0.00")
            tax = ((subtotal + shipping) / 11).quantize(CENT)
            rows.append(
                {
                    "id": order_id,
                    "name": f"#{number}",
                    "processedAt": stamp,
                    "updatedAt": stamp,
                    "cancelledAt": None,
                    "test": False,
                    "currencyCode": "AUD",
                    "displayFinancialStatus": "PAID",
                    "totalDiscountsSet": _money(Decimal(0)),
                    "totalShippingPriceSet": _money(shipping),
                    "totalTaxSet": _money(tax),
                    "totalRefundedSet": _money(Decimal(0)),
                    "totalPriceSet": _money(subtotal + shipping),
                    "refunds": [],
                }
            )
            agreement = f"gid://shopify/SalesAgreement/{number}"
            rows.append(
                {"id": agreement, "happenedAt": stamp, "reason": "ORDER", "__parentId": order_id}
            )
            for ref, variant, title, sku, price, quantity, amount in lines:
                line_id = f"gid://shopify/LineItem/{ref}"
                rows.append(
                    {
                        "id": line_id,
                        "title": title,
                        "sku": sku,
                        "quantity": quantity,
                        "variant": {"id": variant},
                        "originalUnitPriceSet": _money(price),
                        "__parentId": order_id,
                    }
                )
                rows.append(
                    {
                        "id": f"gid://shopify/Sale/{ref}",
                        "actionType": "ORDER",
                        "lineType": "PRODUCT",
                        "quantity": quantity,
                        "totalAmount": _money(amount),
                        "totalDiscountAmountBeforeTaxes": _money(Decimal(0)),
                        "totalTaxAmount": _money((amount / 11).quantize(CENT)),
                        "lineItem": {"id": line_id},
                        "__parentId": agreement,
                    }
                )
            if shipping:
                rows.append(
                    {
                        "id": f"gid://shopify/Sale/{number}9",
                        "actionType": "ORDER",
                        "lineType": "SHIPPING",
                        "quantity": None,
                        "totalAmount": _money(shipping),
                        "totalDiscountAmountBeforeTaxes": _money(Decimal(0)),
                        "totalTaxAmount": _money((shipping / 11).quantize(CENT)),
                        "__parentId": agreement,
                    }
                )
    return rows


# ------------------------------------------------------------------ Google Ads
def demo_google_performance(customer: Any, today: date, days: int, perf_row: Any) -> None:
    """Daily rows for the Search campaign (11, ad group 2101, ad 90001) and Performance Max
    (12), with the account's totals, for the last ``days`` days."""
    rng = random.Random(2511)  # noqa: S311 - repeatable demo figures, not security
    account, campaign, group, ad = [], [], [], []
    for i in range(days):
        day = (today - timedelta(days=days - i)).isoformat()
        lift = _season(i, days)
        search = {
            "impressions": int(rng.gauss(1400, 150) * lift),
            "clicks": int(rng.gauss(42, 6) * lift),
            "cost_micros": int(rng.gauss(26, 3) * lift * 1_000_000),
            "conversions": round(max(0.0, rng.gauss(2.2, 0.8) * lift), 1),
            "conversions_value": round(max(0.0, rng.gauss(130, 30) * lift), 2),
        }
        pmax = {
            "impressions": int(rng.gauss(2600, 300) * lift),
            "clicks": int(rng.gauss(30, 5) * lift),
            "cost_micros": int(rng.gauss(18, 2.5) * lift * 1_000_000),
            "conversions": round(max(0.0, rng.gauss(1.1, 0.5) * lift), 1),
            "conversions_value": round(max(0.0, rng.gauss(70, 20) * lift), 2),
        }
        total = {k: search[k] + pmax[k] for k in search}
        total["conversions"] = round(float(total["conversions"]), 1)
        total["conversions_value"] = round(float(total["conversions_value"]), 2)
        account.append(perf_row(day, **total))
        campaign.append(perf_row(day, campaign="11", **search))
        campaign.append(perf_row(day, campaign="12", **pmax))
        group.append(perf_row(day, campaign="11", ad_group="2101", **search))
        ad.append(perf_row(day, campaign="11", ad_group="2101", ad="90001", **search))
    customer.performance = {"account": account, "campaign": campaign, "ad_group": group, "ad": ad}


# ------------------------------------------------------------------ Google Analytics
def demo_visits(today: date, days: int, visit: Any) -> list[Any]:
    """Daily visits from organic search, paid search and direct."""
    rng = random.Random(3307)  # noqa: S311 - repeatable demo figures, not security
    out = []
    channels = (
        ("Organic Search", "google", "organic", None, 70),
        ("Paid Search", "google", "cpc", "Gloves - Search", 45),
        ("Direct", "(direct)", "(none)", None, 25),
    )
    for i in range(days):
        day = today - timedelta(days=days - i)
        lift = _season(i, days)
        for channel, source, medium, campaign, base in channels:
            sessions = max(1, int(rng.gauss(base, base * 0.12) * lift))
            purchases = max(0, int(rng.gauss(sessions * 0.03, 0.8)))
            out.append(
                visit(
                    day,
                    channel=channel,
                    source=source,
                    medium=medium,
                    campaign=campaign or "(not set)",
                    sessions=sessions,
                    engaged=int(sessions * 0.62),
                    users=int(sessions * 0.85),
                    new_users=int(sessions * 0.4),
                    key_events=Decimal(purchases * 3),
                    purchases=purchases,
                    revenue=(Decimal("44.50") * purchases).quantize(CENT),
                    landing_page="/collections/gloves" if campaign else "/",
                    item_views=int(sessions * 0.45),
                    add_to_carts=int(sessions * 0.12),
                    checkouts=max(purchases, int(sessions * 0.05)),
                )
            )
    return out
