"""Credential key rotation: re-wrap every data key with the active key version (PHASE_01B_PLAN §8).

Runs as the narrow ``advegax_system`` role. Ciphertexts are untouched; only the wrapped data
keys change, so secrets are never decrypted into memory beyond the data key itself.

Usage: ``python -m app.domains.integrations.rotation``
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.security.encryption import EncryptedSecret
from app.domains.integrations.models import ExternalConnectionCredential
from app.runtime import Runtime

logger = logging.getLogger("advegax.rotation")


def rewrap_all(rt: Runtime, *, batch_size: int = 200) -> int:
    active = rt.cipher_active_version()
    rotated = 0
    while True:
        with rt.db.transaction(system=True) as session:
            rows = (
                session.execute(
                    select(ExternalConnectionCredential)
                    .where(
                        ExternalConnectionCredential.key_version.is_not(None),
                        ExternalConnectionCredential.key_version != active,
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            if not rows:
                break
            for row in rows:
                if (
                    row.ciphertext is None
                    or row.wrapped_data_key is None
                    or row.key_version is None
                ):
                    continue
                new = rt.cipher.rewrap(
                    EncryptedSecret(row.ciphertext, row.wrapped_data_key, row.key_version)
                )
                row.wrapped_data_key, row.key_version = new.wrapped_data_key, new.key_version
                rotated += 1
    logger.info("credential_keys_rewrapped", extra={"count": rotated, "active_version": active})
    return rotated


if __name__ == "__main__":  # pragma: no cover - operational entry point
    from app.core.settings import get_settings
    from app.runtime import build_runtime

    print(f"rewrapped={rewrap_all(build_runtime(get_settings()))}")
