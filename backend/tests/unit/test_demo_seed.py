"""The desktop demo data command refuses a deployed environment (Phase 16)."""

from __future__ import annotations

from app.core.settings import Environment


def test_demo_data_never_goes_into_a_deployed_environment(monkeypatch, settings, capsys):
    from demo import seed

    # The command raises the sign-in limits for its own process; keep that out of other tests.
    monkeypatch.setattr(seed.os, "environ", dict(seed.os.environ))

    deployed = settings.model_copy(update={"ENVIRONMENT": Environment.PRODUCTION})
    monkeypatch.setattr(seed, "get_settings", lambda: deployed)
    monkeypatch.setattr(seed.get_settings, "cache_clear", lambda: None, raising=False)
    assert seed.main() == 1
    assert "deployed" in capsys.readouterr().err
