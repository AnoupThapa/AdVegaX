"""The creative engine's records (Phase 9, task 9-02, PHASE_09_PLAN §6; A27).

* ``creative_sets`` — one AI drafting of a ready strategy (its run is the trace).
* ``creatives`` — one **version** of one ad concept for one platform. Versions of a concept
  share ``concept_id``; an edit adds a version, never changes one. At most one approved
  version per concept (a partial unique index). Only approved versions are offered to the
  campaign builder (Phase 10B).
* ``creative_assets`` — images the organization uploaded, re-encoded, under random keys.
* ``creative_rules`` — the organization's own prohibited and allowed-capitalised words.

All tenant-owned with forced row-level security; nothing is deleted by the application.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

TZ = DateTime(timezone=True)
CREATIVE_STATUSES = ("draft", "approved", "rejected", "archived")
FORMATS = ("google_rsa", "meta_single")
ASSET_STATUSES = ("active", "archived")
ASSET_TYPES = ("image/jpeg", "image/png", "image/webp")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user(column: str = "users.id") -> Any:
    return ForeignKey(column, ondelete="SET NULL")


class CreativeSet(UUIDPrimaryKey, Base):
    __tablename__ = "creative_sets"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_creative_sets_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "strategy_id"],
            ["campaign_strategies.organization_id", "campaign_strategies.id"],
            ondelete="CASCADE",
            name="fk_creative_sets_strategy",
        ),
        ForeignKeyConstraint(
            ["organization_id", "ai_run_id"],
            ["ai_runs.organization_id", "ai_runs.id"],
            name="fk_creative_sets_ai_run",
        ),
        Index("ix_creative_sets_organization_id_strategy_id", "organization_id", "strategy_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ai_run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class CreativeAsset(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "creative_assets"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_creative_assets_organization_id_id"),
        UniqueConstraint("storage_key", name="uq_creative_assets_storage_key"),
        CheckConstraint(_in("status", ASSET_STATUSES), name="status"),
        CheckConstraint(_in("content_type", ASSET_TYPES), name="content_type"),
        CheckConstraint("width > 0 AND height > 0 AND bytes > 0", name="size"),
        CheckConstraint("char_length(sha256) = 64", name="sha256"),
        Index("ix_creative_assets_organization_id_status", "organization_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # As sent by the browser: shown only, never used as a path.
    original_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(_user())


class Creative(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "creatives"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_creatives_organization_id_id"),
        UniqueConstraint("concept_id", "version", name="uq_creatives_concept_id_version"),
        ForeignKeyConstraint(
            ["organization_id", "set_id"],
            ["creative_sets.organization_id", "creative_sets.id"],
            ondelete="CASCADE",
            name="fk_creatives_set",
        ),
        ForeignKeyConstraint(
            ["organization_id", "asset_id"],
            ["creative_assets.organization_id", "creative_assets.id"],
            name="fk_creatives_asset",
        ),
        ForeignKeyConstraint(
            ["organization_id", "replaces_id"],
            ["creatives.organization_id", "creatives.id"],
            name="fk_creatives_replaces",
        ),
        CheckConstraint(_in("status", CREATIVE_STATUSES), name="status"),
        CheckConstraint(_in("format", FORMATS), name="format"),
        CheckConstraint(_in("platform", ("google_ads", "meta_ads")), name="platform"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_creatives_organization_id_status", "organization_id", "status"),
        Index("ix_creatives_set_id", "set_id"),
        Index(
            "uq_creatives_one_approved_per_concept",
            "concept_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    set_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(nullable=False)  # the same for every version
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    replaces_id: Mapped[uuid.UUID | None] = mapped_column()
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    angle: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # the texts
    rationale: Mapped[str | None] = mapped_column(Text)
    compliance_notes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)  # advice only
    checks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)  # the fixed checks' results
    asset_id: Mapped[uuid.UUID | None] = mapped_column()
    decided_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    decided_at: Mapped[datetime | None] = mapped_column(TZ)
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user())


class CreativeRules(Base):
    __tablename__ = "creative_rules"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    prohibited_terms: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    allowed_caps: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
