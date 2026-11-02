"""The campaign builder API (Phase 10B, task 10B-05, PLAN §6; API_SPECIFICATION §19K)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.actions.schemas import ActionOut
from app.domains.builder.schemas import (
    DraftCreateIn,
    DraftOut,
    DraftPreviewOut,
    DraftUpdateIn,
    MetaAssetOut,
)
from app.domains.builder.service import BuilderService

router = APIRouter(tags=["campaign builder"])
ORG = "/organizations/{organization_id}"
ONE = f"{ORG}/campaign-drafts/{{draft_id}}"


def get_builder(rt: RuntimeDep) -> BuilderService:
    return BuilderService(rt)


BuilderDep = Annotated[BuilderService, Depends(get_builder)]


@router.post(
    f"{ORG}/campaign-drafts", status_code=status.HTTP_201_CREATED, response_model=Envelope[DraftOut]
)
def create_campaign_draft(
    body: DraftCreateIn, ctx: TenantDep, svc: BuilderDep
) -> Envelope[DraftOut]:
    """Prepare one platform's campaign from a ready strategy and an approved creative.
    Errors: DRAFT_INVALID, CREATIVE_NOT_APPROVED."""
    return ok(svc.create(ctx, body))


@router.get(f"{ORG}/campaign-drafts", response_model=Envelope[list[DraftOut]])
def list_campaign_drafts(
    ctx: TenantDep, svc: BuilderDep, strategy_id: uuid.UUID | None = None
) -> Envelope[list[DraftOut]]:
    """Drafts, newest first (archived ones left out)."""
    return ok(svc.list_drafts(ctx, strategy_id))


@router.get(ONE, response_model=Envelope[DraftOut])
def get_campaign_draft(draft_id: uuid.UUID, ctx: TenantDep, svc: BuilderDep) -> Envelope[DraftOut]:
    return ok(svc.get(ctx, draft_id))


@router.patch(ONE, response_model=Envelope[DraftOut])
def update_campaign_draft(
    draft_id: uuid.UUID, body: DraftUpdateIn, ctx: TenantDep, svc: BuilderDep
) -> Envelope[DraftOut]:
    """Edit until launched; every change asks for the declarations again.
    Errors: DRAFT_NOT_EDITABLE, CREATIVE_NOT_APPROVED."""
    return ok(svc.update(ctx, draft_id, body))


@router.post(f"{ONE}/archive", response_model=Envelope[DraftOut])
def archive_campaign_draft(
    draft_id: uuid.UUID, ctx: TenantDep, svc: BuilderDep
) -> Envelope[DraftOut]:
    return ok(svc.archive(ctx, draft_id))


@router.post(f"{ONE}/validate", response_model=Envelope[DraftPreviewOut])
def validate_campaign_draft(
    draft_id: uuid.UUID, ctx: TenantDep, svc: BuilderDep
) -> Envelope[DraftPreviewOut]:
    """Every check and the platform's test; nothing is created."""
    return ok(svc.validate(ctx, draft_id))


@router.post(
    f"{ONE}/launch", status_code=status.HTTP_201_CREATED, response_model=Envelope[ActionOut]
)
def launch_campaign_draft(
    draft_id: uuid.UUID, ctx: TenantDep, svc: BuilderDep
) -> Envelope[ActionOut]:
    """Request creating the campaign — everything paused — approved by an owner or admin.
    Errors: DRAFT_INVALID, ACTION_DUPLICATE, ACTION_NOT_ALLOWED, ACTIONS_DISABLED."""
    return ok(svc.launch(ctx, draft_id))


@router.post(
    f"{ONE}/go-live", status_code=status.HTTP_201_CREATED, response_model=Envelope[ActionOut]
)
def go_live_campaign_draft(
    draft_id: uuid.UUID, ctx: TenantDep, svc: BuilderDep
) -> Envelope[ActionOut]:
    """Request switching the created campaign on — approved by an owner or admin."""
    return ok(svc.go_live(ctx, draft_id))


@router.post(
    f"{ONE}/clean-up", status_code=status.HTTP_201_CREATED, response_model=Envelope[ActionOut]
)
def clean_up_campaign_draft(
    draft_id: uuid.UUID, ctx: TenantDep, svc: BuilderDep
) -> Envelope[ActionOut]:
    """Request removing what a failed launch created (it is paused)."""
    return ok(svc.clean_up(ctx, draft_id))


@router.get(
    f"{ORG}/ad-accounts/{{ad_account_id}}/meta-pages", response_model=Envelope[list[MetaAssetOut]]
)
def list_meta_pages(
    ad_account_id: uuid.UUID, ctx: TenantDep, svc: BuilderDep
) -> Envelope[list[MetaAssetOut]]:
    """The Facebook Pages the connection's person can advertise as."""
    return ok(svc.meta_pages(ctx, ad_account_id))


@router.get(
    f"{ORG}/ad-accounts/{{ad_account_id}}/meta-pixels", response_model=Envelope[list[MetaAssetOut]]
)
def list_meta_pixels(
    ad_account_id: uuid.UUID, ctx: TenantDep, svc: BuilderDep
) -> Envelope[list[MetaAssetOut]]:
    """The ad account's pixels (datasets)."""
    return ok(svc.meta_pixels(ctx, ad_account_id))
