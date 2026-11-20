"""Shopify bulk exports and their mapping to normalized commerce records (task 2A-06).

Verified against shopify.dev (Admin GraphQL ``2026-10``) on 2026-10-13:

* ``bulkOperationRunQuery(query:)`` returns ``bulkOperation { id status }`` and ``userErrors``;
  from 2026-01 the operation is polled with ``bulkOperation(id:)`` (fields ``status``,
  ``errorCode``, ``objectCount``, ``url``, ``partialDataUrl``). Statuses include ``CREATED``,
  ``RUNNING``, ``COMPLETED``, ``FAILED``, ``CANCELED``; ``url`` is null when nothing matched.
* Output is JSONL: one node per line; nested-connection children come on later lines with
  ``__parentId``. Limits: ≤ 5 connections, nesting ≤ 2 levels, ≤ 5 concurrent per shop.
* Fields used: ``Product`` (id, title, handle, productType, vendor, status ∈ ACTIVE / ARCHIVED /
  DRAFT / UNLISTED, updatedAt, variants), ``ProductVariant`` (id, title, sku, price: Money,
  updatedAt, inventoryQuantity, inventoryItem), ``InventoryItem`` (id, tracked, unitCost: MoneyV2
  — hidden without the "View product costs" permission), ``Order`` (name, processedAt,
  cancelledAt, test, currencyCode, displayFinancialStatus, the ``*Set`` MoneyBags, refunds — a
  list, lineItems and agreements — connections), ``SalesAgreement`` (id, happenedAt, reason ∈
  OrderActionType, sales), ``Sale`` (id, actionType ∈ SaleActionType, lineType ∈ SaleLineType,
  quantity, totalAmount, totalDiscountAmountBeforeTaxes, totalTaxAmount; ``ProductSale.lineItem``),
  ``LineItem`` (id, title, sku, quantity, variant, originalUnitPriceSet), ``Refund`` (id,
  createdAt, totalRefundedSet). Amounts are read in the **shop currency** (``shopMoney``).

Child rows are recognised by their fields rather than by type names in ids. No customer,
address or contact field is requested (Q8): ``Order.customer`` and addresses are left out until
the scope question is settled on a development store (2A-01).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.providers.base.errors import InvalidRequestError
from app.providers.base.types import (
    BulkKind,
    BulkOperationState,
    BulkStatus,
    CommerceOrderLineRecord,
    CommerceOrderRecord,
    CommerceProductRecord,
    CommerceRecord,
    CommerceRefundRecord,
    CommerceSaleRecord,
    CommerceVariantRecord,
)

logger = logging.getLogger("advegax.providers.shopify.bulk")


class BulkExportRejectedError(InvalidRequestError):
    """Shopify refused to start the export (``userErrors``); not retried automatically."""

    code = "bulk_export_rejected"


RUN_MUTATION = """
mutation AdVegaXBulkExport($query: String!) {
  bulkOperationRunQuery(query: $query) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""

STATE_QUERY = """
query AdVegaXBulkState($id: ID!) {
  bulkOperation(id: $id) { id status errorCode objectCount url partialDataUrl }
}
"""

_MONEY = "shopMoney { amount currencyCode }"

# Field lists shared by bulk exports and by single-object fetches (webhooks, 2A-07), so both
# paths produce identical nodes and go through the same mapping.
PRODUCT_FIELDS = "id title handle productType vendor status updatedAt"
VARIANT_FIELDS = (
    "id title sku price updatedAt inventoryQuantity "
    "inventoryItem { id tracked unitCost { amount currencyCode } }"
)
ORDER_FIELDS = f"""id name processedAt updatedAt cancelledAt test currencyCode
      displayFinancialStatus
      totalDiscountsSet {{ {_MONEY} }}
      totalShippingPriceSet {{ {_MONEY} }}
      totalTaxSet {{ {_MONEY} }}
      totalRefundedSet {{ {_MONEY} }}
      totalPriceSet {{ {_MONEY} }}
      refunds {{ id createdAt totalRefundedSet {{ {_MONEY} }} }}"""
LINE_FIELDS = f"id title sku quantity variant {{ id }} originalUnitPriceSet {{ {_MONEY} }}"
AGREEMENT_FIELDS = "id happenedAt reason"
SALE_FIELDS = f"""id actionType lineType quantity
          totalAmount {{ {_MONEY} }}
          totalDiscountAmountBeforeTaxes {{ {_MONEY} }}
          totalTaxAmount {{ {_MONEY} }}
          ... on ProductSale {{ lineItem {{ id }} }}"""


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _search(created_since: datetime | None, updated_since: datetime | None) -> str:
    terms = []
    if created_since is not None:
        terms.append(f"created_at:>='{_stamp(created_since)}'")
    if updated_since is not None:
        terms.append(f"updated_at:>='{_stamp(updated_since)}'")
    return f'(query: "{" AND ".join(terms)}")' if terms else ""


def catalogue_query(updated_since: datetime | None = None) -> str:
    """Products (optionally only those updated since a time) with their variants."""
    return f"""
{{
  products{_search(None, updated_since)} {{
    edges {{ node {{
      {PRODUCT_FIELDS}
      variants {{ edges {{ node {{
        {VARIANT_FIELDS}
      }} }} }}
    }} }}
  }}
}}
"""


CATALOGUE_QUERY = catalogue_query()


def orders_query(
    created_since: datetime | None = None, updated_since: datetime | None = None
) -> str:
    """Orders (filtered by creation and/or update time), with lines, sales agreements and
    refunds. Four connections (orders, lineItems, agreements, sales) and two levels of
    nesting — within Shopify's bulk limits. ``refunds`` is a plain list, not a connection.
    """
    return f"""
{{
  orders{_search(created_since, updated_since)} {{
    edges {{ node {{
      {ORDER_FIELDS}
      lineItems {{ edges {{ node {{
        {LINE_FIELDS}
      }} }} }}
      agreements {{ edges {{ node {{
        {AGREEMENT_FIELDS}
        sales {{ edges {{ node {{
          {SALE_FIELDS}
        }} }} }}
      }} }} }}
    }} }}
  }}
}}
"""


# Single-object fetches (2A-07). Page sizes keep each query well under Shopify's 1,000-point
# single-query limit; a longer nested list is reported as incomplete and the store is then
# reconciled through a bulk export instead.
PRODUCT_FETCH = f"""
query AdVegaXProduct($id: ID!) {{
  product(id: $id) {{
    {PRODUCT_FIELDS}
    variants(first: 250) {{ pageInfo {{ hasNextPage }} edges {{ node {{ {VARIANT_FIELDS} }} }} }}
  }}
}}
"""

ORDER_FETCH = f"""
query AdVegaXOrder($id: ID!) {{
  order(id: $id) {{
    {ORDER_FIELDS}
    lineItems(first: 100) {{ pageInfo {{ hasNextPage }} edges {{ node {{ {LINE_FIELDS} }} }} }}
    agreements(first: 10) {{
      pageInfo {{ hasNextPage }}
      edges {{ node {{
        {AGREEMENT_FIELDS}
        sales(first: 50) {{ pageInfo {{ hasNextPage }} edges {{ node {{
          {SALE_FIELDS}
        }} }} }}
      }} }}
    }}
  }}
}}
"""


def _children(node: dict[str, Any], field_name: str) -> tuple[list[dict[str, Any]], bool]:
    """Nodes of a fetched connection and whether it was complete."""
    connection = node.pop(field_name, None)
    if not isinstance(connection, dict):
        return [], True
    info = connection.get("pageInfo")
    complete = not (isinstance(info, dict) and info.get("hasNextPage") is True)
    edges = connection.get("edges")
    nodes = [
        e["node"]
        for e in (edges if isinstance(edges, list) else [])
        if isinstance(e, dict) and isinstance(e.get("node"), dict)
    ]
    return nodes, complete


def flatten_product(product: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """A fetched product as bulk-style nodes (children carry ``__parentId``)."""
    product = dict(product)
    variants, complete = _children(product, "variants")
    parent = product.get("id")
    return [product, *({**v, "__parentId": parent} for v in variants)], complete


def flatten_order(order: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    order = dict(order)
    parent = order.get("id")
    lines, lines_complete = _children(order, "lineItems")
    agreements, agreements_complete = _children(order, "agreements")
    nodes: list[dict[str, Any]] = [order, *({**line, "__parentId": parent} for line in lines)]
    complete = lines_complete and agreements_complete
    for agreement in agreements:
        agreement = dict(agreement)
        sales, sales_complete = _children(agreement, "sales")
        complete = complete and sales_complete
        nodes.append({**agreement, "__parentId": parent})
        nodes.extend({**sale, "__parentId": agreement.get("id")} for sale in sales)
    return nodes, complete


# ------------------------------------------------------------------ operation state
_STATUS = {
    "CREATED": BulkStatus.RUNNING,
    "RUNNING": BulkStatus.RUNNING,
    "CANCELING": BulkStatus.RUNNING,
    "COMPLETED": BulkStatus.COMPLETED,
    "FAILED": BulkStatus.FAILED,
    "CANCELED": BulkStatus.FAILED,
    "EXPIRED": BulkStatus.FAILED,
}


def parse_state(node: Any) -> BulkOperationState:
    if not isinstance(node, dict):
        return BulkOperationState(BulkStatus.FAILED, error_code="operation_missing")
    raw = str(node.get("status") or "").upper()
    status = _STATUS.get(raw, BulkStatus.RUNNING if not raw else BulkStatus.FAILED)
    error = node.get("errorCode")
    count = node.get("objectCount")
    url = node.get("url")
    return BulkOperationState(
        status=status,
        result_url=url if isinstance(url, str) and url else None,
        error_code=(str(error).lower()[:64] if error else None)
        or (raw.lower() if status is BulkStatus.FAILED else None),
        object_count=int(count) if isinstance(count, (int, str)) and str(count).isdigit() else None,
    )


# ------------------------------------------------------------------ value helpers
def _text(value: object, limit: int = 512) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:limit]


def _id(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 255 else None


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _money(bag: object) -> tuple[Decimal | None, str | None]:
    """``MoneyBag`` → shop-currency amount and currency."""
    if not isinstance(bag, dict):
        return None, None
    shop = bag.get("shopMoney")
    if not isinstance(shop, dict):
        return None, None
    currency = shop.get("currencyCode")
    return _decimal(shop.get("amount")), currency if isinstance(currency, str) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


_PRODUCT_STATUS = {
    "ACTIVE": "active",
    "ARCHIVED": "archived",
    "DRAFT": "draft",
    "UNLISTED": "unlisted",
}
_LINE_TYPES = {
    "PRODUCT": "product",
    "SHIPPING": "shipping",
    "DUTY": "duty",
    "FEE": "fee",
    "ADDITIONAL_FEE": "additional_fee",
    "ADJUSTMENT": "adjustment",
    "TIP": "tip",
    "GIFT_CARD": "gift_card",
}
_ACTIONS = {"ORDER": "order", "RETURN": "return", "UPDATE": "update"}
_REASONS = {"ORDER": "order", "ORDER_EDIT": "order_edit", "REFUND": "refund", "RETURN": "return"}


# ------------------------------------------------------------------ JSONL mapping
@dataclass
class _Agreement:
    order_id: str
    happened_at: datetime
    reason: str


@dataclass
class ExportReader:
    """Maps one export's JSONL lines to records. Holds only small id maps in memory."""

    kind: BulkKind
    skipped_lines: int = 0
    _agreements: dict[str, _Agreement] = field(default_factory=dict)
    _excluded_orders: set[str] = field(default_factory=set)

    def records(self, lines: Iterator[bytes]) -> Iterator[CommerceRecord]:
        for line in lines:
            try:
                node = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                self.skipped_lines += 1
                continue
            if not isinstance(node, dict):
                self.skipped_lines += 1
                continue
            yield from self._map(node)
        if self.skipped_lines:
            logger.warning("bulk_lines_skipped", extra={"count": self.skipped_lines})

    def nodes(self, nodes: Iterable[dict[str, Any]]) -> list[CommerceRecord]:
        """Map already-parsed nodes (a single-object fetch, flattened)."""
        return [record for node in nodes for record in self._map(node)]

    def _map(self, node: dict[str, Any]) -> list[CommerceRecord]:
        node_id = _id(node.get("id"))
        if node_id is None:
            self.skipped_lines += 1
            return []
        parent = _id(node.get("__parentId"))
        record: CommerceRecord | None
        if self.kind is BulkKind.CATALOGUE:
            if "inventoryItem" in node and parent:
                record = self._variant(node_id, parent, node)
            elif "handle" in node:
                record = self._product(node_id, node)
            else:
                self.skipped_lines += 1
                return []
        elif "actionType" in node and parent:
            record = self._sale(node_id, parent, node)
        elif "happenedAt" in node and parent:
            self._agreement(node_id, parent, node)
            return []
        elif "originalUnitPriceSet" in node and parent:
            record = self._line(node_id, parent, node)
        elif "processedAt" in node:
            order = self._order(node_id, node)
            if order is None:
                return []
            return [order, *self._refunds(node_id, order.currency, node.get("refunds"))]
        else:
            self.skipped_lines += 1
            return []
        return [record] if record is not None else []

    # catalogue
    def _product(self, node_id: str, node: dict[str, Any]) -> CommerceRecord | None:
        title = _text(node.get("title"))
        if title is None:
            self.skipped_lines += 1
            return None
        return CommerceProductRecord(
            external_id=node_id,
            title=title,
            status=_PRODUCT_STATUS.get(str(node.get("status")), "draft"),
            handle=_text(node.get("handle"), 255),
            product_type=_text(node.get("productType"), 255),
            vendor=_text(node.get("vendor"), 255),
            updated_at=_time(node.get("updatedAt")),
        )

    def _variant(self, node_id: str, parent: str, node: dict[str, Any]) -> CommerceRecord:
        item = node.get("inventoryItem") if isinstance(node.get("inventoryItem"), dict) else {}
        assert isinstance(item, dict)
        tracked = item.get("tracked") if isinstance(item.get("tracked"), bool) else None
        cost = item.get("unitCost") if isinstance(item.get("unitCost"), dict) else None
        currency = cost.get("currencyCode") if cost else None
        return CommerceVariantRecord(
            external_id=node_id,
            product_external_id=parent,
            title=_text(node.get("title")),
            sku=_text(node.get("sku"), 255),
            price=_decimal(node.get("price")),
            inventory_item_id=_id(item.get("id")),
            inventory_tracked=tracked,
            # Quantity only means something for tracked items; otherwise "not tracked" (None).
            inventory_available=_int(node.get("inventoryQuantity")) if tracked else None,
            unit_cost=_decimal(cost.get("amount")) if cost else None,
            cost_currency=currency if isinstance(currency, str) else None,
            updated_at=_time(node.get("updatedAt")),
        )

    # orders
    def _order(self, node_id: str, node: dict[str, Any]) -> CommerceOrderRecord | None:
        ordered_at = _time(node.get("processedAt"))
        currency = node.get("currencyCode")
        if node.get("test") is True or ordered_at is None or not isinstance(currency, str):
            self._excluded_orders.add(node_id)  # test orders are excluded (PHASE_02A_PLAN §8)
            if node.get("test") is not True:
                self.skipped_lines += 1
            return None
        status = node.get("displayFinancialStatus")
        return CommerceOrderRecord(
            external_id=node_id,
            currency=currency,
            ordered_at=ordered_at,
            order_number=_text(node.get("name"), 64),
            cancelled_at=_time(node.get("cancelledAt")),
            financial_status=status.lower()[:32] if isinstance(status, str) else None,
            discount_amount=_money(node.get("totalDiscountsSet"))[0],
            shipping_amount=_money(node.get("totalShippingPriceSet"))[0],
            tax_amount=_money(node.get("totalTaxSet"))[0],
            refund_amount=_money(node.get("totalRefundedSet"))[0],
            total_amount=_money(node.get("totalPriceSet"))[0],
            updated_at=_time(node.get("updatedAt")),
        )

    def _refunds(
        self, order_id: str, currency: str, refunds: object
    ) -> Iterator[CommerceRefundRecord]:
        if not isinstance(refunds, list):
            return
        for refund in refunds:
            if not isinstance(refund, dict):
                continue
            refund_id, created = _id(refund.get("id")), _time(refund.get("createdAt"))
            if refund_id is None or created is None:
                continue
            amount, refund_currency = _money(refund.get("totalRefundedSet"))
            yield CommerceRefundRecord(
                external_id=refund_id,
                order_external_id=order_id,
                processed_at=created,
                currency=refund_currency or currency,
                total_amount=amount,
            )

    def _line(self, node_id: str, parent: str, node: dict[str, Any]) -> CommerceRecord | None:
        if parent in self._excluded_orders:
            return None
        quantity = _int(node.get("quantity"))
        if quantity is None:
            self.skipped_lines += 1
            return None
        variant = node.get("variant")
        return CommerceOrderLineRecord(
            external_id=node_id,
            order_external_id=parent,
            quantity=quantity,
            variant_external_id=_id(variant.get("id")) if isinstance(variant, dict) else None,
            title=_text(node.get("title")),
            sku=_text(node.get("sku"), 255),
            unit_price=_money(node.get("originalUnitPriceSet"))[0],
        )

    def _agreement(self, node_id: str, parent: str, node: dict[str, Any]) -> None:
        happened = _time(node.get("happenedAt"))
        if parent in self._excluded_orders:
            return
        if happened is None:
            self.skipped_lines += 1
            return
        self._agreements[node_id] = _Agreement(
            parent, happened, _REASONS.get(str(node.get("reason")), "other")
        )

    def _sale(self, node_id: str, parent: str, node: dict[str, Any]) -> CommerceRecord | None:
        agreement = self._agreements.get(parent)
        if agreement is None:
            # Parent not seen: an excluded (test) order's agreement, or out-of-order data.
            return None
        amount, currency = _money(node.get("totalAmount"))
        discount, _ = _money(node.get("totalDiscountAmountBeforeTaxes"))
        tax, _ = _money(node.get("totalTaxAmount"))
        if amount is None or currency is None:
            self.skipped_lines += 1
            return None
        line_item = node.get("lineItem")
        return CommerceSaleRecord(
            external_id=node_id,
            agreement_external_id=parent,
            order_external_id=agreement.order_id,
            happened_at=agreement.happened_at,
            agreement_reason=agreement.reason,
            action=_ACTIONS.get(str(node.get("actionType")), "other"),
            line_type=_LINE_TYPES.get(str(node.get("lineType")), "other"),
            amount=amount,
            discount_amount=discount or Decimal(0),
            tax_amount=tax or Decimal(0),
            currency=currency,
            quantity=_int(node.get("quantity")),
            line_item_external_id=(
                _id(line_item.get("id")) if isinstance(line_item, dict) else None
            ),
        )
