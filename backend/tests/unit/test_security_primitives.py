"""Passwords, tokens, CSRF signing, cookies and email address validation."""

from __future__ import annotations

import pytest
from app.core.security import csrf, passwords, tokens
from app.core.security.cookies import clear_session_cookie, set_session_cookie
from app.domains.identity.emails import normalize_email
from starlette.responses import Response


def test_password_hash_and_verify():
    hashed = passwords.hash_password("a long enough passphrase")
    assert hashed.startswith("$argon2id$")
    assert passwords.verify_password(hashed, "a long enough passphrase").valid
    assert not passwords.verify_password(hashed, "wrong").valid
    assert not passwords.verify_password("not-a-hash", "x").valid
    passwords.verify_dummy("anything")


def test_password_rehash_detection():
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("passphrase value")
    assert passwords.verify_password(weak, "passphrase value").needs_rehash


def test_password_policy():
    kwargs = {"email": "a@example.com", "min_length": 12, "max_length": 128}
    assert passwords.password_policy_errors("x" * 12, **kwargs) == []
    assert passwords.password_policy_errors("short", **kwargs)
    assert passwords.password_policy_errors("x" * 129, **kwargs)
    assert passwords.password_policy_errors(
        "A@Example.com", email="a@example.com", min_length=8, max_length=128
    )


def test_tokens():
    a, b = tokens.generate_token(), tokens.generate_token()
    assert a != b and len(a) >= 43
    assert tokens.hash_token(a) == tokens.hash_token(a) != a
    assert len(tokens.hash_token(a)) == 64
    assert tokens.keyed_hash("k1", "1.2.3.4") != tokens.keyed_hash("k2", "1.2.3.4")


def test_csrf_signing():
    secret = "s" * 40
    binding = csrf.session_binding("session-token")
    token = csrf.issue_csrf_token(secret, binding)
    ok = {"header_token": token, "cookie_token": token, "binding": binding}
    assert csrf.is_valid_csrf(secret, **ok)
    assert not csrf.is_valid_csrf("other" * 10, **ok)
    assert not csrf.is_valid_csrf(secret, **{**ok, "binding": csrf.ANONYMOUS_BINDING})
    assert not csrf.is_valid_csrf(secret, **{**ok, "cookie_token": None})
    assert not csrf.is_valid_csrf(secret, **{**ok, "header_token": token + "x"})
    assert not csrf.is_valid_csrf(
        secret, header_token="nodot", cookie_token="nodot", binding=binding
    )
    assert csrf.session_binding(None) == csrf.ANONYMOUS_BINDING


def test_cookie_flags(settings):
    response = Response()
    set_session_cookie(response, settings, "value")
    clear_session_cookie(response, settings)
    cookies = response.headers.getlist("set-cookie")
    assert all("HttpOnly" in c and "SameSite=lax" in c for c in cookies)
    assert "Max-Age=0" in cookies[1] or "expires" in cookies[1].lower()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  Ada@Example.COM ", "ada@example.com"),
        ("first.last+tag@sub.example.co", "first.last+tag@sub.example.co"),
    ],
)
def test_valid_emails(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "no-at-sign",
        "a@b",
        "a@@b.com",
        ".a@example.com",
        "a.@example.com",
        "a..b@example.com",
        "a@-bad.com",
        "a@example.123",
        "a" * 65 + "@example.com",
        "a b@example.com",
        "a@" + "b" * 250 + ".com",
    ],
)
def test_invalid_emails(raw):
    with pytest.raises(ValueError, match="valid email"):
        normalize_email(raw)
