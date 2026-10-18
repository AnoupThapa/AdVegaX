"""Reading ad accounts, campaigns and their figures (task 3-08, PLAN §10-§11).

Same rules as the store API: every member can read, managers and above can "Sync now",
another organization's data is a 404, money is an exact decimal string and every missing
value carries an availability and a reason instead of a 0 (A10).

Figures are **platform-reported** and never added across levels: an account's totals come
from its account-level rows, a campaign's from its campaign rows, and so on. Rates are
derived on read (A5) and are "unavailable" with a reason when their divisor is 0. A day that
was not read is "not synchronized"; a period containing one has no totals. The last days
(``ADS_UNSETTLED_DAYS``) are marked as not settled because the platform still changes them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.domains.advertising.importer import (
    QUOTA_WAITING,
    chain_running,
    local_today,
    request_sync,
)
from app.domains.advertising.models import (
    Ad,
    AdAccount,
    AdBudget,
    AdCampaign,
    AdGroup,
    AdPerformanceDaily,
    AdSyncState,
)
from app.domains.advertising.schemas import (
    AdAccountOut,
    AdBudgetOut,
    AdCampaignDetailOut,
    AdCampaignListOut,
    AdCampaignOut,
    AdDailyMetricsOut,
    AdDayOut,
    AdFiguresOut,
    AdGroupOut,
    AdHealthOut,
    AdOut,
    AdResyncOut,
    AdSyncOut,
)
from app.domains.commerce.schemas import FigureOut
from app.domains.finance.definitions import minor_units
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

SOURCE = "platform_reported"
NOT_SYNCHRONIZED = "not_synchronized"
RATE_PLACES = Decimal("0.000001")  # rates and per-unit money: six decimals, exact half-even
DEFAULT_DAYS = 30


@dataclass(frozen=True)
class _AccountRow:
    account: AdAccount
    state: AdSyncState | None
    resource: ExternalResource
    connection: ExternalConnection
    linked: bool


@dataclass(frozen=True)
class Sums:
    """Measures of a day or a period; None = the platform did not provide one of them."""

    impressions: int | None = 0
    clicks: int | None = 0
    cost: Decimal | None = Decimal(0)
    conversions: Decimal | None = Decimal(0)
    conversion_value: Decimal | None = Decimal(0)


ZERO = Sums()


@dataclass(frozen=True)
class _Period:
    first: date
    last: date
    today: date
    synced_from: date | None

    @property
    def synced(self) -> bool:
        """Every day of the period has been read."""
        return (
            self.synced_from is not None
            and self.first >= self.synced_from
            and self.last <= self.today
        )

    def day_synced(self, day: date) -> bool:
        return self.synced_from is not None and self.synced_from <= day <= self.today


# ---------------------------------------------------------------------- figures
def _rate(numerator: Any, denominator: Any, zero_reason: str) -> FigureOut:
    if numerator is None or denominator is None:
        return FigureOut(value=None, availability="unavailable", reason="not_provided")
    if Decimal(denominator) == 0:
        return FigureOut(value=None, availability="unavailable", reason=zero_reason)
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        RATE_PLACES, rounding=ROUND_HALF_EVEN
    )
    return FigureOut(value=value, availability="available")


def figures(sums: Sums) -> AdFiguresOut:
    return AdFiguresOut(availability="available", **_measures(sums))


def _measures(sums: Sums) -> dict[str, Any]:
    return {
        "impressions": sums.impressions,
        "clicks": sums.clicks,
        "cost": sums.cost,
        "conversions": sums.conversions,
        "conversion_value": sums.conversion_value,
        "click_through_rate": _rate(sums.clicks, sums.impressions, "no_impressions"),
        "cost_per_click": _rate(sums.cost, sums.clicks, "no_clicks"),
        "cost_per_conversion": _rate(sums.cost, sums.conversions, "no_conversions"),
        "conversion_value_per_cost": _rate(sums.conversion_value, sums.cost, "no_cost"),
    }


def _not_synced() -> dict[str, Any]:
    missing = FigureOut(value=None, availability=NOT_SYNCHRONIZED, reason=NOT_SYNCHRONIZED)
    return {
        "availability": NOT_SYNCHRONIZED,
        "reason": NOT_SYNCHRONIZED,
        "impressions": None,
        "clicks": None,
        "cost": None,
        "conversions": None,
        "conversion_value": None,
        "click_through_rate": missing,
        "cost_per_click": missing,
        "cost_per_conversion": missing,
        "conversion_value_per_cost": missing,
    }


def not_synced_figures() -> AdFiguresOut:
    return AdFiguresOut(**_not_synced())


def add(a: Sums, b: Sums) -> Sums:
    def plus(x: Any, y: Any) -> Any:
        return None if x is None or y is None else x + y

    return Sums(
        impressions=plus(a.impressions, b.impressions),
        clicks=plus(a.clicks, b.clicks),
        cost=plus(a.cost, b.cost),
        conversions=plus(a.conversions, b.conversions),
        conversion_value=plus(a.conversion_value, b.conversion_value),
    )


def _row_sums(row: AdPerformanceDaily) -> Sums:
    return Sums(row.impressions, row.clicks, row.cost, row.conversions, row.conversion_value)


def _budget(budget: AdBudget | None) -> AdBudgetOut | None:
    if budget is None:
        return None
    return AdBudgetOut(
        name=budget.name,
        period=budget.period,
        amount=budget.amount,
        currency=budget.currency,
        shared=budget.shared,
    )


# ---------------------------------------------------------------------- the service
class AdvertisingReadService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ accounts
    def _rows(
        self, session: Session, ctx: TenantContext, account_id: uuid.UUID | None
    ) -> list[_AccountRow]:
        active_link = (
            select(OrganizationResourceLink.id)
            .where(
                OrganizationResourceLink.external_resource_id == AdAccount.external_resource_id,
                OrganizationResourceLink.status == "active",
            )
            .exists()
        )
        stmt = (
            select(AdAccount, AdSyncState, ExternalResource, ExternalConnection, active_link)
            .outerjoin(AdSyncState, AdSyncState.ad_account_id == AdAccount.id)
            .join(ExternalResource, ExternalResource.id == AdAccount.external_resource_id)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .where(AdAccount.organization_id == ctx.organization_id)
            .order_by(AdAccount.created_at)
        )
        if account_id is not None:
            stmt = stmt.where(AdAccount.id == account_id)
        return [
            _AccountRow(a, st, r, c, bool(linked)) for a, st, r, c, linked in session.execute(stmt)
        ]

    def _one(self, session: Session, ctx: TenantContext, account_id: uuid.UUID) -> _AccountRow:
        rows = self._rows(session, ctx, account_id)
        if not rows:
            raise NotFound()
        return rows[0]

    def _account_out(self, row: _AccountRow) -> AdAccountOut:
        account, state = row.account, row.state
        running = state is not None and chain_running(self.rt, state)
        return AdAccountOut(
            id=account.id,
            resource_id=account.external_resource_id,
            provider=account.provider,
            source=SOURCE,
            external_account_id=account.external_account_id,
            name=account.name,
            group_path=row.resource.group_path,
            currency=account.currency,
            currency_minor_units=minor_units(account.currency),
            timezone=account.timezone,
            status=account.status,
            platform_status=account.platform_status,
            linked=row.linked,
            connection_status=row.connection.status,
            history_from=account.history_from,
            first_import_completed_at=account.first_import_completed_at,
            sync=AdSyncOut(
                running=running,
                mode=state.sync_mode if state is not None and running else None,
                progress=(
                    state.import_progress
                    if state is not None and account.first_import_completed_at is None
                    else None
                ),
                waiting_for_allowance=(
                    running and state is not None and state.last_error_code == QUOTA_WAITING
                ),
                last_quick_at=state.last_quick_at if state else None,
                last_nightly_at=state.last_nightly_at if state else None,
                last_weekly_at=state.last_weekly_at if state else None,
                last_error_code=(
                    state.last_error_code
                    if state is not None and state.last_error_code != QUOTA_WAITING
                    else None
                ),
                last_error_at=(
                    state.last_error_at
                    if state is not None and state.last_error_code != QUOTA_WAITING
                    else None
                ),
            ),
            health=(
                AdHealthOut(code=account.health_code, checked_at=account.health_checked_at)
                if account.health_checked_at is not None
                else None
            ),
            created_at=account.created_at,
        )

    def list_accounts(self, ctx: TenantContext) -> list[AdAccountOut]:
        authorize(ctx, Permission.ADS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return [self._account_out(row) for row in self._rows(session, ctx, None)]

    def get_account(self, ctx: TenantContext, account_id: uuid.UUID) -> AdAccountOut:
        authorize(ctx, Permission.ADS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._account_out(self._one(session, ctx, account_id))

    def resync(self, ctx: TenantContext, account_id: uuid.UUID) -> AdResyncOut:
        """ "Sync now": the structure and the last 30 days (limited per account)."""
        authorize(ctx, Permission.ADS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            account = self._one(session, ctx, account_id).account
            job_id, mode = request_sync(session, self.rt, account, requested_by=ctx.user_id)
            return AdResyncOut(ad_account_id=account.id, job_id=job_id, mode=mode.value)

    # ------------------------------------------------------------------ periods
    def _period(self, account: AdAccount, from_day: date | None, to_day: date | None) -> _Period:
        today = local_today(self.rt, account.timezone)
        last = to_day or today
        first = from_day or date.fromordinal(last.toordinal() - (DEFAULT_DAYS - 1))
        span = last.toordinal() - first.toordinal() + 1
        if span < 1 or span > self.rt.settings.METRICS_MAX_DAYS:
            raise ValidationFailed(details=[{"field": "from", "issue": "invalid_range"}])
        synced_from = account.history_from if account.first_import_completed_at else None
        return _Period(first, last, today, synced_from)

    def daily_metrics(
        self,
        ctx: TenantContext,
        account_id: uuid.UUID,
        *,
        from_day: date | None,
        to_day: date | None,
    ) -> AdDailyMetricsOut:
        """Account-level days and totals for a period (defaults to the last 30 days)."""
        authorize(ctx, Permission.ADS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            account = self._one(session, ctx, account_id).account
            period = self._period(account, from_day, to_day)
            rows = {
                r.day: r
                for r in session.execute(
                    select(AdPerformanceDaily).where(
                        AdPerformanceDaily.organization_id == ctx.organization_id,
                        AdPerformanceDaily.ad_account_id == account.id,
                        AdPerformanceDaily.level == "account",
                        AdPerformanceDaily.day >= period.first,
                        AdPerformanceDaily.day <= period.last,
                    )
                ).scalars()
            }
            settled_until = date.fromordinal(
                period.today.toordinal() - max(0, self.rt.settings.ADS_UNSETTLED_DAYS)
            )
            days: list[AdDayOut] = []
            total, complete = ZERO, True
            for ordinal in range(period.first.toordinal(), period.last.toordinal() + 1):
                day = date.fromordinal(ordinal)
                row = rows.get(day)
                settled = day <= settled_until
                if row is None or not period.day_synced(day):
                    complete = False  # never read: "not synchronized", never 0
                    days.append(AdDayOut(day=day, settled=settled, **_not_synced()))
                    continue
                sums = _row_sums(row)
                total = add(total, sums)
                days.append(
                    AdDayOut(day=day, settled=settled, availability="available", **_measures(sums))
                )
            return AdDailyMetricsOut(
                ad_account_id=account.id,
                source=SOURCE,
                currency=account.currency,
                currency_minor_units=minor_units(account.currency),
                timezone=account.timezone,
                from_day=period.first,
                to_day=period.last,
                synced_from=period.synced_from,
                settled_until=settled_until,
                days=days,
                totals=figures(total) if complete else not_synced_figures(),
            )

    # ------------------------------------------------------------------ campaigns
    def _sums_by(
        self,
        session: Session,
        ctx: TenantContext,
        account_id: uuid.UUID,
        level: str,
        key: Any,
        period: _Period,
        *where: Any,
    ) -> dict[uuid.UUID, Sums]:
        """Period sums per linked entity of one level (rows of unknown entities are left out
        here; they still count in the account totals)."""
        p = AdPerformanceDaily
        columns = (p.impressions, p.clicks, p.cost, p.conversions, p.conversion_value)
        stmt = (
            select(
                key,
                *(func.sum(c) for c in columns),
                *(func.bool_and(c.is_not(None)) for c in columns),
            )
            .where(
                p.organization_id == ctx.organization_id,
                p.ad_account_id == account_id,
                p.level == level,
                p.day >= period.first,
                p.day <= period.last,
                key.is_not(None),
                *where,
            )
            .group_by(key)
        )
        result: dict[uuid.UUID, Sums] = {}
        for row in session.execute(stmt):
            sums, provided = row[1:6], row[6:11]
            values = [v if ok else None for v, ok in zip(sums, provided, strict=True)]
            result[row[0]] = Sums(
                impressions=int(values[0]) if values[0] is not None else None,
                clicks=int(values[1]) if values[1] is not None else None,
                cost=values[2],
                conversions=values[3],
                conversion_value=values[4],
            )
        return result

    def _entity_figures(
        self, period: _Period, sums: dict[uuid.UUID, Sums], key: uuid.UUID
    ) -> AdFiguresOut:
        if not period.synced:
            return not_synced_figures()
        return figures(sums.get(key, ZERO))  # no row in a read period: no activity

    def _campaign_out(
        self,
        campaign: AdCampaign,
        budget: AdBudget | None,
        figures_out: AdFiguresOut,
    ) -> AdCampaignOut:
        return AdCampaignOut(
            id=campaign.id,
            ad_account_id=campaign.ad_account_id,
            external_id=campaign.external_campaign_id,
            name=campaign.name,
            status=campaign.status,
            platform_type=campaign.platform_type,
            bidding_strategy_type=campaign.bidding_strategy_type,
            start_date=campaign.start_date,
            end_date=campaign.end_date,
            budget=_budget(budget),
            figures=figures_out,
        )

    def list_campaigns(
        self,
        ctx: TenantContext,
        account_id: uuid.UUID,
        *,
        from_day: date | None,
        to_day: date | None,
    ) -> AdCampaignListOut:
        """Every campaign of the account (removed ones included) with its period figures."""
        authorize(ctx, Permission.ADS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            account = self._one(session, ctx, account_id).account
            period = self._period(account, from_day, to_day)
            sums = self._sums_by(
                session,
                ctx,
                account.id,
                "campaign",
                AdPerformanceDaily.campaign_id,
                period,
            )
            rows = session.execute(
                select(AdCampaign, AdBudget)
                .outerjoin(AdBudget, AdBudget.id == AdCampaign.budget_id)
                .where(
                    AdCampaign.organization_id == ctx.organization_id,
                    AdCampaign.ad_account_id == account.id,
                )
                .order_by(AdCampaign.name, AdCampaign.id)
            ).all()
            return AdCampaignListOut(
                ad_account_id=account.id,
                source=SOURCE,
                currency=account.currency,
                currency_minor_units=minor_units(account.currency),
                from_day=period.first,
                to_day=period.last,
                items=[
                    self._campaign_out(c, b, self._entity_figures(period, sums, c.id))
                    for c, b in rows
                ],
            )

    def get_campaign(
        self,
        ctx: TenantContext,
        campaign_id: uuid.UUID,
        *,
        from_day: date | None,
        to_day: date | None,
    ) -> AdCampaignDetailOut:
        """One campaign with its ad groups and ads, each with its own period figures."""
        authorize(ctx, Permission.ADS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            found = session.execute(
                select(AdCampaign, AdBudget)
                .outerjoin(AdBudget, AdBudget.id == AdCampaign.budget_id)
                .where(
                    AdCampaign.organization_id == ctx.organization_id,
                    AdCampaign.id == campaign_id,
                )
            ).one_or_none()
            if found is None:
                raise NotFound()
            campaign, budget = found
            account = self._one(session, ctx, campaign.ad_account_id).account
            period = self._period(account, from_day, to_day)
            p = AdPerformanceDaily
            own = self._sums_by(
                session,
                ctx,
                account.id,
                "campaign",
                p.campaign_id,
                period,
                p.campaign_id == campaign.id,
            )
            group_sums = self._sums_by(
                session,
                ctx,
                account.id,
                "ad_group",
                p.ad_group_id,
                period,
                p.campaign_id == campaign.id,
            )
            ad_sums = self._sums_by(
                session, ctx, account.id, "ad", p.ad_id, period, p.campaign_id == campaign.id
            )
            groups = session.execute(
                select(AdGroup, AdBudget)
                .outerjoin(AdBudget, AdBudget.id == AdGroup.budget_id)
                .where(
                    AdGroup.organization_id == ctx.organization_id,
                    AdGroup.campaign_id == campaign.id,
                )
                .order_by(AdGroup.name, AdGroup.id)
            ).all()
            ads_by_group: dict[uuid.UUID, list[Ad]] = {}
            group_ids = [g.id for g, _ in groups]
            if group_ids:
                for item in session.execute(
                    select(Ad)
                    .where(Ad.organization_id == ctx.organization_id, Ad.ad_group_id.in_(group_ids))
                    .order_by(Ad.external_ad_id)
                ).scalars():
                    ads_by_group.setdefault(item.ad_group_id, []).append(item)
            base = self._campaign_out(
                campaign, budget, self._entity_figures(period, own, campaign.id)
            )
            return AdCampaignDetailOut(
                **base.model_dump(),
                provider=account.provider,
                source=SOURCE,
                synced_from=period.synced_from,
                currency=account.currency,
                currency_minor_units=minor_units(account.currency),
                from_day=period.first,
                to_day=period.last,
                ad_groups=[
                    AdGroupOut(
                        id=g.id,
                        external_id=g.external_ad_group_id,
                        name=g.name,
                        status=g.status,
                        platform_type=g.platform_type,
                        budget=_budget(gb),
                        figures=self._entity_figures(period, group_sums, g.id),
                        ads=[
                            AdOut(
                                id=a.id,
                                external_id=a.external_ad_id,
                                name=a.name,
                                status=a.status,
                                platform_type=a.platform_type,
                                figures=self._entity_figures(period, ad_sums, a.id),
                            )
                            for a in ads_by_group.get(g.id, [])
                        ],
                    )
                    for g, gb in groups
                ],
            )
