"""Webhook intake through the real API, database and job runner (task 2A-05, PHASE_02A_PLAN §7).

Covers: no session/CSRF needed but signature required (401 otherwise), the middleware exemption
is exactly one path shape, metadata-only storage, de-duplication, replay window, organization
routing (live connection, then store), uninstall → revoke, privacy requests recorded and
audited, retention purge and rate limiting. Deliveries are built by the Shopify simulator.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.core.errors import RateLimited
from app.domains.webhooks import service as webhooks
from sqlalchemy import text

from tests.shopify_sim import ShopifySim, build_provider, callback_params, webhook_request

SHOP = "eve-zone.myshopify.com"
URL = "/api/v1/webhooks/shopify"


@pytest.fixture
def shopify(runtime, clock):
    sim = ShopifySim()
    sim.add_shop(SHOP)
    runtime.providers.register(build_provider(sim, clock))
    return sim


@pytest.fixture
def owner(make_client, shopify):
    c = make_client()
    c.signup("hooks-owner@example.com")
    c.org = c.create_org("Hook Co")["id"]
    return c


def _connect(client) -> str:
    started = client.post(
        f"/organizations/{client.org}/connections/shopify/start",
        {"params": {"shop_domain": SHOP}},
    ).json()["data"]["authorize_url"]
    response = client.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    return parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]


def _deliver(http, clock, topic, payload, *, shop=SHOP, webhook_id=None, age=None, **kw):
    triggered = clock.now() - (age or timedelta(seconds=1))
    headers, body = webhook_request(
        topic,
        payload,
        shop=shop,
        webhook_id=webhook_id or str(uuid.uuid4()),
        triggered_at=triggered.isoformat(),
        **kw,
    )
    return http.post(URL, content=body, headers=headers)


def _events(admin_engine):
    with admin_engine.begin() as db:
        return (
            db.execute(text("SELECT * FROM webhook_events ORDER BY received_at")).mappings().all()
        )


def _audit_actions(admin_engine, org):
    with admin_engine.begin() as db:
        return [
            row[0]
            for row in db.execute(
                text(
                    "SELECT action FROM audit_logs WHERE organization_id = :o ORDER BY created_at"
                ),
                {"o": org},
            )
        ]


# ------------------------------------------------------------------ authentication
def test_signed_webhook_is_accepted_without_session_or_csrf(owner, client, clock, admin_engine):
    _connect(owner)
    # ``client`` has no session, no Origin header and no CSRF token: only the signature counts.
    response = _deliver(
        client.http,
        clock,
        "products/update",
        {"admin_graphql_api_id": "gid://shopify/Product/1", "updated_at": "2026-10-13T10:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"status": "accepted"}
    (event,) = _events(admin_engine)
    assert event["organization_id"] == uuid.UUID(owner.org)
    assert event["topic"] == "products/update"
    assert event["object_external_id"] == "gid://shopify/Product/1"
    # Connected but the store is not linked/imported: the fetch job records why it skipped.
    assert (event["status"], event["error_code"]) == ("ignored", "store_not_imported")


def test_bad_signature_is_401_and_nothing_is_stored(owner, client, clock, admin_engine):
    _connect(owner)
    response = _deliver(
        client.http, clock, "products/update", {"id": 1}, secret="wrong-secret-0123456789"
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert _events(admin_engine) == []


def test_signed_but_malformed_delivery_is_400(client, shopify, clock):
    headers, body = webhook_request("products/update", {"id": 1}, shop=SHOP, webhook_id="")
    response = client.http.post(URL, content=body, headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_WEBHOOK"


@pytest.mark.parametrize(
    "age", [timedelta(hours=7), -timedelta(minutes=10)], ids=["too-old", "from-the-future"]
)
def test_replayed_or_future_deliveries_are_refused(client, shopify, clock, admin_engine, age):
    response = _deliver(client.http, clock, "products/update", {"id": 1}, age=age)
    assert response.status_code == 401
    assert _events(admin_engine) == []


def test_retries_within_shopifys_four_hour_window_are_accepted(client, shopify, clock):
    response = _deliver(client.http, clock, "products/update", {"id": 1}, age=timedelta(hours=4))
    assert response.status_code == 200


@pytest.mark.parametrize("provider", ["fake", "nope"])
def test_platforms_without_webhooks_answer_404(client, provider):
    response = client.http.post(
        f"/api/v1/webhooks/{provider}", content=b"{}", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 404


def test_body_limits_still_apply(client, shopify):
    response = client.http.post(URL, content=b"x=1", headers={"Content-Type": "text/plain"})
    assert response.status_code == 415
    response = client.http.post(
        URL,
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": "9999999"},
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/webhooks/shopify/compliance",
        "/api/v1/webhooks/",
        "/api/v1/auth/login",
        "/api/v1/organizations",
    ],
)
def test_csrf_exemption_covers_only_the_webhook_path(client, path):
    """Every other POST — including look-alike paths — still needs Origin + CSRF."""
    response = client.http.post(path, json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


# ------------------------------------------------------------------ storage and de-duplication
def test_only_metadata_is_stored_never_the_body(owner, client, clock, admin_engine, caplog):
    _connect(owner)
    caplog.set_level(logging.DEBUG)
    payload = {
        "id": 820982911946154508,
        "email": "jon@example.com",
        "customer": {"id": 1, "first_name": "Jon", "phone": "555-625-1199"},
        "shipping_address": {"address1": "123 Amoebobacterieae St"},
    }
    assert _deliver(client.http, clock, "orders/create", payload).status_code == 200
    (event,) = _events(admin_engine)
    stored = " ".join(str(v) for v in event.values())
    for secret in ("jon@example.com", "555-625", "Amoebobacterieae", "Jon"):
        assert secret not in stored
        assert secret not in caplog.text
    with admin_engine.begin() as db:
        columns = {
            row[0]
            for row in db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'webhook_events'"
                )
            )
        }
    assert not columns & {"body", "payload", "data", "raw"}


def test_redelivery_is_recognised_and_not_repeated(owner, client, clock, admin_engine):
    _connect(owner)
    first = _deliver(client.http, clock, "products/update", {"id": 1}, webhook_id="hook-1")
    again = _deliver(client.http, clock, "products/update", {"id": 1}, webhook_id="hook-1")
    assert first.json()["data"]["status"] == "accepted"
    assert again.status_code == 200
    assert again.json()["data"]["status"] == "duplicate"
    assert len(_events(admin_engine)) == 1


def test_unknown_store_and_unhandled_topics_are_recorded_as_ignored(
    owner, client, clock, admin_engine
):
    _connect(owner)
    unknown = _deliver(client.http, clock, "products/update", {"id": 1}, shop="other.myshopify.com")
    unhandled = _deliver(client.http, clock, "carts/update", {"id": 2})
    assert unknown.json()["data"]["status"] == "ignored"
    assert unhandled.json()["data"]["status"] == "ignored"
    statuses = {
        (e["external_account_id"], e["status"], e["organization_id"]) for e in _events(admin_engine)
    }
    assert statuses == {
        ("other.myshopify.com", "ignored", None),
        (SHOP, "ignored", uuid.UUID(owner.org)),
    }


# ------------------------------------------------------------------ uninstall
def _connection(owner, conn):
    return owner.get(f"/organizations/{owner.org}/connections/{conn}").json()["data"]


def test_uninstall_revokes_the_connection_and_keeps_data(owner, client, clock, admin_engine):
    conn = _connect(owner)
    (resource,) = owner.get(f"/organizations/{owner.org}/connections/{conn}/resources").json()[
        "data"
    ]
    owner.post(f"/organizations/{owner.org}/resources/{resource['id']}/link")
    response = _deliver(
        client.http, clock, "app/uninstalled", {"id": 1, "domain": SHOP}, webhook_id="bye"
    )
    assert response.json()["data"]["status"] == "accepted"
    detail = _connection(owner, conn)
    assert detail["status"] == "revoked"
    assert detail["last_error_code"] == "app_uninstalled"
    with admin_engine.begin() as db:
        ciphertext = db.execute(
            text("SELECT ciphertext FROM external_connection_credentials WHERE connection_id = :c"),
            {"c": conn},
        ).scalar_one()
    assert ciphertext is None  # tokens deleted
    resources = owner.get(f"/organizations/{owner.org}/connections/{conn}/resources").json()["data"]
    assert [r["id"] for r in resources] == [resource["id"]]  # data kept (D-2A-2)
    (event,) = _events(admin_engine)
    assert event["status"] == "processed"
    assert "connection.revoked_by_platform" in _audit_actions(admin_engine, owner.org)
    # Shopify retries the same delivery: nothing happens twice.
    again = _deliver(client.http, clock, "app/uninstalled", {"id": 1}, webhook_id="bye")
    assert again.json()["data"]["status"] == "duplicate"
    assert _audit_actions(admin_engine, owner.org).count("connection.revoked_by_platform") == 1


def test_uninstall_job_is_idempotent(owner, client, clock, runtime, admin_engine):
    _connect(owner)
    _deliver(client.http, clock, "app/uninstalled", {"id": 1}, webhook_id="bye")
    with admin_engine.begin() as db:
        job_id, subject = db.execute(
            text("SELECT id, subject_id FROM job_runs WHERE job_type = :t"),
            {"t": webhooks.JOB_PLATFORM_REVOKED},
        ).one()
    from app.domains.jobs.service import ClaimedJob

    job = ClaimedJob(
        job_id, uuid.UUID(owner.org), webhooks.JOB_PLATFORM_REVOKED, subject, 1, 5, None, None
    )
    webhooks.platform_revoked(runtime, job)  # second run: event already processed → no-op
    assert _audit_actions(admin_engine, owner.org).count("connection.revoked_by_platform") == 1


def test_a_failed_follow_up_leaves_no_record_so_the_retry_is_handled(
    owner, runtime, clock, admin_engine, monkeypatch
):
    conn = _connect(owner)
    headers, body = webhook_request(
        "app/uninstalled",
        {"id": 1},
        shop=SHOP,
        webhook_id="retry-me",
        triggered_at=clock.now().isoformat(),
    )
    lower = {k.lower(): v for k, v in headers.items()}

    def broken(*_a, **_k):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(webhooks, "create_job", broken)
    with pytest.raises(RuntimeError):
        webhooks.receive(runtime, "shopify", lower, body, ip="203.0.113.9")
    assert _events(admin_engine) == []
    monkeypatch.undo()
    assert webhooks.receive(runtime, "shopify", lower, body, ip="203.0.113.9") == "accepted"
    assert _connection(owner, conn)["status"] == "revoked"


# ------------------------------------------------------------------ privacy webhooks
@pytest.mark.parametrize(
    ("topic", "payload", "object_id"),
    [
        (
            "customers/data_request",
            {
                "shop_domain": SHOP,
                "customer": {"id": 191167, "email": "a@b.c"},
                "data_request": {"id": 9},
            },
            "191167",
        ),
        (
            "customers/redact",
            {
                "shop_domain": SHOP,
                "customer": {"id": 191167, "email": "a@b.c"},
                "orders_to_redact": [1],
            },
            "191167",
        ),
    ],
)
def test_customer_privacy_requests_are_recorded_and_audited(
    owner, client, clock, admin_engine, topic, payload, object_id
):
    _connect(owner)
    response = _deliver(client.http, clock, topic, payload)
    assert response.status_code == 200
    (event,) = _events(admin_engine)
    # Carried out at once (2A-07): nothing personal is held, and the customer id that came
    # with the request is removed from the intake log.
    assert (event["status"], event["object_external_id"]) == ("processed", None)
    assert event["error_code"] == "no_personal_data_held"
    actions = _audit_actions(admin_engine, owner.org)
    assert "privacy.request_received" in actions
    assert {"privacy.data_request_answered", "privacy.customer_redacted"} & set(actions)
    assert object_id


def test_shop_redact_after_uninstall_is_routed_through_the_store(
    owner, client, clock, admin_engine
):
    conn = _connect(owner)
    _deliver(client.http, clock, "app/uninstalled", {"id": 1})
    # The connection is revoked now; an imported store still identifies the organization.
    with admin_engine.begin() as db:
        resource = db.execute(
            text("SELECT id FROM external_resources WHERE connection_id = :c"), {"c": conn}
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO stores (id, organization_id, external_resource_id, provider, "
                "external_store_id, domain, currency, timezone) VALUES (gen_random_uuid(), :o, "
                ":r, 'shopify', 'gid://shopify/Shop/1', :d, 'AUD', 'Australia/Sydney')"
            ),
            {"o": owner.org, "r": resource, "d": SHOP},
        )
    clock.advance(timedelta(hours=48))
    response = _deliver(client.http, clock, "shop/redact", {"shop_id": 1, "shop_domain": SHOP})
    assert response.json()["data"]["status"] == "accepted"
    event = _events(admin_engine)[-1]
    assert (event["topic"], event["organization_id"]) == ("shop/redact", uuid.UUID(owner.org))
    assert _audit_actions(admin_engine, owner.org)[-2:] == [
        "privacy.request_received",
        "privacy.shop_redacted",
    ]
    assert _events(admin_engine)[-1]["status"] == "processed"
    with admin_engine.begin() as db:
        assert db.execute(text("SELECT count(*) FROM stores")).scalar_one() == 0  # erased


def test_privacy_request_for_a_store_never_connected_is_acknowledged(client, shopify, clock):
    response = _deliver(
        client.http,
        clock,
        "shop/redact",
        {"shop_id": 2, "shop_domain": "stranger.myshopify.com"},
        shop="stranger.myshopify.com",
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ignored"


# ------------------------------------------------------------------ retention and limits
def test_metadata_older_than_the_retention_period_is_purged(
    owner, client, clock, runtime, admin_engine
):
    _connect(owner)
    _deliver(client.http, clock, "products/update", {"id": 1})
    clock.advance(timedelta(days=29))
    _deliver(client.http, clock, "products/update", {"id": 2})
    clock.advance(timedelta(days=2))
    assert webhooks.purge_expired(runtime) == 1
    assert [e["object_external_id"] for e in _events(admin_engine)] == ["gid://shopify/Product/2"]


def test_purge_is_scheduled(runtime):
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule["webhook-purge"]
    assert schedule["task"] == "advegax.schedule.webhook_purge"
    assert schedule["schedule"] == runtime.settings.SCHEDULE_WEBHOOK_PURGE_INTERVAL.total_seconds()


def test_per_ip_rate_limit(runtime, shopify, clock):
    runtime.settings = runtime.settings.model_copy(update={"THROTTLE_WEBHOOK_PER_IP_PER_MINUTE": 2})
    headers, body = webhook_request(
        "products/update",
        {"id": 1},
        shop=SHOP,
        webhook_id="w",
        triggered_at=clock.now().isoformat(),
    )
    lower = {k.lower(): v for k, v in headers.items()}
    webhooks.receive(runtime, "shopify", lower, body, ip="198.51.100.7")
    webhooks.receive(runtime, "shopify", lower, body, ip="198.51.100.7")
    with pytest.raises(RateLimited):
        webhooks.receive(runtime, "shopify", lower, body, ip="198.51.100.7")
    # Other senders are unaffected.
    assert webhooks.receive(runtime, "shopify", lower, body, ip="198.51.100.8") == "duplicate"


def test_delivery_without_a_trigger_time_is_accepted(client, shopify):
    headers, body = webhook_request("products/update", {"id": 1}, shop=SHOP, webhook_id="no-time")
    response = client.http.post(URL, content=body, headers=headers)
    assert response.json()["data"]["status"] == "ignored"  # store not connected


def test_uninstall_job_for_a_missing_event_is_dropped(runtime):
    from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError

    for subject in (None, str(uuid.uuid4())):
        job = ClaimedJob(
            uuid.uuid4(), uuid.uuid4(), webhooks.JOB_PLATFORM_REVOKED, subject, 1, 5, None, None
        )
        with pytest.raises(JobSubjectGoneError):
            webhooks.platform_revoked(runtime, job)
