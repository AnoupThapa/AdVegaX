"""Connect simulated Meta ad accounts for the browser end-to-end tests (task 4-08).

    uv run python -m tests.e2e_meta_ads --email E --organization ORG_ID

Runs the **real** Facebook Login for Business (PKCE, long-lived token) → discovery by business
(an account with an unpaid balance cannot be linked) → link one account → first import
(structure with archived and deleted objects, 13 months of figures) in this process, with the
in-process Meta simulator behind the real ``SafeHttpClient`` and jobs run in-process. Nothing
leaves the machine: CI never calls Meta. The sample figures are moved to a recent day so they
fall inside every view, and the sign-in is made to end in 10 days so its notice shows.

The person must already exist (with the e2e password) and be an owner, admin or manager of the
organization. Prints ``{"ad_account_id": ..., "connection_id": ...}`` as JSON. Refuses to run
in a deployed environment; this module is excluded from the Docker image.
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

from tests.helpers import ApiClient
from tests.meta_sim import MetaSim, build_provider, sample_insights, sample_structure

USER = "10160000000000001"
AU, OWN, UNPAID = "act_1001", "act_1003", "act_1004"
SIGN_IN_DAYS = 10


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
    sim = MetaSim(clock=runtime.clock)
    sim.add_user(USER)
    sim.token_expiry_seconds = SIGN_IN_DAYS * 24 * 3600
    today = runtime.clock.now().astimezone(ZoneInfo("Australia/Sydney")).date()
    sale_day = date.fromordinal(today.toordinal() - 3).isoformat()
    sample_insights(
        sample_structure(
            sim.add_account(
                AU, USER, name="Eve Zone AU", currency="AUD", timezone_name="Australia/Sydney"
            )
        ),
        sale_day,
    )
    sim.add_account(OWN, USER, name="Own ads", business=None)
    sim.add_account(UNPAID, USER, name="Old shop", account_status=3)
    # The simulator replaces the real provider when Meta is switched on (as in CI).
    runtime.providers._providers.pop("meta_ads", None)
    runtime.providers.register(build_provider(sim))
    set_worker_runtime(runtime)  # jobs run here, with the simulator, not in the worker
    celery_app.conf.task_always_eager = True
    app = create_app(settings, runtime)
    client = ApiClient(app)
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        org = args.organization
        started = client.post(f"/organizations/{org}/connections/meta_ads/start", {"params": {}})
        if started.status_code != 200:
            return _fail(f"start failed: {started.status_code}")
        returned = client.http.get(
            "/api/v1/connections/meta_ads/callback",
            params=sim.approve(started.json()["data"]["authorize_url"], USER),
            follow_redirects=False,
        )
        query = parse_qs(urlsplit(returned.headers.get("location", "")).query)
        if "connection_id" not in query:
            return _fail("Meta did not connect")
        connection = query["connection_id"][0]
        resources = client.get(f"/organizations/{org}/connections/{connection}/resources")
        by_id = {r["external_id"]: r for r in resources.json()["data"]}
        linked = client.post(f"/organizations/{org}/resources/{by_id[AU]['id']}/link")
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
