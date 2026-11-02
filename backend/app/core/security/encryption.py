"""Envelope encryption for persisted platform credentials (PHASE_01B_PLAN §8, D15, A16).

Each secret gets a fresh 256-bit data key. The secret is encrypted with AES-256-GCM using
associated data that binds it to its tenant and connection, so a ciphertext copied to another
row or organization cannot be decrypted. The data key is wrapped by a ``KeyProvider``:
``LocalKeyRing`` (keys from the secret store / environment) now; cloud KMS adapters later.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12
_WRAP_AAD = b"advegax:dek-wrap:v1"


class DecryptionError(Exception):
    """Ciphertext, key or associated data does not match. Never includes secret material."""


def parse_key_ring(value: str) -> dict[int, bytes]:
    """Parse ``"1:<base64 32 bytes>,2:<base64 32 bytes>"`` into ``{version: key}``."""
    ring: dict[int, bytes] = {}
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        version_text, sep, encoded = item.partition(":")
        if not sep or not version_text.isdigit() or int(version_text) < 1:
            raise ValueError("ENCRYPTION_KEYS entries must look like '<version>:<base64 key>'")
        try:
            key = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("ENCRYPTION_KEYS contains an invalid base64 key") from None
        if len(key) != KEY_BYTES:
            raise ValueError("ENCRYPTION_KEYS keys must be exactly 32 bytes")
        ring[int(version_text)] = key
    if not ring:
        raise ValueError("ENCRYPTION_KEYS must contain at least one key")
    return ring


class KeyProvider(Protocol):
    @property
    def active_version(self) -> int: ...

    def wrap(self, data_key: bytes) -> tuple[bytes, int]: ...

    def unwrap(self, wrapped: bytes, version: int) -> bytes: ...


class LocalKeyRing:
    """Key-encryption keys held in configuration (from a managed secret store when deployed)."""

    def __init__(self, keys: dict[int, bytes], active_version: int) -> None:
        if active_version not in keys:
            raise ValueError("active key version is not in the key ring")
        self._keys = dict(keys)
        self._active = active_version

    @property
    def active_version(self) -> int:
        return self._active

    def wrap(self, data_key: bytes) -> tuple[bytes, int]:
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self._keys[self._active]).encrypt(nonce, data_key, _WRAP_AAD)
        return nonce + sealed, self._active

    def unwrap(self, wrapped: bytes, version: int) -> bytes:
        key = self._keys.get(version)
        if key is None:
            raise DecryptionError("unknown key version")
        try:
            return AESGCM(key).decrypt(wrapped[:NONCE_BYTES], wrapped[NONCE_BYTES:], _WRAP_AAD)
        except InvalidTag:
            raise DecryptionError("data key could not be unwrapped") from None


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    wrapped_data_key: bytes
    key_version: int


class EnvelopeCipher:
    def __init__(self, provider: KeyProvider) -> None:
        self._provider = provider

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> EncryptedSecret:
        data_key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(data_key).encrypt(nonce, plaintext, associated_data)
        wrapped, version = self._provider.wrap(data_key)
        return EncryptedSecret(
            ciphertext=nonce + sealed, wrapped_data_key=wrapped, key_version=version
        )

    def decrypt(self, secret: EncryptedSecret, *, associated_data: bytes) -> bytes:
        data_key = self._provider.unwrap(secret.wrapped_data_key, secret.key_version)
        try:
            return AESGCM(data_key).decrypt(
                secret.ciphertext[:NONCE_BYTES], secret.ciphertext[NONCE_BYTES:], associated_data
            )
        except InvalidTag:
            raise DecryptionError("secret could not be decrypted") from None

    def rewrap(self, secret: EncryptedSecret) -> EncryptedSecret:
        """Re-wrap the data key with the active key version (key rotation)."""
        data_key = self._provider.unwrap(secret.wrapped_data_key, secret.key_version)
        wrapped, version = self._provider.wrap(data_key)
        return EncryptedSecret(
            ciphertext=secret.ciphertext, wrapped_data_key=wrapped, key_version=version
        )


def cipher_from_settings(keys: str, active_version: int) -> EnvelopeCipher:
    return EnvelopeCipher(LocalKeyRing(parse_key_ring(keys), active_version))
