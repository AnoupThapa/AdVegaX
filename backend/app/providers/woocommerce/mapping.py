"""WooCommerce REST v3 → platform-neutral commerce records (task 2B-05, PHASE_02B_PLAN §9-§10).

Only fields the commerce model has are read. **Customer details (billing, shipping, email,
phone, names) are never read**: the mapper ignores them, they are not copied anywhere, and the
reader also asks the store not to send them (``_fields``).

Sales records follow the same definitions as Shopify's, so the finance core needs no
WooCommerce-specific code (parity, §10):

* each order is one "agreement" dated by its creation (store-local via GMT dates);
* each product, shipping and fee line is a sale: ``amount`` = line total **including** tax,
  ``tax`` = the line's tax, ``discount`` = subtotal - total (before tax). So net sales =
  ``amount - tax`` = the line total after discounts, and gross = net + discount = the line
  subtotal — the same formula as Shopify's;
* each refund is an agreement dated by the refund; its line items are returns (negative);
  the part of a refund not covered by its lines (amount-only refunds) is an ``adjustment``
  reversal, counted in full because WooCommerce does not split its tax (to confirm, Step 0).

Order status decides whether an order counts (Q-2B-2, WooCommerce Analytics' defaults);
uncounted orders are kept with ``excluded_reason``. Line costs come from WooCommerce's own
cost of goods (recorded with the sale) and are never replaced by a later product cost.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.providers.base.types import (
    CommerceOrderLineRecord,
    CommerceOrderRecord,
    CommerceProductRecord,
    CommerceRecord,
    CommerceRefundRecord,
    CommerceSaleRecord,
    CommerceVariantRecord,
)

# Q-2B-2: statuses WooCommerce Analytics leaves out by default, plus drafts and trash.
EXCLUDED_STATUSES = frozenset(
    {"pending", "failed", "cancelled", "checkout-draft", "auto-draft", "draft", "trash"}
)
PRODUCT_STATUS = {
    "publish": "active",
    "draft": "draft",
    "pending": "draft",
    "future": "draft",
    "private": "unlisted",
    "trash": "deleted",
}
# Fields asked for: everything the mapper reads, nothing about customers.
PRODUCT_FIELDS = (
    "id,name,slug,type,status,sku,price,manage_stock,stock_quantity,date_modified_gmt,"
    "categories,cost_of_goods_sold"
)
VARIATION_FIELDS = (
    "id,parent_id,sku,price,manage_stock,stock_quantity,date_modified_gmt,attributes,"
    "cost_of_goods_sold"
)
ORDER_FIELDS = (
    "id,number,status,currency,date_created_gmt,date_modified_gmt,discount_total,"
    "shipping_total,total,total_tax,line_items,shipping_lines,fee_lines,refunds"
)
REFUND_FIELDS = "id,parent_id,date_created_gmt,amount,line_items,shipping_lines,fee_lines"


class MappingError(ValueError):
    """A record could not be read; it is skipped and counted, never half-stored."""


# ------------------------------------------------------------------ values
def money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def money_or_zero(value: Any) -> Decimal:
    """For line components WooCommerce always sends (missing = nothing charged)."""
    return money(value) or Decimal(0)


def gmt(value: Any) -> datetime | None:
    """WooCommerce ``*_gmt`` dates come without a zone suffix; they are UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.removesuffix("Z"))
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return None


def _text(value: Any, limit: int = 512) -> str | None:
    return value[:limit] if isinstance(value, str) and value.strip() else None


def external_id(value: Any) -> str:
    number = _int(value)
    if number is None or number <= 0:
        raise MappingError("id")
    return str(number)


def _cost_total(node: dict[str, Any]) -> Decimal | None:
    cogs = node.get("cost_of_goods_sold")
    return money(cogs.get("total_value")) if isinstance(cogs, dict) else None


# ------------------------------------------------------------------ catalogue
def product_records(product: dict[str, Any], currency: str) -> list[CommerceRecord]:
    """A product and, for simple products, its single variant (the product itself)."""
    pid = external_id(product.get("id"))
    categories = product.get("categories")
    first = categories[0] if isinstance(categories, list) and categories else None
    records: list[CommerceRecord] = [
        CommerceProductRecord(
            external_id=pid,
            title=_text(product.get("name"), 512) or f"Product {pid}",
            status=PRODUCT_STATUS.get(str(product.get("status")), "draft"),
            handle=_text(product.get("slug"), 255),
            product_type=_text(first.get("name"), 255) if isinstance(first, dict) else None,
            updated_at=gmt(product.get("date_modified_gmt")),
        )
    ]
    if product.get("type") == "simple":
        records.append(_variant(product, pid, pid, None, currency))
    return records


def variation_record(
    variation: dict[str, Any], parent_id: str, currency: str
) -> CommerceVariantRecord:
    attributes = variation.get("attributes")
    title = None
    if isinstance(attributes, list):
        parts = [
            str(a.get("option"))
            for a in attributes
            if isinstance(a, dict) and isinstance(a.get("option"), str) and a.get("option")
        ]
        title = " / ".join(parts)[:512] or None
    return _variant(variation, external_id(variation.get("id")), parent_id, title, currency)


def _variant(
    node: dict[str, Any], vid: str, pid: str, title: str | None, currency: str
) -> CommerceVariantRecord:
    tracked = node.get("manage_stock")
    tracked_flag = tracked is True  # "parent" (variation inherits) is resolved by WooCommerce
    stock = _int(node.get("stock_quantity")) if tracked is True or tracked == "parent" else None
    cost = _cost_total(node)
    return CommerceVariantRecord(
        external_id=vid,
        product_external_id=pid,
        title=title,
        sku=_text(node.get("sku"), 255),
        price=money(node.get("price")),
        inventory_tracked=tracked_flag or tracked == "parent",
        inventory_available=stock,
        unit_cost=cost,
        cost_currency=currency if cost is not None else None,
        updated_at=gmt(node.get("date_modified_gmt")),
    )


# ------------------------------------------------------------------ orders
def order_records(order: dict[str, Any], store_currency: str) -> list[CommerceRecord]:
    oid = external_id(order.get("id"))
    created = gmt(order.get("date_created_gmt"))
    if created is None:
        raise MappingError("date_created_gmt")
    currency = _text(order.get("currency"), 3) or store_currency
    status = str(order.get("status") or "")
    excluded = (
        "status"
        if status in EXCLUDED_STATUSES
        else "other_currency"
        if currency != store_currency
        else None
    )
    refunds = order.get("refunds")
    refunded = None
    if isinstance(refunds, list):
        totals = [money(r.get("total")) for r in refunds if isinstance(r, dict)]
        refunded = sum((abs(t) for t in totals if t is not None), Decimal(0)) if totals else None
    records: list[CommerceRecord] = [
        CommerceOrderRecord(
            external_id=oid,
            currency=currency,
            ordered_at=created,
            order_number=_text(order.get("number"), 64),
            financial_status=status[:32] or None,
            discount_amount=money(order.get("discount_total")),
            shipping_amount=money(order.get("shipping_total")),
            tax_amount=money(order.get("total_tax")),
            refund_amount=refunded,
            total_amount=money(order.get("total")),
            updated_at=gmt(order.get("date_modified_gmt")),
            excluded_reason=excluded,
        )
    ]
    agreement = f"order:{oid}"
    for line in _list(order.get("line_items")):
        lid = external_id(line.get("id"))
        quantity = _int(line.get("quantity")) or 0
        total, subtotal = money_or_zero(line.get("total")), money(line.get("subtotal"))
        tax = money_or_zero(line.get("total_tax"))
        cost_total = _line_cost(line)
        variation = _int(line.get("variation_id")) or 0
        product = _int(line.get("product_id")) or 0
        records.append(
            CommerceOrderLineRecord(
                external_id=lid,
                order_external_id=oid,
                quantity=max(quantity, 0),
                variant_external_id=str(variation or product) if (variation or product) else None,
                title=_text(line.get("name"), 512),
                sku=_text(line.get("sku"), 255),
                unit_price=money(line.get("price")),
                unit_cost=(cost_total / quantity) if cost_total is not None and quantity else None,
                cost_from_platform=True,
            )
        )
        records.append(
            _sale(
                f"line:{lid}",
                agreement,
                oid,
                created,
                "order",
                "order",
                "product",
                amount=total + tax,
                tax=tax,
                discount=(subtotal - total) if subtotal is not None else Decimal(0),
                currency=currency,
                quantity=quantity,
                line_id=lid,
            )
        )
    for kind, line_type in (("shipping_lines", "shipping"), ("fee_lines", "fee")):
        for line in _list(order.get(kind)):
            lid = external_id(line.get("id"))
            total, tax = money_or_zero(line.get("total")), money_or_zero(line.get("total_tax"))
            records.append(
                _sale(
                    f"{line_type}:{lid}",
                    agreement,
                    oid,
                    created,
                    "order",
                    "order",
                    line_type,
                    amount=total + tax,
                    tax=tax,
                    discount=Decimal(0),
                    currency=currency,
                )
            )
    return records


def refund_records(refund: dict[str, Any], currency: str) -> list[CommerceRecord]:
    rid, oid = external_id(refund.get("id")), external_id(refund.get("parent_id"))
    created = gmt(refund.get("date_created_gmt"))
    if created is None:
        raise MappingError("date_created_gmt")
    amount = money(refund.get("amount"))
    records: list[CommerceRecord] = [
        CommerceRefundRecord(
            external_id=rid,
            order_external_id=oid,
            processed_at=created,
            currency=currency,
            total_amount=abs(amount) if amount is not None else None,
        )
    ]
    agreement = f"refund:{rid}"
    covered = Decimal(0)
    for line in _list(refund.get("line_items")):
        lid = external_id(line.get("id"))
        total, subtotal = money_or_zero(line.get("total")), money(line.get("subtotal"))
        tax = money_or_zero(line.get("total_tax"))
        quantity = _int(line.get("quantity"))
        records.append(
            _sale(
                f"refund-line:{rid}:{lid}",
                agreement,
                oid,
                created,
                "refund",
                "return",
                "product",
                amount=total + tax,
                tax=tax,
                discount=(subtotal - total) if subtotal is not None else Decimal(0),
                currency=currency,
                quantity=quantity,
                line_id=_refunded_item(line),
            )
        )
        covered += total + tax
    for kind, line_type in (("shipping_lines", "shipping"), ("fee_lines", "fee")):
        for line in _list(refund.get(kind)):
            lid = external_id(line.get("id"))
            total, tax = money_or_zero(line.get("total")), money_or_zero(line.get("total_tax"))
            records.append(
                _sale(
                    f"refund-{line_type}:{rid}:{lid}",
                    agreement,
                    oid,
                    created,
                    "refund",
                    "return",
                    line_type,
                    amount=total + tax,
                    tax=tax,
                    discount=Decimal(0),
                    currency=currency,
                )
            )
            covered += total + tax
    if amount is not None:
        rest = -abs(amount) - covered  # refunded money not explained by refunded lines
        if rest != 0:
            records.append(
                _sale(
                    f"refund-amount:{rid}",
                    agreement,
                    oid,
                    created,
                    "refund",
                    "return",
                    "adjustment",
                    amount=rest,
                    tax=Decimal(0),
                    discount=Decimal(0),
                    currency=currency,
                )
            )
    return records


def _sale(
    sid: str,
    agreement: str,
    oid: str,
    happened: datetime,
    reason: str,
    action: str,
    line_type: str,
    *,
    amount: Decimal,
    tax: Decimal,
    discount: Decimal,
    currency: str,
    quantity: int | None = None,
    line_id: str | None = None,
) -> CommerceSaleRecord:
    return CommerceSaleRecord(
        external_id=sid,
        agreement_external_id=agreement,
        order_external_id=oid,
        happened_at=happened,
        agreement_reason=reason,
        action=action,
        line_type=line_type,
        amount=amount,
        discount_amount=discount,
        tax_amount=tax,
        currency=currency,
        quantity=quantity,
        line_item_external_id=line_id,
    )


def _line_cost(line: dict[str, Any]) -> Decimal | None:
    cogs = line.get("cost_of_goods_sold")
    return money(cogs.get("value")) if isinstance(cogs, dict) else None


def _refunded_item(line: dict[str, Any]) -> str | None:
    """The original order line a refund line returns (``_refunded_item_id`` meta)."""
    for meta in _list(line.get("meta_data")):
        if meta.get("key") == "_refunded_item_id":
            value = _int(meta.get("value"))
            return str(value) if value else None
    return None


def _list(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, list):
        yield from (v for v in value if isinstance(v, dict))


def safe_map(items: Iterable[Any], mapper: Any, *args: Any) -> tuple[list[CommerceRecord], int]:
    """Map each item; an unreadable item is skipped and counted, never half-stored."""
    records: list[CommerceRecord] = []
    skipped = 0
    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        try:
            records.extend(mapper(item, *args))
        except MappingError:
            skipped += 1
    return records, skipped
