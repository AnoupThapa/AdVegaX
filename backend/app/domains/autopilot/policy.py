"""The autopilot policy, its readiness and its switches (Phase 12, task 12-02, PHASE_12_PLAN
Q-12-2 … Q-12-5, Q-12-11; A31).

Autopilot may act for an organization only when **all** of these hold:

1. the installation's switch ``AUTOPILOT_ENABLED`` is on and the organization is in
   ``AUTOPILOT_ORGANIZATIONS`` (staged rollout);
2. the organization is **ready**: at least ``AUTOPILOT_READY_CHANGES`` changes made from
   advice approved by a person, all verified on the platform, none mismatched;
3. an owner switched it on (and nobody stopped it since, and it did not stop itself);
4. the Action Engine's own switches are on (installation and "Pause all changes").
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.actions.facts import switches_on
from app.domains.actions.models import Action
from app.domains.autopilot.models import AUTOMATIC_KINDS, AutopilotPolicy
from app.runtime import Runtime


def policy_for(
    rt: Runtime, session: Session, org_id: uuid.UUID, *, lock: bool = False
) -> AutopilotPolicy:
    """The organization's policy, made (off) with the installation's ceilings the first time."""
    row = session.get(AutopilotPolicy, org_id, with_for_update=lock)
    if row is None:
        s = rt.settings
        row = AutopilotPolicy(
            organization_id=org_id,
            enabled=False,
            kinds=list(AUTOMATIC_KINDS),
            ad_account_ids=[],
            excluded_campaign_ids=[],
            max_changes_per_day=s.AUTOPILOT_MAX_CHANGES_PER_DAY,
            campaign_cooldown_days=s.AUTOPILOT_MIN_COOLDOWN_DAYS,
            max_decrease_percent=s.AUTOPILOT_MAX_DECREASE_PERCENT,
            max_cumulative_decrease_percent=s.AUTOPILOT_MAX_CUMULATIVE_DECREASE_PERCENT,
            cumulative_window_days=s.AUTOPILOT_CUMULATIVE_WINDOW_DAYS,
            min_campaign_age_days=s.AUTOPILOT_MIN_CAMPAIGN_AGE_DAYS,
        )
        session.add(row)
        session.flush()
    return row


def proven(session: Session, org_id: uuid.UUID) -> tuple[int, int]:
    """(verified, mismatched) changes made from advice approved by a person."""
    rows = dict(
        session.execute(
            select(Action.verification, func.count())
            .where(
                Action.organization_id == org_id,
                Action.source == "recommendation",
                Action.status == "succeeded",
            )
            .group_by(Action.verification)
        ).all()
    )
    return int(rows.get("verified", 0)), int(rows.get("mismatch", 0))


def missing(rt: Runtime, session: Session, org_id: uuid.UUID) -> list[str]:
    """What stops autopilot from being switched on (empty: it can be)."""
    s = rt.settings
    reasons = []
    if not s.AUTOPILOT_ENABLED:
        reasons.append("installation_off")
    if org_id not in s.AUTOPILOT_ORGANIZATIONS:
        reasons.append("not_in_rollout")
    verified, mismatched = proven(session, org_id)
    if verified < s.AUTOPILOT_READY_CHANGES:
        reasons.append("too_few_verified_changes")
    if mismatched:
        reasons.append("mismatched_changes")
    if not switches_on(rt, session, org_id):
        reasons.append("changes_switched_off")
    return reasons


def may_act(rt: Runtime, session: Session, policy: AutopilotPolicy) -> bool:
    return policy.enabled and not missing(rt, session, policy.organization_id)


def snapshot(policy: AutopilotPolicy) -> dict[str, Any]:
    """The policy as kept on each automatic change (``actions.policy``)."""
    return {
        "enabled_by": str(policy.enabled_by) if policy.enabled_by else None,
        "enabled_at": policy.enabled_at.isoformat() if policy.enabled_at else None,
        "kinds": list(policy.kinds),
        "ad_account_ids": list(policy.ad_account_ids),
        "max_changes_per_day": policy.max_changes_per_day,
        "campaign_cooldown_days": policy.campaign_cooldown_days,
        "max_decrease_percent": policy.max_decrease_percent,
        "max_cumulative_decrease_percent": policy.max_cumulative_decrease_percent,
        "cumulative_window_days": policy.cumulative_window_days,
        "min_campaign_age_days": policy.min_campaign_age_days,
    }
