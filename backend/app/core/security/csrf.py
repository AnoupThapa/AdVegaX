"""Signed double-submit CSRF tokens bound to the session (PHASE_01A_PLAN §14).

Token format: ``<nonce>.<signature>`` where the signature is
HMAC-SHA256(secret, "csrf|" + nonce + "|" + binding) and ``binding`` is the hash of the
current session token, or ``"anonymous"`` when there is no session. A request passes when
the header token equals the CSRF cookie and the signature matches the request's binding.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.core.security.tokens import hash_token

ANONYMOUS_BINDING = "anonymous"
CSRF_HEADER = "x-csrf-token"


def session_binding(session_token: str | None) -> str:
    return hash_token(session_token) if session_token else ANONYMOUS_BINDING


def _sign(secret: str, nonce: str, binding: str) -> str:
    message = f"csrf|{nonce}|{binding}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def issue_csrf_token(secret: str, binding: str) -> str:
    nonce = secrets.token_urlsafe(18)
    return f"{nonce}.{_sign(secret, nonce, binding)}"


def is_valid_csrf(
    secret: str, *, header_token: str | None, cookie_token: str | None, binding: str
) -> bool:
    if not header_token or not cookie_token:
        return False
    if not hmac.compare_digest(header_token, cookie_token):
        return False
    nonce, sep, signature = header_token.partition(".")
    if not sep or not nonce or not signature:
        return False
    return hmac.compare_digest(signature, _sign(secret, nonce, binding))
