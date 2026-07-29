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

#: Days added to an XBRL fact instant before the fact is treated as knowable.
#:
#: The frames API dates each share count by ``end`` -- the *fiscal* instant the
#: fact describes -- and carries an accession but no filing date. A share count
#: for the quarter ending 2020-03-31 is not public on 2020-03-31; it appears in
#: a 10-Q due 40-45 days later, or a 10-K due 60-90 days after a year end.
#: Using the raw instant lets the universe know a share count, and therefore a
#: market cap, up to three months before anyone could have.
#:
#: 90 days covers the slowest statutory deadline. It is deliberately the
#: conservative direction: a name enters the universe later than it might have,
#: never earlier. Recovering the true filing date would need one submissions
#: lookup per (issuer, quarter) -- ~165,000 requests -- to buy back at most a
#: few weeks of eligibility on a slow-moving quantity.
FILING_LAG = pd.Timedelta(days=90)

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
                    # `end` is the fiscal instant the fact describes; the fact
                    # itself is not public until the filing carrying it is.
                    # See FILING_LAG.
                    "fact_instant": pd.to_datetime(
                        [r.get("end") for r in rows], errors="coerce"
                    ).astype("datetime64[ns]"),
                    "as_of": pd.to_datetime(
                        [r.get("end") for r in rows], errors="coerce"
                    ).astype("datetime64[ns]") + FILING_LAG,
                    "accession": [r.get("accn", "") for r in rows],
                    "period": period,
                }
            )
        )
        log.info("frame %s: %d companies", period, len(rows))
    if not frames:
        return pd.DataFrame(
            columns=["cik", "entity", "shares", "fact_instant", "as_of", "accession", "period"]
        )
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


def operating_issuers(
    client: HttpClient, full_universe: Universe, periods: list[str]
) -> pd.DataFrame:
    """Tickers that filed a cover-page share count in the window.

    The candidate pool, and the *only* filter applied before prices are
    fetched. It is deliberately weak: it removes closed-end funds, trusts,
    and registrants that never filed financials, and nothing else.

    It is worth being explicit about why it is not stronger. The tempting move
    is to rank candidates by something -- insider-filing volume, filing count,
    anything -- and keep the top N, because the price fetch is the expensive
    step and a smaller pool is a shorter fetch. Every such ranking is computed
    over the whole window, which means the 2015 universe is chosen using facts
    from 2026. The cap-and-liquidity screen in :func:`rolling_universe` is
    computed from trailing data only, so it can do the cutting instead. Paying
    for a few thousand extra price series is the cost of not making that
    mistake.
    """
    shares = fetch_shares_outstanding(client, periods)
    if shares.empty:
        return pd.DataFrame(columns=["ticker", "cik", "quarters"])
    shares["ticker"] = shares["cik"].map(lambda c: full_universe.ticker_for_cik(c))
    shares = shares.dropna(subset=["ticker"])
    shares = shares[shares["shares"] > 0]
    out = (
        shares.groupby("ticker", observed=True)
        .agg(cik=("cik", "first"), quarters=("period", "nunique"))
        .reset_index()
        .sort_values("ticker")
    )
    log.info("candidate pool: %d issuers filed share counts across %d quarters",
             len(out), len(periods))
    return out


def rolling_universe(
    panel: pd.DataFrame,
    *,
    max_names: int = 2000,
    min_cap: float = MICRO_CAP,
    max_cap: float = MID_CAP_MAX,
) -> pd.DataFrame:
    """Per-quarter membership, capped at ``max_names``, decided point-in-time.

    Once a cap band and a liquidity floor have been applied there are usually
    more eligible names than a study wants to carry. Something has to break the
    tie, and the choice of tiebreak is a place where lookahead gets in through
    the back door -- "the 2,000 most liquid names *of the period*" is fine,
    "the 2,000 largest *today*" is not, and they look similar written down.

    The tiebreak here is **trailing 21-day dollar volume as of the quarter
    end**, which is knowable on the day membership is set. Membership is
    therefore a rolling thing: a name that becomes liquid enters, a name that
    dries up leaves, and neither transition needs the future. Delisted names
    stay in the quarters where they qualified.

    Returns one row per (period, ticker) with the rank that admitted it.
    """
    if panel.empty:
        return pd.DataFrame(columns=["period", "as_of", "ticker", "market_cap", "adv_usd", "rank"])

    eligible = panel[
        panel["in_band"]
        & panel["market_cap"].between(min_cap, max_cap)
        & panel["adv_usd"].notna()
    ].copy()
    if eligible.empty:
        return pd.DataFrame(columns=["period", "as_of", "ticker", "market_cap", "adv_usd", "rank"])

    eligible = eligible.sort_values(["period", "adv_usd"], ascending=[True, False])
    eligible["rank"] = eligible.groupby("period", observed=True).cumcount() + 1
    members = eligible[eligible["rank"] <= max_names]
    cols = ["period", "as_of", "ticker", "market_cap", "adv_usd", "rank"]
    members = members[cols].reset_index(drop=True)

    per_q = members.groupby("period", observed=True)["ticker"].nunique()
    log.info(
        "rolling universe: %d distinct names, %d-%d per quarter (median %d), %d quarters",
        members["ticker"].nunique(), per_q.min(), per_q.max(), int(per_q.median()), len(per_q),
    )
    return members


def membership_mask(members: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Daily ``in_universe`` flag from quarterly membership.

    Forward-filled from the last quarter a name was admitted, never backward:
    a name admitted in 2019Q2 is in the universe from that quarter end onward,
    not for the quarter that produced the numbers.
    """
    if members.empty or prices.empty:
        return prices.assign(in_universe=False)[["date", "ticker", "in_universe"]]

    m = members[["as_of", "ticker"]].copy()
    m["as_of"] = m["as_of"].astype("datetime64[ns]")
    m["in_universe"] = True
    m = m.sort_values("as_of")
    px = prices[["date", "ticker"]].copy()
    px["date"] = px["date"].astype("datetime64[ns]")
    px = px.sort_values("date")
    out = pd.merge_asof(
        px, m, left_on="date", right_on="as_of", by="ticker", direction="backward",
        # Membership set at a quarter end stands until the next one is
        # published; beyond two quarters the name stopped qualifying.
        tolerance=pd.Timedelta(days=200),
    )
    out["in_universe"] = out["in_universe"].fillna(False).astype(bool)
    return out[["date", "ticker", "in_universe"]]


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
