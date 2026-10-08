"""Email delivery tasks. Tasks receive IDs only; each opens its own system-role unit of work."""

from __future__ import annotations

import uuid
from functools import lru_cache

from app.core.settings import get_settings
from app.domains.notifications.delivery import DeliveryOutcome, deliver, due_outbox_ids
from app.runtime import Runtime, build_runtime
from app.workers.celery_app import celery_app


@lru_cache
def worker_runtime() -> Runtime:
    return build_runtime(get_settings())


def deliver_now(outbox_id: uuid.UUID) -> DeliveryOutcome:
    rt = worker_runtime()
    result = deliver(rt.db, rt.settings, rt.sender, outbox_id)
    if result.outcome is DeliveryOutcome.RETRY and result.retry_in is not None:
        deliver_email.apply_async(
            args=[str(outbox_id)], countdown=int(result.retry_in.total_seconds())
        )
    return result.outcome


@celery_app.task(name="advegax.email.deliver")  # type: ignore[untyped-decorator]
def deliver_email(outbox_id: str) -> str:
    return deliver_now(uuid.UUID(outbox_id)).value


def deliver_pending() -> int:
    """Deliver every due outbox email (manual sweep until the 1B scheduler exists)."""
    rt = worker_runtime()
    return sum(
        1
        for oid in due_outbox_ids(rt.db)
        if deliver(rt.db, rt.settings, rt.sender, oid).outcome is DeliveryOutcome.SENT
    )


if __name__ == "__main__":  # pragma: no cover - operational entry point
    print(f"delivered={deliver_pending()}")
