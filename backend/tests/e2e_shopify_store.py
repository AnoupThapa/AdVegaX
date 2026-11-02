"""Connect a simulated Shopify store for the browser end-to-end tests (task 2A-11).

    uv run python -m tests.e2e_shopify_store --email E --organization ORG_ID --shop NAME

Runs the **real** connect → link → first import → daily figures path in this process, with the
in-process Shopify simulator behind the real ``SafeHttpClient`` and jobs run in-process. Nothing
leaves the machine: CI never calls Shopify. The browser tests then read the result through the
running API and web app like any other store.

The person must already exist (with the e2e password) and be an owner, admin or manager of the
organization. Prints ``{"store_id": ..., "connection_id": ...}`` as JSON. Refuses to run in a
deployed environment, and this module is excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.core.settings import get_settings
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime

from tests.helpers import ApiClient
from tests.shopify_sim import (
    ShopifySim,
    build_provider,
    callback_params,
    sample_catalogue,
    sample_orders,
)

ORDER_AT = "2026-10-05T01:30:00Z"
REFUND_AT = "2026-10-08T03:00:00Z"


def recent_orders(now: datetime) -> list[dict[str, Any]]:
    """The sample orders moved to recent days, so they sit inside every default view."""

    def stamp(moment: datetime) -> str:
        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    text = json.dumps(sample_orders())
    text = text.replace(ORDER_AT, stamp(now - timedelta(days=3)))
    text = text.replace(REFUND_AT, stamp(now - timedelta(days=1)))
    return list(json.loads(text))


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--shop", required=True, help="store name, e.g. e2e-1234")
    parser.add_argument("--password", default="correct horse battery staple")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.is_deployed:
        return _fail("refusing to run in a deployed environment")

    runtime = build_runtime(settings)
    shop = f"{args.shop.lower()}.myshopify.com"
    sim = ShopifySim(strict_tokens=True)
    sim.add_shop(shop, catalogue=sample_catalogue(), orders=recent_orders(runtime.clock.now()))
    runtime.providers.register(build_provider(sim, runtime.clock))
    set_worker_runtime(runtime)  # jobs run here, with the simulator, not in the worker
    celery_app.conf.task_always_eager = True
    client = ApiClient(create_app(settings, runtime))
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        org = args.organization
        started = client.post(
            f"/organizations/{org}/connections/shopify/start", {"params": {"shop_domain": shop}}
        )
        if started.status_code != 200:
            return _fail(f"start failed: {started.status_code}")
        callback = client.http.get(
            "/api/v1/connections/shopify/callback",
            params=callback_params(started.json()["data"]["authorize_url"]),
            follow_redirects=False,
        )
        query = parse_qs(urlsplit(callback.headers.get("location", "")).query)
        if "connection_id" not in query:
            return _fail("callback did not connect")
        connection = query["connection_id"][0]
        resources = client.get(f"/organizations/{org}/connections/{connection}/resources")
        (resource,) = resources.json()["data"]
        if client.post(f"/organizations/{org}/resources/{resource['id']}/link").status_code != 201:
            return _fail("link failed")
        (store,) = client.get(f"/organizations/{org}/stores").json()["data"]
        if store["status"] != "active" or sim.rejected_tokens:
            return _fail(f"import did not finish: {store['status']}")
        print(json.dumps({"store_id": store["id"], "connection_id": connection}))
        return 0
    finally:
        client.post("/auth/logout")  # leave no extra signed-in session behind
        client.close()
        set_worker_runtime(None)
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
