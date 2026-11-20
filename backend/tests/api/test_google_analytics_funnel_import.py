# ruff: noqa: F811 (the fixtures are shared with test_google_analytics_sync)
"""The funnel figures in the GA4 import (Phase 7, task 7-02, PLAN §7, Q-7-3).

Every view now carries product views (``view_item`` events), adds to cart and checkouts started,
and a fourth view keeps each day's landing pages — paths only, never query strings — capped like
the source view. A property imported before Phase 7 is read once more over its whole history,
in the background, only when no regular run is due; its figures stay readable meanwhile.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.domains.analytics.importer import enqueue_analytics_syncs
from sqlalchemy import text

from tests.api.test_google_analytics_sync import (  # noqa: F401 (fixtures)
    AU,
    HOURS,
    TODAY,
    _connect,
    _finish_chain,
    _link,
    _ranges,
    _rows,
    owner,
    sim,
)
from tests.ga4_sim import Visit

DAY = date(2026, 10, 4)


def _daily(admin_engine, breakdown):
    return _rows(
        admin_engine,
        "SELECT d.* FROM analytics_daily d JOIN analytics_properties p ON p.id = d.property_id "
        "WHERE d.breakdown = :b AND p.external_property_id = :e ORDER BY d.day, d.dimension_key",
        b=breakdown,
        e=AU,
    )


def _property(admin_engine):
    (row,) = _rows(
        admin_engine,
        "SELECT id, funnel_reread_at, first_import_completed_at FROM analytics_properties "
        "WHERE external_property_id = :e",
        e=AU,
    )
    return row


def test_every_view_carries_the_funnel_figures(owner, admin_engine):
    (total,) = [r for r in _daily(admin_engine, "total") if r["day"] == DAY]
    assert (total["item_view_events"], total["add_to_carts"], total["checkouts"]) == (4, 2, 1)
    (channel,) = [r for r in _daily(admin_engine, "channel") if r["day"] == DAY]
    assert channel["add_to_carts"] == 2
    (source,) = [r for r in _daily(admin_engine, "source") if r["day"] == DAY]
    assert source["checkouts"] == 1


def test_a_quiet_day_has_real_zeros_for_the_funnel_too(owner, admin_engine):
    quiet = next(r for r in _daily(admin_engine, "total") if r["day"] == date(2026, 10, 5))
    assert (quiet["item_view_events"], quiet["add_to_carts"], quiet["checkouts"]) == (0, 0, 0)


def test_landing_pages_are_kept_as_paths(make_client, sim, admin_engine):
    sim.properties[AU].traffic = [
        Visit(DAY, landing_page="/products/gloves", sessions=7, add_to_carts=3),
        Visit(DAY, landing_page="/products/gloves?utm_source=x&email=a@b.example", sessions=2),
        Visit(DAY, landing_page="/", sessions=4),
    ]
    _link(_connect(make_client, sim))
    pages = {r["landing_page"]: r for r in _daily(admin_engine, "landing_page") if r["day"] == DAY}
    assert set(pages) == {"/", "/products/gloves"}  # the query string is never kept
    gloves = pages["/products/gloves"]
    assert gloves["dimension_key"] == "/products/gloves"
    assert gloves["sessions"] == 7  # one row per path and day: the duplicate is skipped
    assert all("@" not in (r["landing_page"] or "") for r in _daily(admin_engine, "landing_page"))


def test_rare_landing_pages_are_combined_into_other(make_client, sim, runtime, admin_engine):
    runtime.settings = runtime.settings.model_copy(update={"ANALYTICS_SOURCE_ROWS_PER_DAY": 3})
    sim.properties[AU].traffic = [
        Visit(DAY, landing_page=f"/p/{n}", sessions=50 - n, checkouts=1) for n in range(6)
    ]
    _link(_connect(make_client, sim))
    pages = {r["landing_page"]: r for r in _daily(admin_engine, "landing_page") if r["day"] == DAY}
    assert set(pages) == {"/p/0", "/p/1", "(other)"}
    other = pages["(other)"]
    assert (other["other_row"], other["sessions"], other["checkouts"]) == (
        True,
        48 + 47 + 46 + 45,
        4,
    )
    assert other["total_users"] is None  # never added up


def test_the_first_import_counts_as_read_with_the_funnel(owner, admin_engine):
    prop = _property(admin_engine)
    assert prop["funnel_reread_at"] == prop["first_import_completed_at"]


def _imported_before_phase_7(admin_engine):
    with admin_engine.begin() as db:
        db.execute(text("UPDATE analytics_properties SET funnel_reread_at = NULL"))
        db.execute(
            text(
                "UPDATE analytics_daily SET item_view_events = NULL, add_to_carts = NULL, "
                "checkouts = NULL"
            )
        )
        db.execute(text("DELETE FROM analytics_daily WHERE breakdown = 'landing_page'"))


def test_a_property_imported_before_is_read_once_more_in_monthly_slices(
    owner, sim, runtime, admin_engine, clock
):
    _imported_before_phase_7(admin_engine)
    assert _daily(admin_engine, "total")[0]["add_to_carts"] is None  # unknown, never 0
    before = len(sim.calls(":batchRunReports"))
    assert enqueue_analytics_syncs(runtime) == 1  # nothing else is due: the re-read starts
    state = _finish_chain(runtime, owner, admin_engine, clock)
    spans = _ranges(sim, before)
    assert spans[0][0] == date(2025, 9, 14) and len(spans) == 14  # 13 months, month by month
    assert state["status"] == "active" and state["sync_mode"] is None
    assert _property(admin_engine)["funnel_reread_at"] is not None
    (total,) = [r for r in _daily(admin_engine, "total") if r["day"] == DAY]
    assert total["add_to_carts"] == 2
    assert [r["day"] for r in _daily(admin_engine, "landing_page")] == [DAY, TODAY]
    assert enqueue_analytics_syncs(runtime) == 0  # once only


def test_a_regular_run_goes_before_the_reread(owner, sim, runtime, admin_engine, clock):
    _imported_before_phase_7(admin_engine)
    clock.advance(3 * HOURS)  # the 3-hour run is due
    before = len(sim.calls(":batchRunReports"))
    assert enqueue_analytics_syncs(runtime) == 1
    assert _ranges(sim, before) == [(date(2026, 10, 13), TODAY)]
    assert _property(admin_engine)["funnel_reread_at"] is None  # still due
    assert enqueue_analytics_syncs(runtime) == 1  # now the re-read
    _finish_chain(runtime, owner, admin_engine, clock, step=timedelta(minutes=1))
    assert _property(admin_engine)["funnel_reread_at"] is not None


def test_the_property_page_offers_only_its_three_views(owner):
    prop = owner.get(f"/organizations/{owner.org}/analytics-properties").json()["data"][0]
    response = owner.get(
        f"/organizations/{owner.org}/analytics-properties/{prop['id']}/metrics/daily"
        "?breakdown=landing_page"
    )
    assert response.status_code == 422
