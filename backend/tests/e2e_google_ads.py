"""Connect simulated Google Ads accounts for the browser end-to-end tests (task 3-10).

    uv run python -m tests.e2e_google_ads --email E --organization ORG_ID

Runs the **real** Google sign-in (PKCE) → discovery (directly and through managers) → link
two agency accounts → first import (structure + 13 months) in this process, with the
in-process Google Ads simulator behind the real ``SafeHttpClient`` and jobs run in-process.
Nothing leaves the machine: CI never calls Google. The sample figures are moved to recent
days so they fall inside every view.

The person must already exist (with the e2e password) and be an owner, admin or manager of the
organization. Prints ``{"ad_account_id": ..., "connection_id": ...}`` (the AU account) as JSON.
Refuses to run in a deployed environment; this module is excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from app.core.settings import get_settings
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime

from tests.google_ads_sim import (
    GoogleAdsSim,
    build_provider,
    sample_hierarchy,
    sample_performance,
    sample_structure,
)
from tests.helpers import ApiClient

SUB = "108000000000000000001"
AU, NZ = "1000000001", "1000000002"


def recent_days(today: date) -> tuple[str, str]:
    """The Search day three days ago and the Performance Max day twenty days ago."""
    return (
        date.fromordinal(today.toordinal() - 3).isoformat(),
        date.fromordinal(today.toordinal() - 20).isoformat(),
    )


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


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
    sim = sample_hierarchy(GoogleAdsSim(clock=runtime.clock))
    today = runtime.clock.now().astimezone(ZoneInfo("Australia/Sydney")).date()
    search_day, pmax_day = recent_days(today)
    for customer in (AU, NZ):
        sample_performance(sample_structure(sim.customers[customer]), search_day, pmax_day)
    # The simulator replaces the real provider when Google Ads is switched on (as in CI).
    runtime.providers._providers.pop("google_ads", None)
    runtime.providers.register(build_provider(sim))
    set_worker_runtime(runtime)  # jobs run here, with the simulator, not in the worker
    celery_app.conf.task_always_eager = True
    app = create_app(settings, runtime)
    client = ApiClient(app)
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        org = args.organization
        started = client.post(f"/organizations/{org}/connections/google_ads/start", {"params": {}})
        if started.status_code != 200:
            return _fail(f"start failed: {started.status_code}")
        returned = client.http.get(
            "/api/v1/connections/google_ads/callback",
            params=sim.approve(started.json()["data"]["authorize_url"], SUB),
            follow_redirects=False,
        )
        query = parse_qs(urlsplit(returned.headers.get("location", "")).query)
        if "connection_id" not in query:
            return _fail("Google Ads did not connect")
        connection = query["connection_id"][0]
        resources = client.get(f"/organizations/{org}/connections/{connection}/resources")
        by_id = {r["external_id"]: r for r in resources.json()["data"]}
        for external in (AU, NZ):
            linked = client.post(f"/organizations/{org}/resources/{by_id[external]['id']}/link")
            if linked.status_code != 201:
                return _fail("link failed")
        accounts = {
            a["external_account_id"]: a
            for a in client.get(f"/organizations/{org}/ad-accounts").json()["data"]
        }
        if accounts.get(AU, {}).get("status") != "active":
            return _fail("import did not finish")
        print(json.dumps({"ad_account_id": accounts[AU]["id"], "connection_id": connection}))
        return 0
    finally:
        client.post("/auth/logout")  # leave no extra signed-in session behind
        client.close()
        set_worker_runtime(None)
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
