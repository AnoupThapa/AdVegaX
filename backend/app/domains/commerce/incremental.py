"""Webhook-driven updates: "object X changed" → fetch X by id → upsert (task 2A-07, PLAN §7).

A webhook body is never used as data (it is discarded at intake). Each delivery only says
which object changed; the job fetches that object's **current** state from the platform, so
arrival order does not matter and the importer's "newer wins" guard protects against races.

* Bursts for one object are coalesced: while a fetch for it is queued, further deliveries are
  recorded as ``ignored`` / ``coalesced`` — the queued fetch reads the latest state anyway.
* Deleted products are marked deleted (order history keeps them); deleted orders are removed.
* An object too large for one request is applied as far as fetched and the store is then
  reconciled through a bulk export.
* Stores still importing ignore single updates: the import's own reconciliation covers them.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.domains.commerce.importer import (
    StoreRef,
    apply_records,
    commerce_provider,
    request_reconcile,
)
from app.domains.commerce.models import Order, Product, ProductVariant, Store
from app.domains.finance.service import order_days, recompute_days
from app.domains.integrations.jobs import call_provider
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.integrations.tokens import usable_secrets
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError, create_job
from app.domains.webhooks.events import EventView, finish_event, load_event
from app.providers.base.errors import ProviderError
from app.providers.base.interfaces import CommerceProvider
from app.providers.base.types import ChangedObject, FetchResult, WebhookTarget
from app.runtime import Runtime

logger = logging.getLogger("advegax.commerce.incremental")

JOB_OBJECT_CHANGED = "commerce.object_changed"


def _coalesce_key(provider: str, account: str, object_id: str) -> str:
    return f"object-fetch:{provider}:{account}:{object_id}"


def schedule_fetch(
    session: Session,
    rt: Runtime,
    *,
    org_id: uuid.UUID,
    event_id: uuid.UUID,
    provider: str,
    account: str,
    object_id: str,
) -> bool:
    """Queue a fetch for this object unless one is already queued (returns False then)."""
    ttl = int(rt.settings.COMMERCE_FETCH_COALESCE.total_seconds())
    if not rt.redis.set(_coalesce_key(provider, account, object_id), "1", nx=True, ex=ttl):
        return False
    create_job(
        session,
        rt,
        organization_id=org_id,
        job_type=JOB_OBJECT_CHANGED,
        subject_type="webhook_event",
        subject_id=event_id,
        requested_by=None,
    )
    return True


@dataclass(frozen=True)
class _Target:
    store: StoreRef
    provider: CommerceProvider


def _resolve(rt: Runtime, event: EventView, org_id: uuid.UUID) -> _Target | str:
    """The store the event is about, or the reason it is ignored."""
    with rt.db.transaction(org_id=org_id) as session:
        row = session.execute(
            select(Store, ExternalConnection)
            .join(ExternalResource, ExternalResource.id == Store.external_resource_id)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .where(
                Store.organization_id == org_id,
                Store.provider == event.provider,
                Store.domain == event.account_id,
            )
            .order_by(Store.created_at.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return "store_not_imported"
        store, connection = row
        if store.first_import_completed_at is None:
            return "import_pending"  # the import's reconciliation picks this change up
        linked = session.execute(
            select(OrganizationResourceLink.id).where(
                OrganizationResourceLink.external_resource_id == store.external_resource_id,
                OrganizationResourceLink.status == "active",
            )
        ).first()
        if linked is None or connection.status != "active":
            return "store_not_syncing"
        provider = commerce_provider(rt.providers.get(connection.provider))
        if provider is None:
            return "unsupported"
        return _Target(
            StoreRef(
                org_id=org_id,
                store_id=store.id,
                connection_id=connection.id,
                currency=store.currency,
                history_from=store.history_from,
            ),
            provider,
        )


def object_changed(rt: Runtime, job: ClaimedJob) -> None:
    if job.subject_id is None or job.organization_id is None:
        raise JobSubjectGoneError()
    event = load_event(rt, uuid.UUID(job.subject_id))
    if event is None or event.organization_id != job.organization_id:
        raise JobSubjectGoneError()
    if event.status != "received":
        return  # already handled
    if event.object_external_id is None:
        finish_event(rt, event.id, "ignored", "no_object")
        return
    # From here on a new delivery for this object queues a new fetch.
    rt.redis.delete(_coalesce_key(event.provider, event.account_id, event.object_external_id))
    resolved = _resolve(rt, event, job.organization_id)
    if isinstance(resolved, str):
        finish_event(rt, event.id, "ignored", resolved)
        return
    target = resolved.provider.webhook_target(event.topic)
    try:
        outcome = _process(rt, resolved, target, event.object_external_id)
    except ProviderError as exc:
        if not exc.retryable or job.attempts >= job.max_attempts:
            finish_event(rt, event.id, "failed", str(exc) or exc.code)
        raise
    finish_event(rt, event.id, "processed", outcome)


def _process(rt: Runtime, target: _Target, what: WebhookTarget, object_id: str) -> str | None:
    """Apply one change; returns a short note for the event log (or None)."""
    store, provider = target.store, target.provider
    if what.object is ChangedObject.NONE:
        return "nothing_to_fetch"
    if what.deleted:
        _delete(rt, store, what.object, object_id)
        return "deleted"
    product_id = object_id
    if what.object is ChangedObject.INVENTORY_ITEM:
        found = _product_for_inventory_item(rt, store, object_id)
        if found is None:
            return "unknown_inventory_item"  # a new product: its own webhook brings it
        product_id = found
    secrets = usable_secrets(rt, store.org_id, store.connection_id)

    def fetch() -> FetchResult:
        if what.object is ChangedObject.ORDER:
            return provider.fetch_order(secrets, object_id)
        return provider.fetch_product(secrets, product_id)

    result = call_provider(rt, provider, store.org_id, store.connection_id, fetch)
    if not result.found:
        # Not visible to the app (deleted, a test order, or outside the allowed history):
        # deletions arrive as their own topic, so nothing is removed here.
        return "not_found"
    apply_records(rt, store, result.records)
    if not result.complete:
        request_reconcile(rt, store.org_id, store.store_id)
        return "partial_reconcile_requested"
    return None


def _product_for_inventory_item(rt: Runtime, store: StoreRef, item_id: str) -> str | None:
    with rt.db.transaction(org_id=store.org_id) as session:
        return session.execute(
            select(Product.external_product_id)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .where(
                ProductVariant.store_id == store.store_id,
                ProductVariant.external_inventory_item_id == item_id,
            )
            .limit(1)
        ).scalar_one_or_none()


def _delete(rt: Runtime, store: StoreRef, kind: ChangedObject, object_id: str) -> None:
    now = rt.clock.now()
    with rt.db.transaction(org_id=store.org_id) as session:
        if kind is ChangedObject.PRODUCT:
            # Marked, not removed: order lines keep pointing at the variant (A10, §8).
            product_ids = list(
                session.execute(
                    update(Product)
                    .where(
                        Product.store_id == store.store_id,
                        Product.external_product_id == object_id,
                    )
                    .values(status="deleted", updated_at=now)
                    .returning(Product.id)
                ).scalars()
            )
            if product_ids:
                session.execute(
                    update(ProductVariant)
                    .where(ProductVariant.product_id.in_(product_ids))
                    .values(deleted=True, updated_at=now)
                )
        elif kind is ChangedObject.ORDER:
            # A deleted order no longer exists in the store's reports: remove it with its
            # lines, sales and refunds (they cascade), then rebuild the days it touched.
            store_row = session.get(Store, store.store_id)
            order_ids = list(
                session.execute(
                    select(Order.id).where(
                        Order.store_id == store.store_id, Order.external_order_id == object_id
                    )
                ).scalars()
            )
            days = order_days(session, store_row, order_ids) if store_row else set()
            session.execute(delete(Order).where(Order.id.in_(order_ids)))
            if store_row is not None:
                recompute_days(session, rt, store_row, days)
