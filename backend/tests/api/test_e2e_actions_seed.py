"""The browser tests' change helper (task 10A-07) works and refuses deployed settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.settings import Environment
from sqlalchemy import text


def test_makes_and_undoes_a_simulated_change(make_client, admin_engine, capsys):
    from tests import e2e_actions as seed
    from tests import e2e_google_ads as ads

    owner = make_client()
    owner.signup("seed-actions@example.com")
    org = owner.create_org("Seed Actions")["id"]
    assert ads.main(["--email", "seed-actions@example.com", "--organization", org]) == 0
    linked = json.loads(capsys.readouterr().out)
    today = datetime.now(UTC).date()  # the helpers run on the real clock
    with admin_engine.begin() as db:
        for back in range(3):
            for quote, rate in (("AUD", "1.6"), ("USD", "1.0")):
                db.execute(
                    text(
                        "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                        "VALUES ('ecb', 'EUR', :q, :d, :r, now())"
                    ),
                    {"q": quote, "d": today - timedelta(days=back), "r": Decimal(rate)},
                )
    args = ["--email", "seed-actions@example.com", "--organization", org]
    assert seed.main([*args, "--connection", linked["connection_id"]]) == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    done = owner.get(f"/organizations/{org}/actions/{out['done']}").json()["data"]
    assert (done["status"], done["verification"]) == ("succeeded", "verified")
    assert done["params"] == {"daily_budget": "60.00"}
    undo = owner.get(f"/organizations/{org}/actions/{out['undo']}").json()["data"]
    assert (undo["status"], undo["undo_of"]) == ("pending", out["done"])


def test_the_actions_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_actions as seed

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(seed, "get_settings", lambda: deployed)
    args = ["--email", "a@example.com", "--organization", "x", "--connection", "y"]
    assert seed.main(args) == 1
    assert "deployed" in capsys.readouterr().err
