"""Connect a simulated GA4 property for the browser end-to-end tests (task 5-09).

    uv run python -m tests.e2e_google_analytics --email E --organization ORG_ID

Runs the **real** Google sign-in (PKCE, offline access, ``analytics.readonly`` only) →
discovery by Analytics account (a property without a currency cannot be linked) → link one
property → first import (13 months, three views) in this process, with the in-process GA4
simulator behind the real ``SafeHttpClient`` and jobs run in-process. Nothing leaves the
machine: CI never calls Google. The sample visits are put on recent days so they fall inside
every view; one day carries Google's privacy-threshold note.

The person must already exist (with the e2e password) and be an owner, admin or manager of the
organization. Prints ``{"property_id": ..., "connection_id": ...}`` as JSON. Refuses to run in
a deployed environment; this module is excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from app.core.settings import get_settings
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime

from tests.ga4_sim import GA4Sim, Visit, build_provider
from tests.helpers import ApiClient

SUB = "108000000000000000077"
AU, NZ, NO_DETAILS = "111", "112", "211"


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def sample(sim: GA4Sim, today: date) -> None:
    """Eve Zone AU: organic and paid visits three days ago, a refund the day after."""
    sim.add_account("900", "Eve Zone")
    sim.add_account("901", "Mediflex")
    au = sim.add_property(AU, "900", SUB, display_name="Eve Zone AU")
    sim.add_property(
        NZ, "900", SUB, display_name="Eve Zone NZ", currency="NZD", time_zone="Pacific/Auckland"
    )
    sim.add_property(NO_DETAILS, "901", SUB, display_name="Mediflex", currency=None)
    busy = date.fromordinal(today.toordinal() - 3)
    au.traffic = [
        Visit(
            busy,
            sessions=120,
            engaged=80,
            users=95,
            new_users=40,
            key_events=Decimal("12"),
            purchases=3,
            revenue=Decimal("189.90"),
        ),
        Visit(
            busy,
            channel="Paid Search",
            source="google",
            medium="cpc",
            campaign="Spring Sale",
            sessions=30,
            engaged=24,
            users=28,
            new_users=10,
            key_events=Decimal("4.5"),
            purchases=2,
            revenue=Decimal("120.50"),
        ),
        Visit(
            date.fromordinal(busy.toordinal() + 1),
            sessions=10,
            engaged=5,
            users=9,
            new_users=2,
            key_events=Decimal("1"),
            purchases=0,
            revenue=Decimal("-20.00"),
        ),
    ]
    au.day_users[busy] = 118  # Google's distinct users for the day, not 95 + 28
    au.metadata = {"total": {"subjectToThresholding": True}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--password", default="correct horse battery staple")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.is_deployed:
        return _fail("refusing to run in a deployed environment")

    runtime = build_runtime(settings)
    sim = GA4Sim(clock=runtime.clock)
    sample(sim, runtime.clock.now().astimezone(ZoneInfo("Australia/Sydney")).date())
    # The simulator replaces the real provider when Google Analytics is switched on (as in CI).
    runtime.providers._providers.pop("google_analytics", None)
    runtime.providers.register(build_provider(sim))
    set_worker_runtime(runtime)  # jobs run here, with the simulator, not in the worker
    celery_app.conf.task_always_eager = True
    app = create_app(settings, runtime)
    client = ApiClient(app)
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        org = args.organization
        started = client.post(
            f"/organizations/{org}/connections/google_analytics/start", {"params": {}}
        )
        if started.status_code != 200:
            return _fail(f"start failed: {started.status_code}")
        returned = client.http.get(
            "/api/v1/connections/google_analytics/callback",
            params=sim.approve(started.json()["data"]["authorize_url"], SUB),
            follow_redirects=False,
        )
        query = parse_qs(urlsplit(returned.headers.get("location", "")).query)
        if "connection_id" not in query:
            return _fail("Google Analytics did not connect")
        connection = query["connection_id"][0]
        resources = client.get(f"/organizations/{org}/connections/{connection}/resources")
        by_id = {r["external_id"]: r for r in resources.json()["data"]}
        linked = client.post(f"/organizations/{org}/resources/{by_id[AU]['id']}/link")
        if linked.status_code != 201:
            return _fail("link failed")
        found = {
            p["external_property_id"]: p
            for p in client.get(f"/organizations/{org}/analytics-properties").json()["data"]
        }
        if found.get(AU, {}).get("status") != "active":
            return _fail("import did not finish")
        print(json.dumps({"property_id": found[AU]["id"], "connection_id": connection}))
        return 0
    finally:
        client.post("/auth/logout")  # leave no extra signed-in session behind
        client.close()
        set_worker_runtime(None)
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
