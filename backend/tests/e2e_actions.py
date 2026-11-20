"""Make simulated changes for the browser end-to-end tests (Phase 10A, task 10A-07).

    uv run python -m tests.e2e_actions --email E --organization ORG_ID --connection CONN_ID

After ``tests.e2e_google_ads`` linked the simulated Google Ads accounts: this process switches
the Action Engine on **for itself only** and, through the **real** API with the in-process
Google Ads simulator behind the real ``SafeHttpClient`` (jobs run here):

1. allows changes through the connection and sets the maximum daily budget (AUD 500.00);
2. requests the Search campaign's daily budget from AUD 50.00 to AUD 60.00 (checked, dry run),
   approves it, and the worker sends it, reads it back and verifies it;
3. requests the undo, which waits for approval.

Nothing leaves the machine; the web server's own engine stays off. Prints
``{"done": ..., "undo": ..., "campaign": ...}`` as JSON. Refuses to run in a deployed
environment; this module is excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from app.core.settings import get_settings
from app.domains.integrations.tokens import usable_secrets
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime

from tests.e2e_google_ads import AU, SUB
from tests.google_ads_sim import GoogleAdsSim, build_provider, sample_hierarchy, sample_structure
from tests.helpers import ApiClient


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--connection", required=True)
    parser.add_argument("--password", default="correct horse battery staple")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.is_deployed:
        return _fail("refusing to run in a deployed environment")
    settings = settings.model_copy(update={"ACTIONS_ENABLED": True})
    runtime = build_runtime(settings)
    sim = sample_hierarchy(GoogleAdsSim(clock=runtime.clock))
    sample_structure(sim.customers[AU])
    # This account's Search campaign holds its own budget, so it may be changed here.
    sim.customers[AU].budgets[0]["campaignBudget"]["explicitlyShared"] = False
    runtime.providers._providers.pop("google_ads", None)
    runtime.providers.register(build_provider(sim))
    set_worker_runtime(runtime)
    celery_app.conf.task_always_eager = True
    org, connection = uuid.UUID(args.organization), uuid.UUID(args.connection)
    # The connection's sign-in came from the first helper's simulator: this one accepts it.
    token = str(usable_secrets(runtime, org, connection)["access_token"])
    sim.access_tokens[token] = (SUB, runtime.clock.now().timestamp() + 3600)
    client = ApiClient(create_app(settings, runtime))
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        base = f"/organizations/{org}"
        if (
            client.put(
                f"{base}/connections/{connection}/write-access", {"allowed": True}
            ).status_code
            != 200
        ):
            return _fail("changes could not be allowed")
        saved = client.put(
            f"{base}/action-settings",
            {"paused": False, "require_second_person": False, "max_daily_budget": "500.00"},
        )
        if saved.status_code != 200:
            return _fail("settings were refused")
        accounts = {
            a["external_account_id"]: a for a in client.get(f"{base}/ad-accounts").json()["data"]
        }
        campaigns = client.get(f"{base}/ad-accounts/{accounts[AU]['id']}/campaigns").json()["data"]
        search = next(c for c in campaigns["items"] if c["external_id"] == "11")
        asked = client.post(
            f"{base}/actions",
            {
                "action_type": "campaign.set_daily_budget",
                "campaign_id": search["id"],
                "params": {"daily_budget": "60.00"},
            },
        )
        if asked.status_code != 201:
            return _fail(f"the change was refused: {asked.text}")
        done = client.post(f"{base}/actions/{asked.json()['data']['id']}/approve").json()["data"]
        if done["status"] != "succeeded" or done["verification"] != "verified":
            return _fail(f"the change was not made: {done['status']}")
        undo = client.post(f"{base}/actions/{done['id']}/undo")
        if undo.status_code != 201:
            return _fail(f"the undo was refused: {undo.text}")
        print(
            json.dumps(
                {"done": done["id"], "undo": undo.json()["data"]["id"], "campaign": search["id"]}
            )
        )
        return 0
    finally:
        client.post("/auth/logout")
        client.close()
        set_worker_runtime(None)
        runtime.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
