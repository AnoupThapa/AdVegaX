"""Export the OpenAPI schema that the web app's API types are generated from (PHASE_01C_PLAN §2).

Usage (from backend/): ``uv run python -m app.api.openapi_export [path]``.
The committed copy lives at ``frontend/lib/api/openapi.json``; a backend test fails when it
drifts from the live application, and the frontend regenerates its TypeScript types from it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.main import create_app

DEFAULT_TARGET = Path(__file__).resolve().parents[3] / "frontend" / "lib" / "api" / "openapi.json"


def render(schema: dict[str, Any] | None = None) -> str:
    """Stable, diff-friendly JSON for the schema."""
    if schema is None:
        app = create_app()
        try:
            schema = app.openapi()
        finally:
            app.state.runtime.close()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    target = Path(args[0]) if args else DEFAULT_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
