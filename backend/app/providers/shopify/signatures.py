"""HMAC verification for Shopify requests (verified 2026-10-13, PHASE_02A_PLAN §4.1).

* **OAuth callback and install requests:** remove ``hmac`` (and the legacy ``signature``) from
  the query parameters, sort the rest by key, join as ``key=value`` with ``&``, and compute a
  hex HMAC-SHA256 with the app's client secret.
* **Webhooks:** base64 HMAC-SHA256 of the raw request body with the client secret, in the
  ``X-Shopify-Hmac-Sha256`` header (used from task 2A-05).

All comparisons are constant-time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping

_EXCLUDED = frozenset({"hmac", "signature"})


def query_message(params: Mapping[str, str]) -> str:
    return "&".join(f"{key}={params[key]}" for key in sorted(params) if key not in _EXCLUDED)


def sign_query(params: Mapping[str, str], secret: str) -> str:
    return hmac.new(secret.encode(), query_message(params).encode(), hashlib.sha256).hexdigest()


def verify_query(params: Mapping[str, str], secret: str) -> bool:
    supplied = params.get("hmac", "")
    if not supplied or len(supplied) != 64:
        return False
    return hmac.compare_digest(sign_query(params, secret), supplied.lower())


def sign_body(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_body(body: bytes, header_value: str | None, secret: str) -> bool:
    if not header_value:
        return False
    try:
        supplied = base64.b64decode(header_value, validate=True)
    except (ValueError, TypeError):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(expected, supplied)
