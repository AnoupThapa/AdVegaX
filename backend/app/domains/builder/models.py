"""The campaign builder's drafts (Phase 10B, task 10B-02, PHASE_10B_PLAN §5; A29).

A **campaign draft** is one platform's campaign, prepared from a ready strategy and one
approved creative: what will be created, exactly. It can be edited until it is launched
(every edit adds one to ``version``). Launching, going live and cleaning up are changes made
through the Action Engine (``actions.draft_id``), approved by a person.

Tenant-owned with forced row-level security; never deleted by the application.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey

TZ = DateTime(timezone=True)
DRAFT_STATUSES = ("draft", "launching", "created", "live", "failed", "archived")
DRAFT_PLATFORMS = ("google_ads", "meta_ads")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user() -> Any:
    return ForeignKey("users.id", ondelete="SET NULL")


class CampaignDraft(UUIDPrimaryKey, Base):
    __tablename__ = "campaign_drafts"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_campaign_drafts_organization_id_id"),
        UniqueConstraint("reference", name="uq_campaign_drafts_reference"),
        ForeignKeyConstraint(
            ["organization_id", "strategy_id"],
            ["campaign_strategies.organization_id", "campaign_strategies.id"],
            ondelete="CASCADE",
            name="fk_campaign_drafts_strategy",
        ),
        ForeignKeyConstraint(
            ["organization_id", "creative_id"],
            ["creatives.organization_id", "creatives.id"],
            name="fk_campaign_drafts_creative",
        ),
        ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            ondelete="CASCADE",
            name="fk_campaign_drafts_ad_account",
        ),
        CheckConstraint(_in("status", DRAFT_STATUSES), name="status"),
        CheckConstraint(_in("platform", DRAFT_PLATFORMS), name="platform"),
        CheckConstraint("daily_budget > 0", name="daily_budget"),
        CheckConstraint("char_length(currency) = 3", name="currency"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("age_min BETWEEN 18 AND 65 AND age_max BETWEEN age_min AND 65", name="age"),
        Index("ix_campaign_drafts_organization_id_strategy_id", "organization_id", "strategy_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creative_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    daily_budget: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Country codes (ISO 3166-1 alpha-2) from the supported list.
    locations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    age_min: Mapped[int] = mapped_column(Integer, nullable=False, server_default="18")
    age_max: Mapped[int] = mapped_column(Integer, nullable=False, server_default="65")
    # Google: [{"text": ..., "match": "phrase" | "exact" | "broad"}].
    keywords: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    landing_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    meta_page_id: Mapped[str | None] = mapped_column(String(32))
    meta_pixel_id: Mapped[str | None] = mapped_column(String(32))
    declaration_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    declaration_confirmed_at: Mapped[datetime | None] = mapped_column(TZ)
    # In the platform's campaign name, so a lost answer is looked up, never sent twice.
    reference: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    # The platform IDs created so far (campaign, budget, ad group / ad set, creative, ad, image).
    created_ids: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
