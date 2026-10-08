"""Configuration: centralized security durations and deployed-environment safety."""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.core.settings import Settings
from pydantic import ValidationError

SECURE = {
    "ENVIRONMENT": "production",
    "SECRET_KEY": "s" * 48,
    "COOKIE_SECURE": True,
    "SESSION_COOKIE_NAME": "__Host-advegax_session",
    "CSRF_COOKIE_NAME": "__Host-advegax_csrf",
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
    "APP_BASE_URL": "https://app.example.com",
    "API_BASE_URL": "https://api.example.com",
    "ENCRYPTION_KEYS": "1:" + "QUJD" * 10 + "QUI=",
    "EMAIL_BACKEND": "smtp",
    "CELERY_TASK_ALWAYS_EAGER": False,
}


def make(**overrides):
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_approved_defaults():
    s = make()
    assert s.SESSION_IDLE_TIMEOUT == timedelta(hours=24)
    assert s.SESSION_ABSOLUTE_TIMEOUT == timedelta(days=14)
    assert s.EMAIL_VERIFICATION_TTL == timedelta(hours=24)
    assert s.PASSWORD_RESET_TTL == timedelta(minutes=30)
    assert s.INVITATION_TTL == timedelta(days=7)
    assert (s.THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE, s.THROTTLE_LOGIN_PER_IP_PER_MINUTE) == (
        5,
        20,
    )
    assert s.THROTTLE_REGISTER_PER_IP_PER_HOUR == 5
    assert (
        s.THROTTLE_EMAIL_ACTION_PER_EMAIL_PER_HOUR,
        s.THROTTLE_EMAIL_ACTION_PER_IP_PER_HOUR,
    ) == (3, 10)


def test_durations_are_configurable_from_environment(monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT", "PT2H")
    monkeypatch.setenv("SESSION_ABSOLUTE_TIMEOUT", "P1D")
    monkeypatch.setenv("PASSWORD_RESET_TTL", "PT15M")
    s = Settings()
    assert s.SESSION_IDLE_TIMEOUT == timedelta(hours=2)
    assert s.SESSION_ABSOLUTE_TIMEOUT == timedelta(days=1)
    assert s.PASSWORD_RESET_TTL == timedelta(minutes=15)


@pytest.mark.parametrize(
    "overrides",
    [
        {"SESSION_IDLE_TIMEOUT": timedelta(days=15)},
        {"INVITATION_TTL": timedelta(0)},
        {"PASSWORD_RESET_TTL": timedelta(seconds=-1)},
        {"PASSWORD_MIN_LENGTH": 64, "PASSWORD_MAX_LENGTH": 32},
    ],
)
def test_invalid_durations_rejected(overrides):
    with pytest.raises(ValidationError):
        make(**overrides)


def test_secure_production_configuration_accepted():
    s = make(**SECURE)
    assert s.is_deployed
    assert s.CORS_ALLOWED_ORIGINS == ["https://app.example.com"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("SECRET_KEY", "short"),
        ("COOKIE_SECURE", False),
        ("SESSION_COOKIE_NAME", "advegax_session"),
        ("CSRF_COOKIE_NAME", "csrf"),
        ("CORS_ALLOWED_ORIGINS", "*"),
        ("CORS_ALLOWED_ORIGINS", "http://app.example.com"),
        ("CORS_ALLOWED_ORIGINS", ""),
        ("APP_BASE_URL", "http://app.example.com"),
        ("EMAIL_BACKEND", "memory"),
        ("CELERY_TASK_ALWAYS_EAGER", True),
    ],
)
def test_insecure_production_configuration_rejected(key, value):
    with pytest.raises(ValidationError, match="Insecure configuration"):
        make(**{**SECURE, key: value})


def test_staging_is_validated_like_production():
    with pytest.raises(ValidationError):
        make(**{**SECURE, "ENVIRONMENT": "staging", "COOKIE_SECURE": False})
