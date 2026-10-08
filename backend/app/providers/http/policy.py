"""Destination policy for outbound requests to externally supplied hosts (A11).

This is a security boundary: a destination is accepted only if the URL is well-formed HTTPS,
the hostname is a public DNS name, and **every** address it resolves to is globally routable.
The check is repeated after DNS resolution and for every redirect target.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.providers.base.errors import BlockedDestinationError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], list[str]]

_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".intranet",
    ".lan",
    ".home",
    ".corp",
    ".private",
    ".localdomain",
    ".home.arpa",
    ".in-addr.arpa",
    ".ip6.arpa",
)
_BLOCKED_NAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "instance-data",
        "kubernetes",
        "kubernetes.default",
    }
)
# Networks that tunnel/translate to other address families and could reach internal IPv4.
_BLOCKED_V6_NETWORKS = (
    ipaddress.IPv6Network("64:ff9b::/96"),  # NAT64
    ipaddress.IPv6Network("64:ff9b:1::/48"),  # local-use NAT64
    ipaddress.IPv6Network("2002::/16"),  # 6to4
    ipaddress.IPv6Network("2001::/32"),  # Teredo
)
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$")


@dataclass(frozen=True)
class Destination:
    host: str  # validated, normalized (IDNA) hostname
    port: int
    path: str  # path + query, never empty
    address: str  # the validated IP address the connection is pinned to


def default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise BlockedDestinationError("dns_resolution_failed") from None
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_blocked_address(address: IPAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_blocked_address(address.ipv4_mapped)
        if any(address in net for net in _BLOCKED_V6_NETWORKS):
            return True
    return (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _normalize_host(raw: str) -> str:
    host = raw.strip().rstrip(".").lower()
    if not host or host.startswith("[") or ":" in host:
        raise BlockedDestinationError("ip_literal_not_allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise BlockedDestinationError("ip_literal_not_allowed")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise BlockedDestinationError("invalid_hostname") from None
    labels = ascii_host.split(".")
    if _NUMERIC_LABEL.match(labels[-1]) or all(_NUMERIC_LABEL.match(label) for label in labels):
        raise BlockedDestinationError("ip_literal_not_allowed")
    if ascii_host in _BLOCKED_NAMES or ascii_host.endswith(_BLOCKED_SUFFIXES):
        raise BlockedDestinationError("internal_hostname")
    if len(labels) < 2 or any(not label or len(label) > 63 for label in labels):
        raise BlockedDestinationError("invalid_hostname")
    return ascii_host


def validate_destination(
    url: str, *, resolver: Resolver, allowed_ports: frozenset[int]
) -> Destination:
    """Parse, validate and resolve ``url``; return a destination pinned to a safe address."""
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise BlockedDestinationError("scheme_not_allowed")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise BlockedDestinationError("credentials_in_url")
    try:
        port = parts.port or 443
    except ValueError:
        raise BlockedDestinationError("invalid_port") from None
    if port not in allowed_ports:
        raise BlockedDestinationError("port_not_allowed")
    host = _normalize_host(parts.hostname or "")
    addresses = resolver(host, port)
    if not addresses:
        raise BlockedDestinationError("dns_resolution_failed")
    parsed: list[IPAddress] = []
    for text in addresses:
        try:
            parsed.append(ipaddress.ip_address(text.split("%")[0]))
        except ValueError:
            raise BlockedDestinationError("invalid_resolved_address") from None
    if any(is_blocked_address(a) for a in parsed):
        raise BlockedDestinationError("resolves_to_blocked_address")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return Destination(host=host, port=port, path=path, address=str(parsed[0]))
