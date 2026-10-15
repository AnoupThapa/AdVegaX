"""Read API shapes for stores, products and daily figures (task 2A-09, PLAN §11).

Money is returned as exact decimal **strings** in the store currency (never floats) together
with the currency's minor units, so the web app rounds only for display. Every value that can
be missing carries an ``availability`` instead of a 0 (A10).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Availability = Literal["available", "unavailable", "unsupported", "not_synchronized"]


class FigureOut(BaseModel):
    value: Decimal | None
    availability: Availability
    reason: str | None = None


class SyncOut(BaseModel):
    running: bool
    mode: str | None  # initial | reconcile | deep while running
    progress: int | None  # 0-100 during the first import
    last_reconciled_at: datetime | None
    last_deep_reconciled_at: datetime | None
    last_error_code: str | None
    last_error_at: datetime | None


class HealthOut(BaseModel):
    """Store configuration found by the daily check (2B-06): a plain message key for the web
    app (e.g. ``cost_of_goods_off``, ``woocommerce_too_old``, ``timezone_unknown``), or None."""

    code: str | None
    checked_at: datetime | None


class StoreOut(BaseModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    provider: str
    domain: str
    name: str | None
    currency: str
    currency_minor_units: int
    timezone: str
    status: str  # importing | active | error | disconnected
    linked: bool
    connection_status: str
    history_from: datetime | None  # the oldest order history the platform allows
    first_import_completed_at: datetime | None
    sync: SyncOut
    created_at: datetime
    # Self-hosted platforms (2B-06); empty for Shopify.
    site_url: str | None = None
    platform_version: str | None = None
    health: HealthOut | None = None
    counted_statuses: list[str] | None = None  # order statuses the figures count (Q-2B-2)


class InventoryOut(BaseModel):
    availability: Availability
    tracked: bool | None
    available: int | None
    synced_at: datetime | None


class CostOut(BaseModel):
    availability: Availability
    unit_cost: Decimal | None
    source: str | None  # import_snapshot | platform
    effective_from: datetime | None
    reason: str | None = None


class VariantOut(BaseModel):
    id: uuid.UUID
    external_id: str
    title: str | None
    sku: str | None
    price: Decimal | None
    deleted: bool
    inventory: InventoryOut
    cost: CostOut


class ProductOut(BaseModel):
    id: uuid.UUID
    external_id: str
    title: str
    handle: str | None
    product_type: str | None
    vendor: str | None
    status: str
    updated_at: datetime | None
    variants: list[VariantOut]


class ProductPage(BaseModel):
    items: list[ProductOut]
    next_cursor: str | None


class DayOut(BaseModel):
    day: date
    availability: Availability  # not_synchronized before the history start or the import
    gross_sales: Decimal | None
    discounts: Decimal | None
    sales_reversals: Decimal | None
    net_sales: Decimal | None
    shipping: Decimal | None
    taxes: Decimal | None
    duties: Decimal | None
    fees: Decimal | None
    total_sales: Decimal | None
    orders_count: int | None
    cogs: FigureOut
    gross_profit: FigureOut
    cost_coverage: FigureOut


class TotalsOut(BaseModel):
    availability: Availability  # not_synchronized when part of the period is not synced
    gross_sales: Decimal | None
    discounts: Decimal | None
    sales_reversals: Decimal | None
    net_sales: Decimal | None
    shipping: Decimal | None
    taxes: Decimal | None
    duties: Decimal | None
    fees: Decimal | None
    total_sales: Decimal | None
    orders_count: int | None
    cogs: FigureOut
    gross_profit: FigureOut
    gross_margin: FigureOut
    cost_coverage: FigureOut
    shipping_cost: FigureOut
    payment_fees: FigureOut
    new_vs_returning: FigureOut


class DailyMetricsOut(BaseModel):
    store_id: uuid.UUID
    definition_version: str
    currency: str
    currency_minor_units: int
    timezone: str
    from_day: date
    to_day: date
    synced_from: date | None  # first day with complete data (store-local)
    days: list[DayOut]
    totals: TotalsOut


class ResyncOut(BaseModel):
    store_id: uuid.UUID
    job_id: uuid.UUID
    mode: str
