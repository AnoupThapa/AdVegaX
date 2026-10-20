"""The unified analytics API (Phase 6, task 6-05, PLAN §8; definitions: ``registry.py``).

Every member can read (``analytics.view``); another organization's data is never visible (row-
level security plus explicit organization filters; a foreign store is a 404). Periods default to
the last 30 days of the reporting time zone and are at most ``METRICS_MAX_DAYS`` long.
"""

from __future__ import annotations

import uuid
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.domains.commerce.models import Store
from app.domains.commerce.schemas import FigureOut
from app.domains.finance.definitions import minor_units
from app.domains.fx.service import FxTable
from app.domains.metrics import channels as channel_figures
from app.domains.metrics.engine import Figure, Inputs, Scope, compute, load_inputs, load_scope
from app.domains.metrics.registry import DEFINITION_VERSION, METRICS
from app.domains.metrics.schemas import (
    AnalyticsChannelOut,
    ChannelsOut,
    ConversionOut,
    MetricDefinitionOut,
    OverviewDayOut,
    OverviewOut,
    PlatformOut,
    SourceOut,
)
from app.domains.organizations.models import Organization
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

DEFAULT_DAYS = 30


def figure_out(figure: Figure) -> FigureOut:
    return FigureOut(
        value=figure.value,
        availability=figure.availability,
        reason=figure.reason,
    )


def definitions() -> list[MetricDefinitionOut]:
    return [
        MetricDefinitionOut(
            key=m.key,
            label=m.label,
            unit=m.unit,
            formula=m.formula,
            note=m.note,
            sources=list(m.sources),
        )
        for m in METRICS
    ]


class MetricsReadService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    def _prepare(
        self,
        session: Session,
        ctx: TenantContext,
        from_day: date | None,
        to_day: date | None,
        store_id: uuid.UUID | None,
    ) -> tuple[Scope, Inputs, FxTable]:
        org = session.get(Organization, ctx.organization_id)
        if org is None:
            raise NotFound()
        if store_id is not None:
            found = session.execute(
                select(Store.id).where(
                    Store.organization_id == ctx.organization_id, Store.id == store_id
                )
            ).first()
            if found is None:
                raise NotFound()
        now = self.rt.clock.now()
        scope = load_scope(
            session,
            organization_id=ctx.organization_id,
            currency=org.default_currency,
            timezone=org.default_timezone,
            now=now,
            store_id=store_id,
        )
        today = now.astimezone(ZoneInfo(org.default_timezone)).date()
        last = to_day or today
        first = from_day or date.fromordinal(last.toordinal() - (DEFAULT_DAYS - 1))
        span = last.toordinal() - first.toordinal() + 1
        if span < 1 or span > self.rt.settings.METRICS_MAX_DAYS:
            raise ValidationFailed(details=[{"field": "from", "issue": "invalid_range"}])
        fx = FxTable.load(session, first, last, self.rt.settings.FX_MAX_STALE_DAYS)
        return scope, load_inputs(session, scope, first, last, fx), fx

    def _context(
        self, scope: Scope, inputs: Inputs, fx: FxTable, store_id: uuid.UUID | None
    ) -> dict[str, object]:
        return {
            "definition_version": DEFINITION_VERSION,
            "reporting_currency": scope.currency,
            "currency_minor_units": minor_units(scope.currency),
            "reporting_timezone": scope.timezone,
            "store_id": store_id,
            "from_day": inputs.first,
            "to_day": inputs.last,
            "sources": [
                SourceOut(
                    kind=s.kind,
                    id=s.id,
                    provider=s.provider,
                    name=s.name,
                    currency=s.currency,
                    timezone=s.timezone,
                    synced_from=s.synced_from,
                    updated_at=s.updated_at,
                )
                for s in scope.sources
            ],
            "conversions": _conversions(scope, inputs, fx),
            "notes": (
                ["time_zones_differ"]
                if any(s.timezone != scope.timezone for s in scope.sources)
                else []
            ),
        }

    def overview(
        self,
        ctx: TenantContext,
        *,
        from_day: date | None,
        to_day: date | None,
        store_id: uuid.UUID | None,
    ) -> OverviewOut:
        authorize(ctx, Permission.ANALYTICS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            scope, inputs, fx = self._prepare(session, ctx, from_day, to_day, store_id)
            totals = compute(scope, inputs.period())
            days = [
                OverviewDayOut(
                    day=day,
                    figures={
                        k: figure_out(v) for k, v in compute(scope, inputs.period(day, day)).items()
                    },
                )
                for day in sorted(inputs.days)
            ]
            return OverviewOut(
                **self._context(scope, inputs, fx, store_id),
                totals={k: figure_out(v) for k, v in totals.items()},
                days=days,
                definitions=definitions(),
            )

    def channels(
        self,
        ctx: TenantContext,
        *,
        from_day: date | None,
        to_day: date | None,
        store_id: uuid.UUID | None,
    ) -> ChannelsOut:
        authorize(ctx, Permission.ANALYTICS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            scope, inputs, fx = self._prepare(session, ctx, from_day, to_day, store_id)
            platforms = channel_figures.platforms(session, scope, inputs.first, inputs.last, fx)
            ga, ga_missing = channel_figures.analytics_channels(
                session, scope, inputs.first, inputs.last, fx
            )
            return ChannelsOut(
                **self._context(scope, inputs, fx, store_id),
                ad_spend=figure_out(compute(scope, inputs.period())["ad_spend"]),
                platforms=[
                    PlatformOut(
                        provider=p.provider,
                        source="platform_reported",
                        ad_accounts=p.accounts,
                        figures={k: figure_out(v) for k, v in p.figures.items()},
                    )
                    for p in platforms
                ],
                analytics_channels=[
                    AnalyticsChannelOut(
                        channel=c.channel,
                        figures={k: figure_out(v) for k, v in c.figures.items()},
                    )
                    for c in ga
                ],
                analytics_channels_missing=figure_out(ga_missing) if ga_missing else None,
            )


def _conversions(scope: Scope, inputs: Inputs, fx: FxTable) -> list[ConversionOut]:
    """Each source currency other than the reporting one: which banks' rates, which dates."""
    found: list[ConversionOut] = []
    currencies = sorted({s.currency for s in scope.sources} - {scope.currency})
    for currency in currencies:
        dates: list[date] = []
        banks: set[str] = set()
        missing_days = 0
        for day in sorted(inputs.days):
            rate = fx.rate(currency, scope.currency, day)
            if rate is None:
                missing_days += 1
                continue
            dates.append(rate.rate_date)
            banks.update(rate.sources)
        found.append(
            ConversionOut(
                currency=currency,
                rate_sources=sorted(banks),
                first_rate_date=min(dates) if dates else None,
                last_rate_date=max(dates) if dates else None,
                days_without_rate=missing_days,
            )
        )
    return found
