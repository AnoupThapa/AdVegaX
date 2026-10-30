"""Credential protection: encrypted at rest, tenant-bound, never exposed (D15, A16)."""

from __future__ import annotations

import logging

from app.domains.integrations.rotation import rewrap_all
from app.providers.fake import provider as fake
from sqlalchemy import text

from tests.helpers import connected


def _setup(make_client, email, org_name):
    c = make_client()
    c.signup(email)
    org = c.create_org(org_name)["id"]
    return c, org, connected(c, org)


def _raw_token(runtime, admin_engine, connection_id):
    """Decrypt through the real boundary to learn the token value used by the fake platform."""
    from app.domains.integrations.credentials import load_secrets
    from app.domains.integrations.models import ExternalConnection

    with runtime.db.transaction(org_id=_org_of(admin_engine, connection_id)) as session:
        connection = session.get(ExternalConnection, connection_id)
        return load_secrets(session, runtime.cipher, connection)


def _org_of(admin_engine, connection_id):
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT organization_id FROM external_connections WHERE id = :i"),
            {"i": connection_id},
        ).scalar_one()


def test_secrets_are_encrypted_at_rest_and_never_exposed(
    make_client, admin_engine, runtime, caplog
):
    caplog.set_level(logging.DEBUG)
    c, org, conn = _setup(make_client, "cred@example.com", "Cred Co")
    secrets = _raw_token(runtime, admin_engine, conn)
    token = secrets["access_token"]
    assert token.startswith("fake-at-")
    with admin_engine.connect() as db:
        row = db.execute(
            text(
                "SELECT ciphertext, wrapped_data_key, key_version FROM "
                "external_connection_credentials WHERE connection_id = :i"
            ),
            {"i": conn},
        ).one()
        dumps = " ".join(
            str(r)
            for t in (
                "audit_logs",
                "security_events",
                "job_runs",
                "external_connections",
                "external_resources",
            )
            for r in db.execute(text(f"SELECT * FROM {t}")).all()
        )
    assert token.encode() not in bytes(row.ciphertext)
    assert row.key_version == 1
    assert token not in dumps and secrets["refresh_token"] not in dumps
    for path in (
        f"/organizations/{org}/connections",
        f"/organizations/{org}/connections/{conn}",
        f"/organizations/{org}/connections/{conn}/resources",
    ):
        body = c.get(path).text
        assert token not in body and "ciphertext" not in body and "secret" not in body.lower()
    assert token not in caplog.text


def test_ciphertext_copied_to_another_tenant_cannot_be_decrypted(
    make_client, admin_engine, runtime
):
    _, _, conn_a = _setup(make_client, "a-cred@example.com", "A Cred")
    b, org_b, conn_b = _setup(make_client, "b-cred@example.com", "B Cred")
    with admin_engine.begin() as db:  # attacker with DB write access swaps B's secret for A's
        db.execute(
            text(
                "UPDATE external_connection_credentials SET ciphertext = src.ciphertext, "
                "wrapped_data_key = src.wrapped_data_key FROM external_connection_credentials src "
                "WHERE src.connection_id = :a "
                "AND external_connection_credentials.connection_id = :b"
            ),
            {"a": conn_a, "b": conn_b},
        )
    resources = b.get(f"/organizations/{org_b}/connections/{conn_b}/resources").json()["data"]
    b.post(f"/organizations/{org_b}/resources/{resources[0]['id']}/link")
    job = b.post(f"/organizations/{org_b}/resources/{resources[0]['id']}/sync").json()["data"]
    view = b.get(f"/organizations/{org_b}/jobs/{job['id']}").json()["data"]
    assert (view["status"], view["last_error_code"]) == ("failed", "auth_expired")
    assert not any(call.startswith("sync") for call in fake.behaviour.calls)


def test_disconnect_erases_ciphertext(make_client, admin_engine):
    c, org, conn = _setup(make_client, "erase@example.com", "Erase Co")
    c.post(f"/organizations/{org}/connections/{conn}/disconnect")
    with admin_engine.connect() as db:
        row = db.execute(
            text(
                "SELECT ciphertext, wrapped_data_key, key_version FROM "
                "external_connection_credentials WHERE connection_id = :i"
            ),
            {"i": conn},
        ).one()
    assert tuple(row) == (None, None, None)


def test_key_rotation_rewraps_all_credentials(make_client, admin_engine, settings, clock):
    import base64
    import os

    from app.runtime import build_runtime

    _, _, conn = _setup(make_client, "rot@example.com", "Rot Co")
    new_key = base64.b64encode(os.urandom(32)).decode()
    rotated_settings = settings.model_copy(
        update={
            "ENCRYPTION_KEYS": type(settings.ENCRYPTION_KEYS)(
                settings.ENCRYPTION_KEYS.get_secret_value() + f",2:{new_key}"
            ),
            "ENCRYPTION_ACTIVE_KEY_VERSION": 2,
        }
    )
    rt2 = build_runtime(rotated_settings, clock=clock)
    try:
        assert rewrap_all(rt2) == 1
        assert rewrap_all(rt2) == 0
        with admin_engine.connect() as db:
            assert (
                db.execute(
                    text("SELECT key_version FROM external_connection_credentials")
                ).scalar_one()
                == 2
            )
        secrets = _raw_token(rt2, admin_engine, conn)  # still decryptable after rotation
        assert secrets["access_token"].startswith("fake-at-")
    finally:
        rt2.close()
