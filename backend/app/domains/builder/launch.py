"""Launching a campaign draft through the Action Engine (Phase 10B, task 10B-04, Q-10B-8/9).

Three changes of a draft, each requested, approved and audited like any 10A change:

* ``campaign.create`` — everything created **paused** (Google: one all-or-nothing request;
  Meta: image, campaign, ad set, creative, ad — each paused, each ID kept as it exists);
* ``campaign.go_live`` — the created campaign switched on (Meta: ad, ad set, campaign);
* ``campaign.remove_draft_objects`` — what a failed launch created is removed.

The engine's guarantees hold: written down before the call, one change of a draft at a time
(database and lock), both switches checked right before the call, and an unknown outcome is
**looked up by the draft's reference** (in every name), never sent again. Before creating,
the platform is searched for the reference too, so a campaign is never created twice.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ActionInvalid, ActionNotAllowed
from app.core.storage import StorageError
from app.domains.actions import engine
from app.domains.actions.facts import switches_on
from app.domains.actions.models import Action
from app.domains.actions.schemas import DraftRefOut
from app.domains.actions.validation import failures, passed
from app.domains.advertising.importer import SyncMode, start_sync
from app.domains.advertising.models import AdAccount
from app.domains.builder import checks as draft_checks
from app.domains.builder.context import (
    DraftContext,
    build_of,
    builder_for,
    facts,
    has_conversions,
    load,
)
from app.domains.builder.models import CampaignDraft
from app.domains.creative.service import storage_for
from app.domains.integrations.tokens import AccountBusy, account_lock, usable_secrets
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError
from app.providers.base.changes import BuildIncomplete, BuildResult, CampaignBuilder
from app.providers.base.errors import ProviderError, UnknownOutcomeError
from app.providers.base.types import AdEntityStatus
from app.runtime import Runtime

logger = logging.getLogger("advegax.builder")

CREATE, GO_LIVE, REMOVE = "campaign.create", "campaign.go_live", "campaign.remove_draft_objects"
COMPLETE = {"google_ads": ("campaign", "budget"), "meta_ads": ("campaign", "ad_set", "ad")}


def draft_ref_of(session: Session, org_id: uuid.UUID, draft_id: uuid.UUID) -> DraftRefOut | None:
    draft = session.get(CampaignDraft, draft_id)
    if draft is None or draft.organization_id != org_id:
        return None
    account = session.get(AdAccount, draft.ad_account_id)
    return DraftRefOut(
        id=draft.id,
        name=draft.name,
        platform=draft.platform,
        ad_account_id=draft.ad_account_id,
        ad_account_name=account.name if account else None,
        strategy_id=draft.strategy_id,
        status=draft.status,
    )


def preconditions(c: DraftContext, action_type: str) -> str | None:
    """Why this change of the draft cannot be made now (None: it can)."""
    d = c.draft
    if action_type == CREATE:
        return None if d.status == "draft" else "draft_not_launchable"
    if action_type == GO_LIVE:
        return (
            None if d.status == "created" and d.created_ids.get("campaign") else "draft_not_created"
        )
    if d.status not in ("failed", "created") or not d.created_ids:
        return "nothing_to_remove"
    return None


def recheck(rt: Runtime, session: Session, action: Action) -> None:
    """At approval: the draft is unchanged since the request, and every check still passes."""
    assert action.draft_id is not None
    c = load(session, action.organization_id, action.draft_id)
    builder = builder_for(rt, c.account.provider)
    problem = None
    if builder is not None:
        from app.domains.actions.facts import write_access_problem

        problem = write_access_problem(c.connection, builder)
    if problem is not None:
        raise ActionNotAllowed(details=[{"reason": problem}])
    reason = preconditions(c, action.action_type)
    if reason is None and int(action.params.get("version", 0)) != c.draft.version:
        reason = "draft_changed"
    if reason is not None:
        raise ActionInvalid(details=[{"check": "draft", "reason": reason}])
    if action.action_type == CREATE:
        results = draft_checks.run(facts(rt, session, c, exclude=action.id))
        if not passed(results):
            raise ActionInvalid(details=failures(results))


# ------------------------------------------------------------------ the worker
def _load_job(job: ClaimedJob) -> tuple[uuid.UUID, uuid.UUID]:
    if job.organization_id is None or job.subject_id is None:
        raise JobSubjectGoneError()
    return job.organization_id, uuid.UUID(job.subject_id)


def _context(
    rt: Runtime, org_id: uuid.UUID, action_id: uuid.UUID, wanted: str
) -> tuple[Action, DraftContext, CampaignBuilder] | None:
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id)
        if action is None or action.organization_id != org_id or action.draft_id is None:
            raise JobSubjectGoneError()
        if action.status != wanted:
            return None
        c = load(session, org_id, action.draft_id)
        builder = builder_for(rt, c.account.provider)
        if builder is None:
            if wanted == "queued":
                action.error_code = "platform_unavailable"
                engine.transition(
                    session, rt, action, "failed", detail={"reason": "platform_unavailable"}
                )
            return None
        return action, c, builder


def _call(rt: Runtime, builder: CampaignBuilder, c: DraftContext, fn: Any) -> Any:
    return engine.platform_call(rt, builder, c.account.organization_id, c.connection.id, fn)


def execute(rt: Runtime, job: ClaimedJob) -> None:
    """Send one approved change of a draft (job ``draft_action_execute``)."""
    org_id, action_id = _load_job(job)
    with rt.db.transaction(org_id=org_id) as session:
        if not switches_on(rt, session, org_id):
            return
    found = _context(rt, org_id, action_id, "queued")
    if found is None:
        return
    action, c, builder = found
    try:
        with account_lock(
            rt.redis,
            f"action-draft:{c.draft.id}",
            wait_seconds=0,
            ttl_seconds=int(rt.settings.ACTIONS_LOCK_TTL.total_seconds()),
        ):
            _execute_locked(rt, job, action, c, builder)
    except AccountBusy:
        raise  # another change of this draft is being sent: the job tries again later


def _fail_before_sending(rt: Runtime, org_id: uuid.UUID, action_id: uuid.UUID, code: str) -> None:
    with rt.db.transaction(org_id=org_id) as session:
        row = session.get(Action, action_id, with_for_update=True)
        if row is not None and row.status == "queued":
            row.error_code = code
            engine.transition(session, rt, row, "failed", detail={"reason": code, "sent": False})


def _execute_locked(
    rt: Runtime, job: ClaimedJob, queued: Action, c: DraftContext, builder: CampaignBuilder
) -> None:
    org_id, action_id, kind = c.account.organization_id, queued.id, queued.action_type
    image = b""
    try:
        secrets = usable_secrets(rt, org_id, c.connection.id)
        existing: dict[str, str] = {}
        if kind == CREATE:
            # Never twice: a campaign carrying this draft's reference already exists?
            existing = _call(
                rt, builder, c, lambda: builder.find_campaign(secrets, c.ref, c.draft.reference)
            )
            if c.draft.platform == "meta_ads" and not existing and c.asset_key:
                image = storage_for(rt).get(c.asset_key)
    except ProviderError as exc:
        if exc.retryable and job.attempts < job.max_attempts:
            raise
        _fail_before_sending(rt, org_id, action_id, exc.code)
        return
    except StorageError:
        _fail_before_sending(rt, org_id, action_id, "image_unavailable")
        return
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        if action is None or action.status != "queued" or not switches_on(rt, session, org_id):
            return
        draft = session.get(CampaignDraft, c.draft.id, with_for_update=True)
        assert draft is not None
        reason = preconditions(c, kind)
        if reason is not None:
            action.error_code = reason
            engine.transition(session, rt, action, "stale", detail={"reason": reason})
            return
        action.submitted_at = rt.clock.now()
        action.platform_request = {"change": kind, "reference": draft.reference}
        if kind == CREATE:
            draft.status = "launching"
            draft.updated_at = rt.clock.now()
        engine.transition(session, rt, action, "submitting")
        maximize = has_conversions(rt, session, c.account)
    if kind == CREATE and existing:
        _finish_create(
            rt, org_id, action_id, c, builder, secrets, BuildResult(ids=existing), found=True
        )
        return
    try:
        if kind == CREATE:
            build = build_of(c, image=image, maximize_conversions=maximize)
            result = _call(
                rt,
                builder,
                c,
                lambda: builder.create_campaign(
                    secrets, c.ref, build, c.account.currency, validate_only=False
                ),
            )
            _finish_create(rt, org_id, action_id, c, builder, secrets, result)
            return
        ids = dict(c.draft.created_ids)
        call = builder.go_live if kind == GO_LIVE else builder.remove_objects
        receipt = _call(rt, builder, c, lambda: call(secrets, c.ref, ids))
        _finish_other(rt, org_id, action_id, c, kind, receipt.request)
    except BuildIncomplete as stopped:
        unknown = isinstance(stopped.cause, UnknownOutcomeError)
        code = getattr(stopped.cause, "code", "build_incomplete")
        _record(
            rt,
            org_id,
            action_id,
            c,
            ids=stopped.ids,
            outcome="unknown" if unknown else "failed",
            code=code,
        )
    except UnknownOutcomeError:
        _record(rt, org_id, action_id, c, outcome="unknown", code="outcome_unknown")
    except ProviderError as exc:
        _record(rt, org_id, action_id, c, outcome="failed", code=exc.code)
    except Exception:  # we cannot know whether it was made
        logger.exception("draft_action_error", extra={"action_id": str(action_id)})
        _record(rt, org_id, action_id, c, outcome="unknown", code="outcome_unknown")


def _record(
    rt: Runtime,
    org_id: uuid.UUID,
    action_id: uuid.UUID,
    c: DraftContext,
    *,
    outcome: str,
    code: str,
    ids: dict[str, str] | None = None,
) -> None:
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        draft = session.get(CampaignDraft, c.draft.id, with_for_update=True)
        if action is None or draft is None:  # pragma: no cover - deleted with the organization
            return
        if ids is not None:
            draft.created_ids = {**draft.created_ids, **ids}
        action.error_code = code
        action.platform_answer = {"refused": code} if outcome == "failed" else {"lost": True}
        if outcome == "unknown":
            engine.transition(session, rt, action, "unknown", detail={"reason": code})
            engine.schedule(
                session,
                rt,
                action,
                engine.JOB_DRAFT_RECONCILE,
                delay_seconds=int(rt.settings.ACTIONS_RECONCILE_DELAY.total_seconds()),
            )
            return
        if action.action_type == CREATE:
            # Nothing runs: what exists is paused. With nothing created, the draft can be
            # fixed and launched again; otherwise it waits for cleanup.
            draft.status = "failed" if draft.created_ids else "draft"
            draft.error_code = code
            draft.updated_at = rt.clock.now()
        engine.transition(session, rt, action, "failed", detail={"reason": code, "sent": True})


def _finish_create(
    rt: Runtime,
    org_id: uuid.UUID,
    action_id: uuid.UUID,
    c: DraftContext,
    builder: CampaignBuilder,
    secrets: Any,
    result: BuildResult,
    *,
    found: bool = False,
) -> None:
    """Record what was created, check it is **paused**, and schedule the account's sync."""
    status = None
    try:
        snapshot = _call(
            rt,
            builder,
            c,
            lambda: builder.read_campaign(
                secrets, c.ref, result.ids["campaign"], c.account.currency
            ),
        )
        status = snapshot.status
    except ProviderError:
        status = None
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        draft = session.get(CampaignDraft, c.draft.id, with_for_update=True)
        if action is None or draft is None:  # pragma: no cover
            return
        draft.created_ids = {**draft.created_ids, **result.ids}
        draft.status, draft.error_code, draft.updated_at = "created", None, rt.clock.now()
        if result.request:
            action.platform_request = result.request
        action.platform_answer = {"created": sorted(result.ids)}
        action.observed = {"status": status.value if status else None}
        action.verification = (
            "not_checked"
            if status is None
            else "verified"
            if status is AdEntityStatus.PAUSED
            else "mismatch"
        )
        detail = {"found_by": "look_up"} if found else {}
        engine.transition(session, rt, action, "succeeded", detail=detail)
        account = session.get(AdAccount, c.account.id)
        if account is not None:
            try:
                start_sync(session, rt, account, SyncMode.QUICK)
            except Exception:  # pragma: no cover - the scheduled runs read it later anyway
                logger.warning("draft_sync_not_started", extra={"draft_id": str(draft.id)})


def _finish_other(
    rt: Runtime,
    org_id: uuid.UUID,
    action_id: uuid.UUID,
    c: DraftContext,
    kind: str,
    request: dict[str, Any],
) -> None:
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        draft = session.get(CampaignDraft, c.draft.id, with_for_update=True)
        if action is None or draft is None:  # pragma: no cover
            return
        action.platform_request = request
        if kind == GO_LIVE:
            draft.status = "live"
        else:
            draft.status, draft.created_ids, draft.error_code = "draft", {}, None
        draft.updated_at = rt.clock.now()
        engine.transition(session, rt, action, "succeeded")


def reconcile(rt: Runtime, job: ClaimedJob) -> None:
    """Find out what happened to a draft's change whose outcome is unknown (reads only)."""
    org_id, action_id = _load_job(job)
    found = _context(rt, org_id, action_id, "unknown")
    if found is None:
        return
    action, c, builder = found
    kind = action.action_type
    try:
        secrets = usable_secrets(rt, org_id, c.connection.id)
        if kind == GO_LIVE:
            campaign = c.draft.created_ids.get("campaign", "")
            snapshot = _call(
                rt,
                builder,
                c,
                lambda: builder.read_campaign(secrets, c.ref, campaign, c.account.currency),
            )
            seen: dict[str, str] = {}
            live = snapshot.status is AdEntityStatus.ACTIVE
        else:
            seen = _call(
                rt, builder, c, lambda: builder.find_campaign(secrets, c.ref, c.draft.reference)
            )
            live = False
    except ProviderError as exc:
        _look_again(rt, org_id, action_id, exc.code)
        return
    if kind == CREATE:
        merged = {**c.draft.created_ids, **seen}
        if all(k in merged for k in COMPLETE[c.draft.platform]):
            _finish_create(
                rt, org_id, action_id, c, builder, secrets, BuildResult(ids=seen), found=True
            )
            return
        _settle(rt, org_id, action_id, c, ids=seen, code="incomplete" if merged else "not_applied")
    elif kind == GO_LIVE:
        if live:
            _finish_other(rt, org_id, action_id, c, kind, {"found_by": "look_up"})
        else:
            _settle(rt, org_id, action_id, c, code="not_applied")
    elif not seen:
        _finish_other(rt, org_id, action_id, c, kind, {"found_by": "look_up"})
    else:
        _settle(rt, org_id, action_id, c, code="not_applied")


def _settle(
    rt: Runtime,
    org_id: uuid.UUID,
    action_id: uuid.UUID,
    c: DraftContext,
    *,
    code: str,
    ids: dict[str, str] | None = None,
) -> None:
    with rt.db.transaction(org_id=org_id) as session:
        action = session.get(Action, action_id, with_for_update=True)
        draft = session.get(CampaignDraft, c.draft.id, with_for_update=True)
        if action is None or draft is None or action.status != "unknown":
            return
        action.reconcile_attempts += 1
        action.error_code = code
        if ids:
            draft.created_ids = {**draft.created_ids, **ids}
        if action.action_type == CREATE:
            draft.status = "failed" if draft.created_ids else "draft"
            draft.error_code, draft.updated_at = code, rt.clock.now()
        engine.transition(session, rt, action, "failed", detail={"reason": code})


def _look_again(rt: Runtime, org_id: uuid.UUID, action_id: uuid.UUID, code: str) -> None:
    with rt.db.transaction(org_id=org_id) as session:
        row = session.get(Action, action_id, with_for_update=True)
        if row is None or row.status != "unknown":
            return
        row.reconcile_attempts += 1
        row.updated_at = rt.clock.now()
        if row.reconcile_attempts >= rt.settings.ACTIONS_RECONCILE_ATTEMPTS:
            row.error_code = "needs_checking"
            return
        row.error_code = code
        engine.schedule(
            session,
            rt,
            row,
            engine.JOB_DRAFT_RECONCILE,
            delay_seconds=int(rt.settings.ACTIONS_RECONCILE_DELAY.total_seconds())
            * row.reconcile_attempts,
        )


def open_action(session: Session, org_id: uuid.UUID, draft_id: uuid.UUID) -> uuid.UUID | None:
    from app.domains.actions.models import OPEN_STATUSES

    return session.execute(
        select(Action.id).where(
            Action.organization_id == org_id,
            Action.draft_id == draft_id,
            Action.status.in_(OPEN_STATUSES),
        )
    ).scalar_one_or_none()
