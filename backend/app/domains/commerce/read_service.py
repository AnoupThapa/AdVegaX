"""Read side of commerce: stores, products, daily figures, "Sync now" (task 2A-09, PLAN §11).

Every query runs in the caller's tenant context (RLS) **and** filters by organization
explicitly; a store, product or figure of another organization is answered with 404.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import date, tzinfo
from decimal import Decimal

from sqlalchemy import or_, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security.throttle import Limit
from app.domains.commerce.importer import SyncMode, chain_running, start_sync
from app.domains.commerce.models import (
    PRODUCT_STATUSES,
    CommerceSyncState,
    Product,
    ProductCostHistory,
    ProductVariant,
    Store,
)
from app.domains.commerce.schemas import (
    CostOut,
    DailyMetricsOut,
    DayOut,
    FigureOut,
    HealthOut,
    InventoryOut,
    ProductOut,
    ProductPage,
    ResyncOut,
    StoreOut,
    SyncOut,
    TotalsOut,
    VariantOut,
)
from app.domains.finance.definitions import (
    DEFINITION_VERSION,
    DayComponents,
    Figure,
    local_day,
    minor_units,
    summarize,
)
from app.domains.finance.models import FinancialDaily
from app.domains.finance.service import store_zone
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

HOUR = 3600
MAX_PAGE_SIZE = 100


class SyncInProgress(Conflict):
    code = "SYNC_IN_PROGRESS"
    message = "This store is already being synchronized."


class StoreNotSyncing(Conflict):
    code = "STORE_NOT_SYNCING"
    message = "This store is not linked to an active connection."


def _figure(figure: Figure) -> FigureOut:
    return FigureOut(value=figure.value, availability=figure.availability, reason=figure.reason)


NOT_SYNCED = FigureOut(value=None, availability="not_synchronized", reason="not_synchronized")


@dataclass(frozen=True)
class _StoreRow:
    store: Store
    state: CommerceSyncState | None
    connection: ExternalConnection
    linked: bool


class CommerceReadService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ stores
    def _rows(
        self, session: Session, ctx: TenantContext, store_id: uuid.UUID | None
    ) -> list[_StoreRow]:
        active_link = (
            select(OrganizationResourceLink.id)
            .where(
                OrganizationResourceLink.external_resource_id == Store.external_resource_id,
                OrganizationResourceLink.status == "active",
            )
            .exists()
        )
        stmt = (
            select(Store, CommerceSyncState, ExternalConnection, active_link)
            .outerjoin(CommerceSyncState, CommerceSyncState.store_id == Store.id)
            .join(ExternalResource, ExternalResource.id == Store.external_resource_id)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .where(Store.organization_id == ctx.organization_id)
            .order_by(Store.created_at)
        )
        if store_id is not None:
            stmt = stmt.where(Store.id == store_id)
        return [_StoreRow(s, st, c, bool(linked)) for s, st, c, linked in session.execute(stmt)]

    def _store_out(self, row: _StoreRow) -> StoreOut:
        store, state = row.store, row.state
        running = state is not None and chain_running(self.rt, state)
        return StoreOut(
            id=store.id,
            resource_id=store.external_resource_id,
            provider=store.provider,
            domain=store.domain,
            name=store.name,
            currency=store.currency,
            currency_minor_units=minor_units(store.currency),
            timezone=store.timezone,
            status=store.status,
            linked=row.linked,
            connection_status=row.connection.status,
            history_from=store.history_from,
            first_import_completed_at=store.first_import_completed_at,
            sync=SyncOut(
                running=running,
                mode=state.sync_mode if state is not None and running else None,
                progress=(
                    state.import_progress
                    if state is not None and store.first_import_completed_at is None
                    else None
                ),
                last_reconciled_at=state.last_reconciled_at if state else None,
                last_deep_reconciled_at=state.last_deep_reconciled_at if state else None,
                last_error_code=state.last_error_code if state else None,
                last_error_at=state.last_error_at if state else None,
            ),
            created_at=store.created_at,
            site_url=store.site_url,
            platform_version=store.platform_version,
            health=(
                HealthOut(code=store.health_code, checked_at=store.health_checked_at)
                if store.health_checked_at is not None
                else None
            ),
            counted_statuses=list(store.counted_statuses) if store.counted_statuses else None,
        )

    def list_stores(self, ctx: TenantContext) -> list[StoreOut]:
        authorize(ctx, Permission.STORES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return [self._store_out(row) for row in self._rows(session, ctx, None)]

    def _one(self, session: Session, ctx: TenantContext, store_id: uuid.UUID) -> _StoreRow:
        rows = self._rows(session, ctx, store_id)
        if not rows:
            raise NotFound()
        return rows[0]

    def get_store(self, ctx: TenantContext, store_id: uuid.UUID) -> StoreOut:
        authorize(ctx, Permission.STORES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._store_out(self._one(session, ctx, store_id))

    # ------------------------------------------------------------------ "Sync now"
    def resync(self, ctx: TenantContext, store_id: uuid.UUID) -> ResyncOut:
        authorize(ctx, Permission.STORES_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            row = self._one(session, ctx, store_id)
            if not row.linked or row.connection.status != "active":
                raise StoreNotSyncing()
            state = session.get(CommerceSyncState, store_id, with_for_update=True)
            if row.store.first_import_completed_at is None or (
                state is not None and chain_running(self.rt, state)
            ):
                raise SyncInProgress()
            # Each run is a full deep check: limited per store (not per person).
            self.rt.throttler.hit(
                Limit("store_resync", self.rt.settings.THROTTLE_STORE_RESYNC_PER_HOUR, HOUR),
                str(store_id),
            )
            job_id = start_sync(
                session, self.rt, row.store, SyncMode.DEEP, requested_by=ctx.user_id
            )
            return ResyncOut(store_id=store_id, job_id=job_id, mode=SyncMode.DEEP.value)

    # ------------------------------------------------------------------ products
    def list_products(
        self,
        ctx: TenantContext,
        store_id: uuid.UUID,
        *,
        cursor: str | None,
        page_size: int,
        search: str | None,
        status: str | None,
    ) -> ProductPage:
        authorize(ctx, Permission.STORES_VIEW)
        if status is not None and status not in PRODUCT_STATUSES:
            raise ValidationFailed(details=[{"field": "status", "issue": "unknown_status"}])
        after = _decode_cursor(cursor) if cursor else None
        size = max(1, min(page_size, MAX_PAGE_SIZE))
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            store = self._one(session, ctx, store_id).store
            stmt = select(Product).where(
                Product.organization_id == ctx.organization_id, Product.store_id == store.id
            )
            stmt = stmt.where(Product.status == status if status else Product.status != "deleted")
            if search:
                pattern = f"%{_escape_like(search.strip()[:100])}%"
                sku_match = (
                    select(ProductVariant.id)
                    .where(
                        ProductVariant.product_id == Product.id,
                        ProductVariant.sku.ilike(pattern, escape="\\"),
                    )
                    .exists()
                )
                stmt = stmt.where(or_(Product.title.ilike(pattern, escape="\\"), sku_match))
            if after is not None:
                stmt = stmt.where(tuple_(Product.title, Product.id) > tuple_(*after))
            products = list(
                session.execute(stmt.order_by(Product.title, Product.id).limit(size + 1)).scalars()
            )
            more = len(products) > size
            products = products[:size]
            variants = self._variants(session, [p.id for p in products])
            items = [self._product_out(p, variants.get(p.id, [])) for p in products]
        next_cursor = _encode_cursor(products[-1].title, products[-1].id) if more else None
        return ProductPage(items=items, next_cursor=next_cursor)

    def get_product(
        self, ctx: TenantContext, store_id: uuid.UUID, product_id: uuid.UUID
    ) -> ProductOut:
        authorize(ctx, Permission.STORES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            store = self._one(session, ctx, store_id).store
            product = session.execute(
                select(Product).where(
                    Product.id == product_id,
                    Product.store_id == store.id,
                    Product.organization_id == ctx.organization_id,
                )
            ).scalar_one_or_none()
            if product is None:
                raise NotFound()
            return self._product_out(
                product, self._variants(session, [product.id]).get(product.id, [])
            )

    def _variants(
        self, session: Session, product_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[VariantOut]]:
        if not product_ids:
            return {}
        rows = list(
            session.execute(
                select(ProductVariant)
                .where(ProductVariant.product_id.in_(product_ids))
                .order_by(ProductVariant.title, ProductVariant.id)
            ).scalars()
        )
        latest = (
            {
                c.variant_id: c
                for c in session.execute(
                    select(ProductCostHistory)
                    .where(ProductCostHistory.variant_id.in_([v.id for v in rows]))
                    .ext(distinct_on(ProductCostHistory.variant_id))
                    .order_by(
                        ProductCostHistory.variant_id, ProductCostHistory.effective_from.desc()
                    )
                ).scalars()
            }
            if rows
            else {}
        )
        out: dict[uuid.UUID, list[VariantOut]] = {}
        for v in rows:
            out.setdefault(v.product_id, []).append(_variant_out(v, latest.get(v.id)))
        return out

    @staticmethod
    def _product_out(product: Product, variants: list[VariantOut]) -> ProductOut:
        return ProductOut(
            id=product.id,
            external_id=product.external_product_id,
            title=product.title,
            handle=product.handle,
            product_type=product.product_type,
            vendor=product.vendor,
            status=product.status,
            updated_at=product.external_updated_at,
            variants=variants,
        )

    # ------------------------------------------------------------------ daily figures
    def daily_metrics(
        self,
        ctx: TenantContext,
        store_id: uuid.UUID,
        *,
        from_day: date | None,
        to_day: date | None,
    ) -> DailyMetricsOut:
        authorize(ctx, Permission.STORES_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            store = self._one(session, ctx, store_id).store
            tz = store_zone(store)
            today = local_day(self.rt.clock.now(), tz)
            last = to_day or today
            first = from_day or date.fromordinal(last.toordinal() - 29)
            span = last.toordinal() - first.toordinal() + 1
            if span < 1 or span > self.rt.settings.METRICS_MAX_DAYS:
                raise ValidationFailed(details=[{"field": "from", "issue": "invalid_range"}])
            rows = {
                r.day: r
                for r in session.execute(
                    select(FinancialDaily).where(
                        FinancialDaily.organization_id == ctx.organization_id,
                        FinancialDaily.store_id == store.id,
                        FinancialDaily.definition_version == DEFINITION_VERSION,
                        FinancialDaily.day >= first,
                        FinancialDaily.day <= last,
                    )
                ).scalars()
            }
            synced_from = _synced_from(store, tz)
            days: list[DayOut] = []
            components: list[DayComponents] = []
            all_synced = True
            for ordinal in range(first.toordinal(), last.toordinal() + 1):
                day = date.fromordinal(ordinal)
                if synced_from is None or day < synced_from or day > today:
                    all_synced = False
                    days.append(_unsynced_day(day))
                    continue
                c = _components(rows.get(day))
                components.append(c)
                days.append(_day_out(day, c))
            totals = _totals(components) if all_synced else _unsynced_totals()
            return DailyMetricsOut(
                store_id=store.id,
                definition_version=DEFINITION_VERSION,
                currency=store.currency,
                currency_minor_units=minor_units(store.currency),
                timezone=str(tz),
                from_day=first,
                to_day=last,
                synced_from=synced_from,
                days=days,
                totals=totals,
            )


# ---------------------------------------------------------------------- helpers
def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _encode_cursor(title: str, product_id: uuid.UUID) -> str:
    raw = json.dumps([title, str(product_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        title, product_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return str(title), uuid.UUID(str(product_id))
    except (ValueError, TypeError, binascii.Error):
        raise ValidationFailed(details=[{"field": "cursor", "issue": "invalid"}]) from None


def _variant_out(v: ProductVariant, cost: ProductCostHistory | None) -> VariantOut:
    if v.inventory_tracked is None:
        inventory = InventoryOut(
            availability="not_synchronized", tracked=None, available=None, synced_at=None
        )
    elif not v.inventory_tracked:
        inventory = InventoryOut(
            availability="unavailable",
            tracked=False,
            available=None,
            synced_at=v.inventory_synced_at,
        )
    else:
        inventory = InventoryOut(
            availability="available" if v.inventory_available is not None else "unavailable",
            tracked=True,
            available=v.inventory_available,
            synced_at=v.inventory_synced_at,
        )
    if cost is None:
        cost_out = CostOut(
            availability="unavailable",
            unit_cost=None,
            source=None,
            effective_from=None,
            reason="no_cost_from_platform",
        )
    elif cost.unit_cost is None:
        cost_out = CostOut(
            availability="unavailable",
            unit_cost=None,
            source=cost.source,
            effective_from=cost.effective_from,
            reason="cost_removed",
        )
    else:
        cost_out = CostOut(
            availability="available",
            unit_cost=cost.unit_cost,
            source=cost.source,
            effective_from=cost.effective_from,
        )
    return VariantOut(
        id=v.id,
        external_id=v.external_variant_id,
        title=v.title,
        sku=v.sku,
        price=v.price,
        deleted=v.deleted,
        inventory=inventory,
        cost=cost_out,
    )


def _synced_from(store: Store, tz: tzinfo) -> date | None:
    """First store-local day with complete data: the day after the history start (that day
    itself is only partly covered), once the first import has finished."""
    if store.first_import_completed_at is None or store.history_from is None:
        return None
    start = store.history_from.astimezone(tz)
    return date.fromordinal(start.date().toordinal() + 1)


def _components(row: FinancialDaily | None) -> DayComponents:
    if row is None:
        return DayComponents()  # synced day without activity: real zeros
    return DayComponents(
        gross_sales=row.gross_sales,
        discounts=row.discounts,
        sales_reversals=row.sales_reversals,
        shipping=row.shipping,
        taxes=row.taxes,
        duties=row.duties,
        fees=row.fees,
        orders_count=row.orders_count,
        known_cogs=row.cogs if row.cogs is not None else Decimal(0),
        costed_net_sales=row.costed_net_sales,
        uncosted_lines=row.uncosted_lines,
    )


def _day_out(day: date, c: DayComponents) -> DayOut:
    s = summarize([c])
    return DayOut(
        day=day,
        availability="available",
        gross_sales=s.gross_sales,
        discounts=s.discounts,
        sales_reversals=s.sales_reversals,
        net_sales=s.net_sales,
        shipping=s.shipping,
        taxes=s.taxes,
        duties=s.duties,
        fees=s.fees,
        total_sales=s.total_sales,
        orders_count=s.orders_count,
        cogs=_figure(s.cogs),
        gross_profit=_figure(s.gross_profit),
        cost_coverage=_figure(s.cost_coverage),
    )


def _unsynced_day(day: date) -> DayOut:
    return DayOut(
        day=day,
        availability="not_synchronized",
        gross_sales=None,
        discounts=None,
        sales_reversals=None,
        net_sales=None,
        shipping=None,
        taxes=None,
        duties=None,
        fees=None,
        total_sales=None,
        orders_count=None,
        cogs=NOT_SYNCED,
        gross_profit=NOT_SYNCED,
        cost_coverage=NOT_SYNCED,
    )


def _totals(components: list[DayComponents]) -> TotalsOut:
    s = summarize(components)
    return TotalsOut(
        availability="available",
        gross_sales=s.gross_sales,
        discounts=s.discounts,
        sales_reversals=s.sales_reversals,
        net_sales=s.net_sales,
        shipping=s.shipping,
        taxes=s.taxes,
        duties=s.duties,
        fees=s.fees,
        total_sales=s.total_sales,
        orders_count=s.orders_count,
        cogs=_figure(s.cogs),
        gross_profit=_figure(s.gross_profit),
        gross_margin=_figure(s.gross_margin),
        cost_coverage=_figure(s.cost_coverage),
        shipping_cost=_figure(s.shipping_cost),
        payment_fees=_figure(s.payment_fees),
        new_vs_returning=_figure(s.new_vs_returning),
    )


def _unsynced_totals() -> TotalsOut:
    """Part of the period has no data yet: totals would understate it, so none are given."""
    return TotalsOut(
        availability="not_synchronized",
        gross_sales=None,
        discounts=None,
        sales_reversals=None,
        net_sales=None,
        shipping=None,
        taxes=None,
        duties=None,
        fees=None,
        total_sales=None,
        orders_count=None,
        cogs=NOT_SYNCED,
        gross_profit=NOT_SYNCED,
        gross_margin=NOT_SYNCED,
        cost_coverage=NOT_SYNCED,
        shipping_cost=NOT_SYNCED,
        payment_fees=NOT_SYNCED,
        new_vs_returning=NOT_SYNCED,
    )
