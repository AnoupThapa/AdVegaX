"""Database engines per role and transaction-scoped tenant context (DATABASE_SCHEMA §19).

Tenant/user context is applied with ``set_config(..., is_local => true)`` at the start of
every transaction, so it can never leak to the next user of a pooled connection.
Session-level ``SET`` of these settings is forbidden (enforced by a test).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.core.settings import Settings

logger = logging.getLogger("advegax.db")

ORG_SETTING = "app.current_org_id"
USER_SETTING = "app.current_user_id"
AFTER_COMMIT_KEY = "after_commit"

_SET_CONTEXT = text(
    "SELECT set_config('app.current_org_id', :org, true), "
    "set_config('app.current_user_id', :usr, true)"
)


class Database:
    """Holds one engine per database role. The migrator role is never used at runtime."""

    def __init__(self, settings: Settings) -> None:
        common: dict[str, Any] = {"pool_pre_ping": True, "future": True}
        self.app_engine: Engine = create_engine(
            settings.DATABASE_URL_APP.get_secret_value(),
            pool_size=settings.DATABASE_POOL_SIZE,
            **common,
        )
        self.system_engine: Engine = create_engine(
            settings.DATABASE_URL_SYSTEM.get_secret_value(), pool_size=2, **common
        )

    def dispose(self) -> None:
        self.app_engine.dispose()
        self.system_engine.dispose()

    @contextmanager
    def transaction(
        self,
        *,
        org_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        system: bool = False,
    ) -> Iterator[Session]:
        """One unit of work: a single transaction with tenant/user context applied first."""
        engine = self.system_engine if system else self.app_engine
        session = Session(engine, expire_on_commit=False, autoflush=True)
        session.info[AFTER_COMMIT_KEY] = []
        try:
            with session.begin():
                set_context(session, org_id=org_id, user_id=user_id)
                yield session
            callbacks: list[Callable[[], None]] = session.info[AFTER_COMMIT_KEY]
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    logger.exception("after_commit_callback_failed")
        finally:
            session.close()


def set_context(session: Session, *, org_id: uuid.UUID | None, user_id: uuid.UUID | None) -> None:
    session.execute(
        _SET_CONTEXT, {"org": str(org_id) if org_id else "", "usr": str(user_id) if user_id else ""}
    )


def after_commit(session: Session, callback: Callable[[], None]) -> None:
    """Run ``callback`` only if the surrounding transaction commits."""
    session.info[AFTER_COMMIT_KEY].append(callback)
