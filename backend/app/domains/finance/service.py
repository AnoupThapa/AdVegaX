"""Recomputing ``financial_daily`` from stored sales records (task 2A-08, PLAN sections 9 and 10).

``recompute_days`` rebuilds the rows for a span of store-local days from ``sales_entries`` and
``orders`` — idempotent, so it can run after every import, reconciliation or webhook. Days with
no activity get no row. Everything runs in the store's tenant context (RLS).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domains.commerce.models import Order, OrderItem, SalesEntry, Store
from app.domains.finance.definitions import (
    DEFINITION_VERSION,
    SaleRow,
    compute_days,
    local_day,
)
from app.domains.finance.models import FinancialDaily
from app.runtime import Runtime

logger = logging.getLogger("advegax.finance")


def store_zone(store: Store) -> ZoneInfo:
    try:
        return ZoneInfo(store.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("store_timezone_invalid", extra={"store_id": str(store.id)})
        return ZoneInfo("UTC")


def _next_day(day: date) -> date:
    """Calendar arithmetic (not a duration setting)."""
    return date.fromordinal(day.toordinal() + 1)


def _bounds(first: date, last: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(first, time.min, tzinfo=tz)
    end = datetime.combine(_next_day(last), time.min, tzinfo=tz)
    return start, end


def recompute_span(session: Session, rt: Runtime, store: Store, first: date, last: date) -> int:
    """Rebuild every day from ``first`` to ``last`` (store-local, inclusive). Returns rows."""
    if last < first:
        return 0
    tz = store_zone(store)
    start, end = _bounds(first, last, tz)
    sales = [
        SaleRow(
            happened_at=row.happened_at,
            action=row.action,
            line_type=row.line_type,
            amount=row.amount,
            discount_amount=row.discount_amount,
            tax_amount=row.tax_amount,
            quantity=row.quantity,
            unit_cost=row.unit_cost,
        )
        for row in session.execute(
            select(
                SalesEntry.happened_at,
                SalesEntry.action,
                SalesEntry.line_type,
                SalesEntry.amount,
                SalesEntry.discount_amount,
                SalesEntry.tax_amount,
                SalesEntry.quantity,
                OrderItem.unit_cost,
            )
            .outerjoin(
                OrderItem,
                (OrderItem.id == SalesEntry.order_item_id)
                & (OrderItem.organization_id == SalesEntry.organization_id),
            )
            .where(
                SalesEntry.store_id == store.id,
                SalesEntry.happened_at >= start,
                SalesEntry.happened_at < end,
            )
        )
    ]
    order_times = session.execute(
        select(Order.ordered_at).where(
            Order.store_id == store.id, Order.ordered_at >= start, Order.ordered_at < end
        )
    ).scalars()
    days = compute_days(sales, order_times, tz)
    skipped = sum(d.skipped_lines for d in days.values())
    if skipped:
        logger.warning(
            "finance_lines_not_counted", extra={"store_id": str(store.id), "count": skipped}
        )

    session.execute(
        delete(FinancialDaily).where(
            FinancialDaily.store_id == store.id,
            FinancialDaily.definition_version == DEFINITION_VERSION,
            FinancialDaily.day >= first,
            FinancialDaily.day <= last,
        )
    )
    now = rt.clock.now()
    rows = [
        {
            "id": uuid.uuid4(),
            "organization_id": store.organization_id,
            "store_id": store.id,
            "day": day,
            "currency": store.currency,
            "definition_version": DEFINITION_VERSION,
            "gross_sales": c.gross_sales,
            "discounts": c.discounts,
            "sales_reversals": c.sales_reversals,
            "net_sales": c.net_sales,
            "shipping": c.shipping,
            "taxes": c.taxes,
            "duties": c.duties,
            "fees": c.fees,
            "total_sales": c.total_sales,
            "orders_count": c.orders_count,
            "cogs": c.cogs,
            "costed_net_sales": c.costed_net_sales,
            "uncosted_lines": c.uncosted_lines,
            "computed_at": now,
        }
        for day, c in sorted(days.items())
        if first <= day <= last
    ]
    if rows:
        session.execute(insert(FinancialDaily).values(rows))
    return len(rows)


def recompute_since(rt: Runtime, org_id: uuid.UUID, store_id: uuid.UUID, since: datetime) -> int:
    """Rebuild from the store-local day of ``since`` through today."""
    with rt.db.transaction(org_id=org_id) as session:
        store = session.get(Store, store_id)
        if store is None:
            return 0
        tz = store_zone(store)
        return recompute_span(
            session, rt, store, local_day(since, tz), local_day(rt.clock.now(), tz)
        )


def order_days(session: Session, store: Store, order_ids: Iterable[uuid.UUID]) -> set[date]:
    """Store-local days touched by these orders (their order date and every sale date)."""
    ids = list(order_ids)
    if not ids:
        return set()
    tz = store_zone(store)
    moments = list(
        session.execute(select(Order.ordered_at).where(Order.id.in_(ids))).scalars()
    ) + list(
        session.execute(
            select(SalesEntry.happened_at).where(SalesEntry.order_id.in_(ids))
        ).scalars()
    )
    return {local_day(m, tz) for m in moments}


def recompute_days(session: Session, rt: Runtime, store: Store, days: Iterable[date]) -> int:
    """Rebuild the given days (each run of consecutive days in one pass)."""
    ordered = sorted(set(days))
    total, run_start, previous = 0, None, None
    for day in ordered:
        if run_start is None:
            run_start = day
        elif previous is not None and day != _next_day(previous):
            total += recompute_span(session, rt, store, run_start, previous)
            run_start = day
        previous = day
    if run_start is not None and previous is not None:
        total += recompute_span(session, rt, store, run_start, previous)
    return total
