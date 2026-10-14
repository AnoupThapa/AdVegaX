"""Paged imports (task 2B-02, PHASE_02B_PLAN §9).

Platforms without bulk exports read history page by page. To test the framework before the
WooCommerce provider exists, the Shopify simulator's store is served through a provider that
declares ``PAGED_IMPORT`` instead of ``BULK_IMPORT``. The same store must end up exactly as
with bulk exports — same rows, same daily figures — however many pages it takes, and a stopped
import must resume from its saved cursor without duplicates.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from app.core.settings import Settings
from app.domains.commerce import importer
from app.domains.commerce.importer import SyncMode, enqueue_reconciliations
from app.domains.commerce.models import Store
from app.domains.jobs.service import ClaimedJob
from app.providers.base.capabilities import Capability, ProviderCapabilities
from app.providers.base.errors import (
    InvalidRequestError,
    OutboundTimeoutError,
    ProviderError,
)
from app.providers.base.types import BulkKind, CommercePage
from app.providers.shopify.bulk import ExportReader
from app.providers.shopify.provider import ShopifyProvider
from pydantic import ValidationError
from sqlalchemy import text

from tests.shopify_sim import (
    ShopifySim,
    build_provider,
    callback_params,
    sample_catalogue,
    sample_orders,
)

SHOP = "eve-zone.myshopify.com"


class PagedProvider(ShopifyProvider):
    """The simulator's store, served page by page (no bulk exports)."""

    capabilities = ProviderCapabilities(
        (ShopifyProvider.capabilities.supported - {Capability.BULK_IMPORT})
        | {Capability.PAGED_IMPORT}
    )

    def __init__(self, sim: ShopifySim, page_size: int, **kw: Any) -> None:
        super().__init__(**kw)
        self.sim = sim
        self.page_size = page_size
        self.calls: list[tuple[str, str | None, Any, Any]] = []
        self.fail_at: dict[int, ProviderError] = {}  # call number → error to raise

    def read_page(self, secrets, kind, cursor, *, created_since=None, updated_since=None):
        self.calls.append((kind.value, cursor, created_since, updated_since))
        error = self.fail_at.pop(len(self.calls), None)
        if error is not None:
            raise error
        shop = self.sim.shops[SHOP]
        nodes = shop.catalogue if kind is BulkKind.CATALOGUE else shop.orders
        lines = iter([json.dumps(n).encode() for n in nodes])
        records = list(ExportReader(kind).records(lines))
        start = int(cursor or 0)
        end = start + self.page_size
        more = end < len(records)
        return CommercePage(
            records=tuple(records[start:end]),
            next_cursor=str(end) if more else None,
            progress=min(100, end * 100 // len(records)) if records else 100,
        )


def _paged(sim: ShopifySim, clock: Any, page_size: int) -> PagedProvider:
    base = build_provider(sim, clock)
    return PagedProvider(
        sim,
        page_size,
        apps=base._apps,
        http_factory=sim.http_factory,
        api_version="2026-10",
        scopes=("read_products", "read_inventory", "read_orders"),
        clock=clock,
        install_max_age=timedelta(minutes=5),
        default_order_history=timedelta(days=60),
    )


@pytest.fixture
def sim():
    s = ShopifySim()
    s.add_shop(SHOP, catalogue=sample_catalogue(), orders=sample_orders())
    return s


def _link(make_client) -> Any:
    c = make_client()
    c.signup(f"paged-{uuid.uuid4().hex[:8]}@example.com")
    c.org = c.create_org("Paged Co")["id"]
    started = c.post(
        f"/organizations/{c.org}/connections/shopify/start", {"params": {"shop_domain": SHOP}}
    ).json()["data"]["authorize_url"]
    response = c.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    c.conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    (resource,) = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    c.resource = resource["id"]
    assert c.post(f"/organizations/{c.org}/resources/{c.resource}/link").status_code == 201
    return c


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _snapshot(admin_engine) -> dict[str, Any]:
    """Everything an import writes, without ids and timestamps that differ between runs."""
    return {
        "products": _rows(
            admin_engine, "SELECT external_product_id, title, status FROM products ORDER BY 1"
        ),
        "variants": _rows(
            admin_engine,
            "SELECT v.external_variant_id, v.sku, v.price, v.inventory_available, "
            "v.inventory_tracked, h.unit_cost, h.source FROM product_variants v "
            "LEFT JOIN product_cost_history h ON h.variant_id = v.id ORDER BY 1, 6",
        ),
        "orders": _rows(
            admin_engine,
            "SELECT external_order_id, gross_amount, tax_amount, refund_amount "
            "FROM orders ORDER BY 1",
        ),
        "lines": _rows(
            admin_engine,
            "SELECT external_line_item_id, quantity, unit_cost, cost_source, "
            "variant_id IS NOT NULL AS linked FROM order_items ORDER BY 1",
        ),
        "sales": _rows(
            admin_engine,
            "SELECT external_sale_id, action, line_type, amount, tax_amount, "
            "order_item_id IS NOT NULL AS linked FROM sales_entries ORDER BY 1",
        ),
        "refunds": _rows(
            admin_engine,
            "SELECT external_refund_id, total_amount, processed_at FROM refunds ORDER BY 1",
        ),
        "figures": _rows(
            admin_engine,
            "SELECT day, gross_sales, discounts, sales_reversals, net_sales, shipping, taxes, "
            "total_sales, orders_count, cogs, costed_net_sales, uncosted_lines "
            "FROM financial_daily ORDER BY day",
        ),
    }


def _bulk_snapshot(make_client, runtime, sim, clock, admin_engine) -> dict[str, Any]:
    runtime.providers.register(build_provider(sim, clock))
    _link(make_client)
    snap = _snapshot(admin_engine)
    with admin_engine.begin() as db:
        db.execute(text("TRUNCATE stores, external_connections, external_resources CASCADE"))
    runtime.providers._providers.pop("shopify")  # the next test step registers its own
    return snap


@pytest.mark.parametrize("page_size", [1, 3, 100])
def test_paged_import_matches_the_bulk_import(
    make_client, runtime, sim, clock, admin_engine, page_size
):
    expected = _bulk_snapshot(make_client, runtime, sim, clock, admin_engine)
    assert expected["figures"], "the bulk import produced figures to compare against"

    provider = _paged(sim, clock, page_size)
    runtime.providers.register(provider)
    sim.bulk_queries.clear()
    owner = _link(make_client)
    assert sim.bulk_queries == []  # nothing went through bulk exports
    assert _snapshot(admin_engine) == expected

    (store,) = owner.get(f"/organizations/{owner.org}/stores").json()["data"]
    assert (store["status"], store["sync"]["running"]) == ("active", False)
    (state,) = _rows(admin_engine, "SELECT * FROM commerce_sync_state")
    assert state["import_progress"] == 100
    assert (state["import_cursor"], state["import_counts"], state["import_job_id"]) == (
        None,
        None,
        None,
    )
    kinds = [c[0] for c in provider.calls]
    assert kinds == sorted(kinds)  # the catalogue first, then orders
    catalogue_records = len(
        list(
            ExportReader(BulkKind.CATALOGUE).records(
                iter([json.dumps(n).encode() for n in sim.shops[SHOP].catalogue])
            )
        )
    )
    assert kinds.count("catalogue") == max(1, -(-catalogue_records // page_size))
    # The orders read is limited to the allowed history; the catalogue is not filtered.
    first_orders = next(c for c in provider.calls if c[0] == "orders")
    assert first_orders[1] is None and first_orders[2] is not None
    assert all(c[2] is None for c in provider.calls if c[0] == "catalogue")


def test_counts_accumulate_over_pages_and_are_audited(
    make_client, runtime, sim, clock, admin_engine
):
    runtime.providers.register(_paged(sim, clock, page_size=2))
    _link(make_client)
    (completed,) = _rows(
        admin_engine,
        "SELECT metadata FROM audit_logs WHERE action = 'store.import_completed'",
    )
    (catalogue,) = _rows(
        admin_engine,
        "SELECT metadata FROM audit_logs WHERE action = 'store.catalogue_imported'",
    )
    assert catalogue["metadata"]["counts"]["products"] == 2
    assert catalogue["metadata"]["counts"]["variants"] == 3
    counts = completed["metadata"]["counts"]
    assert (counts["products"], counts["variants"], counts["orders"], counts["refunds"]) == (
        2,
        3,
        1,
        1,
    )
    assert counts["finance_days"] >= 1


def test_progress_is_saved_between_pages(make_client, runtime, sim, clock, admin_engine):
    provider = _paged(sim, clock, page_size=1)
    seen: list[tuple[str | None, int | None]] = []
    original = provider.read_page

    def spy(*args: Any, **kw: Any) -> CommercePage:
        (state,) = _rows(
            admin_engine, "SELECT import_cursor, import_progress FROM commerce_sync_state"
        )
        seen.append((state["import_cursor"], state["import_progress"]))
        return original(*args, **kw)

    provider.read_page = spy  # type: ignore[method-assign]
    runtime.providers.register(provider)
    _link(make_client)
    cursors = [c for c, _ in seen]
    assert cursors[0] is None and "1" in cursors  # each step resumes from the saved cursor
    progress = [p for _, p in seen]
    assert progress == sorted(progress)  # never goes backwards
    assert 0 < max(progress) < 100


def test_a_failed_page_is_retried_from_the_same_cursor(
    make_client, runtime, sim, clock, admin_engine
):
    expected = _bulk_snapshot(make_client, runtime, sim, clock, admin_engine)
    provider = _paged(sim, clock, page_size=2)
    provider.fail_at[3] = OutboundTimeoutError()
    runtime.providers.register(provider)
    owner = _link(make_client)
    # The failed step is retried later by the job framework; run that retry now.
    (state,) = _rows(admin_engine, "SELECT store_id, import_job_id FROM commerce_sync_state")
    assert state["import_job_id"] is not None and len(provider.calls) == 3
    retry = ClaimedJob(
        state["import_job_id"],
        uuid.UUID(owner.org),
        importer.JOB_IMPORT_STEP,
        str(state["store_id"]),
        2,
        5,
        None,
        None,
    )
    importer.import_step(runtime, retry)
    assert provider.calls[2][1] == provider.calls[3][1]  # the same page was asked again
    assert _snapshot(admin_engine) == expected  # nothing duplicated or lost


def test_a_permanent_error_ends_the_chain_and_clears_the_cursor(
    make_client, runtime, sim, clock, admin_engine
):
    provider = _paged(sim, clock, page_size=1)
    provider.fail_at[2] = InvalidRequestError()
    runtime.providers.register(provider)
    owner = _link(make_client)
    (store,) = owner.get(f"/organizations/{owner.org}/stores").json()["data"]
    assert (store["status"], store["sync"]["running"]) == ("error", False)
    assert store["sync"]["last_error_code"] == "invalid_request"
    (state,) = _rows(admin_engine, "SELECT import_cursor, import_counts FROM commerce_sync_state")
    assert (state["import_cursor"], state["import_counts"]) == (None, None)
    # Starting again (the import never finished, so it restarts) begins from the first page.
    provider.calls.clear()
    with runtime.db.transaction(org_id=uuid.UUID(owner.org)) as session:
        row = session.get(Store, uuid.UUID(store["id"]))
        importer.start_import(session, runtime, row, requested_by=None)
    assert provider.calls[0][1] is None
    (store,) = owner.get(f"/organizations/{owner.org}/stores").json()["data"]
    assert store["status"] == "active"


def test_hourly_check_reads_only_changes_through_pages(
    make_client, runtime, sim, clock, admin_engine
):
    provider = _paged(sim, clock, page_size=2)
    runtime.providers.register(provider)
    _link(make_client)
    provider.calls.clear()
    clock.advance(timedelta(hours=1))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    assert {c[0] for c in provider.calls} == {"catalogue", "orders"}
    assert all(c[3] is not None for c in provider.calls)  # "changed since" on every page


def test_a_provider_must_implement_what_it_declares(sim, clock):
    class DeclaresOnly(ShopifyProvider):
        capabilities = PagedProvider.capabilities

    declares = DeclaresOnly(
        apps=build_provider(sim, clock)._apps,
        http_factory=sim.http_factory,
        api_version="2026-10",
        scopes=("read_products",),
        clock=clock,
        install_max_age=timedelta(minutes=5),
        default_order_history=timedelta(days=60),
    )
    assert importer.commerce_provider(declares) is None  # no read_page: not an importer
    assert importer.commerce_provider(_paged(sim, clock, 1)) is not None
    assert importer.commerce_provider(build_provider(sim, clock)) is not None


def test_page_interval_cannot_be_negative():
    with pytest.raises(ValidationError, match="COMMERCE_PAGE_INTERVAL"):
        Settings(COMMERCE_PAGE_INTERVAL=timedelta(seconds=-1))  # type: ignore[call-arg]
