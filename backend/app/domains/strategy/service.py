"""The campaign strategy workflow (Phase 8, task 8-05, PLAN Q-8-7, Q-8-8; D16).

* **Generate** (owner, admin, manager, analyst): check the request and the product, build the
  context (8-03), ask the model through ``run_task`` (daily limit, time limit, one retry; the
  call runs outside any transaction) and keep the validated answer as a **draft** with the
  budget amounts AdVegaX computed. Nothing is created at Google or Meta.
* **Edit**: the whole strategy and/or the budget, re-validated against today's figures with the
  same chain as the model's answers (8-04); an edited strategy is a draft again.
* **Mark ready** for the campaign builder (Phase 10B) and **archive** (kept, never deleted).
* Every change is audited (no strategy text in the audit — its status, objective, platforms
  and budget). Viewers can read; usage (runs, tokens, estimated cost) is for owners and admins.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ProductNotPlannable, StrategyArchived, ValidationFailed
from app.domains.ai.models import AiModel, AiRun, CampaignStrategy, PromptVersion
from app.domains.ai.runs import run_task, runs_today
from app.domains.audit.service import Actor, record_audit
from app.domains.commerce.models import Product
from app.domains.finance.definitions import for_display, minor_units
from app.domains.fx.service import FxTable
from app.domains.organizations.models import Organization
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.domains.strategy import budget as budgets
from app.domains.strategy.context import PlanningContext, build_context
from app.domains.strategy.schemas import (
    AiRunRefOut,
    BudgetIn,
    BudgetOut,
    EvidenceOut,
    PlatformAmountOut,
    StrategyCreateIn,
    StrategyOut,
    StrategySummaryOut,
    StrategyUpdateIn,
    UsageOut,
    UsagePeriodOut,
)
from app.domains.strategy.task import strategy_task
from app.domains.strategy.validation import (
    StrategyRequest,
    evidence_keys,
    plannable,
    shape_reasons,
    validate,
)
from app.runtime import Runtime

RESOURCE = "campaign_strategy"
FX_LOOKBACK_DAYS = 7
USAGE_DAYS = 30


def _invalid(field: str, reasons: list[str]) -> ValidationFailed:
    return ValidationFailed(details=[{"field": field, "issue": r} for r in reasons])


def _budget(body: BudgetIn, currency: str) -> budgets.Budget:
    exponent = body.amount.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > minor_units(currency):
        raise _invalid("budget.amount", ["too_many_decimals"])
    return budgets.Budget(body.amount, body.period, currency)


def _summary(row: Any) -> dict[str, Any]:
    """What the audit keeps of a strategy: never its text."""
    return {
        "status": row.status,
        "objective": row.strategy.get("objective"),
        "platforms": [p.get("platform") for p in row.strategy.get("platforms", [])],
        "budget": {
            "amount": str(row.budget_amount),
            "period": row.budget_period,
            "currency": row.budget_currency,
        },
    }


def strategy_row(
    session: Session, organization_id: uuid.UUID, strategy_id: uuid.UUID, *, lock: bool = False
) -> tuple[CampaignStrategy, str | None, AiRun, AiModel, PromptVersion]:
    """The strategy with its product's title and the run, model and prompt it came from."""
    query = (
        select(CampaignStrategy, Product.title, AiRun, AiModel, PromptVersion)
        .join(
            AiRun,
            (AiRun.id == CampaignStrategy.ai_run_id)
            & (AiRun.organization_id == CampaignStrategy.organization_id),
        )
        .join(AiModel, AiModel.id == AiRun.model_id)
        .join(PromptVersion, PromptVersion.id == AiRun.prompt_version_id)
        .outerjoin(
            Product,
            (Product.id == CampaignStrategy.product_id)
            & (Product.organization_id == CampaignStrategy.organization_id),
        )
        .where(
            CampaignStrategy.organization_id == organization_id,
            CampaignStrategy.id == strategy_id,
        )
    )
    if lock:
        query = query.with_for_update(of=CampaignStrategy)
    found = session.execute(query).first()
    if found is None:
        raise NotFound()
    row, title, run, model, prompt = found
    return row, title, run, model, prompt


def _budget_out(row: CampaignStrategy) -> BudgetOut:
    return BudgetOut(
        amount=for_display(row.budget_amount, row.budget_currency),
        period=row.budget_period,
        currency=row.budget_currency,
        currency_minor_units=minor_units(row.budget_currency),
    )


class StrategyService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ helpers
    def _context(self, session: Session, ctx: TenantContext, product_id: uuid.UUID) -> Any:
        return build_context(
            session,
            self.rt.settings,
            organization_id=ctx.organization_id,
            product_id=product_id,
            now=self.rt.clock.now(),
        )

    def _minimums(self, session: Session, context: PlanningContext) -> dict[str, Decimal | None]:
        first = context.last.fromordinal(context.last.toordinal() - FX_LOOKBACK_DAYS)
        fx = FxTable.load(session, first, context.last, self.rt.settings.FX_MAX_STALE_DAYS)
        return budgets.minimums(self.rt.settings, fx, context.currency, context.last)

    def _check(
        self,
        session: Session,
        context: PlanningContext,
        request: StrategyRequest,
        answer: dict[str, Any],
    ) -> list[str]:
        return validate(
            answer,
            context,
            request,
            minimums=self._minimums(session, context),
            target_factor=self.rt.settings.PLANNER_TARGET_FACTOR,
        )

    def _out(self, session: Session, ctx: TenantContext, strategy_id: uuid.UUID) -> StrategyOut:
        row, title, run, model, prompt = strategy_row(session, ctx.organization_id, strategy_id)
        figures = (run.context_snapshot or {}).get("figures", {})
        evidence: dict[str, EvidenceOut | None] = {}
        shape_ok = not shape_reasons(row.strategy)
        for key in evidence_keys(row.strategy) if shape_ok else []:
            found = figures.get(key)
            evidence[key] = EvidenceOut(**found) if isinstance(found, dict) else None
        return StrategyOut(
            id=row.id,
            product_id=row.product_id,
            product_title=title,
            status=row.status,
            strategy=row.strategy,
            budget=_budget_out(row),
            budget_amounts={
                p: PlatformAmountOut(amount=Decimal(v["amount"]), daily=Decimal(v["daily"]))
                for p, v in row.budget_amounts.items()
            },
            evidence=evidence,
            validated=True,
            ai_run=AiRunRefOut(
                id=run.id,
                provider=model.provider,
                model=model.model_name,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                created_at=run.created_at,
            ),
            created_by=row.created_by,
            edited_by=row.edited_by,
            edited_at=row.edited_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _audit(
        self,
        session: Session,
        ctx: TenantContext,
        action: str,
        row: Any,
        before: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record_audit(
            session,
            organization_id=ctx.organization_id,
            actor=Actor.user(ctx.user_id),
            action=f"{RESOURCE}.{action}",
            resource_type=RESOURCE,
            resource_id=row.id,
            before=before,
            after=_summary(row),
            metadata=metadata,
        )

    # ------------------------------------------------------------------ generate
    def generate(self, ctx: TenantContext, body: StrategyCreateIn) -> StrategyOut:
        authorize(ctx, Permission.STRATEGIES_MANAGE)
        platforms = tuple(dict.fromkeys(body.platforms))
        if len(platforms) != len(body.platforms):
            raise _invalid("platforms", ["duplicate_platform"])
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            org = session.get(Organization, ctx.organization_id)
            if org is None:
                raise NotFound()
            budget = _budget(body.budget, org.default_currency)
            context = self._context(session, ctx, body.product_id)
            reasons = plannable(context)
            reasons += [
                f"platform_not_connected:{p}" for p in platforms if p not in context.platforms
            ]
            minimums = self._minimums(session, context)
            reasons += budgets.floor_reasons(budget, list(platforms), minimums)
            if reasons:
                raise ProductNotPlannable(details=[{"reason": r} for r in reasons])
        request = StrategyRequest(body.product_id, platforms, body.objective, budget)
        task = strategy_task(
            context,
            request,
            minimums=minimums,
            target_factor=self.rt.settings.PLANNER_TARGET_FACTOR,
        )
        outcome = run_task(
            self.rt, organization_id=ctx.organization_id, user_id=ctx.user_id, task=task
        )
        split = budgets.amounts(
            budget,
            {
                p["platform"]: Decimal(str(p["budget_share_percent"]))
                for p in outcome.data["platforms"]
            },
        )
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = CampaignStrategy(
                organization_id=ctx.organization_id,
                product_id=context.product_id,
                ai_run_id=outcome.run_id,
                status="draft",
                strategy=outcome.data,
                budget_amount=budget.amount,
                budget_period=budget.period,
                budget_currency=budget.currency,
                budget_amounts=budgets.out(budget, split),
                created_by=ctx.user_id,
            )
            session.add(row)
            session.flush()
            self._audit(session, ctx, "generated", row, metadata={"ai_run_id": outcome.run_id})
            return self._out(session, ctx, row.id)

    # ------------------------------------------------------------------ read
    def get(self, ctx: TenantContext, strategy_id: uuid.UUID) -> StrategyOut:
        authorize(ctx, Permission.STRATEGIES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._out(session, ctx, strategy_id)

    def list_strategies(
        self,
        ctx: TenantContext,
        *,
        page: int,
        page_size: int,
        status: str | None,
        product_id: uuid.UUID | None,
    ) -> tuple[list[StrategySummaryOut], int]:
        authorize(ctx, Permission.STRATEGIES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            where = [CampaignStrategy.organization_id == ctx.organization_id]
            if status is not None:
                where.append(CampaignStrategy.status == status)
            else:
                where.append(CampaignStrategy.status != "archived")
            if product_id is not None:
                where.append(CampaignStrategy.product_id == product_id)
            total = session.execute(
                select(func.count()).select_from(CampaignStrategy).where(*where)
            ).scalar_one()
            rows = session.execute(
                select(CampaignStrategy, Product.title)
                .outerjoin(
                    Product,
                    (Product.id == CampaignStrategy.product_id)
                    & (Product.organization_id == CampaignStrategy.organization_id),
                )
                .where(*where)
                .order_by(CampaignStrategy.updated_at.desc(), CampaignStrategy.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            items = [
                StrategySummaryOut(
                    id=row.id,
                    product_id=row.product_id,
                    product_title=title,
                    status=row.status,
                    objective=str(row.strategy.get("objective")),
                    platforms=[str(p.get("platform")) for p in row.strategy.get("platforms", [])],
                    budget=_budget_out(row),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row, title in rows
            ]
            return items, total

    # ------------------------------------------------------------------ change
    def update(
        self, ctx: TenantContext, strategy_id: uuid.UUID, body: StrategyUpdateIn
    ) -> StrategyOut:
        authorize(ctx, Permission.STRATEGIES_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = strategy_row(session, ctx.organization_id, strategy_id, lock=True)[0]
            if row.status == "archived":
                raise StrategyArchived()
            before = _summary(row)
            answer = body.strategy if body.strategy is not None else row.strategy
            budget = (
                _budget(body.budget, row.budget_currency)
                if body.budget is not None
                else budgets.Budget(row.budget_amount, row.budget_period, row.budget_currency)
            )
            shape = shape_reasons(answer)
            if shape:
                raise _invalid("strategy", shape)
            platforms = tuple(p["platform"] for p in answer["platforms"])
            request = StrategyRequest(row.product_id, platforms, answer["objective"], budget)
            context = self._context(session, ctx, row.product_id)
            reasons = self._check(session, context, request, answer)
            if reasons:
                raise _invalid("strategy", reasons)
            split = budgets.amounts(
                budget,
                {
                    p["platform"]: Decimal(str(p["budget_share_percent"]))
                    for p in answer["platforms"]
                },
            )
            row.strategy = answer
            row.budget_amount, row.budget_period = budget.amount, budget.period
            row.budget_amounts = budgets.out(budget, split)
            row.status = "draft"  # an edited strategy is reviewed again before it is ready
            row.edited_by, row.edited_at = ctx.user_id, self.rt.clock.now()
            row.updated_at = row.edited_at
            session.flush()
            self._audit(session, ctx, "edited", row, before=before)
            return self._out(session, ctx, row.id)

    def _move(self, ctx: TenantContext, strategy_id: uuid.UUID, to: str) -> StrategyOut:
        authorize(ctx, Permission.STRATEGIES_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = strategy_row(session, ctx.organization_id, strategy_id, lock=True)[0]
            if row.status == to:
                return self._out(session, ctx, row.id)  # nothing to change
            if row.status == "archived":
                raise StrategyArchived()
            before = _summary(row)
            row.status = to
            row.updated_at = self.rt.clock.now()
            session.flush()
            self._audit(session, ctx, "ready" if to == "ready" else "archived", row, before=before)
            return self._out(session, ctx, row.id)

    def mark_ready(self, ctx: TenantContext, strategy_id: uuid.UUID) -> StrategyOut:
        return self._move(ctx, strategy_id, "ready")

    def archive(self, ctx: TenantContext, strategy_id: uuid.UUID) -> StrategyOut:
        return self._move(ctx, strategy_id, "archived")

    # ------------------------------------------------------------------ usage
    def usage(self, ctx: TenantContext) -> UsageOut:
        authorize(ctx, Permission.AI_USAGE_VIEW)
        now = self.rt.clock.now()
        today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        since = datetime.fromordinal(today.toordinal() - (USAGE_DAYS - 1)).replace(tzinfo=UTC)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            used = runs_today(session, ctx.organization_id, now)

            def period(start: datetime) -> UsagePeriodOut:
                rows = session.execute(
                    select(
                        AiRun.status,
                        func.count(),
                        func.coalesce(func.sum(AiRun.input_tokens), 0),
                        func.coalesce(func.sum(AiRun.output_tokens), 0),
                        func.sum(AiRun.estimated_cost),
                        func.count(AiRun.estimated_cost),
                    )
                    .where(AiRun.organization_id == ctx.organization_id, AiRun.created_at >= start)
                    .group_by(AiRun.status)
                ).all()
                by = {r[0]: r for r in rows}
                runs = sum(r[1] for r in rows)
                priced = sum(r[5] for r in rows)
                cost = sum((r[4] or Decimal(0) for r in rows), Decimal(0))
                return UsagePeriodOut(
                    runs=runs,
                    succeeded=by["succeeded"][1] if "succeeded" in by else 0,
                    rejected=by["rejected"][1] if "rejected" in by else 0,
                    failed=sum(by[s][1] for s in ("failed", "timed_out") if s in by),
                    input_tokens=int(sum(r[2] for r in rows)),
                    output_tokens=int(sum(r[3] for r in rows)),
                    # Unknown unless every run has a price; no runs with prices set: 0.
                    estimated_cost_usd=(
                        cost
                        if runs and priced == runs
                        else Decimal(0)
                        if not runs and self._priced()
                        else None
                    ),
                )

            limit = self.rt.settings.AI_DAILY_RUNS
            return UsageOut(
                daily_limit=limit,
                runs_today=used,
                remaining_today=max(limit - used, 0),
                today=period(today),
                last_30_days=period(since),
                ai_enabled=self.rt.settings.AI_ENABLED,
            )

    def _priced(self) -> bool:
        s = self.rt.settings
        return s.AI_PRICE_INPUT_PER_MTOK is not None and s.AI_PRICE_OUTPUT_PER_MTOK is not None
