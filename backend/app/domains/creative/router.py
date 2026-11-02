"""The creative engine API (Phase 9, task 9-05, PLAN §7; API_SPECIFICATION §19I)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.core.errors import AssetInvalid
from app.domains.creative.schemas import (
    ApproveIn,
    AssetOut,
    CreativeOut,
    CreativeRulesIn,
    CreativeRulesOut,
    CreativeSetCreateIn,
    CreativeSetOut,
    CreativeSetSummaryOut,
    CreativeUpdateIn,
    RejectIn,
)
from app.domains.creative.service import CreativeService

router = APIRouter(tags=["creatives"])
ORG = "/organizations/{organization_id}"
ONE = f"{ORG}/creatives/{{creative_id}}"
ASSET = f"{ORG}/creative-assets/{{asset_id}}"


def get_creatives(rt: RuntimeDep) -> CreativeService:
    return CreativeService(rt)


CreativesDep = Annotated[CreativeService, Depends(get_creatives)]


@router.post(
    f"{ORG}/ai/creative-sets",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[CreativeSetOut],
)
def generate_creative_set(
    body: CreativeSetCreateIn, ctx: TenantDep, svc: CreativesDep
) -> Envelope[CreativeSetOut]:
    """Draft the ad copy for every platform of a strategy marked ready (one AI run). Every
    concept is kept as a draft with its check results; nothing is sent to Google or Meta.
    Errors: STRATEGY_NOT_READY, AI_LIMIT_REACHED, AI_UNAVAILABLE, AI_ANSWER_REJECTED."""
    return ok(svc.generate(ctx, body.strategy_id))


@router.get(f"{ORG}/creative-sets", response_model=Envelope[list[CreativeSetSummaryOut]])
def list_creative_sets(
    ctx: TenantDep, svc: CreativesDep, strategy_id: uuid.UUID | None = None
) -> Envelope[list[CreativeSetSummaryOut]]:
    return ok(svc.list_sets(ctx, strategy_id))


@router.get(f"{ORG}/creative-sets/{{set_id}}", response_model=Envelope[CreativeSetOut])
def get_creative_set(
    set_id: uuid.UUID, ctx: TenantDep, svc: CreativesDep
) -> Envelope[CreativeSetOut]:
    """The newest version of each concept, with its checks and versions."""
    return ok(svc.get_set(ctx, set_id))


@router.get(f"{ORG}/creatives", response_model=Envelope[list[CreativeOut]])
def list_creatives(
    ctx: TenantDep,
    svc: CreativesDep,
    status_filter: Annotated[
        Literal["draft", "approved", "rejected", "archived"] | None, Query(alias="status")
    ] = None,
    platform: Literal["google_ads", "meta_ads"] | None = None,
    strategy_id: uuid.UUID | None = None,
) -> Envelope[list[CreativeOut]]:
    """With ``status=approved``: the creatives the campaign builder may use."""
    return ok(
        svc.list_creatives(ctx, status=status_filter, platform=platform, strategy_id=strategy_id)
    )


@router.get(ONE, response_model=Envelope[CreativeOut])
def get_creative(
    creative_id: uuid.UUID, ctx: TenantDep, svc: CreativesDep
) -> Envelope[CreativeOut]:
    return ok(svc.get(ctx, creative_id))


@router.patch(ONE, response_model=Envelope[CreativeOut])
def update_creative(
    creative_id: uuid.UUID, body: CreativeUpdateIn, ctx: TenantDep, svc: CreativesDep
) -> Envelope[CreativeOut]:
    """An edit makes a new draft version; the version edited is kept unchanged."""
    return ok(svc.update(ctx, creative_id, body))


@router.post(f"{ONE}/approve", response_model=Envelope[CreativeOut])
def approve_creative(
    creative_id: uuid.UUID, body: ApproveIn, ctx: TenantDep, svc: CreativesDep
) -> Envelope[CreativeOut]:
    """Owners, admins, managers. Checks run again; CREATIVE_CHECKS_FAILED lists what failed."""
    return ok(svc.approve(ctx, creative_id, confirm=body.confirm_flags))


@router.post(f"{ONE}/reject", response_model=Envelope[CreativeOut])
def reject_creative(
    creative_id: uuid.UUID, body: RejectIn, ctx: TenantDep, svc: CreativesDep
) -> Envelope[CreativeOut]:
    return ok(svc.reject(ctx, creative_id, body.reason))


@router.post(f"{ONE}/archive", response_model=Envelope[CreativeOut])
def archive_creative(
    creative_id: uuid.UUID, ctx: TenantDep, svc: CreativesDep
) -> Envelope[CreativeOut]:
    return ok(svc.archive(ctx, creative_id))


@router.post(
    f"{ORG}/creative-assets",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[AssetOut],
)
def upload_creative_asset(
    ctx: TenantDep, svc: CreativesDep, rt: RuntimeDep, file: Annotated[UploadFile, File()]
) -> Envelope[AssetOut]:
    """An image (JPEG, PNG or WebP). Checked by decoding and re-saved without hidden data."""
    data = file.file.read(rt.settings.ASSET_MAX_BYTES + 1)
    if len(data) > rt.settings.ASSET_MAX_BYTES:
        raise AssetInvalid(details=[{"reason": "too_large"}])
    return ok(svc.upload(ctx, file.filename, data))


@router.get(f"{ORG}/creative-assets", response_model=Envelope[list[AssetOut]])
def list_creative_assets(
    ctx: TenantDep, svc: CreativesDep, archived: bool = False
) -> Envelope[list[AssetOut]]:
    return ok(svc.list_assets(ctx, archived=archived))


@router.get(
    f"{ASSET}/content",
    response_class=Response,
    responses={200: {"content": {"image/*": {}}, "description": "The image"}},
)
def creative_asset_content(asset_id: uuid.UUID, ctx: TenantDep, svc: CreativesDep) -> Response:
    """The image itself, for members of the organization only (never a public link)."""
    data, kind = svc.content(ctx, asset_id)
    return Response(
        content=data,
        media_type=kind,
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "private, max-age=300",
            "Cross-Origin-Resource-Policy": "same-site",
        },
    )


@router.post(f"{ASSET}/archive", response_model=Envelope[AssetOut])
def archive_creative_asset(
    asset_id: uuid.UUID, ctx: TenantDep, svc: CreativesDep
) -> Envelope[AssetOut]:
    return ok(svc.archive_asset(ctx, asset_id))


@router.get(f"{ORG}/creative-rules", response_model=Envelope[CreativeRulesOut])
def get_creative_rules(ctx: TenantDep, svc: CreativesDep) -> Envelope[CreativeRulesOut]:
    return ok(svc.get_rules(ctx))


@router.put(f"{ORG}/creative-rules", response_model=Envelope[CreativeRulesOut])
def put_creative_rules(
    body: CreativeRulesIn, ctx: TenantDep, svc: CreativesDep
) -> Envelope[CreativeRulesOut]:
    """Owners and admins: the organization's own prohibited and allowed-capitalised words."""
    return ok(svc.put_rules(ctx, body))
