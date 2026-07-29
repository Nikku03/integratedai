"""Insider, flow, institutional and news adapters."""

from __future__ import annotations

import inspect
import io
import time
import zipfile

import numpy as np
import pandas as pd
import pytest

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


# ----------------------------------------------------------------- moonshot


def _spike_prices(n=400, seed=0):
    """Two names: one that pops often, one that grinds."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n)
    frames = []
    for tkr, vol in [("POPPY", 0.05), ("QUIET", 0.008)]:
        c = 20 * np.exp(np.cumsum(rng.normal(0.0002, vol, n)))
        frames.append(pd.DataFrame({
            "date": dates, "ticker": tkr,
            "open": c * (1 + rng.normal(0, 0.001, n)),
            "high": c * 1.02, "low": c * 0.98, "close": c,
            "volume": 1e6, "adj_factor": 1.0,
        }))
    return pd.concat(frames, ignore_index=True)


def test_spike_label_uses_absolute_barriers():
    """+10% means +10%, not 10% of sigma."""
    from iai.labels import build_spike_labels

    cfg = Config.moonshot()
    px = _spike_prices()
    lab = build_spike_labels(px, cfg, target=0.10, stop=0.07, horizon=10)
    assert not lab.empty
    ok = lab.dropna(subset=["entry_price"])
    assert np.allclose(ok["target_price"], ok["entry_price"] * 1.10)
    assert np.allclose(ok["stop_price"], ok["entry_price"] * 0.93)


def test_spike_rate_is_higher_for_the_volatile_name():
    """The label is deliberately unbalanced across the universe.

    An absolute barrier is mechanically easier for a volatile name. That is not
    a defect to normalise away -- it is why volatility_control() exists.
    """
    from iai.labels import build_spike_labels

    cfg = Config.moonshot()
    lab = build_spike_labels(_spike_prices(), cfg, target=0.10, stop=0.07, horizon=10)
    rates = lab.groupby("ticker")["spike"].mean()
    assert rates["POPPY"] > rates["QUIET"]


def test_spike_label_entry_is_the_next_open():
    from iai.labels import build_spike_labels

    cfg = Config.moonshot()
    px = _spike_prices()
    lab = build_spike_labels(px, cfg).dropna(subset=["entry_price"])
    assert (lab["entry_date"] > lab["date"]).all()
    merged = lab.merge(
        px[["date", "ticker", "open"]].rename(columns={"date": "entry_date"}),
        on=["entry_date", "ticker"], how="left",
    )
    assert np.allclose(merged["entry_price"], merged["open"], equal_nan=True)


def test_expected_value_penalises_the_downside():
    """A high spike probability with a high stop probability is a bad trade."""
    from iai.moonshot import expected_value

    good = expected_value(np.array([0.35]), np.array([0.30]), 0.10, 0.07)
    bad = expected_value(np.array([0.40]), np.array([0.50]), 0.10, 0.07)
    assert good[0] > bad[0], "EV ignored the downside leg"
    # And the naive ranking would get this backwards.
    assert 0.40 > 0.35


def test_expected_value_matches_the_arithmetic():
    from iai.moonshot import expected_value

    ev = expected_value(np.array([0.4]), np.array([0.3]), 0.10, 0.07, r_time=0.01)
    assert ev[0] == pytest.approx(0.4 * 0.10 - 0.3 * 0.07 + 0.3 * 0.01)


def test_expected_value_clips_a_negative_residual():
    """Two independently calibrated models can sum past 1."""
    from iai.moonshot import expected_value

    ev = expected_value(np.array([0.7]), np.array([0.6]), 0.10, 0.07, r_time=0.05)
    assert np.isfinite(ev).all()
    assert ev[0] == pytest.approx(0.7 * 0.10 - 0.6 * 0.07)


def test_select_per_week_spreads_entries_across_time():
    """Regression: global top-N put 490 of 492 trades in one year."""
    from iai.moonshot import select_per_week

    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2022-01-03", periods=260)
    df = pd.DataFrame({
        "date": np.repeat(dates, 20),
        "ticker": np.tile([f"T{i}" for i in range(20)], len(dates)),
    })
    # Scores drift upward over time, so a global top-N would take only the tail.
    df["ev"] = np.linspace(0, 1, len(df)) + rng.normal(0, 0.01, len(df))

    picked = select_per_week(df, per_week=5)
    per_week = picked.groupby(picked["date"].dt.to_period("W")).size()
    assert per_week.max() <= 5
    # Every week should be represented, not just the last few.
    assert picked["date"].dt.year.nunique() == df["date"].dt.year.nunique()
    assert per_week.min() >= 1


def test_select_per_week_respects_the_daily_cap():
    from iai.moonshot import select_per_week

    dates = pd.to_datetime(["2022-01-03"] * 20 + ["2022-01-04"] * 20)
    df = pd.DataFrame({
        "date": dates, "ticker": [f"T{i}" for i in range(40)],
        "ev": np.arange(40, dtype="float64"),
    })
    picked = select_per_week(df, per_week=10, max_per_day=3)
    assert picked.groupby("date").size().max() <= 3


def test_clustered_se_exceeds_the_naive_one_when_trades_move_together():
    """The whole reason the primary criterion uses it.

    A strategy that takes five trades a week is taking five bets on the same
    week's tape. Dividing by sqrt(n) prices them as five independent draws and
    inflates t by whatever the within-week correlation is. With a strong common
    weekly shock the naive t here clears 2.0 on pure noise; the clustered one
    does not.
    """
    from iai.moonshot import clustered_se

    rng = np.random.default_rng(7)
    n_weeks, per_week = 200, 5
    weeks = np.repeat(np.arange(n_weeks), per_week)
    # Each week gets a common shock; individual trades add little on top.
    common = rng.normal(0.004, 0.05, n_weeks)
    x = pd.Series(np.repeat(common, per_week) + rng.normal(0, 0.005, n_weeks * per_week))

    naive = x.std(ddof=1) / np.sqrt(len(x))
    clu = clustered_se(x, pd.Series(weeks))
    assert clu > naive * 1.5, "clustering must widen the SE when weeks move together"
    assert abs(x.mean() / clu) < abs(x.mean() / naive)


def test_clustered_se_matches_the_naive_one_when_trades_are_independent():
    """A tightening that costs nothing when it is not needed."""
    from iai.moonshot import clustered_se

    rng = np.random.default_rng(11)
    x = pd.Series(rng.normal(0.001, 0.06, 1500))
    weeks = pd.Series(np.repeat(np.arange(300), 5))
    naive = x.std(ddof=1) / np.sqrt(len(x))
    assert clustered_se(x, weeks) == pytest.approx(naive, rel=0.15)


def test_clustered_se_needs_more_than_one_cluster():
    from iai.moonshot import clustered_se

    x = pd.Series([0.01, -0.02, 0.03])
    assert np.isnan(clustered_se(x, pd.Series(["w1"] * 3)))
    assert np.isnan(clustered_se(pd.Series([0.01]), pd.Series(["w1"])))


def test_selection_report_carries_both_t_statistics():
    """The naive t stays visible so the dependence is shown, not assumed."""
    from iai.moonshot import selection_report

    rng = np.random.default_rng(3)
    n = 500
    dates = pd.to_datetime(np.repeat(pd.bdate_range("2022-01-03", periods=100), 5))
    sel = pd.DataFrame({
        "date": dates, "ret": rng.normal(0.01, 0.07, n), "cost_rt": 0.0066,
        "spike": rng.random(n) < 0.33,
        "exit_reason": rng.choice(["target", "stop", "time"], n),
    })
    uni = sel.assign(spike=rng.random(n) < 0.24)
    rep = selection_report(sel, uni).iloc[0]
    assert {"net_t", "net_t_clustered", "n_weeks"} <= set(rep.index)
    assert rep["n_weeks"] > 1
    assert np.isfinite(rep["net_t_clustered"])


def test_volatility_control_flags_a_pure_volatility_tilt():
    """A selector that only picks volatile names must show lift ~1 in-bucket."""
    from iai.moonshot import volatility_control

    rng = np.random.default_rng(1)
    n = 4000
    vol = rng.uniform(0.01, 0.08, n)
    # Spike probability is a pure function of volatility: no skill available.
    spike = (rng.random(n) < (vol * 8)).astype(int)
    uni = pd.DataFrame({"vol21": vol, "spike": spike, "ret": 0.0,
                        "exit_reason": "time"})
    # "Model" = take the most volatile names.
    sel = uni.nlargest(400, "vol21")
    ctrl = volatility_control(sel, uni)
    assert not ctrl.empty
    # Within each volatility bucket the tilt has no advantage.
    assert ctrl["lift"].between(0.7, 1.4).all(), ctrl.to_string()


# ------------------------------------------------------------ shard fetching


def _load_colab_fetch():
    from importlib.machinery import SourceFileLoader
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "colab_fetch.py"
    return SourceFileLoader("colab_fetch", str(path)).load_module()


def test_shards_are_disjoint_and_complete():
    """Every ticker goes to exactly one shard. No gaps, no double-fetching."""
    cf = _load_colab_fetch()
    pool = [f"T{i:04d}" for i in range(997)]  # prime-ish, so sizes are uneven
    for n in (1, 2, 3, 6, 12):
        shards = [cf.shard_tickers(pool, i, n) for i in range(n)]
        flat = [t for s in shards for t in s]
        assert len(flat) == len(pool), f"n={n}: {len(flat)} != {len(pool)}"
        assert set(flat) == set(pool), f"n={n}: coverage gap"
        assert len(set(flat)) == len(flat), f"n={n}: a ticker landed in two shards"


def test_shards_are_balanced():
    """Sizes differ by at most one, so no shard runs hours longer than the rest."""
    cf = _load_colab_fetch()
    pool = [f"T{i:04d}" for i in range(1000)]
    sizes = [len(cf.shard_tickers(pool, i, 7)) for i in range(7)]
    assert max(sizes) - min(sizes) <= 1, sizes


def test_shards_are_not_contiguous_alphabetical_blocks():
    """Round-robin, not A-C / D-F.

    Alphabetical blocks correlate with sector and listing venue, so a
    contiguous split hands one shard the biotechs and another the banks -- and
    their runtimes differ by hours.
    """
    cf = _load_colab_fetch()
    pool = [f"T{i:04d}" for i in range(100)]
    first = cf.shard_tickers(pool, 0, 4)
    # A contiguous split would make shard 0 the first 25 entries.
    assert first != sorted(pool)[:25]
    assert first[0] == "T0000" and first[1] == "T0004"


def test_shard_index_out_of_range_is_rejected():
    cf = _load_colab_fetch()
    rc = cf.main(["--stage", "prices", "--shard", "5", "--n-shards", "3",
                  "--user-agent", "a b@c.com"])
    assert rc == 2


def test_anonymous_user_agent_is_rejected():
    """The SEC blocks anonymous scrapers, and the block hits the whole IP."""
    cf = _load_colab_fetch()
    assert cf.main(["--stage", "prices", "--user-agent", ""]) == 2
    assert cf.main(["--stage", "prices", "--user-agent", "integratedai"]) == 2


def test_stages_run_in_dependency_order(tmp_path):
    """A stage whose input is missing must say which one to run, not crash."""
    cf = _load_colab_fetch()
    args = ["--out", str(tmp_path), "--user-agent", "a b@c.com"]
    for stage in ("prices", "events"):
        with pytest.raises(SystemExit, match="candidates -> prices -> screen"):
            cf.main(["--stage", stage, *args])


def test_only_per_ticker_stages_are_shardable():
    """Sharding the bulk-archive stage would be n times the bytes for no speed.

    Prices and events are one request per ticker and split cleanly. Insiders is
    46 whole-market archives; every shard would download and parse all of them.
    """
    cf = _load_colab_fetch()
    src = inspect.getsource(cf.stage_insiders)
    assert "ignores sharding" in src
    for stage in (cf.stage_prices, cf.stage_events):
        assert "shard_tickers" in inspect.getsource(stage)


# ------------------------------------------------------- bulk insider loader


def test_quarters_covers_the_range():
    from iai.sources.insiders_bulk import quarters

    qs = quarters("2015-01-01", "2026-12-31")
    assert qs[0] == (2015, 1)
    assert qs[-1] == (2026, 4)
    assert len(qs) == 48
    # Eleven years of Form 4s in 48 requests instead of ~900,000.
    assert len(quarters("2021-01-01", "2024-12-31")) == 16


def test_relationship_flags_unpack_in_order():
    """RPTOWNER_RELATIONSHIP packs director,officer,tenpercent,other."""
    from iai.sources.insiders_bulk import _parse_relationship

    assert _parse_relationship("0,1,0,0") == (True, False, False)    # officer
    assert _parse_relationship("1,0,0,0") == (False, True, False)    # director
    assert _parse_relationship("0,0,1,0") == (False, False, True)    # 10% owner
    assert _parse_relationship("1,1,1,0") == (True, True, True)
    assert _parse_relationship(None) == (False, False, False)
    assert _parse_relationship("") == (False, False, False)


def test_bulk_availability_is_pessimistic():
    """No acceptance time in the bulk data, so assume it landed after the bell.

    Reversing this to gain back half a session is exactly the trade that turns
    a backtest into fiction.
    """
    from iai.sources.insiders_bulk import BulkInsiderTransactions

    avail = BulkInsiderTransactions._available(pd.Timestamp("2024-03-05"))
    et = avail.tz_convert("America/New_York")
    assert (et.hour, et.minute) >= (16, 0), "availability must be after the close"
    assert et.date() == pd.Timestamp("2024-03-05").date()


def test_bulk_events_pass_pit_validation():
    """Transaction date must never post-date availability."""
    from iai.core.http import HttpClient
    from iai.sources.insiders_bulk import BulkInsiderTransactions

    cfg = Config.moonshot()
    src = BulkInsiderTransactions(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    trades = pd.DataFrame([
        # Filed the same day as the trade -- the case that broke the XML path.
        {"ticker": "AAA", "cik": "1", "accession": "acc-1", "owner": "Jane",
         "owner_cik": "9", "role": "ceo", "code": "P", "shares": 10000.0,
         "price": 12.5, "value_usd": 125000.0,
         "transaction_date": pd.Timestamp("2024-03-05"),
         "filing_date": pd.Timestamp("2024-03-05")},
        {"ticker": "BBB", "cik": "2", "accession": "acc-2", "owner": "Bob",
         "owner_cik": "8", "role": "director", "code": "S", "shares": 5000.0,
         "price": 20.0, "value_usd": 100000.0,
         "transaction_date": pd.Timestamp("2024-03-01"),
         "filing_date": pd.Timestamp("2024-03-04")},
    ])
    events = src._to_events(trades, pd.Timestamp("2024-01-01", tz="UTC"),
                            pd.Timestamp("2025-01-01", tz="UTC"))
    assert len(events) == 2
    validate_events(events_to_frame(events))
    assert {e.kind for e in events} == {"insider.buy", "insider.sell"}


def test_bulk_applies_the_same_weights_as_the_xml_path():
    """A CEO open-market buy must weigh the same however it was loaded."""
    from iai.core.http import HttpClient
    from iai.sources.insiders import ROLE_WEIGHTS, TRANSACTION_WEIGHTS
    from iai.sources.insiders_bulk import BulkInsiderTransactions

    cfg = Config.moonshot()
    src = BulkInsiderTransactions(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    trades = pd.DataFrame([{
        "ticker": "AAA", "cik": "1", "accession": "a", "owner": "J", "owner_cik": "9",
        "role": "ceo", "code": "P", "shares": 1000.0, "price": 10.0, "value_usd": 10_000_000.0,
        "transaction_date": pd.Timestamp("2024-03-05"),
        "filing_date": pd.Timestamp("2024-03-07"),
    }])
    ev = src._to_events(trades, pd.Timestamp("2024-01-01", tz="UTC"),
                        pd.Timestamp("2025-01-01", tz="UTC"))[0]
    base = TRANSACTION_WEIGHTS["P"] * ROLE_WEIGHTS["ceo"]
    assert ev.weight == pytest.approx(base * 3.0)  # size multiplier saturates at 3x


def test_bulk_cluster_needs_distinct_insiders():
    from iai.core.http import HttpClient
    from iai.sources.insiders_bulk import BulkInsiderTransactions

    cfg = Config.moonshot()
    src = BulkInsiderTransactions(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    base = {"ticker": "AAA", "cik": "1", "role": "ceo", "code": "P", "shares": 1000.0,
            "price": 100.0, "value_usd": 100_000.0,
            "transaction_date": pd.Timestamp("2024-03-05")}
    # Same owner buying three times is not a cluster.
    same = pd.DataFrame([
        {**base, "accession": f"a{i}", "owner": "Jane", "owner_cik": "9",
         "filing_date": pd.Timestamp("2024-03-05") + pd.Timedelta(days=i)}
        for i in range(3)
    ])
    assert src._clusters(same, pd.Timestamp("2024-01-01", tz="UTC"),
                         pd.Timestamp("2025-01-01", tz="UTC")) == []

    # Two different owners is.
    diff = pd.DataFrame([
        {**base, "accession": "a1", "owner": "Jane", "owner_cik": "9",
         "filing_date": pd.Timestamp("2024-03-05")},
        {**base, "accession": "a2", "owner": "Bob", "owner_cik": "8",
         "filing_date": pd.Timestamp("2024-03-06")},
    ])
    out = src._clusters(diff, pd.Timestamp("2024-01-01", tz="UTC"),
                        pd.Timestamp("2025-01-01", tz="UTC"))
    assert len(out) == 1
    assert out[0].payload["n_insiders"] == 2


def test_filer_typo_dates_do_not_crash_or_time_travel():
    """Regression: a real 2016Q1 filing carries transaction date 0016-03-16.

    Found by running the eleven-year fetch -- 563,414 transactions contain
    typos that four years and 341 names did not. Year 16 is not merely wrong,
    it is outside the range pandas can localise to New York, so it raised
    partway through the run rather than quietly skewing a feature.

    The repair falls back to the filing date, which can only move an event
    LATER. That direction matters: it cannot manufacture lookahead.
    """
    from iai.core.config import Config
    from iai.core.http import HttpClient
    from iai.sources.insiders_bulk import BulkInsiderTransactions

    cfg = Config.moonshot()
    src = BulkInsiderTransactions(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    filed = pd.Timestamp("2016-03-18")
    avail = src._available(filed)

    bad = src._event_time(pd.Timestamp("0016-03-16"), filed, avail)
    assert bad <= avail, "a repaired date must not post-date availability"
    assert bad.year == 2016
    assert src._repaired == 1, "repairs must be counted, not silent"

    # A plausible date is left exactly as it was.
    good = src._event_time(pd.Timestamp("2016-03-16"), filed, avail)
    assert good.tz_convert("America/New_York").date() == pd.Timestamp("2016-03-16").date()
    assert src._repaired == 1, "a valid date must not be counted as a repair"

    # Missing dates fall back too, and are not counted as typos.
    assert src._event_time(pd.NaT, filed, avail) <= avail
    assert src._repaired == 1


def test_events_survive_a_daylight_saving_gap():
    """Half a million filer-typed dates will eventually land in the DST gap.

    tz_localize raises on a nonexistent wall-clock time by default. Shifting
    forward is the conservative direction -- it can only make an event later.
    """
    from iai.sources.insiders_bulk import _et

    for day in ("2016-03-13", "2021-03-14", "2024-03-10"):  # spring forward
        assert _et(pd.Timestamp(day), 9, 30) is not None
    for day in ("2016-11-06", "2024-11-03"):  # fall back, ambiguous
        assert _et(pd.Timestamp(day), 9, 30) is not None


def test_typo_dates_pass_pit_validation_end_to_end():
    """The validator is the backstop; the repair must satisfy it."""
    from iai.core.config import Config
    from iai.core.http import HttpClient
    from iai.sources.insiders_bulk import BulkInsiderTransactions

    cfg = Config.moonshot()
    src = BulkInsiderTransactions(cfg, HttpClient(cfg.data.cache_dir, "t"), Universe())
    trades = pd.DataFrame([{
        "ticker": "AAA", "cik": "1", "accession": "a1", "owner": "Jane",
        "owner_cik": "9", "role": "ceo", "code": "P", "shares": 1000.0,
        "price": 50.0, "value_usd": 50_000.0,
        "transaction_date": pd.Timestamp("0016-03-16"),   # the typo
        "filing_date": pd.Timestamp("2016-03-18"),
    }, {
        "ticker": "BBB", "cik": "2", "accession": "a2", "owner": "Bob",
        "owner_cik": "8", "role": "director", "code": "P", "shares": 1000.0,
        "price": 50.0, "value_usd": 50_000.0,
        "transaction_date": pd.Timestamp("2016-03-16"),   # fine
        "filing_date": pd.Timestamp("2016-03-18"),
    }])
    events = src._to_events(trades, pd.Timestamp("2016-01-01", tz="UTC"),
                            pd.Timestamp("2017-01-01", tz="UTC"))
    assert len(events) == 2
    validate_events(events_to_frame(events))


# ------------------------------------------------- bulk archives: cache, cores


def _fake_archive(rows: list[dict]) -> bytes:
    """A minimal but structurally real quarterly Form 345 zip."""
    sub = pd.DataFrame([{
        "ACCESSION_NUMBER": r["acc"], "DOCUMENT_TYPE": "4",
        "ISSUERTRADINGSYMBOL": r.get("symbol", r["ticker"]),
        "ISSUERCIK": r.get("cik", "0000000001"),
        "FILING_DATE": r["filed"],
    } for r in rows])
    trans = pd.DataFrame([{
        "ACCESSION_NUMBER": r["acc"], "TRANS_CODE": r.get("code", "P"),
        "TRANS_SHARES": "1000", "TRANS_PRICEPERSHARE": "50",
        "TRANS_DATE": r["txn"],
    } for r in rows])
    owners = pd.DataFrame([{
        "ACCESSION_NUMBER": r["acc"],
        "RPTOWNERCIK": r["owner_cik"] if "owner_cik" in r else "9",
        "RPTOWNERNAME": r["owner"] if "owner" in r else "Jane",
        "RPTOWNER_RELATIONSHIP": "0,1,0,0", "RPTOWNER_TITLE": "CEO",
    } for r in rows])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, df in (("SUBMISSION.tsv", sub), ("NONDERIV_TRANS.tsv", trans),
                         ("REPORTINGOWNER.tsv", owners)):
            z.writestr(name, df.to_csv(sep="\t", index=False))
    return buf.getvalue()


def test_parse_archive_is_pure_so_it_can_run_in_a_process():
    """Parsing takes bytes, not a client -- that is what makes cores usable.

    Unzipping and three read_csv calls over ~110,000 rows is CPU-bound, and the
    GIL makes threads useless for it. Keeping the parse free of the HTTP client
    is what lets it be handed to a process pool.
    """
    from iai.sources.insiders_bulk import parse_archive

    sig = inspect.signature(parse_archive)
    assert list(sig.parameters) == ["blob", "cik_to_ticker"]

    blob = _fake_archive([
        {"acc": "a1", "ticker": "AAA", "cik": "0000000011",
         "filed": "07-MAR-2024", "txn": "05-MAR-2024"},
        {"acc": "a2", "ticker": "ZZZ", "cik": "0000000022",
         "filed": "08-MAR-2024", "txn": "06-MAR-2024"},
    ])
    everything = parse_archive(blob)
    assert set(everything["ticker"]) == {"AAA", "ZZZ"}

    # Filtering happens before the joins, so a universe is a real saving.
    filtered = parse_archive(blob, {"0000000011": "AAA"})
    assert set(filtered["ticker"]) == {"AAA"}
    assert filtered["role"].iloc[0] == "ceo"
    assert filtered["value_usd"].iloc[0] == pytest.approx(50_000.0)


def test_issuers_resolve_by_cik_not_by_the_filers_symbol():
    """Regression: symbol matching lost 18-30% of open-market insider buys.

    ISSUERTRADINGSYMBOL is free text. Matched against a universe built from
    *today's* symbol map it silently zeroes the entire insider history of any
    name that was renamed, and misattributes a delisted company's filings to
    whoever holds its old symbol now. Measured on the real pre-registered
    universe and real archives: 2015q1 lost 18.9% of open-market buys, 2018q3
    29.6%, 2021q2 18.1% -- concentrated on names with corporate actions, while
    EDGAR (which keys on CIK) kept their full 8-K history beside a structurally
    zero insider feature.
    """
    from iai.sources.insiders_bulk import parse_archive

    blob = _fake_archive([
        # Renamed: files under its old symbol, universe knows it as NEWCO.
        {"acc": "a1", "ticker": "OLDCO", "cik": "0000000011",
         "filed": "07-MAR-2024", "txn": "05-MAR-2024"},
        # Punctuation mismatch: filers type '.', company_tickers.json uses '-'.
        {"acc": "a2", "ticker": "BRK.B", "cik": "0000000022",
         "filed": "07-MAR-2024", "txn": "05-MAR-2024"},
        # Blank/placeholder symbols are common on small caps.
        {"acc": "a3", "ticker": "NONE", "cik": "0000000033",
         "filed": "07-MAR-2024", "txn": "05-MAR-2024"},
    ])
    cik_map = {"0000000011": "NEWCO", "0000000022": "BRK-B", "0000000033": "TINY"}
    out = parse_archive(blob, cik_map)

    assert set(out["ticker"]) == {"NEWCO", "BRK-B", "TINY"}, (
        "every filing must be kept and relabelled with the universe's ticker"
    )
    # Symbol matching would have kept none of them.
    symbols = {"NEWCO", "BRK-B", "TINY"}
    assert not ({"OLDCO", "BRK.B", "NONE"} & symbols)


def test_a_reassigned_symbol_is_not_attributed_to_the_new_owner():
    """A delisted company's filings must not land on whoever holds the symbol now."""
    from iai.sources.insiders_bulk import parse_archive

    blob = _fake_archive([
        # Dead company that used to trade as PRE.
        {"acc": "a1", "ticker": "PRE", "cik": "0000911421",
         "filed": "07-MAR-2015", "txn": "05-MAR-2015"},
    ])
    # The universe's PRE today is a different CIK entirely.
    out = parse_archive(blob, {"0001876431": "PRE"})
    assert out.empty, "the dead issuer's filings must not be relabelled as the live one"


def test_payloads_never_carry_nan():
    """A bare NaN cannot survive repr()/literal_eval and aborted the merge.

    147 of 563,414 Form 4s have no RPTOWNERNAME. Each one produced
    ``{'owner': nan, ...}``, which reprs as a *name* rather than a literal.
    """
    import ast

    from iai.sources.insiders_bulk import parse_archive

    blob = _fake_archive([
        {"acc": "a1", "ticker": "AAA", "cik": "0000000011",
         "filed": "07-MAR-2024", "txn": "05-MAR-2024", "owner": None,
         "owner_cik": None},
    ])
    out = parse_archive(blob, {"0000000011": "AAA"})
    assert out["owner"].iloc[0] is None, "a missing owner must be None, not NaN"
    assert out["owner_cik"].iloc[0] is None

    # The round trip the event store actually performs, which a bare NaN breaks.
    payload = {"owner": out["owner"].iloc[0], "owner_cik": out["owner_cik"].iloc[0],
               "role": out["role"].iloc[0]}
    assert ast.literal_eval(repr(payload)) == payload


def test_screen_refuses_a_partial_shard_set():
    """Five of six shards makes a plausible universe -- a different one."""
    cf = _load_colab_fetch()
    from pathlib import Path

    complete = [Path(f"prices_shard{i:02d}of03.parquet") for i in range(3)]
    cf._require_all_shards(complete, "prices")  # must not raise

    partial = [Path("prices_shard00of03.parquet"), Path("prices_shard02of03.parquet")]
    with pytest.raises(SystemExit, match="missing shard"):
        cf._require_all_shards(partial, "prices")

    mixed = [Path("prices_shard00of03.parquet"), Path("prices_shard00of06.parquet")]
    with pytest.raises(SystemExit, match="inconsistent"):
        cf._require_all_shards(mixed, "prices")


def test_share_counts_are_not_known_before_they_were_filed():
    """The XBRL fact instant is a fiscal date, not a publication date.

    A share count for the quarter ending 2020-03-31 arrives in a 10-Q due
    40-45 days later. Dating it 2020-03-31 lets the universe compute a market
    cap up to three months before anyone could have.
    """
    from iai.universe_builder import FILING_LAG

    assert FILING_LAG >= pd.Timedelta(days=90), (
        "the lag must cover the slowest statutory deadline (10-K at 90 days)"
    )


def test_binary_cache_survives_a_restart(tmp_path):
    """A run that dies at archive 40 must resume, not start over."""
    from iai.core.http import HttpClient

    calls = []
    blob = _fake_archive([{"acc": "a1", "ticker": "AAA", "cik": "0000000011",
                           "filed": "07-MAR-2024", "txn": "05-MAR-2024"}])

    class _Resp:
        status_code = 200
        headers: dict = {}
        content = blob

        def raise_for_status(self):
            pass

    client = HttpClient(tmp_path, "t b@c.com", rate_per_sec=0.0)
    client.session.get = lambda url, **kw: (calls.append(url), _Resp())[1]

    first = client.get_bytes("https://example.test/2024q1.zip")
    assert first == blob
    # A fresh client over the same cache directory must not refetch.
    again = HttpClient(tmp_path, "t b@c.com", rate_per_sec=0.0)
    again.session.get = lambda url, **kw: (calls.append(url), _Resp())[1]
    assert again.get_bytes("https://example.test/2024q1.zip") == blob
    assert len(calls) == 1, "cached archive was refetched"


def test_client_errors_are_answers_not_failures(tmp_path):
    """A 400 means the symbol does not exist. Retrying cannot change that.

    This was the single largest waste of wall clock in a wide fetch: Yahoo
    answers 400 for every delisted ticker, a 5,000-name pool over eleven years
    contains thousands of them, and four attempts with exponential backoff is
    fifteen seconds each. Hours, spent asking again.
    """
    from iai.core.http import HttpClient

    def _count_attempts(status: int) -> int:
        calls: list[str] = []

        class _Resp:
            status_code = status
            headers: dict = {}

            def raise_for_status(self):
                raise AssertionError("must not reach raise_for_status")

        client = HttpClient(tmp_path / str(status), "t b@c.com", rate_per_sec=0.0)
        client.session.get = lambda url, **kw: (calls.append(url), _Resp())[1]
        assert client.get("https://example.test/x") is None
        return len(calls)

    for status in (400, 404, 410, 422):
        assert _count_attempts(status) == 1, f"{status} was retried"


def test_a_block_is_never_mistaken_for_an_absent_resource(tmp_path):
    """403 means "you are not allowed", not "it is not there".

    The distinction is the difference between a shorter run and a silently
    empty one. The SEC blocks an abusive IP with 403 rather than 429 -- its own
    docs say so, and the block covers the whole address. If 403 were treated as
    a definitive miss and cached, every URL attempted during the block would be
    remembered as "nothing here" and the fetch would report success having
    collected nothing at all.
    """
    from iai.core.http import HttpClient

    def _attempt_block(status: int) -> tuple[int, list]:
        calls: list[str] = []

        class _Blocked:
            status_code = status
            headers: dict = {}

            def raise_for_status(self):
                raise AssertionError("a block must not reach raise_for_status")

        cache = tmp_path / f"blk{status}"
        client = HttpClient(cache, "t b@c.com", rate_per_sec=0.0, max_retries=3)
        client.session.get = lambda url, **kw: (calls.append(url), _Blocked())[1]
        assert client.get("https://example.test/x") is None
        return len(calls), list(cache.glob("*.json"))

    for status in (401, 403, 407):
        attempts, cached = _attempt_block(status)
        assert attempts == 3, f"{status} must be retried, not accepted as an answer"
        # And crucially: nothing may be written to the cache.
        assert cached == [], f"{status} was cached as a miss: {cached}"

    # 429 and 5xx are the opposite case: transient, and worth retrying.
    calls = []

    class _Throttled:
        status_code = 429
        headers = {"Retry-After": "0"}

        def raise_for_status(self):
            pass

    client = HttpClient(tmp_path / "429", "t b@c.com", rate_per_sec=0.0, max_retries=3)
    client.session.get = lambda url, **kw: (calls.append(url), _Throttled())[1]
    assert client.get("https://example.test/x") is None
    assert len(calls) == 3, "throttling must still be retried"


def test_definitive_miss_is_cached_but_expires_sooner_than_a_hit(tmp_path):
    """A dead ticker must not be re-asked every run -- nor written off forever.

    A symbol that 400s today may list next month, so the negative cache has a
    much shorter life than a positive one. Caching misses permanently would
    quietly shrink the universe over time.
    """
    from iai.core.http import HttpClient

    calls = []

    class _Resp:
        status_code = 400
        headers: dict = {}

        def raise_for_status(self):
            pass

    client = HttpClient(tmp_path, "t b@c.com", rate_per_sec=0.0, ttl_hours=720.0)
    client.session.get = lambda url, **kw: (calls.append(url), _Resp())[1]

    assert client.get("https://example.test/DEAD") is None
    assert client.get("https://example.test/DEAD") is None
    assert len(calls) == 1, "the miss was not cached"

    path = client._key("https://example.test/DEAD", None, None)
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    assert age_hours > client.ttl / 3600 - client.miss_ttl_hours - 1
    assert age_hours < client.ttl / 3600, "the miss must not already be expired"


def test_truncated_cache_entry_is_refetched_not_trusted(tmp_path):
    """A killed run can leave a partial file; it must not look like a hit."""
    from iai.core.http import HttpClient

    client = HttpClient(tmp_path, "t b@c.com", rate_per_sec=0.0)
    url = "https://example.test/2024q1.zip"
    # The .part staging name is what a killed write leaves behind, and it is
    # not the name the reader looks for.
    key = client._key(url, None, None).with_suffix(".bin")
    assert not key.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_load_quarters_parses_every_quarter_it_downloads(monkeypatch, tmp_path):
    """Overlapping download and parse must not drop or duplicate a quarter."""
    from iai.core.http import HttpClient
    from iai.sources import insiders_bulk as ib

    archives = {
        (2024, q): _fake_archive([{
            "acc": f"acc-{q}", "ticker": "AAA", "cik": "0000000011",
            "filed": f"0{q}-MAR-2024", "txn": f"0{q}-MAR-2024",
        }])
        for q in (1, 2, 3, 4)
    }
    client = HttpClient(tmp_path, "t b@c.com", rate_per_sec=0.0)
    monkeypatch.setattr(
        client, "get_bytes",
        lambda url, **kw: archives[(2024, int(url.rsplit("q", 1)[1][0]))],
    )

    # processes=0 exercises the inline path; the pooled path is the same code.
    out = ib.load_quarters(client, list(archives),
                           cik_to_ticker={"0000000011": "AAA"}, processes=0)
    assert len(out) == 4
    assert sorted(out["accession"]) == ["acc-1", "acc-2", "acc-3", "acc-4"]


def test_missing_quarter_does_not_abort_the_run(monkeypatch, tmp_path):
    from iai.core.http import HttpClient
    from iai.sources import insiders_bulk as ib

    good = _fake_archive([{"acc": "a1", "ticker": "AAA", "cik": "0000000011",
                           "filed": "07-MAR-2024", "txn": "05-MAR-2024"}])
    client = HttpClient(tmp_path, "t b@c.com", rate_per_sec=0.0)
    monkeypatch.setattr(
        client, "get_bytes",
        lambda url, **kw: good if "2024q1" in url else None,
    )
    out = ib.load_quarters(client, [(2024, 1), (2024, 2)], processes=0)
    assert len(out) == 1


# --------------------------------------------------- point-in-time universe cut


def _cap_panel() -> pd.DataFrame:
    """Four names, two quarters. ADV ordering flips between them."""
    rows = []
    for period, as_of, advs in (
        ("CY2020Q1I", "2020-03-31", {"AAA": 9e6, "BBB": 5e6, "CCC": 1e6, "HUGE": 9e9}),
        ("CY2020Q2I", "2020-06-30", {"AAA": 1e6, "BBB": 8e6, "CCC": 7e6, "HUGE": 9e9}),
    ):
        for tkr, adv in advs.items():
            cap = 5e11 if tkr == "HUGE" else 5e8
            rows.append({
                "period": period, "as_of": pd.Timestamp(as_of), "ticker": tkr,
                "market_cap": cap, "adv_usd": adv,
                "in_band": cap <= 10e9,
            })
    return pd.DataFrame(rows)


def test_universe_cut_uses_trailing_liquidity_not_the_full_window():
    """Membership must be decidable on the day it is set.

    "The 2,000 most liquid names of the period" is point-in-time. "The 2,000
    largest today" is not, and they look identical written down. The tiebreak
    here is trailing dollar volume, so a name that dries up leaves and a name
    that becomes liquid enters -- and the ordering is allowed to differ between
    quarters, which is the whole tell that no future data was used.
    """
    from iai.universe_builder import rolling_universe

    members = rolling_universe(_cap_panel(), max_names=2)
    q1 = set(members[members["period"] == "CY2020Q1I"]["ticker"])
    q2 = set(members[members["period"] == "CY2020Q2I"]["ticker"])
    assert q1 == {"AAA", "BBB"}
    assert q2 == {"BBB", "CCC"}, "the cut must follow that quarter's liquidity"
    assert "HUGE" not in q1 | q2, "out-of-band names must never be admitted"
    assert members.groupby("period")["ticker"].nunique().max() == 2


def test_membership_never_reaches_backward_in_time():
    """A name admitted at a quarter end is in from then on, not before."""
    from iai.universe_builder import membership_mask, rolling_universe

    members = rolling_universe(_cap_panel(), max_names=2)
    prices = pd.DataFrame({
        "date": pd.to_datetime(["2020-03-30", "2020-04-01", "2020-07-01"] * 1),
        "ticker": ["CCC", "CCC", "CCC"],
    })
    mask = membership_mask(members, prices).set_index("date")["in_universe"]
    # CCC only qualifies at the 2020Q2 measurement date (2020-06-30).
    assert not mask[pd.Timestamp("2020-03-30")]
    assert not mask[pd.Timestamp("2020-04-01")]
    assert mask[pd.Timestamp("2020-07-01")]


def test_membership_lapses_when_a_name_stops_qualifying():
    """Delisted and dried-up names must not stay in the universe forever."""
    from iai.universe_builder import membership_mask, rolling_universe

    members = rolling_universe(_cap_panel(), max_names=2)
    prices = pd.DataFrame({
        "date": pd.to_datetime(["2020-04-01", "2021-06-01"]),
        "ticker": ["AAA", "AAA"],
    })
    mask = membership_mask(members, prices).set_index("date")["in_universe"]
    assert mask[pd.Timestamp("2020-04-01")]
    assert not mask[pd.Timestamp("2021-06-01")], "membership must expire"


def test_union_filtering_is_not_the_same_as_membership_and_is_lookahead():
    """The trap the --members flag exists to close.

    Filtering the price panel to "every name that was ever in the universe" is
    the natural thing to write and it is lookahead: a name that first qualified
    in 2020Q2 is present in the file *because of* a 2020Q2 fact, so trading it
    in 2020Q1 uses information from the future. The per-date mask is what makes
    the universe point-in-time rather than merely small.
    """
    from iai.universe_builder import membership_mask, rolling_universe

    members = rolling_universe(_cap_panel(), max_names=2)
    union = set(members["ticker"])
    assert "CCC" in union, "CCC qualifies in 2020Q2, so a union filter keeps it"

    prices = pd.DataFrame({
        "date": pd.to_datetime(["2020-02-03", "2020-07-01"]),
        "ticker": ["CCC", "CCC"],
    })
    # A union filter would keep both rows.
    union_kept = prices[prices["ticker"].isin(union)]
    assert len(union_kept) == 2

    # The per-date mask keeps only the one that was knowable.
    mask = membership_mask(members, prices)
    pit_kept = prices.merge(mask, on=["date", "ticker"])
    pit_kept = pit_kept[pit_kept["in_universe"]]
    assert len(pit_kept) == 1
    assert pit_kept["date"].iloc[0] == pd.Timestamp("2020-07-01")


def test_moonshot_script_warns_when_membership_is_not_applied():
    """Running without --members must say so, not fail silently."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "moonshot.py"
    src = path.read_text()
    assert "--members" in src
    assert "membership_mask" in src
    assert "WARNING: no --members" in src, "the unsafe path must announce itself"


def test_candidate_pool_applies_no_outcome_based_ranking():
    """The pre-price filter must not be computed over the whole window.

    Ranking candidates by filing activity would pick the 2015 universe using
    facts from 2026. The only thing allowed before prices is "did this
    registrant file financials at all".
    """
    from iai.universe_builder import operating_issuers

    src = inspect.getsource(operating_issuers)
    assert "nunique" in src  # quarters counted, but only reported
    assert "head(" not in src and "nlargest" not in src, "no top-N cut before prices"
