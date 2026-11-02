"""The browser tests' billing helper (task 13-08) subscribes through the simulator and refuses
deployed settings."""

from __future__ import annotations

import json

from app.core.settings import Environment


def test_the_helper_subscribes_the_organization(make_client, capsys):
    from tests import e2e_billing as seed

    owner = make_client()
    owner.signup("seed-billing@example.com")
    org = owner.create_org("Seed Billing")["id"]
    args = ["--email", "seed-billing@example.com", "--organization", org, "--plan", "starter"]
    assert seed.main(args) == 0, capsys.readouterr().err
    assert json.loads(capsys.readouterr().out) == {"status": "active", "plan": "starter"}


def test_the_helper_refuses_a_deployed_environment(monkeypatch, settings, capsys):
    from tests import e2e_billing as seed

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(seed, "get_settings", lambda: deployed)
    args = ["--email", "x@example.com", "--organization", "00000000-0000-0000-0000-000000000000"]
    assert seed.main(args) == 1
    assert "deployed" in capsys.readouterr().err
