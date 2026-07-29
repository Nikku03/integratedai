"""Form 4 insider transactions from the SEC's quarterly bulk data sets.

Why this exists
---------------
:mod:`iai.sources.insiders` fetches one XML document per filing. That is correct
and it does not scale: 341 names over four years is 55,548 documents and about
70 minutes at the SEC's 9 requests/second. Scaling to 2,000 names over eleven
years is roughly **895,000 documents and 28 hours** on one IP, and sharding
across six machines still leaves nearly five hours.

The SEC already publishes exactly this data, pre-parsed, as quarterly TSV
archives:

    https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/YYYYqQ_form345.zip

Each archive is ~14 MB and downloads in about two seconds. It contains **every**
Form 3/4/5 filed that quarter, for every issuer, already extracted into
relational tables. Eleven years is 44 archives:

===========================  ==================  ==============
approach                     requests            wall clock
===========================  ==================  ==============
per-document XML             ~895,000            ~28 hours
**quarterly bulk archives**  **44**              **~3 minutes**
===========================  ==================  ==============

That is roughly a 500x reduction on what was 99% of the fetch budget, and it
removes the reason to shard across machines at all. Prices become the
bottleneck instead, at 2,000 requests.

The one thing the bulk data does not have
-----------------------------------------
``SUBMISSION.tsv`` carries ``FILING_DATE`` -- a **date**, with no time. The
per-document path reads ``acceptanceDateTime`` to the second and can tell a
09:40 filing (tradable at that day's close) from a 19:20 one (not public until
the next morning).

Losing that precision is handled by assuming the **pessimistic** case: a filing
is treated as arriving after the close of ``FILING_DATE``, so it is not
actionable until the next session's open. Roughly two thirds of Form 4s are in
fact filed after hours, so this is right more often than not, and where it is
wrong it costs part of a session of edge rather than inventing any. Never
reverse this assumption to gain back the half day; that is precisely the trade
that turns a backtest into fiction.

If you need the exact timestamps for a subset -- say the open-market purchases
in your traded universe -- fetch those from the submissions API and leave the
rest on the bulk path. :func:`enrich_acceptance_times` does that.
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections import defaultdict

import pandas as pd

from ..core.config import Config
from ..core.http import HttpClient
from ..core.types import Event, to_utc
from ..core.universe import Universe
from .base import EventSource
from .insiders import ROLE_WEIGHTS, TRANSACTION_WEIGHTS, classify_role

log = logging.getLogger(__name__)

BULK_URL = (
    "https://www.sec.gov/files/structureddata/data/"
    "insider-transactions-data-sets/{year}q{quarter}_form345.zip"
)

#: Relationship flags are packed into one string like "1,0,0,0" ordered
#: director, officer, tenpercent, other.
_REL_FIELDS = ("director", "officer", "tenpercent", "other")


def quarters(start: str, end: str) -> list[tuple[int, int]]:
    """(year, quarter) pairs covering ``[start, end]``."""
    idx = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="Q")
    return [(p.year, p.quarter) for p in idx]


def _parse_relationship(raw: str) -> tuple[bool, bool, bool]:
    """Unpack RPTOWNER_RELATIONSHIP into (is_officer, is_director, is_ten)."""
    if not isinstance(raw, str):
        return False, False, False
    parts = [p.strip() for p in raw.split(",")]
    flags = dict(zip(_REL_FIELDS, parts, strict=False))
    truthy = {"1", "true", "TRUE", "Y"}
    return (
        flags.get("officer", "") in truthy,
        flags.get("director", "") in truthy,
        flags.get("tenpercent", "") in truthy,
    )


def load_quarter(
    client: HttpClient, year: int, quarter: int, *, tickers: set[str] | None = None
) -> pd.DataFrame:
    """Download one quarterly archive and return joined non-derivative trades.

    Filtering to ``tickers`` happens before the joins, which matters: an
    unfiltered quarter is ~111,000 transaction rows and the join against
    reporting owners is the expensive step.
    """
    url = BULK_URL.format(year=year, quarter=quarter)
    # The archive is binary, so it bypasses the JSON/text cache and is fetched
    # directly. It is ~14 MB and the SEC serves it quickly.
    try:
        resp = client.session.get(url, timeout=180)
        if resp.status_code != 200:
            log.warning("bulk %sq%s -> HTTP %s", year, quarter, resp.status_code)
            return pd.DataFrame()
        blob = resp.content
    except Exception:  # noqa: BLE001 - a missing quarter must not abort the run
        log.exception("bulk %sq%s failed", year, quarter)
        return pd.DataFrame()

    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        sub = pd.read_csv(z.open("SUBMISSION.tsv"), sep="\t", dtype=str)
        trans = pd.read_csv(z.open("NONDERIV_TRANS.tsv"), sep="\t", dtype=str)
        owners = pd.read_csv(z.open("REPORTINGOWNER.tsv"), sep="\t", dtype=str)
    except Exception:  # noqa: BLE001 - corrupt archive
        log.exception("bulk %sq%s could not be read", year, quarter)
        return pd.DataFrame()

    sub = sub[sub["DOCUMENT_TYPE"] == "4"]
    sub["ticker"] = sub["ISSUERTRADINGSYMBOL"].str.upper().str.strip()
    if tickers:
        sub = sub[sub["ticker"].isin(tickers)]
    if sub.empty:
        return pd.DataFrame()

    keep = set(sub["ACCESSION_NUMBER"])
    trans = trans[trans["ACCESSION_NUMBER"].isin(keep)]
    trans = trans[trans["TRANS_CODE"].isin(TRANSACTION_WEIGHTS)]
    if trans.empty:
        return pd.DataFrame()

    # One filing can carry several reporting owners; keep the first, matching
    # the per-document parser's behaviour.
    owners = owners[owners["ACCESSION_NUMBER"].isin(keep)].drop_duplicates(
        subset="ACCESSION_NUMBER", keep="first"
    )

    df = trans.merge(
        sub[["ACCESSION_NUMBER", "ticker", "ISSUERCIK", "FILING_DATE"]],
        on="ACCESSION_NUMBER", how="left",
    ).merge(
        owners[["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME",
                "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"]],
        on="ACCESSION_NUMBER", how="left",
    )

    df["shares"] = pd.to_numeric(df["TRANS_SHARES"], errors="coerce")
    df["price"] = pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce")
    df["transaction_date"] = pd.to_datetime(df["TRANS_DATE"], format="%d-%b-%Y", errors="coerce")
    df["filing_date"] = pd.to_datetime(df["FILING_DATE"], format="%d-%b-%Y", errors="coerce")
    df = df.dropna(subset=["shares", "filing_date", "ticker"])

    rel = df["RPTOWNER_RELATIONSHIP"].map(_parse_relationship)
    df["role"] = [
        classify_role(title if isinstance(title, str) else "", *flags)
        for title, flags in zip(df["RPTOWNER_TITLE"], rel, strict=False)
    ]
    df["value_usd"] = df["shares"] * df["price"]
    return df.rename(columns={
        "ACCESSION_NUMBER": "accession", "TRANS_CODE": "code",
        "RPTOWNERCIK": "owner_cik", "RPTOWNERNAME": "owner", "ISSUERCIK": "cik",
    })[[
        "ticker", "cik", "accession", "owner", "owner_cik", "role", "code",
        "shares", "price", "value_usd", "transaction_date", "filing_date",
    ]]


class BulkInsiderTransactions(EventSource):
    """Form 4 events from quarterly bulk archives.

    Drop-in replacement for :class:`~iai.sources.insiders.InsiderTransactions`,
    emitting the same event kinds and weights. Two behavioural differences,
    both stated rather than hidden:

    * ``available_ts`` is the **close of the filing date**, because the bulk
      data has no acceptance time. Conservative; see the module docstring.
    * Coverage is every issuer the SEC has, not just those in the universe, so
      passing a universe is a filter rather than a fetch plan.
    """

    name = "insiders"
    default_latency = pd.Timedelta(days=2)

    def __init__(
        self,
        cfg: Config,
        client: HttpClient,
        universe: Universe,
        *,
        cluster_days: int = 14,
        min_cluster: int = 2,
        min_value_usd: float = 25_000.0,
        **kwargs,
    ) -> None:
        super().__init__(cfg, client, universe, **kwargs)
        self.cluster_days = cluster_days
        self.min_cluster = min_cluster
        self.min_value_usd = min_value_usd

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        start, end = to_utc(start), to_utc(end)
        tickers = set(self.universe.tickers) or None

        frames = []
        qs = quarters(str(start.date()), str(end.date()))
        for year, quarter in qs:
            df = load_quarter(self.client, year, quarter, tickers=tickers)
            if not df.empty:
                frames.append(df)
            log.info("bulk %sq%s: %d qualifying transactions", year, quarter, len(df))
        if not frames:
            return []
        trades = pd.concat(frames, ignore_index=True)
        log.info("bulk insiders: %d transactions over %d quarters", len(trades), len(qs))

        events = self._to_events(trades, start, end)
        events.extend(self._clusters(trades, start, end))
        return events

    # ---------------------------------------------------------------- events

    @staticmethod
    def _available(filing_date: pd.Timestamp) -> pd.Timestamp:
        """Pessimistic availability: the close of the filing date.

        Without an acceptance time, assume the filing landed after the bell.
        The calendar layer then rolls it to the next session's open.
        """
        return to_utc(
            pd.Timestamp(filing_date).tz_localize("America/New_York").replace(hour=17, minute=30)
        )

    def _to_events(self, trades: pd.DataFrame, start, end) -> list[Event]:
        out: list[Event] = []
        for r in trades.itertuples(index=False):
            value = r.value_usd
            if pd.notna(value) and value < self.min_value_usd:
                continue
            available = self._available(r.filing_date)
            if not (start <= available < end):
                continue

            weight = TRANSACTION_WEIGHTS.get(r.code, 0.0) * ROLE_WEIGHTS.get(r.role, 0.6)
            if pd.notna(value) and value > 0:
                weight *= min(1.0 + (value / 1_000_000.0) ** 0.5, 3.0)

            txn = r.transaction_date if pd.notna(r.transaction_date) else r.filing_date
            event_ts = min(
                to_utc(pd.Timestamp(txn).tz_localize("America/New_York").replace(hour=9, minute=30)),
                available,
            )
            out.append(Event(
                source=self.name,
                kind="insider.buy" if r.code == "P" else "insider.sell",
                ticker=r.ticker,
                event_ts=event_ts,
                available_ts=available,
                payload={
                    "id": f"{r.accession}:{r.owner_cik}:{pd.Timestamp(txn):%Y%m%d}:{r.code}",
                    "owner": r.owner, "role": r.role, "code": r.code,
                    "shares": float(r.shares),
                    "price": float(r.price) if pd.notna(r.price) else None,
                    "value_usd": float(value) if pd.notna(value) else None,
                    "source_path": "bulk",
                },
                weight=weight,
            ))
        return out

    def _clusters(self, trades: pd.DataFrame, start, end) -> list[Event]:
        """Distinct insiders buying inside a rolling window."""
        buys = trades[(trades["code"] == "P") & (trades["value_usd"].fillna(0) >= self.min_value_usd)]
        by_ticker: dict[str, list] = defaultdict(list)
        for r in buys.itertuples(index=False):
            by_ticker[r.ticker].append(r)

        out: list[Event] = []
        window = pd.Timedelta(days=self.cluster_days)
        for ticker, rows in by_ticker.items():
            rows.sort(key=lambda x: x.filing_date)
            for i, anchor in enumerate(rows):
                lo = anchor.filing_date - window
                members = [x for x in rows[: i + 1] if x.filing_date >= lo]
                distinct = {x.owner_cik or x.owner for x in members}
                if len(distinct) < self.min_cluster:
                    continue
                available = self._available(anchor.filing_date)
                if not (start <= available < end):
                    continue
                total = float(sum(x.value_usd or 0 for x in members))
                last_txn = max(
                    (x.transaction_date for x in members if pd.notna(x.transaction_date)),
                    default=anchor.filing_date,
                )
                out.append(Event(
                    source=self.name,
                    kind="insider.cluster_buy",
                    ticker=ticker,
                    event_ts=min(
                        to_utc(pd.Timestamp(last_txn).tz_localize("America/New_York").replace(hour=9, minute=30)),
                        available,
                    ),
                    available_ts=available,
                    payload={
                        "id": f"cluster:{ticker}:{anchor.filing_date:%Y%m%d}:{len(distinct)}",
                        "n_insiders": len(distinct), "n_trades": len(members),
                        "total_usd": total, "roles": sorted({x.role for x in members}),
                        "source_path": "bulk",
                    },
                    weight=3.0 + 1.5 * (len(distinct) - 1),
                ))
        # One cluster event per ticker per day.
        seen: set[tuple[str, str]] = set()
        deduped = []
        for e in sorted(out, key=lambda x: x.available_ts):
            key = (e.ticker, e.available_ts.strftime("%Y%m%d"))
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        log.info("bulk insiders: %d cluster-buy events", len(deduped))
        return deduped


def enrich_acceptance_times(
    events: pd.DataFrame, client: HttpClient, universe: Universe, *, kinds: tuple[str, ...] = ("insider.buy",)
) -> pd.DataFrame:
    """Replace date-only availability with exact acceptance times, for a subset.

    The bulk path is pessimistic by half a session. If that matters -- and it
    only matters for the events you actually trade -- this fetches real
    ``acceptanceDateTime`` values for the named kinds from the submissions API
    and leaves everything else alone. Fetching a few thousand is cheap; fetching
    all of them defeats the purpose of using bulk data at all.
    """
    from .edgar import SUBMISSIONS_URL, dissemination_ts

    if events.empty:
        return events
    target = events[events["kind"].isin(kinds)]
    ciks = {universe.cik(t) for t in target["ticker"].unique()}
    ciks.discard(None)

    exact: dict[str, pd.Timestamp] = {}
    for cik in ciks:
        blob = client.get(SUBMISSIONS_URL.format(cik=cik))
        if not blob:
            continue
        rec = blob.get("filings", {}).get("recent", {})
        forms = rec.get("form", [])
        for i, form in enumerate(forms):
            if form != "4":
                continue
            acc = rec.get("accessionNumber", [""] * len(forms))[i]
            raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
            if acc and raw:
                exact[acc] = dissemination_ts(to_utc(raw))

    out = events.copy()
    n = 0
    for idx, row in out.iterrows():
        if row["kind"] not in kinds:
            continue
        acc = str(row["payload"].get("id", "")).split(":")[0]
        ts = exact.get(acc)
        # Only ever move availability EARLIER, and never before the event.
        if ts is not None and ts < row["available_ts"] and ts >= row["event_ts"]:
            out.at[idx, "available_ts"] = ts
            n += 1
    log.info("enriched %d/%d events with exact acceptance times", n, len(target))
    return out
