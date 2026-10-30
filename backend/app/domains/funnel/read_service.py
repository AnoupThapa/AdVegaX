"""The funnel API (Phase 7, task 7-06, PLAN §8; definitions: ``registry.py``).

Same rules as the unified analytics API (Phase 6): every member can read (``analytics.view``);
another organization's data or store is never visible (row-level security plus explicit
organization filters; a foreign store is a 404); periods default to the last 30 days of the
reporting time zone and are at most ``METRICS_MAX_DAYS`` long. The findings also read the
previous period and the baseline days before the period (Q-7-7).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.domains.funnel import breakdowns
from app.domains.funnel.engine import StepFigure, channels, load_funnel, platforms, whole
from app.domains.funnel.findings import find_drop_offs, rules_from
from app.domains.funnel.registry import FUNNEL_VERSION, PLATFORM_STAGES, STAGES, Stage
from app.domains.funnel.schemas import (
    CampaignFunnelOut,
    CampaignFunnelsOut,
    ChannelFunnelOut,
    FindingOut,
    FunnelOut,
    LandingPageFunnelOut,
    LandingPagesOut,
    PlatformFunnelOut,
    RulesOut,
    StepOut,
)
from app.domains.fx.service import FxTable
from app.domains.metrics.engine import Figure, Inputs, Scope, load_inputs
from app.domains.metrics.read_service import MetricsReadService, figure_out
from app.domains.metrics.schemas import MetricDefinitionOut
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext

MAX_LANDING_PAGES = 100


def _shift(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() + days)


def stage_definitions(stages: tuple[Stage, ...]) -> list[MetricDefinitionOut]:
    return [
        MetricDefinitionOut(
            key=s.key, label=s.label, unit="count", formula=s.formula, note=None, sources=[s.source]
        )
        for s in stages
    ]


def stages_out(stages: dict[str, Figure]) -> dict[str, Any]:
    return {k: figure_out(v) for k, v in stages.items()}


def steps_out(steps: list[StepFigure]) -> list[StepOut]:
    return [
        StepOut(
            from_stage=s.step.from_stage,
            to_stage=s.step.to_stage,
            kind=s.step.kind,
            rate=figure_out(s.rate) if s.rate is not None else None,
        )
        for s in steps
    ]


class FunnelReadService(MetricsReadService):
    def _funnel_context(
        self, scope: Scope, inputs: Inputs, fx: FxTable, store_id: uuid.UUID | None
    ) -> dict[str, Any]:
        context = self._context(scope, inputs, fx, store_id, ())
        context["definition_version"] = FUNNEL_VERSION
        context["definitions"] = stage_definitions(STAGES)
        return context

    def _open(
        self,
        session: Session,
        ctx: TenantContext,
        from_day: date | None,
        to_day: date | None,
        store_id: uuid.UUID | None,
    ) -> tuple[Scope, Inputs, FxTable]:
        return self._prepare(session, ctx, from_day, to_day, store_id)

    def funnel(
        self,
        ctx: TenantContext,
        *,
        from_day: date | None,
        to_day: date | None,
        store_id: uuid.UUID | None,
    ) -> FunnelOut:
        authorize(ctx, Permission.ANALYTICS_VIEW)
        rules = rules_from(self.rt.settings)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            scope, inputs, fx = self._open(session, ctx, from_day, to_day, store_id)
            first, last = inputs.first, inputs.last
            span = last.toordinal() - first.toordinal() + 1
            start = _shift(first, -max(span, rules.baseline_days))
            wide_fx = FxTable.load(session, start, last, self.rt.settings.FX_MAX_STALE_DAYS)
            funnel = load_funnel(session, scope, load_inputs(session, scope, start, last, wide_fx))
            period = funnel.period(first, last)
            stages, steps = whole(scope, period)
            listed, why = channels(scope, period)
            return FunnelOut(
                **self._funnel_context(scope, inputs, fx, store_id),
                stages=stages_out(stages),
                steps=steps_out(steps),
                platforms=[
                    PlatformFunnelOut(
                        provider=provider,
                        source="platform_reported",
                        ad_accounts=accounts,
                        stages=stages_out(own),
                        steps=steps_out(own_steps),
                    )
                    for provider, accounts, own, own_steps in platforms(scope, period)
                ],
                platform_definitions=stage_definitions(PLATFORM_STAGES),
                channels=[
                    ChannelFunnelOut(channel=name, stages=stages_out(s), steps=steps_out(st))
                    for name, s, st in listed
                ],
                channels_missing=figure_out(why) if why is not None else None,
                findings=[
                    FindingOut(**f.__dict__)
                    for f in find_drop_offs(scope, funnel, first, last, rules)
                ],
                rules=RulesOut(
                    drop_share=rules.drop_share,
                    min_events=rules.min_events,
                    baseline_days=rules.baseline_days,
                    previous_from=_shift(first, -span),
                    previous_to=_shift(first, -1),
                ),
            )

    def campaign_funnels(
        self,
        ctx: TenantContext,
        *,
        from_day: date | None,
        to_day: date | None,
        store_id: uuid.UUID | None,
    ) -> CampaignFunnelsOut:
        authorize(ctx, Permission.ANALYTICS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            scope, inputs, fx = self._open(session, ctx, from_day, to_day, store_id)
            found = breakdowns.campaign_funnels(session, scope, inputs.first, inputs.last)
            return CampaignFunnelsOut(
                **self._funnel_context(scope, inputs, fx, store_id),
                items=[
                    CampaignFunnelOut(
                        id=c.id,
                        ad_account_id=c.ad_account_id,
                        provider=c.provider,
                        source="platform_reported",
                        name=c.name,
                        status=c.status,
                        stages=stages_out(c.stages),
                        steps=steps_out(c.steps),
                        analytics=stages_out(c.analytics) if c.analytics is not None else None,
                        analytics_steps=steps_out(c.analytics_steps),
                        shared_match=c.shared_match,
                    )
                    for c in found.items
                ],
                other_traffic=stages_out(found.other_traffic)
                if found.other_traffic is not None
                else None,
                other_traffic_steps=steps_out(found.other_traffic_steps),
                website=stages_out(found.website) if found.website is not None else None,
                analytics_missing=figure_out(found.analytics_missing)
                if found.analytics_missing is not None
                else None,
                platform_definitions=stage_definitions(PLATFORM_STAGES),
            )

    def landing_pages(
        self,
        ctx: TenantContext,
        *,
        from_day: date | None,
        to_day: date | None,
        store_id: uuid.UUID | None,
    ) -> LandingPagesOut:
        authorize(ctx, Permission.ANALYTICS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            scope, inputs, fx = self._open(session, ctx, from_day, to_day, store_id)
            items, count, why = breakdowns.landing_page_funnels(
                session, scope, inputs.first, inputs.last, MAX_LANDING_PAGES
            )
            return LandingPagesOut(
                **self._funnel_context(scope, inputs, fx, store_id),
                items=[
                    LandingPageFunnelOut(
                        landing_page=p.landing_page,
                        stages=stages_out(p.stages),
                        steps=steps_out(p.steps),
                    )
                    for p in items
                ],
                item_count=count,
                items_missing=figure_out(why) if why is not None else None,
            )
