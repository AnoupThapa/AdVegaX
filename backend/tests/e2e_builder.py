"""Build a simulated Google Ads campaign for the browser end-to-end tests (Phase 10B, 10B-07).

    uv run python -m tests.e2e_builder --email E --organization ORG_ID --connection CONN_ID \
        --strategy STRATEGY_ID --set SET_ID

After ``tests.e2e_google_ads`` linked the simulated Google Ads accounts and
``tests.e2e_creatives`` drafted the creatives of a ready strategy: this process switches the
Action Engine on **for itself only** and, through the **real** API with the in-process Google
Ads simulator behind the real ``SafeHttpClient`` (jobs run here):

1. approves the Google Ads creative, allows changes through the connection and sets the
   maximum daily budget (AUD 500.00);
2. builds a campaign draft from the strategy, adds two keywords and confirms the declarations;
3. launches it: checked, tested by the platform, approved, created **paused** and read back;
4. asks for Go live, which waits for approval.

Nothing leaves the machine; the web server's own engine stays off. Prints
``{"draft": ..., "launch": ..., "go_live": ..., "reference": ...}`` as JSON. Refuses to run in
a deployed environment; this module is excluded from the Docker image.
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
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--set", required=True)
    parser.add_argument("--password", default="correct horse battery staple")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.is_deployed:
        return _fail("refusing to run in a deployed environment")
    settings = settings.model_copy(update={"ACTIONS_ENABLED": True})
    runtime = build_runtime(settings)
    sim = sample_hierarchy(GoogleAdsSim(clock=runtime.clock))
    sample_structure(sim.customers[AU])
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
        found = client.get(f"{base}/creative-sets/{args.set}")
        if found.status_code != 200:
            return _fail("creative set not found")
        google = next(
            (c for c in found.json()["data"]["creatives"] if c["platform"] == "google_ads"), None
        )
        if google is None:
            return _fail("no Google Ads creative")
        approved = client.post(f"{base}/creatives/{google['id']}/approve", {"confirm_flags": True})
        if approved.status_code != 200:
            return _fail(f"the creative was not approved: {approved.text}")
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
        made = client.post(
            f"{base}/campaign-drafts",
            {
                "strategy_id": args.strategy,
                "platform": "google_ads",
                "ad_account_id": accounts[AU]["id"],
            },
        )
        if made.status_code != 201:
            return _fail(f"the draft was refused: {made.text}")
        draft = made.json()["data"]
        filled = client.patch(
            f"{base}/campaign-drafts/{draft['id']}",
            {
                "keywords": [
                    {"text": "nitrile gloves"},
                    {"text": "bulk gloves", "match": "exact"},
                ],
                "confirm_declarations": True,
            },
        )
        if filled.status_code != 200:
            return _fail(f"the draft could not be filled in: {filled.text}")
        asked = client.post(f"{base}/campaign-drafts/{draft['id']}/launch")
        if asked.status_code != 201:
            return _fail(f"the launch was refused: {asked.text}")
        done = client.post(f"{base}/actions/{asked.json()['data']['id']}/approve").json()["data"]
        if done["status"] != "succeeded":
            return _fail(f"the campaign was not created: {done['status']}")
        live = client.post(f"{base}/campaign-drafts/{draft['id']}/go-live")
        if live.status_code != 201:
            return _fail(f"go live was refused: {live.text}")
        print(
            json.dumps(
                {
                    "draft": draft["id"],
                    "launch": done["id"],
                    "go_live": live.json()["data"]["id"],
                    "reference": draft["reference"],
                }
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
