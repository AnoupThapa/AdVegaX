"""Autopilot: its policy, switching it on and off, and its runs (Phase 12, task 12-05,
PHASE_12_PLAN Q-12-2 … Q-12-8; A31).

* **Read** (every role): the policy, readiness and the installation's ceilings; the runs.
* **Change the policy** and **switch on** (owners only): limits may only be as strict as the
  installation's ceilings or stricter; switching on needs the organization's name typed and
  readiness (``policy.missing``); included ad accounts must be the organization's own.
* **Stop** (owner, admin, manager): one step, takes effect at once.

Every step is audited.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AutopilotConfirmation, AutopilotNotReady, ValidationFailed
from app.core.settings import Settings
from app.domains.advertising.models import AdAccount, AdCampaign
from app.domains.audit.service import Actor, record_audit
from app.domains.autopilot.models import AutopilotPolicy, AutopilotRun
from app.domains.autopilot.policy import missing, policy_for, proven
from app.domains.autopilot.runner import stop
from app.domains.autopilot.schemas import (
    AutopilotEnableIn,
    AutopilotLimits,
    AutopilotPolicyIn,
    AutopilotPolicyOut,
    AutopilotRunOut,
    ReadinessOut,
)
from app.domains.billing import entitlements
from app.domains.organizations.models import Organization
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

LIMITS = (
    "max_changes_per_day",
    "campaign_cooldown_days",
    "max_decrease_percent",
    "max_cumulative_decrease_percent",
    "cumulative_window_days",
    "min_campaign_age_days",
)


def ceilings(s: Settings) -> AutopilotLimits:
    return AutopilotLimits(
        max_changes_per_day=s.AUTOPILOT_MAX_CHANGES_PER_DAY,
        campaign_cooldown_days=s.AUTOPILOT_MIN_COOLDOWN_DAYS,
        max_decrease_percent=s.AUTOPILOT_MAX_DECREASE_PERCENT,
        max_cumulative_decrease_percent=s.AUTOPILOT_MAX_CUMULATIVE_DECREASE_PERCENT,
        cumulative_window_days=s.AUTOPILOT_CUMULATIVE_WINDOW_DAYS,
        min_campaign_age_days=s.AUTOPILOT_MIN_CAMPAIGN_AGE_DAYS,
    )


def looser(limits: AutopilotLimits, bound: AutopilotLimits) -> list[str]:
    """The limits looser than the installation allows (counts and percentages above their
    ceiling; waiting times shorter than their floor)."""
    out = []
    for name in ("max_changes_per_day", "max_decrease_percent", "max_cumulative_decrease_percent"):
        if getattr(limits, name) > getattr(bound, name):
            out.append(name)
    for name in ("campaign_cooldown_days", "cumulative_window_days", "min_campaign_age_days"):
        if getattr(limits, name) < getattr(bound, name):
            out.append(name)
    return out


class AutopilotService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    def _out(self, session: Session, org_id: uuid.UUID, row: AutopilotPolicy) -> AutopilotPolicyOut:
        verified, _ = proven(session, org_id)
        lacking = missing(self.rt, session, org_id)
        return AutopilotPolicyOut(
            enabled=row.enabled,
            enabled_by=row.enabled_by,
            enabled_at=row.enabled_at,
            stopped_by=row.stopped_by,
            stopped_at=row.stopped_at,
            stopped_reason=row.stopped_reason,
            kinds=list(row.kinds),
            ad_account_ids=[uuid.UUID(a) for a in row.ad_account_ids],
            excluded_campaign_ids=[uuid.UUID(c) for c in row.excluded_campaign_ids],
            **{name: getattr(row, name) for name in LIMITS},
            ceilings=ceilings(self.rt.settings),
            readiness=ReadinessOut(
                ready=not lacking,
                missing=lacking,
                verified_changes=verified,
                needed_changes=self.rt.settings.AUTOPILOT_READY_CHANGES,
            ),
            updated_at=row.updated_at if row.updated_by else None,
        )

    def get(self, ctx: TenantContext) -> AutopilotPolicyOut:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._out(
                session, ctx.organization_id, policy_for(self.rt, session, ctx.organization_id)
            )

    def put(self, ctx: TenantContext, body: AutopilotPolicyIn) -> AutopilotPolicyOut:
        authorize(ctx, Permission.AUTOPILOT_MANAGE)
        bad = looser(body, ceilings(self.rt.settings))
        if bad:
            raise ValidationFailed(
                details=[{"field": name, "reason": "beyond_installation_limit"} for name in bad]
            )
        org_id = ctx.organization_id
        with self.rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            accounts = {
                str(a)
                for a in session.execute(
                    select(AdAccount.id).where(AdAccount.organization_id == org_id)
                ).scalars()
            }
            chosen = [str(a) for a in dict.fromkeys(body.ad_account_ids)]
            unknown = [a for a in chosen if a not in accounts]
            campaigns = [str(c) for c in dict.fromkeys(body.excluded_campaign_ids)]
            known = {
                str(c)
                for c in session.execute(
                    select(AdCampaign.id).where(AdCampaign.organization_id == org_id)
                ).scalars()
            }
            if unknown or any(c not in known for c in campaigns):
                raise ValidationFailed(details=[{"reason": "not_this_organization"}])
            row = policy_for(self.rt, session, org_id, lock=True)
            row.kinds = list(dict.fromkeys(body.kinds))
            row.ad_account_ids = chosen
            row.excluded_campaign_ids = campaigns
            for name in LIMITS:
                setattr(row, name, getattr(body, name))
            row.updated_by, row.updated_at = ctx.user_id, self.rt.clock.now()
            record_audit(
                session,
                organization_id=org_id,
                actor=Actor.user(ctx.user_id),
                action="autopilot.policy_updated",
                resource_type="autopilot_policy",
                resource_id=org_id,
                after=body.model_dump(mode="json"),
            )
            session.flush()
            return self._out(session, org_id, row)

    def enable(self, ctx: TenantContext, body: AutopilotEnableIn) -> AutopilotPolicyOut:
        authorize(ctx, Permission.AUTOPILOT_MANAGE)
        org_id = ctx.organization_id
        with self.rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            org = session.get(Organization, org_id)
            assert org is not None
            if body.confirm.strip() != org.name.strip():
                raise AutopilotConfirmation()
            entitlements.require(self.rt, session, org_id, "autopilot")  # Phase 13, Q-13-1
            lacking = missing(self.rt, session, org_id)
            row = policy_for(self.rt, session, org_id, lock=True)
            if not row.kinds:
                lacking.append("no_kinds")
            if not row.ad_account_ids:
                lacking.append("no_ad_accounts")
            if lacking:
                raise AutopilotNotReady(details=[{"reason": r} for r in lacking])
            now = self.rt.clock.now()
            row.enabled = True
            row.enabled_by, row.enabled_at = ctx.user_id, now
            row.stopped_by = row.stopped_at = row.stopped_reason = None
            row.updated_by, row.updated_at = ctx.user_id, now
            record_audit(
                session,
                organization_id=org_id,
                actor=Actor.user(ctx.user_id),
                action="autopilot.enabled",
                resource_type="autopilot_policy",
                resource_id=org_id,
                after={"enabled": True, "kinds": list(row.kinds)},
            )
            session.flush()
            return self._out(session, org_id, row)

    def stop(self, ctx: TenantContext) -> AutopilotPolicyOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        org_id = ctx.organization_id
        with self.rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            row = policy_for(self.rt, session, org_id, lock=True)
            stop(self.rt, session, row, "stopped", user_id=ctx.user_id)
            session.flush()
            return self._out(session, org_id, row)

    def runs(self, ctx: TenantContext, limit: int = 30) -> list[AutopilotRunOut]:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rows = session.execute(
                select(AutopilotRun)
                .where(AutopilotRun.organization_id == ctx.organization_id)
                .order_by(AutopilotRun.started_at.desc())
                .limit(limit)
            ).scalars()
            return [
                AutopilotRunOut(
                    id=r.id,
                    started_at=r.started_at,
                    considered=r.considered,
                    made=[uuid.UUID(m) for m in r.made],
                    skipped=list(r.skipped),
                    limit_reached=r.limit_reached,
                    stopped_reason=r.stopped_reason,
                )
                for r in rows
            ]
