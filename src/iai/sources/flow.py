"""Volume, price and attention anomalies -- the market's own footprint.

You asked for "volume increase" and "institutions making a move". Those are the
same question asked two ways, and for a days-to-weeks horizon this module is
probably the most valuable source in the package, for a reason worth stating
plainly:

    **Every other source tells you what happened. Volume tells you who is
    acting on it, and it tells you today rather than in two days or forty-five.**

A 13F is 45 days stale. A Form 4 is 2 days stale. Unusual volume is *zero* days
stale, free, complete across every listed name, and impossible to suppress --
an institution accumulating a small-cap position cannot hide the print. It is
also the only signal here that is not an announcement, which matters because
the announcement-driven sources keep turning out to be priced in by the open.

What is detected
----------------
``flow.volume_surge``
    Dollar volume z-scored against the name's own trailing baseline. Not a
    fixed multiple: a stock that normally trades $500k and does $3m is a far
    bigger event than a $200m name doing $600m.
``flow.breakout`` / ``flow.breakdown``
    Close through a trailing high or low, **confirmed by volume**. An unconfirmed
    breakout is noise; the volume is the whole point.
``flow.accumulation`` / ``flow.distribution``
    Multi-day pattern: price drifting one way while volume runs above baseline
    and closes cluster near the high (or low) of each day's range. This is the
    classic institutional-footprint shape -- a fund working an order over days
    rather than a single print.
``flow.churn``
    Heavy volume, small net move. Someone large is transacting with someone
    else large. Frequently precedes a directional resolution.
``flow.gap``
    Overnight gap beyond a volatility-scaled threshold.

Point-in-time handling
----------------------
Every one of these is computed from bar ``t`` alone plus **shifted** trailing
baselines, so it is known at the close of ``t`` and is dated to it.
``available_ts`` is that session's close (16:00 ET), which the calendar layer
then maps to a next-open entry. No baseline includes the day being scored --
that is the whole trick, and getting it wrong makes every threshold fire on
its own contribution to the mean.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..core.types import Event, to_utc
from .base import EventSource

log = logging.getLogger(__name__)

CLOSE_HOUR = 16

#: Floor on the trailing standard deviation used to z-score log quantities.
#:
#: Dividing by a rolling std and dropping the zero cases looks harmless and is
#: not: a name that traded almost identical volume every day for a quarter has a
#: near-zero baseline std, so the day it finally does 20x gets a z of infinity
#: or NaN and is discarded. That is the single highest-signal observation in the
#: series being thrown away for being too extreme. Flooring the denominator
#: keeps it, bounded.
MIN_LOG_STD = 0.10


def _safe_std(std: pd.Series) -> pd.Series:
    """Trailing std with a floor, so a degenerate baseline cannot swallow a spike."""
    return std.fillna(MIN_LOG_STD).clip(lower=MIN_LOG_STD)


class FlowAnomalies(EventSource):
    """Detect volume and price anomalies from daily OHLCV.

    Unlike the other sources this one consumes a price frame rather than an
    API, because the raw material is already local. It is still an
    :class:`EventSource` so it composes with the registry and shares the same
    point-in-time contract.
    """

    name = "flow"
    default_latency = pd.Timedelta(0)

    def __init__(
        self,
        *args,
        prices: pd.DataFrame | None = None,
        baseline: int = 60,
        min_periods: int = 20,
        vol_z: float = 2.0,
        breakout_window: int = 60,
        accumulation_days: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.prices = prices if prices is not None else pd.DataFrame()
        self.baseline = baseline
        self.min_periods = min_periods
        self.vol_z = vol_z
        self.breakout_window = breakout_window
        self.accumulation_days = accumulation_days
        self.enabled = not self.prices.empty

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": "" if self.enabled else "no price frame supplied",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        feats = compute_flow(self.prices, self)
        if feats.empty:
            return []

        events: list[Event] = []
        for row in feats.itertuples(index=False):
            avail = to_utc(
                pd.Timestamp(row.date).tz_localize("America/New_York").replace(hour=CLOSE_HOUR)
            )
            if not (start <= avail < end):
                continue
            events.extend(_row_events(row, avail, self))
        log.info("flow: %d anomaly events", len(events))
        return events


def compute_flow(prices: pd.DataFrame, cfg: FlowAnomalies) -> pd.DataFrame:
    """Per (date, ticker) anomaly measures, all from strictly trailing baselines."""
    if prices.empty:
        return pd.DataFrame()

    df = prices.sort_values(["ticker", "date"]).copy()
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"] * df.get("adj_factor", 1.0)
    df["dollar_vol"] = df["close"] * df["volume"]

    def by_ticker():
        # Rebuilt after each column assignment: a groupby captured before a
        # column exists cannot transform on it.
        return df.groupby("ticker", observed=True, sort=False)

    g = by_ticker()
    df["ret"] = g["adj_close"].pct_change()

    # --- volume, z-scored against a SHIFTED baseline -----------------------
    # Log dollar volume, because raw volume is heavily right-skewed and a raw
    # z-score would fire on every third day for a thin name.
    df["log_dv"] = np.log1p(df["dollar_vol"])
    g = by_ticker()
    mean_dv = g["log_dv"].transform(
        lambda s: s.rolling(cfg.baseline, min_periods=cfg.min_periods).mean().shift(1)
    )
    std_dv = g["log_dv"].transform(
        lambda s: s.rolling(cfg.baseline, min_periods=cfg.min_periods).std().shift(1)
    )
    df["vol_z"] = (df["log_dv"] - mean_dv) / _safe_std(std_dv)

    # --- trailing extremes, again shifted so today is not its own high -----
    df["prior_high"] = g["close"].transform(
        lambda s: s.rolling(cfg.breakout_window, min_periods=cfg.min_periods).max().shift(1)
    )
    df["prior_low"] = g["close"].transform(
        lambda s: s.rolling(cfg.breakout_window, min_periods=cfg.min_periods).min().shift(1)
    )

    # --- volatility-scaled gap --------------------------------------------
    prev_close = g["close"].shift(1)
    df["gap"] = df["open"] / prev_close - 1.0
    daily_sigma = g["ret"].transform(
        lambda s: s.rolling(21, min_periods=10).std().shift(1)
    )
    df["gap_sigma"] = df["gap"] / daily_sigma.replace(0, np.nan)

    # --- where in the day's range did it close? ---------------------------
    # Near the high on heavy volume is buying pressure; near the low is the
    # opposite. This is the cheapest available read on order-flow direction
    # from daily bars.
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_location"] = ((df["close"] - df["low"]) / rng).clip(0, 1)

    # --- multi-day accumulation / distribution ----------------------------
    # Volume above baseline AND closes persistently in the upper part of the
    # range AND net drift, sustained over several sessions.
    df["heavy"] = (df["vol_z"] > 1.0).astype("float64")
    g = by_ticker()
    df["heavy_days"] = g["heavy"].transform(
        lambda s: s.rolling(cfg.accumulation_days, min_periods=cfg.accumulation_days).sum()
    )
    df["mean_cl"] = g["close_location"].transform(
        lambda s: s.rolling(cfg.accumulation_days, min_periods=cfg.accumulation_days).mean()
    )
    df["drift"] = g["adj_close"].transform(lambda s: s.pct_change(cfg.accumulation_days))

    df["sigma"] = daily_sigma
    keep = [
        "date", "ticker", "close", "open", "high", "low", "volume", "dollar_vol",
        "ret", "vol_z", "prior_high", "prior_low", "gap", "gap_sigma",
        "close_location", "heavy_days", "mean_cl", "drift", "sigma",
    ]
    return df[keep].dropna(subset=["vol_z"]).reset_index(drop=True)


def _row_events(row, avail: pd.Timestamp, cfg: FlowAnomalies) -> list[Event]:
    """Turn one (date, ticker) measurement row into zero or more events."""
    out: list[Event] = []
    event_ts = avail  # observed at the close it describes
    base = {"date": str(pd.Timestamp(row.date).date()), "vol_z": float(row.vol_z)}

    def add(kind: str, weight: float, extra: dict) -> None:
        out.append(
            Event(
                source="flow",
                kind=kind,
                ticker=row.ticker,
                event_ts=event_ts,
                available_ts=avail,
                payload={"id": f"{kind}:{row.ticker}:{base['date']}", **base, **extra},
                weight=weight,
            )
        )

    vz = float(row.vol_z)

    if vz >= cfg.vol_z:
        # Weight grows with the surprise but saturates: a 12-sigma volume day
        # is not four times more informative than a 3-sigma one, it usually
        # means an index rebalance or a halt reopen.
        add("flow.volume_surge", min(1.0 + (vz - cfg.vol_z) / 2.0, 3.0),
            {"direction": "up" if row.ret and row.ret > 0 else "down",
             "ret": float(row.ret) if pd.notna(row.ret) else None})

    # Breakouts must be volume-confirmed. An unconfirmed breakout is a tick.
    if pd.notna(row.prior_high) and row.close > row.prior_high and vz >= 1.0:
        add("flow.breakout", 1.5 + min(vz / 3.0, 1.5),
            {"prior_high": float(row.prior_high), "close": float(row.close)})
    if pd.notna(row.prior_low) and row.close < row.prior_low and vz >= 1.0:
        add("flow.breakdown", 1.5 + min(vz / 3.0, 1.5),
            {"prior_low": float(row.prior_low), "close": float(row.close)})

    # Sustained heavy volume with closes near the highs and net upward drift.
    if (
        pd.notna(row.heavy_days) and row.heavy_days >= 3
        and pd.notna(row.mean_cl) and row.mean_cl >= 0.6
        and pd.notna(row.drift) and row.drift > 0
    ):
        add("flow.accumulation", 2.0 + float(row.heavy_days) / 5.0,
            {"heavy_days": float(row.heavy_days), "mean_close_location": float(row.mean_cl),
             "drift": float(row.drift)})
    if (
        pd.notna(row.heavy_days) and row.heavy_days >= 3
        and pd.notna(row.mean_cl) and row.mean_cl <= 0.4
        and pd.notna(row.drift) and row.drift < 0
    ):
        add("flow.distribution", 2.0 + float(row.heavy_days) / 5.0,
            {"heavy_days": float(row.heavy_days), "mean_close_location": float(row.mean_cl),
             "drift": float(row.drift)})

    # Churn: heavy volume, little net movement. Two large parties trading with
    # each other; the resolution usually comes later.
    if vz >= cfg.vol_z and pd.notna(row.ret) and pd.notna(row.sigma) and row.sigma > 0:
        if abs(row.ret) < 0.5 * row.sigma:
            add("flow.churn", 1.5, {"ret": float(row.ret), "sigma": float(row.sigma)})

    if pd.notna(row.gap_sigma) and abs(row.gap_sigma) >= 2.0:
        add("flow.gap", min(1.0 + abs(float(row.gap_sigma)) / 4.0, 3.0),
            {"gap": float(row.gap), "gap_sigma": float(row.gap_sigma),
             "direction": "up" if row.gap > 0 else "down"})

    return out
