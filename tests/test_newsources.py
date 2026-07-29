"""Insider, flow, institutional and news adapters."""

from __future__ import annotations

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
    rc = cf.main(["--shard", "5", "--n-shards", "3", "--user-agent", "a b@c.com"])
    assert rc == 2


def test_anonymous_user_agent_is_rejected():
    """The SEC blocks anonymous scrapers, and the block hits the whole IP."""
    cf = _load_colab_fetch()
    assert cf.main(["--shard", "0", "--n-shards", "1", "--user-agent", ""]) == 2
    assert cf.main(["--shard", "0", "--n-shards", "1", "--user-agent", "integratedai"]) == 2


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
