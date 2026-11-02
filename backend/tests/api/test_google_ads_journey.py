"""The whole Phase 3 journey against the Google Ads simulator (task 3-10, PLAN §14).

One organization, start to finish, through the real API, database, job runner and the
simulator (OAuth with PKCE, REST ``searchStream``, managers, quotas):

connect → discover (directly and through a manager; a cancelled account cannot be linked) →
link two accounts → first import (structure + 13 months) → the 3-hour run picks up a renamed
campaign → a correction to a past day is picked up by the nightly run → the shared allowance
runs out and every run waits, then continues by itself → the person removes AdVegaX in their
Google account ("Needs reconnecting"; nothing is updated) → reconnect with the same Google
account (same connection, links and data) → "Sync now" → disconnect (permission revoked at
Google, links ended, figures still readable). Throughout: no token, the developer token or the
client secret ever appears in a response, the audit log or the logs.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.advertising import importer
from app.domains.advertising.importer import enqueue_ad_syncs
from app.domains.advertising.quota import SharedQuota
from app.domains.jobs.service import ClaimedJob
from sqlalchemy import text

from tests.google_ads_sim import (
    CLIENT_SECRET,
    DEVELOPER_TOKEN,
    GoogleAdsSim,
    build_provider,
    perf_row,
    sample_hierarchy,
    sample_performance,
    sample_structure,
)

SUB = "108000000000000000001"
AU, NZ, DIRECT, CANCELLED = "1000000001", "1000000002", "1000000003", "1000000004"
SEARCH_DAY, PMAX_DAY = "2026-10-01", "2026-04-10"
HOURS = timedelta(hours=1)


@pytest.fixture
def sim(runtime, clock):
    s = sample_hierarchy(GoogleAdsSim(clock=clock))
    for customer in (AU, NZ):
        sample_performance(sample_structure(s.customers[customer]), SEARCH_DAY, PMAX_DAY)
    runtime.providers.register(build_provider(s))
    return s


class Journey:
    """Keeps every response so the test can prove no secret ever left the API."""

    def __init__(self, owner: Any, admin_engine: Any, sim: GoogleAdsSim) -> None:
        self.owner = owner
        self.db = admin_engine
        self.sim = sim
        self.bodies: list[str] = []
        self.org = owner.org

    def keep(self, response: Any) -> Any:
        self.bodies.append(response.text)
        return response

    def get(self, path: str) -> Any:
        response = self.keep(self.owner.get(f"/organizations/{self.org}{path}"))
        assert response.status_code == 200, (path, response.text)
        return response.json()["data"]

    def post(self, path: str) -> Any:
        return self.keep(self.owner.post(f"/organizations/{self.org}{path}"))

    def rows(self, sql: str, **params: Any) -> list[Any]:
        with self.db.begin() as db:
            return list(db.execute(text(sql), params).mappings().all())

    def connect(self) -> str:
        started = self.keep(
            self.owner.post(
                f"/organizations/{self.org}/connections/google_ads/start", {"params": {}}
            )
        ).json()["data"]["authorize_url"]
        response = self.owner.http.get(
            "/api/v1/connections/google_ads/callback",
            params=self.sim.approve(started, SUB),
            follow_redirects=False,
        )
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert "connection_id" in query, query
        return query["connection_id"][0]

    def accounts(self) -> dict[str, Any]:
        return {a["external_account_id"]: a for a in self.get("/ad-accounts")}

    def day(self, account_id: str, day: str) -> dict[str, Any]:
        data = self.get(f"/ad-accounts/{account_id}/metrics/daily?from={day}&to={day}")
        (only,) = data["days"]
        return dict(only)

    def run_waiting_steps(self, runtime: Any) -> None:
        """Run each account's held-back step now (the delayed job's time has come)."""
        for state in self.rows("SELECT ad_account_id, import_job_id FROM ad_sync_state"):
            if state["import_job_id"] is None:
                continue
            importer.import_step(
                runtime,
                ClaimedJob(
                    state["import_job_id"],
                    uuid.UUID(self.org),
                    importer.JOB_AD_IMPORT_STEP,
                    str(state["ad_account_id"]),
                    1,
                    5,
                    None,
                    None,
                ),
            )


def test_the_whole_google_ads_journey(make_client, sim, clock, runtime, admin_engine, caplog):
    caplog.set_level(logging.DEBUG)
    owner = make_client()
    owner.signup("ads-journey@example.com")
    owner.org = owner.create_org("Eve Zone")["id"]
    j = Journey(owner, admin_engine, sim)

    # 1. Connect: Google's sign-in with PKCE; accounts are found directly and through the
    #    agency's managers; the cancelled one says why it cannot be linked.
    conn = j.connect()
    resources = {r["external_id"]: r for r in j.get(f"/connections/{conn}/resources")}
    assert set(resources) == {AU, NZ, DIRECT, CANCELLED}
    assert resources[AU]["group_path"] == resources[NZ]["group_path"]
    assert resources[AU]["group_path"] and resources[DIRECT]["group_path"] is None
    assert resources[CANCELLED]["unavailable_reason"] == "account_not_enabled"
    refused = j.post(f"/resources/{resources[CANCELLED]['id']}/link")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "RESOURCE_UNAVAILABLE")

    # 2. Link the two agency accounts: each imports its structure and 13 months of figures.
    for external in (AU, NZ):
        assert j.post(f"/resources/{resources[external]['id']}/link").status_code == 201
    accounts = j.accounts()
    assert set(accounts) == {AU, NZ}
    au = accounts[AU]
    assert (au["status"], au["currency"], au["sync"]["running"]) == ("active", "AUD", False)
    assert au["first_import_completed_at"] and au["history_from"] == "2025-09-14"
    search = j.day(au["id"], SEARCH_DAY)
    assert (search["cost"], search["clicks"]) == ("12.345678", 34)
    totals = j.get(f"/ad-accounts/{au['id']}/metrics/daily")["totals"]
    assert (totals["availability"], totals["cost"]) == ("available", "12.345678")
    names = [c["name"] for c in j.get(f"/ad-accounts/{au['id']}/campaigns")["items"]]
    assert names == ["Gloves - Search", "Old test", "Spring - PMax"]

    # 3. Three hours later: the 3-hour run reads the structure and the last two days.
    sim.customers[AU].campaigns[0]["campaign"]["name"] = "Gloves - Search (AU)"
    clock.advance(3 * HOURS)
    assert enqueue_ad_syncs(runtime) == 2
    names = [c["name"] for c in j.get(f"/ad-accounts/{au['id']}/campaigns")["items"]]
    assert "Gloves - Search (AU)" in names

    # 4. Google corrects a past day (invalid clicks removed): the nightly run picks it up.
    sim.customers[AU].performance["account"][0] = perf_row(
        SEARCH_DAY, impressions=1200, clicks=30, cost_micros=9_000_000
    )
    clock.advance(21 * HOURS)
    assert enqueue_ad_syncs(runtime) == 2  # both accounts' nightly runs
    corrected = j.day(au["id"], SEARCH_DAY)
    assert (corrected["clicks"], corrected["cost"]) == (30, "9.000000")

    # 5. The allowance shared by every customer runs out: runs wait, nothing is marked, and
    #    they continue by themselves once the 24-hour window has moved on.
    provider = runtime.providers.get("google_ads")
    provider.shared_daily_operations = 100
    clock.advance(3 * HOURS)
    SharedQuota(runtime.redis, clock).reserve("google_ads", 100, ceiling=100, window_seconds=86400)
    before = len(sim.calls("googleAds:searchStream"))
    assert enqueue_ad_syncs(runtime) == 2
    assert len(sim.calls("googleAds:searchStream")) == before  # nothing was sent to Google
    waiting = j.accounts()[AU]["sync"]
    assert (waiting["running"], waiting["waiting_for_allowance"], waiting["last_error_code"]) == (
        True,
        True,
        None,
    )
    clock.advance(25 * HOURS)
    j.run_waiting_steps(runtime)
    owner.login("ads-journey@example.com")  # a day idle: the session has ended
    owner.refresh_csrf()
    done = j.accounts()[AU]
    assert (done["sync"]["running"], done["sync"]["waiting_for_allowance"]) == (False, False)
    assert done["health"]["code"] is None and done["status"] == "active"
    provider.shared_daily_operations = None

    # 6. The person removes AdVegaX in their Google account: the next run cannot sign in,
    #    the connection says "Needs reconnecting", and nothing else changes.
    sim.refresh_tokens.clear()
    clock.advance(3 * HOURS)
    enqueue_ad_syncs(runtime)
    detail = j.get(f"/connections/{conn}")
    assert (detail["status"], detail["last_error_code"]) == ("expired", "google_sign_in_rejected")
    assert j.accounts()[AU]["connection_status"] == "expired"
    assert enqueue_ad_syncs(runtime) == 0  # no runs while it needs reconnecting
    assert j.day(au["id"], SEARCH_DAY)["cost"] == "9.000000"  # figures still readable

    # 7. Reconnect with the same Google account: the same connection, links and figures.
    assert j.connect() == conn
    assert j.get(f"/connections/{conn}")["status"] == "active"
    again = j.accounts()
    assert again[AU]["id"] == au["id"] and again[AU]["linked"] is True
    assert len(j.rows("SELECT id FROM ad_accounts")) == 2

    # 8. "Sync now" from the account page: the structure and the last 30 days.
    resync = j.post(f"/ad-accounts/{au['id']}/resync")
    assert resync.status_code == 202, resync.text
    assert resync.json()["data"]["mode"] == "nightly"
    viewer = make_client()
    viewer.signup("ads-journey-viewer@example.com")
    owner.invite_and_join(j.org, viewer, "ads-journey-viewer@example.com", "viewer")
    assert viewer.get(f"/organizations/{j.org}/ad-accounts/{au['id']}").status_code == 200
    assert viewer.post(f"/organizations/{j.org}/ad-accounts/{au['id']}/resync").status_code == 403

    # 9. Disconnect: Google is asked to revoke the permission, links end, figures stay.
    (refresh,) = sim.refresh_tokens
    disconnected = j.post(f"/connections/{conn}/disconnect")
    assert disconnected.json()["data"]["status"] == "revoked"
    assert refresh in sim.revoked
    after = j.accounts()
    assert {a["linked"] for a in after.values()} == {False}
    assert j.day(au["id"], SEARCH_DAY)["cost"] == "9.000000"
    blocked = j.post(f"/ad-accounts/{au['id']}/resync")
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (409, "AD_ACCOUNT_NOT_SYNCING")
    assert enqueue_ad_syncs(runtime) == 0
    actions = [r["action"] for r in j.rows("SELECT action FROM audit_logs ORDER BY created_at")]
    for expected in (
        "connection.created",
        "resource.linked",
        "ad_account.import_started",
        "ad_account.import_completed",
        "ad_account.sync_started",
        "connection.revoked",
    ):
        assert expected in actions, expected

    # 10. No token or secret ever left the API, the audit log or the logs.
    secrets = [DEVELOPER_TOKEN, CLIENT_SECRET, *sim.access_tokens, *sim.revoked]
    audit = json.dumps([dict(r) for r in j.rows("SELECT * FROM audit_logs")], default=str)
    served = [r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage()]
    for secret in secrets:
        for body in j.bodies:
            assert secret not in body
        assert secret not in audit
        assert all(secret not in line for line in served)
