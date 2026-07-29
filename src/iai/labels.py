"""Triple-barrier labelling.

Why not just forward returns
----------------------------
A fixed 15-day forward return labels a trade you would never have held for 15
days. If a position is down 2 sigma on day three you are out, and the label
should reflect that. The triple barrier -- upper (take profit), lower (stop),
vertical (time) -- labels the outcome of the trade *as the risk engine would
actually have run it*, so the model is trained on the thing it is being asked
to predict.

Barriers are volatility-scaled
------------------------------
A fixed 5% barrier is a coin flip on a microcap and unreachable on a utility.
Scaling by trailing volatility over the holding horizon keeps the base rate
roughly constant across the universe, which matters because an unbalanced,
regime-dependent label is the fastest way to a model that just predicts
volatility.

What comes out
--------------
``label``
    1 if the upper barrier was touched first, 0 otherwise. This is what the
    classifier learns.
``ret``
    Realised return of the simulated trade, open-to-exit. This is what the
    backtest and the sizing layer use; the classifier's probability is only
    half of an edge estimate, the other half is payoff.
``holding_days`` / ``exit_reason``
    Diagnostics, and the input to the purge width in walk-forward CV: a
    training sample's label depends on prices up to ``exit_date``, so any test
    sample within that window is contaminated.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .core.config import Config

log = logging.getLogger(__name__)

#: Cap on the horizon-scaled volatility used to place barriers.
#:
#: After a 250% single-day move -- a biotech trial readout, a buyout, a short
#: squeeze -- trailing daily vol can exceed 45%, and ``sigma * sqrt(horizon)``
#: then exceeds 1.0. The lower barrier ``entry * (1 - 0.75 * sigma_h)`` goes
#: **negative**: a stop below zero that can never trade, so every such sample is
#: forced to a time-stop label. The upper barrier becomes a 4x target that is
#: equally unreachable.
#:
#: It also corrupts everything downstream: :func:`estimate_payoffs` buckets on
#: relative barrier width, and a width of -648 drags the quantile edges for the
#: whole panel, so 41 bad rows out of 105,000 distort the payoff estimates used
#: to size every trade.
#:
#: 0.60 means the barriers can be at most +/- 60% of entry over the horizon,
#: which is already an extreme bet and comfortably wider than any barrier a
#: sane configuration would want.
MAX_SIGMA_HORIZON = 0.60

#: Hard floor on the lower barrier as a fraction of entry price. A stop is a
#: price you can actually trade at.
MIN_BARRIER_FRACTION = 0.05

LABEL_COLS = [
    "date",
    "ticker",
    "entry_date",
    "exit_date",
    "label",
    "ret",
    "holding_days",
    "exit_reason",
    "barrier_up",
    "barrier_dn",
]


def build_labels(prices: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Triple-barrier outcomes for a hypothetical long entered the next open.

    ``date`` is the signal date (the feature row's date). Entry is the *open*
    of the next session, which is the earliest fill a daily-bar strategy can
    honestly claim. Barriers are checked against subsequent highs and lows.
    """
    if prices.empty:
        return pd.DataFrame(columns=LABEL_COLS)

    df = prices.sort_values(["ticker", "date"]).copy()
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"] * df.get("adj_factor", 1.0)
    if "ret" not in df.columns:
        df["ret"] = df.groupby("ticker", observed=True)["adj_close"].pct_change()

    lc = cfg.labels
    df["sigma_d"] = df.groupby("ticker", observed=True)["ret"].transform(
        lambda s: s.rolling(lc.vol_window, min_periods=10).std()
    )
    # Horizon-scaled sigma. sqrt-time is wrong in the tails but it is the right
    # first-order scaling and it keeps the barriers interpretable. Winsorised
    # so a post-gap volatility estimate cannot push a barrier through zero --
    # see MAX_SIGMA_HORIZON.
    df["sigma_h"] = (df["sigma_d"] * np.sqrt(lc.max_holding_days)).clip(
        upper=MAX_SIGMA_HORIZON
    )

    out = []
    for _ticker, grp in df.groupby("ticker", observed=True, sort=False):
        out.append(_label_one(grp.reset_index(drop=True), lc))
    result = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=LABEL_COLS)
    return result.dropna(subset=["label"]).reset_index(drop=True)


def _label_one(g: pd.DataFrame, lc) -> pd.DataFrame:
    n = len(g)
    horizon = lc.max_holding_days
    lag = lc.entry_lag_days

    dates = g["date"].to_numpy()
    open_ = g["open"].to_numpy(dtype="float64")
    high = g["high"].to_numpy(dtype="float64")
    low = g["low"].to_numpy(dtype="float64")
    close = g["close"].to_numpy(dtype="float64")
    sigma_h = g["sigma_h"].to_numpy(dtype="float64")

    labels = np.full(n, np.nan)
    rets = np.full(n, np.nan)
    hold = np.full(n, np.nan)
    reason = np.array([""] * n, dtype=object)
    up_arr = np.full(n, np.nan)
    dn_arr = np.full(n, np.nan)
    entry_idx = np.full(n, -1, dtype=int)
    exit_idx = np.full(n, -1, dtype=int)

    for i in range(n):
        e = i + lag
        if e >= n or not np.isfinite(sigma_h[i]) or sigma_h[i] <= 0:
            continue
        entry_px = open_[e]
        if not np.isfinite(entry_px) or entry_px <= 0:
            continue

        up = entry_px * (1.0 + lc.upper_mult * sigma_h[i])
        # Floor the stop: a barrier at or below zero is not a price.
        dn = max(
            entry_px * (1.0 - lc.lower_mult * sigma_h[i]),
            entry_px * MIN_BARRIER_FRACTION,
        )
        up_arr[i], dn_arr[i] = up, dn
        entry_idx[i] = e

        last = min(e + horizon, n - 1)
        hit_i, hit_lab, hit_ret, hit_reason = last, 0.0, np.nan, "time"
        for j in range(e, last + 1):
            hi_touch = high[j] >= up
            lo_touch = low[j] <= dn
            if hi_touch and lo_touch:
                # Both barriers inside one bar. Daily data cannot say which
                # came first, so assume the stop -- the pessimistic read. The
                # alternative silently inflates the win rate on exactly the
                # most volatile names, where it matters most.
                hit_i, hit_lab, hit_ret, hit_reason = j, 0.0, dn / entry_px - 1.0, "both"
                break
            if hi_touch:
                hit_i, hit_lab, hit_ret, hit_reason = j, 1.0, up / entry_px - 1.0, "upper"
                break
            if lo_touch:
                hit_i, hit_lab, hit_ret, hit_reason = j, 0.0, dn / entry_px - 1.0, "lower"
                break
        if hit_reason == "time":
            hit_ret = close[last] / entry_px - 1.0
            hit_lab = 0.0

        labels[i] = hit_lab
        rets[i] = hit_ret
        hold[i] = hit_i - e + 1
        reason[i] = hit_reason
        exit_idx[i] = hit_i

    valid = entry_idx >= 0
    return pd.DataFrame(
        {
            "date": dates,
            "ticker": g["ticker"].to_numpy(),
            "entry_date": np.where(valid, dates[np.clip(entry_idx, 0, n - 1)], np.datetime64("NaT")),
            "exit_date": np.where(valid, dates[np.clip(exit_idx, 0, n - 1)], np.datetime64("NaT")),
            "label": labels,
            "ret": rets,
            "holding_days": hold,
            "exit_reason": reason,
            "barrier_up": up_arr,
            "barrier_dn": dn_arr,
        }
    )


def label_summary(labels: pd.DataFrame) -> pd.DataFrame:
    """Base rate, payoff and holding period -- check this before trusting a model."""
    if labels.empty:
        return pd.DataFrame()
    wins = labels[labels["label"] == 1]["ret"]
    losses = labels[labels["label"] == 0]["ret"]
    return pd.DataFrame(
        [
            {
                "n": len(labels),
                "base_rate": float(labels["label"].mean()),
                "mean_ret": float(labels["ret"].mean()),
                "avg_win": float(wins.mean()) if len(wins) else np.nan,
                "avg_loss": float(losses.mean()) if len(losses) else np.nan,
                "payoff_ratio": float(wins.mean() / abs(losses.mean()))
                if len(wins) and len(losses) and losses.mean() != 0
                else np.nan,
                "median_hold": float(labels["holding_days"].median()),
                "pct_time_stop": float((labels["exit_reason"] == "time").mean()),
                "pct_upper": float((labels["exit_reason"] == "upper").mean()),
                "pct_lower": float((labels["exit_reason"] == "lower").mean()),
                "pct_ambiguous": float((labels["exit_reason"] == "both").mean()),
            }
        ]
    )


def sample_weights(labels: pd.DataFrame, cfg: Config) -> pd.Series:
    """Down-weight overlapping samples.

    Consecutive daily signals on the same name share most of their outcome
    window, so treating them as independent observations inflates the effective
    sample size by roughly the holding period and makes every significance test
    a fantasy. Weight each sample by the inverse of how many other samples
    overlap its [entry, exit] window.
    """
    if labels.empty:
        return pd.Series(dtype="float64")

    weights = np.ones(len(labels), dtype="float64")
    df = labels.reset_index(drop=True)
    for _, idx in df.groupby("ticker", observed=True).groups.items():
        sub = df.loc[idx]
        starts = sub["entry_date"].to_numpy()
        ends = sub["exit_date"].to_numpy()
        pos = np.asarray(idx)
        for k in range(len(pos)):
            overlap = int(((starts <= ends[k]) & (ends >= starts[k])).sum())
            weights[pos[k]] = 1.0 / max(overlap, 1)
    return pd.Series(weights, index=labels.index, name="sample_weight")
