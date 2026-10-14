"""The browser tests' simulated-store helper (task 2A-11) works and refuses deployed settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.core.settings import Environment

from tests import e2e_shopify_store as seed


def test_connects_and_imports_a_simulated_store(make_client, admin_engine, capsys):
    owner = make_client()
    owner.signup("seed-owner@example.com")
    org = owner.create_org("Seed Co")["id"]
    code = seed.main(
        ["--email", "seed-owner@example.com", "--organization", org, "--shop", "E2E-1"]
    )
    assert code == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    (store,) = owner.get(f"/organizations/{org}/stores").json()["data"]
    assert store["id"] == out["store_id"]
    assert (store["domain"], store["status"], store["linked"]) == (
        "e2e-1.myshopify.com",
        "active",
        True,
    )
    products = owner.get(f"/organizations/{org}/stores/{store['id']}/products").json()["data"]
    assert len(products["items"]) == 2


def test_wrong_password_fails_cleanly(make_client, capsys):
    owner = make_client()
    owner.signup("seed-two@example.com")
    org = owner.create_org("Seed Two")["id"]
    args = ["--email", "seed-two@example.com", "--organization", org, "--shop", "e2e-2"]
    assert seed.main([*args, "--password", "wrong password here"]) == 1
    assert "sign-in failed" in capsys.readouterr().err


def test_refuses_deployed_environments(settings, monkeypatch, capsys):
    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(seed, "get_settings", lambda: deployed)
    assert seed.main(["--email", "a@example.com", "--organization", "x", "--shop", "s"]) == 1
    assert "deployed" in capsys.readouterr().err


def test_sample_orders_are_moved_to_recent_days():
    now = datetime(2027, 3, 10, 12, tzinfo=UTC)
    text = json.dumps(seed.recent_orders(now))
    assert seed.ORDER_AT not in text and seed.REFUND_AT not in text
    assert "2027-03-07T12:00:00Z" in text and "2027-03-09T12:00:00Z" in text
