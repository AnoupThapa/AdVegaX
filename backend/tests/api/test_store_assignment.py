"""Phase 6 foundations (task 6-02, PLAN §7, Q-6-1, Q-6-2, Q-6-3).

* An organization with several stores can say which store an ad account's spend or an analytics
  property's visits belong to (owners and admins); null = the whole organization.
* The store must be one of the organization's own (checked by the API and by a composite key).
* Exchange rates are shared reference data: the app role can only read them.
* The reporting currency and time zone are the organization's own settings.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.helpers import connected
from tests.security.test_rls import app_engine  # noqa: F401  (fixture)


def _store_resource(db, org: str, connection: str, tag: str) -> str:
    rid = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO external_resources (id, organization_id, connection_id, kind, provider, "
            "external_id, discovered_at, last_seen_at) VALUES (:id, :org, :conn, 'store', 'fake', "
            ":tag, now(), now())"
        ),
        {"id": rid, "org": org, "conn": connection, "tag": tag},
    )
    return rid


def _seed(admin_engine, org: str, connection: str) -> dict[str, str]:
    """Two stores, one ad account and one analytics property in ``org``."""
    ids = {k: str(uuid.uuid4()) for k in ("store_a", "store_b", "account", "property")}
    with admin_engine.begin() as db:
        for key, tag in (("store_a", "shop-a"), ("store_b", "shop-b")):
            db.execute(
                text(
                    "INSERT INTO stores (id, organization_id, external_resource_id, provider, "
                    "external_store_id, domain, currency, timezone) VALUES "
                    "(:id, :org, :res, 'fake', :tag, :domain, 'AUD', 'Australia/Sydney')"
                ),
                {
                    "id": ids[key],
                    "org": org,
                    "res": _store_resource(db, org, connection, tag),
                    "tag": tag,
                    "domain": f"{tag}.example",
                },
            )
        ad_resource = db.execute(
            text(
                "SELECT id FROM external_resources WHERE organization_id = :org "
                "AND kind = 'ad_account' LIMIT 1"
            ),
            {"org": org},
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO ad_accounts (id, organization_id, external_resource_id, provider, "
                "external_account_id, name, currency, timezone, platform_status) VALUES "
                "(:id, :org, :res, 'fake', 'acc-1', 'Ads', 'AUD', 'Australia/Sydney', 'active')"
            ),
            {"id": ids["account"], "org": org, "res": ad_resource},
        )
        prop_resource = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO external_resources (id, organization_id, connection_id, kind, "
                "provider, external_id, discovered_at, last_seen_at) VALUES (:id, :org, :conn, "
                "'analytics_property', 'fake', 'p-1', now(), now())"
            ),
            {"id": prop_resource, "org": org, "conn": connection},
        )
        db.execute(
            text(
                "INSERT INTO analytics_properties (id, organization_id, external_resource_id, "
                "provider, external_property_id, name, currency, timezone, platform_status) "
                "VALUES (:id, :org, :res, 'fake', 'p-1', 'Site', 'AUD', 'Australia/Sydney', "
                "'active')"
            ),
            {"id": ids["property"], "org": org, "res": prop_resource},
        )
    return ids


@pytest.fixture
def owner(make_client, admin_engine):
    c = make_client()
    c.signup(f"assign-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    c.conn = connected(c, c.org)
    c.ids = _seed(admin_engine, c.org, c.conn)
    return c


def _account(c):
    return f"/organizations/{c.org}/ad-accounts/{c.ids['account']}"


def _property(c):
    return f"/organizations/{c.org}/analytics-properties/{c.ids['property']}"


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


# ------------------------------------------------------------------ store assignment
@pytest.mark.parametrize("path", [_account, _property])
def test_nothing_is_assigned_until_an_owner_chooses(owner, path):
    response = owner.get(path(owner))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["store_id"] is None  # the whole organization


@pytest.mark.parametrize(
    ("path", "kind"), [(_account, "ad_account"), (_property, "analytics_property")]
)
def test_an_owner_assigns_and_clears_a_store(owner, admin_engine, path, kind):
    store = owner.ids["store_b"]
    response = owner.put(f"{path(owner)}/store", {"store_id": store})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["store_id"] == store
    assert owner.get(path(owner)).json()["data"]["store_id"] == store
    cleared = owner.put(f"{path(owner)}/store", {"store_id": None})
    assert cleared.json()["data"]["store_id"] is None
    audits = _rows(
        admin_engine,
        "SELECT before_json AS before, after_json AS after FROM audit_logs "
        "WHERE action = :a ORDER BY created_at",
        a=f"{kind}.store_assigned",
    )
    assert [(a["before"]["store_id"], a["after"]["store_id"]) for a in audits] == [
        (None, store),
        (store, None),
    ]
    again = owner.put(f"{path(owner)}/store", {"store_id": None})  # no change: no new record
    assert again.status_code == 200
    assert (
        len(
            _rows(
                admin_engine,
                "SELECT id FROM audit_logs WHERE action = :a",
                a=f"{kind}.store_assigned",
            )
        )
        == 2
    )


@pytest.mark.parametrize("path", [_account, _property])
def test_only_a_store_of_the_organization_can_be_chosen(owner, make_client, admin_engine, path):
    other = make_client()
    other.signup(f"other-{uuid.uuid4().hex[:6]}@example.com")
    other.org = other.create_org("Other")["id"]
    other.conn = connected(other, other.org)
    foreign = _seed(admin_engine, other.org, other.conn)["store_a"]
    for store in (foreign, str(uuid.uuid4())):
        response = owner.put(f"{path(owner)}/store", {"store_id": store})
        assert (response.status_code, response.json()["error"]["details"]) == (
            422,
            [{"field": "store_id", "issue": "unknown_store"}],
        )


@pytest.mark.parametrize("role", ["manager", "analyst", "viewer"])
@pytest.mark.parametrize("path", [_account, _property])
def test_only_owners_and_admins_assign(owner, make_client, role, path):
    member = make_client()
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    member.signup(email)
    owner.invite_and_join(owner.org, member, email, role)
    member.org, member.ids = owner.org, owner.ids
    assert member.get(path(member)).status_code == 200
    response = member.put(f"{path(member)}/store", {"store_id": owner.ids["store_a"]})
    assert response.status_code == 403


def test_the_database_refuses_another_organizations_store(owner, make_client, admin_engine):
    other = make_client()
    other.signup(f"db-{uuid.uuid4().hex[:6]}@example.com")
    other.org = other.create_org("Other")["id"]
    other.conn = connected(other, other.org)
    foreign = _seed(admin_engine, other.org, other.conn)["store_a"]
    for table, key in (("ad_accounts", "account"), ("analytics_properties", "property")):
        with pytest.raises(IntegrityError), admin_engine.begin() as db:
            db.execute(
                text(f"UPDATE {table} SET store_id = :s WHERE id = :id"),
                {"s": foreign, "id": owner.ids[key]},
            )


def test_removing_a_store_only_clears_the_assignment(owner, admin_engine):
    owner.put(f"{_account(owner)}/store", {"store_id": owner.ids["store_b"]})
    with admin_engine.begin() as db:
        db.execute(text("DELETE FROM stores WHERE id = :s"), {"s": owner.ids["store_b"]})
    (row,) = _rows(
        admin_engine,
        "SELECT organization_id, store_id FROM ad_accounts WHERE id = :id",
        id=owner.ids["account"],
    )
    assert (str(row["organization_id"]), row["store_id"]) == (owner.org, None)


# ------------------------------------------------------------------ exchange rates
def test_exchange_rates_are_read_only_to_the_application(app_engine, settings):  # noqa: F811
    from sqlalchemy import create_engine

    with app_engine.begin() as db:
        assert db.execute(text("SELECT count(*) FROM fx_rates")).scalar_one() >= 0
    with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                "VALUES ('ecb', 'EUR', 'AUD', '2026-10-19', 1.65, now())"
            )
        )
    system = create_engine(settings.DATABASE_URL_SYSTEM.get_secret_value())
    try:
        with system.begin() as db:
            db.execute(
                text(
                    "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                    "VALUES ('ecb', 'EUR', 'AUD', '2026-10-19', 1.6512, now()) "
                    "ON CONFLICT DO NOTHING"
                )
            )
            assert (
                db.execute(
                    text(
                        "SELECT rate FROM fx_rates WHERE quote = 'AUD' AND rate_date = '2026-10-19'"
                    )
                ).scalar_one()
                > 0
            )
        with pytest.raises(DBAPIError, match="permission denied"), system.begin() as db:
            db.execute(text("DELETE FROM fx_rates"))
    finally:
        system.dispose()


@pytest.mark.parametrize(
    "values",
    [
        "('xe', 'EUR', 'AUD', '2026-10-19', 1.65, 1)",
        "('ecb', 'EUR', 'EUR', '2026-10-19', 1, 1)",
        "('ecb', 'EUR', 'aud', '2026-10-19', 1.65, 1)",
        "('ecb', 'EUR', 'AUD', '2026-10-19', 0, 1)",
        "('nrb', 'JPY', 'NPR', '2026-10-19', 9.1, 0)",
    ],
)
def test_invalid_rates_are_refused(admin_engine, values):
    with pytest.raises(IntegrityError), admin_engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO fx_rates (source, base, quote, rate_date, rate, unit, fetched_at) "
                f"SELECT s, b, q, d::date, r, u, now() FROM (VALUES {values}) v(s, b, q, d, r, u)"
            )
        )


# ------------------------------------------------------------------ reporting settings
def test_the_reporting_currency_and_time_zone_are_the_organizations(owner):
    org = owner.get(f"/organizations/{owner.org}").json()["data"]
    assert (org["default_currency"], org["default_timezone"]) == ("AUD", "Australia/Sydney")
    changed = owner.patch(
        f"/organizations/{owner.org}",
        {"default_currency": "NZD", "default_timezone": "Pacific/Auckland"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["default_currency"] == "NZD"
