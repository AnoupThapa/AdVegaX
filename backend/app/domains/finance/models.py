"""Daily financial components per store (Phase 2A, PHASE_02A_PLAN §10; DATABASE_SCHEMA §13).

Only **additive** components are stored; ratios such as margin are calculated on read (A5).
Every row records the definition version that produced it (``finance-v1``) so figures stay
reproducible when definitions change. Cost of goods is NULL — not 0 — when any sold line in the
day has no known cost; ``costed_net_sales`` and ``uncosted_lines`` let the UI show coverage.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey

MONEY = Numeric(20, 6)


class FinancialDaily(UUIDPrimaryKey, Base):
    __tablename__ = "financial_daily"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "store_id"],
            ["stores.organization_id", "stores.id"],
            ondelete="CASCADE",
            name="fk_financial_daily_store",
        ),
        UniqueConstraint(
            "store_id",
            "day",
            "definition_version",
            name="uq_financial_daily_store_id_day_definition_version",
        ),
        CheckConstraint("orders_count >= 0", name="orders_count"),
        CheckConstraint("uncosted_lines >= 0", name="uncosted_lines"),
        CheckConstraint("(cogs IS NULL) = (uncosted_lines > 0)", name="cogs_availability"),
        Index(
            "ix_financial_daily_organization_id_store_id_day", "organization_id", "store_id", "day"
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)  # in the store's time zone
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(32), nullable=False)
    gross_sales: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    discounts: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    sales_reversals: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net_sales: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    shipping: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    taxes: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    duties: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fees: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_sales: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    orders_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL when any product line of the day lacks a cost (A10) — see ``uncosted_lines``.
    cogs: Mapped[Decimal | None] = mapped_column(MONEY)
    costed_net_sales: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    uncosted_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
