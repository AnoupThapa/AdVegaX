"""The browser tests' creative-drafting helper (task 9-07) works and refuses deployed settings."""

from __future__ import annotations

import json

from app.core.settings import Environment

from tests.api.test_creatives_api import maker  # noqa: F401  (fixture)
from tests.api.test_strategies_api import owner  # noqa: F401  (fixture)
from tests.api.test_strategy_context import shop  # noqa: F401  (fixture)


# ------------------------------------------------------------------ creatives (9-07)
def test_drafts_creatives_with_the_ai_simulator(maker, capsys):  # noqa: F811
    from tests import e2e_creatives as creative_seed

    args = ["--email", maker.email, "--organization", maker.org, "--strategy", maker.strategy]
    assert creative_seed.main(args) == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    data = maker.get(f"/organizations/{maker.org}/creative-sets/{out['set_id']}").json()["data"]
    assert sorted(c["platform"] for c in data["creatives"]) == ["google_ads", "meta_ads"]
    assert all(c["approvable"] and c["status"] == "draft" for c in data["creatives"])
    assert creative_seed.main([*args[:4], "--strategy", maker.org]) == 1  # not a strategy


def test_the_creatives_seed_refuses_deployed_environments(settings, monkeypatch, capsys):
    from tests import e2e_creatives as creative_seed

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(creative_seed, "get_settings", lambda: deployed)
    assert (
        creative_seed.main(["--email", "a@example.com", "--organization", "x", "--strategy", "y"])
        == 1
    )
    assert "deployed" in capsys.readouterr().err
