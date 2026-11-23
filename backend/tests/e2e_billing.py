"""Subscribe an organization through the Stripe simulator, for the browser tests (Phase 13,
13-08).

    uv run python -m tests.e2e_billing --email E --organization ORG_ID --plan starter

The owner (``--email``) starts Checkout through the real API in this process, with billing on
**for this process only** and the in-process Stripe simulator behind the real
``SafeHttpClient``; the simulator completes the payment and its signed
``checkout.session.completed`` event goes through the real webhook intake, which reads the
subscription back and applies it. The web server (billing on, no Stripe key) then shows the
plan. Nothing leaves the machine. Prints ``{"status": ..., "plan": ...}`` as JSON. Refuses to
run in a deployed environment; this module is excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from app.core.settings import get_settings
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime

from tests.helpers import ApiClient
from tests.stripe_sim import StripeSim


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--plan", default="starter", choices=("starter", "growth", "scale"))
    parser.add_argument("--password", default="correct horse battery staple")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.is_deployed:
        return _fail("refusing to run in a deployed environment")
    org = uuid.UUID(args.organization)
    settings = settings.model_copy(update={"BILLING_ENABLED": True})
    runtime = build_runtime(settings)
    sim = StripeSim(clock=runtime.clock)
    sim.seed_prices()
    runtime.extras["billing_provider"] = sim.provider()
    set_worker_runtime(runtime)
    celery_app.conf.task_always_eager = True
    client = ApiClient(create_app(settings, runtime))
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        base = f"/organizations/{org}/billing"
        started = client.post(f"{base}/checkout", {"plan": args.plan, "interval": "month"})
        if started.status_code != 200:
            return _fail(f"checkout was refused: {started.text}")
        session = started.json()["data"]["url"].rsplit("/", 1)[1]
        payload, signature = sim.pay(session)
        hooked = client.http.post(
            "/api/v1/billing/stripe/webhook",
            content=payload,
            headers={"stripe-signature": signature, "content-type": "application/json"},
        )
        if hooked.status_code != 200 or hooked.json()["data"]["status"] != "applied":
            return _fail(f"the event was not applied: {hooked.text}")
        data = client.get(base).json()["data"]
        print(json.dumps({"status": data["status"], "plan": data["subscribed_plan"]}))
        return 0
    finally:
        client.close()
        set_worker_runtime(None)
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
