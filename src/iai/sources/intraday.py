"""Hourly bars, including pre- and post-market.

Why this module exists
----------------------
Daily bars cannot answer the question "how much of the move happened in the
first hour". They collapse the entire propagation of a catalyst into one
number, which is precisely the number that hides whether an effect is
capturable.

A concrete example of what daily bars cannot distinguish:

* An 8-K lands at 16:05 ET. By the next open the stock gaps +5%. It closes the
  next day +6%. **Daily bars show +6% and you captured none of it.**
* An 8-K lands at 16:05 ET. The stock gaps +5%, then grinds to +20% over the
  following two sessions as retail reads about it. **Daily bars show +20% and
  you could have captured 15 points of it.**

Those are completely different trades and the daily series reports them almost
identically. Separating them is the whole point of :mod:`iai.cascade`.

Coverage and its limits
-----------------------
Yahoo serves 1-hour bars for roughly the trailing 730 days, and 5/15/30-minute
bars for only 60 days. So the propagation study runs on ~2 years, not the full
backtest window. That is a real constraint, not a choice: minute-level history
of any depth is a paid product (Polygon, Databento, Algoseek), and
:class:`CsvIntraday` is the hook for it.

``includePrePost=true`` matters more than it looks. A large share of small-cap
8-Ks are filed after the close, and the initial repricing happens in the
after-hours and pre-market sessions where the spread is enormous. Excluding
those bars would make the overnight move look like a clean gap you could have
traded at the open, which is exactly the fiction to avoid.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..core.config import Config
from ..core.http import HttpClient

log = logging.getLogger(__name__)

YAHOO_CHART = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

INTRADAY_COLUMNS = ["ts", "ticker", "open", "high", "low", "close", "volume", "session"]

#: Regular US cash session in Eastern time.
RTH_OPEN = (9, 30)
RTH_CLOSE = (16, 0)


def _session_of(ts_et: pd.Timestamp) -> str:
    """Label a bar as pre-market, regular hours, or after-hours."""
    hm = (ts_et.hour, ts_et.minute)
    if hm < RTH_OPEN:
        return "pre"
    if hm >= RTH_CLOSE:
        return "post"
    return "rth"


class IntradayPrices:
    """Hourly OHLCV per ticker, timestamped in UTC and session-labelled."""

    def __init__(self, cfg: Config, client: HttpClient) -> None:
        self.cfg = cfg
        self.client = client

    def fetch(
        self,
        tickers: list[str],
        *,
        interval: str = "1h",
        range_: str = "730d",
        include_prepost: bool = True,
    ) -> pd.DataFrame:
        frames = []
        for tkr in tickers:
            df = self._one(tkr, interval, range_, include_prepost)
            if df is not None and not df.empty:
                frames.append(df)
        if not frames:
            return pd.DataFrame(columns=INTRADAY_COLUMNS)
        out = pd.concat(frames, ignore_index=True)
        log.info(
            "intraday: %d bars, %d tickers, %s .. %s",
            len(out), out["ticker"].nunique(), out["ts"].min(), out["ts"].max(),
        )
        return out.sort_values(["ticker", "ts"]).reset_index(drop=True)

    def _one(self, ticker: str, interval: str, range_: str, prepost: bool) -> pd.DataFrame | None:
        blob = self.client.get(
            YAHOO_CHART.format(symbol=ticker),
            params={
                "interval": interval,
                "range": range_,
                "includePrePost": "true" if prepost else "false",
            },
            headers={"User-Agent": BROWSER_UA},
        )
        if not blob:
            return None
        try:
            result = blob["chart"]["result"][0]
            quote = result["indicators"]["quote"][0]
            ts = result["timestamp"]
        except (KeyError, TypeError, IndexError):
            log.warning("no intraday payload for %s", ticker)
            return None

        idx = pd.to_datetime(ts, unit="s", utc=True)
        df = pd.DataFrame(
            {
                "ts": idx,
                "ticker": ticker.upper(),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume"),
            }
        ).dropna(subset=["close"])
        if df.empty:
            return None
        et = df["ts"].dt.tz_convert("America/New_York")
        df["session"] = [_session_of(t) for t in et]
        df["volume"] = df["volume"].astype("float64").fillna(0.0)
        return df[INTRADAY_COLUMNS]


class CsvIntraday:
    """Load a vendor intraday extract. Schema is :data:`INTRADAY_COLUMNS`.

    Point this at Polygon, Databento, Algoseek or an IB export when you need
    minute bars or more than two years of history.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def fetch(self, tickers: list[str], **_kwargs) -> pd.DataFrame:
        if not self.path.exists():
            log.error("intraday file %s not found", self.path)
            return pd.DataFrame(columns=INTRADAY_COLUMNS)
        df = pd.read_parquet(self.path) if self.path.suffix == ".parquet" else pd.read_csv(self.path)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        if "session" not in df.columns:
            et = df["ts"].dt.tz_convert("America/New_York")
            df["session"] = [_session_of(t) for t in et]
        want = {t.upper() for t in tickers}
        return df[df["ticker"].str.upper().isin(want)].reset_index(drop=True)


def bar_index(intraday: pd.DataFrame) -> pd.DataFrame:
    """Add a per-ticker sequential bar number, for offset arithmetic.

    Offsets must be counted in *bars*, not clock time: an event at 16:05 on a
    Friday is six calendar hours but only one bar away from the next print.
    """
    df = intraday.sort_values(["ticker", "ts"]).copy()
    df["bar_i"] = df.groupby("ticker", observed=True).cumcount()
    return df
