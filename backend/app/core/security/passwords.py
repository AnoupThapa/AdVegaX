"""Password hashing with Argon2id (RFC 9106 defaults from argon2-cffi)."""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
# Computed once so that unknown-account logins cost the same as real ones.
_DUMMY_HASH = _hasher.hash("advegax-dummy-password-for-timing-equalisation")


@dataclass(frozen=True)
class PasswordCheck:
    valid: bool
    needs_rehash: bool = False


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> PasswordCheck:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return PasswordCheck(valid=False)
    return PasswordCheck(valid=True, needs_rehash=_hasher.check_needs_rehash(password_hash))


def verify_dummy(password: str) -> None:
    """Spend the same work as a real verification; result is always discarded."""
    verify_password(_DUMMY_HASH, password)


def password_policy_errors(
    password: str, *, email: str, min_length: int, max_length: int
) -> list[str]:
    errors: list[str] = []
    if len(password) < min_length:
        errors.append(f"Password must be at least {min_length} characters.")
    if len(password) > max_length:
        errors.append(f"Password must be at most {max_length} characters.")
    if password.strip().lower() == email.strip().lower():
        errors.append("Password must not be your email address.")
    return errors
