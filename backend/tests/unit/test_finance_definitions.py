"""Finance core v1 golden tests (task 2A-08, PHASE_02A_PLAN §10).

Every expected figure below is calculated by hand from the definitions in
``app/domains/finance/definitions.py`` and must match to the cent (exactly, as Decimal).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D  # noqa: N817 - short name keeps hand calculations readable
from zoneinfo import ZoneInfo

import pytest
from app.domains.finance.definitions import (
    DEFINITION_VERSION,
    SaleRow,
    compute_days,
    for_display,
    minor_units,
    summarize,
)

UTC_TZ = ZoneInfo("UTC")
SYDNEY = ZoneInfo("Australia/Sydney")


def at(day: int, hour: int = 12, month: int = 10, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def sale(
    when,
    amount,
    *,
    discount="0",
    tax="0",
    action="order",
    line="product",
    qty=None,
    cost=None,
):
    return SaleRow(
        happened_at=when,
        action=action,
        line_type=line,
        amount=D(amount),
        discount_amount=D(discount),
        tax_amount=D(tax),
        quantity=qty,
        unit_cost=D(cost) if cost is not None else None,
    )


def test_definition_version_is_recorded():
    assert DEFINITION_VERSION == "finance-v1"


def test_order_with_line_and_order_discounts_shipping_and_tax():
    # 2 x 25.00 with a 5.00 line discount and a 3.00 share of an order discount; 10% tax.
    # Shipping 8.00 with a 2.00 shipping discount; 0.60 tax on shipping.
    sales = [
        sale(at(5), "46.20", discount="8.00", tax="4.20", qty=2, cost="9.00"),
        sale(at(5), "6.60", tax="0.60", line="shipping"),
    ]
    (day,) = compute_days(sales, [at(5)], UTC_TZ).values()
    assert day.gross_sales == D("50.00")  # 2 x 25.00
    assert day.discounts == D("8.00")
    assert day.sales_reversals == D("0")
    assert day.net_sales == D("42.00")
    assert day.shipping == D("6.00")  # 8.00 - 2.00 discount
    assert day.taxes == D("4.80")
    assert day.total_sales == D("52.80")  # 42.00 + 4.80 + 6.00
    assert day.orders_count == 1
    assert day.cogs == D("18.00")
    assert (day.costed_net_sales, day.uncosted_lines) == (D("42.00"), 0)


def test_tax_inclusive_store_gives_the_same_ex_tax_figures():
    # Price 22.00 including 10% GST; 2.20 discount (incl.) = 2.00 before tax; tax 1.80.
    (day,) = compute_days(
        [sale(at(5), "19.80", discount="2.00", tax="1.80", qty=1, cost="5")], [], UTC_TZ
    ).values()
    assert (day.gross_sales, day.discounts, day.net_sales) == (D("20.00"), D("2.00"), D("18.00"))
    assert day.total_sales == D("19.80")


def test_partial_refund_in_a_later_month_is_dated_when_processed():
    sales = [
        sale(at(28, month=9), "44.00", tax="4.00", qty=2, cost="10"),
        sale(at(3), "-22.00", tax="-2.00", action="return", qty=-1, cost="10"),
    ]
    days = compute_days(sales, [at(28, month=9)], UTC_TZ)
    september, october = days[date(2026, 9, 28)], days[date(2026, 10, 3)]
    assert (september.gross_sales, september.net_sales, september.cogs) == (
        D("40.00"),
        D("40.00"),
        D("20"),
    )
    assert october.gross_sales == D("0")
    assert october.sales_reversals == D("20.00")
    assert october.net_sales == D("-20.00")
    assert october.taxes == D("-2.00")
    assert october.total_sales == D("-22.00")
    assert october.cogs == D("-10")  # returned unit's cost comes back on the refund day
    assert october.orders_count == 0


def test_cancelled_order_counts_on_its_day_and_reverses_on_the_cancel_day():
    sales = [
        sale(at(5), "33.00", tax="3.00", qty=3, cost="4"),
        sale(at(5), "5.00", line="shipping"),
        sale(at(6), "-33.00", tax="-3.00", action="return", qty=-3, cost="4"),
        sale(at(6), "-5.00", action="return", line="shipping"),
    ]
    days = compute_days(sales, [at(5)], UTC_TZ)
    assert days[date(2026, 10, 5)].total_sales == D("38.00")
    cancel = days[date(2026, 10, 6)]
    assert (cancel.sales_reversals, cancel.shipping, cancel.total_sales) == (
        D("30.00"),
        D("-5.00"),
        D("-38.00"),
    )
    assert summarize(days.values()).net_sales == D("0")


def test_order_edit_price_change_is_a_reversal_without_unit_cost():
    # An edit lowers a line's price by 4.00 (+0.40 tax): action "update" — money only.
    sales = [
        sale(at(5), "22.00", tax="2.00", qty=1, cost="8"),
        sale(at(7), "-4.40", tax="-0.40", action="update", cost="8"),
    ]
    edit = compute_days(sales, [], UTC_TZ)[date(2026, 10, 7)]
    assert (edit.sales_reversals, edit.net_sales, edit.cogs) == (D("4.00"), D("-4.00"), D("0"))
    assert edit.costed_net_sales == D("-4.00")


def test_discount_removed_in_an_edit_reduces_reversals():
    edit = compute_days([sale(at(7), "3.30", tax="0.30", action="update", cost="1")], [], UTC_TZ)[
        date(2026, 10, 7)
    ]
    assert edit.sales_reversals == D("-3.00")
    assert edit.net_sales == D("3.00")


def test_refunded_shipping_duties_fees_and_adjustments():
    sales = [
        sale(at(5), "15.00", line="duty"),
        sale(at(5), "2.20", tax="0.20", line="fee"),
        sale(at(5), "1.00", line="additional_fee"),
        sale(at(9), "-6.00", line="shipping", action="return"),
        sale(at(9), "-1.50", line="adjustment", action="update"),
    ]
    days = compute_days(sales, [], UTC_TZ)
    first, later = days[date(2026, 10, 5)], days[date(2026, 10, 9)]
    assert (first.duties, first.fees, first.taxes, first.total_sales) == (
        D("15.00"),
        D("3.00"),
        D("0.20"),
        D("18.20"),
    )
    assert (later.shipping, later.sales_reversals, later.net_sales) == (
        D("-6.00"),
        D("1.50"),
        D("-1.50"),
    )
    assert later.total_sales == D("-7.50")


def test_gift_cards_tips_and_unknown_lines_are_not_sales():
    sales = [
        sale(at(5), "50.00", line="gift_card", qty=1),
        sale(at(5), "3.00", line="tip"),
        sale(at(5), "9.99", line="other"),
    ]
    (day,) = compute_days(sales, [at(5)], UTC_TZ).values()
    assert (day.gross_sales, day.total_sales, day.taxes) == (D("0"), D("0"), D("0"))
    assert day.skipped_lines == 1  # only "other" is logged (a platform type to look at)
    assert day.cogs == D("0") and day.orders_count == 1


def test_missing_cost_makes_cogs_unknown_never_zero():
    sales = [
        sale(at(5), "30.00", qty=1, cost="12"),
        sale(at(5), "70.00", qty=1, cost=None),  # no cost known for this product
    ]
    (day,) = compute_days(sales, [], UTC_TZ).values()
    assert day.cogs is None
    assert (day.uncosted_lines, day.costed_net_sales) == (1, D("30.00"))
    summary = summarize([day])
    assert summary.cogs.value is None and summary.cogs.availability == "unavailable"
    assert summary.gross_profit.value is None
    assert summary.gross_profit.reason == "missing_product_costs"
    assert summary.gross_margin.value is None
    assert summary.cost_coverage.value == D("0.3")  # 30 of 100 net sales have a cost


def test_cost_change_mid_period_uses_each_line_cost():
    sales = [
        sale(at(5), "20.00", qty=2, cost="6.00"),  # cost before the change
        sale(at(20), "20.00", qty=2, cost="7.50"),  # after the change
    ]
    summary = summarize(compute_days(sales, [], UTC_TZ).values())
    assert summary.cogs.value == D("27.00")  # 2 x 6.00 + 2 x 7.50
    assert summary.gross_profit.value == D("13.00")
    assert summary.gross_margin.value == D("0.325")


def test_store_time_zone_decides_the_day():
    # 14:30 UTC on 5 Oct is 01:30 on 6 Oct in Sydney (UTC+11 in October).
    days = compute_days([sale(at(5, hour=14, minute=30), "10.00")], [], SYDNEY)
    assert list(days) == [date(2026, 10, 6)]
    # 12:59 UTC on 5 Oct is 23:59 on 5 Oct in Sydney.
    days = compute_days([sale(at(5, hour=12, minute=59), "10.00")], [], SYDNEY)
    assert list(days) == [date(2026, 10, 5)]


def test_daylight_saving_change_day_boundaries():
    # Sydney moves from UTC+10 to UTC+11 at 02:00 local on Sunday 4 Oct 2026.
    before = at(3, hour=13, minute=59)  # 23:59 Sat 3 Oct (UTC+10)
    after_midnight = at(3, hour=14, minute=0)  # 00:00 Sun 4 Oct (UTC+10)
    end_of_sunday = at(4, hour=12, minute=59)  # 23:59 Sun 4 Oct (UTC+11)
    monday = at(4, hour=13, minute=0)  # 00:00 Mon 5 Oct (UTC+11)
    days = compute_days(
        [sale(m, "1.00") for m in (before, after_midnight, end_of_sunday, monday)], [], SYDNEY
    )
    assert {d: v.gross_sales for d, v in days.items()} == {
        date(2026, 10, 3): D("1.00"),
        date(2026, 10, 4): D("2.00"),  # the 23-hour day
        date(2026, 10, 5): D("1.00"),
    }


def test_orders_are_counted_on_their_order_day_only():
    days = compute_days([], [at(5), at(5, hour=20), at(6)], UTC_TZ)
    assert {d: v.orders_count for d, v in days.items()} == {
        date(2026, 10, 5): 2,
        date(2026, 10, 6): 1,
    }


def test_period_summary_and_unsupported_figures():
    days = compute_days(
        [
            sale(at(5), "110.00", discount="10.00", tax="10.00", qty=2, cost="20"),
            sale(at(6), "-55.00", tax="-5.00", action="return", qty=-1, cost="20"),
        ],
        [at(5)],
        UTC_TZ,
    )
    s = summarize(days.values())
    assert (s.gross_sales, s.discounts, s.sales_reversals, s.net_sales) == (
        D("110.00"),  # net 100.00 + 10.00 discount
        D("10.00"),
        D("50.00"),
        D("50.00"),
    )
    assert (s.taxes, s.total_sales, s.orders_count) == (D("5.00"), D("55.00"), 1)
    assert s.cogs.value == D("20")  # 2 x 20 sold - 1 x 20 returned
    assert s.gross_profit.value == D("30.00")
    assert s.gross_margin.value == D("0.6")
    assert s.cost_coverage.value == D("1")
    for figure in (s.shipping_cost, s.payment_fees):
        assert (figure.value, figure.availability) == (None, "unsupported")
    assert (s.new_vs_returning.value, s.new_vs_returning.availability) == (None, "unavailable")


def test_no_net_sales_means_margin_and_coverage_are_not_available():
    s = summarize([])
    assert s.net_sales == D("0")
    assert s.gross_profit.value == D("0")  # nothing sold, nothing uncosted: a real zero
    assert (s.gross_margin.value, s.gross_margin.reason) == (None, "no_net_sales")
    assert s.cost_coverage.value is None


@pytest.mark.parametrize(
    ("value", "currency", "shown"),
    [
        ("2.345", "AUD", "2.34"),  # half-even: to the even neighbour
        ("2.355", "AUD", "2.36"),
        ("-18.905", "USD", "-18.90"),
        ("1234.5", "JPY", "1234"),
        ("1235.5", "JPY", "1236"),
        ("1.2345", "KWD", "1.234"),
        ("10", "NPR", "10.00"),
    ],
)
def test_display_rounding_half_even_to_minor_unit(value, currency, shown):
    assert str(for_display(D(value), currency)) == shown


def test_minor_units():
    assert (minor_units("aud"), minor_units("JPY"), minor_units("BHD")) == (2, 0, 3)
