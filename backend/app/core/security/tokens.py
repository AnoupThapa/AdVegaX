"""Opaque random tokens; only their hashes are stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32  # 256 bits


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def keyed_hash(secret: str, value: str, *, length: int = 32) -> str:
    """Keyed, non-reversible fingerprint (e.g. IP addresses in security events)."""
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:length]
