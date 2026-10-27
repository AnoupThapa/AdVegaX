"""What the checks need to know about a campaign and its organization (Phase 10A, 10A-02).

Read from AdVegaX's own records under the organization's context; the platform's view of
the campaign (``CampaignSnapshot``) is read separately, through the provider.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ActionsDisabled, NotFound
from app.domains.actions.catalogue import ActionSpec
from app.domains.actions.models import Action, ActionSettings
from app.domains.actions.validation import Limits
from app.domains.advertising.models import AdAccount, AdCampaign
from app.domains.fx.service import FxTable
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.strategy import budget as budgets
from app.providers.base.changes import CampaignWriter, ChangeKind, campaign_writer
from app.providers.base.registry import UnknownProvider
from app.providers.base.types import AdAccountRef
from app.runtime import Runtime

# Changes that reached (or may have reached) the platform count towards the limits.
SENT = ("submitting", "unknown", "succeeded")


@dataclass
class Target:
    campaign: AdCampaign
    account: AdAccount
    resource: ExternalResource
    connection: ExternalConnection
    linked: bool

    @property
    def ref(self) -> AdAccountRef:
        return AdAccountRef(self.account.external_account_id, self.resource.access_hint)


def load_target(session: Session, org_id: uuid.UUID, campaign_id: uuid.UUID) -> Target:
    row = session.execute(
        select(AdCampaign, AdAccount, ExternalResource, ExternalConnection)
        .join(
            AdAccount,
            (AdAccount.id == AdCampaign.ad_account_id)
            & (AdAccount.organization_id == AdCampaign.organization_id),
        )
        .join(ExternalResource, ExternalResource.id == AdAccount.external_resource_id)
        .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
        .where(AdCampaign.organization_id == org_id, AdCampaign.id == campaign_id)
    ).one_or_none()
    if row is None:
        raise NotFound()
    campaign, account, resource, connection = row
    linked = (
        session.execute(
            select(OrganizationResourceLink.id).where(
                OrganizationResourceLink.external_resource_id == resource.id,
                OrganizationResourceLink.status == "active",
            )
        ).first()
        is not None
    )
    return Target(campaign, account, resource, connection, linked)


def writer_for(rt: Runtime, provider_code: str) -> CampaignWriter | None:
    try:
        return campaign_writer(rt.providers.get(provider_code))
    except UnknownProvider:
        return None


def resource_reason(target: Target, writer: CampaignWriter | None) -> str | None:
    """Why this campaign cannot be changed through AdVegaX at all (None: it can)."""
    if writer is None:
        return "platform_cannot_change"
    if not target.linked:
        return "account_not_linked"
    if target.connection.status != "active":
        return "connection_inactive"
    if target.account.status != "active" or target.account.platform_status != "active":
        return "account_not_active"
    if target.campaign.status == "removed":
        return "campaign_not_changeable"
    return None


def write_access_problem(
    connection: ExternalConnection, writer: CampaignWriter | None
) -> str | None:
    """Why changes are not allowed through this connection (None: they are)."""
    if writer is None:
        return "platform_cannot_change"
    missing = set(writer.write_scopes) - set(connection.granted_scopes)
    if missing:
        return "permission_missing"
    if connection.write_access_granted_at is None:
        return "changes_not_allowed"
    return None


def org_settings(session: Session, org_id: uuid.UUID) -> ActionSettings:
    """The organization's settings (defaults when never saved; not added to the session)."""
    found = session.get(ActionSettings, org_id)
    return found or ActionSettings(
        organization_id=org_id, paused=False, require_second_person=False
    )


def switches_on(rt: Runtime, session: Session, org_id: uuid.UUID) -> bool:
    return rt.settings.ACTIONS_ENABLED and not org_settings(session, org_id).paused


def require_switches(rt: Runtime, session: Session, org_id: uuid.UUID) -> None:
    if not switches_on(rt, session, org_id):
        raise ActionsDisabled()


def limits_for(
    rt: Runtime,
    session: Session,
    target: Target,
    spec: ActionSpec,
    *,
    undo: bool,
    exclude: uuid.UUID | None = None,
) -> Limits:
    s = rt.settings
    now = rt.clock.now()
    today = now.date()
    currency = target.account.currency
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    settings = org_settings(session, target.account.organization_id)
    if spec.kind is ChangeKind.SET_DAILY_BUDGET:
        fx = FxTable.load(session, today, today, s.FX_MAX_STALE_DAYS)
        minimum = budgets.minimums(s, fx, currency, today).get(target.account.provider)
        if settings.max_daily_budget is not None and settings.max_daily_budget_currency:
            maximum = fx.convert(
                settings.max_daily_budget, settings.max_daily_budget_currency, currency, today
            )
    others = [Action.id != exclude] if exclude is not None else []
    recent = session.execute(
        select(func.count())
        .select_from(Action)
        .where(
            Action.organization_id == target.account.organization_id,
            Action.campaign_id == target.campaign.id,
            Action.action_type == "campaign.set_daily_budget",
            Action.status.in_(SENT),
            Action.submitted_at >= now - s.ACTIONS_BUDGET_CHANGE_INTERVAL,
            *others,
        )
    ).scalar_one()
    used = session.execute(
        select(func.count())
        .select_from(Action)
        .where(
            Action.organization_id == target.account.organization_id,
            Action.ad_account_id == target.account.id,
            or_(
                Action.status.in_(("approved", "queued")),
                Action.submitted_at >= now - s.ACTIONS_VOLUME_WINDOW,
            ),
            *others,
        )
    ).scalar_one()
    return Limits(
        increase_percent=s.ACTIONS_MAX_INCREASE_PERCENT,
        decrease_percent=s.ACTIONS_MAX_DECREASE_PERCENT,
        minimum=minimum,
        maximum=maximum,
        maximum_set=settings.max_daily_budget is not None,
        budget_changed_recently=recent > 0,
        volume_used=int(used),
        volume_limit=s.ACTIONS_DAILY_LIMIT_PER_ACCOUNT,
        undo=undo,
    )
