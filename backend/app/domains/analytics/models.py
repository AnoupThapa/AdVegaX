"""Platform-neutral analytics model (Phase 5, PHASE_05_PLAN §8; decision Q11).

Analytics platforms (GA4 first) report **aggregates**, not events, so AdVegaX keeps daily
aggregates per property in three views: the property's total, by default channel group, and by
source / medium / campaign. Nothing here is specific to one platform (D4, D19).

Every table is tenant-owned with composite foreign keys ``(organization_id, parent_id)`` and
forced Row-Level Security (migration 0014). Money is exact ``Decimal`` in the **property's**
currency; days are in the property's time zone. A measure the platform did not provide is
``NULL``, never 0 (A10); a day that was never read has no row ("not synced yet").

**Users are distinct counts:** a row's users count each person once *for that day*. They are
never added across days or views (Q-5-5); only sessions, key events, purchases and revenue add up.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

MONEY = Numeric(20, 6)
TZ = DateTime(timezone=True)

# AdVegaX's own state of a linked property (like stores and ad accounts).
PROPERTY_STATUSES = ("importing", "active", "disconnected", "error")
# The platform's state of the property. Only ``active`` properties can be linked (Q-5-3).
PROPERTY_PLATFORM_STATUSES = ("active", "deleted")
# The three views kept per day (Q-5-4). ``total`` has ``dimension_key = 'total'``.
BREAKDOWNS = ("total", "channel", "source")
SOURCES = ("platform_reported",)
SYNC_MODES = ("initial", "quick", "nightly", "weekly")
TOTAL_KEY = "total"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _tenant_fk(columns: list[str], parent: str, name: str) -> ForeignKeyConstraint:
    """Composite (organization_id, parent_id) foreign key — the cross-tenant guard."""
    return ForeignKeyConstraint(
        ["organization_id", *columns],
        [f"{parent}.organization_id", f"{parent}.id"],
        ondelete="CASCADE",
        name=name,
    )


class AnalyticsProperty(UUIDPrimaryKey, Timestamps, Base):
    """Analytics extension of a linked ``external_resources`` row of kind
    ``analytics_property`` (a GA4 property)."""

    __tablename__ = "analytics_properties"
    __table_args__ = (
        _tenant_fk(
            ["external_resource_id"],
            "external_resources",
            "fk_analytics_properties_external_resource",
        ),
        UniqueConstraint(
            "organization_id", "id", name="uq_analytics_properties_organization_id_id"
        ),
        UniqueConstraint(
            "external_resource_id", name="uq_analytics_properties_external_resource_id"
        ),
        UniqueConstraint(
            "organization_id",
            "provider",
            "external_property_id",
            name="uq_analytics_properties_org_provider_external_id",
        ),
        CheckConstraint(_in("status", PROPERTY_STATUSES), name="status"),
        CheckConstraint(_in("platform_status", PROPERTY_PLATFORM_STATUSES), name="platform_status"),
        CheckConstraint("char_length(currency) = 3", name="currency"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_property_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    # The account (GA4: Analytics account) the property sits in, for display only.
    account_name: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="importing")
    platform_status: Mapped[str] = mapped_column(String(16), nullable=False)
    history_from: Mapped[date | None] = mapped_column(Date)
    first_import_completed_at: Mapped[datetime | None] = mapped_column(TZ)
    # Plain-language message key for the property page, never a raw platform error.
    health_code: Mapped[str | None] = mapped_column(String(64))
    health_checked_at: Mapped[datetime | None] = mapped_column(TZ)


class AnalyticsDaily(UUIDPrimaryKey, Base):
    """One row per property, day, view and value, as reported by the platform.

    ``dimension_key`` makes the row unique: ``'total'``, the channel group, or
    ``source|medium|campaign``. The flags record what the platform said about the report the
    row came from (Q-5-8): rare values grouped into "(other)", rows withheld for privacy
    (thresholding), sampling, truncation. They are shown, never hidden.
    """

    __tablename__ = "analytics_daily"
    __table_args__ = (
        _tenant_fk(["property_id"], "analytics_properties", "fk_analytics_daily_property"),
        UniqueConstraint(
            "property_id",
            "breakdown",
            "dimension_key",
            "day",
            name="uq_analytics_daily_property_id_breakdown_dimension_key_day",
        ),
        CheckConstraint(_in("breakdown", BREAKDOWNS), name="breakdown"),
        CheckConstraint(_in("source", SOURCES), name="source"),
        CheckConstraint(
            f"(breakdown = 'total') = (dimension_key = '{TOTAL_KEY}')", name="dimension_key"
        ),
        CheckConstraint("char_length(currency) = 3", name="currency"),
        *(
            CheckConstraint(f"{c} IS NULL OR {c} >= 0", name=c)
            for c in (
                "sessions",
                "engaged_sessions",
                "total_users",
                "new_users",
                "key_events",
                "purchases",
            )  # purchase revenue is net of refunds and can be negative (0015)
        ),
        Index(
            "ix_analytics_daily_organization_id_property_id_day",
            "organization_id",
            "property_id",
            "day",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)  # in the property's time zone
    breakdown: Mapped[str] = mapped_column(String(16), nullable=False)
    dimension_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    channel_group: Mapped[str | None] = mapped_column(String(255))
    traffic_source: Mapped[str | None] = mapped_column(String(255))
    traffic_medium: Mapped[str | None] = mapped_column(String(255))
    campaign: Mapped[str | None] = mapped_column(String(255))
    # NULL = not provided by the platform (never 0); a day with no activity has real zeros.
    sessions: Mapped[int | None] = mapped_column(BigInteger)
    engaged_sessions: Mapped[int | None] = mapped_column(BigInteger)
    total_users: Mapped[int | None] = mapped_column(BigInteger)  # this day only (Q-5-5)
    new_users: Mapped[int | None] = mapped_column(BigInteger)
    key_events: Mapped[Decimal | None] = mapped_column(MONEY)  # platforms report fractions
    purchases: Mapped[int | None] = mapped_column(BigInteger)
    purchase_revenue: Mapped[Decimal | None] = mapped_column(MONEY)  # minus refunds: may be < 0
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    other_row: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    thresholded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    sampled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="platform_reported"
    )
    fetched_at: Mapped[datetime] = mapped_column(TZ, nullable=False)


class AnalyticsSyncState(Base):
    """Per-property synchronization progress (one row per property)."""

    __tablename__ = "analytics_sync_state"
    __table_args__ = (
        _tenant_fk(["property_id"], "analytics_properties", "fk_analytics_sync_state_property"),
        CheckConstraint(
            "import_progress IS NULL OR (import_progress BETWEEN 0 AND 100)",
            name="import_progress",
        ),
        CheckConstraint("sync_mode IS NULL OR " + _in("sync_mode", SYNC_MODES), name="sync_mode"),
        CheckConstraint(
            "import_cursor IS NULL OR char_length(import_cursor) <= 2048", name="import_cursor"
        ),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    import_progress: Mapped[int | None] = mapped_column(Integer)
    sync_mode: Mapped[str | None] = mapped_column(String(16))
    sync_started_at: Mapped[datetime | None] = mapped_column(TZ)
    # The import step allowed to continue (a duplicated job message stops at this check).
    import_job_id: Mapped[uuid.UUID | None] = mapped_column()
    # Opaque position of the running chain (e.g. the next monthly slice of the first import).
    import_cursor: Mapped[str | None] = mapped_column(String(2048))
    last_quick_at: Mapped[datetime | None] = mapped_column(TZ)
    last_nightly_at: Mapped[datetime | None] = mapped_column(TZ)
    last_weekly_at: Mapped[datetime | None] = mapped_column(TZ)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_at: Mapped[datetime | None] = mapped_column(TZ)
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
