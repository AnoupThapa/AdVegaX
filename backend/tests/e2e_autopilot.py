"""Let autopilot make a simulated change for the browser end-to-end tests (Phase 12, 12-07).

    uv run python -m tests.e2e_autopilot --email E --organization ORG_ID --connection C

After ``tests.e2e_google_ads`` linked the simulated Google Ads accounts (AU and NZ) and the
recorded exchange rates were stored. This process switches the Action Engine and autopilot on
**for itself only** (with this organization in its allow-list and one verified change as
readiness) and, with the in-process Google Ads simulator behind the real ``SafeHttpClient``:

1. writes 35 days of figures: both Search campaigns spent every day without a conversion;
2. runs the daily look; a person (the owner, through the real API) approves the AU pause,
   which is sent and verified — the organization is now ready;
3. the owner includes the NZ account and switches autopilot on (typing the name);
4. autopilot acts on the NZ advice: the pause is requested, approved by autopilot under the
   policy, sent and verified.

Nothing leaves the machine; the web server's own engine and autopilot stay off. Prints
``{"action": ..., "recommendation": ...}`` (autopilot's change) as JSON. Refuses to run in a
deployed environment; this module is excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from app.core.settings import get_settings
from app.domains.autopilot.runner import run as autopilot
from app.domains.integrations.tokens import usable_secrets
from app.domains.optimization.look import local_today, run_look
from app.domains.organizations.models import Organization
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime

from tests.e2e_google_ads import AU, NZ, SUB
from tests.e2e_recommendations import write_figures
from tests.google_ads_sim import GoogleAdsSim, build_provider, sample_hierarchy, sample_structure
from tests.helpers import ApiClient

NO_RESULTS = {AU: ((25, 0, 0), (20, 2, 60)), NZ: ((60, 0, 0), (40, 4, 150))}
LIMITS = {
    "max_changes_per_day": 5,
    "campaign_cooldown_days": 7,
    "max_decrease_percent": 20,
    "max_cumulative_decrease_percent": 50,
    "cumulative_window_days": 30,
    "min_campaign_age_days": 14,
}


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
    org, connection = uuid.UUID(args.organization), uuid.UUID(args.connection)
    settings = settings.model_copy(
        update={
            "ACTIONS_ENABLED": True,
            "AI_ENABLED": False,
            "AUTOPILOT_ENABLED": True,
            "AUTOPILOT_ORGANIZATIONS": [org],
            "AUTOPILOT_READY_CHANGES": 1,
        }
    )
    runtime = build_runtime(settings)
    sim = sample_hierarchy(GoogleAdsSim(clock=runtime.clock))
    sample_structure(sim.customers[AU])
    sample_structure(sim.customers[NZ])
    runtime.providers._providers.pop("google_ads", None)
    runtime.providers.register(build_provider(sim))
    set_worker_runtime(runtime)
    celery_app.conf.task_always_eager = True
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
        with runtime.db.transaction(org_id=org) as session:
            found = session.get(Organization, org)
            if found is None:
                return _fail("organization not found")
            today, name = local_today(runtime.clock.now(), found.default_timezone), found.name
        write_figures(runtime, org, today, NO_RESULTS)
        run_look(runtime, org)
        items = client.get(f"{base}/recommendations?status=open").json()["data"]["items"]
        by_account = {i["campaign"]["ad_account_name"] or "": i for i in items if i["campaign"]}
        accounts = {
            a["external_account_id"]: a["id"]
            for a in client.get(f"{base}/ad-accounts").json()["data"]
        }
        mine = [
            i for i in items if i["campaign"] and i["campaign"]["ad_account_id"] == accounts[AU]
        ]
        theirs = [
            i for i in items if i["campaign"] and i["campaign"]["ad_account_id"] == accounts[NZ]
        ]
        if not mine or not theirs:
            return _fail(f"the advice was not found: {sorted(by_account)}")
        approved = client.post(f"{base}/recommendations/{mine[0]['id']}/approve")
        if (
            approved.status_code != 200
            or approved.json()["data"]["action"]["status"] != "succeeded"
        ):
            return _fail(f"the person's approval failed: {approved.text}")
        body = {
            "kinds": ["spend_without_results", "losing_money"],
            "ad_account_ids": [accounts[NZ]],
            "excluded_campaign_ids": [],
            **LIMITS,
        }
        if client.put(f"{base}/autopilot", body).status_code != 200:
            return _fail("the policy was refused")
        on = client.post(f"{base}/autopilot/enable", {"confirm": name})
        if on.status_code != 200:
            return _fail(f"autopilot could not be switched on: {on.text}")
        autopilot(runtime, org)
        advice = client.get(f"{base}/recommendations/{theirs[0]['id']}").json()["data"]
        action = advice["action"]
        if advice["status"] != "approved" or action is None or action["status"] != "succeeded":
            return _fail(f"autopilot did not act: {advice['status']} {action}")
        print(json.dumps({"action": action["id"], "recommendation": advice["id"]}))
        return 0
    finally:
        client.post("/auth/logout")
        client.close()
        set_worker_runtime(None)
        runtime.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
