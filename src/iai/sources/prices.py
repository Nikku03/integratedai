"""Daily OHLCV.

Prices are not an event source -- they are the substrate everything else is
measured against -- so this module returns frames rather than
:class:`~iai.core.types.Event` objects.

Two adapters ship here:

``YahooPrices``
    Free, no key, good enough for research. Yahoo's split/dividend adjustment
    is applied retroactively to the whole history, which means a naive backtest
    that reads ``adjclose`` uses *today's* adjustment factors on a bar from
    2019. For a days-to-weeks horizon on liquid names this is a second-order
    error, but it is a real one: this adapter therefore keeps raw OHLC *and*
    the adjustment factor separately, and the backtest trades raw prices while
    the feature layer uses adjusted returns.

``CsvPrices``
    Read from disk. Use this with a paid vendor extract (Polygon, Databento,
    Norgate) when you want survivorship-bias-free history with delisted names
    included -- which you do, because a catalyst strategy is disproportionately
    exposed to names that later delist.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.config import Config
from ..core.http import HttpClient

log = logging.getLogger(__name__)

YAHOO_CHART = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"

PRICE_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume", "adj_factor"]


def _empty_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "ticker": pd.Series(dtype="object"),
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
            "adj_factor": pd.Series(dtype="float64"),
        }
    )


class YahooPrices:
    """Daily bars from Yahoo's public chart endpoint."""

    def __init__(self, cfg: Config, client: HttpClient) -> None:
        self.cfg = cfg
        self.client = client

    def fetch(self, tickers: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        frames = []
        for tkr in tickers:
            df = self._one(tkr, start, end)
            if df is not None and not df.empty:
                frames.append(df)
        if not frames:
            return _empty_prices()
        return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)

    def _one(self, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
        params = {
            "period1": int(pd.Timestamp(start).timestamp()),
            "period2": int(pd.Timestamp(end).timestamp()),
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
        # Yahoo rejects the default python-requests agent from shared egress IPs.
        blob = self.client.get(
            YAHOO_CHART.format(symbol=ticker),
            params=params,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"},
        )
        if not blob:
            return None
        try:
            result = blob["chart"]["result"][0]
            quote = result["indicators"]["quote"][0]
            ts = result["timestamp"]
        except (KeyError, TypeError, IndexError):
            log.warning("no price payload for %s", ticker)
            return None

        df = pd.DataFrame(
            {
                "date": pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York").normalize().tz_localize(None),
                "ticker": ticker.upper(),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume"),
            }
        )
        adj = result.get("indicators", {}).get("adjclose")
        if adj and adj[0].get("adjclose"):
            adjclose = pd.Series(adj[0]["adjclose"], dtype="float64")
            df["adj_factor"] = (adjclose / df["close"]).astype("float64")
        else:
            df["adj_factor"] = 1.0
        df = df.dropna(subset=["close", "open"])
        df["volume"] = df["volume"].astype("float64").fillna(0.0)
        df["adj_factor"] = df["adj_factor"].fillna(1.0)
        return df[PRICE_COLUMNS]


class CsvPrices:
    """Load a vendor extract. Expects the :data:`PRICE_COLUMNS` schema."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def fetch(self, tickers: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        if not self.path.exists():
            log.error("price file %s not found", self.path)
            return _empty_prices()
        df = pd.read_parquet(self.path) if self.path.suffix == ".parquet" else pd.read_csv(self.path)
        df["date"] = pd.to_datetime(df["date"])
        if "adj_factor" not in df.columns:
            df["adj_factor"] = 1.0
        want = {t.upper() for t in tickers}
        df = df[df["ticker"].str.upper().isin(want)]
        mask = (df["date"] >= pd.Timestamp(start).tz_localize(None)) & (
            df["date"] <= pd.Timestamp(end).tz_localize(None)
        )
        return df.loc[mask, PRICE_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)


def add_derived(prices: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Attach adjusted returns, trailing vol, ADV and a tradability flag.

    Returns are computed on the adjusted series so a 2-for-1 split is not a
    -50% day. Everything is shifted so that a row dated ``t`` contains only
    information observable at the close of ``t``.
    """
    if prices.empty:
        out = prices.copy()
        for col in ("adj_close", "ret", "vol", "adv_usd", "tradable", "dollar_vol"):
            out[col] = pd.Series(dtype="float64")
        return out

    df = prices.sort_values(["ticker", "date"]).copy()
    df["adj_close"] = df["close"] * df["adj_factor"]
    g = df.groupby("ticker", observed=True, sort=False)
    df["ret"] = g["adj_close"].pct_change()
    df["vol"] = (
        g["ret"].transform(lambda s: s.rolling(cfg.features.vol_window, min_periods=10).std())
    )
    df["dollar_vol"] = df["close"] * df["volume"]
    df["adv_usd"] = g["dollar_vol"].transform(lambda s: s.rolling(21, min_periods=5).mean())
    df["tradable"] = (
        (df["adv_usd"] >= cfg.features.min_adv_usd)
        & (df["close"] >= cfg.features.min_price)
        & df["vol"].notna()
    )
    return df.reset_index(drop=True)


def forward_path(
    prices: pd.DataFrame, ticker: str, start_date: pd.Timestamp, horizon: int
) -> pd.DataFrame:
    """The next ``horizon`` sessions of bars for ``ticker`` starting at ``start_date``."""
    sub = prices[(prices["ticker"] == ticker) & (prices["date"] >= start_date)]
    return sub.head(horizon).reset_index(drop=True)


def pivot_close(prices: pd.DataFrame) -> pd.DataFrame:
    """date x ticker matrix of adjusted closes, for correlation work."""
    if prices.empty:
        return pd.DataFrame()
    col = "adj_close" if "adj_close" in prices.columns else "close"
    return prices.pivot_table(index="date", columns="ticker", values=col, aggfunc="last").astype(
        "float64"
    )


def realized_corr(prices: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    """Trailing return correlation matrix, used by the risk layer."""
    px = pivot_close(prices)
    if px.empty:
        return pd.DataFrame()
    rets = np.log(px).diff().tail(window)
    return rets.corr(min_periods=max(10, window // 3)).fillna(0.0)
