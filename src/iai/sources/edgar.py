"""SEC EDGAR: the catalyst backbone.

Two endpoints do the heavy lifting.

``data.sec.gov/submissions/CIK##########.json``
    One request returns an issuer's entire recent filing history including
    ``acceptanceDateTime`` (to the second) and, for 8-Ks, the *item codes*.
    Item codes are the highest signal-to-effort field in all of public market
    data: a single string tells you whether the filing is a routine investor
    deck (7.01) or an auditor resignation (4.01).

``efts.sec.gov/LATEST/search-index``
    EDGAR full-text search over filing bodies and exhibits back to 2001. This
    is how we find catalysts that have no dedicated form type -- collaboration
    agreements, FDA correspondence, going-concern language -- and how the
    partner graph is built.

Point-in-time handling
----------------------
``event_ts`` is ``acceptanceDateTime``, which is when EDGAR accepted the
document. ``available_ts`` adds :data:`DISSEMINATION_LAG` because acceptance
and public dissemination are not the same instant: filings accepted after
17:30 ET are disseminated the next business morning, and the full-text index
trails acceptance by minutes. Modelling that gap is what keeps the backtest
honest.
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from ..core.types import Event, to_utc
from .base import EventSource

log = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FTS_URL = "https://efts.sec.gov/LATEST/search-index"

#: Gap between EDGAR acceptance and the filing being publicly retrievable.
DISSEMINATION_LAG = pd.Timedelta(minutes=15)
#: Filings accepted after this ET time are disseminated the next business day.
AFTER_HOURS_CUTOFF = (17, 30)

#: Prior importance by 8-K item. These are not fitted -- they are a prior
#: encoding how much a given disclosure typically moves a small/mid-cap name,
#: used only to weight event intensity before the model sees it. The model is
#: free to learn that the prior is wrong; the weights just stop a stream of
#: routine 7.01s from drowning out a single 4.02.
ITEM_WEIGHTS: dict[str, float] = {
    # Business and operations
    "1.01": 2.0,   # material definitive agreement - partnerships, licensing, supply deals
    "1.02": 2.0,   # termination of material agreement - often the mirror image
    "1.03": 3.0,   # bankruptcy or receivership
    "1.05": 2.5,   # material cybersecurity incident
    # Financial information
    "2.01": 2.0,   # completion of acquisition or disposition
    "2.02": 1.5,   # results of operations - high impact but the most crowded trade
    "2.03": 1.0,   # creation of a direct financial obligation
    "2.04": 2.5,   # triggering event accelerating an obligation - distress
    "2.05": 1.5,   # costs associated with exit or disposal - restructuring
    "2.06": 2.0,   # material impairment
    # Securities and trading markets
    "3.01": 2.5,   # delisting notice or transfer of listing
    "3.02": 1.8,   # unregistered sale of equity - dilution, often a PIPE
    "3.03": 1.2,   # material modification to rights of security holders
    # Accounting
    "4.01": 2.2,   # change in certifying accountant
    "4.02": 3.0,   # non-reliance on previously issued financials - restatement
    # Governance
    "5.01": 2.5,   # change in control
    "5.02": 1.5,   # departure or election of directors and officers
    "5.03": 0.5,
    "5.07": 0.4,   # submission of matters to a vote
    # Other
    "7.01": 0.6,   # Reg FD disclosure
    "8.01": 0.8,   # other events - genuinely variable, hence the middling weight
    "9.01": 0.2,   # financial statements and exhibits - bookkeeping
}

#: Non-8-K forms worth tracking, with priors.
FORM_WEIGHTS: dict[str, float] = {
    "SC 13D": 2.5,      # activist stake, >5% with intent
    "SC 13D/A": 1.8,
    "SC 13G": 0.8,      # passive stake
    "SC TO-T": 3.0,     # third-party tender offer
    "SC TO-I": 2.0,     # issuer tender offer
    "DEFM14A": 2.5,     # merger proxy
    "PREM14A": 2.2,
    "S-1": 1.5,
    "S-3": 1.2,         # shelf registration - forward dilution risk
    "S-4": 1.8,         # M&A securities registration
    "424B5": 1.8,       # takedown off a shelf - actual dilution, today
    "8-K": 1.0,
    "10-Q": 0.8,
    "10-K": 0.8,
    "NT 10-K": 2.5,     # late filing notification - reliable distress tell
    "NT 10-Q": 2.2,
    "25-NSE": 2.5,      # exchange-initiated delisting
}

_ITEM_RE = re.compile(r"\b(\d\.\d\d)\b")


def parse_items(raw: str) -> list[str]:
    """Pull item codes out of the submissions API's comma-joined ``items`` field."""
    if not raw:
        return []
    return _ITEM_RE.findall(raw)


def dissemination_ts(acceptance: pd.Timestamp) -> pd.Timestamp:
    """When an accepted filing actually became retrievable by the public."""
    ts = to_utc(acceptance)
    local = ts.tz_convert("America/New_York")
    if (local.hour, local.minute) >= AFTER_HOURS_CUTOFF:
        nxt = (local + pd.Timedelta(days=1)).normalize().replace(hour=6)
        while nxt.weekday() >= 5:
            nxt = (nxt + pd.Timedelta(days=1)).normalize().replace(hour=6)
        return nxt.tz_convert("UTC")
    return ts + DISSEMINATION_LAG


class EdgarFilings(EventSource):
    """Per-issuer filing history from the submissions API.

    Emits one event per filing. 8-Ks are split into one event per item code so
    a filing carrying both 5.02 and 8.01 contributes to two distinct feature
    families rather than being averaged into mush.
    """

    name = "edgar"
    default_latency = DISSEMINATION_LAG

    def __init__(self, *args, forms: set[str] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.forms = forms or set(FORM_WEIGHTS)

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        start, end = to_utc(start), to_utc(end)
        events: list[Event] = []
        for ticker in self.universe.tickers:
            cik = self.universe.cik(ticker)
            if not cik:
                continue
            events.extend(self._one_issuer(ticker, cik, start, end))
        return events

    def _one_issuer(
        self, ticker: str, cik: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> list[Event]:
        blob = self.client.get(SUBMISSIONS_URL.format(cik=cik))
        if not blob:
            return []
        out: list[Event] = []
        chunks = [blob.get("filings", {}).get("recent", {})]
        # Issuers with long histories page older filings into separate files.
        for extra in blob.get("filings", {}).get("files", []):
            older = self.client.get(f"https://data.sec.gov/submissions/{extra['name']}")
            if older:
                chunks.append(older)

        sic = str(blob.get("sic", ""))
        sic_desc = blob.get("sicDescription", "")

        for rec in chunks:
            forms = rec.get("form", [])
            for i in range(len(forms)):
                form = forms[i]
                if form not in self.forms:
                    continue
                acc_raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
                filed = rec.get("filingDate", [None] * len(forms))[i]
                if not acc_raw and not filed:
                    continue
                # Older records lack acceptanceDateTime; fall back to the filing
                # date at the after-hours cutoff, which is the conservative read.
                if acc_raw:
                    event_ts = to_utc(acc_raw)
                else:
                    event_ts = to_utc(
                        pd.Timestamp(filed).tz_localize("America/New_York").replace(hour=17, minute=30)
                    )
                available = dissemination_ts(event_ts)
                if not (start <= available < end):
                    continue

                accession = rec.get("accessionNumber", [""] * len(forms))[i]
                items = parse_items(rec.get("items", [""] * len(forms))[i] or "")
                base_payload = {
                    "id": accession,
                    "form": form,
                    "cik": cik,
                    "sic": sic,
                    "sic_description": sic_desc,
                    "primary_doc": rec.get("primaryDocument", [""] * len(forms))[i],
                    "url": self._doc_url(cik, accession, rec.get("primaryDocument", [""] * len(forms))[i]),
                }

                if form == "8-K" and items:
                    for item in items:
                        out.append(
                            Event(
                                source=self.name,
                                kind=f"8-K.{item}",
                                ticker=ticker,
                                event_ts=event_ts,
                                available_ts=available,
                                payload={**base_payload, "item": item},
                                weight=ITEM_WEIGHTS.get(item, 0.8),
                            )
                        )
                else:
                    out.append(
                        Event(
                            source=self.name,
                            kind=f"form.{form}",
                            ticker=ticker,
                            event_ts=event_ts,
                            available_ts=available,
                            payload=base_payload,
                            weight=FORM_WEIGHTS.get(form, 0.5),
                        )
                    )
        return out

    @staticmethod
    def _doc_url(cik: str, accession: str, doc: str) -> str:
        if not accession:
            return ""
        acc = accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"


#: Full-text queries that identify catalysts with no dedicated form type. Each
#: entry is (kind, phrase, weight). Phrases are quoted so EDGAR FTS treats them
#: as exact, which matters enormously for precision -- unquoted "clinical hold"
#: matches any filing containing both words anywhere.
FTS_QUERIES: list[tuple[str, str, float]] = [
    ("catalyst.collaboration", '"collaboration agreement"', 2.0),
    ("catalyst.license", '"license agreement"', 1.8),
    ("catalyst.supply", '"supply agreement"', 1.5),
    ("catalyst.distribution", '"distribution agreement"', 1.5),
    ("catalyst.joint_venture", '"joint venture"', 1.8),
    ("catalyst.merger", '"definitive merger agreement"', 3.0),
    ("catalyst.strategic_alt", '"strategic alternatives"', 2.5),
    ("legal.going_concern", '"substantial doubt about our ability to continue"', 2.8),
    ("legal.material_weakness", '"material weakness"', 1.8),
    ("legal.sec_investigation", '"formal order of investigation"', 3.0),
    ("legal.subpoena", '"received a subpoena"', 2.5),
    ("legal.class_action", '"putative class action"', 1.8),
    ("legal.doj", '"Department of Justice"', 1.5),
    ("regulatory.clinical_hold", '"clinical hold"', 3.0),
    ("regulatory.crl", '"complete response letter"', 3.0),
    ("regulatory.fda_approval", '"FDA has approved"', 2.8),
    ("regulatory.breakthrough", '"breakthrough therapy designation"', 2.0),
    ("regulatory.warning_letter", '"warning letter"', 2.0),
]


class EdgarFullText(EventSource):
    """EDGAR full-text search for phrase-level catalysts.

    FTS covers 2001-present and returns the CIKs of matching filings, which we
    map back to tickers. The endpoint paginates at 100 hits and caps at 10,000
    per query, so queries are issued per calendar month to stay under the cap
    and to keep each cached response small.
    """

    name = "edgar_fts"
    default_latency = DISSEMINATION_LAG

    def __init__(self, *args, queries: list[tuple[str, str, float]] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.queries = queries or FTS_QUERIES

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        start, end = to_utc(start), to_utc(end)
        events: list[Event] = []
        months = pd.date_range(start.normalize(), end.normalize(), freq="MS", inclusive="both")
        if len(months) == 0:
            months = pd.DatetimeIndex([start.normalize()])
        for kind, phrase, weight in self.queries:
            for m_start in months:
                m_end = min(m_start + pd.offsets.MonthEnd(1), end.tz_localize(None))
                events.extend(self._query(kind, phrase, weight, m_start, m_end))
        return events

    def _query(
        self,
        kind: str,
        phrase: str,
        weight: float,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> list[Event]:
        out: list[Event] = []
        for offset in (0, 100, 200):
            params = {
                "q": phrase,
                "forms": "8-K,10-K,10-Q,S-1,424B5",
                "startdt": pd.Timestamp(start).strftime("%Y-%m-%d"),
                "enddt": pd.Timestamp(end).strftime("%Y-%m-%d"),
                "from": offset,
            }
            blob = self.client.get(FTS_URL, params=params)
            hits = (blob or {}).get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                src = hit.get("_source", {})
                ciks = src.get("ciks") or []
                filed = src.get("file_date")
                if not filed:
                    continue
                # FTS exposes only a date, so we assume the conservative
                # after-hours acceptance and let dissemination_ts roll it.
                event_ts = to_utc(
                    pd.Timestamp(filed).tz_localize("America/New_York").replace(hour=17, minute=30)
                )
                available = dissemination_ts(event_ts)
                for cik in ciks:
                    ticker = self.universe.ticker_for_cik(cik)
                    if not ticker:
                        continue
                    out.append(
                        Event(
                            source=self.name,
                            kind=kind,
                            ticker=ticker,
                            event_ts=event_ts,
                            available_ts=available,
                            payload={
                                "id": hit.get("_id", ""),
                                "phrase": phrase,
                                "form": src.get("root_form", ""),
                                "score": hit.get("_score"),
                            },
                            weight=weight,
                        )
                    )
            if len(hits) < 100:
                break
        return out
