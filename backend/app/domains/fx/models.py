"""Exchange rates (Phase 6, PHASE_06_PLAN §7, Q-6-3).

One published rate per source, currency pair and day, **exactly as published** (an exact decimal
and the source's own unit, e.g. Nepal Rastra Bank quotes JPY per 10 and INR per 100). Shared
reference data, not tenant data: the application can read it, only the system role writes it
(migration 0016). Conversions are computed in one place (``app/domains/fx/convert.py``, 6-03).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey

FX_SOURCES = ("ecb", "nrb")


class FxRate(UUIDPrimaryKey, Base):
    """``unit`` units of ``base`` are worth ``rate`` units of ``quote``, as the source quotes it.

    ECB: base EUR, e.g. quote AUD, unit 1 (1 EUR = rate AUD). NRB: e.g. base JPY, quote NPR,
    unit 10 (10 JPY = rate NPR); NRB's middle rate (buy + sell) / 2 is stored."""

    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint(
            "source", "base", "quote", "rate_date", name="uq_fx_rates_source_base_quote_rate_date"
        ),
        CheckConstraint("source IN ('ecb', 'nrb')", name="source"),
        CheckConstraint("base ~ '^[A-Z]{3}$' AND quote ~ '^[A-Z]{3}$'", name="currencies"),
        CheckConstraint("base <> quote", name="different_currencies"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("unit > 0", name="unit_positive"),
    )

    source: Mapped[str] = mapped_column(String(8), nullable=False)
    base: Mapped[str] = mapped_column(String(3), nullable=False)
    quote: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    unit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
