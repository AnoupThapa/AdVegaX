"""Fill a desktop installation with demo data (Phase 16, task 16-01; A35).

    uv run python -m demo.seed

Creates two people and three organizations and runs AdVegaX's **real** import, analytics,
AI, change, autopilot, billing and agency paths against its own **simulators** (the same ones
the tests use) — nothing leaves the computer:

* ``demo@advegax.local`` owns **Eve Zone** (Shopify store, Google Ads, Meta, Google Analytics,
  a strategy, creatives, a campaign draft, recommendations, changes) and **Mediflex**
  (WooCommerce store, Google Ads with autopilot, a Starter plan);
* ``agency@advegax.local`` owns **Demo Agency**, which Eve Zone has given Manager access.

Both sign in with the password ``DEMO_PASSWORD`` below. Refuses to run when deployed. Run
``scripts/windows/reset-demo.ps1`` (or drop and re-create the database) to start again.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from collections.abc import Callable
from typing import Any

from app.core.settings import EmailBackend, get_settings
from app.main import create_app
from app.runtime import build_runtime
from app.workers.celery_app import celery_app
from app.workers.email_tasks import set_worker_runtime
from tests.helpers import ApiClient, last_email, token_from

DEMO_PASSWORD = "AdVegaX-demo-2026"  # noqa: S105 - public demo sign-in on a desktop only
OWNER, AGENCY_OWNER = "demo@advegax.local", "agency@advegax.local"


def _run(step: str, main: Callable[[list[str]], int], args: list[str]) -> dict[str, Any]:
    """Run one simulator helper and return the JSON it prints."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main([*args, "--password", DEMO_PASSWORD])
    if code != 0:
        raise SystemExit(f"demo step failed: {step}")
    lines = [line for line in out.getvalue().splitlines() if line.startswith("{")]
    print(f"  ✓ {step}")
    return json.loads(lines[-1]) if lines else {}


def _person(client: ApiClient, email: str, name: str) -> None:
    if client.login(email, DEMO_PASSWORD).status_code != 200:
        if client.register(email, DEMO_PASSWORD, name=name).status_code != 202:
            raise SystemExit(f"could not register {email}")
        if client.login(email, DEMO_PASSWORD).status_code != 200:
            raise SystemExit(f"could not sign in as {email}")
    if client.get("/auth/me").json()["data"]["email_verified"]:
        return
    client.post("/auth/resend-verification", {"email": email})
    client.post("/auth/verify-email", {"token": token_from(last_email(email, "Verify"))})


def _organization(client: ApiClient, name: str) -> str:
    for org in client.get("/organizations").json()["data"]:
        if org["name"] == name and not org.get("via_agency"):
            raise SystemExit(f"demo data already exists ({name}); run reset-demo first")
    return str(client.create_org(name)["id"])


def main() -> int:
    # Many simulated sign-ins within a minute, in this process only.
    os.environ.setdefault("THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE", "100")
    os.environ.setdefault("THROTTLE_LOGIN_PER_IP_PER_MINUTE", "200")
    get_settings.cache_clear()
    from tests import (
        e2e_actions,
        e2e_autopilot,
        e2e_billing,
        e2e_builder,
        e2e_creatives,
        e2e_fx_rates,
        e2e_google_ads,
        e2e_google_analytics,
        e2e_meta_ads,
        e2e_recommendations,
        e2e_shopify_store,
        e2e_strategy,
        e2e_woocommerce_store,
    )

    settings = get_settings()
    if settings.is_deployed:
        print("Refusing to put demo data in a deployed environment.", file=sys.stderr)
        return 1
    # People are made here with emails kept in memory (to read the sign-up link); everything
    # else runs through the helpers with the installation's own settings.
    local = settings.model_copy(
        update={"EMAIL_BACKEND": EmailBackend.MEMORY, "AGENCY_ENABLED": True}
    )
    runtime = build_runtime(local)
    set_worker_runtime(runtime)
    celery_app.conf.task_always_eager = True
    owner, agency = ApiClient(create_app(local, runtime)), ApiClient(create_app(local, runtime))
    try:
        print("Creating the demo people and organizations…")
        _person(owner, OWNER, "Demo Owner")
        _person(agency, AGENCY_OWNER, "Demo Agency Owner")
        eve = _organization(owner, "Eve Zone")
        medi = _organization(owner, "Mediflex")
        firm = _organization(agency, "Demo Agency")

        print("Importing simulated platforms (nothing leaves this computer)…")
        _run("exchange rates", lambda _args: e2e_fx_rates.main(), [])
        base = ["--email", OWNER, "--organization", eve]
        _run("Eve Zone: Shopify store", e2e_shopify_store.main, [*base, "--shop", "evezone-demo"])
        ads = _run("Eve Zone: Google Ads", e2e_google_ads.main, base)
        _run("Eve Zone: Meta ads", e2e_meta_ads.main, base)
        _run("Eve Zone: Google Analytics", e2e_google_analytics.main, base)
        conn = ["--connection", ads["connection_id"]]
        _run("Eve Zone: recommendations", e2e_recommendations.main, [*base, *conn])
        plan = _run("Eve Zone: AI campaign strategy", e2e_strategy.main, base)
        ready = owner.post(
            f"/organizations/{eve}/ai/campaign-strategies/{plan['strategy_id']}/ready"
        )
        if ready.status_code != 200:
            raise SystemExit(f"the strategy could not be marked ready: {ready.text}")
        made = _run(
            "Eve Zone: creatives",
            e2e_creatives.main,
            [*base, "--strategy", plan["strategy_id"]],
        )
        _run(
            "Eve Zone: campaign draft",
            e2e_builder.main,
            [*base, *conn, "--strategy", plan["strategy_id"], "--set", made["set_id"]],
        )
        _run("Eve Zone: changes to ad accounts", e2e_actions.main, [*base, *conn])

        base = ["--email", OWNER, "--organization", medi]
        _run(
            "Mediflex: WooCommerce store",
            e2e_woocommerce_store.main,
            [*base, "--host", "mediflex-demo.example.com"],
        )
        ads = _run("Mediflex: Google Ads", e2e_google_ads.main, base)
        _run(
            "Mediflex: autopilot",
            e2e_autopilot.main,
            [*base, "--connection", ads["connection_id"]],
        )
        _run("Mediflex: Starter plan", e2e_billing.main, [*base, "--plan", "starter"])

        print("Giving Demo Agency access to Eve Zone…")
        code = agency.post(f"/organizations/{firm}/agency/code").json()["data"]["code"]
        grant = owner.post(
            f"/organizations/{eve}/agency/grants", {"code": code, "role": "manager"}
        ).json()["data"]["id"]
        agency.post(f"/organizations/{firm}/agency/grants/{grant}/accept")
        print("  ✓ agency access")
        from app.domains.platform.make_admin import make

        make(OWNER)
        print(f"  ✓ {OWNER} can open the Admin portal (/admin)")
    finally:
        owner.close()
        agency.close()
        runtime.close()
    print(f"\nDone. Sign in at the web app as {OWNER} or {AGENCY_OWNER}, password {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
