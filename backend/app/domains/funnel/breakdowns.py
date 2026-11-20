"""The funnel by campaign and by landing page (Phase 7, task 7-06, PLAN §8, Q-7-6, Q-7-9).

**Campaigns:** each campaign's own funnel as its platform reports it (the campaign-level daily
rows), and Google Analytics' funnel for the campaign of **exactly the same name** (as Q-6-9:
Google Ads ↔ google / cpc; Meta ↔ facebook or instagram / paid or cpc). Visits that match no
campaign are **"Other traffic"**, so the campaigns' Google Analytics part plus Other traffic add
up to the website (the source view). Two campaigns of the same name and platform share one match
(``shared_match``): it is counted once.

**Landing pages:** Google Analytics' funnel for each page a visit started on (paths only), most
visits first.

Counts are events, not people (Q-7-5). Computed on read (Q-7-8).
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.advertising.models import AdCampaign, AdPerformanceDaily
from app.domains.analytics.models import AnalyticsDaily
from app.domains.funnel.engine import (
    GA_COLUMNS,
    GAP,
    PLATFORM_COLUMNS,
    StepFigure,
    platform_steps,
    step_rates,
    stored_count,
)
from app.domains.funnel.registry import CHANNEL_STAGES, CHANNEL_STEPS, PLATFORM_REPORTS
from app.domains.metrics.campaigns import GOOGLE_MATCH, META_MATCH
from app.domains.metrics.engine import UNAVAILABLE, Figure, Scope, missing, plus, synced

GA_KEYS = tuple(s.key for s in CHANNEL_STAGES)


def _days(first: date, last: date) -> list[date]:
    return [date.fromordinal(o) for o in range(first.toordinal(), last.toordinal() + 1)]


def _ga_stages(rows: list[AnalyticsDaily]) -> dict[str, Figure]:
    return {
        key: plus(Figure(Decimal(0)), *(stored_count(getattr(r, GA_COLUMNS[key])) for r in rows))
        for key in GA_KEYS
    }


def _ga_steps(stages: dict[str, Figure]) -> list[StepFigure]:
    return step_rates(CHANNEL_STEPS, stages, store_ok=True)


def _ga_ready(session: Session, scope: Scope, first: date, last: date) -> Figure | None:
    """Why there is no Google Analytics part, or None when every day was read — including
    the funnel figures (a property imported before Phase 7 is re-read once, Q-7-3)."""
    if not scope.properties:
        return missing(UNAVAILABLE, "no_analytics_property")
    if not all(synced(p, d) for p in scope.properties for d in _days(first, last)):
        return GAP
    not_reread = session.execute(
        select(AnalyticsDaily.id)
        .where(
            AnalyticsDaily.property_id.in_([p.id for p in scope.properties]),
            AnalyticsDaily.breakdown == "total",
            AnalyticsDaily.day.between(first, last),
            AnalyticsDaily.add_to_carts.is_(None),
        )
        .limit(1)
    ).first()
    return GAP if not_reread is not None else None


# ------------------------------------------------------------------ campaigns
@dataclass(frozen=True)
class CampaignFunnel:
    id: uuid.UUID
    ad_account_id: uuid.UUID
    provider: str
    name: str
    status: str
    stages: dict[str, Figure]
    steps: list[StepFigure]
    analytics: dict[str, Figure] | None
    analytics_steps: list[StepFigure]
    shared_match: bool


@dataclass(frozen=True)
class CampaignFunnels:
    items: list[CampaignFunnel]
    other_traffic: dict[str, Figure] | None
    other_traffic_steps: list[StepFigure]
    website: dict[str, Figure] | None  # the source view: campaigns + other traffic
    analytics_missing: Figure | None


def _matches(provider: str, name: str, source: str, medium: str, campaign: str) -> bool:
    sources, mediums = GOOGLE_MATCH if provider == "google_ads" else META_MATCH
    return campaign == name and source in sources and medium in mediums


def campaign_funnels(session: Session, scope: Scope, first: date, last: date) -> CampaignFunnels:
    accounts = {a.id: a for a in scope.ad_accounts}
    days = _days(first, last)
    campaigns = (
        list(
            session.execute(
                select(AdCampaign)
                .where(AdCampaign.ad_account_id.in_(list(accounts)))
                .order_by(AdCampaign.name, AdCampaign.id)
            ).scalars()
        )
        if accounts
        else []
    )
    perf: dict[uuid.UUID, list[AdPerformanceDaily]] = defaultdict(list)
    if accounts:
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

    why = _ga_ready(session, scope, first, last)
    source_rows: list[AnalyticsDaily] = []
    if why is None:
        source_rows = list(
            session.execute(
                select(AnalyticsDaily).where(
                    AnalyticsDaily.property_id.in_([p.id for p in scope.properties]),
                    AnalyticsDaily.breakdown == "source",
                    AnalyticsDaily.day.between(first, last),
                )
            ).scalars()
        )

    def key(row: AnalyticsDaily) -> tuple[str, str, str]:
        return (
            (row.traffic_source or "").lower(),
            (row.traffic_medium or "").lower(),
            row.campaign or "",
        )

    named = Counter((c.name, accounts[c.ad_account_id].provider) for c in campaigns)
    matched: set[int] = set()
    items: list[CampaignFunnel] = []
    for c in campaigns:
        account = accounts[c.ad_account_id]
        reported = PLATFORM_REPORTS.get(account.provider, ("impressions", "clicks", "purchases"))
        if not all(synced(account, d) for d in days):
            stages = dict.fromkeys(reported, GAP)
        else:
            own = perf.get(c.id, [])  # a read day without a row had no activity
            stages = {
                k: plus(
                    Figure(Decimal(0)),
                    *(stored_count(getattr(p, PLATFORM_COLUMNS[k])) for p in own),
                )
                for k in reported
            }
        analytics: dict[str, Figure] | None = None
        analytics_steps: list[StepFigure] = []
        if why is None:
            mine = [r for r in source_rows if _matches(account.provider, c.name, *key(r))]
            matched.update(id(r) for r in mine)
            if mine:
                analytics = _ga_stages(mine)
            else:
                nothing = missing(UNAVAILABLE, "no_match")
                analytics = dict.fromkeys(GA_KEYS, nothing)
            analytics_steps = _ga_steps(analytics)
        items.append(
            CampaignFunnel(
                id=c.id,
                ad_account_id=c.ad_account_id,
                provider=account.provider,
                name=c.name,
                status=c.status,
                stages=stages,
                steps=step_rates(platform_steps(account.provider), stages, store_ok=True),
                analytics=analytics,
                analytics_steps=analytics_steps,
                shared_match=named[(c.name, account.provider)] > 1,
            )
        )
    if why is not None:
        return CampaignFunnels(items, None, [], None, why)
    other = _ga_stages([r for r in source_rows if id(r) not in matched])
    return CampaignFunnels(items, other, _ga_steps(other), _ga_stages(source_rows), None)


# ------------------------------------------------------------------ landing pages
@dataclass(frozen=True)
class LandingPageFunnel:
    landing_page: str
    stages: dict[str, Figure]
    steps: list[StepFigure]


def landing_page_funnels(
    session: Session, scope: Scope, first: date, last: date, limit: int
) -> tuple[list[LandingPageFunnel], int, Figure | None]:
    """The largest landing pages (most visits first), how many there are, or why none."""
    why = _ga_ready(session, scope, first, last)
    if why is not None:
        return [], 0, why
    pages: dict[str, list[AnalyticsDaily]] = defaultdict(list)
    for row in session.execute(
        select(AnalyticsDaily).where(
            AnalyticsDaily.property_id.in_([p.id for p in scope.properties]),
            AnalyticsDaily.breakdown == "landing_page",
            AnalyticsDaily.day.between(first, last),
        )
    ).scalars():
        pages[row.landing_page or row.dimension_key].append(row)
    found = [
        LandingPageFunnel(page, stages, _ga_steps(stages))
        for page, rows in pages.items()
        for stages in (_ga_stages(rows),)
    ]
    found.sort(key=lambda f: (-(f.stages["landing_page_views"].value or 0), f.landing_page))
    return found[:limit], len(found), None
