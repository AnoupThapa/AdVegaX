"""What an organization may do on its plan (Phase 13, tasks 13-02 and 13-05, PHASE_13_PLAN
Q-13-2, Q-13-5 … Q-13-8, Q-13-10; A32).

``standing`` turns the billing account into what is in force **now**:

* billing switched off for the installation → no limits (as before Phase 13);
* a complimentary organization → the Scale limits, never charged;
* a subscription that is active (or in Stripe's own trial) → its plan;
* a payment failed → its plan for ``BILLING_PAYMENT_GRACE`` from the first failure, then
  **read-only**;
* no subscription → the trial (``BILLING_TRIAL_PLAN``) until ``trial_ends_at``, then
  **read-only**.

**Read-only** keeps everything visible; nothing new is added, imported, changed or generated.
Limits are checked on the server when something is **added** (a store, an ad account, a member,
an AI run) or autopilot is switched on; what already exists is never removed by a downgrade.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import OrganizationReadOnly, PlanLimitReached
from app.core.settings import Settings
from app.domains.billing.models import BillingAccount
from app.domains.billing.plans import COMPLIMENTARY_PLAN, PLANS, Plan
from app.domains.integrations.models import ExternalResource, OrganizationResourceLink
from app.domains.organizations.models import Invitation, Membership
from app.runtime import Runtime

LIMITED = ("stores", "ad_accounts", "members")
KIND = {"stores": "store", "ad_accounts": "ad_account"}


@dataclass(frozen=True)
class Standing:
    status: str  # off | complimentary | trialing | active | past_due | read_only
    plan: Plan | None  # the limits in force (None: no limits — billing off — or read-only)
    read_only: bool
    grace_ends_at: datetime | None = None


def standing(
    settings: Settings, org_id: uuid.UUID, account: BillingAccount | None, now: datetime
) -> Standing:
    if not settings.BILLING_ENABLED:
        return Standing("off", None, False)
    if org_id in settings.BILLING_COMPLIMENTARY_ORGANIZATIONS:
        return Standing("complimentary", PLANS[COMPLIMENTARY_PLAN], False)
    if account is None:
        return Standing("trialing", PLANS[settings.BILLING_TRIAL_PLAN], False)
    plan = PLANS.get(account.plan or "")
    status = account.subscription_status
    if plan is not None and status in ("active", "trialing"):
        return Standing("active", plan, False)
    if plan is not None and status in ("past_due", "unpaid"):
        grace = (account.first_failed_at or now) + settings.BILLING_PAYMENT_GRACE
        if now < grace:
            return Standing("past_due", plan, False, grace)
        return Standing("read_only", None, True, grace)
    if now < account.trial_ends_at:
        return Standing("trialing", PLANS[settings.BILLING_TRIAL_PLAN], False)
    return Standing("read_only", None, True)


def account_for(rt: Runtime, session: Session, org_id: uuid.UUID) -> BillingAccount:
    """The organization's billing account, made the first time it is needed while billing is
    on — when the organization is created, or for one that existed before billing was
    switched on, the first time it is used — with its trial starting then (Q-13-2)."""
    account = session.get(BillingAccount, org_id)
    if account is None:
        # Two requests may arrive together: the first insert wins, the other reads it.
        session.execute(
            insert(BillingAccount)
            .values(
                organization_id=org_id,
                subscription_status="none",
                trial_ends_at=rt.clock.now() + timedelta(days=rt.settings.BILLING_TRIAL_DAYS),
                cancel_at_period_end=False,
            )
            .on_conflict_do_nothing(index_elements=["organization_id"])
        )
        account = session.get(BillingAccount, org_id)
        assert account is not None
    return account


def standing_of(rt: Runtime, session: Session, org_id: uuid.UUID) -> Standing:
    if not rt.settings.BILLING_ENABLED:
        return Standing("off", None, False)
    return standing(rt.settings, org_id, account_for(rt, session, org_id), rt.clock.now())


def usage(session: Session, org_id: uuid.UUID, now: datetime) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, kind in KIND.items():
        out[name] = int(
            session.execute(
                select(func.count())
                .select_from(OrganizationResourceLink)
                .join(
                    ExternalResource,
                    ExternalResource.id == OrganizationResourceLink.external_resource_id,
                )
                .where(
                    OrganizationResourceLink.organization_id == org_id,
                    OrganizationResourceLink.status == "active",
                    ExternalResource.kind == kind,
                )
            ).scalar_one()
        )
    members = session.execute(
        select(func.count())
        .select_from(Membership)
        .where(Membership.organization_id == org_id, Membership.status == "active")
    ).scalar_one()
    invited = session.execute(
        select(func.count())
        .select_from(Invitation)
        .where(
            Invitation.organization_id == org_id,
            Invitation.status == "pending",
            Invitation.expires_at > now,
        )
    ).scalar_one()
    out["members"] = int(members) + int(invited)
    return out


def is_read_only(rt: Runtime, session: Session, org_id: uuid.UUID) -> bool:
    """Schedulers skip a read-only organization: nothing new is imported or generated."""
    return rt.settings.BILLING_ENABLED and standing_of(rt, session, org_id).read_only


def require_writable(rt: Runtime, session: Session, org_id: uuid.UUID) -> None:
    if standing_of(rt, session, org_id).read_only:
        raise OrganizationReadOnly()


def require(rt: Runtime, session: Session, org_id: uuid.UUID, what: str) -> None:
    """Refuse adding one more ``what`` (stores, ad_accounts, members) or switching autopilot
    on, when the plan in force does not allow it."""
    now = standing_of(rt, session, org_id)
    if now.read_only:
        raise OrganizationReadOnly()
    if now.plan is None:
        return
    limits = now.plan.limits
    if what == "autopilot":
        if not limits.autopilot:
            raise PlanLimitReached(details=[{"limit": "autopilot", "plan": now.plan.code}])
        return
    allowed = getattr(limits, what)
    used = usage(session, org_id, rt.clock.now())[what]
    if used >= allowed:
        raise PlanLimitReached(
            details=[{"limit": what, "allowed": allowed, "used": used, "plan": now.plan.code}]
        )


def ai_runs_allowed(rt: Runtime, session: Session, org_id: uuid.UUID) -> int:
    """Today's AI runs: the installation's limit, or the plan's when it is lower."""
    now = standing_of(rt, session, org_id)
    if now.read_only:
        return 0
    if now.plan is None:
        return rt.settings.AI_DAILY_RUNS
    return min(rt.settings.AI_DAILY_RUNS, now.plan.limits.ai_runs_per_day)
