"""WooCommerce store addresses, REST client and SSRF hardening (task 2B-03, PLAN §6-§7).

No network: DNS is stubbed and the transport is ``httpx.MockTransport``. The client runs behind
the real ``SafeHttpClient``, so the SSRF policy, address pinning and limits are the real ones.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx
import pytest
from app.providers.base.errors import (
    BlockedDestinationError,
    InvalidRequestError,
    OutboundTimeoutError,
    PermissionDeniedError,
    RateLimitedError,
    ResourceNotFoundError,
    ResponseTooLargeError,
    RetryableError,
)
from app.providers.http.client import OutboundPolicy, SafeHttpClient
from app.providers.woocommerce.client import (
    MAX_PER_PAGE,
    AuthHeaderStrippedError,
    KeyRejectedError,
    StoreRedirectedError,
    UnexpectedResponseError,
    WooClient,
    WooCommerceApiNotFoundError,
)
from app.providers.woocommerce.stores import (
    StoreAddress,
    StoreAddressError,
    normalize_store_url,
)

PUBLIC = "93.184.216.34"
KEY, SECRET = "ck_test_0123456789", "cs_test_abcdefghij"
POLICY = OutboundPolicy(connect_timeout=1, read_timeout=1, max_response_bytes=4096, max_redirects=3)


# ------------------------------------------------------------------ store addresses
@pytest.mark.parametrize(
    ("raw", "host", "path"),
    [
        ("shop.example.com", "shop.example.com", ""),
        ("  HTTPS://Shop.Example.com/  ", "shop.example.com", ""),
        ("https://shop.example.com/wp-admin/admin.php?page=wc", "shop.example.com", ""),
        ("https://shop.example.com/wp-json/wc/v3", "shop.example.com", ""),
        ("https://example.com/shop/", "example.com", "/shop"),
        ("https://example.com/en/Shop/wp-login.php", "example.com", "/en/Shop"),
        ("https://example.com:443/store#top", "example.com", "/store"),
        ("https://bücher.example/", "xn--bcher-kva.example", ""),
    ],
)
def test_store_addresses_are_normalized(raw, host, path):
    address = normalize_store_url(raw)
    assert (address.host, address.path) == (host, path)
    assert address.base_url == f"https://{host}{path}"


def test_store_identity_ignores_path_case():
    assert normalize_store_url("example.com/Shop").account_id == "example.com/shop"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "invalid_store_url"),
        ("http://shop.example.com", "https_required"),
        ("ftp://shop.example.com", "invalid_store_url"),
        ("javascript:alert(1)", "invalid_store_url"),
        ("//shop.example.com", "invalid_store_url"),
        ("https://user:pass@shop.example.com", "credentials_in_url"),
        ("https://shop.example.com@evil.example", "credentials_in_url"),
        ("https://shop.example.com:8443", "port_not_allowed"),
        ("https://shop.example.com:80", "port_not_allowed"),
        ("https://127.0.0.1", "ip_literal_not_allowed"),
        ("https://2130706433", "ip_literal_not_allowed"),  # decimal 127.0.0.1
        ("https://0177.0.0.1", "ip_literal_not_allowed"),  # octal
        ("https://0x7f.0.0.1", "ip_literal_not_allowed"),  # hex
        ("https://[::1]", "ip_literal_not_allowed"),
        ("https://localhost", "internal_hostname"),
        ("https://shop.local", "internal_hostname"),
        ("https://metadata.google.internal", "internal_hostname"),
        ("https://example.com/../admin", "invalid_store_url"),
        ("https://example.com/sh op", "invalid_store_url"),
        ("https://example.com/a/b/c/d/e/f", "invalid_store_url"),
        ("https://example.com\\@evil.example", "invalid_store_url"),
        ("https://example.com/%2e%2e/", "invalid_store_url"),
        ("x" * 2049, "invalid_store_url"),
    ],
)
def test_unsafe_or_invalid_addresses_are_refused(raw, code):
    with pytest.raises(StoreAddressError) as caught:
        normalize_store_url(raw)
    assert str(caught.value) == code


# ------------------------------------------------------------------ the client
class Store:
    """A WooCommerce store behind a mock transport; records every request it receives."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []
        self.addresses: list[str] = [PUBLIC]

    def resolve(self, host: str, port: int) -> list[str]:
        return [self.addresses.pop(0) if len(self.addresses) > 1 else self.addresses[0]]

    def factory(self, policy: OutboundPolicy = POLICY):
        def make() -> SafeHttpClient:
            return SafeHttpClient(
                policy,
                resolver=self.resolve,
                transport=httpx.MockTransport(self._serve),
            )

        return make

    def _serve(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def ok(data: Any, **headers: str) -> httpx.Response:
    return httpx.Response(200, json=data, headers=headers)


def error(status: int, code: str | None = None, **headers: str) -> httpx.Response:
    body = {"code": code, "message": "sensitive detail", "data": {"status": status}}
    return httpx.Response(status, json=body if code else {"x": 1}, headers=headers)


def client_for(store: Store, address: str = "https://shop.example.com/shop", **kw: Any):
    return WooClient(
        store.factory(kw.pop("policy", POLICY)),
        normalize_store_url(address),
        consumer_key=KEY,
        consumer_secret=SECRET,
    )


def test_requests_use_basic_auth_over_https_and_never_put_keys_in_the_url():
    store = Store(lambda r: ok([{"id": 1}], **{"X-WP-Total": "7", "X-WP-TotalPages": "3"}))
    page = client_for(store).get_page("/orders", 2, 3, {"modified_after": "2026-10-01T00:00:00"})
    assert page.data == [{"id": 1}] and (page.total, page.total_pages) == (7, 3)
    (request,) = store.requests
    assert request.url.host == PUBLIC  # pinned to the checked address
    assert request.headers["host"] == "shop.example.com"
    assert request.url.path == "/shop/wp-json/wc/v3/orders"
    assert dict(request.url.params) == {
        "modified_after": "2026-10-01T00:00:00",
        "page": "2",
        "per_page": "3",
    }
    expected = base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
    assert request.headers["authorization"] == f"Basic {expected}"
    assert KEY not in str(request.url) and SECRET not in str(request.url)
    assert "consumer_key" not in str(request.url)


def test_the_public_index_is_read_without_credentials():
    store = Store(lambda r: ok({"name": "Eve", "timezone_string": "Australia/Sydney"}))
    assert client_for(store).index()["timezone_string"] == "Australia/Sydney"
    (request,) = store.requests
    assert request.url.path == "/shop/wp-json/"
    assert "authorization" not in request.headers


def test_the_client_never_shows_its_credentials():
    client = client_for(Store(lambda r: ok([])))
    assert KEY not in repr(client) and SECRET not in repr(client)
    assert KEY not in str(client) and SECRET not in str(client)


@pytest.mark.parametrize(
    ("response", "error_type", "code"),
    [
        (error(401, "woocommerce_rest_authentication_error"), KeyRejectedError, "key_rejected"),
        (
            error(401, "woocommerce_rest_cannot_view"),
            AuthHeaderStrippedError,
            "auth_header_stripped",
        ),
        (error(401), AuthHeaderStrippedError, "auth_header_stripped"),
        (error(403, "woocommerce_rest_cannot_view"), PermissionDeniedError, "permission_denied"),
        (error(404, "rest_no_route"), WooCommerceApiNotFoundError, "woocommerce_api_not_found"),
        (error(404, "woocommerce_rest_shop_order_invalid_id"), ResourceNotFoundError, "not_found"),
        (error(500), RetryableError, "retryable"),
        (error(503), RetryableError, "retryable"),
        (httpx.Response(200, text="<html>challenge</html>"), UnexpectedResponseError, None),
        (
            httpx.Response(200, text="{bad json", headers={"content-type": "application/json"}),
            UnexpectedResponseError,
            None,
        ),
        (ok("just a string"), UnexpectedResponseError, None),
    ],
)
def test_errors_become_codes_and_never_carry_the_body(response, error_type, code):
    store = Store(lambda r: response)
    with pytest.raises(error_type) as caught:
        client_for(store).get("/orders")
    if code is not None:
        assert caught.value.code == code
    assert "sensitive detail" not in str(caught.value)
    assert "challenge" not in str(caught.value)


def test_rate_limits_carry_a_bounded_retry_after():
    store = Store(lambda r: error(429, None, **{"Retry-After": "12"}))
    with pytest.raises(RateLimitedError) as caught:
        client_for(store).get("/orders")
    assert caught.value.retry_after_seconds == 12
    store = Store(lambda r: error(429, None, **{"Retry-After": "99999"}))
    with pytest.raises(RateLimitedError) as caught:
        client_for(store).get("/orders")
    assert caught.value.retry_after_seconds == 300
    store = Store(lambda r: error(429, None, **{"Retry-After": "soon"}))
    with pytest.raises(RateLimitedError) as caught:
        client_for(store).get("/orders")
    assert caught.value.retry_after_seconds is None


@pytest.mark.parametrize(
    "location", ["https://www.shop.example.com/shop/", "https://evil.example/", "/shop/en/"]
)
def test_redirects_are_never_followed_so_credentials_go_nowhere_else(location):
    store = Store(lambda r: httpx.Response(301, headers={"Location": location}))
    with pytest.raises(StoreRedirectedError):
        client_for(store).get("/orders")
    assert len(store.requests) == 1  # nothing was sent to the redirect target


def test_paging_headers_are_bounded():
    store = Store(lambda r: ok([], **{"X-WP-Total": "-1", "X-WP-TotalPages": "9" * 20}))
    page = client_for(store).get_page("/products", 1, MAX_PER_PAGE)
    assert (page.total, page.total_pages) == (None, None)
    with pytest.raises(ValueError):
        client_for(store).get_page("/products", 1, MAX_PER_PAGE + 1)
    not_a_list = Store(lambda r: ok({"not": "a list"}))
    with pytest.raises(UnexpectedResponseError):
        client_for(not_a_list).get_page("/products", 1, 10)


@pytest.mark.parametrize(
    "route", ["/../../wp-admin", "orders", "/orders?x=1", "/a b", "/" + "a" * 300]
)
def test_routes_are_fixed_paths(route):
    with pytest.raises(ValueError):
        client_for(Store(lambda r: ok([]))).get(route)


# ------------------------------------------------------------------ SSRF at request time
def test_dns_rebinding_after_connect_is_refused_on_the_next_request():
    store = Store(lambda r: ok([]))
    store.addresses = [PUBLIC, "10.0.0.5"]  # public at first, then an internal address
    client = client_for(store)
    client.get("/orders")
    with pytest.raises(BlockedDestinationError, match="resolves_to_blocked_address"):
        client.get("/orders")
    assert len(store.requests) == 1  # the internal address was never contacted


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "169.254.169.254", "::1", "fd00::1", "100.64.0.1"]
)
def test_a_store_name_that_resolves_internally_is_never_called(address):
    store = Store(lambda r: ok([]))
    store.addresses = [address]
    with pytest.raises(BlockedDestinationError):
        client_for(store).get("/orders")
    assert store.requests == []


def test_huge_bodies_are_cut_off():
    store = Store(
        lambda r: httpx.Response(
            200, content=b"[" + b"1," * 5000 + b"1]", headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(ResponseTooLargeError):
        client_for(store).get("/orders")


def test_a_slowly_dripping_body_hits_the_whole_request_deadline(monkeypatch):
    clock = {"now": 1000.0}

    def drip():
        for _ in range(50):
            clock["now"] += 1.0  # each chunk arrives a second later — under the read timeout
            yield b" "
        yield b"[]"

    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    store = Store(
        lambda r: httpx.Response(200, content=drip(), headers={"content-type": "application/json"})
    )
    policy = OutboundPolicy(
        connect_timeout=1,
        read_timeout=5,
        max_response_bytes=4096,
        max_redirects=0,
        request_timeout=10,
    )
    with pytest.raises(OutboundTimeoutError):
        client_for(store, policy=policy).get("/orders")


def test_credentials_are_required_for_api_calls_but_not_for_the_index():
    store = Store(lambda r: ok({"name": "x"}))
    anonymous = WooClient(store.factory(), StoreAddress("shop.example.com", ""))
    assert anonymous.index() == {"name": "x"}
    with pytest.raises(ValueError):
        anonymous.get("/orders")
    with pytest.raises(ValueError):
        WooClient(store.factory(), StoreAddress("shop.example.com", ""), consumer_key=KEY)


def test_error_bodies_are_read_only_for_their_code():
    body = json.dumps({"code": "x" * 500, "message": "m"})
    store = Store(lambda r: httpx.Response(401, text=body))
    with pytest.raises(AuthHeaderStrippedError):
        client_for(store).get("/orders")  # an oversized code is ignored, not echoed


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (httpx.Response(400, json={"code": "rest_invalid_param"}), InvalidRequestError),
        (httpx.Response(410, text="gone"), ResourceNotFoundError),
        (httpx.Response(204), UnexpectedResponseError),
        (httpx.Response(401, text="not json"), PermissionDeniedError),
    ],
)
def test_other_statuses(response, error_type):
    store = Store(lambda r: response)
    anonymous = WooClient(store.factory(), StoreAddress("shop.example.com", ""))
    with pytest.raises(error_type):
        anonymous.index()


def test_the_index_must_be_an_object():
    store = Store(lambda r: ok([1, 2]))
    with pytest.raises(UnexpectedResponseError):
        WooClient(store.factory(), StoreAddress("shop.example.com", "")).index()


@pytest.mark.parametrize("value", ["-5", "nan"])
def test_unusable_retry_after_is_ignored(value):
    store = Store(lambda r: error(429, None, **{"Retry-After": value}))
    with pytest.raises(RateLimitedError) as caught:
        client_for(store).get("/orders")
    assert caught.value.retry_after_seconds is None


def test_other_blocked_destinations_are_not_disguised_as_redirects():
    store = Store(lambda r: ok([]))
    store.addresses = ["10.1.2.3"]
    with pytest.raises(BlockedDestinationError):
        client_for(store).get("/orders")
