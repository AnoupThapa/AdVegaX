"""WooCommerce store addresses (task 2B-03, PHASE_02B_PLAN §6.1 and §7).

A WooCommerce store lives on the merchant's own server, so the address is untrusted input that
AdVegaX will call (SSRF, risk 6 — CRITICAL). This module only **normalizes and refuses**:

* HTTPS only (Q10b). A pasted ``http://`` address is refused, never upgraded silently, because
  the merchant must know their store is served over HTTPS.
* A public DNS name: no IP literals in any notation, no internal names, no user name or
  password, no port other than 443 (checked by the shared outbound policy).
* WordPress may live in a sub-folder (``example.com/shop``). Admin and API paths that people
  paste (``/wp-admin…``, ``/wp-json…``, ``/wp-login.php``) are removed; query and fragment are
  dropped. Path segments are restricted to safe characters; ``..`` is refused.

Whether the name resolves to a public address is checked again on **every** request by
``SafeHttpClient`` (DNS rebinding cannot slip through after this check).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.providers.base.errors import BlockedDestinationError, InvalidConnectParamsError
from app.providers.http.policy import normalize_host

MAX_LENGTH = 2048
MAX_SEGMENTS = 5
_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,100}$")
_WORDPRESS_TAILS = ("wp-admin", "wp-json", "wp-login.php", "index.php")


class StoreAddressError(InvalidConnectParamsError):
    """The store address cannot be used. ``str(error)`` is a plain code for the web app."""


@dataclass(frozen=True)
class StoreAddress:
    host: str  # IDNA, lower-case
    path: str  # "" or "/shop" — no trailing slash

    @property
    def base_url(self) -> str:
        return f"https://{self.host}{self.path}"

    @property
    def account_id(self) -> str:
        """Identity of the store across organizations (one store, one connection)."""
        return f"{self.host}{self.path.lower()}"


def normalize_store_url(raw: str) -> StoreAddress:
    """Return the store's normalized address or raise ``StoreAddressError`` with a code."""
    text = (raw or "").strip()
    if not text or len(text) > MAX_LENGTH or any(ch.isspace() or ord(ch) < 32 for ch in text):
        raise StoreAddressError("invalid_store_url")
    if "\\" in text:
        raise StoreAddressError("invalid_store_url")
    lowered = text.lower()
    if "://" not in lowered:
        if lowered.startswith("//"):
            raise StoreAddressError("invalid_store_url")
        text = f"https://{text}"
    elif lowered.startswith("http://"):
        raise StoreAddressError("https_required")
    elif not lowered.startswith("https://"):
        raise StoreAddressError("invalid_store_url")
    parts = urlsplit(text)
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise StoreAddressError("credentials_in_url")
    try:
        port = parts.port
    except ValueError:
        raise StoreAddressError("invalid_store_url") from None
    if port not in (None, 443):
        raise StoreAddressError("port_not_allowed")
    try:
        host = normalize_host(parts.hostname or "")
    except BlockedDestinationError as exc:
        raise StoreAddressError(str(exc)) from None
    return StoreAddress(host=host, path=_normalize_path(parts.path))


def _normalize_path(path: str) -> str:
    segments = [s for s in path.split("/") if s]
    for index, segment in enumerate(segments):
        if segment.lower() in _WORDPRESS_TAILS:
            segments = segments[:index]
            break
    if len(segments) > MAX_SEGMENTS:
        raise StoreAddressError("invalid_store_url")
    for segment in segments:
        if segment in (".", "..") or not _SEGMENT.fullmatch(segment):
            raise StoreAddressError("invalid_store_url")
    return "".join(f"/{s}" for s in segments)
