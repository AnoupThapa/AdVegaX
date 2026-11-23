"""Campaigns and products (Phase 6, task 6-06, PLAN §8, Q-6-9, Q-6-10, Q-6-11).

**Campaigns:** every campaign of the ad accounts in scope with what its platform reports for the
period (from the campaign-level daily rows), converted to the reporting currency with each day's
rate; its **budget use against today's budget** (daily budgets only: AdVegaX keeps no budget
history yet); and — when a Google Analytics property is in scope — Google Analytics' sessions,
purchases and revenue for the campaign whose name matches **exactly** (Google Ads: source
``google`` / medium ``cpc``; Meta: ``facebook`` or ``instagram`` / ``paid`` or ``cpc``). No
attribution model; a campaign without a match says "no match", never 0.

**Products:** every product sold in the period in the stores in scope: units, net sales, product
cost, gross profit and margin, built from the same sales records and rules as finance-v1 (each
sale on its day, returns on theirs, the strict missing-cost rule). Ad spend per product is not
shown (Q-6-10). Orders in another currency are left out and counted.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.advertising.models import AdBudget, AdCampaign, AdPerformanceDaily
from app.domains.analytics.models import AnalyticsDaily
from app.domains.commerce.models import Order, OrderItem, Product, ProductVariant, SalesEntry
from app.domains.finance.definitions import SaleRow, compute_days
from app.domains.fx.service import FxTable
from app.domains.metrics.engine import (
    NOT_SYNCED,
    UNAVAILABLE,
    Figure,
    Scope,
    minus,
    missing,
    plus,
    ratio,
    synced,
)

GOOGLE_MATCH = ({"google"}, {"cpc"})
META_MATCH = ({"facebook", "instagram"}, {"paid", "cpc"})


def _days(first: date, last: date) -> list[date]:
    return [date.fromordinal(o) for o in range(first.toordinal(), last.toordinal() + 1)]


def _money(fx: FxTable, value: Decimal | None, currency: str, target: str, day: date) -> Figure:
    if value is None:
        return missing(UNAVAILABLE, "not_provided")
    converted = fx.convert(value, currency, target, day)
    return Figure(converted) if converted is not None else missing(UNAVAILABLE, "no_exchange_rate")


def _count(value: Decimal | int | None) -> Figure:
    return Figure(Decimal(value)) if value is not None else missing(UNAVAILABLE, "not_provided")


# ------------------------------------------------------------------ campaigns
@dataclass(frozen=True)
class CampaignFigures:
    id: uuid.UUID
    ad_account_id: uuid.UUID
    provider: str
    name: str
    status: str
    budget_period: str | None
    figures: dict[str, Figure]
    analytics: dict[str, Figure] | None  # None when no property is in scope
    analytics_missing: Figure | None


def _analytics_by_campaign(
    session: Session, scope: Scope, first: date, last: date, fx: FxTable
) -> tuple[dict[tuple[str, str, str], dict[str, list[Figure]]], Figure | None]:
    props = list(scope.properties)
    if not props:
        return {}, missing(UNAVAILABLE, "no_analytics_property")
    if not all(synced(p, d) for p in props for d in _days(first, last)):
        return {}, missing(NOT_SYNCED, NOT_SYNCED)
    currency_of = {p.id: p.currency for p in props}
    found: dict[tuple[str, str, str], dict[str, list[Figure]]] = {}
    for row in session.execute(
        select(AnalyticsDaily).where(
            AnalyticsDaily.property_id.in_(list(currency_of)),
            AnalyticsDaily.breakdown == "source",
            AnalyticsDaily.day.between(first, last),
        )
    ).scalars():
        key = (
            (row.traffic_source or "").lower(),
            (row.traffic_medium or "").lower(),
            row.campaign or "",
        )
        entry = found.setdefault(key, {"sessions": [], "purchases": [], "revenue": []})
        entry["sessions"].append(_count(row.sessions))
        entry["purchases"].append(_count(row.purchases))
        entry["revenue"].append(
            _money(fx, row.purchase_revenue, currency_of[row.property_id], scope.currency, row.day)
        )
    return found, None


def _match(
    found: dict[tuple[str, str, str], dict[str, list[Figure]]], provider: str, name: str
) -> dict[str, Figure]:
    sources, mediums = GOOGLE_MATCH if provider == "google_ads" else META_MATCH
    parts: dict[str, list[Figure]] = {"sessions": [], "purchases": [], "revenue": []}
    for (source, medium, campaign), entry in found.items():
        if campaign == name and source in sources and medium in mediums:
            for k in parts:
                parts[k] += entry[k]
    if not parts["sessions"]:
        nothing = missing(UNAVAILABLE, "no_match")
        return {"sessions": nothing, "purchases": nothing, "purchase_revenue": nothing}
    return {
        "sessions": plus(*parts["sessions"]),
        "purchases": plus(*parts["purchases"]),
        "purchase_revenue": plus(*parts["revenue"]),
    }


def campaigns(
    session: Session, scope: Scope, first: date, last: date, fx: FxTable
) -> list[CampaignFigures]:
    accounts = {a.id: a for a in scope.ad_accounts}
    if not accounts:
        return []
    rows = session.execute(
        select(AdCampaign, AdBudget)
        .outerjoin(AdBudget, AdBudget.id == AdCampaign.budget_id)
        .where(AdCampaign.ad_account_id.in_(list(accounts)))
        .order_by(AdCampaign.name, AdCampaign.id)
    ).all()
    perf: dict[uuid.UUID, list[AdPerformanceDaily]] = defaultdict(list)
    for p in session.execute(
        select(AdPerformanceDaily).where(
            AdPerformanceDaily.ad_account_id.in_(list(accounts)),
            AdPerformanceDaily.level == "campaign",
            AdPerformanceDaily.campaign_id.is_not(None),
            AdPerformanceDaily.day.between(first, last),
        )
    ).scalars():
        assert p.campaign_id is not None
        perf[p.campaign_id].append(p)
    ga, ga_missing = _analytics_by_campaign(session, scope, first, last, fx)
    days = _days(first, last)
    found = []
    for campaign, budget in rows:
        account = accounts[campaign.ad_account_id]
        if not all(synced(account, d) for d in days):
            gap = missing(NOT_SYNCED, NOT_SYNCED)
            figures = dict.fromkeys(
                (
                    "spend",
                    "clicks",
                    "impressions",
                    "conversions",
                    "conversion_value",
                    "platform_roas",
                    "cost_per_click",
                    "cost_per_conversion",
                    "budget_use",
                ),
                gap,
            )
        else:
            own = perf.get(campaign.id, [])  # a read day without a row had no activity
            spend = plus(
                Figure(Decimal(0)),
                *(_money(fx, p.cost, account.currency, scope.currency, p.day) for p in own),
            )
            value = plus(
                Figure(Decimal(0)),
                *(
                    _money(fx, p.conversion_value, account.currency, scope.currency, p.day)
                    for p in own
                ),
            )
            clicks = plus(Figure(Decimal(0)), *(_count(p.clicks) for p in own))
            conversions = plus(Figure(Decimal(0)), *(_count(p.conversions) for p in own))
            native = plus(
                Figure(Decimal(0)),
                *(
                    Figure(p.cost) if p.cost is not None else missing(UNAVAILABLE, "not_provided")
                    for p in own
                ),
            )
            figures = {
                "spend": spend,
                "clicks": clicks,
                "impressions": plus(Figure(Decimal(0)), *(_count(p.impressions) for p in own)),
                "conversions": conversions,
                "conversion_value": value,
                "platform_roas": ratio(value, spend, "no_ad_spend"),
                "cost_per_click": ratio(spend, clicks, "no_clicks"),
                "cost_per_conversion": ratio(spend, conversions, "no_conversions"),
                "budget_use": _budget_use(native, budget, len(days)),
            }
        found.append(
            CampaignFigures(
                id=campaign.id,
                ad_account_id=campaign.ad_account_id,
                provider=account.provider,
                name=campaign.name,
                status=campaign.status,
                budget_period=budget.period if budget is not None else None,
                figures=figures,
                analytics=_match(ga, account.provider, campaign.name)
                if ga_missing is None
                else None,
                analytics_missing=ga_missing,
            )
        )
    return found


def _budget_use(spend: Figure, budget: AdBudget | None, days: int) -> Figure:
    """Spend (in the account's own currency) / (today's daily budget x days) (Q-6-11)."""
    if budget is None:
        return missing(UNAVAILABLE, "no_budget")
    if budget.period != "daily":
        return missing("unsupported", "not_a_daily_budget")
    if budget.shared:
        return missing("unsupported", "shared_budget")
    if budget.amount is None:
        return missing(UNAVAILABLE, "not_provided")
    return ratio(spend, Figure(budget.amount * days), "no_budget")


# ------------------------------------------------------------------ products
@dataclass(frozen=True)
class ProductFigures:
    product_id: uuid.UUID | None  # None: lines AdVegaX could not match to a product
    store_id: uuid.UUID
    title: str | None
    figures: dict[str, Figure]


def products(
    session: Session, scope: Scope, first: date, last: date, fx: FxTable
) -> tuple[list[ProductFigures], Figure | None, int]:
    """Products, most net sales first; why there are none (no store, a day not read); and how
    many sale lines in another currency were left out."""
    stores = list(scope.stores)
    if not stores:
        return [], missing(UNAVAILABLE, "no_store"), 0
    if not all(synced(s, d) for s in stores for d in _days(first, last)):
        return [], missing(NOT_SYNCED, NOT_SYNCED), 0
    found: list[ProductFigures] = []
    foreign = 0
    for store in stores:
        tz = ZoneInfo(store.timezone)
        by_product: dict[uuid.UUID | None, list[SaleRow]] = defaultdict(list)
        titles: dict[uuid.UUID | None, str | None] = {None: None}
        for row in session.execute(
            select(
                SalesEntry.happened_at,
                SalesEntry.action,
                SalesEntry.line_type,
                SalesEntry.amount,
                SalesEntry.discount_amount,
                SalesEntry.tax_amount,
                SalesEntry.quantity,
                OrderItem.unit_cost,
                Product.id,
                Product.title,
                Order.currency,
            )
            .join(
                Order,
                (Order.id == SalesEntry.order_id)
                & (Order.organization_id == SalesEntry.organization_id),
            )
            .outerjoin(
                OrderItem,
                (OrderItem.id == SalesEntry.order_item_id)
                & (OrderItem.organization_id == SalesEntry.organization_id),
            )
            .outerjoin(
                ProductVariant,
                (ProductVariant.id == OrderItem.variant_id)
                & (ProductVariant.organization_id == OrderItem.organization_id),
            )
            .outerjoin(
                Product,
                (Product.id == ProductVariant.product_id)
                & (Product.organization_id == ProductVariant.organization_id),
            )
            .where(
                SalesEntry.store_id == store.id,
                SalesEntry.line_type == "product",
                SalesEntry.happened_at >= datetime.combine(first, time.min, tz),
                SalesEntry.happened_at
                < datetime.combine(date.fromordinal(last.toordinal() + 1), time.min, tz),
                Order.excluded_reason.is_(None),
            )
        ):
            local = row.happened_at.astimezone(tz).date()
            if not first <= local <= last:
                continue
            if row.currency != store.currency:
                foreign += 1  # Q-2B-5: never summed with the store currency
                continue
            titles[row.id] = row.title
            by_product[row.id].append(
                SaleRow(
                    happened_at=row.happened_at,
                    action=row.action,
                    line_type=row.line_type,
                    amount=row.amount,
                    discount_amount=row.discount_amount,
                    tax_amount=row.tax_amount,
                    quantity=row.quantity,
                    unit_cost=row.unit_cost,
                )
            )
        for product_id, sales in by_product.items():
            days = compute_days(sales, (), tz)
            net, cost = [], []
            for day, c in days.items():
                net.append(_money(fx, c.net_sales, store.currency, scope.currency, day))
                cogs = (
                    _money(fx, c.cogs, store.currency, scope.currency, day)
                    if c.cogs is not None
                    else missing(UNAVAILABLE, "missing_product_costs")
                )
                cost.append(cogs)
            units = sum(
                (abs(s.quantity or 0) * (1 if s.action == "order" else -1))
                for s in sales
                if s.action in ("order", "return")
            )
            net_sales, product_cost = plus(*net), plus(*cost)
            gross = minus(net_sales, product_cost)
            found.append(
                ProductFigures(
                    product_id=product_id,
                    store_id=store.id,
                    title=titles.get(product_id),
                    figures={
                        "units": Figure(Decimal(units)),
                        "net_sales": net_sales,
                        "product_cost": product_cost,
                        "gross_profit": gross,
                        "gross_margin": ratio(gross, net_sales, "no_net_sales"),
                    },
                )
            )
    found.sort(key=lambda p: (-(p.figures["net_sales"].value or 0), p.title or "~"))
    return found, None, foreign
