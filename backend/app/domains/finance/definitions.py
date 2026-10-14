"""Finance core v1 — the one place store figures are defined (task 2A-08, PLAN §10, MASTER §7).

Built from the platform's **sales records** (``sales_entries``: one row per sale or reversal,
each with its own date), mirroring Shopify's Sales report: a sale counts on the day it
happened (an order on its order date), a reversal (return, cancellation, edit, refunded
shipping …) on the day it was processed. Days are in the **store's time zone**; amounts are
``Decimal`` in the store currency and are never rounded here (rounding is for display only).

Per sale (Shopify ``Sale``): ``amount`` = total after taxes and discounts, ``tax_amount`` =
its taxes, ``discount_amount`` = discounts allocated before taxes. Hence, excluding tax:

* net of the line   = amount - tax
* gross of the line = net + discount   (price x quantity before discounts)

This holds for tax-inclusive and tax-exclusive stores alike.

=====================  =======================================================================
Component              Definition v1
=====================  =======================================================================
gross_sales            product lines, action "order": sum  (net + discount)
discounts              product lines, action "order": sum  discount
sales_reversals        product lines with any other action (return / update / other) and price
                       adjustments: -sum  net   (positive when money was given back)
net_sales              gross_sales - discounts - sales_reversals  (= sum  net of product lines and
                       adjustments)
shipping               shipping lines: sum  net  (charges - shipping discounts - refunded shipping)
duties, fees           duty lines / fee + additional-fee lines: sum  net
taxes                  sum  tax of every counted line
total_sales            net_sales + taxes + duties + shipping + fees  (Shopify "Total sales")
orders_count           orders whose order date is the day (test orders are never imported)
cogs                   sum  quantity x unit cost for product lines: + on the order day, - on the
                       return day; **NULL when any of the day's product lines has no cost**
costed_net_sales       net sales of product lines whose cost is known (cost coverage)
uncosted_lines         product order/return lines without a known cost
=====================  =======================================================================

Gift-card sales (a liability, not revenue) and tips are not counted; nor are line types the
platform adds in future ("other") — they are logged so a new type is noticed.
Derived figures (gross profit, margin, coverage) are computed on read by ``summarize``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from zoneinfo import ZoneInfo

DEFINITION_VERSION = "finance-v1"
ZERO = Decimal(0)

_PRODUCT = "product"
_COUNTED_OTHER = {"shipping": "shipping", "duty": "duties", "fee": "fees", "additional_fee": "fees"}
_NOT_COUNTED = {"gift_card", "tip", "other"}


@dataclass(frozen=True)
class SaleRow:
    happened_at: datetime
    action: str  # order | return | update | other
    line_type: str
    amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    quantity: int | None = None
    unit_cost: Decimal | None = None  # from the order line; None = unknown or no line


@dataclass
class DayComponents:
    gross_sales: Decimal = ZERO
    discounts: Decimal = ZERO
    sales_reversals: Decimal = ZERO
    shipping: Decimal = ZERO
    taxes: Decimal = ZERO
    duties: Decimal = ZERO
    fees: Decimal = ZERO
    orders_count: int = 0
    known_cogs: Decimal = ZERO
    costed_net_sales: Decimal = ZERO
    uncosted_lines: int = 0
    skipped_lines: int = field(default=0, compare=False)

    @property
    def net_sales(self) -> Decimal:
        return self.gross_sales - self.discounts - self.sales_reversals

    @property
    def total_sales(self) -> Decimal:
        return self.net_sales + self.taxes + self.duties + self.shipping + self.fees

    @property
    def cogs(self) -> Decimal | None:
        return None if self.uncosted_lines else self.known_cogs


def local_day(moment: datetime, tz: ZoneInfo) -> date:
    return moment.astimezone(tz).date()


def compute_days(
    sales: Iterable[SaleRow], order_times: Iterable[datetime], tz: ZoneInfo
) -> dict[date, DayComponents]:
    days: dict[date, DayComponents] = {}

    def day(moment: datetime) -> DayComponents:
        return days.setdefault(local_day(moment, tz), DayComponents())

    for ordered_at in order_times:
        day(ordered_at).orders_count += 1

    for sale in sales:
        target = day(sale.happened_at)
        net = sale.amount - sale.tax_amount
        if sale.line_type in _NOT_COUNTED:
            if sale.line_type == "other":
                target.skipped_lines += 1
            continue
        target.taxes += sale.tax_amount
        if sale.line_type in _COUNTED_OTHER:
            name = _COUNTED_OTHER[sale.line_type]
            setattr(target, name, getattr(target, name) + net)
            continue
        if sale.line_type == "adjustment":
            target.sales_reversals -= net
            continue
        # Product lines.
        if sale.action == "order":
            target.gross_sales += net + sale.discount_amount
            target.discounts += sale.discount_amount
        else:
            target.sales_reversals -= net
        _add_cost(target, sale, net)
    return days


def _add_cost(target: DayComponents, sale: SaleRow, net: Decimal) -> None:
    moves_units = sale.action in ("order", "return")
    if sale.unit_cost is None:
        if moves_units:
            target.uncosted_lines += 1
        return
    target.costed_net_sales += net
    if moves_units and sale.quantity is not None:
        units = abs(sale.quantity)
        sign = 1 if sale.action == "order" else -1
        target.known_cogs += sign * units * sale.unit_cost


# ------------------------------------------------------------------ reading a period
@dataclass(frozen=True)
class Figure:
    """A derived figure with its availability (A10): ``value`` is None unless available."""

    value: Decimal | None
    availability: str  # available | unavailable | unsupported
    reason: str | None = None


def _available(value: Decimal) -> Figure:
    return Figure(value, "available")


def _missing(availability: str, reason: str) -> Figure:
    return Figure(None, availability, reason)


@dataclass(frozen=True)
class PeriodSummary:
    gross_sales: Decimal
    discounts: Decimal
    sales_reversals: Decimal
    net_sales: Decimal
    shipping: Decimal
    taxes: Decimal
    duties: Decimal
    fees: Decimal
    total_sales: Decimal
    orders_count: int
    cogs: Figure
    gross_profit: Figure
    gross_margin: Figure
    cost_coverage: Figure
    shipping_cost: Figure
    payment_fees: Figure
    new_vs_returning: Figure


def summarize(days: Iterable[DayComponents]) -> PeriodSummary:
    """Totals for a period plus derived figures, each with its availability."""
    rows = list(days)
    total = DayComponents()
    for row in rows:
        for name in (
            "gross_sales",
            "discounts",
            "sales_reversals",
            "shipping",
            "taxes",
            "duties",
            "fees",
            "known_cogs",
            "costed_net_sales",
        ):
            setattr(total, name, getattr(total, name) + getattr(row, name))
        total.orders_count += row.orders_count
        total.uncosted_lines += row.uncosted_lines
    net = total.net_sales

    if total.uncosted_lines:
        cogs = _missing("unavailable", "missing_product_costs")
        profit = _missing("unavailable", "missing_product_costs")
    else:
        cogs = _available(total.known_cogs)
        profit = _available(net - total.known_cogs)
    if profit.value is not None and net != ZERO:
        margin = _available(profit.value / net)
    elif profit.value is None:
        margin = _missing("unavailable", "missing_product_costs")
    else:
        margin = _missing("unavailable", "no_net_sales")
    coverage = (
        _available(total.costed_net_sales / net)
        if net != ZERO
        else _missing("unavailable", "no_net_sales")
    )
    return PeriodSummary(
        gross_sales=total.gross_sales,
        discounts=total.discounts,
        sales_reversals=total.sales_reversals,
        net_sales=net,
        shipping=total.shipping,
        taxes=total.taxes,
        duties=total.duties,
        fees=total.fees,
        total_sales=total.total_sales,
        orders_count=total.orders_count,
        cogs=cogs,
        gross_profit=profit,
        gross_margin=margin,
        cost_coverage=coverage,
        # Not provided reliably by Shopify (PLAN §3): shown as "Not available", never 0.
        shipping_cost=_missing("unsupported", "not_provided_by_platform"),
        payment_fees=_missing("unsupported", "not_provided_by_platform"),
        # Needs the hashed customer key, not collected until the scope check (2A-06 dev. 2).
        new_vs_returning=_missing("unavailable", "customer_key_not_collected"),
    )


# ------------------------------------------------------------------ display rounding
_MINOR_UNITS = {
    **dict.fromkeys(
        (
            [
                "BIF",
                "CLP",
                "DJF",
                "GNF",
                "ISK",
                "JPY",
                "KMF",
                "KRW",
                "PYG",
                "RWF",
                "UGX",
                "UYI",
                "VND",
                "VUV",
                "XAF",
                "XOF",
                "XPF",
            ]
        ),
        0,
    ),
    **dict.fromkeys(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"], 3),
}


def minor_units(currency: str) -> int:
    """ISO 4217 minor units (2 unless listed)."""
    return _MINOR_UNITS.get(currency.upper(), 2)


def for_display(value: Decimal, currency: str) -> Decimal:
    """Round half-even to the currency's minor unit — only when showing a figure."""
    return value.quantize(Decimal(1).scaleb(-minor_units(currency)), rounding=ROUND_HALF_EVEN)
