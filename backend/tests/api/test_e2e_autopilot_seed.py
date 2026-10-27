"""The browser tests' autopilot helper (task 12-07) works and refuses deployed settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.settings import Environment
from sqlalchemy import text


def test_autopilot_pauses_the_nz_campaign(make_client, admin_engine, capsys):
    from tests import e2e_autopilot as seed
    from tests import e2e_google_ads as ads

    owner = make_client()
    owner.signup("seed-auto@example.com")
    org = owner.create_org("Seed Auto")["id"]
    assert ads.main(["--email", "seed-auto@example.com", "--organization", org]) == 0
    linked = json.loads(capsys.readouterr().out)
    today = datetime.now(UTC).date()  # the helpers run on the real clock
    with admin_engine.begin() as db:
        for back in range(45):
            for quote, rate in (("AUD", "1.6"), ("NZD", "1.8"), ("USD", "1.0")):
                db.execute(
                    text(
                        "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                        "VALUES ('ecb', 'EUR', :q, :d, :r, now()) ON CONFLICT DO NOTHING"
                    ),
                    {"q": quote, "d": today - timedelta(days=back), "r": Decimal(rate)},
                )
    args = ["--email", "seed-auto@example.com", "--organization", org]
    assert seed.main([*args, "--connection", linked["connection_id"]]) == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    change = owner.get(f"/organizations/{org}/actions/{out['action']}").json()["data"]
    assert (change["source"], change["status"]) == ("autopilot", "succeeded")
    assert owner.get(f"/organizations/{org}/autopilot").json()["data"]["enabled"] is True


def test_the_autopilot_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_autopilot as seed

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(seed, "get_settings", lambda: deployed)
    args = ["--email", "a@example.com", "--organization", "x", "--connection", "y"]
    assert seed.main(args) == 1
    assert "deployed" in capsys.readouterr().err
