"""Shopify bulk exports: queries, operation state, JSONL mapping and the streaming download
(task 2A-06). No network, no database — the simulator answers over the real safe client."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from app.providers.base.errors import (
    BlockedDestinationError,
    InvalidRequestError,
    ResponseTooLargeError,
    RetryableError,
)
from app.providers.base.types import (
    BulkKind,
    BulkStatus,
    CommerceOrderLineRecord,
    CommerceOrderRecord,
    CommerceProductRecord,
    CommerceRefundRecord,
    CommerceSaleRecord,
    CommerceVariantRecord,
)
from app.providers.http.client import DownloadExpiredError, OutboundPolicy, SafeHttpClient
from app.providers.shopify.bulk import CATALOGUE_QUERY, ExportReader, orders_query, parse_state

from tests.shopify_sim import (
    BULK_HOST,
    PUBLIC_IP,
    ShopifySim,
    build_provider,
    sample_catalogue,
    sample_orders,
)

SHOP = "eve-zone.myshopify.com"
SECRETS = {"shop": SHOP, "access_token": "shpat_sim_access_1"}


def _lines(nodes):
    return iter(json.dumps(n).encode() for n in nodes)


# ------------------------------------------------------------------ queries
def _connections(query: str) -> int:
    return len(re.findall(r"edges\s*\{", query))


def test_queries_stay_within_shopify_bulk_limits_and_ask_for_no_personal_data():
    orders = orders_query(datetime(2026, 8, 14, 9, 30, tzinfo=UTC))
    assert _connections(CATALOGUE_QUERY) == 2
    assert _connections(orders) == 4  # ≤ 5 connections; nesting orders > agreements > sales
    for query in (CATALOGUE_QUERY, orders):
        for field in ("customer", "email", "phone", "Address", "firstName", "lastName"):
            assert field not in query
    assert "created_at:>='2026-08-14T09:30:00Z'" in orders
    assert "(query:" not in orders_query(None)


def test_history_window_depends_on_read_all_orders(clock):
    provider = build_provider(ShopifySim(), clock)
    assert provider.history_limit(("read_orders",)).days == 60
    assert provider.history_limit(("read_orders", "read_all_orders")) is None


# ------------------------------------------------------------------ operation state
@pytest.mark.parametrize(
    ("node", "status", "error"),
    [
        ({"status": "CREATED"}, BulkStatus.RUNNING, None),
        ({"status": "RUNNING", "objectCount": "57"}, BulkStatus.RUNNING, None),
        ({"status": "COMPLETED", "url": "https://x/y"}, BulkStatus.COMPLETED, None),
        ({"status": "FAILED", "errorCode": "ACCESS_DENIED"}, BulkStatus.FAILED, "access_denied"),
        ({"status": "CANCELED"}, BulkStatus.FAILED, "canceled"),
        ({"status": "SOMETHING_NEW"}, BulkStatus.FAILED, "something_new"),
        (None, BulkStatus.FAILED, "operation_missing"),
    ],
)
def test_operation_state_is_normalized(node, status, error):
    state = parse_state(node)
    assert (state.status, state.error_code) == (status, error)


def test_result_url_never_appears_in_repr():
    state = parse_state({"status": "COMPLETED", "url": "https://x/y?signature=secret"})
    assert state.result_url and "signature" not in repr(state)


# ------------------------------------------------------------------ mapping
def test_catalogue_mapping():
    records = list(ExportReader(BulkKind.CATALOGUE).records(_lines(sample_catalogue())))
    products = [r for r in records if isinstance(r, CommerceProductRecord)]
    variants = {r.external_id: r for r in records if isinstance(r, CommerceVariantRecord)}
    assert [(p.title, p.status) for p in products] == [
        ("Nitrile Gloves", "active"),
        ("Gift Wrap", "unlisted"),
    ]
    medium = variants["gid://shopify/ProductVariant/11"]
    assert medium.product_external_id == "gid://shopify/Product/1"
    assert (medium.price, medium.unit_cost, medium.cost_currency) == (
        Decimal("19.90"),
        Decimal("7.25"),
        "AUD",
    )
    assert (medium.inventory_tracked, medium.inventory_available) == (True, 120)
    large = variants["gid://shopify/ProductVariant/12"]
    assert large.unit_cost is None  # no cost, or hidden by staff permissions → unknown, not 0
    assert large.inventory_available == 0  # tracked and really zero
    untracked = variants["gid://shopify/ProductVariant/21"]
    assert (untracked.inventory_tracked, untracked.inventory_available) == (False, None)


def test_orders_mapping_excludes_test_orders_and_dates_reversals_by_processing():
    reader = ExportReader(BulkKind.ORDERS)
    records = list(reader.records(_lines(sample_orders())))
    orders = [r for r in records if isinstance(r, CommerceOrderRecord)]
    assert [o.external_id for o in orders] == ["gid://shopify/Order/500"]
    (order,) = orders
    assert order.order_number == "#1001"
    assert order.financial_status == "partially_refunded"
    assert order.total_amount == Decimal("63.80")
    refunds = [r for r in records if isinstance(r, CommerceRefundRecord)]
    assert [(r.external_id, r.total_amount) for r in refunds] == [
        ("gid://shopify/Refund/900", Decimal("21.89"))
    ]
    lines = [r for r in records if isinstance(r, CommerceOrderLineRecord)]
    assert {line.external_id for line in lines} == {
        "gid://shopify/LineItem/601",
        "gid://shopify/LineItem/602",
    }
    sales = {r.external_id: r for r in records if isinstance(r, CommerceSaleRecord)}
    assert set(sales) == {f"gid://shopify/Sale/{n}" for n in (801, 802, 803, 804)}
    sale, shipping, reversal = (
        sales["gid://shopify/Sale/801"],
        sales["gid://shopify/Sale/803"],
        sales["gid://shopify/Sale/804"],
    )
    assert (sale.action, sale.line_type, sale.agreement_reason) == ("order", "product", "order")
    assert sale.line_item_external_id == "gid://shopify/LineItem/601"
    assert (shipping.line_type, shipping.line_item_external_id) == ("shipping", None)
    assert (reversal.action, reversal.agreement_reason) == ("return", "refund")
    assert reversal.amount == Decimal("-20.79")
    assert reversal.happened_at == datetime(2026, 10, 8, 3, tzinfo=UTC)  # processing date
    assert sale.happened_at == datetime(2026, 10, 5, 1, 30, tzinfo=UTC)
    assert reader.skipped_lines == 0


def test_unknown_enum_values_map_to_other_and_bad_lines_are_counted():
    reader = ExportReader(BulkKind.ORDERS)
    nodes = [
        {
            "id": "o",
            "processedAt": "2026-10-01T00:00:00Z",
            "currencyCode": "AUD",
            "test": False,
        },
        {"id": "a", "happenedAt": "2026-10-01T00:00:00Z", "reason": "NEW", "__parentId": "o"},
        {
            "id": "s",
            "actionType": "NEW",
            "lineType": "NEW",
            "totalAmount": {"shopMoney": {"amount": "1", "currencyCode": "AUD"}},
            "__parentId": "a",
        },
        {"id": "s2", "actionType": "ORDER", "lineType": "TIP", "__parentId": "a"},  # no amount
        {"no": "id"},
        {"id": "orphan", "actionType": "ORDER", "__parentId": "unknown-agreement"},
    ]
    lines = [*(json.dumps(n).encode() for n in nodes), b"{not json", b"[1]"]
    records = list(reader.records(iter(lines)))
    sales = [r for r in records if isinstance(r, CommerceSaleRecord)]
    assert [(s.action, s.line_type, s.agreement_reason) for s in sales] == [
        ("other", "other", "other")
    ]
    assert sales[0].discount_amount == Decimal(0)
    assert reader.skipped_lines == 4  # no amount, no id, bad JSON, not an object


# ------------------------------------------------------------------ provider calls
@pytest.fixture
def sim():
    s = ShopifySim()
    s.add_shop(SHOP, catalogue=sample_catalogue(), orders=sample_orders())
    return s


def test_bulk_export_round_trip(sim, clock):
    provider = build_provider(sim, clock)
    op = provider.start_bulk_export(SECRETS, BulkKind.CATALOGUE, since=None)
    assert op == "gid://shopify/BulkOperation/1"
    assert "products" in sim.bulk_queries[0]
    state = provider.bulk_export_state(SECRETS, op)
    assert state.status is BulkStatus.COMPLETED
    assert state.object_count == 5
    records = list(provider.read_bulk_export(state.result_url, BulkKind.CATALOGUE))
    assert len(records) == 5
    download = sim.calls("/sim/bulk-1.jsonl")[0]
    assert "x-shopify-access-token" not in download.headers  # signed URL: no token sent


def test_bulk_user_errors_are_a_permanent_failure_without_the_message(sim, clock):
    sim.bulk_user_errors = True
    with pytest.raises(InvalidRequestError) as caught:
        build_provider(sim, clock).start_bulk_export(SECRETS, BulkKind.ORDERS, since=None)
    assert caught.value.code == "bulk_export_rejected"
    assert "Invalid query" not in str(caught.value)


def test_download_host_must_be_allowlisted(sim, clock):
    provider = build_provider(sim, clock)
    with pytest.raises(BlockedDestinationError):
        list(provider.read_bulk_export(f"https://{SHOP}/file.jsonl", BulkKind.CATALOGUE))


@pytest.mark.parametrize(
    ("status", "error"),
    [(403, DownloadExpiredError), (410, DownloadExpiredError), (503, RetryableError)],
)
def test_download_errors(sim, clock, status, error):
    provider = build_provider(sim, clock)
    op = provider.start_bulk_export(SECRETS, BulkKind.CATALOGUE, since=None)
    url = provider.bulk_export_state(SECRETS, op).result_url
    sim.download_status = status
    with pytest.raises(error):
        list(provider.read_bulk_export(url, BulkKind.CATALOGUE))


@pytest.mark.parametrize(
    "secrets", [{}, {"shop": "evil.example", "access_token": "x"}, {"shop": SHOP}]
)
def test_incomplete_credentials_mean_reconnect(sim, clock, secrets):
    from app.providers.base.errors import AuthExpiredError

    with pytest.raises(AuthExpiredError):
        build_provider(sim, clock).start_bulk_export(secrets, BulkKind.CATALOGUE, since=None)


# ------------------------------------------------------------------ streaming client
def _client(handler, **policy):
    base = {
        "connect_timeout": 1,
        "read_timeout": 1,
        "max_response_bytes": 1000,
        "max_redirects": 0,
    }
    return SafeHttpClient(
        OutboundPolicy(**{**base, **policy}),
        resolver=lambda host, port: [PUBLIC_IP],
        transport=httpx.MockTransport(handler),
    )


def _allowed(host: str) -> bool:
    return host == BULK_HOST


def test_streaming_yields_lines_beyond_the_normal_response_limit():
    body = b"".join(b'{"n": %d}\n' % i for i in range(500)) + b'{"n": "last-no-newline"}'
    client = _client(lambda request: httpx.Response(200, content=body))
    lines = list(client.stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))
    assert len(lines) == 501  # far more than the 1,000-byte whole-response cap
    assert lines[-1] == b'{"n": "last-no-newline"}'


def test_streaming_enforces_the_download_size_limit():
    client = _client(
        lambda request: httpx.Response(200, content=b"x\n" * 1000), max_download_bytes=1024
    )
    with pytest.raises(ResponseTooLargeError):
        list(client.stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))
    declared = _client(
        lambda request: httpx.Response(200, headers={"content-length": "999999"}, content=b""),
        max_download_bytes=1024,
    )
    with pytest.raises(ResponseTooLargeError):
        list(declared.stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))


def test_streaming_refuses_one_huge_line(monkeypatch):
    from app.providers.http import client as client_module

    monkeypatch.setattr(client_module, "MAX_LINE_BYTES", 10)
    client = _client(lambda request: httpx.Response(200, content=b"x" * 50))
    with pytest.raises(ResponseTooLargeError):
        list(client.stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))


def test_streaming_enforces_the_time_limit():
    client = _client(lambda request: httpx.Response(200, content=b"a\n"), download_timeout=-1)
    from app.providers.base.errors import OutboundTimeoutError

    with pytest.raises(OutboundTimeoutError):
        list(client.stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(302, headers={"location": "https://elsewhere/"}), BlockedDestinationError),
        (httpx.Response(429), RetryableError),
        (httpx.Response(304), InvalidRequestError),
    ],
)
def test_streaming_status_handling(response, error):
    client = _client(lambda request: response)
    with pytest.raises(error):
        list(client.stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))


def test_streaming_maps_transport_failures():
    from app.providers.base.errors import OutboundTimeoutError

    def timeout(request):
        raise httpx.ReadTimeout("slow")

    def broken(request):
        raise httpx.ConnectError("down")

    with pytest.raises(OutboundTimeoutError):
        list(_client(timeout).stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))
    with pytest.raises(RetryableError):
        list(_client(broken).stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))


def test_streaming_still_blocks_private_addresses():
    client = SafeHttpClient(
        OutboundPolicy(connect_timeout=1, read_timeout=1, max_response_bytes=10, max_redirects=0),
        resolver=lambda host, port: ["10.0.0.5"],
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    with pytest.raises(BlockedDestinationError):
        list(client.stream_lines(f"https://{BULK_HOST}/f", allowed_host=_allowed))
