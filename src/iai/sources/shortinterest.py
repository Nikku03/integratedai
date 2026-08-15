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


def for_settlement(client, settlement: str, limit: int = 20000) -> pd.DataFrame:
    """The whole cross-section for one settlement date.

    About 16,000 symbols come back per date, consolidated across venues, which
    makes this the cheaper way to build a panel: 24 requests a year rather than
    one per ticker. It is also a survivorship-free symbol list in its own right,
    since a company that dies simply stops appearing after its last settlement.
    """
    body = {"limit": limit,
            "compareFilters": [{"fieldName": "settlementDate",
                                "fieldValue": settlement, "compareType": "EQUAL"}]}
    return _parse(client.post_text(API, body, HEADERS))


def settlement_dates(lo: str = "2017-12-29", hi: str = "2025-12-31") -> list[str]:
    """Semi-monthly settlement dates, which FINRA sets at mid-month and month-end.

    Generated rather than fetched because the schedule is mechanical; a date
    that turns out not to exist simply returns no rows.
    """
    out = []
    for ts in pd.date_range(lo, hi, freq="MS"):
        mid = ts + pd.Timedelta(days=14)
        end = ts + pd.offsets.MonthEnd(0)
        for d in (mid, end):
            if pd.Timestamp(lo) <= d <= pd.Timestamp(hi):
                out.append(d.strftime("%Y-%m-%d"))
    return out


__all__ = ["API", "FIRST_SETTLEMENT", "for_settlement", "for_symbol",
           "settlement_dates"]
