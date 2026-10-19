"""The whole Phase 4 journey against the Meta simulator (task 4-08, PLAN §14).

One organization, start to finish, through the real API, database, job runner and the
simulator (Facebook Login for Business with PKCE, the long-lived token, ``appsecret_proof``,
the Graph API with usage headers):

connect → discover ad accounts by business (an account with an unpaid balance cannot be
linked) → link an AUD and a JPY account → first import (structure with archived and deleted
objects, 13 months of figures, budgets in cents and in whole yen) → the 3-hour run picks up a
renamed campaign → Meta corrects a past day and the nightly run picks it up → Meta's usage
reaches its limit: runs pause and continue by themselves → the sign-in nears its end: a warning
14 days before, shown with its date → the person removes AdVegaX in Facebook ("Needs
reconnecting"; nothing is updated) → reconnect with the same Facebook account (same
connection, links and data; a new 60 days) → "Sync now" → disconnect (permission removed at
Meta, links ended, figures still readable). Throughout: no token or the app secret ever
appears in a response, the audit log or the logs.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.advertising import importer
from app.domains.advertising.importer import enqueue_ad_syncs
from app.domains.integrations import jobs as integration_jobs
from app.domains.jobs.service import ClaimedJob
from sqlalchemy import text

from tests.meta_sim import (
    APP_SECRET,
    MetaSim,
    build_provider,
    sample_insights,
    sample_structure,
    usage,
)

USER = "10160000000000001"
AU, JP, OWN, UNPAID = "act_1001", "act_1002", "act_1003", "act_1004"
SALE_DAY = "2026-10-01"
HOURS = timedelta(hours=1)
EMAIL = "meta-journey@example.com"


@pytest.fixture
def sim(runtime, clock):
    s = MetaSim(clock=clock)
    s.add_user(USER)
    sample_insights(
        sample_structure(
            s.add_account(
                AU, USER, name="Eve Zone AU", currency="AUD", timezone_name="Australia/Sydney"
            )
        ),
        SALE_DAY,
    )
    sample_insights(
        sample_structure(
            s.add_account(JP, USER, name="Eve Zone JP", currency="JPY", timezone_name="Asia/Tokyo")
        ),
        SALE_DAY,
    )
    s.add_account(OWN, USER, name="Own ads", business=None)
    s.add_account(UNPAID, USER, name="Old shop", account_status=3)
    runtime.providers.register(build_provider(s))
    return s


class Journey:
    """Keeps every response so the test can prove no secret ever left the API."""

    def __init__(self, owner: Any, admin_engine: Any, sim: MetaSim) -> None:
        self.owner = owner
        self.db = admin_engine
        self.sim = sim
        self.bodies: list[str] = []
        self.org = owner.org
        self.tokens_seen: set[str] = set()

    def keep(self, response: Any) -> Any:
        self.bodies.append(response.text)
        self.tokens_seen |= set(self.sim.tokens)
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

    def sign_in_again(self) -> None:
        """Days pass in this test; the person's AdVegaX session ends meanwhile."""
        self.owner.login(EMAIL)
        self.owner.refresh_csrf()

    def connect(self) -> str:
        started = self.keep(
            self.owner.post(f"/organizations/{self.org}/connections/meta_ads/start", {"params": {}})
        ).json()["data"]["authorize_url"]
        response = self.owner.http.get(
            "/api/v1/connections/meta_ads/callback",
            params=self.sim.approve(started, USER),
            follow_redirects=False,
        )
        self.tokens_seen |= set(self.sim.tokens)
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
        for _ in range(30):
            states = [
                s
                for s in self.rows("SELECT ad_account_id, import_job_id FROM ad_sync_state")
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
                        importer.JOB_AD_IMPORT_STEP,
                        str(state["ad_account_id"]),
                        1,
                        5,
                        None,
                        None,
                    ),
                )
        raise AssertionError("the held-back steps did not finish")


def test_the_whole_meta_journey(make_client, sim, clock, runtime, admin_engine, caplog):
    caplog.set_level(logging.DEBUG)
    owner = make_client()
    owner.signup(EMAIL)
    owner.org = owner.create_org("Eve Zone")["id"]
    j = Journey(owner, admin_engine, sim)

    # 1. Connect with Facebook Login for Business; the ad accounts are grouped by business and
    #    the one with an unpaid balance says why it cannot be linked.
    conn = j.connect()
    detail = j.get(f"/connections/{conn}")
    assert (detail["provider"], detail["status"]) == ("meta_ads", "active")
    assert detail["sign_in_expires_at"] is not None  # about 60 days from now
    resources = {r["external_id"]: r for r in j.get(f"/connections/{conn}/resources")}
    assert set(resources) == {AU, JP, OWN, UNPAID}
    assert resources[AU]["group_path"] == resources[JP]["group_path"] == "Eve Zone Business"
    assert resources[OWN]["group_path"] is None
    assert resources[UNPAID]["unavailable_reason"] == "account_unsettled"
    refused = j.post(f"/resources/{resources[UNPAID]['id']}/link")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "RESOURCE_UNAVAILABLE")

    # 2. Link the AUD and the JPY account: each imports its structure and 13 months of figures.
    for external in (AU, JP):
        assert j.post(f"/resources/{resources[external]['id']}/link").status_code == 201
    accounts = j.accounts()
    assert set(accounts) == {AU, JP}
    au, jp = accounts[AU], accounts[JP]
    assert (au["provider"], au["status"], au["currency"]) == ("meta_ads", "active", "AUD")
    assert au["first_import_completed_at"] and au["history_from"] == "2025-09-14"
    assert au["connection_expires_at"] == detail["sign_in_expires_at"]
    sale = j.day(au["id"], SALE_DAY)
    assert (sale["cost"], sale["clicks"], sale["conversions"]) == ("48.750000", 36, "2.000000")
    assert sale["conversion_value"] == "159.900000"  # purchases and their value (omni_purchase)
    campaigns = j.get(f"/ad-accounts/{au['id']}/campaigns")["items"]
    by_name = {c["name"]: c for c in campaigns}
    assert set(by_name) == {"Gloves - Sales", "Spring push", "Winter", "Test"}
    assert (by_name["Winter"]["status"], by_name["Test"]["status"]) == ("archived", "removed")
    assert Decimal(by_name["Gloves - Sales"]["budget"]["amount"]) == Decimal("50")  # 5000 cents
    jp_budget = {c["name"]: c for c in j.get(f"/ad-accounts/{jp['id']}/campaigns")["items"]}
    assert Decimal(jp_budget["Gloves - Sales"]["budget"]["amount"]) == Decimal("5000")  # yen
    sets = j.get(f"/campaigns/{by_name['Gloves - Sales']['id']}")["ad_groups"]
    assert [g["name"] for g in sets] == ["AU buyers"]  # Meta's ad sets

    # 3. Three hours later: the 3-hour run reads the structure and the last days again.
    sim.accounts[AU].campaigns[0]["name"] = "Gloves - Sales (AU)"
    clock.advance(3 * HOURS)
    assert enqueue_ad_syncs(runtime) == 2
    names = {c["name"] for c in j.get(f"/ad-accounts/{au['id']}/campaigns")["items"]}
    assert "Gloves - Sales (AU)" in names

    # 4. Meta corrects a past day (Meta's figures settle after 28 days): the nightly run.
    row = next(r for r in sim.accounts[AU].insights["account"] if r["date_start"] == SALE_DAY)
    row["spend"] = "47.10"
    clock.advance(21 * HOURS)
    assert enqueue_ad_syncs(runtime) == 2
    assert j.day(au["id"], SALE_DAY)["cost"] == "47.100000"

    # 5. Meta's usage reaches its limit: AdVegaX stops calling, every account's run pauses
    #    without using a retry, and continues by itself when Meta's wait is over.
    sim.usage_headers = usage(97, regain_minutes=7)
    clock.advance(3 * HOURS)
    before = len(sim.requests)
    assert enqueue_ad_syncs(runtime) == 2
    # The headers put AdVegaX's whole app at 97 %: after the first answer every Meta account
    # waits, so the second account sends nothing at all.
    assert len(sim.requests) - before == 1
    waiting = j.accounts()[AU]["sync"]
    assert (waiting["running"], waiting["waiting_for_allowance"]) == (True, True)
    assert j.get(f"/connections/{conn}")["status"] == "active"
    sim.usage_headers = {}
    clock.advance(8 * timedelta(minutes=1))
    j.run_waiting_steps(runtime)
    done = j.accounts()[AU]
    assert (done["sync"]["running"], done["sync"]["waiting_for_allowance"]) == (False, False)
    assert done["status"] == "active" and done["health"]["code"] is None

    # 6. The sign-in nears its end: one warning 14 days before, and the date stays visible.
    ends = datetime.fromisoformat(detail["sign_in_expires_at"])
    clock.advance((ends - clock.now()) - timedelta(days=13))
    assert integration_jobs.check_sign_in_expiry(runtime) == 1
    assert integration_jobs.check_sign_in_expiry(runtime) == 0
    j.sign_in_again()
    warned = j.rows("SELECT metadata FROM audit_logs WHERE action = 'connection.sign_in_expiring'")
    assert [w["metadata"]["days"] for w in warned] == [14]
    assert j.accounts()[AU]["connection_expires_at"] == detail["sign_in_expires_at"]

    # 7. The person removes AdVegaX in Facebook: the next run cannot read, the connection says
    #    "Needs reconnecting", and nothing else changes.
    j.tokens_seen |= set(sim.tokens)
    sim.tokens.clear()
    clock.advance(3 * HOURS)
    enqueue_ad_syncs(runtime)
    detail_now = j.get(f"/connections/{conn}")
    assert (detail_now["status"], detail_now["last_error_code"]) == (
        "expired",
        "meta_sign_in_rejected",
    )
    assert j.accounts()[AU]["connection_status"] == "expired"
    assert enqueue_ad_syncs(runtime) == 0  # no runs while it needs reconnecting
    assert j.day(au["id"], SALE_DAY)["cost"] == "47.100000"  # figures still readable

    # 8. Reconnect with the same Facebook account: the same connection, links and figures, and
    #    a new 60 days.
    assert j.connect() == conn
    renewed = j.get(f"/connections/{conn}")
    assert renewed["status"] == "active"
    assert renewed["sign_in_expires_at"] > detail["sign_in_expires_at"]
    again = j.accounts()
    assert again[AU]["id"] == au["id"] and again[AU]["linked"] is True
    assert len(j.rows("SELECT id FROM ad_accounts")) == 2

    # 9. "Sync now" from the account page; viewers can read but not sync.
    resync = j.post(f"/ad-accounts/{au['id']}/resync")
    assert resync.status_code == 202, resync.text
    viewer = make_client()
    viewer.signup("meta-journey-viewer@example.com")
    owner.invite_and_join(j.org, viewer, "meta-journey-viewer@example.com", "viewer")
    assert viewer.get(f"/organizations/{j.org}/ad-accounts/{au['id']}").status_code == 200
    assert viewer.post(f"/organizations/{j.org}/ad-accounts/{au['id']}/resync").status_code == 403

    # 10. Disconnect: Meta is asked to remove AdVegaX's permission, links end, figures stay.
    (live,) = [t for t, v in sim.tokens.items() if v[2]]
    j.tokens_seen |= set(sim.tokens)
    disconnected = j.post(f"/connections/{conn}/disconnect")
    assert disconnected.json()["data"]["status"] == "revoked"
    assert live in sim.removed
    after = j.accounts()
    assert {a["linked"] for a in after.values()} == {False}
    assert {a["connection_expires_at"] for a in after.values()} == {None}
    assert j.day(au["id"], SALE_DAY)["cost"] == "47.100000"
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
        "connection.sign_in_expiring",
        "connection.health_changed",
        "connection.revoked",
    ):
        assert expected in actions, expected
    # Read-only: every call to Meta was a read, except the token exchanges and the removal.
    writes = {(r.method, r.url.path.split("/", 2)[-1]) for r in sim.requests if r.method != "GET"}
    assert writes <= {("POST", "oauth/access_token"), ("DELETE", "me/permissions")}

    # 11. No token or the app secret ever left the API, the audit log or the logs.
    secrets = [APP_SECRET, *j.tokens_seen, *sim.removed]
    assert len(secrets) > 4
    audit = json.dumps([dict(r) for r in j.rows("SELECT * FROM audit_logs")], default=str)
    served = [r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage()]
    for secret in secrets:
        for body in j.bodies:
            assert secret not in body
        assert secret not in audit
        assert all(secret not in line for line in served)
