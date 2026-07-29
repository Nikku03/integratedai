"""Insider, flow, institutional and news adapters."""

from __future__ import annotations

import numpy as np
import pandas as pd

from iai.core.config import Config
from iai.core.http import HttpClient
from iai.core.types import events_to_frame, validate_events
from iai.core.universe import Universe
from iai.sources.flow import FlowAnomalies, compute_flow
from iai.sources.insiders import (
    ROLE_WEIGHTS,
    TRANSACTION_WEIGHTS,
    InsiderTransactions,
    _transaction_ts,
    classify_role,
    parse_form4,
)
from iai.sources.institutional import STAKE_FORMS, ThirteenF, parse_13f_table
from iai.sources.news import FilingNews

FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport>2024-03-05</periodOfReport>
  <issuer>
    <issuerCik>0000012345</issuerCik>
    <issuerName>Example Corp</issuerName>
    <issuerTradingSymbol>EXMP</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0000099999</rptOwnerCik>
      <rptOwnerName>Smith Jane</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector><isOfficer>1</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner><isOther>0</isOther>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-03-05</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>12.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-03-05</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>50000</value></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


# ---------------------------------------------------------------- Form 4


def test_parse_form4_extracts_open_market_purchase():
    trades = parse_form4(FORM4, pd.Timestamp("2024-03-07 21:00", tz="UTC"), "acc-1")
    assert len(trades) == 1, "should keep only the P transaction"
    t = trades[0]
    assert t.ticker == "EXMP"
    assert t.code == "P"
    assert t.shares == 10000
    assert t.price == 12.5
    assert t.value_usd == 125_000
    assert t.role == "ceo"


def test_parse_form4_drops_grants_and_exercises():
    """Awards and option exercises are compensation mechanics, not signal."""
    codes = {t.code for t in parse_form4(FORM4, pd.Timestamp("2024-03-07", tz="UTC"), "a")}
    assert "A" not in codes and "M" not in codes
    assert set(TRANSACTION_WEIGHTS) == {"P", "S"}


def test_parse_form4_survives_malformed_xml():
    assert parse_form4("<not-xml", pd.Timestamp("2024-01-01", tz="UTC"), "a") == []
    assert parse_form4("", pd.Timestamp("2024-01-01", tz="UTC"), "a") == []


def test_role_classification():
    assert classify_role("Chief Executive Officer", True, False, False) == "ceo"
    assert classify_role("CFO", True, False, False) == "cfo"
    assert classify_role("EVP Sales", True, False, False) == "officer"
    assert classify_role("", False, True, False) == "director"
    assert classify_role("", False, False, True) == "tenpercent"
    assert ROLE_WEIGHTS["ceo"] > ROLE_WEIGHTS["director"] > ROLE_WEIGHTS["tenpercent"]


def test_purchase_outweighs_sale():
    """An insider buying is stronger evidence than an insider selling."""
    assert TRANSACTION_WEIGHTS["P"] > TRANSACTION_WEIGHTS["S"]


def test_same_day_filing_cannot_time_travel():
    """Regression: a Form 4 filed the same morning as the trade.

    The transaction date carries no time, so an earlier version anchored it at
    the 16:00 close -- which lands *after* a filing accepted at 10:42 ET and
    made available_ts < event_ts. validate_events caught it; this pins it.
    """
    txn = pd.Timestamp("2024-03-05")
    accepted = pd.Timestamp("2024-03-05 14:42", tz="UTC")  # 09:42 ET
    assert _transaction_ts(txn, accepted) <= accepted


def test_insider_events_pass_pit_validation():
    trades = parse_form4(FORM4, pd.Timestamp("2024-03-07 21:00", tz="UTC"), "acc-1")
    cfg = Config()
    src = InsiderTransactions(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    ev = src._to_event(trades[0], pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC"))
    assert ev is not None
    validate_events(events_to_frame([ev]))
    assert ev.kind == "insider.buy"


def test_small_insider_purchases_are_filtered():
    trades = parse_form4(FORM4, pd.Timestamp("2024-03-07 21:00", tz="UTC"), "a")
    cfg = Config()
    src = InsiderTransactions(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe(), min_value_usd=1e9)
    assert src._to_event(trades[0], pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")) is None


# ------------------------------------------------------------------- flow


def _price_frame(n=200, seed=0, surge_at=150):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n)
    close = 20 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    volume = np.full(n, 1_000_000.0) * np.exp(rng.normal(0, 0.15, n))
    volume[surge_at] *= 25          # unmistakable volume surge
    close[surge_at:] *= 1.30        # and a breakout
    return pd.DataFrame({
        "date": dates, "ticker": "TEST",
        "open": close * 0.995, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": volume, "adj_factor": 1.0,
    })


def test_flow_detects_a_planted_volume_surge():
    cfg = Config()
    src = FlowAnomalies(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe(), prices=_price_frame())
    events = src.fetch(pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC"))
    kinds = {e.kind for e in events}
    assert "flow.volume_surge" in kinds
    validate_events(events_to_frame(events))


def test_flow_baselines_exclude_the_scored_day():
    """A day must not contribute to the baseline it is measured against.

    If it does, every threshold is partly firing on its own contribution and
    the z-scores are systematically shrunk toward zero.
    """
    cfg = Config()
    src = FlowAnomalies(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe(), prices=_price_frame())
    flow = compute_flow(src.prices, src)
    surge = flow.loc[flow["vol_z"].idxmax()]
    # A 25x volume day scored against a baseline that included itself could not
    # reach this far out.
    assert surge["vol_z"] > 4.0


def test_flow_events_are_dated_to_their_own_close():
    cfg = Config()
    src = FlowAnomalies(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe(), prices=_price_frame())
    for e in src.fetch(pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")):
        assert e.available_ts == e.event_ts
        assert e.available_ts.tz_convert("America/New_York").hour == 16


def test_flow_disabled_without_prices():
    cfg = Config()
    src = FlowAnomalies(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    assert not src.enabled
    assert src.fetch(pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")) == []


# ---------------------------------------------------------- institutional


def test_13f_is_off_by_default_and_says_why():
    """A 45-day-stale source must not silently join a short-horizon model."""
    cfg = Config()
    src = ThirteenF(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    assert not src.enabled
    assert "stale" in src.health()["reason"].lower()


def test_13f_table_parsing_handles_namespaces():
    xml = """<?xml version="1.0"?>
    <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
      <infoTable>
        <nameOfIssuer>EXAMPLE CORP</nameOfIssuer>
        <cusip>123456789</cusip>
        <value>1000</value>
        <shrsOrPrnAmt><sshPrnamt>50000</sshPrnamt></shrsOrPrnAmt>
      </infoTable>
    </informationTable>"""
    rows = parse_13f_table(xml)
    assert len(rows) == 1
    assert rows[0]["cusip"] == "123456789"
    assert rows[0]["shares"] == 50000


def test_activist_stake_outweighs_passive():
    """13D carries intent; 13G does not. That difference is the whole signal."""
    assert STAKE_FORMS["SC 13D"][1] > STAKE_FORMS["SC 13G"][1]


# -------------------------------------------------------------------- news


def test_filing_news_derives_attention_from_press_releases():
    cfg = Config()
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2022-01-03", periods=120, tz="UTC")
    rows = []
    for i, d in enumerate(dates):
        # Baseline of ~1 press release/day, then a burst of 12.
        n = 12 if i == 100 else int(rng.integers(0, 2))
        for j in range(n):
            rows.append({
                "uid": f"u{i}_{j}", "source": "edgar", "kind": "8-K.7.01", "ticker": "TEST",
                "event_ts": d, "available_ts": d, "weight": 0.6, "payload": {},
            })
    base = pd.DataFrame(rows)
    src = FilingNews(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe(), base_events=base)
    events = src.fetch(pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC"))
    assert events, "a 12x press-release burst should register as an attention spike"
    assert all(e.kind == "news.attention_spike" for e in events)
    validate_events(events_to_frame(events))


def test_filing_news_disabled_without_base_events():
    cfg = Config()
    src = FilingNews(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    assert not src.enabled
    assert src.health()["reason"]


# ------------------------------------------------------------- short config


def test_short_horizon_profile_is_internally_consistent():
    cfg = Config.short_horizon()
    # The model must not be trained on a horizon the risk engine will not hold.
    assert cfg.risk.max_holding_days == cfg.labels.max_holding_days
    # Purge must cover the label horizon or folds leak.
    assert cfg.model.purge_days >= cfg.labels.max_holding_days
    # Asymmetric barriers: that is what "big reward" means mechanically.
    assert cfg.labels.upper_mult > cfg.labels.lower_mult
    # Small caps cost more to trade than the default assumes.
    assert cfg.costs.half_spread_bps > Config().costs.half_spread_bps
    assert cfg.features.min_adv_usd < Config().features.min_adv_usd


def test_short_horizon_is_actually_shorter():
    assert Config.short_horizon().labels.max_holding_days < Config().labels.max_holding_days
    assert Config.short_horizon().features.halflives[0] < Config().features.halflives[0]


# ------------------------------------------------------- barrier degeneracy


def test_barriers_stay_positive_after_a_volatility_explosion():
    """Regression: a 250% gap must not produce a stop below zero.

    Found on real data -- MDGL after its NASH readout pushed trailing daily vol
    past 45%, so sigma * sqrt(8) exceeded 1.0 and the lower barrier
    ``entry * (1 - 0.75 * sigma_h)`` went negative. A stop below zero can never
    trade, so every such sample was silently forced to a time-stop label, and
    the resulting relative barrier width of -648 dragged the payoff-bucket
    quantiles for the entire panel.
    """
    from iai.labels import MAX_SIGMA_HORIZON, build_labels

    cfg = Config.short_horizon()
    n = 120
    dates = pd.bdate_range("2023-01-03", periods=n)
    close = np.full(n, 100.0)
    close[60] = 350.0          # +250% in one session
    close[61:] = 340.0
    px = pd.DataFrame({
        "date": dates, "ticker": "GAPPY",
        "open": close, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": 1e6, "adj_factor": 1.0,
    })
    labels = build_labels(px, cfg)
    assert not labels.empty
    assert (labels["barrier_dn"] > 0).all(), "a stop was placed at or below zero"
    assert (labels["barrier_dn"] < labels["barrier_up"]).all()
    # And the relative width stays in a range that cannot corrupt payoff buckets.
    width = (labels["barrier_up"] - labels["barrier_dn"]) / labels["barrier_dn"]
    assert width.max() < 100, f"degenerate barrier width {width.max():.1f}"
    assert MAX_SIGMA_HORIZON > 0


def test_normal_volatility_barriers_are_untouched():
    """The clamp must not bind on ordinary names, or it changes the strategy."""
    from iai.labels import build_labels

    cfg = Config.short_horizon()
    rng = np.random.default_rng(0)
    n = 200
    close = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))  # ~32% annual vol
    px = pd.DataFrame({
        "date": pd.bdate_range("2023-01-03", periods=n), "ticker": "CALM",
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 1e6, "adj_factor": 1.0,
    })
    labels = build_labels(px, cfg)
    entry_implied = labels["barrier_dn"] / (1 - cfg.labels.lower_mult * 0.02 * np.sqrt(8))
    # Stops should sit a few percent below entry, nowhere near the 5% floor.
    ratio = labels["barrier_dn"] / entry_implied
    assert ratio.min() > 0.5, "the degenerate-case floor is binding on a calm name"


# ------------------------------------------------------------------ cascade


def _cascade_prices(n=200, seed=0, event_at=100, gap=0.05, intraday=0.03, tail=0.0):
    """A stock with a planted overnight gap, then a planted same-session drift.

    Built level-by-level so each leg is unambiguous:
      open(event_at)  = close(event_at-1) * (1 + gap)     <- overnight
      close(event_at) = open(event_at)    * (1 + intraday) <- same session
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n)
    close = 50 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    open_ = close.copy()
    # Quiet baseline: open each day at the prior close.
    open_[1:] = close[:-1]
    # Plant the two legs on the event session, then carry the level forward.
    open_[event_at] = close[event_at - 1] * (1 + gap)
    close[event_at] = open_[event_at] * (1 + intraday)
    for i in range(event_at + 1, n):
        open_[i] = close[i - 1]
        close[i] = open_[i] * (1 + tail)
    subject = pd.DataFrame({
        "date": dates, "ticker": "CASC",
        "open": open_, "high": np.maximum(open_, close) * 1.001,
        "low": np.minimum(open_, close) * 0.999, "close": close,
        "volume": 1e6, "adj_factor": 1.0,
    })
    # Abnormal returns are measured against the cross-section, so a single
    # ticker is its own benchmark and every leg comes out exactly zero. Add
    # quiet peers so "abnormal" means something.
    peers = []
    for k in range(6):
        flat = 30 + np.zeros(n)
        peers.append(pd.DataFrame({
            "date": dates, "ticker": f"PEER{k}",
            "open": flat, "high": flat * 1.001, "low": flat * 0.999,
            "close": flat, "volume": 1e6, "adj_factor": 1.0,
        }))
    return pd.concat([subject, *peers], ignore_index=True)


def test_daily_cascade_separates_gap_from_intraday():
    """The planted overnight gap and the planted intraday drift must not mix.

    This is the whole point of the decomposition: the gap is unavailable to
    anyone entering at the open, and conflating the two makes an uncapturable
    move look tradable.
    """
    from iai.cascade import daily_cascade

    px = _cascade_prices(gap=0.05, intraday=0.03, tail=0.0)
    # One after-hours event on the session before the planted move.
    ev_date = px["date"].iloc[99]
    events = pd.DataFrame([{
        "uid": "e1", "source": "edgar", "kind": "TEST", "ticker": "CASC",
        "event_ts": pd.Timestamp(ev_date, tz="America/New_York").tz_convert("UTC"),
        "available_ts": (pd.Timestamp(ev_date) + pd.Timedelta(hours=17))
            .tz_localize("America/New_York").tz_convert("UTC"),
        "weight": 1.0, "payload": {},
    }])
    out = daily_cascade(events, px, min_events=1, tail_days=3)
    assert not out.empty
    row = out.iloc[0]
    # The gap leg should carry the planted overnight move, the intraday leg the
    # planted same-session drift, and neither should absorb the other.
    assert row["gap"] > 0.03, f"gap leg lost the overnight move: {row['gap']:.4f}"
    assert row["day1_intraday"] > 0.015, f"intraday leg lost the drift: {row['day1_intraday']:.4f}"
    assert row["gap"] > row["day1_intraday"]


def test_daily_cascade_ignores_intraday_arrivals():
    """Mid-session arrivals have no clean open boundary and must be excluded."""
    from iai.cascade import daily_cascade

    px = _cascade_prices()
    ev_date = px["date"].iloc[99]
    events = pd.DataFrame([{
        "uid": "e1", "source": "edgar", "kind": "TEST", "ticker": "CASC",
        "event_ts": pd.Timestamp(ev_date, tz="UTC"),
        "available_ts": (pd.Timestamp(ev_date) + pd.Timedelta(hours=12))
            .tz_localize("America/New_York").tz_convert("UTC"),  # 12:00 ET
        "weight": 1.0, "payload": {},
    }])
    assert daily_cascade(events, px, min_events=1).empty


def test_capturable_excludes_the_gap():
    """capturable must never include the overnight leg."""
    from iai.cascade import daily_cascade

    px = _cascade_prices(gap=0.10, intraday=0.01, tail=0.0)
    ev_date = px["date"].iloc[99]
    events = pd.DataFrame([{
        "uid": "e1", "source": "edgar", "kind": "TEST", "ticker": "CASC",
        "event_ts": pd.Timestamp(ev_date, tz="UTC"),
        "available_ts": (pd.Timestamp(ev_date) + pd.Timedelta(hours=17))
            .tz_localize("America/New_York").tz_convert("UTC"),
        "weight": 1.0, "payload": {},
    }])
    row = daily_cascade(events, px, min_events=1, tail_days=3).iloc[0]
    assert row["capturable"] < row["gap"], "capturable absorbed the untradable gap"
    assert abs(row["capturable"] - (row["day1_intraday"] + row["days_2_to_N"])) < 1e-9


def test_lead_lag_identifies_the_leader():
    """B planted consistently after A must report A as the leader."""
    from iai.cascade import lead_lag

    base = pd.Timestamp("2023-01-03 21:00", tz="UTC")
    rows = []
    for i in range(40):
        t = base + pd.Timedelta(days=3 * i)
        rows.append({"ticker": "AAA", "kind": "FIRST", "available_ts": t})
        rows.append({"ticker": "AAA", "kind": "SECOND", "available_ts": t + pd.Timedelta(hours=20)})
    out = lead_lag(pd.DataFrame(rows), pairs=[("FIRST", "SECOND")], window_hours=96)
    assert not out.empty
    assert out.iloc[0]["leader"] == "FIRST"
    assert out.iloc[0]["pct_b_after_a"] > 0.9
    assert out.iloc[0]["median_gap_h"] > 0
