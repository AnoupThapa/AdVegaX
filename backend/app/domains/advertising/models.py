"""Platform-neutral advertising model (Phase 3, PHASE_03_PLAN §8).

Ad accounts, campaigns, budgets, ad groups, ads and daily performance, designed against both
Google Ads and Meta (Phase 4): Google "ad group" and Meta "ad set" are both ``ad_groups``. Nothing
here is specific to one platform; providers map into these tables (D4, D19). Platform-only
details go in ``provider_extensions`` (display only — the core never computes on it).

Every table is tenant-owned with composite foreign keys ``(organization_id, parent_id)`` and
forced Row-Level Security (migration 0012). Money is exact ``Decimal`` in the **ad account's**
currency; days are in the ad account's time zone. A measure the platform did not provide is
``NULL``, never 0 (A10); a day that was never read has no row ("not synced yet").
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

MONEY = Numeric(20, 6)
TZ = DateTime(timezone=True)

# AdVegaX's own state of a linked ad account (like stores).
AD_ACCOUNT_STATUSES = ("importing", "active", "disconnected", "error")
# The platform's state of the account. Only ``active`` accounts can be linked (Q-3-3).
AD_ACCOUNT_PLATFORM_STATUSES = ("active", "not_enabled", "cancelled", "suspended", "closed")
# Campaigns, ad groups and ads (Google: ENABLED/PAUSED/REMOVED; Meta adds ARCHIVED).
ENTITY_STATUSES = ("active", "paused", "archived", "removed")
BUDGET_LEVELS = ("campaign", "ad_group")
BUDGET_PERIODS = ("daily", "lifetime")
PERFORMANCE_LEVELS = ("account", "campaign", "ad_group", "ad")
# Where a figure comes from. Phase 3 holds only what the platform reports (Q-3-7); AdVegaX's
# own attribution arrives in Phase 6 and is never mixed into these rows.
PERFORMANCE_SOURCES = ("platform_reported",)
SYNC_MODES = ("initial", "quick", "nightly", "weekly")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _tenant_fk(
    columns: list[str], parent: str, name: str, *, cascade: bool = True
) -> ForeignKeyConstraint:
    """Composite (organization_id, parent_id) foreign key — the cross-tenant guard.

    ``cascade=False`` for optional references (e.g. a campaign's budget): removing the
    referenced row must never silently delete history.
    """
    return ForeignKeyConstraint(
        ["organization_id", *columns],
        [f"{parent}.organization_id", f"{parent}.id"],
        ondelete="CASCADE" if cascade else None,
        name=name,
    )


class AdAccount(UUIDPrimaryKey, Timestamps, Base):
    """Advertising extension of a linked ``external_resources`` row of kind ``ad_account``."""

    __tablename__ = "ad_accounts"
    __table_args__ = (
        _tenant_fk(
            ["external_resource_id"], "external_resources", "fk_ad_accounts_external_resource"
        ),
        UniqueConstraint("organization_id", "id", name="uq_ad_accounts_organization_id_id"),
        UniqueConstraint("external_resource_id", name="uq_ad_accounts_external_resource_id"),
        UniqueConstraint(
            "organization_id",
            "provider",
            "external_account_id",
            name="uq_ad_accounts_organization_id_provider_external_account_id",
        ),
        CheckConstraint(_in("status", AD_ACCOUNT_STATUSES), name="status"),
        CheckConstraint(
            _in("platform_status", AD_ACCOUNT_PLATFORM_STATUSES), name="platform_status"
        ),
        CheckConstraint("char_length(currency) = 3", name="currency"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="importing")
    platform_status: Mapped[str] = mapped_column(String(16), nullable=False)
    history_from: Mapped[date | None] = mapped_column(Date)
    first_import_completed_at: Mapped[datetime | None] = mapped_column(TZ)
    # Plain-language message key for the account page (e.g. ``account_cancelled``), never a
    # raw platform error.
    health_code: Mapped[str | None] = mapped_column(String(64))
    health_checked_at: Mapped[datetime | None] = mapped_column(TZ)


class AdBudget(UUIDPrimaryKey, Timestamps, Base):
    """A budget: shared between campaigns (Google) or owned by one campaign or ad set."""

    __tablename__ = "ad_budgets"
    __table_args__ = (
        _tenant_fk(["ad_account_id"], "ad_accounts", "fk_ad_budgets_ad_account"),
        UniqueConstraint("organization_id", "id", name="uq_ad_budgets_organization_id_id"),
        UniqueConstraint(
            "ad_account_id",
            "external_budget_id",
            name="uq_ad_budgets_ad_account_id_external_budget_id",
        ),
        CheckConstraint(_in("level", BUDGET_LEVELS), name="level"),
        CheckConstraint(_in("period", BUDGET_PERIODS), name="period"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount"),
        CheckConstraint("char_length(currency) = 3", name="currency"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_budget_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(512))
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    # NULL when the platform gives no amount (e.g. a budget set elsewhere) — never 0.
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class AdCampaign(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "ad_campaigns"
    __table_args__ = (
        _tenant_fk(["ad_account_id"], "ad_accounts", "fk_ad_campaigns_ad_account"),
        _tenant_fk(["budget_id"], "ad_budgets", "fk_ad_campaigns_budget", cascade=False),
        UniqueConstraint("organization_id", "id", name="uq_ad_campaigns_organization_id_id"),
        UniqueConstraint(
            "ad_account_id",
            "external_campaign_id",
            name="uq_ad_campaigns_ad_account_id_external_campaign_id",
        ),
        CheckConstraint(_in("status", ENTITY_STATUSES), name="status"),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="dates"
        ),
        Index("ix_ad_campaigns_organization_id_ad_account_id", "organization_id", "ad_account_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_campaign_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # The platform's own type (Google channel type such as ``PERFORMANCE_MAX``, Meta
    # objective such as ``OUTCOME_SALES``); shown, never computed on.
    platform_type: Mapped[str | None] = mapped_column(String(64))
    bidding_strategy_type: Mapped[str | None] = mapped_column(String(64))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    budget_id: Mapped[uuid.UUID | None] = mapped_column()
    provider_extensions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AdGroup(UUIDPrimaryKey, Timestamps, Base):
    """Google ad group / Meta ad set."""

    __tablename__ = "ad_groups"
    __table_args__ = (
        _tenant_fk(["campaign_id"], "ad_campaigns", "fk_ad_groups_campaign"),
        _tenant_fk(["budget_id"], "ad_budgets", "fk_ad_groups_budget", cascade=False),
        UniqueConstraint("organization_id", "id", name="uq_ad_groups_organization_id_id"),
        UniqueConstraint(
            "campaign_id",
            "external_ad_group_id",
            name="uq_ad_groups_campaign_id_external_ad_group_id",
        ),
        CheckConstraint(_in("status", ENTITY_STATUSES), name="status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    campaign_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_ad_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_type: Mapped[str | None] = mapped_column(String(64))
    # Meta ad sets can carry their own budget; Google ad groups never do.
    budget_id: Mapped[uuid.UUID | None] = mapped_column()
    provider_extensions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Ad(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "ads"
    __table_args__ = (
        _tenant_fk(["ad_group_id"], "ad_groups", "fk_ads_ad_group"),
        UniqueConstraint("organization_id", "id", name="uq_ads_organization_id_id"),
        UniqueConstraint("ad_group_id", "external_ad_id", name="uq_ads_ad_group_id_external_ad_id"),
        CheckConstraint(_in("status", ENTITY_STATUSES), name="status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ad_group_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_ad_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Many Google ads have no name of their own.
    name: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_type: Mapped[str | None] = mapped_column(String(64))
    provider_extensions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AdPerformanceDaily(UUIDPrimaryKey, Base):
    """One row per ad account, level, entity and day, as reported by the platform.

    Levels are stored as reported and never added into each other: some campaign types (e.g.
    Performance Max) have no ad groups, so account totals come from ``level = 'account'``.
    ``entity_key`` is the platform id of the campaign, ad group or ad (``'account'`` for the
    account level) and makes the row unique even before the entity's structure is known.
    """

    __tablename__ = "ad_performance_daily"
    __table_args__ = (
        _tenant_fk(["ad_account_id"], "ad_accounts", "fk_ad_performance_daily_ad_account"),
        _tenant_fk(
            ["campaign_id"], "ad_campaigns", "fk_ad_performance_daily_campaign", cascade=False
        ),
        _tenant_fk(["ad_group_id"], "ad_groups", "fk_ad_performance_daily_ad_group", cascade=False),
        _tenant_fk(["ad_id"], "ads", "fk_ad_performance_daily_ad", cascade=False),
        UniqueConstraint(
            "ad_account_id",
            "level",
            "entity_key",
            "day",
            name="uq_ad_performance_daily_ad_account_id_level_entity_key_day",
        ),
        CheckConstraint(_in("level", PERFORMANCE_LEVELS), name="level"),
        CheckConstraint(_in("source", PERFORMANCE_SOURCES), name="source"),
        CheckConstraint("(level = 'account') = (entity_key = 'account')", name="entity_key"),
        CheckConstraint("impressions IS NULL OR impressions >= 0", name="impressions"),
        CheckConstraint("clicks IS NULL OR clicks >= 0", name="clicks"),
        CheckConstraint("char_length(currency) = 3", name="currency"),
        Index(
            "ix_ad_performance_daily_organization_id_ad_account_id_day",
            "organization_id",
            "ad_account_id",
            "day",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # Resolved links to the structure (NULL until the entity is known, or at higher levels).
    campaign_id: Mapped[uuid.UUID | None] = mapped_column()
    ad_group_id: Mapped[uuid.UUID | None] = mapped_column()
    ad_id: Mapped[uuid.UUID | None] = mapped_column()
    day: Mapped[date] = mapped_column(Date, nullable=False)  # in the ad account's time zone
    # NULL = not provided by the platform (never 0); a day with no activity has real zeros.
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int | None] = mapped_column(BigInteger)
    cost: Mapped[Decimal | None] = mapped_column(MONEY)
    conversions: Mapped[Decimal | None] = mapped_column(MONEY)  # platforms report fractions
    conversion_value: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="platform_reported"
    )
    fetched_at: Mapped[datetime] = mapped_column(TZ, nullable=False)


class AdSyncState(Base):
    """Per-ad-account synchronization progress (one row per account)."""

    __tablename__ = "ad_sync_state"
    __table_args__ = (
        _tenant_fk(["ad_account_id"], "ad_accounts", "fk_ad_sync_state_ad_account"),
        CheckConstraint(
            "import_progress IS NULL OR (import_progress BETWEEN 0 AND 100)",
            name="import_progress",
        ),
        CheckConstraint("sync_mode IS NULL OR " + _in("sync_mode", SYNC_MODES), name="sync_mode"),
        CheckConstraint(
            "import_cursor IS NULL OR char_length(import_cursor) <= 2048", name="import_cursor"
        ),
    )

    ad_account_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
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
