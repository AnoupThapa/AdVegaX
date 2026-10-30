"""Keys and switches saved in the Admin portal, encrypted (Phase 16, task 16-04; A35).

Each value is sealed with the installation's key set (``ENCRYPTION_KEYS``), bound to its
setting's name. The API never returns a secret: only whether it is set and its last four
characters. ``apply`` reads them when AdVegaX starts and lays them over the settings file.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security.encryption import (
    DecryptionError,
    EncryptedSecret,
    EnvelopeCipher,
    cipher_from_settings,
)
from app.core.settings import Settings
from app.domains.platform.models import PlatformAdmin, PlatformSetting
from app.domains.platform.registry import BY_NAME

logger = logging.getLogger("advegax.platform")


def _aad(name: str) -> bytes:
    return f"advegax:platform-setting:v1|{name}".encode()


def _totp_aad(user_id: uuid.UUID) -> bytes:
    return f"advegax:platform-admin-totp:v1|{user_id}".encode()


def save(
    session: Session, cipher: EnvelopeCipher, name: str, value: str, user_id: uuid.UUID
) -> PlatformSetting:
    entry = BY_NAME[name]
    sealed = cipher.encrypt(value.encode(), associated_data=_aad(name))
    row = session.get(PlatformSetting, name, with_for_update=True)
    if row is None:
        row = PlatformSetting(name=name)
        session.add(row)
    row.ciphertext, row.wrapped_key, row.key_version = (
        sealed.ciphertext,
        sealed.wrapped_data_key,
        sealed.key_version,
    )
    row.hint = value[-4:] if entry.kind == "secret" else value[:8]
    row.updated_by = user_id
    session.flush()
    return row


def _open(cipher: EnvelopeCipher, row: PlatformSetting) -> str:
    return cipher.decrypt(
        EncryptedSecret(row.ciphertext, row.wrapped_key, row.key_version),
        associated_data=_aad(row.name),
    ).decode()


def overrides(session: Session, cipher: EnvelopeCipher) -> dict[str, Any]:
    """Every saved value, typed as its setting expects (unreadable ones are skipped)."""
    out: dict[str, Any] = {}
    for row in session.execute(select(PlatformSetting)).scalars():
        if row.name not in BY_NAME:
            continue
        try:
            raw = _open(cipher, row)
        except DecryptionError:
            logger.warning("platform_setting_unreadable", extra={"setting": row.name})
            continue
        field = Settings.model_fields[row.name]
        out[row.name] = TypeAdapter(field.annotation).validate_python(raw)
    return out


def apply(settings: Settings) -> Settings:
    """The settings with the Admin portal's values laid over them (as AdVegaX starts)."""
    try:
        engine = create_engine(settings.DATABASE_URL_SYSTEM.get_secret_value(), pool_pre_ping=True)
        try:
            cipher = cipher_from_settings(
                settings.ENCRYPTION_KEYS.get_secret_value(), settings.ENCRYPTION_ACTIVE_KEY_VERSION
            )
            with Session(engine) as session:
                found = overrides(session, cipher)
        finally:
            engine.dispose()
    except SQLAlchemyError:
        logger.warning("platform_settings_not_read")  # e.g. before the first migration
        return settings
    if not found:
        return settings
    logger.info("platform_settings_applied", extra={"settings": sorted(found)})
    return Settings.model_validate({**settings.model_dump(), **found})


# ------------------------------------------------------------------ two-step sign-in secrets
def seal_totp(cipher: EnvelopeCipher, admin: PlatformAdmin, secret: str) -> None:
    sealed = cipher.encrypt(secret.encode(), associated_data=_totp_aad(admin.user_id))
    admin.totp_ciphertext, admin.totp_wrapped_key, admin.totp_key_version = (
        sealed.ciphertext,
        sealed.wrapped_data_key,
        sealed.key_version,
    )


def open_totp(cipher: EnvelopeCipher, admin: PlatformAdmin) -> str | None:
    if admin.totp_ciphertext is None or admin.totp_wrapped_key is None:
        return None
    if admin.totp_key_version is None:
        return None
    return cipher.decrypt(
        EncryptedSecret(admin.totp_ciphertext, admin.totp_wrapped_key, admin.totp_key_version),
        associated_data=_totp_aad(admin.user_id),
    ).decode()
