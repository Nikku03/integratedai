"""News flow and attention.

The honest state of free historical news
---------------------------------------
You asked for news. Here is what is actually obtainable, because the gap
between "news data exists" and "news data you can backtest on" is wide and
expensive:

``YahooNews``
    Free, no key, returns article titles with publish timestamps. **Live only** --
    the endpoint returns roughly the last ten items per ticker with no
    date-range parameter. Fine for :func:`iai.pipeline.run_signals`, useless
    for a backtest.
``GdeltNews``
    Free, global, 2015-present, genuinely date-rangeable. Rate limited to one
    request per five seconds, and it blocks shared/cloud egress IPs outright --
    it is blocked from the environment this package was developed in. From a
    residential or dedicated IP it works, and it is the best free historical
    option available.
``CsvNews``
    A vendor archive on disk. This is what you buy when the strategy justifies
    it: Benzinga (~$300/mo, has a good historical API), Marketaux, RavenPack
    (institutional pricing), Alpha Vantage news sentiment (cheap, thin
    history). All of them ship a timestamped archive you can point this at.
``FilingNews``
    **The free historical fallback that actually works, and the default.**
    Company-issued press releases are filed with the SEC as 8-K Items 7.01
    (Reg FD) and 8.01 (other events), plus 2.02 for earnings releases. That is
    *company news*, timestamped to the second, complete for every US issuer
    back to 2001, and already being fetched by the EDGAR source.

What is deliberately not here: scraped headlines with no reliable timestamp.
A news feature whose timestamp is "when the scraper ran" cannot be backtested
and will silently encode lookahead.

The signal, in any case, is not the headline
--------------------------------------------
For a days-to-weeks trade the useful construct is **attention**, not sentiment:
an abnormal *count* of articles relative to the name's own baseline. Sentiment
scoring on financial headlines is notoriously weak -- "beats estimates, stock
falls" is a headline that every off-the-shelf classifier gets backwards -- and
the market's own reaction is measured far more reliably by volume, which is
what :mod:`iai.sources.flow` does.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.types import Event, to_utc
from .base import EventSource

log = logging.getLogger(__name__)

YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

#: 8-K items that are, in substance, press releases.
PRESS_RELEASE_ITEMS = {"7.01", "8.01", "2.02"}

#: Default publish-to-actionable delay for a vendor news archive. Push APIs are
#: seconds; nightly file drops are hours. The difference shows up directly in
#: the backtest, so set it to match the feed you actually bought.
DEFAULT_NEWS_LATENCY = pd.Timedelta(minutes=5)

#: Floor on the trailing std used to z-score log article counts.
#:
#: A name with no coverage for two months has a baseline std of exactly zero,
#: so the day it lands twelve stories divides by zero and is dropped. That is
#: the most informative observation in the series, discarded for being too
#: clean. Real news counts are discrete and small, so a floor near the
#: Poisson-ish scale of log1p counts is the right correction.
MIN_LOG_STD = 0.35


def _attention_events(
    counts: pd.DataFrame,
    source_name: str,
    baseline: int = 60,
    min_periods: int = 20,
    z_threshold: float = 2.0,
) -> list[Event]:
    """Turn a (date, ticker, n_articles) frame into attention-spike events.

    Baselines are rolling and **shifted**, so a spike is measured against the
    name's own history excluding the day being scored.
    """
    if counts.empty:
        return []
    df = counts.sort_values(["ticker", "date"]).copy()
    g = df.groupby("ticker", observed=True, sort=False)
    df["log_n"] = np.log1p(df["n"])
    mean = g["log_n"].transform(
        lambda s: s.rolling(baseline, min_periods=min_periods).mean().shift(1)
    )
    std = g["log_n"].transform(
        lambda s: s.rolling(baseline, min_periods=min_periods).std().shift(1)
    )
    df["z"] = (df["log_n"] - mean) / std.fillna(MIN_LOG_STD).clip(lower=MIN_LOG_STD)

    out: list[Event] = []
    for row in df.dropna(subset=["z"]).itertuples(index=False):
        if row.z < z_threshold:
            continue
        avail = to_utc(
            pd.Timestamp(row.date).tz_localize("America/New_York").replace(hour=16)
        )
        out.append(
            Event(
                source=source_name,
                kind="news.attention_spike",
                ticker=row.ticker,
                event_ts=avail,
                available_ts=avail,
                payload={
                    "id": f"news:{row.ticker}:{pd.Timestamp(row.date):%Y%m%d}",
                    "n_articles": int(row.n),
                    "z": float(row.z),
                },
                weight=min(1.0 + (float(row.z) - z_threshold) / 2.0, 3.0),
            )
        )
    return out


class FilingNews(EventSource):
    """Press-release intensity derived from 8-K Items 7.01, 8.01 and 2.02.

    The default historical news source, because it is the only free one that is
    complete, correctly timestamped and backtestable. Consumes an already
    collected event frame from :mod:`iai.sources.edgar` rather than refetching.
    """

    name = "news"
    default_latency = pd.Timedelta(minutes=15)

    def __init__(self, *args, base_events: pd.DataFrame | None = None, z_threshold: float = 2.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.base_events = base_events if base_events is not None else pd.DataFrame()
        self.z_threshold = z_threshold
        self.enabled = not self.base_events.empty

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": "" if self.enabled else "needs an EDGAR event frame to derive press releases from",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        df = self.base_events
        is_pr = df["kind"].map(
            lambda k: k.startswith("8-K.") and k.split("8-K.")[-1] in PRESS_RELEASE_ITEMS
        )
        pr = df[is_pr]
        if pr.empty:
            return []
        counts = (
            pr.assign(date=pr["available_ts"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None))
            .groupby(["date", "ticker"], observed=True)
            .size()
            .rename("n")
            .reset_index()
        )
        events = _attention_events(counts, self.name, z_threshold=self.z_threshold)
        return [e for e in events if start <= e.available_ts < end]


class YahooNews(EventSource):
    """Recent headlines per ticker. Live use only -- no historical range.

    Yahoo's search endpoint returns about ten recent items and offers no date
    filter, so this cannot build history. It is here for the daily signal run,
    where "is there unusual news on this name right now" is a legitimate
    last-mile check before sending an order.
    """

    name = "news_live"
    default_latency = pd.Timedelta(minutes=30)

    def __init__(self, *args, lookback_days: int = 7, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lookback_days = lookback_days

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": "live only: Yahoo search has no date range, so it cannot build history",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        start, end = to_utc(start), to_utc(end)
        out: list[Event] = []
        for ticker in self.universe.tickers:
            blob = self.client.get(
                YAHOO_SEARCH,
                params={"q": ticker, "newsCount": 20, "quotesCount": 0},
                headers={"User-Agent": BROWSER_UA},
            )
            for item in (blob or {}).get("news", []):
                ts = item.get("providerPublishTime")
                if not ts:
                    continue
                published = to_utc(pd.Timestamp(int(ts), unit="s", tz="UTC"))
                # Yahoo's relatedTickers is the only guard against a headline
                # about a different company matching the search string.
                related = {str(t).upper() for t in (item.get("relatedTickers") or [])}
                if related and ticker not in related:
                    continue
                available = published + self.default_latency
                if not (start <= available < end):
                    continue
                out.append(
                    Event(
                        source=self.name,
                        kind="news.article",
                        ticker=ticker,
                        event_ts=published,
                        available_ts=available,
                        payload={
                            "id": item.get("uuid", ""),
                            "title": item.get("title", ""),
                            "publisher": item.get("publisher", ""),
                            "link": item.get("link", ""),
                        },
                        weight=1.0,
                    )
                )
        return out


class GdeltNews(EventSource):
    """Historical article counts from GDELT.

    Works from a residential or dedicated IP. Blocked from shared cloud egress,
    which is why :class:`FilingNews` is the default. One request per ticker per
    window, and GDELT asks for no more than one request every five seconds --
    that rate limit is respected here rather than worked around, which makes a
    500-name universe roughly 40 minutes per pass.
    """

    name = "news"
    default_latency = pd.Timedelta(hours=1)

    def __init__(self, *args, z_threshold: float = 2.0, max_records: int = 250, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.z_threshold = z_threshold
        self.max_records = max_records

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": "GDELT blocks shared cloud egress IPs; verify reachability before relying on it",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        start, end = to_utc(start), to_utc(end)
        rows = []
        for ticker in self.universe.tickers:
            company = self.universe.by_ticker[ticker]["name"]
            blob = self.client.get(
                GDELT_DOC,
                params={
                    "query": f'"{company}"',
                    "mode": "artlist",
                    "maxrecords": self.max_records,
                    "format": "json",
                    "startdatetime": start.strftime("%Y%m%d%H%M%S"),
                    "enddatetime": end.strftime("%Y%m%d%H%M%S"),
                },
            )
            if not isinstance(blob, dict):
                # GDELT returns a plain-text throttle notice rather than JSON.
                log.warning("gdelt: non-JSON response for %s (rate limited or blocked)", ticker)
                continue
            for art in blob.get("articles", []):
                seen = art.get("seendate")
                if not seen:
                    continue
                rows.append(
                    {
                        "date": pd.Timestamp(seen).tz_localize("UTC").tz_convert("America/New_York").normalize().tz_localize(None),
                        "ticker": ticker,
                    }
                )
        if not rows:
            return []
        counts = pd.DataFrame(rows).groupby(["date", "ticker"], observed=True).size().rename("n").reset_index()
        return _attention_events(counts, self.name, z_threshold=self.z_threshold)


class CsvNews(EventSource):
    """A vendor news archive on disk.

    Expected columns: ``published_utc, ticker, headline`` plus optional
    ``sentiment`` and ``source``. This is the interface to point at a Benzinga,
    Marketaux, RavenPack or Alpha Vantage export.

    ``available_ts`` adds :attr:`default_latency` to the publish time. Set it to
    match your actual feed: a push API is seconds, a nightly file drop is
    hours, and the difference shows up directly in the backtest.
    """

    name = "news"

    def __init__(
        self,
        *args,
        path: str | Path | None = None,
        latency: pd.Timedelta | None = None,
        z_threshold: float = 2.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.path = Path(path) if path else None
        self.default_latency = latency if latency is not None else DEFAULT_NEWS_LATENCY
        self.z_threshold = z_threshold
        self.enabled = bool(self.path and self.path.exists())

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": "" if self.enabled else "no vendor news archive; point --news at a CSV export",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        df = pd.read_csv(self.path)
        df["published_utc"] = pd.to_datetime(df["published_utc"], utc=True)
        df["ticker"] = df["ticker"].str.upper()
        known = set(self.universe.tickers)
        if known:
            df = df[df["ticker"].isin(known)]
        if df.empty:
            return []
        df["date"] = (
            (df["published_utc"] + self.default_latency)
            .dt.tz_convert("America/New_York")
            .dt.normalize()
            .dt.tz_localize(None)
        )
        counts = df.groupby(["date", "ticker"], observed=True).size().rename("n").reset_index()
        events = _attention_events(counts, self.name, z_threshold=self.z_threshold)
        return [e for e in events if start <= e.available_ts < end]
