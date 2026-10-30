"""Envelope encryption: round trip, tampering, associated data, unknown keys, rotation."""

from __future__ import annotations

import base64
import os

import pytest
from app.core.security.encryption import (
    DecryptionError,
    EncryptedSecret,
    EnvelopeCipher,
    LocalKeyRing,
    parse_key_ring,
)

K1, K2 = os.urandom(32), os.urandom(32)
AAD = b"advegax:credential:v1|org-a|conn-1|fake"


def cipher(keys=None, active=1):
    return EnvelopeCipher(LocalKeyRing(keys or {1: K1}, active))


def test_round_trip_and_randomized_output():
    c = cipher()
    a = c.encrypt(b"secret-token", associated_data=AAD)
    b = c.encrypt(b"secret-token", associated_data=AAD)
    assert a.ciphertext != b.ciphertext  # fresh data key and nonce each time
    assert b"secret-token" not in a.ciphertext + a.wrapped_data_key
    assert c.decrypt(a, associated_data=AAD) == b"secret-token"
    assert a.key_version == 1


def test_tampering_and_wrong_context_fail():
    c = cipher()
    sealed = c.encrypt(b"secret-token", associated_data=AAD)
    flipped = bytearray(sealed.ciphertext)
    flipped[-1] ^= 1
    with pytest.raises(DecryptionError):
        c.decrypt(EncryptedSecret(bytes(flipped), sealed.wrapped_data_key, 1), associated_data=AAD)
    with pytest.raises(DecryptionError):
        c.decrypt(sealed, associated_data=b"advegax:credential:v1|org-b|conn-1|fake")
    bad_wrap = bytearray(sealed.wrapped_data_key)
    bad_wrap[-1] ^= 1
    with pytest.raises(DecryptionError):
        c.decrypt(EncryptedSecret(sealed.ciphertext, bytes(bad_wrap), 1), associated_data=AAD)
    with pytest.raises(DecryptionError):
        cipher({1: K2}).decrypt(sealed, associated_data=AAD)
    with pytest.raises(DecryptionError, match="unknown key version"):
        c.decrypt(
            EncryptedSecret(sealed.ciphertext, sealed.wrapped_data_key, 9), associated_data=AAD
        )


def test_rotation_rewraps_without_changing_ciphertext():
    old = cipher({1: K1})
    sealed = old.encrypt(b"secret-token", associated_data=AAD)
    rotated_cipher = cipher({1: K1, 2: K2}, active=2)
    rotated = rotated_cipher.rewrap(sealed)
    assert rotated.key_version == 2
    assert rotated.ciphertext == sealed.ciphertext
    assert cipher({2: K2}, active=2).decrypt(rotated, associated_data=AAD) == b"secret-token"


def test_key_ring_parsing():
    k = base64.b64encode(K1).decode()
    assert parse_key_ring(f"1:{k}, 2:{base64.b64encode(K2).decode()}") == {1: K1, 2: K2}
    for bad in (
        "",
        "x:" + k,
        "0:" + k,
        "1:not-base64!",
        "1:" + base64.b64encode(b"short").decode(),
        "1" + k,
    ):
        with pytest.raises(ValueError):
            parse_key_ring(bad)
    with pytest.raises(ValueError, match="active key version"):
        LocalKeyRing({1: K1}, 2)
