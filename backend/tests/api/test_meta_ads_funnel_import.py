# ruff: noqa: F401, F811 (fixtures shared with test_meta_ads_sync)
"""Meta's funnel actions in the ad import (Phase 7, task 7-03, PLAN §7, Q-7-4).

Every Meta insights row now also gives landing page views, content views, adds to cart and
checkouts initiated, from the ``actions`` list Phase 4 already reads (``landing_page_view``,
``omni_view_content``, ``omni_add_to_cart``, ``omni_initiated_checkout``). A Meta account
imported before Phase 7 is read once more over its history, in the background; a Google Ads
account has no such actions, so it is never re-read for them and they stay "not provided".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.domains.advertising.importer import enqueue_ad_syncs
from sqlalchemy import text

from tests.api import test_google_ads_sync as google
from tests.api.test_meta_ads_sync import (
    AU,
    _finish_chain,
    _link,
    _rows,
    owner,
    sim,
    sleeps,
)

DAY = date(2026, 10, 1)
FUNNEL = ("landing_page_views", "content_views", "adds_to_cart", "checkouts_initiated")


def _perf(admin_engine, level, external_id=AU):
    return _rows(
        admin_engine,
        "SELECT p.* FROM ad_performance_daily p JOIN ad_accounts a ON a.id = p.ad_account_id "
        "WHERE a.external_account_id = :id AND p.level = :level ORDER BY p.day, p.entity_key",
        id=external_id,
        level=level,
    )


def _funnel(row):
    return tuple(row[c] for c in FUNNEL)


def _account(admin_engine, external_id=AU):
    (row,) = _rows(
        admin_engine,
        "SELECT funnel_reread_at, first_import_completed_at FROM ad_accounts "
        "WHERE external_account_id = :id",
        id=external_id,
    )
    return row


def test_every_level_carries_metas_funnel_actions(owner, admin_engine):
    _link(owner)
    (account,) = [r for r in _perf(admin_engine, "account") if r["day"] == DAY]
    assert _funnel(account) == (Decimal(25), Decimal(18), Decimal(6), Decimal(3))
    ads = {r["entity_key"]: r for r in _perf(admin_engine, "ad") if r["day"] == DAY}
    selling = next(r for k, r in ads.items() if k.endswith("340001"))
    assert _funnel(selling)[2] == Decimal(6)
    quiet = next(r for k, r in ads.items() if k.endswith("340003"))
    assert _funnel(quiet) == (Decimal(0),) * 4  # Meta listed no actions: a real zero
    other_day = next(r for r in _perf(admin_engine, "account") if r["day"] != DAY)
    assert _funnel(other_day) == (Decimal(0),) * 4  # a day without activity
    assert (
        _account(admin_engine)["funnel_reread_at"]
        == _account(admin_engine)["first_import_completed_at"]
    )


def test_an_unreadable_action_leaves_only_that_figure_unknown(owner, sim, admin_engine):
    row = next(r for r in sim.accounts[AU].insights["account"] if r["date_start"] == "2026-10-01")
    for action in row["actions"]:
        if action["action_type"] == "omni_add_to_cart":
            action["value"] = "lots"
    _link(owner)
    (account,) = [r for r in _perf(admin_engine, "account") if r["day"] == DAY]
    assert _funnel(account) == (Decimal(25), Decimal(18), None, Decimal(3))
    assert account["cost"] == Decimal("48.75")  # the row is kept


def _imported_before_phase_7(admin_engine):
    with admin_engine.begin() as db:
        db.execute(text("UPDATE ad_accounts SET funnel_reread_at = NULL"))
        db.execute(
            text(
                "UPDATE ad_performance_daily SET landing_page_views = NULL, content_views = NULL, "
                "adds_to_cart = NULL, checkouts_initiated = NULL"
            )
        )


def test_a_meta_account_imported_before_is_read_once_more(owner, sim, runtime, admin_engine, clock):
    _link(owner)
    _imported_before_phase_7(admin_engine)
    before = len(sim.calls("/insights"))
    assert enqueue_ad_syncs(runtime) == 1  # nothing else is due: the re-read starts
    _finish_chain(runtime, owner, admin_engine, clock)
    assert len(sim.calls("/insights")) > before
    (account,) = [r for r in _perf(admin_engine, "account") if r["day"] == DAY]
    assert _funnel(account)[0] == Decimal(25)
    assert _account(admin_engine)["funnel_reread_at"] is not None
    assert enqueue_ad_syncs(runtime) == 0  # once only


def test_a_google_ads_account_is_never_reread_for_funnel_actions(
    make_client, runtime, admin_engine, clock
):
    google_sim = google.sample_hierarchy(google.GoogleAdsSim(clock=clock))
    google.sample_performance(
        google.sample_structure(google_sim.customers[google.AU]), google.SEARCH_DAY, google.PMAX_DAY
    )
    runtime.providers.register(google.build_provider(google_sim))
    google._connect(make_client, google_sim)
    rows = _rows(admin_engine, "SELECT * FROM ad_performance_daily WHERE level = 'account'")
    assert rows and all(_funnel(r) == (None,) * 4 for r in rows)  # not provided by Google Ads
    _imported_before_phase_7(admin_engine)
    before = len(google_sim.requests)
    assert enqueue_ad_syncs(runtime) == 0  # nothing to read again
    assert len(google_sim.requests) == before
    (marked,) = _rows(admin_engine, "SELECT funnel_reread_at FROM ad_accounts")
    assert marked["funnel_reread_at"] is not None
