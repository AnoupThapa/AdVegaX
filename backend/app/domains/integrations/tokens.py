"""Credential lifecycle: refresh before expiry, keep refresh tokens alive (task 2A-04).

Platforms such as Shopify issue short-lived access tokens (1 h) and **rotating** refresh tokens
(90 days; each refresh returns a new pair). They also allow only one current token per app and
account: acquiring a new token (a reconnect) retires the others, and a refresh racing a
reconnect leaves one of the results invalid. So every refresh and every reconnect of the same
platform account runs under one **account lock** (Redis ``SET NX`` with a token-checked
release), and the credential row is re-read under ``SELECT … FOR UPDATE`` inside the lock so a
refresh that another worker already did is not repeated (PHASE_02A_PLAN §6.6).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

import redis
from sqlalchemy import select

from app.core.errors import ServiceUnavailable
from app.core.security.tokens import generate_token
from app.domains.integrations.credentials import load_secrets, store_secrets
from app.domains.integrations.models import ExternalConnection, ExternalConnectionCredential
from app.providers.base.capabilities import Capability
from app.providers.base.errors import AuthExpiredError, RetryableError
from app.providers.base.interfaces import Secrets
from app.runtime import Runtime

logger = logging.getLogger("advegax.integrations.tokens")

LOCK_TTL_SECONDS = 60
LOCK_WAIT_SECONDS = 15.0  # how long a refresh or reconnect waits for the account lock
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""


class AccountBusy(RetryableError):
    """Another refresh or reconnect for the same platform account is in progress."""

    code = "account_busy"


def lock_key(provider: str, account_id: str | None, connection_id: uuid.UUID) -> str:
    return f"token-lock:{provider}:{account_id or connection_id}"


@contextmanager
def account_lock(
    client: redis.Redis, key: str, *, wait_seconds: float, ttl_seconds: int = LOCK_TTL_SECONDS
) -> Iterator[None]:
    """Hold the account lock; wait up to ``wait_seconds`` for it, else raise ``AccountBusy``.

    The lock expires on its own (``LOCK_TTL_SECONDS``) if a process dies while holding it, and
    is released only by its owner (token check), so a slow holder never frees someone else's.
    """
    token = generate_token()
    deadline = time.monotonic() + wait_seconds
    try:
        while not client.set(key, token, nx=True, ex=ttl_seconds):
            if time.monotonic() >= deadline:
                raise AccountBusy()
            time.sleep(0.1)
    except redis.RedisError:
        raise ServiceUnavailable() from None
    try:
        yield
    finally:
        try:
            client.eval(_RELEASE, 1, key, token)
        except redis.RedisError:  # pragma: no cover - the lock then expires by itself
            logger.warning("token_lock_release_failed")


def _needs_refresh(expires_at: datetime | None, now: datetime, margin: timedelta) -> bool:
    return expires_at is not None and expires_at - now <= margin


def usable_secrets(
    rt: Runtime, org_id: uuid.UUID, connection_id: uuid.UUID, *, force: bool = False
) -> Secrets:
    """Secrets ready for a provider call: refreshed first when the access token is about to
    expire (or when ``force`` — the keep-alive). Raises ``AuthExpiredError`` (and marks the
    connection "Needs reconnecting") when the platform refuses the refresh."""
    margin = rt.settings.TOKEN_REFRESH_MARGIN
    with rt.db.transaction(org_id=org_id) as session:
        connection = session.get(ExternalConnection, connection_id)
        if connection is None or connection.organization_id != org_id:
            raise AuthExpiredError("connection_missing")
        provider = rt.providers.get(connection.provider)
        record = session.get(ExternalConnectionCredential, connection_id)
        secrets = load_secrets(session, rt.cipher, connection)
        expires = record.token_expires_at if record else None
        key = lock_key(connection.provider, connection.external_account_id, connection_id)
    if not provider.capabilities.supports(Capability.TOKEN_REFRESH):
        return secrets
    if not force and not _needs_refresh(expires, rt.clock.now(), margin):
        return secrets

    with account_lock(rt.redis, key, wait_seconds=LOCK_WAIT_SECONDS):
        with rt.db.transaction(org_id=org_id) as session:
            connection = session.get(ExternalConnection, connection_id)
            if connection is None or connection.status != "active":
                raise AuthExpiredError("connection_inactive")
            record = session.execute(
                select(ExternalConnectionCredential)
                .where(ExternalConnectionCredential.connection_id == connection_id)
                .with_for_update()
            ).scalar_one_or_none()
            secrets = load_secrets(session, rt.cipher, connection)
            now = rt.clock.now()
            already_fresh = record is not None and (
                record.last_refreshed_at is not None and now - record.last_refreshed_at < margin
            )
            if already_fresh or (
                not force
                and not _needs_refresh(record.token_expires_at if record else None, now, margin)
            ):
                return secrets  # another worker refreshed while we waited for the lock
        try:
            result = provider.refresh_credentials(secrets)
        except AuthExpiredError as exc:
            from app.domains.integrations.jobs import mark_connection_error

            mark_connection_error(rt, org_id, connection_id, exc)
            raise
        now = rt.clock.now()
        with rt.db.transaction(org_id=org_id) as session:
            connection = session.get(ExternalConnection, connection_id)
            if connection is None:  # pragma: no cover - deleted while refreshing
                raise AuthExpiredError("connection_missing")
            store_secrets(
                session,
                rt.cipher,
                connection,
                dict(result.secrets),
                token_expires_at=(
                    now + timedelta(seconds=result.token_expires_in_seconds)
                    if result.token_expires_in_seconds
                    else None
                ),
                refresh_expires_at=(
                    now + timedelta(seconds=result.refresh_expires_in_seconds)
                    if result.refresh_expires_in_seconds
                    else None
                ),
                refreshed_at=now,
            )
        logger.info(
            "credentials_refreshed",
            extra={"provider": provider.code, "connection_id": str(connection_id)},
        )
        return result.secrets
