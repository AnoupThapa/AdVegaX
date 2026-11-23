"""Autopilot's runs and its watchdog (Phase 12, tasks 12-03 and 12-04, PHASE_12_PLAN Q-12-1,
Q-12-4, Q-12-6 … Q-12-9; A31).

**A run** follows each daily look (and "Look again now"), one at a time per organization (a
lock). If autopilot may act (``policy.may_act``), each new open advice of an allowed kind —
only **pause** and a **lower** daily budget, never anything that raises spend — is taken in
rank order when it is in an included ad account, its campaign is not excluded, and every limit
holds:

* at most ``max_changes_per_day`` automatic changes a day (the reporting time zone's day);
* at most one automatic change per campaign in ``campaign_cooldown_days``;
* a budget lowered by at most ``max_decrease_percent`` at a time, and by at most
  ``max_cumulative_decrease_percent`` over ``cumulative_window_days`` (from the budget before
  the first automatic cut in that window);
* the campaign has run for at least ``min_campaign_age_days``.

It is checked again like a person's approval (still open, campaign unchanged, rule still true),
then **requested and approved by autopilot** through the Action Engine — every 10A check, the
platform's test, read-back and verification — with the policy snapshot kept on the change.
Everything skipped is recorded with its reason; a person can still act on it.

**The watchdog** stops autopilot for the organization (and emails the owners) when an automatic
change fails, is not verified or its outcome is unknown, the platform or AdVegaX refuses one,
or the day's limit was reached ``AUTOPILOT_LIMIT_HITS_TO_STOP`` times within
``AUTOPILOT_LIMIT_HITS_WINDOW``. An owner must switch it on again.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.domains.actions.models import Action
from app.domains.actions.schemas import ActionIn
from app.domains.actions.service import ActionService
from app.domains.advertising.models import AdCampaign, AdPerformanceDaily
from app.domains.audit.service import Actor, record_audit
from app.domains.autopilot.models import AUTOMATIC_KINDS, AutopilotPolicy, AutopilotRun
from app.domains.autopilot.policy import may_act, policy_for, snapshot
from app.domains.identity.models import User
from app.domains.integrations.tokens import AccountBusy, account_lock
from app.domains.optimization.explain import money
from app.domains.optimization.models import Recommendation
from app.domains.organizations.models import Membership, Organization
from app.runtime import Runtime

logger = logging.getLogger("advegax.autopilot")
AUTOPILOT = Actor("autopilot", None)
HUNDRED = Decimal(100)
PAUSE, BUDGET = "campaign.pause", "campaign.set_daily_budget"
# Refusals that mean a person should look before autopilot acts again (Q-12-9).
STOPPING_CODES = {"ACTION_NOT_ALLOWED", "ACTION_INVALID", "SERVICE_UNAVAILABLE", "ACTIONS_DISABLED"}


def _day_start(now: datetime, timezone: str) -> datetime:
    local = now.astimezone(ZoneInfo(timezone)).date()
    return datetime.combine(local, time(0), tzinfo=ZoneInfo(timezone))


def _first_day(session: Session, campaign: AdCampaign) -> date | None:
    if campaign.start_date is not None:
        return campaign.start_date
    first: date | None = session.execute(
        select(func.min(AdPerformanceDaily.day)).where(
            AdPerformanceDaily.campaign_id == campaign.id
        )
    ).scalar_one()
    return first


def _automatic(
    session: Session, org_id: uuid.UUID, campaign_id: uuid.UUID, since: datetime
) -> list[Action]:
    return list(
        session.execute(
            select(Action)
            .where(
                Action.organization_id == org_id,
                Action.campaign_id == campaign_id,
                Action.source == "autopilot",
                Action.created_at >= since,
            )
            .order_by(Action.created_at)
        ).scalars()
    )


def refusal(
    session: Session, policy: AutopilotPolicy, rec: Recommendation, now: datetime, today: date
) -> str | None:
    """Why autopilot leaves this advice to a person (None: it may act on it)."""
    if rec.kind not in AUTOMATIC_KINDS or rec.kind not in policy.kinds:
        return "kind_not_allowed"
    proposal = rec.proposal or {}
    kind = proposal.get("action_type")
    if kind not in (PAUSE, BUDGET) or rec.campaign_id is None:
        return "no_change"
    if str(rec.ad_account_id) not in policy.ad_account_ids:
        return "account_not_included"
    if str(rec.campaign_id) in policy.excluded_campaign_ids:
        return "campaign_excluded"
    campaign = session.get(AdCampaign, rec.campaign_id)
    if campaign is None:
        return "campaign_unavailable"
    first = _first_day(session, campaign)
    if first is None or (today - first).days < policy.min_campaign_age_days:
        return "campaign_too_new"
    org_id = rec.organization_id
    if _automatic(
        session, org_id, campaign.id, now - timedelta(days=policy.campaign_cooldown_days)
    ):
        return "campaign_cooldown"
    if kind == BUDGET:
        new = Decimal(proposal["params"]["daily_budget"])
        before = (proposal.get("previous") or {}).get("daily_budget")
        if before is None or new >= Decimal(before):
            return "not_a_decrease"  # autopilot never raises a budget
        old = Decimal(before)
        if (old - new) / old * HUNDRED > policy.max_decrease_percent:
            return "decrease_too_large"
        window = now - timedelta(days=policy.cumulative_window_days)
        cuts = [
            a
            for a in _automatic(session, org_id, campaign.id, window)
            if a.action_type == BUDGET and a.status not in ("rejected", "cancelled", "failed")
        ]
        if cuts:
            start = Decimal(str((cuts[0].previous or {}).get("daily_budget") or old))
            if (
                start > 0
                and (start - new) / start * HUNDRED > policy.max_cumulative_decrease_percent
            ):
                return "cumulative_limit"
    return None


# ------------------------------------------------------------------ notifications
def _owners(session: Session, org_id: uuid.UUID) -> list[str]:
    return list(
        session.execute(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == org_id,
                Membership.role == "owner",
                Membership.status == "active",
            )
            .order_by(User.email)
        ).scalars()
    )


def _link(rt: Runtime, org_id: uuid.UUID, path: str) -> str:
    return f"{rt.settings.APP_BASE_URL.rstrip('/')}/orgs/{org_id}{path}"


def describe(session: Session, action: Action) -> str:
    campaign = session.get(AdCampaign, action.campaign_id) if action.campaign_id else None
    name = campaign.name if campaign else "a campaign"
    if action.action_type == PAUSE:
        return f"Paused {name}"
    old = (action.previous or {}).get("daily_budget")
    new = (action.params or {}).get("daily_budget")
    cur = action.currency
    return (
        f"Lowered the daily budget of {name} from "
        f"{money(Decimal(old), cur) if old else 'its budget'} to {money(Decimal(str(new)), cur)}"
    )


def notify(rt: Runtime, session: Session, org_id: uuid.UUID, template: str, **values: Any) -> None:
    org = session.get(Organization, org_id)
    for email in _owners(session, org_id):
        rt.notifications.send_email(
            session,
            template=template,
            recipient=email,
            organization_id=org_id,
            variables={"organization_name": org.name if org else "", **values},
        )


# ------------------------------------------------------------------ stopping
def stop(
    rt: Runtime,
    session: Session,
    policy: AutopilotPolicy,
    reason: str,
    *,
    user_id: uuid.UUID | None = None,
) -> None:
    """Switch autopilot off for the organization; when it stopped itself, tell the owners."""
    if not policy.enabled:
        return
    now = rt.clock.now()
    policy.enabled = False
    policy.stopped_at, policy.stopped_by, policy.stopped_reason = now, user_id, reason
    policy.updated_at = now
    record_audit(
        session,
        organization_id=policy.organization_id,
        actor=Actor.user(user_id) if user_id else AUTOPILOT,
        action="autopilot.stopped",
        resource_type="autopilot_policy",
        resource_id=policy.organization_id,
        after={"enabled": False},
        metadata={"reason": reason},
    )
    if user_id is None:
        notify(
            rt,
            session,
            policy.organization_id,
            "autopilot_stopped",
            reason=STOP_TEXT.get(reason, reason),
            link=_link(rt, policy.organization_id, "/settings"),
        )


STOP_TEXT = {
    "change_failed": "An automatic change could not be made.",
    "outcome_unknown": "AdVegaX could not confirm whether an automatic change was made.",
    "not_verified": "The platform does not show an automatic change as it was sent.",
    "change_refused": "An automatic change was refused before it was sent.",
    "daily_limit_reached": "Autopilot reached its daily limit twice within a week.",
}


def after_change(rt: Runtime, session: Session, action: Action, problem: str) -> None:
    """The watchdog: an automatic change ended badly — stop autopilot (Q-12-9)."""
    if action.source != "autopilot":
        return
    policy = session.get(AutopilotPolicy, action.organization_id, with_for_update=True)
    if policy is not None:
        stop(rt, session, policy, problem)


# ------------------------------------------------------------------ the run
def run(rt: Runtime, org_id: uuid.UUID) -> uuid.UUID | None:
    """Act on today's eligible advice; returns the run's id (None: autopilot may not act)."""
    try:
        with account_lock(rt.redis, f"autopilot:{org_id}", wait_seconds=0):
            return _run(rt, org_id)
    except AccountBusy:
        return None  # another run for this organization is in progress


def _run(rt: Runtime, org_id: uuid.UUID) -> uuid.UUID | None:
    now = rt.clock.now()
    with rt.db.transaction(org_id=org_id) as session:
        policy = policy_for(rt, session, org_id)
        if not may_act(rt, session, policy):
            return None
        org = session.get(Organization, org_id)
        assert org is not None
        today = now.astimezone(ZoneInfo(org.default_timezone)).date()
        made_today = session.execute(
            select(func.count())
            .select_from(Action)
            .where(
                Action.organization_id == org_id,
                Action.source == "autopilot",
                Action.created_at >= _day_start(now, org.default_timezone),
            )
        ).scalar_one()
        recs = list(
            session.execute(
                select(Recommendation)
                .where(
                    Recommendation.organization_id == org_id,
                    Recommendation.status == "open",
                    Recommendation.expires_at > now,
                )
                .order_by(Recommendation.rank, Recommendation.created_at)
            ).scalars()
        )
        skipped: list[dict[str, Any]] = []
        eligible: list[uuid.UUID] = []
        for rec in recs:
            why = refusal(session, policy, rec, now, today)
            if why:
                skipped.append({"recommendation_id": str(rec.id), "reason": why})
            else:
                eligible.append(rec.id)
        allowed = snapshot(policy)
        room = max(0, policy.max_changes_per_day - int(made_today))
        considered = len(recs)

    made: list[str] = []
    stopped: str | None = None
    limit_reached = len(eligible) > room
    actions = ActionService(rt)
    for rec_id in eligible[:room]:
        body = _approvable(rt, org_id, rec_id, skipped)
        if body is None:
            continue
        try:
            action_id = actions.request_automatic(
                org_id, body, recommendation_id=rec_id, policy=allowed
            )
            actions.approve_automatic(org_id, action_id)
        except AppError as exc:
            skipped.append({"recommendation_id": str(rec_id), "reason": exc.code.lower()})
            if exc.code in STOPPING_CODES:
                stopped = "change_refused"
                break
            continue
        made.append(str(action_id))
        with rt.db.transaction(org_id=org_id) as session:
            approved = session.get(Recommendation, rec_id, with_for_update=True)
            assert approved is not None
            approved.status = "approved"
            approved.decided_at = rt.clock.now()
            approved.updated_at = rt.clock.now()
            record_audit(
                session,
                organization_id=org_id,
                actor=AUTOPILOT,
                action="recommendation.approved",
                resource_type="recommendation",
                resource_id=approved.id,
                after={"status": "approved"},
                metadata={"kind": approved.kind, "action_id": str(action_id), "by": "autopilot"},
            )

    with rt.db.transaction(org_id=org_id) as session:
        policy = policy_for(rt, session, org_id, lock=True)
        if stopped is None and limit_reached:
            hits = session.execute(
                select(func.count())
                .select_from(AutopilotRun)
                .where(
                    AutopilotRun.organization_id == org_id,
                    AutopilotRun.limit_reached.is_(True),
                    AutopilotRun.started_at >= now - rt.settings.AUTOPILOT_LIMIT_HITS_WINDOW,
                )
            ).scalar_one()
            if hits + 1 >= rt.settings.AUTOPILOT_LIMIT_HITS_TO_STOP:
                stopped = "daily_limit_reached"
        row = AutopilotRun(
            organization_id=org_id,
            started_at=now,
            considered=considered,
            made=made,
            skipped=skipped,
            limit_reached=limit_reached,
            stopped_reason=stopped,
        )
        session.add(row)
        session.flush()
        if made:
            lines = []
            for made_id in made:
                found = session.get(Action, uuid.UUID(made_id))
                if found is not None:
                    lines.append(describe(session, found))
            notify(
                rt,
                session,
                org_id,
                "autopilot_changes",
                lines=lines,
                link=_link(rt, org_id, "/changes"),
            )
        if stopped:
            stop(rt, session, policy, stopped)
        record_audit(
            session,
            organization_id=org_id,
            actor=AUTOPILOT,
            action="autopilot.run",
            resource_type="autopilot_run",
            resource_id=row.id,
            metadata={"made": len(made), "skipped": len(skipped), "stopped": stopped},
        )
        run_id = row.id
    logger.info("autopilot_run", extra={"organization_id": str(org_id), "made": len(made)})
    return run_id


def _approvable(
    rt: Runtime, org_id: uuid.UUID, rec_id: uuid.UUID, skipped: list[dict[str, Any]]
) -> ActionIn | None:
    """Checked again as for a person (still open and valid, campaign unchanged, rule true)."""
    from app.domains.optimization.service import staleness

    with rt.db.transaction(org_id=org_id) as session:
        rec = session.get(Recommendation, rec_id, with_for_update=True)
        if rec is None or rec.status != "open" or rec.expires_at <= rt.clock.now():
            skipped.append({"recommendation_id": str(rec_id), "reason": "closed"})
            return None
        why = staleness(rt, session, org_id, rec)
        if why:
            rec.status, rec.closed_reason = "out_of_date", why
            rec.updated_at = rt.clock.now()
            skipped.append({"recommendation_id": str(rec_id), "reason": why})
            return None
        return ActionIn(
            action_type=rec.proposal["action_type"],
            campaign_id=rec.campaign_id,
            params=dict(rec.proposal.get("params") or {}),
        )
