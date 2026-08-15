"""Consolidated short interest and days-to-cover, from FINRA, free and unauthenticated.

`RESULT_WHY_LOSERS.md` ended with a list of information the panel does not have,
and short interest was first on it. The 108 numeric features reach 0.5302
separability between winning and losing picks — indistinguishable — and the
conclusion was that the way forward is new information rather than new
modelling.

FINRA publishes exactly that, for nothing:

    POST https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest

No key, no account, no header beyond a content type. It carries
``daysToCoverQuantity`` as a first-class field — the precise metric named as
missing — alongside the short position, the previous position, the average
daily volume and the settlement date, semi-monthly.

Two things about it are not obvious from the docs
-------------------------------------------------
**It is a POST that behaves like a GET,** with the filters in a JSON body. The
same body always returns the same rows, so it caches like a GET and
:meth:`HttpClient.post_text` treats it that way.

**It answers CSV, not JSON,** despite taking a JSON request and despite
``Content-Type: text/plain``. Parsing the response as JSON raises
``Extra data: line 1 column 28`` — which is a header row, not corruption.

It is survivorship-free, which is the part that matters
-------------------------------------------------------
Unlike the price vendor, FINRA keeps the record after the company dies. ZGNX
returns a full semi-monthly series ending 2022-02-28, weeks before Zogenix was
acquired; OTIC, KDMN, CHMA, AMRS, ATVI, TWTR and XLNX all return real series
that stop at their death dates rather than starting after them. So this joins to
the dead names the price panel is missing, not only to the survivors.

The hard limit is the start date: the consolidated dataset begins **2017-12-29**,
so roughly the first three years of the 2015-2025 panel have no coverage and any
feature built on it must be masked, not zero-filled, before then.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

API = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
HEADERS = {"Content-Type": "application/json"}

#: The dataset does not exist before this settlement date. A feature built on it
#: must be masked rather than zero-filled for earlier rows, or the model will
#: learn "no short interest reported" as a property of 2015 rather than of the
#: data source.
FIRST_SETTLEMENT = pd.Timestamp("2017-12-29")

NUMERIC = ("currentShortPositionQuantity", "previousShortPositionQuantity",
           "averageDailyVolumeQuantity", "daysToCoverQuantity",
           "changePercent", "changePreviousNumber")


def _parse(text: str | None) -> pd.DataFrame:
    if not text or not text.strip():
        return pd.DataFrame()
    d = pd.read_csv(io.StringIO(text))
    if "settlementDate" in d:
        d["settlementDate"] = pd.to_datetime(d["settlementDate"], errors="coerce")
    for c in NUMERIC:
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def for_symbol(client, symbol: str, limit: int = 1000) -> pd.DataFrame:
    """Every settlement date on record for one ticker."""
    body = {"limit": limit,
            "compareFilters": [{"fieldName": "symbolCode",
                                "fieldValue": symbol, "compareType": "EQUAL"}]}
    return _parse(client.post_text(API, body, HEADERS))


#: The server caps a single response at 5,000 rows no matter what ``limit``
#: asks for, and it does so silently — a request for 25,000 returns exactly
#: 5,000 with no error and no indication there is more. A cross-section is
#: roughly 12-16k symbols, so taking the first page would quietly drop most of
#: the universe and, because the rows come back ordered, would bias the sample
#: rather than merely shrink it.
PAGE = 5000

#: ``daysToCoverQuantity`` uses 999.99 as an infinity sentinel for names with no
#: meaningful average volume. It is the 90th percentile of the raw column, so
#: treating it as a number makes "days to cover" look enormous for exactly the
#: illiquid microcaps this project trades. It becomes NaN here.
DTC_SENTINEL = 999.0


def for_settlement(client, settlement: str, max_rows: int = 40000) -> pd.DataFrame:
    """The whole cross-section for one settlement date, paged.

    Roughly 12-16k symbols come back per date, consolidated across venues, which
    makes this the cheap way to build a panel: 24 requests a year rather than
    one per ticker. It is also a survivorship-free symbol list in its own right,
    since a company that dies simply stops appearing after its last settlement.
    """
    parts, offset = [], 0
    while offset < max_rows:
        body = {"limit": PAGE, "offset": offset,
                "compareFilters": [{"fieldName": "settlementDate",
                                    "fieldValue": settlement,
                                    "compareType": "EQUAL"}]}
        page = _parse(client.post_text(API, body, HEADERS))
        if page.empty:
            break
        parts.append(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    if not parts:
        return pd.DataFrame()
    d = pd.concat(parts, ignore_index=True).drop_duplicates(
        subset=["symbolCode", "settlementDate", "marketClassCode"])
    if "daysToCoverQuantity" in d:
        d.loc[d.daysToCoverQuantity >= DTC_SENTINEL, "daysToCoverQuantity"] = np.nan
    return d


def settlement_dates(lo: str = "2017-12-29", hi: str = "2025-12-31") -> list[str]:
    """Semi-monthly settlement dates: mid-month and month-end, rolled to a business day.

    Generated rather than fetched because the schedule is mechanical. The roll
    matters: a naive 15th-and-last-day list puts about a third of the dates on a
    weekend, and the API answers those with zero rows rather than an error — so
    the fetch looks like it succeeded while silently losing a third of the
    panel. Rolling backward to the previous business day is what FINRA does.
    """
    out, seen = [], set()
    for ts in pd.date_range(pd.Timestamp(lo) - pd.offsets.MonthBegin(1),
                            hi, freq="MS"):
        for d in (ts + pd.Timedelta(days=14), ts + pd.offsets.MonthEnd(0)):
            if d.weekday() >= 5:
                d = d - pd.offsets.BDay(1)
            s = d.strftime("%Y-%m-%d")
            if pd.Timestamp(lo) <= d <= pd.Timestamp(hi) and s not in seen:
                seen.add(s)
                out.append(s)
    return sorted(out)


__all__ = ["API", "FIRST_SETTLEMENT", "for_settlement", "for_symbol",
           "settlement_dates"]
