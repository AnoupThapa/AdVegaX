"""The whole Phase 5 journey against the GA4 simulator (task 5-09, PLAN §14).

One organization, start to finish, through the real API, database, job runner and the
simulator (Google sign-in with PKCE and ``analytics.readonly``, the Admin and Data APIs with
Google's quota block):

connect → discover properties by Analytics account (one without a currency cannot be linked)
→ link an AUD (Sydney) and a USD (Los Angeles) property → first import (13 months, three
views) → the 3-hour run → Google corrects a past day and the nightly run picks it up → the
property's hourly tokens run low: its run pauses and continues by itself → the person removes
Analytics access to one property (plain reason on it) → Google stops accepting the sign-in
("Needs reconnecting"; nothing is updated) → reconnect with the same Google account (same
connection, links and data) → "Sync now" → disconnect (permission revoked at Google, links
ended, figures still readable). Throughout: users are never added across days, nothing is
ever written to Google, and no token or the client secret appears in a response, the audit log
or the logs.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.analytics import importer
from app.domains.analytics.importer import enqueue_analytics_syncs
from app.domains.jobs.service import ClaimedJob
from sqlalchemy import text

from tests.ga4_sim import GA4Sim, Visit, build_provider
from tests.google_oauth_sim import CLIENT_SECRET

SUB = "108000000000000000001"
AU, US, NO_DETAILS = "111", "211", "311"
BUSY = date(2026, 10, 5)  # inside the nightly 14-day re-read a day later
HOURS = timedelta(hours=1)
EMAIL = "ga-journey@example.com"


@pytest.fixture
def sim(runtime, clock):
    s = GA4Sim(clock=clock)
    s.add_account("900", "Eve Zone")
    s.add_account("901", "Mediflex")
    au = s.add_property(AU, "900", SUB, display_name="Eve Zone AU")
    us = s.add_property(
        US, "900", SUB, display_name="Eve Zone US", currency="USD", time_zone="America/Los_Angeles"
    )
    s.add_property(NO_DETAILS, "901", SUB, display_name="Mediflex", currency=None)
    au.traffic = [
        Visit(BUSY),
        Visit(
            BUSY,
            channel="Paid Search",
            source="google",
            medium="cpc",
            campaign="Spring Sale",
            sessions=5,
            engaged=4,
            users=4,
            new_users=2,
            key_events=Decimal("1.5"),
            purchases=2,
            revenue=Decimal("120.50"),
        ),
        Visit(date(2026, 10, 3), purchases=0, revenue=Decimal("-30.00")),  # refunds
    ]
    au.day_users[BUSY] = 11
    us.traffic = [Visit(date(2026, 10, 13), sessions=7, revenue=Decimal("19.99"))]
    runtime.providers.register(build_provider(s))
    return s


class Journey:
    """Keeps every response so the test can prove no secret ever left the API."""

    def __init__(self, owner: Any, admin_engine: Any, sim: GA4Sim) -> None:
        self.owner = owner
        self.db = admin_engine
        self.sim = sim
        self.bodies: list[str] = []
        self.org = owner.org
        self.tokens_seen: set[str] = set()

    def remember_tokens(self) -> None:
        self.tokens_seen |= set(self.sim.access_tokens) | set(self.sim.refresh_tokens)

    def keep(self, response: Any) -> Any:
        self.bodies.append(response.text)
        self.remember_tokens()
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
                f"/organizations/{self.org}/connections/google_analytics/start", {"params": {}}
            )
        ).json()["data"]["authorize_url"]
        response = self.owner.http.get(
            "/api/v1/connections/google_analytics/callback",
            params=self.sim.approve(started, SUB),
            follow_redirects=False,
        )
        self.remember_tokens()
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert "connection_id" in query, query
        return query["connection_id"][0]

    def properties(self) -> dict[str, Any]:
        return {p["external_property_id"]: p for p in self.get("/analytics-properties")}

    def day(self, property_id: str, day: date) -> dict[str, Any]:
        data = self.get(f"/analytics-properties/{property_id}/metrics/daily?from={day}&to={day}")
        (only,) = data["days"]
        return dict(only)

    def run_waiting_steps(self, runtime: Any) -> None:
        """Run each property's held-back step now (the delayed job's time has come)."""
        for _ in range(30):
            states = [
                s
                for s in self.rows("SELECT property_id, import_job_id FROM analytics_sync_state")
                if s["import_job_id"] is not None
            ]
            if not states:
                return
            for state in states:
                importer.import_step(
                    runtime,
                    ClaimedJob(
                        state["import_job_id"],
                        uuid.UUID(self.org),
                        importer.JOB_ANALYTICS_IMPORT_STEP,
                        str(state["property_id"]),
                        1,
                        5,
                        None,
                        None,
                    ),
                )
        raise AssertionError("the held-back steps did not finish")


def test_the_whole_google_analytics_journey(make_client, sim, clock, runtime, admin_engine, caplog):
    caplog.set_level(logging.DEBUG)
    owner = make_client()
    owner.signup(EMAIL)
    owner.org = owner.create_org("Eve Zone")["id"]
    j = Journey(owner, admin_engine, sim)

    # 1. Connect with Google (analytics.readonly only); properties are grouped by Analytics
    #    account and the one without a currency says why it cannot be linked.
    conn = j.connect()
    detail = j.get(f"/connections/{conn}")
    assert (detail["provider"], detail["status"]) == ("google_analytics", "active")
    resources = {r["external_id"]: r for r in j.get(f"/connections/{conn}/resources")}
    assert set(resources) == {AU, US, NO_DETAILS}
    assert resources[AU]["group_path"] == resources[US]["group_path"] == "Eve Zone"
    assert resources[NO_DETAILS]["unavailable_reason"] == "property_details_missing"
    refused = j.post(f"/resources/{resources[NO_DETAILS]['id']}/link")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "RESOURCE_UNAVAILABLE")

    # 2. Link both: each imports 13 months in three views, in its own currency and days.
    for external in (AU, US):
        assert j.post(f"/resources/{resources[external]['id']}/link").status_code == 201
    found = j.properties()
    au, us = found[AU], found[US]
    assert (au["status"], au["currency"], au["history_from"]) == ("active", "AUD", "2025-09-14")
    assert (us["status"], us["currency"], us["timezone"]) == (
        "active",
        "USD",
        "America/Los_Angeles",
    )
    busy = j.day(au["id"], BUSY)
    assert (busy["sessions"], busy["total_users"]["value"]) == (15, "11")  # Google's own count
    assert busy["purchase_revenue"] == "170.450000"
    month = j.get(f"/analytics-properties/{au['id']}/metrics/daily?from=2026-10-01&to=2026-10-14")
    assert month["totals"]["total_users"]["reason"] == "users_per_day_only"  # never added up
    assert month["totals"]["purchase_revenue"] == "140.450000"  # a refund day included
    channels = j.get(f"/analytics-properties/{au['id']}/metrics/daily?breakdown=channel")
    assert [i["key"] for i in channels["items"]] == ["Organic Search", "Paid Search"]
    assert j.get(f"/analytics-properties/{us['id']}/metrics/daily")["to_day"] == "2026-10-13"

    # 3. Three hours later: the 3-hour run reads today and yesterday.
    clock.advance(3 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 2
    assert j.properties()[AU]["sync"]["last_quick_at"] is not None

    # 4. Google corrects a past day (late data, key-event credit): the nightly run picks it up.
    sim.properties[AU].traffic[0] = Visit(BUSY, sessions=40, users=30)
    sim.properties[AU].day_users[BUSY] = 33
    clock.advance(21 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 2
    corrected = j.day(au["id"], BUSY)
    assert (corrected["sessions"], corrected["total_users"]["value"]) == (45, "33")

    # 5. Google says the Sydney property's tokens for today are used up: only that property
    #    pauses, without using a retry and without an error; then it continues by itself.
    sim.day_used[AU] = 200_000
    clock.advance(3 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 2
    paused = j.properties()
    assert (paused[AU]["sync"]["running"], paused[AU]["sync"]["waiting_for_allowance"]) == (
        True,
        True,
    )
    assert paused[AU]["sync"]["last_error_code"] is None  # waiting is not an error
    assert paused[AU]["health"]["code"] == "rate_limited"
    assert paused[US]["sync"]["running"] is False  # the other property carried on
    assert j.get(f"/connections/{conn}")["status"] == "active"
    sim.day_used[AU] = 0
    clock.advance(16 * timedelta(minutes=1))
    j.run_waiting_steps(runtime)
    done = j.properties()[AU]
    assert (done["sync"]["running"], done["sync"]["waiting_for_allowance"]) == (False, False)
    assert done["health"]["code"] is None

    # 6. Analytics access to the US property is removed: that property says so; the other one
    #    and the connection are unaffected.
    sim.properties[US].users.clear()
    clock.advance(3 * HOURS)
    assert enqueue_analytics_syncs(runtime) == 2
    after_removal = j.properties()
    assert after_removal[US]["health"]["code"] == "no_property_access"
    assert after_removal[AU]["health"]["code"] is None
    assert j.get(f"/connections/{conn}")["status"] == "active"
    sim.properties[US].users.add(SUB)  # given back in Google Analytics

    # 7. The person removes AdVegaX in their Google account: "Needs reconnecting", no runs.
    j.remember_tokens()
    sim.refresh_tokens.clear()
    sim.access_tokens.clear()
    clock.advance(3 * HOURS)
    enqueue_analytics_syncs(runtime)
    detail_now = j.get(f"/connections/{conn}")
    assert (detail_now["status"], detail_now["last_error_code"]) == (
        "expired",
        "google_sign_in_rejected",
    )
    assert j.properties()[AU]["connection_status"] == "expired"
    assert enqueue_analytics_syncs(runtime) == 0
    assert j.day(au["id"], BUSY)["sessions"] == 45  # figures still readable

    # 8. Reconnect with the same Google account: the same connection, links and figures.
    assert j.connect() == conn
    assert j.get(f"/connections/{conn}")["status"] == "active"
    again = j.properties()
    assert again[AU]["id"] == au["id"] and again[AU]["linked"] is True
    assert len(j.rows("SELECT id FROM analytics_properties")) == 2

    # 9. "Sync now"; viewers can read but not sync. The US property's access problem clears.
    resync = j.post(f"/analytics-properties/{us['id']}/resync")
    assert resync.status_code == 202, resync.text
    assert j.properties()[US]["health"]["code"] is None
    viewer = make_client()
    viewer.signup("ga-journey-viewer@example.com")
    owner.invite_and_join(j.org, viewer, "ga-journey-viewer@example.com", "viewer")
    path = f"/organizations/{j.org}/analytics-properties/{au['id']}"
    assert viewer.get(path).status_code == 200
    assert viewer.post(f"{path}/resync").status_code == 403

    # 10. Disconnect: Google is asked to revoke the permission, links end, figures stay.
    j.remember_tokens()
    disconnected = j.post(f"/connections/{conn}/disconnect")
    assert disconnected.json()["data"]["status"] == "revoked"
    assert len(sim.calls("/revoke")) == 1
    assert {p["linked"] for p in j.properties().values()} == {False}
    assert j.day(au["id"], BUSY)["sessions"] == 45
    blocked = j.post(f"/analytics-properties/{au['id']}/resync")
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (
        409,
        "ANALYTICS_PROPERTY_NOT_SYNCING",
    )
    assert enqueue_analytics_syncs(runtime) == 0
    actions = [r["action"] for r in j.rows("SELECT action FROM audit_logs ORDER BY created_at")]
    for expected in (
        "connection.created",
        "resource.linked",
        "analytics_property.import_started",
        "analytics_property.import_completed",
        "analytics_property.sync_started",
        "connection.health_changed",
        "connection.revoked",
    ):
        assert expected in actions, expected
    # Read-only: every Analytics call was a discovery read or a report.
    analytics = [r for r in sim.requests if r.headers.get("host", "").startswith("analytics")]
    assert {r.method for r in analytics if ":" not in r.url.path} == {"GET"}
    assert {r.url.path.rsplit(":", 1)[-1] for r in analytics if r.method == "POST"} == {
        "batchRunReports"
    }

    # 11. No token or the client secret ever left the API, the audit log or the logs.
    secrets = [CLIENT_SECRET, *j.tokens_seen]
    assert len(secrets) > 4
    audit = json.dumps([dict(r) for r in j.rows("SELECT * FROM audit_logs")], default=str)
    served = [r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage()]
    for secret in secrets:
        for body in j.bodies:
            assert secret not in body
        assert secret not in audit
        assert all(secret not in line for line in served)
