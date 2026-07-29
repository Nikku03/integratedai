"""Source adapters: parsing, timestamp handling and graceful degradation."""

from __future__ import annotations

import pandas as pd

from iai.core.config import Config
from iai.core.types import Event, events_to_frame, validate_events
from iai.core.universe import Universe, normalize_name
from iai.sources.edgar import (
    FORM_WEIGHTS,
    ITEM_WEIGHTS,
    dissemination_ts,
    parse_items,
)
from iai.sources.flights import TailRegistry, convergence_events, detect_convergence
from iai.sources.partners import PartnerGraph, extract_entities
from iai.sources.shipping import TradeExposure

# -------------------------------------------------------------------- EDGAR


def test_parse_8k_item_codes():
    assert parse_items("5.02,7.01,9.01") == ["5.02", "7.01", "9.01"]
    assert parse_items("") == []
    assert parse_items("1.01") == ["1.01"]


def test_item_weights_rank_severity_correctly():
    """A restatement must outrank a routine press release."""
    assert ITEM_WEIGHTS["4.02"] > ITEM_WEIGHTS["7.01"]   # non-reliance vs Reg FD
    assert ITEM_WEIGHTS["1.03"] > ITEM_WEIGHTS["9.01"]   # bankruptcy vs exhibits
    assert ITEM_WEIGHTS["3.01"] > ITEM_WEIGHTS["5.03"]   # delisting vs bylaws
    assert FORM_WEIGHTS["SC TO-T"] > FORM_WEIGHTS["10-K"]


def test_dissemination_adds_lag_during_market_hours():
    accepted = pd.Timestamp("2024-03-05 14:00", tz="America/New_York")
    out = dissemination_ts(accepted)
    assert out > accepted
    assert (out - accepted) < pd.Timedelta(hours=1)


def test_dissemination_defers_after_hours_filings():
    """A filing accepted at 18:00 ET is not public until the next morning."""
    accepted = pd.Timestamp("2024-03-05 18:00", tz="America/New_York")
    out = dissemination_ts(accepted).tz_convert("America/New_York")
    assert out.date() > accepted.date()


def test_dissemination_skips_the_weekend():
    accepted = pd.Timestamp("2024-03-08 19:00", tz="America/New_York")  # Friday night
    out = dissemination_ts(accepted).tz_convert("America/New_York")
    assert out.weekday() < 5, "deferred to a weekend day"


# ----------------------------------------------------------------- universe


def test_name_normalisation_strips_corporate_suffixes():
    assert normalize_name("Apple Inc.") == normalize_name("APPLE INCORPORATED")
    assert normalize_name("Foo & Bar Holdings, LLC") == normalize_name("Foo and Bar")


def test_universe_resolves_by_name_and_cik():
    uni = Universe()
    uni.add(ticker="AAPL", cik="320193", name="Apple Inc.")
    uni.add(ticker="MSFT", cik="789019", name="Microsoft Corporation")
    assert uni.resolve_name("Apple Inc") == "AAPL"
    assert uni.resolve_name("MICROSOFT CORP") == "MSFT"
    assert uni.cik("AAPL") == "0000320193"
    assert uni.ticker_for_cik("0000320193") == "AAPL"


def test_universe_records_unresolved_names():
    uni = Universe()
    uni.add(ticker="AAPL", cik="320193", name="Apple Inc.")
    assert uni.resolve_name("Definitely Not A Real Company Ltd") is None
    assert uni.unresolved


# ------------------------------------------------------------ tail registry


def test_tail_ownership_is_point_in_time():
    """An airframe sold in 2023 was not the buyer's aircraft in 2021."""
    reg = TailRegistry()
    reg.add("abc123", "OLDCO", "Old Holdings LLC", valid_from="2018-01-01", valid_to="2023-06-01")
    reg.add("abc123", "NEWCO", "New Holdings LLC", valid_from="2023-06-01")

    assert reg.owner_at("abc123", pd.Timestamp("2021-05-01", tz="UTC"))[0] == "OLDCO"
    assert reg.owner_at("abc123", pd.Timestamp("2024-05-01", tz="UTC"))[0] == "NEWCO"
    assert reg.owner_at("abc123", pd.Timestamp("2010-01-01", tz="UTC")) is None
    assert reg.owner_at("unknown", pd.Timestamp("2024-01-01", tz="UTC")) is None


def test_tail_registry_csv_roundtrip(tmp_path):
    reg = TailRegistry()
    reg.add("abc123", "AAA", "A Holdings", valid_from="2020-01-01")
    path = tmp_path / "tails.csv"
    reg.to_csv(path)
    back = TailRegistry.from_csv(path)
    assert back.owner_at("abc123", pd.Timestamp("2022-01-01", tz="UTC"))[0] == "AAA"


# -------------------------------------------------------------- convergence


def _flight(ticker, when, airport):
    ts = pd.Timestamp(when, tz="UTC")
    return Event(
        source="flights",
        kind="flight.arrival",
        ticker=ticker,
        event_ts=ts,
        available_ts=ts + pd.Timedelta(hours=2),
        payload={"destination": airport, "id": f"{ticker}{when}"},
    )


def test_convergence_needs_two_different_issuers():
    same = events_to_frame([
        _flight("AAA", "2024-03-05 10:00", "KTEB"),
        _flight("AAA", "2024-03-05 14:00", "KTEB"),
    ])
    assert detect_convergence(same) == []


def test_convergence_detects_a_real_cluster():
    df = events_to_frame([
        _flight("AAA", "2024-03-05 10:00", "KTEB"),
        _flight("BBB", "2024-03-05 13:00", "KTEB"),
        _flight("CCC", "2024-03-20 10:00", "KHPN"),
    ])
    clusters = detect_convergence(df, window_hours=12, min_issuers=2)
    assert len(clusters) == 1
    assert set(clusters[0]["tickers"]) == {"AAA", "BBB"}


def test_convergence_respects_the_time_window():
    df = events_to_frame([
        _flight("AAA", "2024-03-05 10:00", "KTEB"),
        _flight("BBB", "2024-03-09 10:00", "KTEB"),  # four days later
    ])
    assert detect_convergence(df, window_hours=12, min_issuers=2) == []


def test_convergence_events_are_available_only_after_the_last_arrival():
    """The pattern is not observable until every leg in it has landed."""
    df = events_to_frame([
        _flight("AAA", "2024-03-05 10:00", "KTEB"),
        _flight("BBB", "2024-03-05 13:00", "KTEB"),
    ])
    evs = convergence_events(df, window_hours=12, min_issuers=2)
    assert evs
    latest_arrival = df["event_ts"].max()
    for e in evs:
        assert e.available_ts >= latest_arrival
    validate_events(events_to_frame(evs))


# ------------------------------------------------------------ partner graph


def test_entity_extraction_finds_corporate_names():
    html = "<p>entered into a collaboration with <b>Acme Therapeutics Inc.</b> and Globex Corporation</p>"
    names = extract_entities(html)
    assert any("Acme" in n for n in names)
    assert any("Globex" in n for n in names)


def test_partner_graph_is_point_in_time():
    """An edge observed in 2024 must not exist in a 2023 view of the graph."""
    g = PartnerGraph()
    g.add("AAA", "BBB", pd.Timestamp("2024-01-01", tz="UTC"))
    assert g.neighbours("AAA", pd.Timestamp("2023-01-01", tz="UTC")) == {}
    assert "BBB" in g.neighbours("AAA", pd.Timestamp("2024-06-01", tz="UTC"))


def test_partner_edges_decay():
    g = PartnerGraph()
    g.add("AAA", "BBB", pd.Timestamp("2020-01-01", tz="UTC"))
    fresh = g.neighbours("AAA", pd.Timestamp("2020-02-01", tz="UTC"), halflife_days=180)["BBB"]
    stale = g.neighbours("AAA", pd.Timestamp("2024-01-01", tz="UTC"), halflife_days=180)["BBB"]
    assert stale < fresh


def test_partner_graph_ignores_self_edges():
    g = PartnerGraph()
    g.add("AAA", "AAA", pd.Timestamp("2024-01-01", tz="UTC"))
    assert g.neighbours("AAA", pd.Timestamp("2024-06-01", tz="UTC")) == {}


# --------------------------------------------------------------- trade map


def test_trade_exposure_matches_hs_prefixes():
    exp = TradeExposure()
    exp.add("AAA", hs="8703", partner="156", direction="M", sensitivity=-1.0)
    assert ("AAA", -1.0) in exp.tickers_for("870323", "156", "M")
    assert exp.tickers_for("8703", "392", "M") == []
    assert exp.tickers_for("2709", "156", "M") == []


def test_trade_exposure_wildcard_partner():
    exp = TradeExposure()
    exp.add("BBB", hs="27", partner="ALL", direction="M")
    assert exp.tickers_for("2709", "999", "M")


# ------------------------------------------------- graceful degradation


def test_sources_disable_themselves_without_credentials():
    from iai.core.http import HttpClient
    from iai.sources.flights import OpenSkyFlights
    from iai.sources.shipping import AISPortCalls, BillOfLading

    cfg = Config()
    cfg.data.opensky_user = None
    cfg.data.opensky_pass = None
    client = HttpClient(cfg.data.cache_dir, cfg.data.user_agent)
    uni = Universe()

    for src in [
        OpenSkyFlights(cfg, client, uni),
        BillOfLading(cfg, client, uni, path=None),
        AISPortCalls(cfg, client, uni, path=None),
    ]:
        assert not src.enabled
        assert src.health()["reason"], "a disabled source must say why"
        # A disabled source returns nothing rather than raising.
        assert src.fetch(pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-02-01", tz="UTC")) == []


def test_registry_isolates_a_failing_source():
    """One broken source must not take down the collection."""
    from iai.core.http import HttpClient
    from iai.sources.base import EventSource, SourceRegistry

    cfg = Config()
    client = HttpClient(cfg.data.cache_dir, cfg.data.user_agent)
    uni = Universe()

    class Exploding(EventSource):
        name = "exploding"

        def fetch(self, start, end):
            raise RuntimeError("vendor API is down")

    class Working(EventSource):
        name = "working"

        def fetch(self, start, end):
            ts = pd.Timestamp("2024-01-15", tz="UTC")
            return [Event("working", "test.kind", "AAA", ts, ts)]

    reg = SourceRegistry([Exploding(cfg, client, uni), Working(cfg, client, uni)])
    out = reg.collect(pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-02-01", tz="UTC"))
    assert len(out) == 1
    assert out["source"].iloc[0] == "working"


def test_events_deduplicate_on_content():
    ts = pd.Timestamp("2024-01-15", tz="UTC")
    e = Event("edgar", "8-K.1.01", "AAA", ts, ts, payload={"id": "acc-1"})
    dupe = Event("edgar", "8-K.1.01", "AAA", ts, ts, payload={"id": "acc-1"})
    other = Event("edgar", "8-K.1.01", "AAA", ts, ts, payload={"id": "acc-2"})
    assert len(events_to_frame([e, dupe, other])) == 2
