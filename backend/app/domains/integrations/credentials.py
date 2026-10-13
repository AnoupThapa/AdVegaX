"""The only place platform credentials are encrypted or decrypted (D15, A16).

Ciphertexts are bound to ``organization_id | connection_id | provider`` through AES-GCM
associated data, so a credential copied to another connection or tenant cannot be decrypted.
Decrypted secrets are returned only to provider calls; they are never logged, audited or
serialized into API responses (enforced by tests).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.security.encryption import DecryptionError, EncryptedSecret, EnvelopeCipher
from app.domains.integrations.models import ExternalConnection, ExternalConnectionCredential
from app.providers.base.errors import AuthExpiredError


def associated_data(organization_id: uuid.UUID, connection_id: uuid.UUID, provider: str) -> bytes:
    return f"advegax:credential:v1|{organization_id}|{connection_id}|{provider}".encode()


def store_secrets(
    session: Session,
    cipher: EnvelopeCipher,
    connection: ExternalConnection,
    secrets: dict[str, Any],
    *,
    token_expires_at: datetime | None,
    refresh_expires_at: datetime | None = None,
) -> None:
    """Encrypt and save the connection's secrets, replacing any previous ones (reconnect)."""
    sealed = cipher.encrypt(
        json.dumps(secrets, separators=(",", ":")).encode("utf-8"),
        associated_data=associated_data(
            connection.organization_id, connection.id, connection.provider
        ),
    )
    record = session.get(ExternalConnectionCredential, connection.id)
    if record is None:
        record = ExternalConnectionCredential(
            connection_id=connection.id, organization_id=connection.organization_id
        )
        session.add(record)
    record.ciphertext = sealed.ciphertext
    record.wrapped_data_key = sealed.wrapped_data_key
    record.key_version = sealed.key_version
    record.token_expires_at = token_expires_at
    record.refresh_expires_at = refresh_expires_at


def load_secrets(
    session: Session, cipher: EnvelopeCipher, connection: ExternalConnection
) -> dict[str, Any]:
    record = session.get(ExternalConnectionCredential, connection.id)
    if (
        record is None
        or record.ciphertext is None
        or record.wrapped_data_key is None
        or record.key_version is None
        or record.organization_id != connection.organization_id
    ):
        raise AuthExpiredError("credentials_missing")
    try:
        plaintext = cipher.decrypt(
            EncryptedSecret(record.ciphertext, record.wrapped_data_key, record.key_version),
            associated_data=associated_data(
                connection.organization_id, connection.id, connection.provider
            ),
        )
    except DecryptionError:
        raise AuthExpiredError("credentials_unreadable") from None
    secrets: dict[str, Any] = json.loads(plaintext)
    return secrets


def erase_secrets(session: Session, connection_id: uuid.UUID) -> None:
    record = session.get(ExternalConnectionCredential, connection_id)
    if record is not None:
        record.ciphertext = None
        record.wrapped_data_key = None
        record.key_version = None
