"""Carrying out platform privacy requests (task 2A-07; Shopify's mandatory privacy webhooks).

* ``customers/data_request`` and ``customers/redact``: AdVegaX stores **no customer personal
  data** (Q8) — no names, emails, phones or addresses, and in 2A not even the hashed customer
  key. The request is answered by recording that nothing is held, and the customer id that
  arrived with the request is removed from the intake log.
* ``shop/redact`` (sent 48 hours after uninstall): every row imported for that store is
  deleted — products, variants, costs, orders, lines, sales, refunds, daily figures and sync
  state (they cascade from ``stores``). If the store was connected again in the meantime, the
  request is not applied (the merchant is using AdVegaX again) and this is recorded.

Each outcome is audited. Shopify allows 30 days; these run within minutes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select

from app.domains.audit.service import Actor, record_audit
from app.domains.commerce.models import Order, Product, Store
from app.domains.integrations.models import ExternalConnection
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError
from app.domains.webhooks.events import EventView, finish_event, load_event
from app.runtime import Runtime

JOB_CUSTOMER_DATA_REQUEST = "privacy.customer_data_request"
JOB_CUSTOMER_REDACT = "privacy.customer_redact"
JOB_SHOP_REDACT = "privacy.shop_redact"
SYSTEM = Actor("system", None)


def _event(rt: Runtime, job: ClaimedJob) -> EventView | None:
    if job.subject_id is None or job.organization_id is None:
        raise JobSubjectGoneError()
    event = load_event(rt, uuid.UUID(job.subject_id))
    if event is None or event.organization_id != job.organization_id:
        raise JobSubjectGoneError()
    return event if event.status == "received" else None


def _audit(rt: Runtime, org_id: uuid.UUID, event: EventView, action: str, **meta: object) -> None:
    with rt.db.transaction(org_id=org_id) as session:
        record_audit(
            session,
            organization_id=org_id,
            actor=SYSTEM,
            action=action,
            resource_type="webhook_event",
            resource_id=event.id,
            metadata={"topic": event.topic, "store": event.account_id, **meta},
        )


def customer_data_request(rt: Runtime, job: ClaimedJob) -> None:
    event = _event(rt, job)
    if event is None:
        return
    assert job.organization_id is not None
    _audit(rt, job.organization_id, event, "privacy.data_request_answered", personal_data=False)
    finish_event(rt, event.id, "processed", "no_personal_data_held", clear_object=True)


def customer_redact(rt: Runtime, job: ClaimedJob) -> None:
    event = _event(rt, job)
    if event is None:
        return
    assert job.organization_id is not None
    _audit(rt, job.organization_id, event, "privacy.customer_redacted", personal_data=False)
    finish_event(rt, event.id, "processed", "no_personal_data_held", clear_object=True)


def shop_redact(rt: Runtime, job: ClaimedJob) -> None:
    event = _event(rt, job)
    if event is None:
        return
    org_id = job.organization_id
    assert org_id is not None
    with rt.db.transaction(org_id=org_id) as session:
        live = session.execute(
            select(ExternalConnection.id).where(
                ExternalConnection.organization_id == org_id,
                ExternalConnection.provider == event.provider,
                ExternalConnection.external_account_id == event.account_id,
                ExternalConnection.status != "revoked",
            )
        ).first()
    if live is not None:
        _audit(rt, org_id, event, "privacy.shop_redact_skipped", reason="store_reconnected")
        finish_event(rt, event.id, "ignored", "store_reconnected")
        return
    with rt.db.transaction(org_id=org_id) as session:
        store_ids = list(
            session.execute(
                select(Store.id).where(
                    Store.organization_id == org_id,
                    Store.provider == event.provider,
                    Store.domain == event.account_id,
                )
            ).scalars()
        )
        counts = {"stores": len(store_ids), "orders": 0, "products": 0}
        if store_ids:
            counts["orders"] = int(
                session.execute(
                    select(func.count()).select_from(Order).where(Order.store_id.in_(store_ids))
                ).scalar_one()
            )
            counts["products"] = int(
                session.execute(
                    select(func.count()).select_from(Product).where(Product.store_id.in_(store_ids))
                ).scalar_one()
            )
            session.execute(delete(Store).where(Store.id.in_(store_ids)))
    _audit(rt, org_id, event, "privacy.shop_redacted", counts=counts)
    finish_event(rt, event.id, "processed", "store_data_erased" if store_ids else "nothing_held")
