"""Creative engine API shapes (Phase 9, task 9-05; API_SPECIFICATION §19I)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CreativeStatus = Literal["draft", "approved", "rejected", "archived"]


class CreativeSetCreateIn(BaseModel):
    strategy_id: uuid.UUID


class CheckOut(BaseModel):
    """One fixed check's result: ``block`` must be fixed; ``flag`` must be confirmed."""

    code: str
    field: str
    detail: str | None
    severity: Literal["block", "flag"]


class VersionRefOut(BaseModel):
    id: uuid.UUID
    version: int
    status: CreativeStatus
    created_at: datetime


class AssetRefOut(BaseModel):
    id: uuid.UUID
    content_type: str
    width: int
    height: int


class CreativeOut(BaseModel):
    id: uuid.UUID
    set_id: uuid.UUID
    strategy_id: uuid.UUID
    product_id: uuid.UUID
    product_title: str | None
    concept_id: uuid.UUID
    version: int
    latest: bool  # the newest version of its concept
    platform: Literal["google_ads", "meta_ads"]
    format: Literal["google_rsa", "meta_single"]
    angle: str
    status: CreativeStatus
    content: dict[str, Any]
    rationale: str | None
    compliance_notes: list[str]
    checks: list[CheckOut]
    approvable: bool  # no blocking check
    asset: AssetRefOut | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    versions: list[VersionRefOut]


class CreativeSetOut(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    product_id: uuid.UUID
    product_title: str | None
    created_at: datetime
    ai_run_id: uuid.UUID
    creatives: list[CreativeOut]  # the latest version of each concept


class CreativeSetSummaryOut(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    product_title: str | None
    created_at: datetime
    concepts: int
    approved: int


class CreativeUpdateIn(BaseModel):
    """An edit: the whole content as edited and/or the image (Meta). Creates a new version."""

    content: dict[str, Any] | None = None
    asset_id: uuid.UUID | None = None
    remove_asset: bool = False


class ApproveIn(BaseModel):
    confirm_flags: bool = False  # "I have checked the flagged wording"


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AssetOut(BaseModel):
    id: uuid.UUID
    content_type: str
    width: int
    height: int
    bytes: int
    sha256: str
    original_name: str | None
    status: Literal["active", "archived"]
    uploaded_by: uuid.UUID | None
    created_at: datetime


class CreativeRulesIn(BaseModel):
    prohibited_terms: list[str] = Field(max_length=200)
    allowed_caps: list[str] = Field(max_length=100)


class CreativeRulesOut(BaseModel):
    prohibited_terms: list[str]
    allowed_caps: list[str]
    base_prohibited_terms: list[str]  # AdVegaX's own list, always applied
    updated_at: datetime | None
