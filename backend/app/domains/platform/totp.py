"""Two-step sign-in codes (TOTP, RFC 6238: SHA-1, 30 seconds, 6 digits) — Phase 16, Q-16-5.

Works with any authenticator app (Google Authenticator, Microsoft Authenticator, 1Password).
No new library: the standard's own HMAC construction.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote

STEP, DIGITS, WINDOW = 30, 6, 1  # one step either side for clock drift


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def match(secret: str, code: str, now: datetime) -> int | None:
    """The time step ``code`` belongs to (within the drift window), or None if it is wrong."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    counter = int(now.timestamp()) // STEP
    found = None
    for d in range(-WINDOW, WINDOW + 1):  # compare every step: no early exit on a match
        if hmac.compare_digest(code_at(secret, counter + d), code):
            found = counter + d
    return found


def verify(secret: str, code: str, now: datetime) -> bool:
    return match(secret, code, now) is not None


def uri(secret: str, email: str) -> str:
    """The ``otpauth://`` link authenticator apps read (or type the secret in by hand)."""
    return f"otpauth://totp/AdVegaX%20Admin:{quote(email)}?secret={secret}&issuer=AdVegaX%20Admin"
