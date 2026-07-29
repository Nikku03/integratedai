"""Market-state features.

These are not the alpha. They are the controls: without them the model will
happily learn that "events happen to small volatile names, small volatile
names move a lot" and present that as catalyst edge. Including momentum,
volatility, liquidity and a market-regime column forces the event features to
earn their importance against the obvious alternative explanations.

Every column is built from data available at the close of its own date and is
lagged one session before use, because a feature row for session ``t`` is
consumed to size a trade entered at the open of ``t+1``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.config import Config


def build_market_features(prices: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Panel of (date, ticker) -> market-state features."""
    if prices.empty:
        return pd.DataFrame(columns=["date", "ticker"])

    df = prices.sort_values(["ticker", "date"]).copy()
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"] * df.get("adj_factor", 1.0)
    if "ret" not in df.columns:
        df["ret"] = df.groupby("ticker", observed=True)["adj_close"].pct_change()

    g = df.groupby("ticker", observed=True, sort=False)

    for w in cfg.features.momentum_windows:
        df[f"mom_{w}"] = g["adj_close"].transform(lambda s, w=w: s.pct_change(w))

    df["vol_21"] = g["ret"].transform(lambda s: s.rolling(21, min_periods=10).std()) * np.sqrt(252)
    df["vol_63"] = g["ret"].transform(lambda s: s.rolling(63, min_periods=21).std()) * np.sqrt(252)
    # Vol-of-vol: a name whose volatility is itself unstable behaves differently
    # around a catalyst than one with a steady regime.
    df["vol_ratio"] = df["vol_21"] / df["vol_63"]

    df["dollar_vol"] = df["close"] * df["volume"]
    df["adv_21"] = g["dollar_vol"].transform(lambda s: s.rolling(21, min_periods=5).mean())
    df["log_adv"] = np.log1p(df["adv_21"])
    # Volume surge relative to the name's own baseline: often the first visible
    # trace that someone else already knows.
    df["vol_surge"] = df["dollar_vol"] / df["adv_21"]

    # Distance through the recent range. Trees like this more than raw momentum
    # because it is bounded and comparable across names.
    roll_max = g["adj_close"].transform(lambda s: s.rolling(252, min_periods=60).max())
    roll_min = g["adj_close"].transform(lambda s: s.rolling(252, min_periods=60).min())
    df["pct_of_52w_range"] = (df["adj_close"] - roll_min) / (roll_max - roll_min)
    df["drawdown_52w"] = df["adj_close"] / roll_max - 1.0

    # Gap and intraday range capture how the market absorbed yesterday's news.
    prev_close = g["close"].shift(1)
    df["gap"] = df["open"] / prev_close - 1.0
    df["intraday_range"] = (df["high"] - df["low"]) / df["close"].replace(0, np.nan)

    # Illiquidity: return per dollar traded. High values mean your own order
    # will move the price, which the cost model punishes later.
    df["_illiq"] = df["ret"].abs() / df["dollar_vol"].replace(0, np.nan)
    df["amihud"] = df.groupby("ticker", observed=True)["_illiq"].transform(
        lambda s: s.rolling(21, min_periods=10).mean()
    )

    # Cross-sectional market regime, computed from the panel itself so it needs
    # no extra data source.
    by_date = df.groupby("date", observed=True)["ret"]
    mkt = by_date.mean().rename("mkt_ret")
    regime = pd.DataFrame({"mkt_ret": mkt})
    regime["mkt_vol_21"] = mkt.rolling(21, min_periods=10).std() * np.sqrt(252)
    regime["mkt_mom_63"] = mkt.rolling(63, min_periods=21).sum()
    regime["mkt_breadth"] = by_date.apply(lambda s: float((s > 0).mean()))
    df = df.merge(regime.reset_index(), on="date", how="left")

    # Beta to the equal-weight market, and the residual vol left after it. The
    # groupby is rebuilt here because the merge above replaced `df`.
    df = df.sort_values(["ticker", "date"])
    g2 = df.groupby("ticker", observed=True, sort=False)
    cov = g2.apply(
        lambda x: x["ret"].rolling(63, min_periods=30).cov(x["mkt_ret"]), include_groups=False
    ).reset_index(level=0, drop=True)
    mkt_var = df["mkt_ret"].groupby(df["ticker"], observed=True).transform(
        lambda s: s.rolling(63, min_periods=30).var()
    )
    df["beta_63"] = (cov / mkt_var.replace(0, np.nan)).to_numpy()
    # Residual (idiosyncratic) vol: what is left once the market factor is
    # stripped out. Catalyst edge should live here, not in beta.
    systematic = (df["beta_63"] * df["mkt_vol_21"]).abs()
    df["idio_vol"] = np.sqrt(np.clip(df["vol_21"] ** 2 - systematic**2, 0.0, None))

    cols = [
        "date",
        "ticker",
        *[f"mom_{w}" for w in cfg.features.momentum_windows],
        "vol_21",
        "vol_63",
        "vol_ratio",
        "log_adv",
        "vol_surge",
        "pct_of_52w_range",
        "drawdown_52w",
        "gap",
        "intraday_range",
        "amihud",
        "mkt_vol_21",
        "mkt_mom_63",
        "mkt_breadth",
        "beta_63",
        "idio_vol",
    ]
    return df[cols].reset_index(drop=True)
