"""Build a small/mid-cap universe with point-in-time market caps.

Why not just take today's small caps
------------------------------------
Selecting a universe by *current* market cap and backtesting it over five years
is one of the most damaging biases available, and it is subtle because it has
two heads pointing in opposite directions:

**Survivorship.** Companies that went to zero are not in today's small-cap
list. Every delisting, every bankruptcy, every reverse-split-into-oblivion has
been quietly removed from your sample. A catalyst strategy is *disproportionately*
exposed to those names.

**Migration.** A company that is small-cap today and was mid-cap in 2019 got
there by falling 60%. Selecting on today's cap therefore preferentially picks
names that declined over the sample. Conversely, screening today's mid-caps
picks names that rose. Either way you have sorted on the future.

This module builds the universe from **SEC XBRL shares outstanding as reported
each quarter**, multiplied by the price on that date. The share count comes
from the ``dei:EntityCommonStockSharesOutstanding`` cover-page tag, which is
filed with each 10-Q and 10-K, so a name's cap in 2021Q2 is computed from what
was actually on file in 2021Q2.

The remaining bias, stated honestly
-----------------------------------
The XBRL frames API returns companies that filed for a given quarter, so a
company that stopped filing after going bankrupt drops out of later quarters --
which is correct. But the *price* series still comes from a provider whose
history for delisted tickers is patchy. Free price sources are survivorship
biased regardless of how you pick the universe. For anything you would fund,
buy a delisting-inclusive price archive; :class:`~iai.sources.prices.CsvPrices`
is the hook.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .core.http import HttpClient
from .core.universe import Universe

log = logging.getLogger(__name__)

FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/{period}.json"

#: Market-cap bands in USD. "Small and mid cap" as used here.
MICRO_CAP = 50_000_000
SMALL_CAP_MAX = 2_000_000_000
MID_CAP_MAX = 10_000_000_000


def fetch_shares_outstanding(client: HttpClient, periods: list[str]) -> pd.DataFrame:
    """Bulk share counts per quarter.

    ``periods`` are XBRL frame keys like ``"CY2023Q4I"`` (the ``I`` suffix
    marks an instantaneous, as-opposed-to-duration, fact).

    One request returns every filer for that quarter -- about 2,700 companies --
    which is why this is dramatically cheaper than per-company lookups.
    """
    frames = []
    for period in periods:
        blob = client.get(FRAMES_URL.format(period=period))
        if not blob:
            log.warning("no XBRL frame for %s", period)
            continue
        rows = blob.get("data", [])
        frames.append(
            pd.DataFrame(
                {
                    "cik": [str(r["cik"]).zfill(10) for r in rows],
                    "entity": [r.get("entityName", "") for r in rows],
                    "shares": [float(r.get("val", 0) or 0) for r in rows],
                    # Pin the resolution: pandas 3.0 infers second precision
                    # from bare date strings and then refuses to merge_asof
                    # against a microsecond-resolution price index.
                    "as_of": pd.to_datetime(
                        [r.get("end") for r in rows], errors="coerce"
                    ).astype("datetime64[ns]"),
                    "period": period,
                }
            )
        )
        log.info("frame %s: %d companies", period, len(rows))
    if not frames:
        return pd.DataFrame(columns=["cik", "entity", "shares", "as_of", "period"])
    return pd.concat(frames, ignore_index=True)


def quarter_frames(start: str, end: str) -> list[str]:
    """XBRL frame keys covering ``[start, end]``."""
    qs = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="QE")
    return [f"CY{d.year}Q{d.quarter}I" for d in qs]


def build_smallmid_universe(
    client: HttpClient,
    full_universe: Universe,
    prices: pd.DataFrame,
    *,
    min_cap: float = MICRO_CAP,
    max_cap: float = MID_CAP_MAX,
    min_adv_usd: float = 1_000_000.0,
    min_price: float = 2.0,
    as_of: str | pd.Timestamp | None = None,
    periods: list[str] | None = None,
) -> tuple[Universe, pd.DataFrame]:
    """Select issuers whose point-in-time market cap sits in the band.

    Returns ``(universe, cap_panel)`` where ``cap_panel`` has one row per
    (cik, quarter) with shares, price and computed cap -- keep it, because the
    cap band is a *feature* as well as a filter and a strategy that only works
    on microcaps should be told so.
    """
    if prices.empty:
        return Universe(), pd.DataFrame()

    if periods is None:
        periods = quarter_frames(
            str(prices["date"].min().date()), str(prices["date"].max().date())
        )
    shares = fetch_shares_outstanding(client, periods)
    if shares.empty:
        log.error("no share-count data; cannot build a market-cap universe")
        return Universe(), pd.DataFrame()

    # Map CIK -> ticker using the SEC's own mapping.
    shares["ticker"] = shares["cik"].map(lambda c: full_universe.ticker_for_cik(c))
    shares = shares.dropna(subset=["ticker"])

    # Join each quarter's share count to the price on (or just before) the
    # quarter end. asof handles non-trading quarter ends without reaching
    # forward, which a plain merge on date would not. Both keys are forced to
    # a common datetime resolution first -- merge_asof refuses to mix them.
    px = prices[["date", "ticker", "close"]].copy()
    px["date"] = px["date"].astype("datetime64[ns]")
    px = px.sort_values("date")
    shares = shares.dropna(subset=["as_of"]).copy()
    shares["as_of"] = shares["as_of"].astype("datetime64[ns]")
    shares = shares.sort_values("as_of")
    merged = pd.merge_asof(
        shares,
        px.rename(columns={"date": "as_of"}),
        on="as_of",
        by="ticker",
        direction="backward",
        tolerance=pd.Timedelta(days=10),
    ).dropna(subset=["close"])
    merged["market_cap"] = merged["shares"] * merged["close"]

    # Liquidity screen, also point-in-time.
    adv = (
        prices.assign(dv=prices["close"] * prices["volume"])
        .sort_values("date")
        .groupby("ticker", observed=True)
        .apply(lambda g: g.set_index("date")["dv"].rolling(21, min_periods=5).mean(), include_groups=False)
        .reset_index()
        .rename(columns={"dv": "adv_usd", "date": "as_of"})
    )
    adv["as_of"] = adv["as_of"].astype("datetime64[ns]")
    merged = pd.merge_asof(
        merged.sort_values("as_of"),
        adv.sort_values("as_of"),
        on="as_of",
        by="ticker",
        direction="backward",
        tolerance=pd.Timedelta(days=10),
    )

    in_band = (
        merged["market_cap"].between(min_cap, max_cap)
        & (merged["adv_usd"].fillna(0) >= min_adv_usd)
        & (merged["close"] >= min_price)
    )
    panel = merged.assign(in_band=in_band)

    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        eligible = panel[panel["in_band"] & (panel["as_of"] <= cutoff)]
    else:
        # A name qualifies if it was in band for any quarter in the window.
        # Selecting only names in band for *every* quarter would itself be a
        # forward-looking filter (it requires knowing they never migrated).
        eligible = panel[panel["in_band"]]

    tickers = sorted(eligible["ticker"].unique())
    uni = full_universe.subset(tickers)
    log.info(
        "small/mid universe: %d issuers in [$%.0fm, $%.0fm] with ADV >= $%.1fm",
        len(tickers), min_cap / 1e6, max_cap / 1e6, min_adv_usd / 1e6,
    )
    return uni, panel


def cap_band(market_cap: float) -> str:
    if market_cap < MICRO_CAP:
        return "nano"
    if market_cap < 300_000_000:
        return "micro"
    if market_cap < SMALL_CAP_MAX:
        return "small"
    if market_cap < MID_CAP_MAX:
        return "mid"
    return "large"


def cap_features(panel: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill point-in-time market cap onto every trading day.

    The cap known on any date is the one from the most recent *filed* quarter,
    which is what ``merge_asof(direction="backward")`` gives. Never interpolate
    forward from a later filing.
    """
    if panel.empty or prices.empty:
        return pd.DataFrame(columns=["date", "ticker", "market_cap", "cap_band"])

    caps = panel[["as_of", "ticker", "shares"]].dropna().copy()
    caps["as_of"] = caps["as_of"].astype("datetime64[ns]")
    caps = caps.sort_values("as_of")
    px = prices[["date", "ticker", "close"]].copy()
    px["date"] = px["date"].astype("datetime64[ns]")
    px = px.sort_values("date")
    out = pd.merge_asof(
        px, caps, left_on="date", right_on="as_of", by="ticker", direction="backward"
    )
    out["market_cap"] = out["shares"] * out["close"]
    out["log_market_cap"] = np.log1p(out["market_cap"])
    out["cap_band"] = out["market_cap"].map(lambda c: cap_band(c) if pd.notna(c) else "unknown")
    return out[["date", "ticker", "market_cap", "log_market_cap", "cap_band"]]
