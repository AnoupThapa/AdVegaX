"""Initial store import through platform bulk exports (task 2A-06, PHASE_02A_PLAN §9).

Linking a store resource of a commerce platform creates its ``stores`` row and starts the
import. The import is a chain of short jobs (``commerce.import_step``), one step each:

1. start the catalogue export (products → variants, inventory, unit cost);
2. poll until it finishes (a new step every ``COMMERCE_BULK_POLL_INTERVAL``), then stream the
   file line by line and upsert in batches;
3. the same for orders since ``history_from`` (lines, sales agreements, refunds);
4. resolve links between rows that arrived out of order, mark the store active.

Safety: one step at a time per store (Redis lock), and ``commerce_sync_state.import_job_id``
names the only step allowed to continue, so a duplicated job message cannot start a second
chain. Upserts are idempotent and never let an older platform version overwrite a newer one.
Unknown values stay NULL (never 0); costs are recorded as an import-time snapshot because
Shopify has no cost history (orders imported from before it are marked ``import_time``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import Table, select, text
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from app.domains.audit.service import Actor, record_audit
from app.domains.commerce.models import (
    CommerceSyncState,
    Order,
    OrderItem,
    Product,
    ProductCostHistory,
    ProductVariant,
    Refund,
    SalesEntry,
    Store,
)
from app.domains.integrations.jobs import call_provider
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.integrations.tokens import AccountBusy, account_lock, usable_secrets
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError, create_job
from app.providers.base.capabilities import Capability
from app.providers.base.errors import ProviderError
from app.providers.base.interfaces import CommerceProvider, PlatformProvider
from app.providers.base.types import (
    BulkKind,
    BulkStatus,
    CommerceOrderLineRecord,
    CommerceOrderRecord,
    CommerceProductRecord,
    CommerceRecord,
    CommerceRefundRecord,
    CommerceSaleRecord,
    CommerceVariantRecord,
    ResourceKind,
)
from app.providers.http.client import DownloadExpiredError
from app.runtime import Runtime

logger = logging.getLogger("advegax.commerce.import")

JOB_IMPORT_STEP = "commerce.import_step"
WORKER = Actor("worker", None)
IMPORT_LOCK_TTL_SECONDS = 2 * 3600  # covers the longest download (OUTBOUND_DOWNLOAD_TIMEOUT)
PROGRESS_AFTER_CATALOGUE = 40


def commerce_provider(provider: PlatformProvider) -> CommerceProvider | None:
    """The provider as a commerce importer, if it declares ``BULK_IMPORT``."""
    if provider.capabilities.supports(Capability.BULK_IMPORT) and isinstance(
        provider, CommerceProvider
    ):
        return provider
    return None


# ------------------------------------------------------------------ store lifecycle
def on_store_linked(
    session: Session,
    rt: Runtime,
    *,
    resource: ExternalResource,
    connection: ExternalConnection,
    user_id: uuid.UUID | None,
) -> Store | None:
    """Called inside the link transaction. Creates the store (first link) and starts the
    initial import if it never completed. Returns ``None`` for non-commerce resources."""
    provider = commerce_provider(rt.providers.get(connection.provider))
    if provider is None or resource.kind != ResourceKind.STORE.value:
        return None
    if resource.currency is None or resource.timezone is None:
        return None  # discovery found no currency/time zone: nothing can be reported correctly
    org_id = resource.organization_id
    store = session.execute(
        select(Store).where(Store.external_resource_id == resource.id)
    ).scalar_one_or_none()
    now = rt.clock.now()
    if store is None:
        window = rt.settings.COMMERCE_HISTORY_WINDOW
        limit = provider.history_limit(tuple(connection.granted_scopes or ()))
        if limit is not None:
            window = min(window, limit)
        store = Store(
            organization_id=org_id,
            external_resource_id=resource.id,
            provider=connection.provider,
            external_store_id=resource.external_id,
            domain=connection.external_account_id or resource.external_id,
            name=resource.display_name,
            currency=resource.currency,
            timezone=resource.timezone,
            status="importing",
            history_from=now - window,
        )
        session.add(store)
        session.flush()
        session.add(CommerceSyncState(store_id=store.id, organization_id=org_id))
        session.flush()
    if store.first_import_completed_at is None:
        start_import(session, rt, store, requested_by=user_id)
    return store


def start_import(
    session: Session, rt: Runtime, store: Store, *, requested_by: uuid.UUID | None
) -> uuid.UUID:
    """(Re)start the import chain from the catalogue step."""
    state = session.get(CommerceSyncState, store.id, with_for_update=True)
    if state is None:
        state = CommerceSyncState(store_id=store.id, organization_id=store.organization_id)
        session.add(state)
    store.status = "importing"
    state.bulk_operation_id, state.bulk_operation_kind = None, BulkKind.CATALOGUE.value
    state.import_progress, state.last_error_code, state.last_error_at = 0, None, None
    job = _schedule(session, rt, store, state, delay=0, requested_by=requested_by)
    record_audit(
        session,
        organization_id=store.organization_id,
        actor=Actor.user(requested_by) if requested_by else WORKER,
        action="store.import_started",
        resource_type="store",
        resource_id=store.id,
        metadata={
            "job_id": str(job),
            "history_from": store.history_from.isoformat() if store.history_from else None,
        },
    )
    return job


def _schedule(
    session: Session,
    rt: Runtime,
    store: Store,
    state: CommerceSyncState,
    *,
    delay: int,
    requested_by: uuid.UUID | None = None,
) -> uuid.UUID:
    job = create_job(
        session,
        rt,
        organization_id=store.organization_id,
        job_type=JOB_IMPORT_STEP,
        subject_type="store",
        subject_id=store.id,
        requested_by=requested_by,
        delay_seconds=delay,
    )
    state.import_job_id = job.id
    state.updated_at = rt.clock.now()
    return job.id


# ------------------------------------------------------------------ the step
@dataclass(frozen=True)
class _Context:
    org_id: uuid.UUID
    store_id: uuid.UUID
    connection_id: uuid.UUID
    currency: str
    history_from: datetime | None
    kind: BulkKind
    operation_id: str | None
    first_import: bool


def import_step(rt: Runtime, job: ClaimedJob) -> None:
    if job.organization_id is None or job.subject_id is None:
        raise JobSubjectGoneError()
    org_id, store_id = job.organization_id, uuid.UUID(job.subject_id)
    try:
        with account_lock(
            rt.redis,
            f"import-lock:{store_id}",
            wait_seconds=0,
            ttl_seconds=IMPORT_LOCK_TTL_SECONDS,
        ):
            next_delay = _step(rt, job, org_id, store_id)
    except AccountBusy:
        logger.info("import_step_busy", extra={"store_id": str(store_id)})
        return
    if next_delay is not None:
        with rt.db.transaction(org_id=org_id) as session:
            store = session.get(Store, store_id)
            state = session.get(CommerceSyncState, store_id, with_for_update=True)
            if store is not None and state is not None and state.import_job_id == job.id:
                _schedule(session, rt, store, state, delay=next_delay)


def _load(rt: Runtime, job: ClaimedJob, org_id: uuid.UUID, store_id: uuid.UUID):  # type: ignore[no-untyped-def]
    with rt.db.transaction(org_id=org_id) as session:
        row = session.execute(
            select(Store, CommerceSyncState, ExternalConnection)
            .join(CommerceSyncState, CommerceSyncState.store_id == Store.id)
            .join(ExternalResource, ExternalResource.id == Store.external_resource_id)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .where(Store.id == store_id, Store.organization_id == org_id)
        ).one_or_none()
        if row is None:
            raise JobSubjectGoneError()
        store, state, connection = row
        if state.import_job_id != job.id:
            return None, None  # a newer step owns the chain
        linked = session.execute(
            select(OrganizationResourceLink.id).where(
                OrganizationResourceLink.external_resource_id == store.external_resource_id,
                OrganizationResourceLink.status == "active",
            )
        ).first()
        if linked is None or connection.status != "active":
            state.import_job_id = None
            state.last_error_code = "link_ended" if linked is None else "connection_inactive"
            state.last_error_at = rt.clock.now()
            return None, None
        provider = commerce_provider(rt.providers.get(connection.provider))
        if provider is None:
            raise JobSubjectGoneError()
        ctx = _Context(
            org_id=org_id,
            store_id=store.id,
            connection_id=connection.id,
            currency=store.currency,
            history_from=store.history_from,
            kind=BulkKind(state.bulk_operation_kind or BulkKind.CATALOGUE.value),
            operation_id=state.bulk_operation_id,
            first_import=store.first_import_completed_at is None,
        )
        return ctx, provider


def _step(rt: Runtime, job: ClaimedJob, org_id: uuid.UUID, store_id: uuid.UUID) -> int | None:
    """One step; returns the delay before the next step, or ``None`` when the chain ends.

    Temporary platform errors propagate (the job framework retries the step with back-off);
    permanent ones (or the last retry) end the chain with the error recorded on the store.
    """
    ctx, provider = _load(rt, job, org_id, store_id)
    if ctx is None or provider is None:
        return None
    try:
        return _run(rt, ctx, provider)
    except ProviderError as exc:
        if not exc.retryable or job.attempts >= job.max_attempts:
            # Permanent, or the last retry: the store shows the error and the chain ends.
            _fail(rt, ctx, str(exc) or exc.code)
        raise


def _run(rt: Runtime, ctx: _Context, provider: CommerceProvider) -> int | None:
    org_id, store_id = ctx.org_id, ctx.store_id
    poll = int(rt.settings.COMMERCE_BULK_POLL_INTERVAL.total_seconds())
    secrets = usable_secrets(rt, org_id, ctx.connection_id)

    def call[T](fn: Callable[[], T]) -> T:
        return call_provider(rt, provider, org_id, ctx.connection_id, fn)

    if ctx.operation_id is None:
        since = ctx.history_from if ctx.kind is BulkKind.ORDERS else None
        operation_id = call(lambda: provider.start_bulk_export(secrets, ctx.kind, since=since))
        with rt.db.transaction(org_id=org_id) as session:
            state = session.get(CommerceSyncState, store_id, with_for_update=True)
            assert state is not None
            state.bulk_operation_id = operation_id
            state.updated_at = rt.clock.now()
        return poll

    operation = ctx.operation_id
    state_now = call(lambda: provider.bulk_export_state(secrets, operation))
    if state_now.status is BulkStatus.RUNNING:
        return poll
    if state_now.status is BulkStatus.FAILED:
        _fail(rt, ctx, state_now.error_code or "export_failed")
        return None

    counts: dict[str, int] = {}
    if state_now.result_url is not None:  # no URL = the export matched nothing
        url = state_now.result_url
        try:
            counts = _apply(rt, ctx, provider.read_bulk_export(url, ctx.kind))
        except DownloadExpiredError:
            # The signed link lapsed (e.g. a long pause): run the same export again. Rows
            # already written are upserted again harmlessly.
            with rt.db.transaction(org_id=org_id) as session:
                state = session.get(CommerceSyncState, store_id, with_for_update=True)
                assert state is not None
                state.bulk_operation_id = None
            return 0
    if ctx.kind is BulkKind.CATALOGUE:
        with rt.db.transaction(org_id=org_id) as session:
            state = session.get(CommerceSyncState, store_id, with_for_update=True)
            assert state is not None
            state.bulk_operation_id, state.bulk_operation_kind = None, BulkKind.ORDERS.value
            state.import_progress = PROGRESS_AFTER_CATALOGUE
            state.updated_at = rt.clock.now()
            _audit_counts(session, ctx, "store.catalogue_imported", counts)
        return 0
    _finish(rt, ctx, counts)
    return None


def _fail(rt: Runtime, ctx: _Context, code: str) -> None:
    with rt.db.transaction(org_id=ctx.org_id) as session:
        state = session.get(CommerceSyncState, ctx.store_id, with_for_update=True)
        store = session.get(Store, ctx.store_id)
        assert state is not None
        assert store is not None
        state.bulk_operation_id, state.import_job_id = None, None
        state.last_error_code, state.last_error_at = code[:64], rt.clock.now()
        if ctx.first_import:
            store.status = "error"
        record_audit(
            session,
            organization_id=ctx.org_id,
            actor=WORKER,
            action="store.import_failed",
            resource_type="store",
            resource_id=ctx.store_id,
            metadata={"kind": ctx.kind.value, "error": code[:64]},
        )


def _finish(rt: Runtime, ctx: _Context, counts: dict[str, int]) -> None:
    now = rt.clock.now()
    with rt.db.transaction(org_id=ctx.org_id) as session:
        _resolve_links(session, ctx)
        state = session.get(CommerceSyncState, ctx.store_id, with_for_update=True)
        store = session.get(Store, ctx.store_id)
        assert state is not None
        assert store is not None
        state.bulk_operation_id, state.bulk_operation_kind = None, None
        state.import_job_id, state.import_progress = None, 100
        state.last_reconciled_at, state.updated_at = now, now
        store.status = "active"
        if store.first_import_completed_at is None:
            store.first_import_completed_at = now
        _audit_counts(session, ctx, "store.import_completed", counts)


def _audit_counts(session: Session, ctx: _Context, action: str, counts: dict[str, int]) -> None:
    record_audit(
        session,
        organization_id=ctx.org_id,
        actor=WORKER,
        action=action,
        resource_type="store",
        resource_id=ctx.store_id,
        metadata={"counts": counts},
    )


# ------------------------------------------------------------------ applying records
@dataclass
class _Batch:
    products: list[CommerceProductRecord] = field(default_factory=list)
    variants: list[CommerceVariantRecord] = field(default_factory=list)
    orders: list[CommerceOrderRecord] = field(default_factory=list)
    refunds: list[CommerceRefundRecord] = field(default_factory=list)
    lines: list[CommerceOrderLineRecord] = field(default_factory=list)
    sales: list[CommerceSaleRecord] = field(default_factory=list)

    def add(self, record: CommerceRecord) -> None:
        match record:
            case CommerceProductRecord():
                self.products.append(record)
            case CommerceVariantRecord():
                self.variants.append(record)
            case CommerceOrderRecord():
                self.orders.append(record)
            case CommerceRefundRecord():
                self.refunds.append(record)
            case CommerceOrderLineRecord():
                self.lines.append(record)
            case CommerceSaleRecord():
                self.sales.append(record)

    def size(self) -> int:
        return sum(
            len(x)
            for x in (
                self.products,
                self.variants,
                self.orders,
                self.refunds,
                self.lines,
                self.sales,
            )
        )


def _chunks(records: Iterable[CommerceRecord], size: int) -> Iterator[_Batch]:
    batch = _Batch()
    for record in records:
        batch.add(record)
        if batch.size() >= size:
            yield batch
            batch = _Batch()
    if batch.size():
        yield batch


def _apply(rt: Runtime, ctx: _Context, records: Iterable[CommerceRecord]) -> dict[str, int]:
    counts = {"products": 0, "variants": 0, "orders": 0, "refunds": 0, "lines": 0, "sales": 0}
    for batch in _chunks(records, rt.settings.COMMERCE_IMPORT_BATCH_SIZE):
        with rt.db.transaction(org_id=ctx.org_id) as session:
            now = rt.clock.now()
            counts["products"] += _upsert_products(session, ctx, batch.products, now)
            counts["variants"] += _upsert_variants(session, ctx, batch.variants, now)
            counts["orders"] += _upsert_orders(session, ctx, batch.orders, now)
            counts["refunds"] += _upsert_refunds(session, ctx, batch.refunds, now)
            counts["lines"] += _upsert_lines(session, ctx, batch.lines)
            counts["sales"] += _upsert_sales(session, ctx, batch.sales)
    logger.info(
        "import_applied",
        extra={"store_id": str(ctx.store_id), "kind": ctx.kind.value, "counts": counts},
    )
    return counts


def _table(model: Any) -> Table:
    return cast(Table, model.__table__)


def _ids(
    session: Session, model: Any, column: Any, scope: Any, values: Iterable[str]
) -> dict[str, uuid.UUID]:
    wanted = list(dict.fromkeys(values))
    if not wanted:
        return {}
    rows = session.execute(select(column, model.id).where(scope, column.in_(wanted))).all()
    return {str(ext): row_id for ext, row_id in rows}


def _upsert_products(
    session: Session, ctx: _Context, records: list[CommerceProductRecord], now: datetime
) -> int:
    if not records:
        return 0
    table = _table(Product)
    stmt = insert(table).values(
        [
            {
                "id": uuid.uuid4(),
                "organization_id": ctx.org_id,
                "store_id": ctx.store_id,
                "external_product_id": r.external_id,
                "title": r.title,
                "handle": r.handle,
                "product_type": r.product_type,
                "vendor": r.vendor,
                "status": r.status,
                "external_updated_at": r.updated_at,
                "created_at": now,
                "updated_at": now,
            }
            for r in _dedupe(records)
        ]
    )
    excluded = stmt.excluded
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_products_store_id_external_product_id",
            set_={
                "title": excluded.title,
                "handle": excluded.handle,
                "product_type": excluded.product_type,
                "vendor": excluded.vendor,
                "status": excluded.status,
                "external_updated_at": excluded.external_updated_at,
                "updated_at": excluded.updated_at,
            },
            where=_guard(table, excluded),
        )
    )
    return len(records)


def _guard(table: Any, excluded: Any) -> Any:
    return (
        table.c.external_updated_at.is_(None)
        | excluded.external_updated_at.is_(None)
        | (excluded.external_updated_at >= table.c.external_updated_at)
    )


def _dedupe[T: Any](records: list[T]) -> list[T]:
    """Last occurrence wins (an export can repeat a node); one row per id per statement."""
    by_id: dict[str, T] = {}
    for record in records:
        by_id[record.external_id] = record
    return list(by_id.values())


def _upsert_variants(
    session: Session, ctx: _Context, records: list[CommerceVariantRecord], now: datetime
) -> int:
    if not records:
        return 0
    products = _ids(
        session,
        Product,
        Product.external_product_id,
        Product.store_id == ctx.store_id,
        (r.product_external_id for r in records),
    )
    rows = []
    for r in _dedupe(records):
        product_id = products.get(r.product_external_id)
        if product_id is None:
            continue  # parent missing from the export: skip rather than invent
        rows.append(
            {
                "id": uuid.uuid4(),
                "organization_id": ctx.org_id,
                "store_id": ctx.store_id,
                "product_id": product_id,
                "external_variant_id": r.external_id,
                "external_inventory_item_id": r.inventory_item_id,
                "title": r.title,
                "sku": r.sku,
                "price": r.price,
                "inventory_tracked": r.inventory_tracked,
                "inventory_available": r.inventory_available,
                "inventory_synced_at": now,
                "deleted": False,
                "external_updated_at": r.updated_at,
                "created_at": now,
                "updated_at": now,
            }
        )
    if not rows:
        return 0
    table = _table(ProductVariant)
    stmt = insert(table).values(rows)
    excluded = stmt.excluded
    returned = session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_product_variants_store_id_external_variant_id",
            set_={
                c: getattr(excluded, c)
                for c in (
                    "product_id",
                    "external_inventory_item_id",
                    "title",
                    "sku",
                    "price",
                    "inventory_tracked",
                    "inventory_available",
                    "inventory_synced_at",
                    "deleted",
                    "external_updated_at",
                    "updated_at",
                )
            },
            where=_guard(table, excluded),
        ).returning(table.c.id, table.c.external_variant_id)
    ).all()
    variant_ids = {ext: vid for vid, ext in returned}
    _record_costs(session, ctx, records, variant_ids, now)
    return len(rows)


def _record_costs(
    session: Session,
    ctx: _Context,
    records: list[CommerceVariantRecord],
    variant_ids: dict[str, uuid.UUID],
    now: datetime,
) -> None:
    """Add a cost-history row when a variant's unit cost differs from its latest one.

    Costs in another currency than the store's are not recorded (no conversion in 2A). A
    cost that disappears (hidden or removed) is recorded as NULL from now on — never 0.
    """
    if not variant_ids:
        return
    latest = {
        row.variant_id: row.unit_cost
        for row in session.execute(
            select(ProductCostHistory.variant_id, ProductCostHistory.unit_cost)
            .where(ProductCostHistory.variant_id.in_(list(variant_ids.values())))
            .ext(distinct_on(ProductCostHistory.variant_id))
            .order_by(ProductCostHistory.variant_id, ProductCostHistory.effective_from.desc())
        )
    }
    source = "import_snapshot" if ctx.first_import else "platform"
    for record in _dedupe(records):
        variant_id = variant_ids.get(record.external_id)
        if variant_id is None:
            continue
        cost = record.unit_cost if record.cost_currency in (None, ctx.currency) else None
        if record.unit_cost is not None and record.cost_currency not in (None, ctx.currency):
            logger.warning("cost_currency_mismatch", extra={"store_id": str(ctx.store_id)})
        has_history = variant_id in latest
        if (not has_history and cost is None) or (has_history and latest[variant_id] == cost):
            continue
        session.execute(
            insert(ProductCostHistory)
            .values(
                id=uuid.uuid4(),
                organization_id=ctx.org_id,
                variant_id=variant_id,
                unit_cost=cost,
                currency=ctx.currency,
                effective_from=now,
                source=source,
                recorded_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_product_cost_history_variant_id_effective_from")
        )


def _upsert_orders(
    session: Session, ctx: _Context, records: list[CommerceOrderRecord], now: datetime
) -> int:
    if not records:
        return 0
    table = _table(Order)
    stmt = insert(table).values(
        [
            {
                "id": uuid.uuid4(),
                "organization_id": ctx.org_id,
                "store_id": ctx.store_id,
                "external_order_id": r.external_id,
                "order_number": r.order_number,
                "currency": r.currency,
                "ordered_at": r.ordered_at,
                "cancelled_at": r.cancelled_at,
                "financial_status": r.financial_status,
                "discount_amount": r.discount_amount,
                "shipping_amount": r.shipping_amount,
                "tax_amount": r.tax_amount,
                "refund_amount": r.refund_amount,
                "total_amount": r.total_amount,
                "external_updated_at": r.updated_at,
                "created_at": now,
                "updated_at": now,
            }
            for r in _dedupe(records)
        ]
    )
    excluded = stmt.excluded
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_orders_store_id_external_order_id",
            set_={
                c: getattr(excluded, c)
                for c in (
                    "order_number",
                    "currency",
                    "ordered_at",
                    "cancelled_at",
                    "financial_status",
                    "discount_amount",
                    "shipping_amount",
                    "tax_amount",
                    "refund_amount",
                    "total_amount",
                    "external_updated_at",
                    "updated_at",
                )
            },
            where=_guard(table, excluded),
        )
    )
    return len(records)


def _order_ids(session: Session, ctx: _Context, values: Iterable[str]) -> dict[str, uuid.UUID]:
    return _ids(session, Order, Order.external_order_id, Order.store_id == ctx.store_id, values)


def _upsert_refunds(
    session: Session, ctx: _Context, records: list[CommerceRefundRecord], now: datetime
) -> int:
    del now
    if not records:
        return 0
    orders = _order_ids(session, ctx, (r.order_external_id for r in records))
    rows = [
        {
            "id": uuid.uuid4(),
            "organization_id": ctx.org_id,
            "order_id": orders[r.order_external_id],
            "external_refund_id": r.external_id,
            "processed_at": r.processed_at,
            "total_amount": r.total_amount,
            "currency": r.currency,
        }
        for r in _dedupe(records)
        if r.order_external_id in orders
    ]
    if not rows:
        return 0
    stmt = insert(_table(Refund)).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_refunds_order_id_external_refund_id",
            set_={
                "processed_at": stmt.excluded.processed_at,
                "total_amount": stmt.excluded.total_amount,
                "currency": stmt.excluded.currency,
            },
        )
    )
    return len(rows)


def _upsert_lines(session: Session, ctx: _Context, records: list[CommerceOrderLineRecord]) -> int:
    if not records:
        return 0
    orders = _order_ids(session, ctx, (r.order_external_id for r in records))
    variants = _ids(
        session,
        ProductVariant,
        ProductVariant.external_variant_id,
        ProductVariant.store_id == ctx.store_id,
        (r.variant_external_id for r in records if r.variant_external_id),
    )
    costs = _current_costs(session, list(variants.values()))
    rows = []
    for r in _dedupe(records):
        order_id = orders.get(r.order_external_id)
        if order_id is None:
            continue
        variant_id = variants.get(r.variant_external_id or "")
        cost = costs.get(variant_id) if variant_id else None
        rows.append(
            {
                "id": uuid.uuid4(),
                "organization_id": ctx.org_id,
                "order_id": order_id,
                "variant_id": variant_id,
                "external_line_item_id": r.external_id,
                "title": r.title,
                "sku": r.sku,
                "quantity": r.quantity,
                "unit_price": r.unit_price,
                # Shopify keeps no cost history: imported orders take the cost at import time.
                "unit_cost": cost,
                "cost_source": "import_time" if cost is not None else None,
            }
        )
    if not rows:
        return 0
    stmt = insert(_table(OrderItem)).values(rows)
    excluded = stmt.excluded
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_order_items_order_id_external_line_item_id",
            set_={
                c: getattr(excluded, c)
                for c in ("variant_id", "title", "sku", "quantity", "unit_price")
            },
        )
    )
    return len(rows)


def _current_costs(session: Session, variant_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not variant_ids:
        return {}
    rows = session.execute(
        select(ProductCostHistory.variant_id, ProductCostHistory.unit_cost)
        .where(ProductCostHistory.variant_id.in_(variant_ids))
        .ext(distinct_on(ProductCostHistory.variant_id))
        .order_by(ProductCostHistory.variant_id, ProductCostHistory.effective_from.desc())
    ).all()
    return {vid: cost for vid, cost in rows if cost is not None}


def _upsert_sales(session: Session, ctx: _Context, records: list[CommerceSaleRecord]) -> int:
    if not records:
        return 0
    orders = _order_ids(session, ctx, (r.order_external_id for r in records))
    rows = [
        {
            "id": uuid.uuid4(),
            "organization_id": ctx.org_id,
            "store_id": ctx.store_id,
            "order_id": orders[r.order_external_id],
            "order_item_id": None,  # resolved at the end of the import (_resolve_links)
            "external_line_item_id": r.line_item_external_id,
            "external_agreement_id": r.agreement_external_id,
            "external_sale_id": r.external_id,
            "happened_at": r.happened_at,
            "agreement_reason": r.agreement_reason,
            "action": r.action,
            "line_type": r.line_type,
            "quantity": r.quantity,
            "amount": r.amount,
            "discount_amount": r.discount_amount,
            "tax_amount": r.tax_amount,
            "currency": r.currency,
        }
        for r in _dedupe(records)
        if r.order_external_id in orders
    ]
    if not rows:
        return 0
    stmt = insert(_table(SalesEntry)).values(rows)
    excluded = stmt.excluded
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_sales_entries_store_id_external_sale_id",
            set_={
                c: getattr(excluded, c)
                for c in (
                    "order_id",
                    "external_line_item_id",
                    "external_agreement_id",
                    "happened_at",
                    "agreement_reason",
                    "action",
                    "line_type",
                    "quantity",
                    "amount",
                    "discount_amount",
                    "tax_amount",
                    "currency",
                )
            },
        )
    )
    return len(rows)


def _resolve_links(session: Session, ctx: _Context) -> None:
    """Rows whose platform parent arrived later in the export are linked now; order display
    totals that need the lines (gross = sum of unit price times quantity) are filled in."""
    params = {"store": ctx.store_id, "org": ctx.org_id}
    session.execute(
        text(
            "UPDATE sales_entries s SET order_item_id = oi.id "
            "FROM order_items oi "
            "WHERE s.store_id = :store AND s.organization_id = :org "
            "AND s.order_item_id IS NULL AND s.external_line_item_id IS NOT NULL "
            "AND oi.organization_id = s.organization_id AND oi.order_id = s.order_id "
            "AND oi.external_line_item_id = s.external_line_item_id"
        ),
        params,
    )
    session.execute(
        text(
            "UPDATE orders o SET gross_amount = t.gross FROM ("
            "  SELECT order_id, SUM(unit_price * quantity) AS gross, "
            "         COUNT(*) FILTER (WHERE unit_price IS NULL) AS unknown "
            "  FROM order_items WHERE organization_id = :org GROUP BY order_id"
            ") t WHERE o.id = t.order_id AND o.store_id = :store AND o.organization_id = :org "
            "AND t.unknown = 0"
        ),
        params,
    )
