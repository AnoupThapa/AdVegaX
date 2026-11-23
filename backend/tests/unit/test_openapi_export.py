"""The committed OpenAPI schema used by the web app must match the live API (PHASE_01C_PLAN §2)."""

from __future__ import annotations

import json

from app.api import openapi_export


def test_committed_schema_matches_the_application(app):
    committed = openapi_export.DEFAULT_TARGET.read_text(encoding="utf-8")
    assert committed == openapi_export.render(app.openapi()), (
        "frontend/lib/api/openapi.json is out of date: run "
        "`uv run python -m app.api.openapi_export` and `npm run api:generate` in frontend/"
    )


def test_export_writes_stable_json(tmp_path, capsys):
    target = tmp_path / "nested" / "openapi.json"
    assert openapi_export.main([str(target)]) == 0
    first = target.read_text(encoding="utf-8")
    assert openapi_export.main([str(target)]) == 0
    assert target.read_text(encoding="utf-8") == first
    schema = json.loads(first)
    assert schema["info"]["title"] == "AdVegaX API"
    assert "/api/v1/organizations/{organization_id}/connections" in schema["paths"]
    assert "wrote" in capsys.readouterr().out
