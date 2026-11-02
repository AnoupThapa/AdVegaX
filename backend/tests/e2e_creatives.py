"""Draft creatives for the browser end-to-end tests (task 9-07).

    uv run python -m tests.e2e_creatives --email E --organization ORG_ID --strategy STRATEGY_ID

Signs in and asks the **real** API to draft the ad copy of a strategy marked ready, with the
in-process **AI simulator** (``tests.ai_sim``) as the model behind the real ``SafeHttpClient``.
The simulated answer has one concept per platform of the strategy, within every limit, so it
passes the same checks as any answer. Nothing leaves the machine.

Prints ``{"set_id": ...}`` as JSON. Refuses to run in a deployed environment; this module is
excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.core.settings import get_settings
from app.main import create_app
from app.runtime import build_runtime

from tests.ai_sim import AiSim
from tests.helpers import ApiClient

CONCEPTS: dict[str, dict[str, Any]] = {
    "google_ads": {
        "angle": "Bulk savings",
        "rationale": "Buyers already search for bulk boxes.",
        "compliance_notes": ["Check the delivery promise matches your service."],
        "headlines": ["Gloves in Bulk", "Order by the Box", "Fast Local Delivery"],
        "descriptions": [
            "Powder-free gloves for clinics, kitchens and cleaners.",
            "Order online today for delivery to your business.",
        ],
        "path1": "gloves",
        "path2": "bulk",
    },
    "meta_ads": {
        "angle": "Busy kitchens",
        "rationale": "Hospitality owners reorder every month.",
        "compliance_notes": [],
        "primary_texts": ["Reliable gloves for busy kitchens and clinics."],
        "headlines": ["Gloves for busy teams"],
        "descriptions": ["Free delivery"],
        "call_to_action": "SHOP_NOW",
    },
}


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--password", default="correct horse battery staple")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.is_deployed:
        return _fail("refusing to run in a deployed environment")
    runtime = build_runtime(settings.model_copy(update={"AI_ENABLED": True}))
    sim = AiSim()
    runtime.extras["ai_adapter"] = sim.adapter()
    client = ApiClient(create_app(settings, runtime))
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        org = args.organization
        strategy = client.get(f"/organizations/{org}/ai/campaign-strategies/{args.strategy}")
        if strategy.status_code != 200:
            return _fail("strategy not found")
        platforms = [p["platform"] for p in strategy.json()["data"]["strategy"]["platforms"]]
        sim.queue({p: [CONCEPTS[p]] for p in platforms})
        response = client.post(
            f"/organizations/{org}/ai/creative-sets", {"strategy_id": args.strategy}
        )
        if response.status_code != 201:
            return _fail(f"the creatives were refused: {response.text}")
        print(json.dumps({"set_id": response.json()["data"]["id"]}))
        return 0
    finally:
        client.close()
        runtime.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
