"""Connect a simulated WooCommerce store for the browser end-to-end tests (task 2B-09).

    uv run python -m tests.e2e_woocommerce_store --email E --organization ORG_ID --host H
        [--cogs-off]

Runs the **real** connect (the store's approval page delivers a read-only key server to
server) → link → paged first import → daily figures path in this process, with the in-process
WooCommerce simulator behind the real ``SafeHttpClient`` and jobs run in-process. Nothing
leaves the machine: CI never calls a real store. ``--cogs-off`` makes the store send no cost
fields, so the store page shows its "Cost not available" health warning.

The person must already exist (with the e2e password) and be an owner, admin or manager of the
organization. Prints ``{"store_id": ..., "connection_id": ...}`` as JSON. Refuses to run in a
deployed environment, and this module is excluded from the Docker image (like ``tests/``).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from app.core.settings import get_settings
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime

from tests.helpers import ApiClient
from tests.woocommerce_sim import WooSim, WooStore, approve, build_provider, sample_store

ORDER_AT = "2026-10-05T01:30:00"
REFUND_AT = "2026-10-08T03:00:00"


def recent_store(store: WooStore, now: datetime) -> WooStore:
    """The sample store with its order and refund moved to recent days (inside every view)."""

    def stamp(moment: datetime) -> str:
        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    sample_store(store)
    moved = {ORDER_AT: stamp(now - timedelta(days=3)), REFUND_AT: stamp(now - timedelta(days=1))}
    for item in (*store.orders, *store.refunds):
        for key in ("date_created_gmt", "date_modified_gmt"):
            if item.get(key) in moved:
                item[key] = moved[item[key]]
    return store


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--host", required=True, help="store host, e.g. e2e-1234.example.com")
    parser.add_argument("--password", default="correct horse battery staple")
    parser.add_argument("--cogs-off", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.is_deployed:
        return _fail("refusing to run in a deployed environment")

    runtime = build_runtime(settings)
    host = args.host.lower()
    sim = WooSim()
    store = recent_store(sim.add_store(host, name="Woo Test Store"), runtime.clock.now())
    store.cogs_enabled = not args.cogs_off
    # The simulator replaces the real provider when WooCommerce is switched on (as in CI).
    runtime.providers._providers.pop("woocommerce", None)
    runtime.providers.register(build_provider(sim))
    set_worker_runtime(runtime)  # jobs run here, with the simulator, not in the worker
    celery_app.conf.task_always_eager = True
    app = create_app(settings, runtime)
    client, platform = ApiClient(app), ApiClient(app)  # the person, and the store's server
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        org = args.organization
        started = client.post(
            f"/organizations/{org}/connections/woocommerce/start",
            {"params": {"store_url": host}},
        )
        if started.status_code != 200:
            return _fail(f"start failed: {started.status_code}")
        _, returned = approve(
            platform.http, client.http, sim, started.json()["data"]["authorize_url"]
        )
        query = parse_qs(urlsplit(returned.headers.get("location", "")).query)
        if "connection_id" not in query:
            return _fail("the store did not connect")
        connection = query["connection_id"][0]
        resources = client.get(f"/organizations/{org}/connections/{connection}/resources")
        (resource,) = resources.json()["data"]
        if client.post(f"/organizations/{org}/resources/{resource['id']}/link").status_code != 201:
            return _fail("link failed")
        (linked,) = client.get(f"/organizations/{org}/stores").json()["data"]
        if linked["status"] != "active":
            return _fail(f"import did not finish: {linked['status']}")
        print(json.dumps({"store_id": linked["id"], "connection_id": connection}))
        return 0
    finally:
        client.post("/auth/logout")  # leave no extra signed-in session behind
        client.close()
        platform.close()
        set_worker_runtime(None)
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
