"""SSRF-safe outbound HTTP client — the only HTTP client providers may use (A11).

Connections are pinned to the address validated by ``policy.validate_destination`` while TLS
SNI and certificate verification still use the original hostname, defeating DNS rebinding.
Redirects are never followed automatically: each target is re-validated, cross-host redirects
are refused, credentials are not forwarded, and the hop count is limited.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.providers.base.errors import (
    BlockedDestinationError,
    InvalidRequestError,
    OutboundTimeoutError,
    ResponseTooLargeError,
    RetryableError,
)
from app.providers.http.policy import Destination, Resolver, default_resolver, validate_destination

logger = logging.getLogger("advegax.outbound")

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_LINE_BYTES = 16 * 1024 * 1024  # one JSONL record; larger means a malformed export
_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization", "x-api-key"})


@dataclass(frozen=True)
class OutboundPolicy:
    connect_timeout: float
    read_timeout: float
    max_response_bytes: int
    max_redirects: int
    allowed_ports: frozenset[int] = frozenset({443})
    # Streaming downloads (2A-06): overall size and wall-clock limits.
    max_download_bytes: int = 2 * 1024 * 1024 * 1024
    download_timeout: float = 3600.0


@dataclass(frozen=True)
class SafeResponse:
    status_code: int
    headers: httpx.Headers
    content: bytes = field(repr=False)
    host: str


def _url_for(dest: Destination) -> str:
    host = f"[{dest.address}]" if ":" in dest.address else dest.address
    return f"https://{host}:{dest.port}{dest.path}"


def _host_header(dest: Destination) -> str:
    return dest.host if dest.port == 443 else f"{dest.host}:{dest.port}"


class SafeHttpClient:
    def __init__(
        self,
        policy: OutboundPolicy,
        *,
        resolver: Resolver = default_resolver,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._policy = policy
        self._resolver = resolver
        self._client = httpx.Client(
            transport=transport or httpx.HTTPTransport(retries=0),
            follow_redirects=False,
            trust_env=False,  # never route through ambient proxies that would bypass pinning
            timeout=httpx.Timeout(policy.read_timeout, connect=policy.connect_timeout),
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        data: dict[str, str] | None = None,
    ) -> SafeResponse:
        current_url, current_method = url, method.upper()
        current_headers = dict(headers or {})
        original_host: str | None = None
        for hop in range(self._policy.max_redirects + 1):
            dest = validate_destination(
                current_url, resolver=self._resolver, allowed_ports=self._policy.allowed_ports
            )
            if original_host is None:
                original_host = dest.host
            elif dest.host != original_host:
                raise BlockedDestinationError("cross_host_redirect")
            response = self._send(dest, current_method, current_headers, json, data)
            if response.status_code not in REDIRECT_STATUSES:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            if hop == self._policy.max_redirects:
                break
            current_url = urljoin(f"https://{_host_header(dest)}{dest.path}", location)
            if urlsplit(current_url).scheme.lower() != "https":
                raise BlockedDestinationError("scheme_not_allowed")
            # Credentials are never forwarded to a redirect target.
            current_headers = {
                k: v for k, v in current_headers.items() if k.lower() not in _SENSITIVE_HEADERS
            }
            if response.status_code == 303 or (
                response.status_code in (301, 302) and current_method == "POST"
            ):
                current_method, json, data = "GET", None, None
        raise BlockedDestinationError("too_many_redirects")

    def stream_lines(self, url: str, *, allowed_host: Callable[[str], bool]) -> Iterator[bytes]:
        """GET ``url`` and yield its non-empty lines, streaming (task 2A-06: bulk JSONL exports).

        * Only hosts the caller allows (a per-provider allowlist) — checked before connecting,
          on top of the usual SSRF validation and address pinning.
        * No redirects, no credentials sent (the URL is pre-signed).
        * Bounded: ``max_download_bytes`` overall, ``download_timeout`` wall-clock, and one
          line may not exceed ``MAX_LINE_BYTES``; memory use stays at about one line.
        * The URL itself is never logged (signed URLs are bearer secrets).
        """
        dest = validate_destination(
            url, resolver=self._resolver, allowed_ports=self._policy.allowed_ports
        )
        if not allowed_host(dest.host):
            raise BlockedDestinationError("host_not_allowed")
        deadline = time.monotonic() + self._policy.download_timeout
        limit = self._policy.max_download_bytes
        try:
            with self._client.stream(
                "GET",
                _url_for(dest),
                headers={"Host": _host_header(dest)},
                extensions={"sni_hostname": dest.host},
                timeout=httpx.Timeout(
                    self._policy.read_timeout, connect=self._policy.connect_timeout
                ),
            ) as response:
                status = response.status_code
                logger.info("outbound_download", extra={"host": dest.host, "status": status})
                if status in REDIRECT_STATUSES:
                    raise BlockedDestinationError("redirect_not_allowed")
                if status in (400, 401, 403, 404, 410):
                    raise DownloadExpiredError()
                if status >= 500 or status == 429:
                    raise RetryableError("download_failed")
                if status >= 300:
                    raise InvalidRequestError("download_failed")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > limit:
                    raise ResponseTooLargeError()
                size, pending = 0, b""
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ResponseTooLargeError()
                    if time.monotonic() > deadline:
                        raise OutboundTimeoutError()
                    pending += chunk
                    *lines, pending = pending.split(b"\n")
                    if len(pending) > MAX_LINE_BYTES:
                        raise ResponseTooLargeError()
                    for line in lines:
                        if line.strip():
                            yield line
                if pending.strip():
                    yield pending
        except httpx.TimeoutException:
            raise OutboundTimeoutError() from None
        except httpx.TransportError:
            raise RetryableError("transport_error") from None

    def _send(
        self,
        dest: Destination,
        method: str,
        headers: dict[str, str],
        json: Any,
        data: dict[str, str] | None,
    ) -> SafeResponse:
        request_headers = {**headers, "Host": _host_header(dest)}
        try:
            with self._client.stream(
                method,
                _url_for(dest),
                headers=request_headers,
                json=json,
                data=data,
                extensions={"sni_hostname": dest.host},
            ) as response:
                declared = response.headers.get("content-length")
                if (
                    declared
                    and declared.isdigit()
                    and int(declared) > self._policy.max_response_bytes
                ):
                    raise ResponseTooLargeError()
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self._policy.max_response_bytes:
                        raise ResponseTooLargeError()
                    chunks.append(chunk)
                logger.info(
                    "outbound_request", extra={"host": dest.host, "status": response.status_code}
                )
                return SafeResponse(
                    status_code=response.status_code,
                    headers=response.headers,
                    content=b"".join(chunks),
                    host=dest.host,
                )
        except httpx.TimeoutException:
            raise OutboundTimeoutError() from None
        except httpx.TransportError:
            raise RetryableError("transport_error") from None


class DownloadExpiredError(InvalidRequestError):
    """The download link was refused (expired or revoked signed URL)."""

    code = "download_expired"
