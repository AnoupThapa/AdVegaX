"""Exchange rates: reading the two sources, storing them, converting (task 6-03, Q-6-3, Q-6-12).

* The ECB's euro reference rates and Nepal Rastra Bank's NPR rates are read with GET only from
  two fixed addresses, by column and field names; unreadable rows are skipped and counted.
* The scheduled refresh reads 400 days the first time, then from 10 days before the newest
  stored day; it upserts as published; one source failing never stops the other.
* Conversion: each day's own rate; on weekends and holidays the last published rate, at most 7
  days old; cross rates through the euro; NPR through NRB (or through USD); no rate → None.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.domains.fx import service
from app.domains.fx.service import FxTable, refresh_rates
from app.domains.fx.sources import (
    FxAnswerError,
    FxSourceError,
    PublishedRate,
    _get,
)
from sqlalchemy import text

from tests.fx_sim import FxSim

FRI, SAT, SUN, MON = date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)
ECB_HOST, NRB_HOST = "data-api.ecb.europa.eu", "www.nrb.org.np"


@pytest.fixture
def sim():
    s = FxSim()
    for day, aud, usd, jpy, nzd in (
        (FRI, "1.6512", "1.0856", "162.31", "1.8015"),
        (MON, "1.6600", "1.0900", "163.00", "1.8100"),
    ):
        for cur, rate in (("AUD", aud), ("USD", usd), ("JPY", jpy), ("NZD", nzd)):
            s.ecb[(day, cur)] = Decimal(rate)
    s.nrb[(FRI, "USD")] = ("150.10", "150.70", 1)
    s.nrb[(FRI, "JPY")] = ("9.18", "9.22", 10)
    s.nrb[(FRI, "INR")] = ("159.80", "160.04", 100)
    s.nrb[(SAT, "USD")] = ("150.20", "150.80", 1)
    return s


@pytest.fixture
def fx_runtime(runtime, sim):
    runtime.settings = runtime.settings.model_copy(update={"FX_ENABLED": True})
    runtime.extras["fx_sources"] = sim.sources()
    return runtime


def _rows(admin_engine, sql="SELECT * FROM fx_rates ORDER BY source, base, quote, rate_date"):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql)).mappings().all()]


# ------------------------------------------------------------------ the ECB
def test_the_ecb_is_read_by_column_names(sim):
    ecb, _ = sim.sources()
    found = ecb.fetch(FRI, MON)
    assert sorted((r.rate_date, r.quote, r.rate) for r in found)[:2] == [
        (FRI, "AUD", Decimal("1.6512")),
        (FRI, "JPY", Decimal("162.31")),
    ]
    assert {(r.source, r.base, r.unit) for r in found} == {("ecb", "EUR", 1)}
    (call,) = sim.calls(ECB_HOST)
    assert call.method == "GET" and call.url.path == "/service/data/EXR/D..EUR.SP00.A"
    query = dict(call.url.params)
    assert query == {
        "startPeriod": "2026-10-09",
        "endPeriod": "2026-10-12",
        "format": "csvdata",
        "detail": "dataonly",
    }


def test_ecb_columns_in_another_order_and_bad_rows(sim, monkeypatch):
    def answer(path, query):
        body = (
            "TIME_PERIOD,OBS_VALUE,CURRENCY,CURRENCY_DENOM,KEY\n"
            "2026-10-09,1.6512,AUD,EUR,x\n"
            "2026-10-09,,USD,EUR,x\n"  # no value
            "2026-10-09,1.08,usd,EUR,x\n"  # not a currency code
            "2026-10-09,0,GBP,EUR,x\n"  # not positive
            "2026-10-09,1.1,USD,GBP,x\n"  # not against the euro
            "2026-09-01,1.2,CAD,EUR,x\n"  # outside the period
            "not a day,1.3,CHF,EUR,x\n"
        )
        import httpx

        return httpx.Response(200, text=body)

    monkeypatch.setattr(sim, "_ecb", answer)
    ecb, _ = sim.sources()
    assert [(r.quote, r.rate) for r in ecb.fetch(FRI, MON)] == [("AUD", Decimal("1.6512"))]


def test_a_period_without_ecb_rates_is_empty(sim):
    ecb, _ = sim.sources()
    assert ecb.fetch(SAT, SUN) == []  # the ECB answers 404 "No results found"


@pytest.mark.parametrize(
    ("status", "error"), [(500, FxSourceError), (429, FxSourceError), (403, FxAnswerError)]
)
def test_ecb_errors(sim, status, error):
    sim.fail[ECB_HOST] = status
    ecb, _ = sim.sources()
    with pytest.raises(error):
        ecb.fetch(FRI, MON)


def test_an_ecb_answer_without_its_columns_is_refused(sim, monkeypatch):
    import httpx

    monkeypatch.setattr(sim, "_ecb", lambda path, query: httpx.Response(200, text="a,b\n1,2\n"))
    ecb, _ = sim.sources()
    with pytest.raises(FxAnswerError):
        ecb.fetch(FRI, MON)


# ------------------------------------------------------------------ Nepal Rastra Bank
def test_nrb_middle_rates_with_their_units_page_by_page(sim):
    sim.nrb_per_page = 1
    _, nrb = sim.sources()
    found = {(r.rate_date, r.base): r for r in nrb.fetch(FRI, SAT)}
    assert set(found) == {(FRI, "USD"), (FRI, "JPY"), (FRI, "INR"), (SAT, "USD")}
    assert (found[(FRI, "USD")].rate, found[(FRI, "USD")].unit) == (Decimal("150.40"), 1)
    assert (found[(FRI, "JPY")].rate, found[(FRI, "JPY")].unit) == (Decimal("9.20"), 10)
    assert (found[(FRI, "INR")].rate, found[(FRI, "INR")].unit) == (Decimal("159.92"), 100)
    assert {(r.source, r.quote) for r in found.values()} == {("nrb", "NPR")}
    pages = [dict(c.url.params)["page"] for c in sim.calls(NRB_HOST)]
    assert pages == ["1", "2"]


def test_nrb_rows_that_cannot_be_read_are_skipped(sim):
    sim.nrb[(FRI, "GBP")] = ("", "190.1", 1)  # no buy rate
    sim.nrb[(FRI, "EUR")] = ("170.1", "170.9", 0)  # no unit
    _, nrb = sim.sources()
    assert {r.base for r in nrb.fetch(FRI, FRI)} == {"USD", "JPY", "INR"}


def test_an_nrb_answer_without_its_payload_is_refused(sim, monkeypatch):
    import httpx

    monkeypatch.setattr(sim, "_nrb", lambda query: httpx.Response(200, json={"data": {}}))
    _, nrb = sim.sources()
    with pytest.raises(FxAnswerError):
        nrb.fetch(FRI, FRI)


def test_only_the_two_fixed_addresses_can_be_called(sim):
    with pytest.raises(ValueError, match="refused"):
        _get(sim.http_factory, "evil.example", "/service/data/EXR/D..EUR.SP00.A", {})
    with pytest.raises(ValueError, match="refused"):
        _get(sim.http_factory, ECB_HOST, "/service/data/other", {})


# ------------------------------------------------------------------ the scheduled refresh
def test_nothing_is_read_unless_switched_on(runtime, sim):
    runtime.extras["fx_sources"] = sim.sources()
    assert refresh_rates(runtime) == 0
    assert sim.requests == []


def test_the_first_refresh_reads_400_days_in_slices_then_only_recent_days(
    fx_runtime, sim, admin_engine, clock
):
    written = refresh_rates(fx_runtime)
    assert written == 8 + 4
    starts = [date.fromisoformat(dict(c.url.params)["startPeriod"]) for c in sim.calls(ECB_HOST)]
    today = clock.now().date()
    assert starts[0] == today - timedelta(days=400)
    assert len(starts) == 5  # 92-day slices up to today
    rows = _rows(admin_engine)
    assert {r["source"] for r in rows} == {"ecb", "nrb"}
    sim.requests.clear()
    sim.ecb[(FRI, "AUD")] = Decimal("1.6520")  # the ECB corrects a rate
    refresh_rates(fx_runtime)
    (call,) = sim.calls(ECB_HOST)
    assert dict(call.url.params)["startPeriod"] == (MON - timedelta(days=10)).isoformat()
    (aud,) = [r for r in _rows(admin_engine) if r["quote"] == "AUD" and r["rate_date"] == FRI]
    assert aud["rate"] == Decimal("1.6520000000")  # replaced, not duplicated


def test_one_source_failing_never_stops_the_other(fx_runtime, sim, admin_engine):
    sim.fail[ECB_HOST] = 503
    assert refresh_rates(fx_runtime) == 4
    assert {r["source"] for r in _rows(admin_engine)} == {"nrb"}


def test_the_refresh_runs_on_a_schedule(runtime):
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule["fx-rates"]
    assert schedule["task"] == "advegax.schedule.fx_rates"
    assert schedule["schedule"] == runtime.settings.SCHEDULE_FX_INTERVAL.total_seconds()


# ------------------------------------------------------------------ conversion
@pytest.fixture
def table(sim):
    rows = [*sim.sources()[0].fetch(FRI, MON), *sim.sources()[1].fetch(FRI, SAT)]
    return FxTable(rows, timedelta(days=7))


def test_the_same_currency_needs_no_rate(table):
    assert table.convert(Decimal("12.34"), "AUD", "AUD", date(2020, 1, 1)) == Decimal("12.34")


def test_each_day_uses_its_own_rate(table):
    assert table.convert(Decimal("100"), "EUR", "AUD", FRI) == Decimal("165.12")
    assert table.convert(Decimal("100"), "EUR", "AUD", MON) == Decimal("166.00")
    rate = table.rate("AUD", "EUR", FRI)
    assert rate is not None and rate.sources == ("ecb",)
    assert abs(rate.value * Decimal("1.6512") - 1) < Decimal("1e-30")


def test_cross_rates_go_through_the_euro(table):
    rate = table.rate("AUD", "USD", FRI)
    assert rate is not None
    assert abs(rate.value - Decimal("1.0856") / Decimal("1.6512")) < Decimal("1e-26")
    usd = table.convert(Decimal("1651.20"), "AUD", "USD", FRI)
    assert usd is not None and abs(usd - Decimal("1085.60")) < Decimal("1e-25")


def test_weekends_use_the_last_published_rate_with_its_date(table):
    for day in (SAT, SUN):
        rate = table.rate("EUR", "AUD", day)
        assert rate is not None and (rate.value, rate.rate_date) == (Decimal("1.6512"), FRI)


def test_no_rate_is_not_available_never_guessed(table):
    assert table.rate("EUR", "AUD", FRI - timedelta(days=1)) is None  # before any rate
    assert table.rate("EUR", "AUD", MON + timedelta(days=8)) is None  # older than 7 days
    assert table.rate("EUR", "XYZ", FRI) is None  # a currency nobody publishes
    assert table.convert(Decimal("1"), "AUD", "XYZ", FRI) is None


def test_npr_uses_nepal_rastra_banks_middle_rate_and_unit(table):
    usd = table.rate("USD", "NPR", FRI)
    assert usd is not None and (usd.value, usd.sources) == (Decimal("150.40"), ("nrb",))
    assert table.convert(Decimal("10"), "JPY", "NPR", FRI) == Decimal("9.20")  # per 10 yen
    assert table.convert(Decimal("100"), "INR", "NPR", FRI) == Decimal("159.92")
    back = table.convert(Decimal("150.40"), "NPR", "USD", FRI)
    assert back is not None and abs(back - 1) < Decimal("1e-30")
    assert table.rate("USD", "NPR", SAT).value == Decimal("150.50")  # NRB publishes Saturdays


def test_npr_to_a_currency_nrb_does_not_quote_goes_through_usd(table):
    rate = table.rate("NPR", "NZD", FRI)
    assert rate is not None and rate.sources == ("nrb", "ecb")
    expected = (Decimal("1.8015") / Decimal("1.0856")) / Decimal("150.40")
    assert abs(rate.value - expected) < Decimal("1e-28")  # 34 significant digits
    reverse = table.rate("NZD", "NPR", FRI)
    assert reverse is not None and abs(reverse.value * rate.value - 1) < Decimal("1e-30")


def test_the_table_is_loaded_from_stored_rates(fx_runtime, admin_engine):
    refresh_rates(fx_runtime)
    with fx_runtime.db.transaction(org_id=None) as session:
        loaded = FxTable.load(session, FRI, MON, timedelta(days=7))
    assert loaded.convert(Decimal("100"), "EUR", "AUD", SUN) == Decimal("165.12")


def test_rows_are_stored_exactly_as_published(fx_runtime, admin_engine):
    service.store(fx_runtime, [PublishedRate("nrb", "JPY", "NPR", FRI, Decimal("9.2"), 10)])
    (row,) = _rows(admin_engine)
    assert (row["base"], row["quote"], row["rate"], row["unit"]) == (
        "JPY",
        "NPR",
        Decimal("9.2000000000"),
        10,
    )
