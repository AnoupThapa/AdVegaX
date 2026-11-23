"""The Action Engine API (Phase 10A, task 10A-05, PLAN §7; API_SPECIFICATION §19J)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ListEnvelope, ok, ok_list
from app.domains.actions.schemas import (
    ActionIn,
    ActionOut,
    ActionPreviewOut,
    ActionRejectIn,
    ActionSettingsIn,
    ActionSettingsOut,
    WriteAccessIn,
    WriteAccessOut,
)
from app.domains.actions.service import ActionService

router = APIRouter(tags=["actions"])
ORG = "/organizations/{organization_id}"
ONE = f"{ORG}/actions/{{action_id}}"
ACCESS = f"{ORG}/connections/{{connection_id}}/write-access"


def get_actions(rt: RuntimeDep) -> ActionService:
    return ActionService(rt)


ActionsDep = Annotated[ActionService, Depends(get_actions)]
StatusFilter = Literal[
    "open",
    "pending",
    "approved",
    "rejected",
    "cancelled",
    "queued",
    "submitting",
    "unknown",
    "succeeded",
    "failed",
    "stale",
]


@router.post(f"{ORG}/actions/validate", response_model=Envelope[ActionPreviewOut])
def validate_action(body: ActionIn, ctx: TenantDep, svc: ActionsDep) -> Envelope[ActionPreviewOut]:
    """Run every check and the platform's dry run on a change; nothing is kept or changed.
    Errors: ACTIONS_DISABLED, ACTION_NOT_ALLOWED."""
    return ok(svc.validate(ctx, body))


@router.post(
    f"{ORG}/actions", status_code=status.HTTP_201_CREATED, response_model=Envelope[ActionOut]
)
def request_action(body: ActionIn, ctx: TenantDep, svc: ActionsDep) -> Envelope[ActionOut]:
    """Request a change (owners, admins, managers). Kept as ``pending`` only when every check
    and the platform's dry run pass; nothing is sent until an owner or admin approves.
    Errors: ACTIONS_DISABLED, ACTION_INVALID, ACTION_DUPLICATE, ACTION_NOT_ALLOWED."""
    return ok(svc.request(ctx, body))


@router.get(f"{ORG}/actions", response_model=ListEnvelope[ActionOut])
def list_actions(
    ctx: TenantDep,
    svc: ActionsDep,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status_filter: Annotated[StatusFilter | None, Query(alias="status")] = None,
    campaign_id: uuid.UUID | None = None,
) -> ListEnvelope[ActionOut]:
    """Changes, newest first; ``status=open`` for those waiting or on their way."""
    items, total = svc.list_actions(
        ctx, page=page, page_size=page_size, status=status_filter, campaign_id=campaign_id
    )
    return ok_list(items, page=page, page_size=page_size, total=total)


@router.get(ONE, response_model=Envelope[ActionOut])
def get_action(action_id: uuid.UUID, ctx: TenantDep, svc: ActionsDep) -> Envelope[ActionOut]:
    """One change with its checks, what was sent, the platform's answer, the verification and
    every step (who, when, why)."""
    return ok(svc.get(ctx, action_id))


@router.post(f"{ONE}/approve", response_model=Envelope[ActionOut])
def approve_action(action_id: uuid.UUID, ctx: TenantDep, svc: ActionsDep) -> Envelope[ActionOut]:
    """Approve (owners, admins): the checks run again and the change is queued for sending.
    Errors: ACTIONS_DISABLED, ACTION_INVALID, ACTION_NOT_ALLOWED, ACTION_STALE,
    SECOND_PERSON_REQUIRED."""
    return ok(svc.approve(ctx, action_id))


@router.post(f"{ONE}/reject", response_model=Envelope[ActionOut])
def reject_action(
    action_id: uuid.UUID, body: ActionRejectIn, ctx: TenantDep, svc: ActionsDep
) -> Envelope[ActionOut]:
    """Reject with a reason (owners, admins)."""
    return ok(svc.reject(ctx, action_id, body.reason))


@router.post(f"{ONE}/cancel", response_model=Envelope[ActionOut])
def cancel_action(action_id: uuid.UUID, ctx: TenantDep, svc: ActionsDep) -> Envelope[ActionOut]:
    """Cancel before it is sent (the requester, or an owner or admin)."""
    return ok(svc.cancel(ctx, action_id))


@router.post(f"{ONE}/undo", status_code=status.HTTP_201_CREATED, response_model=Envelope[ActionOut])
def undo_action(action_id: uuid.UUID, ctx: TenantDep, svc: ActionsDep) -> Envelope[ActionOut]:
    """Request the opposite of a change that was made, approved like any other."""
    return ok(svc.undo(ctx, action_id))


@router.get(f"{ORG}/action-settings", response_model=Envelope[ActionSettingsOut])
def get_action_settings(ctx: TenantDep, svc: ActionsDep) -> Envelope[ActionSettingsOut]:
    """Pause all changes, the second-person rule, the maximum daily budget and the limits."""
    return ok(svc.get_settings(ctx))


@router.put(f"{ORG}/action-settings", response_model=Envelope[ActionSettingsOut])
def put_action_settings(
    body: ActionSettingsIn, ctx: TenantDep, svc: ActionsDep
) -> Envelope[ActionSettingsOut]:
    """Change the organization's settings (owners, admins)."""
    return ok(svc.put_settings(ctx, body))


@router.get(ACCESS, response_model=Envelope[WriteAccessOut])
def get_write_access(
    connection_id: uuid.UUID, ctx: TenantDep, svc: ActionsDep
) -> Envelope[WriteAccessOut]:
    """Whether AdVegaX may change ad accounts through this connection."""
    return ok(svc.get_write_access(ctx, connection_id))


@router.put(ACCESS, response_model=Envelope[WriteAccessOut])
def put_write_access(
    connection_id: uuid.UUID, body: WriteAccessIn, ctx: TenantDep, svc: ActionsDep
) -> Envelope[WriteAccessOut]:
    """ "Allow changes" through this connection, or take it back (owners, admins).
    Errors: ACTION_NOT_ALLOWED (the platform permission is missing: sign in again)."""
    return ok(svc.put_write_access(ctx, connection_id, body))
