"""PKCE (RFC 7636) S256 challenge derivation, shared by all OAuth providers."""

from __future__ import annotations

import base64
import hashlib


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
