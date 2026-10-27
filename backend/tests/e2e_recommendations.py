"""Make simulated recommendations for the browser end-to-end tests (Phase 11, task 11-08).

    uv run python -m tests.e2e_recommendations --email E --organization ORG_ID --connection C

After ``tests.e2e_google_ads`` linked the simulated Google Ads accounts (AU and NZ) and the
recorded exchange rates were stored: this process switches the Action Engine on **for itself
only** and, with the in-process Google Ads simulator behind the real ``SafeHttpClient``:

1. writes the last 35 days of figures for each account's Search campaign: the AU one spent
   every day without a conversion; the NZ one's cost per conversion tripled;
2. runs the daily look (AdVegaX's own rules; the AI is off), which finds "spend without
   results" (pause) and "cost per conversion jumped" (look into it);
3. through the **real** API: allows changes through the connection, sets the maximum, and
   approves the pause, which is sent, read back and verified.

Nothing leaves the machine; the web server's own engine stays off. Prints
``{"approved": ..., "open": ..., "action": ...}`` as JSON. Refuses to run in a deployed
environment; this module is excluded from the Docker image.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date
from decimal import Decimal

from app.core.settings import get_settings
from app.domains.advertising.models import AdAccount, AdCampaign, AdPerformanceDaily
from app.domains.integrations.tokens import usable_secrets
from app.domains.optimization.look import local_today, run_look
from app.domains.organizations.models import Organization
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from tests.e2e_google_ads import AU, NZ, SUB
from tests.google_ads_sim import GoogleAdsSim, build_provider, sample_hierarchy, sample_structure
from tests.helpers import ApiClient

# (cost, conversions, value) a day: the 7 recent days, then the 28 before them.
FIGURES = {
    AU: ((25, 0, 0), (20, 2, 60)),
    NZ: ((60, 2, 150), (40, 4, 150)),
}


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def write_figures(rt, org: uuid.UUID, today: date) -> None:  # type: ignore[no-untyped-def]
    with rt.db.transaction(org_id=org) as session:
        for external, (recent, baseline) in FIGURES.items():
            account = session.execute(
                select(AdAccount).where(
                    AdAccount.organization_id == org, AdAccount.external_account_id == external
                )
            ).scalar_one()
            campaign = session.execute(
                select(AdCampaign).where(
                    AdCampaign.ad_account_id == account.id,
                    AdCampaign.external_campaign_id == "11",
                )
            ).scalar_one()
            for back in range(1, 36):
                cost, conversions, value = recent if back <= 7 else baseline
                row = {
                    "id": uuid.uuid4(),
                    "organization_id": org,
                    "ad_account_id": account.id,
                    "level": "campaign",
                    "entity_key": campaign.external_campaign_id,
                    "campaign_id": campaign.id,
                    "day": date.fromordinal(today.toordinal() - back),
                    "impressions": 500,
                    "clicks": 40,
                    "cost": Decimal(cost),
                    "conversions": Decimal(conversions),
                    "conversion_value": Decimal(value),
                    "currency": account.currency,
                    "fetched_at": rt.clock.now(),
                }
                session.execute(
                    insert(AdPerformanceDaily)
                    .values(**row)
                    .on_conflict_do_update(
                        constraint="uq_ad_performance_daily_ad_account_id_level_entity_key_day",
                        set_={
                            k: row[k] for k in ("clicks", "cost", "conversions", "conversion_value")
                        },
                    )
                )


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
    settings = settings.model_copy(update={"ACTIONS_ENABLED": True, "AI_ENABLED": False})
    runtime = build_runtime(settings)
    sim = sample_hierarchy(GoogleAdsSim(clock=runtime.clock))
    sample_structure(sim.customers[AU])
    runtime.providers._providers.pop("google_ads", None)
    runtime.providers.register(build_provider(sim))
    set_worker_runtime(runtime)
    celery_app.conf.task_always_eager = True
    org, connection = uuid.UUID(args.organization), uuid.UUID(args.connection)
    token = str(usable_secrets(runtime, org, connection)["access_token"])
    sim.access_tokens[token] = (SUB, runtime.clock.now().timestamp() + 3600)
    client = ApiClient(create_app(settings, runtime))
    try:
        if client.login(args.email, args.password).status_code != 200:
            return _fail("sign-in failed")
        base = f"/organizations/{org}"
        allowed = client.put(f"{base}/connections/{connection}/write-access", {"allowed": True})
        if allowed.status_code != 200:
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
            today = local_today(runtime.clock.now(), found.default_timezone)
        write_figures(runtime, org, today)
        run_look(runtime, org)
        items = client.get(f"{base}/recommendations?status=open").json()["data"]["items"]
        kinds = {i["kind"]: i for i in items}
        if "spend_without_results" not in kinds or "cost_jump" not in kinds:
            return _fail(f"the advice was not found: {sorted(kinds)}")
        approved = client.post(
            f"{base}/recommendations/{kinds['spend_without_results']['id']}/approve"
        )
        if approved.status_code != 200:
            return _fail(f"the approval was refused: {approved.text}")
        action = approved.json()["data"]["action"]
        if action is None or action["status"] != "succeeded":
            return _fail(f"the change was not made: {action}")
        print(
            json.dumps(
                {
                    "approved": kinds["spend_without_results"]["id"],
                    "open": kinds["cost_jump"]["id"],
                    "action": action["id"],
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
