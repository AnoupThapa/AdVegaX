"""What the builder needs about a draft: its strategy, creative, product, store and ad account
(Phase 10B). Read under the organization's context; nothing here calls a platform."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.domains.actions.facts import budget_bounds, org_settings, volume_used, write_access_problem
from app.domains.advertising.models import AdAccount, AdPerformanceDaily
from app.domains.ai.models import CampaignStrategy
from app.domains.builder.checks import DraftFacts
from app.domains.builder.models import CampaignDraft
from app.domains.commerce.models import Product, Store
from app.domains.creative.models import Creative, CreativeAsset, CreativeRules, CreativeSet
from app.domains.creative.policy import BASE_PROHIBITED
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.providers.base.changes import CampaignBuild, CampaignBuilder, Keyword, campaign_builder
from app.providers.base.registry import UnknownProvider
from app.providers.base.types import AdAccountRef
from app.runtime import Runtime


@dataclass
class DraftContext:
    draft: CampaignDraft
    strategy: CampaignStrategy
    creative: Creative
    creative_strategy: uuid.UUID
    asset_key: str | None
    product: Product | None
    store: Store | None
    account: AdAccount
    resource: ExternalResource
    connection: ExternalConnection
    linked: bool

    @property
    def ref(self) -> AdAccountRef:
        return AdAccountRef(self.account.external_account_id, self.resource.access_hint)


def builder_for(rt: Runtime, provider: str) -> CampaignBuilder | None:
    try:
        return campaign_builder(rt.providers.get(provider))
    except UnknownProvider:
        return None


def account_context(
    session: Session, org_id: uuid.UUID, ad_account_id: uuid.UUID
) -> tuple[AdAccount, ExternalResource, ExternalConnection, bool]:
    row = session.execute(
        select(AdAccount, ExternalResource, ExternalConnection)
        .join(ExternalResource, ExternalResource.id == AdAccount.external_resource_id)
        .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
        .where(AdAccount.organization_id == org_id, AdAccount.id == ad_account_id)
    ).one_or_none()
    if row is None:
        raise NotFound()
    account, resource, connection = row
    linked = (
        session.execute(
            select(OrganizationResourceLink.id).where(
                OrganizationResourceLink.external_resource_id == resource.id,
                OrganizationResourceLink.status == "active",
            )
        ).first()
        is not None
    )
    return account, resource, connection, linked


def load(
    session: Session, org_id: uuid.UUID, draft_id: uuid.UUID, *, lock: bool = False
) -> DraftContext:
    query = select(CampaignDraft).where(
        CampaignDraft.organization_id == org_id, CampaignDraft.id == draft_id
    )
    if lock:
        query = query.with_for_update()
    draft = session.execute(query).scalar_one_or_none()
    if draft is None:
        raise NotFound()
    strategy = session.get(CampaignStrategy, draft.strategy_id)
    found = session.execute(
        select(Creative, CreativeSet.strategy_id)
        .join(
            CreativeSet,
            (CreativeSet.id == Creative.set_id)
            & (CreativeSet.organization_id == Creative.organization_id),
        )
        .where(Creative.organization_id == org_id, Creative.id == draft.creative_id)
    ).one_or_none()
    if strategy is None or found is None:
        raise NotFound()
    creative, creative_strategy = found
    asset_key = None
    if creative.asset_id is not None:
        asset = session.get(CreativeAsset, creative.asset_id)
        if asset is not None and asset.organization_id == org_id and asset.status == "active":
            asset_key = asset.storage_key
    product = session.get(Product, strategy.product_id)
    store = session.get(Store, product.store_id) if product is not None else None
    account, resource, connection, linked = account_context(session, org_id, draft.ad_account_id)
    return DraftContext(
        draft=draft,
        strategy=strategy,
        creative=creative,
        creative_strategy=creative_strategy,
        asset_key=asset_key,
        product=product,
        store=store,
        account=account,
        resource=resource,
        connection=connection,
        linked=linked,
    )


def store_hosts(session: Session, org_id: uuid.UUID, store: Store | None) -> list[str]:
    hosts = list(org_settings(session, org_id).landing_domains or [])
    if store is not None:
        hosts.append(store.domain)
        if store.site_url:
            from urllib.parse import urlsplit

            host = urlsplit(store.site_url).hostname
            if host:
                hosts.append(host)
    return hosts


def landing_default(store: Store | None, product: Product | None) -> str:
    """The product's page on the store (Shopify ``/products/<handle>``; WooCommerce
    ``/product/<handle>``)."""
    if store is None:
        return ""
    base = (store.site_url or f"https://{store.domain}").rstrip("/")
    if product is None or not product.handle:
        return base
    path = "products" if store.provider == "shopify" else "product"
    return f"{base}/{path}/{product.handle}"


def has_conversions(rt: Runtime, session: Session, account: AdAccount) -> bool:
    """Whether the account reported conversions in the last 30 days (bidding, Q-10B-4)."""
    first = rt.clock.now().date() - rt.settings.ADS_NIGHTLY_WINDOW  # 30 days
    total = session.execute(
        select(func.coalesce(func.sum(AdPerformanceDaily.conversions), 0)).where(
            AdPerformanceDaily.organization_id == account.organization_id,
            AdPerformanceDaily.ad_account_id == account.id,
            AdPerformanceDaily.level == "account",
            AdPerformanceDaily.day >= first,
        )
    ).scalar_one()
    return Decimal(total or 0) > 0


def prohibited(session: Session, org_id: uuid.UUID) -> list[str]:
    rules = session.get(CreativeRules, org_id)
    own = [str(t).lower() for t in rules.prohibited_terms] if rules else []
    return [*BASE_PROHIBITED, *own]


def resource_reason(rt: Runtime, c: DraftContext) -> str | None:
    builder = builder_for(rt, c.account.provider)
    if builder is None:
        return "platform_cannot_change"
    if not c.linked:
        return "account_not_linked"
    if c.connection.status != "active":
        return "connection_inactive"
    if c.account.status != "active" or c.account.platform_status != "active":
        return "account_not_active"
    return write_access_problem(c.connection, builder)


def facts(
    rt: Runtime, session: Session, c: DraftContext, *, exclude: uuid.UUID | None = None
) -> DraftFacts:
    d = c.draft
    minimum, maximum, maximum_set = budget_bounds(
        rt, session, d.organization_id, c.account.provider, c.account.currency
    )
    platforms = [p.get("platform") for p in c.strategy.strategy.get("platforms", [])]
    return DraftFacts(
        platform=d.platform,
        name=d.name,
        daily_budget=Decimal(d.daily_budget),
        currency=d.currency,
        locations=list(d.locations),
        age_min=d.age_min,
        age_max=d.age_max,
        keywords=list(d.keywords),
        landing_url=d.landing_url,
        meta_page_id=d.meta_page_id,
        meta_pixel_id=d.meta_pixel_id,
        declared=d.declaration_confirmed_at is not None,
        creative_status=c.creative.status,
        creative_platform=c.creative.platform,
        creative_from_strategy=c.creative_strategy == d.strategy_id,
        strategy_status=c.strategy.status,
        strategy_platforms=[p for p in platforms if isinstance(p, str)],
        meta_image=c.asset_key is not None,
        store_hosts=store_hosts(session, d.organization_id, c.store),
        prohibited=prohibited(session, d.organization_id),
        minimum=minimum,
        maximum=maximum,
        maximum_set=maximum_set,
        volume_used=volume_used(rt, session, d.organization_id, c.account.id, exclude),
        volume_limit=rt.settings.ACTIONS_DAILY_LIMIT_PER_ACCOUNT,
        resource_reason=resource_reason(rt, c),
    )


def build_of(c: DraftContext, *, image: bytes, maximize_conversions: bool) -> CampaignBuild:
    d, content = c.draft, dict(c.creative.content)

    def first(key: str) -> str:
        return str((content.get(key) or [""])[0])

    return CampaignBuild(
        reference=d.reference,
        name=d.name,
        daily_budget=Decimal(d.daily_budget),
        locations=tuple(d.locations),
        landing_url=d.landing_url,
        keywords=tuple(Keyword(" ".join(k["text"].split()), k["match"]) for k in d.keywords),
        headlines=tuple(content.get("headlines") or ()) if d.platform == "google_ads" else (),
        descriptions=tuple(content.get("descriptions") or ()) if d.platform == "google_ads" else (),
        path1=str(content.get("path1") or ""),
        path2=str(content.get("path2") or ""),
        maximize_conversions=maximize_conversions,
        primary_text=str(first("primary_texts")),
        headline=str(first("headlines")) if d.platform == "meta_ads" else "",
        description=str(first("descriptions")) if d.platform == "meta_ads" else "",
        call_to_action=str(content.get("call_to_action") or ""),
        image=image,
        page_id=d.meta_page_id or "",
        pixel_id=d.meta_pixel_id,
        age_min=d.age_min,
        age_max=d.age_max,
    )


def summary(d: CampaignDraft) -> dict[str, Any]:
    """What the audit keeps of a draft: never the ad text."""
    return {
        "platform": d.platform,
        "version": d.version,
        "status": d.status,
        "daily_budget": str(d.daily_budget),
        "currency": d.currency,
        "locations": list(d.locations),
        "keywords": len(d.keywords),
        "reference": d.reference,
    }
