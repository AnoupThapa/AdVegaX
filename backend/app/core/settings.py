"""Centralized, environment-driven configuration.

Every security-relevant duration and limit lives here (PHASE_01A_PLAN §22.1).
No other module may hard-code session/token lifetimes or throttling limits.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "insecure-local-development-secret-change-me-0000"  # noqa: S105


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class EmailBackend(StrEnum):
    SMTP = "smtp"
    MEMORY = "memory"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # --- Environment -------------------------------------------------------------
    ENVIRONMENT: Environment = Environment.LOCAL
    SECRET_KEY: SecretStr = SecretStr(_INSECURE_DEFAULT_SECRET)
    LOG_LEVEL: str = "INFO"

    # --- Database (three roles; see DATABASE_SCHEMA §19) ----------------------------
    DATABASE_URL_APP: SecretStr = SecretStr(
        "postgresql+psycopg://advegax_app:advegax_app@localhost:5432/advegax"
    )
    DATABASE_URL_SYSTEM: SecretStr = SecretStr(
        "postgresql+psycopg://advegax_system:advegax_system@localhost:5432/advegax"
    )
    DATABASE_URL_MIGRATOR: SecretStr = SecretStr(
        "postgresql+psycopg://advegax_migrator:advegax_migrator@localhost:5432/advegax"
    )
    DATABASE_POOL_SIZE: int = Field(default=10, ge=1)

    # --- Redis --------------------------------------------------------------------
    REDIS_URL: SecretStr = SecretStr("redis://localhost:6379/0")

    # --- Public URLs and CORS (D13) -------------------------------------------------
    APP_BASE_URL: str = "http://localhost:3000"
    CORS_ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    TRUSTED_PROXY_COUNT: int = Field(default=0, ge=0, le=5)
    MAX_REQUEST_BYTES: int = Field(default=1_048_576, ge=1024)

    # --- Cookies --------------------------------------------------------------------
    SESSION_COOKIE_NAME: str = "advegax_session"
    CSRF_COOKIE_NAME: str = "advegax_csrf"
    COOKIE_SECURE: bool = False

    # --- Session and token lifetimes (approved defaults, A15) ------------------------
    SESSION_IDLE_TIMEOUT: timedelta = timedelta(hours=24)
    SESSION_ABSOLUTE_TIMEOUT: timedelta = timedelta(days=14)
    SESSION_TOUCH_INTERVAL: timedelta = timedelta(minutes=5)
    EMAIL_VERIFICATION_TTL: timedelta = timedelta(hours=24)
    PASSWORD_RESET_TTL: timedelta = timedelta(minutes=30)
    INVITATION_TTL: timedelta = timedelta(days=7)

    # --- Throttling (PHASE_01A_PLAN §9) ------------------------------------------------
    THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE: int = Field(default=5, ge=1)
    THROTTLE_LOGIN_PER_IP_PER_MINUTE: int = Field(default=20, ge=1)
    THROTTLE_REGISTER_PER_IP_PER_HOUR: int = Field(default=5, ge=1)
    THROTTLE_EMAIL_ACTION_PER_EMAIL_PER_HOUR: int = Field(default=3, ge=1)
    THROTTLE_EMAIL_ACTION_PER_IP_PER_HOUR: int = Field(default=10, ge=1)
    THROTTLE_FAIL_OPEN: bool = False

    # --- Passwords ------------------------------------------------------------------
    PASSWORD_MIN_LENGTH: int = Field(default=12, ge=8)
    PASSWORD_MAX_LENGTH: int = Field(default=128, le=1024)

    # --- Transactional email (A9) -----------------------------------------------------
    EMAIL_BACKEND: EmailBackend = EmailBackend.SMTP
    EMAIL_FROM: str = "AdVegaX <no-reply@localhost>"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    SMTP_USE_SSL: bool = False
    SMTP_STARTTLS: bool = False
    SMTP_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    EMAIL_MAX_ATTEMPTS: int = Field(default=5, ge=1)
    EMAIL_RETRY_BASE_DELAY: timedelta = timedelta(seconds=30)

    # --- Background jobs ------------------------------------------------------------
    CELERY_TASK_ALWAYS_EAGER: bool = False

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        durations = {
            "SESSION_IDLE_TIMEOUT": self.SESSION_IDLE_TIMEOUT,
            "SESSION_ABSOLUTE_TIMEOUT": self.SESSION_ABSOLUTE_TIMEOUT,
            "SESSION_TOUCH_INTERVAL": self.SESSION_TOUCH_INTERVAL,
            "EMAIL_VERIFICATION_TTL": self.EMAIL_VERIFICATION_TTL,
            "PASSWORD_RESET_TTL": self.PASSWORD_RESET_TTL,
            "INVITATION_TTL": self.INVITATION_TTL,
            "EMAIL_RETRY_BASE_DELAY": self.EMAIL_RETRY_BASE_DELAY,
        }
        for name, value in durations.items():
            if value <= timedelta(0):
                raise ValueError(f"{name} must be a positive duration")
        if self.SESSION_IDLE_TIMEOUT > self.SESSION_ABSOLUTE_TIMEOUT:
            raise ValueError("SESSION_IDLE_TIMEOUT must not exceed SESSION_ABSOLUTE_TIMEOUT")
        if self.PASSWORD_MIN_LENGTH > self.PASSWORD_MAX_LENGTH:
            raise ValueError("PASSWORD_MIN_LENGTH must not exceed PASSWORD_MAX_LENGTH")
        if self.is_deployed:
            self._validate_deployed()
        return self

    def _validate_deployed(self) -> None:
        problems: list[str] = []
        secret = self.SECRET_KEY.get_secret_value()
        if secret == _INSECURE_DEFAULT_SECRET or len(secret) < 32:
            problems.append("SECRET_KEY must be set to a random value of at least 32 characters")
        if not self.COOKIE_SECURE:
            problems.append("COOKIE_SECURE must be true")
        if not self.SESSION_COOKIE_NAME.startswith("__Host-"):
            problems.append("SESSION_COOKIE_NAME must use the __Host- prefix")
        if not self.CSRF_COOKIE_NAME.startswith("__Host-"):
            problems.append("CSRF_COOKIE_NAME must use the __Host- prefix")
        if not self.CORS_ALLOWED_ORIGINS:
            problems.append("CORS_ALLOWED_ORIGINS must not be empty")
        if any(o == "*" or not o.startswith("https://") for o in self.CORS_ALLOWED_ORIGINS):
            problems.append("CORS_ALLOWED_ORIGINS must list explicit https:// origins (no '*')")
        if not self.APP_BASE_URL.startswith("https://"):
            problems.append("APP_BASE_URL must use https://")
        if self.EMAIL_BACKEND is not EmailBackend.SMTP:
            problems.append("EMAIL_BACKEND must be smtp")
        if self.CELERY_TASK_ALWAYS_EAGER:
            problems.append("CELERY_TASK_ALWAYS_EAGER must be false")
        if problems:
            raise ValueError(
                "Insecure configuration for deployed environment: " + "; ".join(problems)
            )

    @property
    def is_deployed(self) -> bool:
        return self.ENVIRONMENT in {Environment.STAGING, Environment.PRODUCTION}


@lru_cache
def get_settings() -> Settings:
    return Settings()
