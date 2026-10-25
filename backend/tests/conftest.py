"""Test configuration: real PostgreSQL 16 + Redis 7 (PHASE_01A_PLAN §16).

Databases and roles are created by scripts/bootstrap_db.sh. Connection targets can be
overridden with TEST_PG_HOST / TEST_PG_PORT / TEST_REDIS_URL (used by CI).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = os.environ.get("TEST_PG_PORT", "5432")
TEST_DB = "advegax_test"


def _url(role: str, db: str = TEST_DB) -> str:
    return f"postgresql+psycopg://{role}:{role}@{PG_HOST}:{PG_PORT}/{db}"


os.environ.update(
    {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "test-secret-key-with-enough-entropy-0123456789",
        "DATABASE_URL_APP": _url("advegax_app"),
        "DATABASE_URL_SYSTEM": _url("advegax_system"),
        "DATABASE_URL_MIGRATOR": _url("advegax_migrator"),
        "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
        "EMAIL_BACKEND": "memory",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "APP_BASE_URL": "http://localhost:3000",
        "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
        "LOG_LEVEL": "WARNING",
    }
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.settings import Settings, get_settings  # noqa: E402
from app.domains.notifications.email import memory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.runtime import Runtime, build_runtime  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy import Engine, create_engine, text  # noqa: E402

from tests.helpers import ApiClient  # noqa: E402

TABLES = (
    "ai_models",  # shared reference data (Phase 8): which model and prompt version a run used
    "prompt_versions",
    "fx_rates",  # shared reference data (Phase 6), cleared like the rest between tests
    "job_runs",
    "organization_resource_links",
    "external_resources",
    "external_connection_credentials",
    "external_connections",
    "email_outbox",
    "security_events",
    "audit_logs",
    "user_action_tokens",
    "invitations",
    "memberships",
    "organizations",
    "sessions",
    "user_password_credentials",
    "users",
)


# The simulator's sample store has orders on fixed dates (5 and 8 October 2026). Starting the
# test clock at a fixed moment keeps them inside Shopify's 60-day history window whatever the
# real date is; otherwise the commerce tests would start failing in December 2026 (found in
# 2A-11 by running the suite with the clock moved forward). Nothing compares this clock with
# real time: session cookies use Max-Age and jobs use the database clock on both sides.
TEST_CLOCK_START = datetime(2026, 10, 14, tzinfo=UTC)


class FrozenClock:
    """Starts at a fixed moment (``TEST_CLOCK_START``); tests move it forward explicitly."""

    def __init__(self) -> None:
        self.current = TEST_CLOCK_START

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


def alembic_config(url: str) -> Config:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def migrator_engine(settings: Settings) -> Iterator[Engine]:
    url = settings.DATABASE_URL_MIGRATOR.get_secret_value()
    cfg = alembic_config(url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def admin_engine(migrator_engine: Engine) -> Iterator[Engine]:
    """Superuser connection for test inspection only (bypasses RLS by design)."""
    user = os.environ.get("TEST_PG_SUPERUSER", "postgres")
    password = os.environ.get("TEST_PG_SUPERUSER_PASSWORD", "postgres")
    engine = create_engine(f"postgresql+psycopg://{user}:{password}@{PG_HOST}:{PG_PORT}/{TEST_DB}")
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_state(migrator_engine: Engine, settings: Settings) -> Iterator[None]:
    memory.reset()
    yield
    with migrator_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    import redis

    redis.Redis.from_url(settings.REDIS_URL.get_secret_value()).flushdb()
    memory.reset()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def runtime(settings: Settings, clock: FrozenClock) -> Iterator[Runtime]:
    from app.providers.fake import provider as fake_provider
    from app.workers.email_tasks import set_worker_runtime

    fake_provider.reset()
    rt = build_runtime(settings, clock=clock)
    set_worker_runtime(rt)  # eager Celery tasks run with the same runtime and clock
    yield rt
    set_worker_runtime(None)
    rt.close()


@pytest.fixture
def app(settings: Settings, runtime: Runtime) -> FastAPI:
    return create_app(settings, runtime)


@pytest.fixture
def make_client(app: FastAPI) -> Iterator[object]:
    clients: list[ApiClient] = []

    def factory() -> ApiClient:
        client = ApiClient(app)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()


@pytest.fixture
def client(make_client: object) -> ApiClient:
    return make_client()  # type: ignore[operator, no-any-return]
