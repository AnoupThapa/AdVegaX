"""SSRF boundary for externally supplied destinations (A11, A16).

Destinations are validated on the hostname string, again after DNS resolution (every address),
and again for every redirect target. No real network access is needed: DNS is stubbed and the
HTTP transport is replaced by ``httpx.MockTransport``.
"""

from __future__ import annotations

import httpx
import pytest
from app.providers.base.errors import (
    BlockedDestinationError,
    OutboundTimeoutError,
    ResponseTooLargeError,
    RetryableError,
)
from app.providers.http.client import OutboundPolicy, SafeHttpClient
from app.providers.http.policy import default_resolver, is_blocked_address, validate_destination

PUBLIC = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
POLICY = OutboundPolicy(connect_timeout=2, read_timeout=5, max_response_bytes=1024, max_redirects=3)
PORTS = frozenset({443})


def resolver_for(mapping: dict[str, list[str]]):
    def resolve(host: str, port: int) -> list[str]:
        return mapping.get(host, [PUBLIC])

    return resolve


def check(url: str, mapping: dict[str, list[str]] | None = None):
    return validate_destination(url, resolver=resolver_for(mapping or {}), allowed_ports=PORTS)


def blocked(url: str, reason: str, mapping: dict[str, list[str]] | None = None) -> None:
    with pytest.raises(BlockedDestinationError, match=reason):
        check(url, mapping)


# --- URL and hostname checks ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://shop.example.com/",
        "file:///etc/passwd",
        "gopher://shop.example.com/",
        "ftp://shop.example.com/",
        "javascript:alert(1)",
        "//shop.example.com/",
    ],
)
def test_unsupported_schemes(url):
    blocked(url, "scheme_not_allowed")


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@shop.example.com/",
        "https://user@shop.example.com/",
        "https://shop.example.com@169.254.169.254/",
    ],
)
def test_credentials_in_url(url):
    blocked(url, "credentials_in_url")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.1/",
        "https://2130706433/",
        "https://0x7f000001/",
        "https://0x7f.1/",
        "https://017700000001/",
        "https://127.1/",
        "https://[::ffff:127.0.0.1]/",
        "https://[fd00::1]/",
        "https://8.8.8.8/",
    ],
)
def test_ip_literals_and_unusual_encodings(url):
    blocked(url, "ip_literal_not_allowed")


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/",
        "https://LOCALHOST./",
        "https://api.localhost/",
        "https://metadata.google.internal/",
        "https://db.internal/",
        "https://printer.local/",
        "https://router.home.arpa/",
    ],
)
def test_internal_hostnames(url):
    blocked(url, "internal_hostname")


@pytest.mark.parametrize("url", ["https://intranet/", "https://a..b.com/", "https://-/"])
def test_invalid_hostnames(url):
    with pytest.raises(BlockedDestinationError):
        check(url)


def test_ports():
    blocked("https://shop.example.com:8443/", "port_not_allowed")
    blocked("https://shop.example.com:22/", "port_not_allowed")
    blocked("https://shop.example.com:99999/", "invalid_port")
    assert check("https://shop.example.com:443/x").port == 443


# --- post-resolution checks ------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.255.255.254",
        "0.0.0.0",
        "10.1.2.3",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.169.254",
        "169.254.0.1",
        "100.64.0.1",
        "100.127.255.255",
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "192.0.0.1",
        "198.18.0.1",
        "192.0.2.1",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd12:3456::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:10.0.0.1",
        "64:ff9b::a9fe:a9fe",
        "2002:7f00:1::1",
        "2001:0:4136:e378::1",
        "fd00:ec2::254",
    ],
)
def test_names_resolving_to_blocked_addresses(address):
    blocked(
        "https://evil.example.com/", "resolves_to_blocked_address", {"evil.example.com": [address]}
    )


def test_any_blocked_address_rejects_the_whole_name():
    blocked(
        "https://mixed.example.com/",
        "resolves_to_blocked_address",
        {"mixed.example.com": [PUBLIC, "10.0.0.5"]},
    )


def test_public_addresses_allowed_and_pinned():
    dest = check(
        "https://shop.example.com/wp-json/wc/v3/orders?page=2",
        {"shop.example.com": [PUBLIC, PUBLIC_V6]},
    )
    assert (dest.host, dest.port, dest.address) == ("shop.example.com", 443, PUBLIC)
    assert dest.path == "/wp-json/wc/v3/orders?page=2"
    assert not is_blocked_address(__import__("ipaddress").ip_address(PUBLIC_V6))


def test_idna_hostnames_are_normalized():
    assert check("https://BÜCHER.example/").host == "xn--bcher-kva.example"


def test_empty_or_invalid_resolution():
    blocked("https://nx.example.com/", "dns_resolution_failed", {"nx.example.com": []})
    blocked("https://bad.example.com/", "invalid_resolved_address", {"bad.example.com": ["nope"]})


def test_default_resolver_failure_is_blocked():
    with pytest.raises(BlockedDestinationError, match="dns_resolution_failed"):
        default_resolver("does-not-exist.invalid", 443)


# --- client behaviour: pinning, rebinding, redirects, limits, timeouts --------------------


def make_client(handler, mapping=None, policy=POLICY):
    return SafeHttpClient(
        policy, resolver=resolver_for(mapping or {}), transport=httpx.MockTransport(handler)
    )


def test_connection_is_pinned_to_validated_address_with_original_sni_and_host():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ok")

    client = make_client(handler, {"shop.example.com": [PUBLIC]})
    response = client.request(
        "GET", "https://shop.example.com/api?x=1", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 200
    assert response.content == b"ok"
    request = seen[0]
    assert request.url.host == PUBLIC
    assert request.url.path == "/api"
    assert request.headers["host"] == "shop.example.com"
    assert request.extensions["sni_hostname"] == "shop.example.com"


def test_dns_rebinding_cannot_switch_the_connected_address():
    answers = iter([[PUBLIC], ["127.0.0.1"]])
    seen = []

    def resolver(host: str, port: int) -> list[str]:
        return next(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200)

    client = SafeHttpClient(POLICY, resolver=resolver, transport=httpx.MockTransport(handler))
    client.request("GET", "https://rebind.example.com/")
    assert seen == [PUBLIC]  # resolved once, pinned; the second (private) answer is never used


def test_redirect_to_private_address_is_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://shop.example.com/next"})

    client = make_client(handler, {"shop.example.com": [PUBLIC]})
    answers = iter([[PUBLIC], ["169.254.169.254"]])
    client._resolver = lambda host, port: next(answers)  # second lookup rebinds to metadata IP
    with pytest.raises(BlockedDestinationError, match="resolves_to_blocked_address"):
        client.request("GET", "https://shop.example.com/")


@pytest.mark.parametrize(
    "location",
    [
        "https://other.example.com/",
        "https://169.254.169.254/latest",
        "http://shop.example.com/",
        "https://localhost/admin",
        "file:///etc/passwd",
    ],
)
def test_redirect_targets_are_revalidated(location):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(BlockedDestinationError):
        make_client(handler).request("GET", "https://shop.example.com/")


def test_same_host_redirect_followed_without_credentials_and_hop_limit():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/start":
            return httpx.Response(303, headers={"location": "/final"})
        return httpx.Response(200, content=b"done")

    response = make_client(handler).request(
        "POST",
        "https://shop.example.com/start",
        headers={"Authorization": "Bearer secret"},
        json={"a": 1},
    )
    assert response.content == b"done"
    assert seen == [("POST", "/start", "Bearer secret"), ("GET", "/final", None)]

    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(BlockedDestinationError, match="too_many_redirects"):
        make_client(loop).request("GET", "https://shop.example.com/")


def test_redirect_without_location_is_returned():
    response = make_client(lambda r: httpx.Response(302)).request(
        "GET", "https://shop.example.com/"
    )
    assert response.status_code == 302


def test_response_size_limits():
    declared = make_client(
        lambda r: httpx.Response(200, headers={"content-length": "999999"}, content=b"x")
    )
    with pytest.raises(ResponseTooLargeError):
        declared.request("GET", "https://shop.example.com/")

    def streamed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=iter([b"x" * 600, b"y" * 600]))

    with pytest.raises(ResponseTooLargeError):
        make_client(streamed).request("GET", "https://shop.example.com/")


def test_timeouts_and_transport_errors_are_mapped():
    def slow(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["connect"] == POLICY.connect_timeout
        assert request.extensions["timeout"]["read"] == POLICY.read_timeout
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(OutboundTimeoutError):
        make_client(slow).request("GET", "https://shop.example.com/")

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(RetryableError, match="transport_error"):
        make_client(refused).request("GET", "https://shop.example.com/")


def test_ipv6_pinning_uses_brackets():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(204)

    make_client(handler, {"v6.example.com": [PUBLIC_V6]}).request("GET", "https://v6.example.com/")
    assert seen[0].startswith(f"https://[{PUBLIC_V6}]")


def test_client_ignores_ambient_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    client = SafeHttpClient(POLICY)
    assert client._client._trust_env is False
    client.close()
