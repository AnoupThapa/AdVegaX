"""The Action Engine API: request, check, approve, cancel, undo, settings, write access
(Phase 10A, task 10A-05, PHASE_10A_PLAN §7; D16, A2, A28).

* **Request** (owner, admin, manager): the change is checked in full — AdVegaX's checks
  (``validation.py``) against the campaign as the platform reports it **now**, then the
  platform's own dry run. Only a change that passes is kept, as ``pending``; the campaign's
  state at that moment is kept with it (``previous``). ``validate`` runs the same checks and
  dry run and keeps nothing.
* **Approve / reject** (owner, admin): approval re-runs the checks on today's limits and
  queues the change for the worker (``engine.py``); with "require a second person", never by
  the person who asked. A request older than ``ACTIONS_PENDING_TTL`` is stale.
* **Cancel**: the requester or an approver, until the change is being sent.
* **Undo**: the opposite change (previous status or budget) as a new request, approved like
  any other. It restores a value the campaign had, so the step and frequency limits do not
  apply to it; every other check does.
* Both switches are checked at request, at approval and right before the call.

Every step is audited (``engine.transition``) without secrets.
"""

from __future__ import annotations

import re
import uuid
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    ActionDuplicate,
    ActionInvalid,
    ActionNotAllowed,
    ActionStale,
    Conflict,
    NotFound,
    SecondPersonRequired,
    ServiceUnavailable,
)
from app.domains.actions import catalogue, engine, validation
from app.domains.actions.catalogue import CATALOGUE, ActionSpec, ParamsInvalid
from app.domains.actions.facts import (
    Target,
    limits_for,
    load_target,
    org_settings,
    require_switches,
    resource_reason,
    switches_on,
    write_access_problem,
    writer_for,
)
from app.domains.actions.models import OPEN_STATUSES, Action, ActionEvent, ActionSettings
from app.domains.actions.schemas import (
    ActionCheckOut,
    ActionEventOut,
    ActionIn,
    ActionOut,
    ActionPreviewOut,
    ActionSettingsIn,
    ActionSettingsOut,
    BudgetLimitsOut,
    CampaignRefOut,
    CampaignStateOut,
    DryRunOut,
    WriteAccessIn,
    WriteAccessOut,
)
from app.domains.actions.validation import Check, Facts, Limits
from app.domains.advertising.models import AdAccount, AdCampaign
from app.domains.audit.service import Actor, record_audit
from app.domains.finance.definitions import minor_units
from app.domains.integrations.models import ExternalConnection
from app.domains.integrations.tokens import usable_secrets
from app.domains.organizations.models import Organization
from app.domains.organizations.permissions import Permission, authorize, has_permission
from app.domains.organizations.tenancy import TenantContext
from app.providers.base.changes import CampaignSnapshot, CampaignWriter, ChangeKind
from app.providers.base.errors import (
    AuthExpiredError,
    PermissionDeniedError,
    ProviderError,
    ResourceNotFoundError,
    ResourceUnavailableError,
)
from app.runtime import Runtime

# A web address's host name (no scheme, path or port), e.g. ``evezone.com.au``.
HOST = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
# Live undo children: an undo that is open or done blocks another undo of the same change.
_UNDO_BLOCKING = (*OPEN_STATUSES, "succeeded")


class _Assessment:
    """The full check of one requested change (nothing stored yet)."""

    def __init__(
        self,
        *,
        spec: ActionSpec,
        target: Target,
        params: dict[str, str] | None,
        checks: list[Check],
        dry_run: dict[str, Any],
        snapshot: CampaignSnapshot | None,
        limits: Limits,
    ) -> None:
        self.spec = spec
        self.target = target
        self.params = params
        self.checks = checks
        self.dry_run = dry_run
        self.snapshot = snapshot
        self.limits = limits

    @property
    def passed(self) -> bool:
        return validation.passed(self.checks) and self.dry_run.get("result") == "passed"

    def failures(self) -> list[dict[str, Any]]:
        found = validation.failures(self.checks)
        if self.dry_run.get("result") == "failed":
            found.append({"check": "dry_run", "reason": self.dry_run.get("reason")})
        return found


def _state(data: dict[str, Any] | None, currency: str) -> CampaignStateOut | None:
    if data is None:
        return None
    amount = data.get("daily_budget")
    return CampaignStateOut(
        status=data.get("status"),
        budget_level=data.get("budget_level"),
        budget_period=data.get("budget_period"),
        daily_budget=_money(Decimal(amount), currency) if amount is not None else None,
        budget_shared=bool(data.get("budget_shared")),
    )


def _money(value: Decimal | None, currency: str) -> str | None:
    if value is None:
        return None
    return str(value.quantize(catalogue.quantum(currency)))


def _budget_limits(
    spec: ActionSpec, snapshot: CampaignSnapshot | None, limits: Limits, currency: str
) -> BudgetLimitsOut | None:
    """The range one change may set (AdVegaX computes it; the page only shows it)."""
    if spec.kind is not ChangeKind.SET_DAILY_BUDGET:
        return None
    current = snapshot.daily_budget if snapshot else None
    low: list[Decimal] = [x for x in (limits.minimum,) if x is not None]
    high: list[Decimal] = [x for x in (limits.maximum,) if x is not None]
    if current is not None and not limits.undo:
        low.append(current * (100 - limits.decrease_percent) / 100)
        high.append(current * (100 + limits.increase_percent) / 100)
    step = catalogue.quantum(currency)
    lowest = max(low).quantize(step, rounding=ROUND_CEILING) if low else None
    highest = min(high).quantize(step, rounding=ROUND_FLOOR) if high else None
    return BudgetLimitsOut(
        lowest=str(lowest) if lowest is not None else None,
        highest=str(highest) if highest is not None else None,
        platform_minimum=_money(limits.minimum, currency),
        organization_maximum=_money(limits.maximum, currency),
        increase_percent=limits.increase_percent,
        decrease_percent=limits.decrease_percent,
    )


class ActionService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ checking
    def _read(
        self, target: Target, writer: CampaignWriter
    ) -> tuple[CampaignSnapshot | None, str | None]:
        org_id = target.account.organization_id
        try:
            secrets = usable_secrets(self.rt, org_id, target.connection.id)
            snapshot = engine.platform_call(
                self.rt,
                writer,
                org_id,
                target.connection.id,
                lambda: writer.read_campaign(
                    secrets,
                    target.ref,
                    target.campaign.external_campaign_id,
                    target.account.currency,
                ),
            )
        except (ResourceNotFoundError, ResourceUnavailableError):
            return None, "campaign_unavailable"
        except (AuthExpiredError, PermissionDeniedError):
            return None, "connection_needs_attention"
        except ProviderError:
            raise ServiceUnavailable() from None
        return snapshot, None

    def _dry_run(
        self,
        target: Target,
        writer: CampaignWriter,
        spec: ActionSpec,
        params: dict[str, str],
        snapshot: CampaignSnapshot,
    ) -> dict[str, Any]:
        org_id = target.account.organization_id
        change = catalogue.change_of(spec, params)
        try:
            secrets = usable_secrets(self.rt, org_id, target.connection.id)
            engine.platform_call(
                self.rt,
                writer,
                org_id,
                target.connection.id,
                lambda: writer.change_campaign(
                    secrets,
                    target.ref,
                    snapshot,
                    change,
                    target.account.currency,
                    validate_only=True,
                ),
            )
        except ProviderError as exc:
            return {"result": "failed", "reason": exc.code}
        return {"result": "passed"}

    def _assess(
        self,
        ctx: TenantContext,
        body: ActionIn,
        *,
        undo: bool = False,
        for_request: bool = True,
    ) -> _Assessment:
        spec = CATALOGUE[body.action_type]
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            require_switches(self.rt, session, ctx.organization_id)
            target = load_target(session, ctx.organization_id, body.campaign_id)
            writer = writer_for(self.rt, target.account.provider)
            reason = resource_reason(target, writer)
            if reason is None:
                problem = write_access_problem(target.connection, writer)
                if problem is not None:
                    raise ActionNotAllowed(details=[{"reason": problem}])
            try:
                params: dict[str, str] | None = catalogue.parse(
                    spec, dict(body.params), target.account.currency
                )
                params_reason = None
            except ParamsInvalid as exc:
                params, params_reason = None, exc.reason
            if reason is None and params is not None:
                reason = self._open_change(session, ctx, target, spec, params, for_request)
            limits = limits_for(self.rt, session, target, spec, undo=undo)
        snapshot: CampaignSnapshot | None = None
        if reason is None and params is not None and writer is not None:
            snapshot, reason = self._read(target, writer)
        checks = validation.run(
            Facts(
                spec=spec,
                params=params,
                params_reason=params_reason,
                resource_reason=reason,
                snapshot=snapshot,
                limits=limits,
            )
        )
        dry_run: dict[str, Any] = {"result": "skipped"}
        if validation.passed(checks) and writer and snapshot and params is not None:
            dry_run = self._dry_run(target, writer, spec, params, snapshot)
        return _Assessment(
            spec=spec,
            target=target,
            params=params,
            checks=checks,
            dry_run=dry_run,
            snapshot=snapshot,
            limits=limits,
        )

    def _open_change(
        self,
        session: Session,
        ctx: TenantContext,
        target: Target,
        spec: ActionSpec,
        params: dict[str, str],
        for_request: bool,
    ) -> str | None:
        open_key = session.execute(
            select(Action.idempotency_key).where(
                Action.organization_id == ctx.organization_id,
                Action.campaign_id == target.campaign.id,
                Action.status.in_(OPEN_STATUSES),
            )
        ).scalar_one_or_none()
        if open_key is None:
            return None
        if for_request and open_key == catalogue.key(target.campaign.id, spec, params):
            raise ActionDuplicate()
        return "campaign_has_open_change"

    def _preview(self, a: _Assessment) -> ActionPreviewOut:
        currency = a.target.account.currency
        return ActionPreviewOut(
            action_type=a.spec.type,
            campaign_id=a.target.campaign.id,
            currency=currency,
            currency_minor_units=minor_units(currency),
            passed=a.passed,
            checks=[ActionCheckOut(**c.as_json()) for c in a.checks],
            dry_run=DryRunOut(**a.dry_run),
            current=_state(a.snapshot.as_json(), currency) if a.snapshot else None,
            budget_limits=_budget_limits(a.spec, a.snapshot, a.limits, currency),
        )

    def validate(self, ctx: TenantContext, body: ActionIn) -> ActionPreviewOut:
        """Every check and the platform's dry run; nothing is kept."""
        authorize(ctx, Permission.ACTIONS_REQUEST)
        return self._preview(self._assess(ctx, body, for_request=False))

    # ------------------------------------------------------------------ requests
    def request(
        self,
        ctx: TenantContext,
        body: ActionIn,
        *,
        undo_of: uuid.UUID | None = None,
        recommendation_id: uuid.UUID | None = None,
    ) -> ActionOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        assessment = self._assess(ctx, body, undo=undo_of is not None)
        if not assessment.passed or assessment.params is None or assessment.snapshot is None:
            raise ActionInvalid(details=assessment.failures())
        target, params = assessment.target, assessment.params
        try:
            with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
                require_switches(self.rt, session, ctx.organization_id)
                action = Action(
                    id=uuid.uuid4(),
                    organization_id=ctx.organization_id,
                    action_type=assessment.spec.type,
                    provider=target.account.provider,
                    ad_account_id=target.account.id,
                    campaign_id=target.campaign.id,
                    params=params,
                    currency=target.account.currency,
                    previous=engine.stored(assessment.snapshot),
                    status="pending",
                    idempotency_key=catalogue.key(target.campaign.id, assessment.spec, params),
                    checks=[c.as_json() for c in assessment.checks],
                    dry_run=assessment.dry_run,
                    source="recommendation" if recommendation_id else "user",
                    recommendation_id=recommendation_id,
                    undo_of=undo_of,
                    requested_by=ctx.user_id,
                    created_at=self.rt.clock.now(),
                    updated_at=self.rt.clock.now(),
                )
                session.add(action)
                session.flush()
                session.add(
                    ActionEvent(
                        organization_id=ctx.organization_id,
                        action_id=action.id,
                        seq=1,
                        from_status=None,
                        status="pending",
                        actor_type="user",
                        actor_user_id=ctx.user_id,
                        detail={"undo_of": str(undo_of)} if undo_of else {},
                        created_at=self.rt.clock.now(),
                    )
                )
                record_audit(
                    session,
                    organization_id=ctx.organization_id,
                    actor=Actor.user(ctx.user_id),
                    action="action.requested",
                    resource_type="action",
                    resource_id=action.id,
                    after={"status": "pending", "params": params},
                    metadata={
                        "action_type": action.action_type,
                        "campaign_id": str(action.campaign_id),
                        "provider": action.provider,
                        "undo_of": str(undo_of) if undo_of else None,
                        "recommendation_id": str(recommendation_id) if recommendation_id else None,
                    },
                )
                session.flush()
                return self._out(session, ctx, action, events=True)
        except IntegrityError:
            raise ActionDuplicate() from None  # a second request for the campaign at once

    def undo(self, ctx: TenantContext, action_id: uuid.UUID) -> ActionOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            original = self._action(session, ctx, action_id)
            if not self._undoable(session, original):
                raise Conflict("This change cannot be undone.")
            opposite = catalogue.undo(CATALOGUE[original.action_type], original.previous)
            assert opposite is not None  # checked by _undoable
            spec, params = opposite
            body = ActionIn(
                action_type=spec.type,
                campaign_id=original.campaign_id,
                params=params,
            )
        return self.request(ctx, body, undo_of=action_id)

    def _undoable(self, session: Session, action: Action) -> bool:
        if action.draft_id is not None or action.action_type not in CATALOGUE:
            return False  # a draft's launch is undone by pausing or cleaning up (10B)
        if action.status != "succeeded" or action.verification == "mismatch":
            return False
        if catalogue.undo(CATALOGUE[action.action_type], action.previous) is None:
            return False
        child = session.execute(
            select(Action.id).where(
                Action.organization_id == action.organization_id,
                Action.undo_of == action.id,
                Action.status.in_(_UNDO_BLOCKING),
            )
        ).first()
        return child is None

    # ------------------------------------------------------------------ decisions
    def approve(self, ctx: TenantContext, action_id: uuid.UUID) -> ActionOut:
        authorize(ctx, Permission.ACTIONS_APPROVE)
        expired = False
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            require_switches(self.rt, session, ctx.organization_id)
            action = self._action(session, ctx, action_id, lock=True)
            if action.status != "pending":
                raise Conflict("This change is no longer waiting for a decision.")
            settings = org_settings(session, ctx.organization_id)
            if settings.require_second_person and action.requested_by == ctx.user_id:
                raise SecondPersonRequired()
            if action.created_at + self.rt.settings.ACTIONS_PENDING_TTL < self.rt.clock.now():
                action.error_code = "request_expired"
                engine.transition(
                    session,
                    self.rt,
                    action,
                    "stale",
                    user_id=ctx.user_id,
                    detail={"reason": "request_expired"},
                )
                expired = True
            else:
                if action.draft_id is not None:
                    from app.domains.builder.launch import recheck  # a draft's change (10B)

                    recheck(self.rt, session, action)
                else:
                    self._recheck(session, action)
                action.decided_by = ctx.user_id
                action.decided_at = self.rt.clock.now()
                engine.transition(session, self.rt, action, "approved", user_id=ctx.user_id)
                engine.transition(session, self.rt, action, "queued", user_id=ctx.user_id)
                engine.schedule(session, self.rt, action, engine.job_for(action, "execute"))
        if expired:
            raise ActionStale()
        return self.get(ctx, action_id)

    def _recheck(self, session: Session, action: Action) -> None:
        """Today's limits and access, on the campaign as it was when requested (the worker
        reads it again right before sending)."""
        spec = CATALOGUE[action.action_type]
        assert action.campaign_id is not None  # drafts are re-checked by the builder
        target = load_target(session, action.organization_id, action.campaign_id)
        writer = writer_for(self.rt, action.provider)
        reason = resource_reason(target, writer)
        if reason is None:
            problem = write_access_problem(target.connection, writer)
            if problem is not None:
                raise ActionNotAllowed(details=[{"reason": problem}])
        limits = limits_for(
            self.rt, session, target, spec, undo=action.undo_of is not None, exclude=action.id
        )
        checks = validation.run(
            Facts(
                spec=spec,
                params=dict(action.params),
                params_reason=None,
                resource_reason=reason,
                snapshot=engine.snapshot_of(action.previous, target.campaign.external_campaign_id),
                limits=limits,
            )
        )
        if not validation.passed(checks):
            raise ActionInvalid(details=validation.failures(checks))

    def reject(self, ctx: TenantContext, action_id: uuid.UUID, reason: str) -> ActionOut:
        authorize(ctx, Permission.ACTIONS_APPROVE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            action = self._action(session, ctx, action_id, lock=True)
            if action.status != "pending":
                raise Conflict("This change is no longer waiting for a decision.")
            action.decided_by = ctx.user_id
            action.decided_at = self.rt.clock.now()
            action.decision_reason = reason.strip()[:500]
            engine.transition(
                session, self.rt, action, "rejected", user_id=ctx.user_id, detail={"reason": True}
            )
        return self.get(ctx, action_id)

    def cancel(self, ctx: TenantContext, action_id: uuid.UUID) -> ActionOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            action = self._action(session, ctx, action_id, lock=True)
            mine = action.requested_by == ctx.user_id
            if not mine and not has_permission(ctx.role, Permission.ACTIONS_APPROVE):
                authorize(ctx, Permission.ACTIONS_APPROVE)  # refused and audited
            if action.status not in ("pending", "approved", "queued"):
                raise Conflict("This change can no longer be cancelled.")
            engine.transition(session, self.rt, action, "cancelled", user_id=ctx.user_id)
        return self.get(ctx, action_id)

    # ------------------------------------------------------------------ reading
    def _action(
        self, session: Session, ctx: TenantContext, action_id: uuid.UUID, *, lock: bool = False
    ) -> Action:
        query = select(Action).where(
            Action.organization_id == ctx.organization_id, Action.id == action_id
        )
        if lock:
            query = query.with_for_update()
        found = session.execute(query).scalar_one_or_none()
        if found is None:
            raise NotFound()
        return found

    def _out(
        self, session: Session, ctx: TenantContext, a: Action, *, events: bool = False
    ) -> ActionOut:
        campaign_ref: CampaignRefOut | None = None
        if a.campaign_id is not None:
            campaign, account = session.execute(
                select(AdCampaign, AdAccount)
                .join(
                    AdAccount,
                    (AdAccount.id == AdCampaign.ad_account_id)
                    & (AdAccount.organization_id == AdCampaign.organization_id),
                )
                .where(
                    AdCampaign.organization_id == ctx.organization_id,
                    AdCampaign.id == a.campaign_id,
                )
            ).one()
            campaign_ref = CampaignRefOut(
                id=campaign.id,
                name=campaign.name,
                external_id=campaign.external_campaign_id,
                ad_account_id=account.id,
                ad_account_name=account.name,
            )
        draft_ref = None
        if a.draft_id is not None:
            from app.domains.builder.launch import draft_ref_of  # a draft's change (10B)

            draft_ref = draft_ref_of(session, ctx.organization_id, a.draft_id)
        history: list[ActionEventOut] = []
        if events:
            history = [
                ActionEventOut(
                    from_status=e.from_status,
                    status=e.status,
                    actor_type=e.actor_type,
                    actor_user_id=e.actor_user_id,
                    detail=e.detail,
                    created_at=e.created_at,
                )
                for e in session.execute(
                    select(ActionEvent)
                    .where(
                        ActionEvent.organization_id == ctx.organization_id,
                        ActionEvent.action_id == a.id,
                    )
                    .order_by(ActionEvent.seq)
                ).scalars()
            ]
        return ActionOut(
            id=a.id,
            action_type=a.action_type,
            provider=a.provider,
            campaign=campaign_ref,
            draft=draft_ref,
            currency=a.currency,
            currency_minor_units=minor_units(a.currency),
            params=dict(a.params),
            previous=_state(a.previous, a.currency),
            observed=_state(a.observed, a.currency),
            status=a.status,
            checks=[ActionCheckOut(**c) for c in a.checks],
            dry_run=DryRunOut(**a.dry_run) if a.dry_run else None,
            verification=a.verification,
            error_code=a.error_code,
            platform_request=a.platform_request,
            platform_answer=a.platform_answer,
            source=a.source,
            recommendation_id=a.recommendation_id,
            undo_of=a.undo_of,
            requested_by=a.requested_by,
            decided_by=a.decided_by,
            decided_at=a.decided_at,
            decision_reason=a.decision_reason,
            submitted_at=a.submitted_at,
            finished_at=a.finished_at,
            created_at=a.created_at,
            updated_at=a.updated_at,
            can_undo=self._undoable(session, a),
            events=history,
        )

    def get(self, ctx: TenantContext, action_id: uuid.UUID) -> ActionOut:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._out(session, ctx, self._action(session, ctx, action_id), events=True)

    def list_actions(
        self,
        ctx: TenantContext,
        *,
        page: int,
        page_size: int,
        status: str | None,
        campaign_id: uuid.UUID | None,
    ) -> tuple[list[ActionOut], int]:
        authorize(ctx, Permission.ACTIONS_VIEW)
        filters: list[Any] = [Action.organization_id == ctx.organization_id]
        if status == "open":
            filters.append(Action.status.in_(OPEN_STATUSES))
        elif status is not None:
            filters.append(Action.status == status)
        if campaign_id is not None:
            filters.append(Action.campaign_id == campaign_id)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            total = session.execute(
                select(func.count()).select_from(Action).where(*filters)
            ).scalar_one()
            rows = session.execute(
                select(Action)
                .where(*filters)
                .order_by(Action.created_at.desc(), Action.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars()
            return [self._out(session, ctx, a) for a in rows], int(total)

    # ------------------------------------------------------------------ settings
    def _settings_out(self, session: Session, ctx: TenantContext) -> ActionSettingsOut:
        row = org_settings(session, ctx.organization_id)
        saved = session.get(ActionSettings, ctx.organization_id)
        org = session.get(Organization, ctx.organization_id)
        currency = org.default_currency if org else "USD"
        s = self.rt.settings
        return ActionSettingsOut(
            engine_enabled=s.ACTIONS_ENABLED,
            paused=row.paused,
            require_second_person=row.require_second_person,
            max_daily_budget=_money(row.max_daily_budget, currency),
            landing_domains=list(row.landing_domains or []),
            currency=currency,
            currency_minor_units=minor_units(currency),
            increase_percent=s.ACTIONS_MAX_INCREASE_PERCENT,
            decrease_percent=s.ACTIONS_MAX_DECREASE_PERCENT,
            budget_change_interval_minutes=int(
                s.ACTIONS_BUDGET_CHANGE_INTERVAL.total_seconds() // 60
            ),
            daily_limit_per_account=s.ACTIONS_DAILY_LIMIT_PER_ACCOUNT,
            updated_at=saved.updated_at if saved is not None else None,
        )

    def get_settings(self, ctx: TenantContext) -> ActionSettingsOut:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._settings_out(session, ctx)

    def put_settings(self, ctx: TenantContext, body: ActionSettingsIn) -> ActionSettingsOut:
        authorize(ctx, Permission.ACTIONS_SETTINGS)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = session.get(ActionSettings, ctx.organization_id, with_for_update=True)
            if row is None:
                row = ActionSettings(organization_id=ctx.organization_id)
                session.add(row)
            org = session.get(Organization, ctx.organization_id)
            currency = org.default_currency if org else "USD"
            maximum = body.max_daily_budget
            if maximum is not None:
                step = catalogue.quantum(currency)
                if maximum != maximum.quantize(step):
                    raise ActionInvalid(
                        details=[{"check": "shape", "reason": "max_daily_budget_precision"}]
                    )
            was_paused = bool(row.paused)
            before = {
                "paused": was_paused,
                "require_second_person": bool(row.require_second_person),
                "max_daily_budget": _money(row.max_daily_budget, currency),
            }
            row.paused = body.paused
            row.require_second_person = body.require_second_person
            row.max_daily_budget = maximum
            row.max_daily_budget_currency = currency if maximum is not None else None
            if body.landing_domains is not None:
                hosts = [h.strip().lower().rstrip(".") for h in body.landing_domains if h.strip()]
                if any(not HOST.fullmatch(h) for h in hosts):
                    raise ActionInvalid(
                        details=[{"check": "shape", "reason": "landing_domain_invalid"}]
                    )
                row.landing_domains = list(dict.fromkeys(hosts))
            elif row.landing_domains is None:
                row.landing_domains = []
            row.updated_by = ctx.user_id
            row.updated_at = self.rt.clock.now()
            session.flush()
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="action_settings.updated",
                resource_type="action_settings",
                resource_id=ctx.organization_id,
                before=before,
                after={
                    "paused": body.paused,
                    "require_second_person": body.require_second_person,
                    "max_daily_budget": _money(maximum, currency),
                },
            )
            if (
                was_paused
                and not body.paused
                and switches_on(self.rt, session, ctx.organization_id)
            ):
                engine.resume_queued(session, self.rt, ctx.organization_id)
            return self._settings_out(session, ctx)

    # ------------------------------------------------------------------ write access
    def _connection(
        self, session: Session, ctx: TenantContext, connection_id: uuid.UUID, *, lock: bool = False
    ) -> ExternalConnection:
        query = select(ExternalConnection).where(
            ExternalConnection.organization_id == ctx.organization_id,
            ExternalConnection.id == connection_id,
        )
        if lock:
            query = query.with_for_update()
        found = session.execute(query).scalar_one_or_none()
        if found is None:
            raise NotFound()
        return found

    def _access_out(self, connection: ExternalConnection) -> WriteAccessOut:
        writer = writer_for(self.rt, connection.provider)
        missing = (
            sorted(set(writer.write_scopes) - set(connection.granted_scopes)) if writer else []
        )
        return WriteAccessOut(
            connection_id=connection.id,
            provider=connection.provider,
            supported=writer is not None,
            allowed=write_access_problem(connection, writer) is None,
            allowed_at=connection.write_access_granted_at,
            allowed_by=connection.write_access_granted_by,
            missing_permissions=missing,
            can_request_permission=bool(missing)
            and bool(getattr(writer, "write_consent_available", False)),
        )

    def get_write_access(self, ctx: TenantContext, connection_id: uuid.UUID) -> WriteAccessOut:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._access_out(self._connection(session, ctx, connection_id))

    def put_write_access(
        self, ctx: TenantContext, connection_id: uuid.UUID, body: WriteAccessIn
    ) -> WriteAccessOut:
        """ "Allow changes" for one connection (owners, admins), or take it back."""
        authorize(ctx, Permission.ACTIONS_SETTINGS)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            connection = self._connection(session, ctx, connection_id, lock=True)
            writer = writer_for(self.rt, connection.provider)
            if body.allowed:
                if writer is None or connection.status != "active":
                    raise ActionNotAllowed(details=[{"reason": "platform_cannot_change"}])
                if set(writer.write_scopes) - set(connection.granted_scopes):
                    raise ActionNotAllowed(details=[{"reason": "permission_missing"}])
                connection.write_access_granted_at = self.rt.clock.now()
                connection.write_access_granted_by = ctx.user_id
            else:
                connection.write_access_granted_at = None
                connection.write_access_granted_by = None
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="connection.write_access_granted"
                if body.allowed
                else "connection.write_access_removed",
                resource_type="connection",
                resource_id=connection.id,
                metadata={"provider": connection.provider},
            )
            session.flush()
            return self._access_out(connection)
