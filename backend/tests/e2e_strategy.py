"""Make a campaign strategy for the browser end-to-end tests (task 8-07).

    uv run python -m tests.e2e_strategy --email E --organization ORG_ID

Signs in as the person and asks the **real** API for a strategy for the organization's first
product that can be planned, with the connected ad platforms and a budget of 100 a day. The
planner's model is the in-process **AI simulator** (``tests.ai_sim``) behind the real
``SafeHttpClient``: its answer is built from the context AdVegaX itself sends (it cites figures
AdVegaX has and names the risks the rules require), and it passes the same checks as any
answer. Nothing leaves the machine: CI never calls the AI provider.

Prints ``{"strategy_id": ..., "product_title": ...}`` as JSON. Refuses to run in a deployed
environment; this module is excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any

from app.core.settings import get_settings
from app.domains.strategy.context import PlanningContext, build_context
from app.domains.strategy.validation import plannable, required_risks
from app.main import create_app
from app.runtime import build_runtime

from tests.ai_sim import AiSim
from tests.helpers import ApiClient

SHARES = {1: [100], 2: [60, 40]}
TYPES = {"google_ads": "search", "meta_ads": "advantage_plus_shopping"}


def answer_for(context: PlanningContext) -> dict[str, Any]:
    """A strategy that cites only figures AdVegaX has and names every required risk."""
    known = sorted(k for k, f in context.figures.items() if f.value is not None)
    if not known:
        raise RuntimeError("no figure is known for this product")

    def cite(prefix: str) -> list[str]:
        return [next((k for k in known if k.startswith(prefix)), known[0])]

    platforms = context.platforms
    return {
        "objective": "sales",
        "summary": "Start with buyers already searching, then reach similar businesses.",
        "positioning": "Wholesale prices for businesses that buy in bulk.",
        "platforms": [
            {
                "platform": p,
                "campaign_type": TYPES[p],
                "budget_share_percent": share,
                "audience": "Small businesses that reorder supplies every month.",
                "reasoning": "Where this business already finds buyers.",
                "evidence": cite(f"platform.{p}."),
            }
            for p, share in zip(platforms, SHARES[len(platforms)], strict=True)
        ],
        "angles": [{"angle": "Bulk savings per box", "evidence": cite("product.")}],
        "targets": [],
        "risks": [
            {"code": code, "text": "Named because AdVegaX's rules require it."}
            for code in required_risks(context)
        ],
        "assumptions": ["Prices stay as they are."],
    }


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True)
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
        stores = client.get(f"/organizations/{org}/stores").json()["data"]
        for store in stores:
            products = client.get(f"/organizations/{org}/stores/{store['id']}/products").json()
            for product in products["data"]["items"]:
                with runtime.db.transaction(org_id=uuid.UUID(org)) as session:
                    context = build_context(
                        session,
                        runtime.settings,
                        organization_id=uuid.UUID(org),
                        product_id=uuid.UUID(product["id"]),
                        now=runtime.clock.now(),
                    )
                if plannable(context):
                    continue
                sim.queue(answer_for(context))
                response = client.post(
                    f"/organizations/{org}/ai/campaign-strategies",
                    {
                        "product_id": product["id"],
                        "platforms": context.platforms,
                        "objective": "sales",
                        "budget": {"amount": "100", "period": "daily"},
                    },
                )
                if response.status_code != 201:
                    return _fail(f"the strategy was refused: {response.text}")
                data = response.json()["data"]
                print(
                    json.dumps({"strategy_id": data["id"], "product_title": data["product_title"]})
                )
                return 0
        return _fail("no product can be planned")
    finally:
        client.close()
        runtime.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
