"""The Action Engine's state machine and worker (Phase 10A, task 10A-04, Q-10A-6/7/8).

::

    pending ──approve──▶ approved ──▶ queued ──▶ submitting ──▶ succeeded (verified | mismatch)
       │                    │           │            │      ╲──▶ failed
       ├─reject─▶ rejected  ├─cancel    ├─cancel     ╰──────▶ unknown ──look up──▶ succeeded
       ├─cancel─▶ cancelled │           ╰─stale                                  ╲─▶ failed
       ╰─stale──▶ stale     ╰─▶ cancelled

* A change is **written down before the platform is called**: the record moves
  ``queued → submitting`` and commits first. A worker that dies after that leaves
  ``submitting``, which the sweep treats as an unknown outcome — never as "not sent".
* **One at a time per campaign**: at most one open change per campaign (database), and a lock
  around the platform calls (Redis). A job delivered twice finds the record no longer
  ``queued`` and does nothing.
* **Read before write**: right before the call the campaign is read again; if it is no longer
  as it was when the change was requested (another person, or the platform), the change stops
  as ``stale`` and has to be requested again.
* **Never a blind retry**: a timeout or lost answer makes the change ``unknown``; the worker
  reads the campaign to find out (``reconcile``). Made → ``succeeded``; still as before →
  ``failed`` (``not_applied``, safe to request again); something else → ``failed``
  (``changed_elsewhere``). Unreadable → looked up again later, a bounded number of times.
* **Verification**: after a success the campaign is read back and compared (``verified`` /
  ``mismatch``); AdVegaX's copy of the campaign is updated from what the platform reported.
* Both switches (installation and organization) are checked right before the call; while
  either is off, queued changes wait.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.actions import catalogue
from app.domains.actions.catalogue import CATALOGUE
from app.domains.actions.facts import Target, load_target, switches_on, writer_for
from app.domains.actions.models import Action, ActionEvent
from app.domains.advertising.models import AdBudget, AdCampaign
from app.domains.audit.service import Actor, record_audit
from app.domains.integrations.jobs import mark_connection_error
from app.domains.integrations.tokens import AccountBusy, account_lock, usable_secrets
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError, create_job
from app.providers.base.changes import CampaignSnapshot, CampaignWriter, ChangeReceipt
from app.providers.base.errors import AuthExpiredError, ProviderError, UnknownOutcomeError
from app.providers.base.types import AdEntityStatus
from app.runtime import Runtime

logger = logging.getLogger("advegax.actions")

JOB_EXECUTE = "action_execute"
JOB_RECONCILE = "action_reconcile"
# A campaign draft's launch, go-live and cleanup (Phase 10B, ``app/domains/builder/launch.py``).
JOB_DRAFT_EXECUTE = "draft_action_execute"
JOB_DRAFT_RECONCILE = "draft_action_reconcile"


def job_for(action: Action, kind: str) -> str:
    """The job that sends (``execute``) or looks up (``reconcile``) this change."""
    if action.draft_id is not None:
        return JOB_DRAFT_EXECUTE if kind == "execute" else JOB_DRAFT_RECONCILE
    return JOB_EXECUTE if kind == "execute" else JOB_RECONCILE


WORKER = Actor("worker", None)

TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"approved", "rejected", "cancelled", "stale"}),
    "approved": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"submitting", "cancelled", "stale", "failed"}),
    "submitting": frozenset({"succeeded", "failed", "unknown"}),
    "unknown": frozenset({"succeeded", "failed"}),
}
FINAL = frozenset({"rejected", "cancelled", "succeeded", "failed", "stale"})


def transition(
    session: Session,
    rt: Runtime,
    action: Action,
    to: str,
    *,
    user_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Move ``action`` to ``to`` (allowed moves only), with an event and an audit entry."""
    before = action.status
    if to not in TRANSITIONS.get(before, frozenset()):
        raise RuntimeError(f"action cannot move from {before} to {to}")  # programming error
    now = rt.clock.now()
    action.status = to
    action.updated_at = now
    if to in FINAL:
        action.finished_at = now
    session.add(
        ActionEvent(
            organization_id=action.organization_id,
            action_id=action.id,
            seq=next_seq(session, action),
            from_status=before,
            status=to,
            actor_type="user" if user_id else "worker",
            actor_user_id=user_id,
            detail=detail or {},
            created_at=now,
        )
    )
    if action.source == "autopilot" and to in ("failed", "unknown", "stale"):
        from app.domains.autopilot.runner import after_change  # Phase 12 watchdog

        after_change(rt, session, action, "outcome_unknown" if to == "unknown" else "change_failed")
    record_audit(
        session,
        organization_id=action.organization_id,
        actor=Actor.user(user_id) if user_id else WORKER,
        action=f"action.{to}",
        resource_type="action",
        resource_id=action.id,
        before={"status": before},
        after={"status": to},
        metadata={
            "action_type": action.action_type,
            "campaign_id": str(action.campaign_id) if action.campaign_id else None,
            "draft_id": str(action.draft_id) if action.draft_id else None,
            "provider": action.provider,
            **(detail or {}),
        },
    )


def next_seq(session: Session, action: Action) -> int:
    session.flush()
    last = session.execute(
        select(func.max(ActionEvent.seq)).where(
            ActionEvent.organization_id == action.organization_id,
            ActionEvent.action_id == action.id,
        )
    ).scalar_one()
    return int(last or 0) + 1


def schedule(
    session: Session, rt: Runtime, action: Action, job_type: str, *, delay_seconds: int = 0
) -> None:
    create_job(
        session,
        rt,
        organization_id=action.organization_id,
        job_type=job_type,
        subject_type="action",
        subject_id=action.id,
        requested_by=None,
        delay_seconds=delay_seconds,
    )


def platform_call[T](
    rt: Runtime,
    writer: CampaignWriter,
    org_id: uuid.UUID,
    connection_id: uuid.UUID,
    fn: Callable[[], T],
) -> T:
    """Rate-limited call; only an ended sign-in marks the connection (a refused change, e.g.
    a missing change permission, says nothing about reading)."""
    rate, burst = writer.rate_limit
    rt.rate_limiter.acquire(f"{writer.code}:{connection_id}", rate_per_second=rate, burst=burst)
    try:
        return fn()
    except AuthExpiredError as exc:
        mark_connection_error(rt, org_id, connection_id, exc)
        raise


def snapshot_of(data: dict[str, Any], external_id: str) -> CampaignSnapshot:
    """A stored ``previous`` / ``observed`` back as a snapshot."""
    status = data.get("status")
    amount = data.get("daily_budget")
    return CampaignSnapshot(
        external_id=external_id,
        status=AdEntityStatus(status) if status in {s.value for s in AdEntityStatus} else None,
        budget_level=data.get("budget_level"),
        budget_period=data.get("budget_period"),
        daily_budget=Decimal(amount) if amount is not None else None,
        budget_shared=bool(data.get("budget_shared")),
        budget_external_id=data.get("budget_external_id"),
    )


def stored(snapshot: CampaignSnapshot) -> dict[str, Any]:
    """A snapshot as kept on the record (the budget's platform id too: a budget change needs
    it, and it is not secret)."""
    return {**snapshot.as_json(), "budget_external_id": snapshot.budget_external_id}


# ------------------------------------------------------------------ the worker
def _load(job: ClaimedJob) -> tuple[uuid.UUID, uuid.UUID]:
    if job.organization_id is None or job.subject_id is None:
        raise JobSubjectGoneError()
    return job.organization_id, uuid.UUID(job.subject_id)


def _context(
    rt: Runtime, org_id: uuid.UUID, action_id: uuid.UUID, wanted: str
) -> tuple[Action, Target, CampaignWriter] | None:
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id)
        if action is None or action.organization_id != org_id:
            raise JobSubjectGoneError()
        if action.status != wanted:
            return None  # decided, cancelled or already handled (a repeated job)
        if action.campaign_id is None:
            raise JobSubjectGoneError()  # a draft's change: ``builder/launch.py`` sends it
        target = load_target(session, org_id, action.campaign_id)
        writer = writer_for(rt, action.provider)
        if writer is None:
            if wanted == "queued":
                transition(session, rt, action, "failed", detail={"reason": "platform_unavailable"})
                action.error_code = "platform_unavailable"
            return None
        return action, target, writer


def execute(rt: Runtime, job: ClaimedJob) -> None:
    """Send one approved change (job ``action_execute``)."""
    org_id, action_id = _load(job)
    with rt.db.transaction(org_id=org_id) as session:
        if not switches_on(rt, session, org_id):
            return  # waits, queued, until both switches are on again
    found = _context(rt, org_id, action_id, "queued")
    if found is None:
        return
    action, target, writer = found
    try:
        with account_lock(
            rt.redis,
            f"action-campaign:{action.campaign_id}",
            wait_seconds=0,
            ttl_seconds=int(rt.settings.ACTIONS_LOCK_TTL.total_seconds()),
        ):
            _execute_locked(rt, job, action, target, writer)
    except AccountBusy:
        logger.info("action_campaign_busy", extra={"action_id": str(action_id)})
        raise  # another change of this campaign is being sent: the job tries again later


def _fail_before_sending(rt: Runtime, org_id: uuid.UUID, action_id: uuid.UUID, code: str) -> None:
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        if action is not None and action.status == "queued":
            action.error_code = code
            transition(session, rt, action, "failed", detail={"reason": code, "sent": False})


def _execute_locked(
    rt: Runtime, job: ClaimedJob, queued: Action, target: Target, writer: CampaignWriter
) -> None:
    org_id, connection_id, action_id = (
        target.account.organization_id,
        target.connection.id,
        queued.id,
    )
    spec = CATALOGUE[queued.action_type]
    try:
        secrets = usable_secrets(rt, org_id, connection_id)
        now = platform_call(
            rt,
            writer,
            org_id,
            connection_id,
            lambda: writer.read_campaign(
                secrets, target.ref, target.campaign.external_campaign_id, target.account.currency
            ),
        )
    except ProviderError as exc:
        if exc.retryable and job.attempts < job.max_attempts:
            raise  # nothing sent: the job tries again with back-off
        _fail_before_sending(rt, org_id, action_id, exc.code)
        return
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        if action is None or action.status != "queued":
            return  # cancelled while we read
        if not switches_on(rt, session, org_id):
            return
        action.observed = stored(now)
        if not catalogue.same_state(action.previous, now):
            action.error_code = "campaign_changed"
            transition(session, rt, action, "stale", detail={"reason": "campaign_changed"})
            return
        params = dict(action.params)
        change = catalogue.change_of(spec, params)
        before = snapshot_of(action.previous, target.campaign.external_campaign_id)
        action.submitted_at = rt.clock.now()
        action.platform_request = {"change": spec.kind.value, **params}
        transition(session, rt, action, "submitting")
    # Committed: from here on, the change may reach the platform.
    receipt: ChangeReceipt | None = None
    outcome, code = "succeeded", None
    try:
        receipt = platform_call(
            rt,
            writer,
            org_id,
            connection_id,
            lambda: writer.change_campaign(
                secrets, target.ref, before, change, target.account.currency, validate_only=False
            ),
        )
    except UnknownOutcomeError:
        outcome, code = "unknown", "outcome_unknown"
    except ProviderError as exc:
        outcome, code = "failed", exc.code
    except Exception:  # anything unexpected: we cannot know whether it was made
        logger.exception("action_call_error", extra={"action_id": str(action_id)})
        outcome, code = "unknown", "outcome_unknown"
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        if action is None:  # pragma: no cover - deleted with its organization
            return
        if receipt is not None:
            action.platform_request = receipt.request
            action.platform_answer = receipt.answer
        action.error_code = code
        if outcome == "unknown":
            transition(session, rt, action, "unknown", detail={"reason": code})
            schedule(
                session,
                rt,
                action,
                JOB_RECONCILE,
                delay_seconds=int(rt.settings.ACTIONS_RECONCILE_DELAY.total_seconds()),
            )
            return
        if outcome == "failed":
            action.platform_answer = {"refused": code}
            transition(session, rt, action, "failed", detail={"reason": code, "sent": True})
            return
        transition(session, rt, action, "succeeded")
    verify(rt, org_id, action_id, target, writer, secrets)


def verify(
    rt: Runtime,
    org_id: uuid.UUID,
    action_id: uuid.UUID,
    target: Target,
    writer: CampaignWriter,
    secrets: Any,
) -> None:
    """Read the campaign back after a success and compare (best effort: an unreadable
    campaign leaves ``not_checked``)."""
    try:
        now: CampaignSnapshot | None = platform_call(
            rt,
            writer,
            org_id,
            target.connection.id,
            lambda: writer.read_campaign(
                secrets, target.ref, target.campaign.external_campaign_id, target.account.currency
            ),
        )
    except ProviderError:
        now = None
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        if action is None:  # pragma: no cover
            return
        spec = CATALOGUE[action.action_type]
        if now is None:
            action.verification = "not_checked"
            if action.source == "autopilot":
                from app.domains.autopilot.runner import after_change  # Phase 12 watchdog

                after_change(rt, session, action, "not_verified")
            return
        action.observed = stored(now)
        action.verification = (
            "verified" if catalogue.reached(spec, action.params, now) else "mismatch"
        )
        if action.source == "autopilot" and action.verification != "verified":
            from app.domains.autopilot.runner import after_change  # Phase 12 watchdog

            after_change(rt, session, action, "not_verified")
        action.updated_at = rt.clock.now()
        record_audit(
            session,
            organization_id=org_id,
            actor=WORKER,
            action="action.verified",
            resource_type="action",
            resource_id=action.id,
            metadata={"verification": action.verification},
        )
        mirror(session, target.campaign.id, org_id, now)


def mirror(
    session: Session, campaign_id: uuid.UUID, org_id: uuid.UUID, now: CampaignSnapshot
) -> None:
    """Keep AdVegaX's copy of the campaign as the platform just reported it (the next sync
    reads it again anyway)."""
    campaign = session.get(AdCampaign, campaign_id)
    if campaign is None or campaign.organization_id != org_id:
        return
    if now.status is not None:
        campaign.status = now.status.value
    if campaign.budget_id is not None and now.daily_budget is not None:
        budget = session.get(AdBudget, campaign.budget_id)
        if budget is not None and budget.period == "daily" and budget.level == "campaign":
            budget.amount = now.daily_budget


def reconcile(rt: Runtime, job: ClaimedJob) -> None:
    """Find out what happened to a change whose outcome is unknown (job ``action_reconcile``).
    Only reads; never sends the change again."""
    org_id, action_id = _load(job)
    found = _context(rt, org_id, action_id, "unknown")
    if found is None:
        return
    action, target, writer = found
    spec = CATALOGUE[action.action_type]
    try:
        secrets = usable_secrets(rt, org_id, target.connection.id)
        now = platform_call(
            rt,
            writer,
            org_id,
            target.connection.id,
            lambda: writer.read_campaign(
                secrets, target.ref, target.campaign.external_campaign_id, target.account.currency
            ),
        )
    except ProviderError as exc:
        _look_again(rt, org_id, action_id, exc.code)
        return
    with rt.db.transaction(org_id=org_id) as session:
        row = session.get(Action, action_id, with_for_update=True)
        if row is None or row.status != "unknown":
            return
        row.observed = stored(now)
        row.reconcile_attempts += 1
        if catalogue.reached(spec, row.params, now):
            row.error_code = None
            row.verification = "verified"
            transition(session, rt, row, "succeeded", detail={"found_by": "look_up"})
            mirror(session, target.campaign.id, org_id, now)
        elif catalogue.same_state(row.previous, now):
            row.error_code = "not_applied"
            transition(session, rt, row, "failed", detail={"reason": "not_applied"})
        else:
            row.error_code = "changed_elsewhere"
            transition(session, rt, row, "failed", detail={"reason": "changed_elsewhere"})


def _look_again(rt: Runtime, org_id: uuid.UUID, action_id: uuid.UUID, code: str) -> None:
    with rt.db.transaction(org_id=org_id) as session:
        row = session.get(Action, action_id, with_for_update=True)
        if row is None or row.status != "unknown":
            return
        row.reconcile_attempts += 1
        row.updated_at = rt.clock.now()
        if row.reconcile_attempts >= rt.settings.ACTIONS_RECONCILE_ATTEMPTS:
            row.error_code = "needs_checking"  # a person checks the campaign at the platform
            logger.warning("action_outcome_still_unknown", extra={"action_id": str(action_id)})
            return
        row.error_code = code
        schedule(
            session,
            rt,
            row,
            JOB_RECONCILE,
            delay_seconds=int(rt.settings.ACTIONS_RECONCILE_DELAY.total_seconds())
            * row.reconcile_attempts,
        )


# ------------------------------------------------------------------ the sweep
def sweep(rt: Runtime) -> int:
    """Every few minutes: queued changes whose message was lost are sent again (while both
    switches are on); a change left ``submitting`` by a worker that stopped becomes
    ``unknown`` and is looked up; unknown outcomes are looked up again. Returns how many."""
    now = rt.clock.now()
    with rt.db.transaction(system=True) as session:
        rows = session.execute(
            select(Action.id, Action.organization_id, Action.status, Action.updated_at).where(
                Action.status.in_(("queued", "submitting", "unknown"))
            )
        ).all()
    started = 0
    for action_id, org_id, status, updated_at in rows:
        with rt.db.transaction(org_id=org_id) as session:
            action = session.get(Action, action_id, with_for_update=True)
            if action is None or action.status != status:
                continue
            if status == "queued":
                if updated_at > now - rt.settings.SCHEDULE_ACTIONS_SWEEP_INTERVAL:
                    continue
                if not switches_on(rt, session, org_id):
                    continue
                action.updated_at = now
                schedule(session, rt, action, job_for(action, "execute"))
            elif status == "submitting":
                if updated_at > now - rt.settings.ACTIONS_LOCK_TTL:
                    continue
                action.error_code = "outcome_unknown"
                transition(session, rt, action, "unknown", detail={"reason": "worker_stopped"})
                schedule(session, rt, action, job_for(action, "reconcile"))
            else:
                if action.reconcile_attempts >= rt.settings.ACTIONS_RECONCILE_ATTEMPTS:
                    continue
                if updated_at > now - rt.settings.SCHEDULE_ACTIONS_SWEEP_INTERVAL:
                    continue
                action.updated_at = now
                schedule(session, rt, action, job_for(action, "reconcile"))
            started += 1
    if started:
        logger.info("actions_swept", extra={"count": started})
    return started


def resume_queued(session: Session, rt: Runtime, org_id: uuid.UUID) -> int:
    """After "Pause all changes" is lifted: send the organization's queued changes."""
    queued = list(
        session.execute(
            select(Action).where(Action.organization_id == org_id, Action.status == "queued")
        ).scalars()
    )
    for action in queued:
        schedule(session, rt, action, job_for(action, "execute"))
    return len(queued)
