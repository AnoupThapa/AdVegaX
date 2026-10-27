"""Recommendations: reading, deciding, looking again, settings (Phase 11, task 11-06,
PHASE_11_PLAN Q-11-6 … Q-11-10; A30).

* **Read** (every role): the open advice first, by rank; the last look's summary.
* **Approve** (owner, admin, manager — Q-11-7): checked again first — still open and valid, the
  campaign's status and budget unchanged since the advice, and the rule still true with
  today's figures; otherwise the advice is **out of date** and nothing is sent. Then it becomes
  an ordinary Action Engine change (``source = recommendation``) with every 10A check and the
  platform's test. An owner or admin approves that change in the same step, unless the
  organization requires a second person; a manager's change waits for approval in Changes.
* **Reject** with a reason (and an optional note); **"Looked into"** for advice without a change.
* **Look again now** (owner, admin, manager): at most ``OPTIMIZATION_REFRESHES_PER_DAY``.
* **Settings** (owners, admins): the thresholds.

Every decision is audited; the change itself is audited by the Action Engine.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import (
    AppError,
    Conflict,
    NotFound,
    OptimizationDisabled,
    RecommendationClosed,
    RecommendationOutOfDate,
    RefreshLimit,
    ValidationFailed,
)
from app.domains.actions.facts import org_settings
from app.domains.actions.models import Action
from app.domains.actions.schemas import ActionCheckOut, ActionIn
from app.domains.actions.service import ActionService
from app.domains.advertising.models import AdAccount, AdCampaign
from app.domains.audit.service import Actor, record_audit
from app.domains.finance.definitions import for_display
from app.domains.optimization.candidates import state_of
from app.domains.optimization.look import kinds_now, local_today, run_look, settings_for
from app.domains.optimization.models import (
    OptimizationSettings,
    Recommendation,
    RecommendationOutcome,
)
from app.domains.optimization.schemas import (
    ActionRefOut,
    CampaignRef,
    OptimizationSettingsIn,
    OptimizationSettingsOut,
    OutcomeOut,
    ProposalOut,
    RecommendationListOut,
    RecommendationOut,
    RecommendationRejectIn,
    SummaryOut,
)
from app.domains.organizations.models import Organization
from app.domains.organizations.permissions import Permission, authorize, has_permission
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

logger = logging.getLogger("advegax.optimization")
_ORDER = {"open": 0, "approved": 1, "done": 2, "rejected": 3}


def _proposal(rec: Recommendation) -> ProposalOut:
    from app.domains.optimization.explain import money

    p = rec.proposal or {}
    kind = p.get("action_type")
    text = "No change: look into it"
    previous = (p.get("previous") or {}).get("daily_budget")
    if kind == "campaign.pause":
        text = "Pause the campaign"
    elif kind == "campaign.set_daily_budget":
        cur = p["currency"]
        verb = "Raise" if rec.kind == "budget_limited" else "Lower"
        old = money(Decimal(previous), cur) if previous else None
        new = money(Decimal(p["params"]["daily_budget"]), cur)
        text = f"{verb} the daily budget from {old} to {new}"
    return ProposalOut(
        action_type=kind,
        params=dict(p.get("params") or {}),
        currency=p.get("currency"),
        previous_daily_budget=previous,
        text=text,
    )


class RecommendationService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ reading
    def _expire(self, session: Session, org_id: uuid.UUID) -> None:
        session.execute(
            update(Recommendation)
            .where(
                Recommendation.organization_id == org_id,
                Recommendation.status == "open",
                Recommendation.expires_at <= self.rt.clock.now(),
            )
            .values(status="expired", updated_at=self.rt.clock.now())
        )

    def _out(self, session: Session, rec: Recommendation) -> RecommendationOut:
        campaign = None
        if rec.campaign_id is not None:
            row = session.execute(
                select(AdCampaign, AdAccount)
                .join(AdAccount, AdAccount.id == AdCampaign.ad_account_id)
                .where(AdCampaign.id == rec.campaign_id)
            ).one_or_none()
            if row is not None:
                c, a = row
                campaign = CampaignRef(
                    id=c.id,
                    name=c.name,
                    provider=a.provider,
                    ad_account_id=a.id,
                    ad_account_name=a.name,
                )
        action = (
            session.execute(
                select(Action)
                .where(
                    Action.organization_id == rec.organization_id,
                    Action.recommendation_id == rec.id,
                )
                .order_by(Action.created_at.desc())
            )
            .scalars()
            .first()
        )
        outcomes = session.execute(
            select(RecommendationOutcome)
            .where(RecommendationOutcome.recommendation_id == rec.id)
            .order_by(RecommendationOutcome.after_days)
        ).scalars()
        signal = rec.signal or {}
        checks = [ActionCheckOut(**c) for c in rec.prechecks]
        return RecommendationOut(
            id=rec.id,
            kind=rec.kind,
            status=rec.status,
            campaign=campaign,
            funnel=signal.get("facts") if rec.kind == "funnel_drop" else None,
            figures=dict(signal.get("written") or {}),
            raw_figures=dict(signal.get("figures") or {}),
            periods=dict(signal.get("periods") or {}),
            currency=signal.get("currency") or "",
            proposal=_proposal(rec),
            note=signal.get("note"),
            prechecks=checks,
            ready=bool(rec.proposal.get("action_type"))
            and all(c.result == "passed" for c in checks),
            explanation=rec.explanation,
            confidence=rec.confidence,
            assumptions=list(rec.assumptions),
            risks=list(rec.risks),
            rank=rec.rank,
            explained_by=rec.explained_by,
            ai_run_id=rec.ai_run_id,
            expires_at=rec.expires_at,
            closed_reason=rec.closed_reason,
            decided_by=rec.decided_by,
            decided_at=rec.decided_at,
            decision_reason=rec.decision_reason,
            decision_note=rec.decision_note,
            action=ActionRefOut(
                id=action.id, status=action.status, verification=action.verification
            )
            if action
            else None,
            outcomes=[
                OutcomeOut(
                    after_days=o.after_days, before=o.before, after=o.after, created_at=o.created_at
                )
                for o in outcomes
            ],
            created_at=rec.created_at,
        )

    def _summary(self, session: Session, ctx: TenantContext) -> SummaryOut:
        row = session.get(OptimizationSettings, ctx.organization_id)
        org = session.get(Organization, ctx.organization_id)
        assert org is not None
        today = local_today(self.rt.clock.now(), org.default_timezone)
        limit = self.rt.settings.OPTIMIZATION_REFRESHES_PER_DAY
        used = row.refreshes_used if row is not None and row.refreshes_on == today else 0
        count = session.execute(
            select(func.count())
            .select_from(Recommendation)
            .where(
                Recommendation.organization_id == ctx.organization_id,
                Recommendation.status == "open",
            )
        ).scalar_one()
        return SummaryOut(
            enabled=self.rt.settings.OPTIMIZATION_ENABLED,
            open=int(count),
            last_run=row.last_run_summary if row is not None else None,
            refreshes_left=max(0, limit - used),
        )

    def list_recommendations(
        self,
        ctx: TenantContext,
        *,
        status: str | None = None,
        campaign_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> RecommendationListOut:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            self._expire(session, ctx.organization_id)
            query = select(Recommendation).where(
                Recommendation.organization_id == ctx.organization_id
            )
            if status == "decided":
                query = query.where(Recommendation.status.in_(("approved", "rejected", "done")))
            elif status == "closed":
                query = query.where(
                    Recommendation.status.in_(("expired", "out_of_date", "superseded"))
                )
            elif status:
                query = query.where(Recommendation.status == status)
            else:
                query = query.where(Recommendation.status != "superseded")
            if campaign_id is not None:
                query = query.where(Recommendation.campaign_id == campaign_id)
            rows = list(
                session.execute(
                    query.order_by(Recommendation.created_at.desc()).limit(limit)
                ).scalars()
            )
            rows.sort(key=lambda r: (_ORDER.get(r.status, 9), r.status != "open" or r.rank))
            return RecommendationListOut(
                summary=self._summary(session, ctx),
                items=[self._out(session, r) for r in rows],
            )

    def _one(
        self, session: Session, ctx: TenantContext, rec_id: uuid.UUID, *, lock: bool = False
    ) -> Recommendation:
        query = select(Recommendation).where(
            Recommendation.organization_id == ctx.organization_id, Recommendation.id == rec_id
        )
        rec = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
        if rec is None:
            raise NotFound()
        return rec

    def get(self, ctx: TenantContext, rec_id: uuid.UUID) -> RecommendationOut:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            self._expire(session, ctx.organization_id)
            return self._out(session, self._one(session, ctx, rec_id))

    # ------------------------------------------------------------------ decisions
    def _audit(
        self, session: Session, ctx: TenantContext, rec: Recommendation, verb: str, **meta: Any
    ) -> None:
        record_audit(
            session,
            organization_id=ctx.organization_id,
            actor=Actor.user(ctx.user_id),
            action=f"recommendation.{verb}",
            resource_type="recommendation",
            resource_id=rec.id,
            after={"status": rec.status},
            metadata={"kind": rec.kind, **meta},
        )

    def _open(self, rec: Recommendation) -> bool:
        """Whether the advice can still be decided (an expired one is marked so)."""
        if rec.status != "open":
            return False
        if rec.expires_at <= self.rt.clock.now():
            rec.status = "expired"
            rec.updated_at = self.rt.clock.now()
            return False
        return True

    def approve(self, ctx: TenantContext, rec_id: uuid.UUID) -> RecommendationOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        out_of_date: str | None = None
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rec = self._one(session, ctx, rec_id, lock=True)
            if not self._open(rec):
                closed = True
            else:
                closed = False
                if not rec.proposal.get("action_type"):
                    raise Conflict("This advice proposes no change. Mark it as looked into.")
                assert rec.campaign_id is not None
                campaign = session.get(AdCampaign, rec.campaign_id)
                if campaign is None:
                    raise NotFound()
                now_state = state_of(session, campaign.budget_id, campaign.status)
                if any(
                    now_state.get(k) != rec.campaign_state.get(k)
                    for k in ("status", "budget_id", "daily_budget")
                ):
                    out_of_date = "campaign_changed"
                elif rec.kind not in kinds_now(self.rt, session, ctx.organization_id, campaign.id):
                    out_of_date = "no_longer_true"
                if out_of_date:
                    rec.status, rec.closed_reason = "out_of_date", out_of_date
                    rec.updated_at = self.rt.clock.now()
                    self._audit(session, ctx, rec, "out_of_date", reason=out_of_date)
                else:
                    body = ActionIn(
                        action_type=rec.proposal["action_type"],
                        campaign_id=rec.campaign_id,
                        params=dict(rec.proposal.get("params") or {}),
                    )
        if closed:
            raise RecommendationClosed()
        if out_of_date:
            raise RecommendationOutOfDate(details=[{"reason": out_of_date}])
        actions = ActionService(self.rt)
        action = actions.request(ctx, body, recommendation_id=rec_id)
        sent = False
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            second = org_settings(session, ctx.organization_id).require_second_person
        if has_permission(ctx.role, Permission.ACTIONS_APPROVE) and not second:
            try:
                actions.approve(ctx, action.id)
                sent = True
            except AppError as exc:  # the change stays waiting in Changes, with its reason
                logger.info("recommendation_change_waits", extra={"code": exc.code})
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rec = self._one(session, ctx, rec_id, lock=True)
            rec.status = "approved"
            rec.decided_by, rec.decided_at = ctx.user_id, self.rt.clock.now()
            rec.updated_at = self.rt.clock.now()
            self._audit(session, ctx, rec, "approved", action_id=str(action.id), sent=sent)
            return self._out(session, rec)

    def reject(
        self, ctx: TenantContext, rec_id: uuid.UUID, body: RecommendationRejectIn
    ) -> RecommendationOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rec = self._one(session, ctx, rec_id, lock=True)
            if self._open(rec):
                rec.status = "rejected"
                rec.decision_reason = body.reason
                rec.decision_note = (body.note or "").strip() or None
                rec.decided_by, rec.decided_at = ctx.user_id, self.rt.clock.now()
                rec.updated_at = self.rt.clock.now()
                self._audit(session, ctx, rec, "rejected", reason=body.reason)
                return self._out(session, rec)
        raise RecommendationClosed()

    def done(self, ctx: TenantContext, rec_id: uuid.UUID) -> RecommendationOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rec = self._one(session, ctx, rec_id, lock=True)
            if self._open(rec):
                if rec.proposal.get("action_type"):
                    raise Conflict("This advice proposes a change: approve or reject it.")
                rec.status = "done"
                rec.decided_by, rec.decided_at = ctx.user_id, self.rt.clock.now()
                rec.updated_at = self.rt.clock.now()
                self._audit(session, ctx, rec, "done")
                return self._out(session, rec)
        raise RecommendationClosed()

    # ------------------------------------------------------------------ look again now
    def refresh(self, ctx: TenantContext) -> RecommendationListOut:
        authorize(ctx, Permission.ACTIONS_REQUEST)
        if not self.rt.settings.OPTIMIZATION_ENABLED:
            raise OptimizationDisabled()
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            org = session.get(Organization, ctx.organization_id)
            assert org is not None
            row = settings_for(self.rt, session, ctx.organization_id)
            today = local_today(self.rt.clock.now(), org.default_timezone)
            if row.refreshes_on != today:
                row.refreshes_on, row.refreshes_used = today, 0
            if row.refreshes_used >= self.rt.settings.OPTIMIZATION_REFRESHES_PER_DAY:
                raise RefreshLimit()
            row.refreshes_used += 1
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="recommendation.refresh_requested",
                resource_type="organization",
                resource_id=ctx.organization_id,
            )
        run_look(self.rt, ctx.organization_id, user_id=ctx.user_id)
        return self.list_recommendations(ctx)

    # ------------------------------------------------------------------ settings
    def _settings_out(self, session: Session, ctx: TenantContext) -> OptimizationSettingsOut:
        s = self.rt.settings
        org = session.get(Organization, ctx.organization_id)
        assert org is not None
        row = session.get(OptimizationSettings, ctx.organization_id)
        return OptimizationSettingsOut(
            enabled=s.OPTIMIZATION_ENABLED,
            currency=org.default_currency,
            min_spend=str(
                for_display(
                    row.min_spend if row else s.OPTIMIZATION_MIN_SPEND, org.default_currency
                )
            ),
            min_conversions=row.min_conversions if row else s.OPTIMIZATION_MIN_CONVERSIONS,
            budget_step_percent=row.budget_step_percent
            if row
            else s.OPTIMIZATION_BUDGET_STEP_PERCENT,
            cost_jump_percent=row.cost_jump_percent if row else s.OPTIMIZATION_COST_JUMP_PERCENT,
            max_step_percent=min(s.ACTIONS_MAX_INCREASE_PERCENT, s.ACTIONS_MAX_DECREASE_PERCENT),
            updated_at=row.updated_at if row and row.updated_by else None,
        )

    def get_settings(self, ctx: TenantContext) -> OptimizationSettingsOut:
        authorize(ctx, Permission.ACTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._settings_out(session, ctx)

    def put_settings(
        self, ctx: TenantContext, body: OptimizationSettingsIn
    ) -> OptimizationSettingsOut:
        authorize(ctx, Permission.ACTIONS_SETTINGS)
        s = self.rt.settings
        if body.budget_step_percent > min(
            s.ACTIONS_MAX_INCREASE_PERCENT, s.ACTIONS_MAX_DECREASE_PERCENT
        ):
            raise ValidationFailed(
                details=[{"field": "budget_step_percent", "reason": "above_engine_limit"}]
            )
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = settings_for(self.rt, session, ctx.organization_id)
            before = {
                "min_spend": str(row.min_spend),
                "min_conversions": row.min_conversions,
                "budget_step_percent": row.budget_step_percent,
                "cost_jump_percent": row.cost_jump_percent,
            }
            row.min_spend = body.min_spend
            row.min_conversions = body.min_conversions
            row.budget_step_percent = body.budget_step_percent
            row.cost_jump_percent = body.cost_jump_percent
            row.updated_by, row.updated_at = ctx.user_id, self.rt.clock.now()
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="optimization_settings.updated",
                resource_type="optimization_settings",
                resource_id=ctx.organization_id,
                before=before,
                after={**body.model_dump(mode="json")},
            )
            session.flush()
            return self._settings_out(session, ctx)
