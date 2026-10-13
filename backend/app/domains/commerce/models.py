"""Platform-neutral commerce model (Phase 2A, PHASE_02A_PLAN §8).

Stores, catalogue, cost history, orders, sales entries and refunds. Nothing here is specific to
Shopify: providers map their data into these tables (D4, D19). Every table is tenant-owned with
composite foreign keys ``(organization_id, parent_id)``, so a row can never point at another
organization's data even if application code is wrong, and Row-Level Security applies on top.

Money is ``Decimal`` (``NUMERIC(20, 6)``) in the store's currency; missing values are ``NULL``
with an explicit source/availability marker — never 0 (A10).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

MONEY = Numeric(20, 6)
TZ = DateTime(timezone=True)

STORE_STATUSES = ("importing", "active", "disconnected", "error")
PRODUCT_STATUSES = ("active", "draft", "archived", "unlisted", "deleted")
COST_SOURCES = ("platform", "import_snapshot")
LINE_COST_SOURCES = ("order_time", "import_time")
# Verified Shopify enums (2026-10, migration 0008): a sale's action and its agreement's reason.
SALE_ACTIONS = ("order", "return", "update", "other")
AGREEMENT_REASONS = ("order", "order_edit", "refund", "return", "other")
SALE_LINE_TYPES = (
    "product",
    "shipping",
    "duty",
    "fee",
    "additional_fee",
    "adjustment",
    "tip",
    "gift_card",
    "other",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _tenant_fk(
    columns: list[str], parent: str, name: str, *, cascade: bool = True
) -> ForeignKeyConstraint:
    """Composite (organization_id, parent_id) foreign key — the cross-tenant guard.

    ``cascade=False`` for optional references (e.g. an order line's variant): deleting the
    referenced row must never silently delete financial history.
    """
    return ForeignKeyConstraint(
        ["organization_id", *columns],
        [f"{parent}.organization_id", f"{parent}.id"],
        ondelete="CASCADE" if cascade else None,
        name=name,
    )


class Store(UUIDPrimaryKey, Timestamps, Base):
    """Commerce extension of a linked ``external_resources`` row of kind ``store``."""

    __tablename__ = "stores"
    __table_args__ = (
        _tenant_fk(["external_resource_id"], "external_resources", "fk_stores_external_resource"),
        UniqueConstraint("organization_id", "id", name="uq_stores_organization_id_id"),
        UniqueConstraint("external_resource_id", name="uq_stores_external_resource_id"),
        UniqueConstraint(
            "organization_id",
            "provider",
            "external_store_id",
            name="uq_stores_organization_id_provider_external_store_id",
        ),
        CheckConstraint(_in("status", STORE_STATUSES), name="status"),
        CheckConstraint("char_length(currency) = 3", name="currency"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_store_id: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="importing")
    # Earliest order date AdVegaX may hold (60 days, or 13 months with read_all_orders — Q9).
    history_from: Mapped[datetime | None] = mapped_column(TZ)
    first_import_completed_at: Mapped[datetime | None] = mapped_column(TZ)


class Product(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "products"
    __table_args__ = (
        _tenant_fk(["store_id"], "stores", "fk_products_store"),
        UniqueConstraint("organization_id", "id", name="uq_products_organization_id_id"),
        UniqueConstraint(
            "store_id", "external_product_id", name="uq_products_store_id_external_product_id"
        ),
        CheckConstraint(_in("status", PRODUCT_STATUSES), name="status"),
        Index("ix_products_organization_id_store_id", "organization_id", "store_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(255))
    product_type: Mapped[str | None] = mapped_column(String(255))
    vendor: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Platform's own last-modified time: an older update never overwrites a newer one.
    external_updated_at: Mapped[datetime | None] = mapped_column(TZ)


class ProductVariant(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        _tenant_fk(["product_id"], "products", "fk_product_variants_product"),
        _tenant_fk(["store_id"], "stores", "fk_product_variants_store"),
        UniqueConstraint("organization_id", "id", name="uq_product_variants_organization_id_id"),
        UniqueConstraint(
            "store_id",
            "external_variant_id",
            name="uq_product_variants_store_id_external_variant_id",
        ),
        Index("ix_product_variants_organization_id_product_id", "organization_id", "product_id"),
        Index("ix_product_variants_store_id_sku", "store_id", "sku"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_variant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_inventory_item_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(512))
    sku: Mapped[str | None] = mapped_column(String(255))
    price: Mapped[Decimal | None] = mapped_column(MONEY)
    # Inventory (summed across locations). NULL = not tracked / not synchronized — never 0.
    inventory_tracked: Mapped[bool | None] = mapped_column(Boolean)
    inventory_available: Mapped[int | None] = mapped_column(Integer)
    inventory_synced_at: Mapped[datetime | None] = mapped_column(TZ)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    external_updated_at: Mapped[datetime | None] = mapped_column(TZ)


class ProductCostHistory(UUIDPrimaryKey, Base):
    """Effective-dated unit cost per variant; order lines take the cost valid at order time."""

    __tablename__ = "product_cost_history"
    __table_args__ = (
        _tenant_fk(["variant_id"], "product_variants", "fk_product_cost_history_variant"),
        UniqueConstraint(
            "variant_id", "effective_from", name="uq_product_cost_history_variant_id_effective_from"
        ),
        CheckConstraint(_in("source", COST_SOURCES), name="source"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost"),
        Index("ix_product_cost_history_organization_id", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # NULL = the platform has no cost for the item from this moment (cost removed / never set).
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(TZ, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(TZ, nullable=False)


class Order(UUIDPrimaryKey, Timestamps, Base):
    """An order with summary amounts for display. Finance uses ``sales_entries``."""

    __tablename__ = "orders"
    __table_args__ = (
        _tenant_fk(["store_id"], "stores", "fk_orders_store"),
        UniqueConstraint("organization_id", "id", name="uq_orders_organization_id_id"),
        UniqueConstraint(
            "store_id", "external_order_id", name="uq_orders_store_id_external_order_id"
        ),
        CheckConstraint("char_length(currency) = 3", name="currency"),
        CheckConstraint(
            "country_code IS NULL OR char_length(country_code) = 2", name="country_code"
        ),
        Index(
            "ix_orders_organization_id_store_id_ordered_at",
            "organization_id",
            "store_id",
            "ordered_at",
        ),
        Index("ix_orders_store_id_customer_key", "store_id", "customer_key"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    ordered_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(TZ)
    financial_status: Mapped[str | None] = mapped_column(String(32))
    # Summary amounts in the store currency (display only).
    gross_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    discount_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    shipping_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    tax_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    refund_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    total_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    # Q8: one-way, organization-keyed customer key; never names, emails, phones or addresses.
    customer_key: Mapped[str | None] = mapped_column(String(64))
    country_code: Mapped[str | None] = mapped_column(String(2))
    external_updated_at: Mapped[datetime | None] = mapped_column(TZ)


class OrderItem(UUIDPrimaryKey, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        _tenant_fk(["order_id"], "orders", "fk_order_items_order"),
        _tenant_fk(["variant_id"], "product_variants", "fk_order_items_variant", cascade=False),
        UniqueConstraint("organization_id", "id", name="uq_order_items_organization_id_id"),
        UniqueConstraint(
            "order_id",
            "external_line_item_id",
            name="uq_order_items_order_id_external_line_item_id",
        ),
        CheckConstraint(
            "cost_source IS NULL OR " + _in("cost_source", LINE_COST_SOURCES), name="cost_source"
        ),
        CheckConstraint("(unit_cost IS NULL) = (cost_source IS NULL)", name="cost_complete"),
        Index("ix_order_items_organization_id_variant_id", "organization_id", "variant_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # NULL when the product was deleted on the platform or is a custom line.
    variant_id: Mapped[uuid.UUID | None] = mapped_column()
    external_line_item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    sku: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    # Cost per unit valid at order time ("order_time"), or the cost at first import for orders
    # older than the cost history ("import_time"). NULL = no cost known.
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    cost_source: Mapped[str | None] = mapped_column(String(16))


class SalesEntry(UUIDPrimaryKey, Base):
    """One sale or reversal with its own date — the source of store financial figures (§10)."""

    __tablename__ = "sales_entries"
    __table_args__ = (
        _tenant_fk(["order_id"], "orders", "fk_sales_entries_order"),
        _tenant_fk(["order_item_id"], "order_items", "fk_sales_entries_order_item", cascade=False),
        _tenant_fk(["store_id"], "stores", "fk_sales_entries_store"),
        UniqueConstraint(
            "store_id", "external_sale_id", name="uq_sales_entries_store_id_external_sale_id"
        ),
        CheckConstraint(_in("action", SALE_ACTIONS), name="action"),
        CheckConstraint(_in("line_type", SALE_LINE_TYPES), name="line_type"),
        CheckConstraint(_in("agreement_reason", AGREEMENT_REASONS), name="agreement_reason"),
        Index(
            "ix_sales_entries_organization_id_store_id_happened_at",
            "organization_id",
            "store_id",
            "happened_at",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    order_item_id: Mapped[uuid.UUID | None] = mapped_column()
    # Platform line id: resolves ``order_item_id`` after an import (child rows arrive unordered).
    external_line_item_id: Mapped[str | None] = mapped_column(String(255))
    external_agreement_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_sale_id: Mapped[str] = mapped_column(String(255), nullable=False)
    happened_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    agreement_reason: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="other"
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    line_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer)
    # Signed amounts in the store currency, as recorded by the platform (reversals negative).
    # ``amount`` is the sale total after taxes and discounts; ``discount_amount`` the discounts
    # allocated before taxes; ``tax_amount`` the sale's taxes (Shopify ``Sale`` fields).
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class Refund(UUIDPrimaryKey, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        _tenant_fk(["order_id"], "orders", "fk_refunds_order"),
        UniqueConstraint("organization_id", "id", name="uq_refunds_organization_id_id"),
        UniqueConstraint(
            "order_id", "external_refund_id", name="uq_refunds_order_id_external_refund_id"
        ),
        Index("ix_refunds_organization_id_processed_at", "organization_id", "processed_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_refund_id: Mapped[str] = mapped_column(String(255), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    total_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class RefundItem(UUIDPrimaryKey, Base):
    __tablename__ = "refund_items"
    __table_args__ = (
        _tenant_fk(["refund_id"], "refunds", "fk_refund_items_refund"),
        _tenant_fk(["order_item_id"], "order_items", "fk_refund_items_order_item", cascade=False),
        UniqueConstraint(
            "refund_id",
            "external_refund_line_id",
            name="uq_refund_items_refund_id_external_refund_line_id",
        ),
        CheckConstraint("quantity >= 0", name="quantity"),
        Index("ix_refund_items_organization_id_order_item_id", "organization_id", "order_item_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    refund_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    order_item_id: Mapped[uuid.UUID | None] = mapped_column()
    external_refund_line_id: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal: Mapped[Decimal | None] = mapped_column(MONEY)
    restocked: Mapped[bool | None] = mapped_column(Boolean)


class CommerceSyncState(Base):
    """Per-store synchronization cursors and progress (one row per store)."""

    __tablename__ = "commerce_sync_state"
    __table_args__ = (
        _tenant_fk(["store_id"], "stores", "fk_commerce_sync_state_store"),
        CheckConstraint(
            "import_progress IS NULL OR (import_progress BETWEEN 0 AND 100)",
            name="import_progress",
        ),
        CheckConstraint(
            "sync_mode IS NULL OR sync_mode IN ('initial', 'reconcile', 'deep')",
            name="sync_mode",
        ),
    )

    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    import_progress: Mapped[int | None] = mapped_column(Integer)
    bulk_operation_id: Mapped[str | None] = mapped_column(String(255))
    bulk_operation_kind: Mapped[str | None] = mapped_column(String(32))
    # The import step allowed to continue (a duplicated job message stops at this check).
    import_job_id: Mapped[uuid.UUID | None] = mapped_column()
    # What the running chain is (initial / reconcile / deep) and when it started (0009).
    sync_mode: Mapped[str | None] = mapped_column(String(16))
    sync_started_at: Mapped[datetime | None] = mapped_column(TZ)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(TZ)
    last_deep_reconciled_at: Mapped[datetime | None] = mapped_column(TZ)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_at: Mapped[datetime | None] = mapped_column(TZ)
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
