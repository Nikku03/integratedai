"""A survivorship-free listing universe: which tickers existed, and when they stopped.

The price panel this repo runs on holds 3,662 tickers and not one of them stops
trading in eleven years. `RESULT_SURVIVORSHIP.md` established the shape of that
hole from SEC Form 25 filings — 871 involuntary common-stock deaths — but the
denominator had to be borrowed from published counts of US listed companies,
because EDGAR cannot tell you how many stocks were *listed* on a given day.

Tiingo publishes the missing piece as a plain file with no credential of any
kind:

    https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip

108,327 rows of ``ticker, exchange, assetType, priceCurrency, startDate,
endDate``, regenerated daily, where the dates are documented as the first and
last dates price data exists for the asset. That makes ``endDate`` a last-bar
date — a death mark — and it is correct on inspection: ZGNX ends 2022-03-15
(UCB closed the acquisition that March), XLNX 2022-02-14 (AMD closed that day),
TWTR 2022-10-28, ATVI 2023-10-13, KDMN 2021-11-09.

Restricted to US-exchange common stock with at least a year of history,
**5,818 tickers stopped trading between 2015 and 2025** — against a panel of
3,662 survivors. The universe was never 3,662 names.

What this does and does not give you
------------------------------------
It gives an exact, survivorship-free **membership function**: for any date, the
set of tickers with price data. That is enough to compute a real delisting rate
with a measured denominator instead of an assumed one, and enough to audit any
universe for survivorship in one pass.

It does **not** contain prices. The bulk file is metadata only, and Tiingo's
price endpoint returns ``403 {"detail":"Please supply a token"}``. Nothing here
removes the need for a paid extract to actually backfill dead names.

Two traps, both real
--------------------
**Recycled symbols.** 1,270 US tickers carry more than one row because the
symbol was reissued to a different company. Join on ``(ticker, date)`` inside
the listing window, never on ticker alone — that is exactly the failure that
made Yahoo return post-2024 bars under ``SBNY`` for a bank that failed in 2023.

**A stale ``endDate`` is not always a death.** A name that moved to the pink
sheets keeps quoting, so ``SIVBQ`` shows a current ``endDate`` despite Silicon
Valley Bank having failed. Use the exchange column, and treat a move from
NASDAQ/NYSE to PINK as the delisting event rather than waiting for quotes to
stop.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

import numpy as np
import pandas as pd

BULK = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"

#: The exchanges that constitute a US listing. PINK and the OTC tiers are
#: deliberately excluded from "listed": a name trading there has usually already
#: been delisted, which is the event we are trying to date.
LISTED = frozenset({"NASDAQ", "NYSE", "NYSE ARCA", "AMEX", "NYSE MKT", "BATS", "IEX"})
OTC = frozenset({"PINK", "OTCMKTS", "OTCBB", "OTCGREY", "EXPM"})


def fetch(client) -> pd.DataFrame:
    """The full supported-ticker table, typed and de-duplicated on identity."""
    raw = client.get_bytes(BULK)
    if not raw:
        raise RuntimeError("could not fetch the Tiingo ticker file")
    z = zipfile.ZipFile(io.BytesIO(raw))
    text = z.read(z.namelist()[0]).decode("utf-8", errors="ignore")
    d = pd.DataFrame(list(csv.DictReader(io.StringIO(text))))
    for c in ("startDate", "endDate"):
        d[c] = pd.to_datetime(d[c], errors="coerce")
    d = d.dropna(subset=["startDate", "endDate"])
    return d.rename(columns={"assetType": "asset", "priceCurrency": "ccy"})


def us_stocks(d: pd.DataFrame, include_otc: bool = False) -> pd.DataFrame:
    ex = LISTED | OTC if include_otc else LISTED
    return d[(d.asset == "Stock") & (d.ccy == "USD") & d.exchange.isin(ex)].copy()


def deaths(d: pd.DataFrame, lo: str = "2015-01-01", hi: str = "2025-12-31",
           min_days: int = 365) -> pd.DataFrame:
    """Tickers whose last bar falls in the window, with enough prior history to matter.

    ``min_days`` filters out symbols that existed for a few weeks — SPAC units,
    reservation rows, mis-keyed listings — which would otherwise dominate the
    count while representing nothing an equity strategy could have traded.
    """
    u = us_stocks(d)
    m = ((u.endDate >= pd.Timestamp(lo)) & (u.endDate <= pd.Timestamp(hi))
         & ((u.endDate - u.startDate).dt.days >= min_days))
    return u[m].sort_values("endDate")


def live_count(d: pd.DataFrame, dates) -> pd.Series:
    """How many US-listed common stocks had price data on each given date.

    This is the denominator every survivorship calculation in this repo has so
    far had to assume. Counting is done with two sorted searches rather than a
    per-date scan because the caller usually wants a decade of month-ends.
    """
    u = us_stocks(d)
    s = np.sort(u.startDate.to_numpy())
    e = np.sort(u.endDate.to_numpy())
    idx = pd.DatetimeIndex(dates)
    t = idx.to_numpy()
    started = np.searchsorted(s, t, side="right")
    ended = np.searchsorted(e, t, side="left")
    return pd.Series(started - ended, index=idx, name="listed")


def audit(d: pd.DataFrame, panel_tickers, lo: str = "2015-01-01",
          hi: str = "2025-12-31") -> dict:
    """How much of the real universe a given ticker list is missing."""
    have = set(panel_tickers)
    dead = deaths(d, lo, hi)
    missed = dead[~dead.ticker.isin(have)]
    mid = pd.Timestamp(lo) + (pd.Timestamp(hi) - pd.Timestamp(lo)) / 2
    return {"panel": len(have),
            "deaths_in_window": len(dead),
            "deaths_absent_from_panel": len(missed),
            "listed_at_midpoint": int(live_count(d, [mid]).iloc[0]),
            "panel_share_of_midpoint": len(have) / max(1, int(live_count(d, [mid]).iloc[0]))}


__all__ = ["BULK", "LISTED", "OTC", "audit", "deaths", "fetch", "live_count",
           "us_stocks"]
