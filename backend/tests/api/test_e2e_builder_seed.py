"""The browser tests' campaign-building helper (task 10B-07) works and refuses deployed settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.settings import Environment
from sqlalchemy import text

from tests.api.test_creatives_api import maker  # noqa: F401  (fixture)
from tests.api.test_strategies_api import owner  # noqa: F401  (fixture)
from tests.api.test_strategy_context import shop  # noqa: F401  (fixture)


def test_builds_a_paused_campaign_and_asks_for_go_live(maker, admin_engine, capsys):  # noqa: F811
    from tests import e2e_builder as seed
    from tests import e2e_creatives as creative_seed
    from tests import e2e_google_ads as ads

    org = maker.org
    today = datetime.now(UTC).date()  # the helpers run on the real clock
    with admin_engine.begin() as db:
        for back in range(3):
            for quote, rate in (("AUD", "1.6"), ("USD", "1.0")):
                db.execute(
                    text(
                        "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                        "VALUES ('ecb', 'EUR', :q, :d, :r, now()) ON CONFLICT DO NOTHING"
                    ),
                    {"q": quote, "d": today - timedelta(days=back), "r": Decimal(rate)},
                )
    assert ads.main(["--email", maker.email, "--organization", org]) == 0
    linked = json.loads(capsys.readouterr().out)
    args = ["--email", maker.email, "--organization", org, "--strategy", maker.strategy]
    assert creative_seed.main(args) == 0, capsys.readouterr().err
    made = json.loads(capsys.readouterr().out)
    more = ["--connection", linked["connection_id"], "--set", made["set_id"]]
    assert seed.main([*args, *more]) == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    draft = maker.get(f"/organizations/{org}/campaign-drafts/{out['draft']}").json()["data"]
    assert draft["status"] == "created" and draft["reference"] == out["reference"]
    assert draft["open_action_id"] == out["go_live"]
    launch = maker.get(f"/organizations/{org}/actions/{out['launch']}").json()["data"]
    assert (launch["action_type"], launch["status"]) == ("campaign.create", "succeeded")
    live = maker.get(f"/organizations/{org}/actions/{out['go_live']}").json()["data"]
    assert (live["action_type"], live["status"]) == ("campaign.go_live", "pending")
    assert seed.main([*args, "--connection", linked["connection_id"], "--set", org]) == 1


def test_the_builder_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_builder as seed

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(seed, "get_settings", lambda: deployed)
    args = ["--email", "a@example.com", "--organization", "x", "--connection", "y"]
    assert seed.main([*args, "--strategy", "z", "--set", "w"]) == 1
    assert "deployed" in capsys.readouterr().err
