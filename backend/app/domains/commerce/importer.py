"""Initial store import through platform bulk exports (task 2A-06, PHASE_02A_PLAN §9).

Linking a store resource of a commerce platform creates its ``stores`` row and starts the
import. The import is a chain of short jobs (``commerce.import_step``), one step each:

1. start the catalogue export (products → variants, inventory, unit cost);
2. poll until it finishes (a new step every ``COMMERCE_BULK_POLL_INTERVAL``), then stream the
   file line by line and upsert in batches;
3. the same for orders since ``history_from`` (lines, sales agreements, refunds);
4. resolve links between rows that arrived out of order, mark the store active.

Platforms without bulk exports (WooCommerce, 2B-02) declare ``PAGED_IMPORT`` instead: each
step reads **one page** of the current kind and saves the provider's opaque cursor in
``commerce_sync_state.import_cursor``, so a stopped import resumes where it was. Everything
else — locks, the single-chain rule, upserts, links, figures — is shared.

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
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import BindParameter, Table, bindparam, select, text
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.domains.audit.service import Actor, record_audit
from app.domains.billing.entitlements import is_read_only
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
from app.domains.finance.definitions import local_day
from app.domains.finance.service import order_days, recompute_days, recompute_since, store_zone
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
from app.providers.base.interfaces import (
    BulkExportProvider,
    CommerceProvider,
    PagedImportProvider,
    PlatformProvider,
)
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
    StoreHealth,
)
from app.providers.http.client import DownloadExpiredError
from app.runtime import Runtime

logger = logging.getLogger("advegax.commerce.import")

JOB_IMPORT_STEP = "commerce.import_step"
WORKER = Actor("worker", None)
IMPORT_LOCK_TTL_SECONDS = 2 * 3600  # covers the longest download (OUTBOUND_DOWNLOAD_TIMEOUT)
SEEN_TTL_SECONDS = 48 * 3600  # a full catalogue read of a very large store
PROGRESS_AFTER_CATALOGUE = 40


def commerce_provider(provider: PlatformProvider) -> CommerceProvider | None:
    """The provider as a commerce importer: bulk exports (``BULK_IMPORT``) or pages
    (``PAGED_IMPORT``), whichever it declares and implements."""
    caps = provider.capabilities
    if caps.supports(Capability.BULK_IMPORT) and isinstance(provider, BulkExportProvider):
        return provider
    if caps.supports(Capability.PAGED_IMPORT) and isinstance(provider, PagedImportProvider):
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
            counted_statuses=_counted_statuses(provider),
        )
        session.add(store)
        session.flush()
        session.add(CommerceSyncState(store_id=store.id, organization_id=org_id))
        session.flush()
    if store.first_import_completed_at is None:
        start_import(session, rt, store, requested_by=user_id)
    return store


class SyncMode(StrEnum):
    INITIAL = "initial"  # first import: catalogue + order history
    RECONCILE = "reconcile"  # hourly: what changed since the last run
    DEEP = "deep"  # nightly / "Sync now": whole catalogue + recent orders


def start_import(
    session: Session, rt: Runtime, store: Store, *, requested_by: uuid.UUID | None
) -> uuid.UUID:
    """(Re)start the initial import from the catalogue step."""
    return start_sync(session, rt, store, SyncMode.INITIAL, requested_by=requested_by)


def start_sync(
    session: Session,
    rt: Runtime,
    store: Store,
    mode: SyncMode,
    *,
    requested_by: uuid.UUID | None = None,
) -> uuid.UUID:
    """Start a chain in ``mode`` (replacing any chain that was running for this store)."""
    state = session.get(CommerceSyncState, store.id, with_for_update=True)
    if state is None:
        state = CommerceSyncState(store_id=store.id, organization_id=store.organization_id)
        session.add(state)
    now = rt.clock.now()
    if mode is SyncMode.INITIAL:
        store.status = "importing"
        state.import_progress = 0
    state.sync_mode, state.sync_started_at = mode.value, now
    state.bulk_operation_id, state.bulk_operation_kind = None, BulkKind.CATALOGUE.value
    state.import_cursor, state.import_counts = None, None
    state.last_error_code, state.last_error_at = None, None
    job = _schedule(session, rt, store, state, delay=0, requested_by=requested_by)
    if mode is SyncMode.INITIAL or requested_by is not None:
        record_audit(
            session,
            organization_id=store.organization_id,
            actor=Actor.user(requested_by) if requested_by else WORKER,
            action="store.import_started" if mode is SyncMode.INITIAL else "store.sync_started",
            resource_type="store",
            resource_id=store.id,
            metadata={
                "job_id": str(job),
                "mode": mode.value,
                "history_from": store.history_from.isoformat() if store.history_from else None,
            },
        )
    return job


def chain_running(rt: Runtime, state: CommerceSyncState) -> bool:
    """A chain is running unless none was started or it has been silent too long."""
    if state.import_job_id is None:
        return False
    return state.updated_at > rt.clock.now() - rt.settings.COMMERCE_CHAIN_STALE_AFTER


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
    mode: SyncMode = SyncMode.INITIAL
    started_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    cursor: str | None = None  # paged imports: the next page of ``kind``
    counts: dict[str, int] = field(default_factory=dict)  # paged imports: applied so far


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
            mode=SyncMode(state.sync_mode or SyncMode.INITIAL.value),
            started_at=state.sync_started_at,
            last_reconciled_at=state.last_reconciled_at,
            cursor=state.import_cursor,
            counts=dict(state.import_counts or {}),
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
    if isinstance(provider, BulkExportProvider) and provider.capabilities.supports(
        Capability.BULK_IMPORT
    ):
        return _run_bulk(rt, ctx, provider)
    return _run_paged(rt, ctx, cast(PagedImportProvider, provider))


def _run_paged(rt: Runtime, ctx: _Context, provider: PagedImportProvider) -> int | None:
    """Read one page of the current kind, apply it and move the cursor (2B-02)."""
    org_id, store_id = ctx.org_id, ctx.store_id
    secrets = usable_secrets(rt, org_id, ctx.connection_id)
    created, updated = _filters(rt, ctx)
    page = call_provider(
        rt,
        provider,
        org_id,
        ctx.connection_id,
        lambda: provider.read_page(
            secrets, ctx.kind, ctx.cursor, created_since=created, updated_since=updated
        ),
    )
    counts = _apply(rt, ctx, page.records)
    complete = (
        ctx.kind is BulkKind.CATALOGUE
        and ctx.mode is SyncMode.DEEP
        and provider.capabilities.supports(Capability.COMPLETE_CATALOGUE)
    )
    if complete:
        _remember_seen(rt, ctx, page.records)
    if complete and page.next_cursor is None:
        counts = {**counts, "deleted": _mark_unseen_deleted(rt, ctx)}
    total = {k: ctx.counts.get(k, 0) + counts.get(k, 0) for k in {*ctx.counts, *counts}}
    delay = int(rt.settings.COMMERCE_PAGE_INTERVAL.total_seconds())
    if page.next_cursor is not None:
        with rt.db.transaction(org_id=org_id) as session:
            state = session.get(CommerceSyncState, store_id, with_for_update=True)
            assert state is not None
            state.import_cursor, state.import_counts = page.next_cursor, total
            if ctx.mode is SyncMode.INITIAL and page.progress is not None:
                state.import_progress = _paged_progress(ctx.kind, page.progress)
            state.updated_at = rt.clock.now()
        return delay
    if ctx.kind is BulkKind.CATALOGUE:
        with rt.db.transaction(org_id=org_id) as session:
            state = session.get(CommerceSyncState, store_id, with_for_update=True)
            assert state is not None
            state.bulk_operation_kind, state.import_cursor = BulkKind.ORDERS.value, None
            state.import_counts = total
            if ctx.mode is SyncMode.INITIAL:
                state.import_progress = PROGRESS_AFTER_CATALOGUE
                _audit_counts(session, ctx, "store.catalogue_imported", total)
            state.updated_at = rt.clock.now()
        return delay
    _finish(rt, ctx, total, provider)
    return None


def _counted_statuses(provider: CommerceProvider) -> list[str] | None:
    statuses = getattr(provider, "counted_order_statuses", None)
    return list(statuses) if statuses else None


def _seen_key(ctx: _Context) -> str:
    started = ctx.started_at.isoformat() if ctx.started_at else "none"
    return f"catalogue-seen:{ctx.store_id}:{started}"


def _remember_seen(rt: Runtime, ctx: _Context, records: Iterable[CommerceRecord]) -> None:
    """Note every product and variant a full catalogue read lists (2B-06)."""
    members = [
        f"p:{r.external_id}" if isinstance(r, CommerceProductRecord) else f"v:{r.external_id}"
        for r in records
        if isinstance(r, (CommerceProductRecord, CommerceVariantRecord))
    ]
    key = _seen_key(ctx)
    pipe = rt.redis.pipeline()
    pipe.sadd(key, "started")  # the set exists even for a page without products
    if members:
        pipe.sadd(key, *members)
    pipe.expire(key, SEEN_TTL_SECONDS)
    pipe.execute()


def _mark_unseen_deleted(rt: Runtime, ctx: _Context) -> int:
    """After a complete full catalogue read: products and variants it did not list were
    deleted on the platform. They are marked deleted (order history keeps them). Nothing is
    marked when the read listed no product at all — that is more likely a fault than an
    empty store."""
    key = _seen_key(ctx)
    seen = {m.decode() if isinstance(m, bytes) else str(m) for m in rt.redis.smembers(key)}
    rt.redis.delete(key)
    products = {m[2:] for m in seen if m.startswith("p:")}
    variants = {m[2:] for m in seen if m.startswith("v:")}
    if not products:
        logger.warning("catalogue_empty_not_pruned", extra={"store_id": str(ctx.store_id)})
        return 0
    marked = 0
    with rt.db.transaction(org_id=ctx.org_id) as session:
        for product in session.execute(
            select(Product).where(Product.store_id == ctx.store_id, Product.status != "deleted")
        ).scalars():
            if product.external_product_id not in products:
                product.status = "deleted"
                marked += 1
        for variant in session.execute(
            select(ProductVariant).where(
                ProductVariant.store_id == ctx.store_id, ProductVariant.deleted.is_(False)
            )
        ).scalars():
            if variant.external_variant_id not in variants:
                variant.deleted = True
    if marked:
        logger.info(
            "products_marked_deleted", extra={"store_id": str(ctx.store_id), "count": marked}
        )
    return marked


def _paged_progress(kind: BulkKind, within: int) -> int:
    """Overall first-import progress from a provider's estimate within the current kind."""
    within = max(0, min(100, within))
    if kind is BulkKind.CATALOGUE:
        return PROGRESS_AFTER_CATALOGUE * within // 100
    return PROGRESS_AFTER_CATALOGUE + (99 - PROGRESS_AFTER_CATALOGUE) * within // 100


def _run_bulk(rt: Runtime, ctx: _Context, provider: BulkExportProvider) -> int | None:
    org_id, store_id = ctx.org_id, ctx.store_id
    poll = int(rt.settings.COMMERCE_BULK_POLL_INTERVAL.total_seconds())
    secrets = usable_secrets(rt, org_id, ctx.connection_id)

    def call[T](fn: Callable[[], T]) -> T:
        return call_provider(rt, provider, org_id, ctx.connection_id, fn)

    if ctx.operation_id is None:
        created, updated = _filters(rt, ctx)
        operation_id = call(
            lambda: provider.start_bulk_export(
                secrets, ctx.kind, created_since=created, updated_since=updated
            )
        )
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
            if ctx.mode is SyncMode.INITIAL:
                state.import_progress = PROGRESS_AFTER_CATALOGUE
                _audit_counts(session, ctx, "store.catalogue_imported", counts)
            state.updated_at = rt.clock.now()
        return 0
    _finish(rt, ctx, counts, provider)
    return None


def _filters(rt: Runtime, ctx: _Context) -> tuple[datetime | None, datetime | None]:
    """(created_since, updated_since) for the export about to start."""
    if ctx.mode is SyncMode.RECONCILE:
        base = ctx.last_reconciled_at or ctx.started_at or rt.clock.now()
        updated = base - rt.settings.COMMERCE_RECONCILE_OVERLAP
        return (ctx.history_from if ctx.kind is BulkKind.ORDERS else None), updated
    if ctx.kind is BulkKind.CATALOGUE:
        return None, None
    if ctx.mode is SyncMode.DEEP:
        recent = rt.clock.now() - rt.settings.COMMERCE_DEEP_WINDOW
        return (max(recent, ctx.history_from) if ctx.history_from else recent), None
    return ctx.history_from, None


def _fail(rt: Runtime, ctx: _Context, code: str) -> None:
    with rt.db.transaction(org_id=ctx.org_id) as session:
        state = session.get(CommerceSyncState, ctx.store_id, with_for_update=True)
        store = session.get(Store, ctx.store_id)
        assert state is not None
        assert store is not None
        state.bulk_operation_id, state.import_job_id = None, None
        state.import_cursor, state.import_counts = None, None
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
            metadata={"kind": ctx.kind.value, "mode": ctx.mode.value, "error": code[:64]},
        )


def _recompute_older_orders(rt: Runtime, ctx: _Context, since: datetime) -> int:
    if ctx.started_at is None:
        return 0
    with rt.db.transaction(org_id=ctx.org_id) as session:
        store = session.get(Store, ctx.store_id)
        ids = session.execute(
            select(Order.id).where(
                Order.store_id == ctx.store_id,
                Order.updated_at >= ctx.started_at,  # written by this chain
                Order.ordered_at < since,
            )
        ).scalars()
        if store is None:
            return 0
        tz = store_zone(store)
        first = local_day(since, tz)
        days = {d for d in order_days(session, store, ids) if d < first}
        return recompute_days(session, rt, store, days)


def _finish(rt: Runtime, ctx: _Context, counts: dict[str, int], provider: CommerceProvider) -> None:
    created, updated = _filters(rt, ctx)
    since = updated or created or ctx.history_from
    with rt.db.transaction(org_id=ctx.org_id) as session:
        _resolve_links(session, ctx)  # before the figures: sales need their order lines' costs
    if since is not None:
        # Rebuild the daily figures the orders export can have changed (2A-08) …
        days = recompute_since(rt, ctx.org_id, ctx.store_id, since)
        # … and the earlier days of older orders this chain changed: a WooCommerce order that
        # becomes counted (or is cancelled) moves money on its order date (2B-07, Q-2B-2).
        days += _recompute_older_orders(rt, ctx, since)
        counts = {**counts, "finance_days": days}
    health = _check_health(rt, ctx, provider)
    now = rt.clock.now()
    with rt.db.transaction(org_id=ctx.org_id) as session:
        state = session.get(CommerceSyncState, ctx.store_id, with_for_update=True)
        store = session.get(Store, ctx.store_id)
        assert state is not None
        assert store is not None
        started = ctx.started_at or now
        state.bulk_operation_id, state.bulk_operation_kind = None, None
        state.import_cursor, state.import_counts = None, None
        state.import_job_id, state.import_progress = None, 100
        state.sync_mode, state.updated_at = None, now
        # The next hourly run starts from when this one began (plus an overlap).
        state.last_reconciled_at = started
        if ctx.mode is SyncMode.DEEP:
            state.last_deep_reconciled_at = started
        store.status = "active"
        if store.first_import_completed_at is None:
            store.first_import_completed_at = now
        if health is not None:
            store.platform_version = health.platform_version
            store.site_url = health.site_url
            store.health_code = health.warnings[0] if health.warnings else None
            store.health_checked_at = now
        if ctx.mode is SyncMode.INITIAL:
            _audit_counts(session, ctx, "store.import_completed", counts)
    logger.info(
        "store_sync_finished",
        extra={"store_id": str(ctx.store_id), "mode": ctx.mode.value, "counts": counts},
    )


def _check_health(rt: Runtime, ctx: _Context, provider: CommerceProvider) -> StoreHealth | None:
    """The daily store-configuration check (first import and nightly check, 2B-06). A failed
    check never fails the sync; its error code becomes the store's health code."""
    if ctx.mode is SyncMode.RECONCILE or not provider.capabilities.supports(
        Capability.STORE_HEALTH
    ):
        return None
    check = getattr(provider, "store_health", None)
    if check is None:
        return None
    secrets = usable_secrets(rt, ctx.org_id, ctx.connection_id)
    try:
        result = call_provider(rt, provider, ctx.org_id, ctx.connection_id, lambda: check(secrets))
    except ProviderError as exc:
        logger.warning(
            "store_health_failed", extra={"store_id": str(ctx.store_id), "error_code": exc.code}
        )
        return StoreHealth(warnings=(exc.code,))
    return result if isinstance(result, StoreHealth) else None


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
                "excluded_reason": r.excluded_reason,
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
                    "excluded_reason",
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
    history = _cost_history(session, list(variants.values()))
    ordered = _order_times(session, list(orders.values()))
    rows: list[dict[str, Any]] = []
    platform_rows: list[dict[str, Any]] = []
    for r in _dedupe(records):
        order_id = orders.get(r.order_external_id)
        if order_id is None:
            continue
        variant_id = variants.get(r.variant_external_id or "")
        if r.cost_from_platform:
            # The platform recorded the cost with the sale (WooCommerce COGS): use it as is.
            cost, source = (r.unit_cost, "order_time") if r.unit_cost is not None else (None, None)
        elif variant_id:
            cost, source = _cost_for(history.get(variant_id, []), ordered[order_id])
        else:
            cost, source = None, None
        (platform_rows if r.cost_from_platform else rows).append(
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
                "unit_cost": cost,
                "cost_source": source,
            }
        )
    updated = ("variant_id", "title", "sku", "quantity", "unit_price")
    for batch, columns in (
        (rows, updated),
        # A platform-recorded cost is the truth for that sale: refreshed with the line.
        (platform_rows, (*updated, "unit_cost", "cost_source")),
    ):
        if not batch:
            continue
        stmt = insert(_table(OrderItem)).values(batch)
        excluded = stmt.excluded
        session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_order_items_order_id_external_line_item_id",
                set_={c: getattr(excluded, c) for c in columns},
            )
        )
    return len(rows) + len(platform_rows)


def _order_times(session: Session, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    if not order_ids:
        return {}
    rows = session.execute(select(Order.id, Order.ordered_at).where(Order.id.in_(order_ids)))
    times: dict[uuid.UUID, datetime] = {}
    for order_id, ordered_at in rows:
        times[order_id] = ordered_at
    return times


def _cost_history(
    session: Session, variant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[datetime, Decimal | None]]]:
    history: dict[uuid.UUID, list[tuple[datetime, Decimal | None]]] = {}
    if not variant_ids:
        return history
    rows = session.execute(
        select(
            ProductCostHistory.variant_id,
            ProductCostHistory.effective_from,
            ProductCostHistory.unit_cost,
        )
        .where(ProductCostHistory.variant_id.in_(variant_ids))
        .order_by(ProductCostHistory.variant_id, ProductCostHistory.effective_from)
    )
    for variant_id, effective_from, cost in rows:
        history.setdefault(variant_id, []).append((effective_from, cost))
    return history


def _cost_for(
    history: list[tuple[datetime, Decimal | None]], ordered_at: datetime
) -> tuple[Decimal | None, str | None]:
    """Unit cost for a line ordered at ``ordered_at`` (PHASE_02A_PLAN §8).

    * Ordered after cost tracking began: the cost valid at that moment (``order_time``).
    * Ordered before (imported history): the first recorded cost (``import_time``) — Shopify
      keeps no cost history, so this is the best available and is marked as such.
    * No cost known: ``(None, None)`` — never 0.
    """
    if not history:
        return None, None
    if ordered_at < history[0][0]:
        cost = history[0][1]
        return (cost, "import_time") if cost is not None else (None, None)
    valid = [cost for effective_from, cost in history if effective_from <= ordered_at][-1]
    return (valid, "order_time") if valid is not None else (None, None)


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


_LINK_SALES = (
    "UPDATE sales_entries s SET order_item_id = oi.id "
    "FROM order_items oi "
    "WHERE s.store_id = :store AND s.organization_id = :org "
    "AND s.order_item_id IS NULL AND s.external_line_item_id IS NOT NULL "
    "AND oi.organization_id = s.organization_id AND oi.order_id = s.order_id "
    "AND oi.external_line_item_id = s.external_line_item_id"
)
_LINK_SALES_FOR_ORDERS = _LINK_SALES + " AND s.order_id IN :orders"
_GROSS_TEMPLATE = (
    "UPDATE orders o SET gross_amount = CASE WHEN t.unknown = 0 THEN t.gross END "
    "FROM ("
    "  SELECT oi.order_id, SUM(oi.unit_price * oi.quantity) AS gross, "
    "         COUNT(*) FILTER (WHERE oi.unit_price IS NULL) AS unknown "
    "  FROM order_items oi JOIN orders po "
    "    ON po.id = oi.order_id AND po.organization_id = oi.organization_id "
    "  WHERE po.store_id = :store AND oi.organization_id = :org {only} "
    "  GROUP BY oi.order_id"
    ") t WHERE o.id = t.order_id AND o.organization_id = :org"
)
_GROSS = _GROSS_TEMPLATE.format(only="")
_GROSS_FOR_ORDERS = _GROSS_TEMPLATE.format(only="AND oi.order_id IN :orders")


def _resolve_links(
    session: Session, ctx: _Context, order_ids: list[uuid.UUID] | None = None
) -> None:
    """Rows whose platform parent arrived later in the export are linked now, and the order
    display total that needs every line (gross = sum of unit price times quantity) is set —
    empty when any line price is unknown. ``order_ids`` limits the work to those orders."""
    params: dict[str, Any] = {"store": ctx.store_id, "org": ctx.org_id}
    if order_ids is None:
        session.execute(text(_LINK_SALES), params)
        session.execute(text(_GROSS), params)
        return
    if not order_ids:
        return
    params["orders"] = order_ids
    orders: BindParameter[Any] = bindparam("orders", expanding=True)
    session.execute(text(_LINK_SALES_FOR_ORDERS).bindparams(orders), params)
    session.execute(text(_GROSS_FOR_ORDERS).bindparams(orders), params)


# ------------------------------------------------------------------ scheduled reconciliation
def enqueue_reconciliations(rt: Runtime, mode: SyncMode) -> int:
    """Start a ``reconcile`` (hourly) or ``deep`` (nightly) chain for every imported store that
    has no chain running. Returns how many were started.

    The store list comes from a narrow system-role read of ``stores`` (0007 grant); everything
    else runs under each store's tenant context.
    """
    with rt.db.transaction(system=True) as session:
        stores = session.execute(
            select(Store.id, Store.organization_id, Store.provider).where(
                Store.first_import_completed_at.is_not(None),
                Store.status.in_(("active", "error")),
            )
        ).all()
    started = 0
    now = rt.clock.now()
    for store_id, org_id, provider_code in stores:
        interval = _reconcile_interval(rt, provider_code)
        with rt.db.transaction(org_id=org_id) as session:
            store = session.get(Store, store_id)
            state = session.get(CommerceSyncState, store_id, with_for_update=True)
            if store is None or (state is not None and chain_running(rt, state)):
                continue
            if is_read_only(rt, session, org_id):
                continue
            last = state.last_reconciled_at if state is not None else None
            if mode is SyncMode.RECONCILE and last is not None and last > now - interval:
                continue  # checked recently enough for its platform (2B-06)
            start_sync(session, rt, store, mode)
            started += 1
    if started:
        logger.info("reconciliations_started", extra={"mode": mode.value, "count": started})
    return started


def _reconcile_interval(rt: Runtime, provider_code: str) -> timedelta:
    """How often a store of this platform is checked for changes: the platform's own interval
    (WooCommerce has no webhooks: every 15 minutes) or the default (hourly)."""
    try:
        provider = rt.providers.get(provider_code)
    except NotFound:
        return rt.settings.SCHEDULE_COMMERCE_RECONCILE_INTERVAL
    interval = getattr(provider, "reconcile_interval", None)
    if isinstance(interval, timedelta) and interval.total_seconds() > 0:
        return interval
    return rt.settings.SCHEDULE_COMMERCE_RECONCILE_INTERVAL


def request_reconcile(rt: Runtime, org_id: uuid.UUID, store_id: uuid.UUID) -> bool:
    """Ask for a reconciliation soon (e.g. an object too large to fetch on its own)."""
    with rt.db.transaction(org_id=org_id) as session:
        store = session.get(Store, store_id)
        state = session.get(CommerceSyncState, store_id, with_for_update=True)
        if store is None or store.first_import_completed_at is None:
            return False
        if state is not None and chain_running(rt, state):
            return False
        start_sync(session, rt, store, SyncMode.RECONCILE)
        return True


# ------------------------------------------------------------------ single-object updates
@dataclass(frozen=True)
class StoreRef:
    org_id: uuid.UUID
    store_id: uuid.UUID
    connection_id: uuid.UUID
    currency: str
    history_from: datetime | None


def apply_records(
    rt: Runtime, store: StoreRef, records: Iterable[CommerceRecord]
) -> dict[str, int]:
    """Apply fetched records (a webhook's object) with the same upserts and guards as the
    import, then resolve links. Cost rows are recorded as platform changes."""
    ctx = _Context(
        org_id=store.org_id,
        store_id=store.store_id,
        connection_id=store.connection_id,
        currency=store.currency,
        history_from=store.history_from,
        kind=BulkKind.ORDERS,
        operation_id=None,
        first_import=False,
        mode=SyncMode.RECONCILE,
    )
    materialized = list(records)
    counts = _apply(rt, ctx, materialized)
    order_refs = {
        r.order_external_id
        for r in materialized
        if isinstance(r, (CommerceOrderRecord, CommerceOrderLineRecord, CommerceSaleRecord))
        and not isinstance(r, CommerceOrderRecord)
    } | {r.external_id for r in materialized if isinstance(r, CommerceOrderRecord)}
    with rt.db.transaction(org_id=store.org_id) as session:
        ids = list(_order_ids(session, ctx, order_refs).values())
        _resolve_links(session, ctx, ids)
        store_row = session.get(Store, store.store_id)
        if store_row is not None and ids:
            recompute_days(session, rt, store_row, order_days(session, store_row, ids))
    return counts
