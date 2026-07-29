"""Insider transactions from SEC Form 4.

Why this is the best "institutions are moving" signal available for free
----------------------------------------------------------------------
You asked for institutional movement on a short horizon. Ranked by how quickly
the information reaches you:

===================  ==========================  ==========================
Filing               Lag                         Use for a days-to-weeks bet
===================  ==========================  ==========================
**Form 4**           **2 business days**         **Yes. This one.**
SC 13D               10 days after crossing 5%   Yes, activist intent
SC 13G               45 days after year-end      Marginal
**13F-HR**           **45 days after quarter**   **No. See institutional.py**
===================  ==========================  ==========================

A 13F tells you what a fund held up to 135 days ago. Form 4 tells you what an
officer did the day before yesterday. For a two-week holding period those are
not the same class of information.

What actually predicts, and what does not
-----------------------------------------
Most Form 4s are noise, and treating them as one undifferentiated stream is the
main reason naive insider signals fail. The transaction code is everything:

``P`` -- open-market purchase
    The signal. An officer spending their own money at the market price is the
    only transaction here with unambiguous information content.
``S`` -- open-market sale
    Weak and asymmetric. Insiders sell for diversification, tax bills, divorce,
    and house purchases. A sale is mild evidence; a purchase is strong evidence.
``A`` -- grant or award
    Noise. The compensation committee decided this months ago.
``M`` -- option exercise
    Noise, and usually mechanical. Frequently paired with an immediate ``S``.
``F`` -- shares withheld for taxes
    Pure noise. Automatic.
``G`` -- gift
    Noise for our purposes.

The literature (Lakonishok-Lee, Jeng-Metrick-Zeckhauser, Cohen-Malloy-Pomorski)
is consistent on two further points, both implemented here:

1. **Cluster buying dominates single buys.** Three different insiders buying
   inside a fortnight is a far stronger signal than one insider buying three
   times, and both beat a single purchase.
2. **Role matters.** A CEO or CFO purchase carries more information than a
   director's, and a 10% owner's purchase is often mechanical portfolio
   rebalancing rather than a view.

Point-in-time handling
----------------------
``event_ts`` is the **transaction date**; ``available_ts`` is the filing's
acceptance timestamp plus dissemination lag. The gap is the two-business-day
filing window, and it is not optional to model it: dating an insider buy to the
transaction date gives you two free days of a move that is, by construction,
the part worth having.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from xml.etree import ElementTree

import pandas as pd

from ..core.types import Event, to_utc
from .base import EventSource
from .edgar import SUBMISSIONS_URL, dissemination_ts

log = logging.getLogger(__name__)

#: Transaction codes worth emitting, with a base prior weight. Codes absent
#: here (A, M, F, G, C, E, H, I, U, W, Z) are dropped entirely rather than
#: down-weighted -- they are mechanical, and letting them through mostly adds
#: variance to the cluster counts.
TRANSACTION_WEIGHTS: dict[str, float] = {
    "P": 3.0,   # open-market purchase - the signal
    "S": 1.0,   # open-market sale - weak, asymmetric
}

#: Role multipliers. A CEO buying is worth more than a director buying, and a
#: 10% owner buying is frequently a fund rebalancing rather than a view.
ROLE_WEIGHTS: dict[str, float] = {
    "ceo": 1.6,
    "cfo": 1.5,
    "president": 1.4,
    "coo": 1.3,
    "officer": 1.2,
    "director": 1.0,
    "tenpercent": 0.7,
    "other": 0.6,
}

_CEO = re.compile(r"\bchief exec|;?\bceo\b", re.I)
_CFO = re.compile(r"\bchief financ|\bcfo\b", re.I)
_COO = re.compile(r"\bchief oper|\bcoo\b", re.I)
_PRES = re.compile(r"\bpresident\b", re.I)


def classify_role(title: str, is_officer: bool, is_director: bool, is_ten: bool) -> str:
    """Map a free-text officer title and the boolean flags to a role bucket."""
    t = title or ""
    if _CEO.search(t):
        return "ceo"
    if _CFO.search(t):
        return "cfo"
    if _COO.search(t):
        return "coo"
    if _PRES.search(t):
        return "president"
    if is_officer:
        return "officer"
    if is_director:
        return "director"
    if is_ten:
        return "tenpercent"
    return "other"


def _text(node, path: str, default: str = "") -> str:
    found = node.find(path)
    if found is None:
        return default
    # Form 4 wraps most scalars in a <value> child, but not always.
    val = found.find("value")
    target = val if val is not None else found
    return (target.text or default).strip()


def _num(node, path: str) -> float | None:
    raw = _text(node, path)
    try:
        return float(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _transaction_ts(transaction_date: pd.Timestamp, accepted_ts: pd.Timestamp) -> pd.Timestamp:
    """Timestamp for a transaction the filing reports only as a *date*.

    Form 4 gives a transaction date, not a time. An open-market trade happens
    no earlier than the opening bell, so 09:30 ET is the conservative anchor.

    The clamp against ``accepted_ts`` is not belt-and-braces -- it is load
    bearing. Roughly 3% of Form 4s are filed the same day as the transaction,
    and a filing accepted at 10:42 ET would otherwise carry an ``event_ts``
    later than its own ``available_ts``. An earlier version of this function
    anchored at the 16:00 close and ``validate_events`` rejected the batch,
    which is precisely the job that validator exists to do.
    """
    anchor = to_utc(
        pd.Timestamp(transaction_date).tz_localize("America/New_York").replace(hour=9, minute=30)
    )
    return min(anchor, to_utc(accepted_ts))


@dataclass
class InsiderTrade:
    ticker: str
    cik: str
    owner: str
    owner_cik: str
    role: str
    code: str
    acquired: bool
    shares: float
    price: float | None
    transaction_date: pd.Timestamp
    accepted_ts: pd.Timestamp
    accession: str

    @property
    def value_usd(self) -> float | None:
        return self.shares * self.price if self.price else None


def parse_form4(xml_text: str, accepted_ts: pd.Timestamp, accession: str) -> list[InsiderTrade]:
    """Parse one Form 4 XML into individual non-derivative transactions.

    Derivative transactions (option grants, warrant exercises) are skipped:
    they are dominated by compensation mechanics and their "price" is a strike,
    not a market price, so mixing them into a dollar-value signal is wrong.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    ticker = _text(root, "issuer/issuerTradingSymbol").upper()
    issuer_cik = _text(root, "issuer/issuerCik")
    if not ticker:
        return []

    out: list[InsiderTrade] = []
    # A single Form 4 can carry several reporting owners (joint filings).
    owners = root.findall("reportingOwner") or [root]
    primary = owners[0]
    rel = primary.find("reportingOwnerRelationship")
    is_officer = _text(rel, "isOfficer") in ("1", "true") if rel is not None else False
    is_director = _text(rel, "isDirector") in ("1", "true") if rel is not None else False
    is_ten = _text(rel, "isTenPercentOwner") in ("1", "true") if rel is not None else False
    title = _text(rel, "officerTitle") if rel is not None else ""
    role = classify_role(title, is_officer, is_director, is_ten)
    owner_name = _text(primary, "reportingOwnerId/rptOwnerName")
    owner_cik = _text(primary, "reportingOwnerId/rptOwnerCik")

    for txn in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(txn, "transactionCoding/transactionCode")
        if code not in TRANSACTION_WEIGHTS:
            continue
        tdate = _text(txn, "transactionDate")
        if not tdate:
            continue
        shares = _num(txn, "transactionAmounts/transactionShares")
        price = _num(txn, "transactionAmounts/transactionPricePerShare")
        acq = _text(txn, "transactionAmounts/transactionAcquiredDisposedCode") == "A"
        if not shares:
            continue
        out.append(
            InsiderTrade(
                ticker=ticker,
                cik=issuer_cik,
                owner=owner_name,
                owner_cik=owner_cik,
                role=role,
                code=code,
                acquired=acq,
                shares=float(shares),
                price=price,
                transaction_date=pd.Timestamp(tdate),
                accepted_ts=accepted_ts,
                accession=accession,
            )
        )
    return out


class InsiderTransactions(EventSource):
    """Form 4 open-market purchases and sales, with cluster detection.

    Emits two kinds of event:

    ``insider.buy`` / ``insider.sell``
        One per transaction, weighted by code, role and dollar size.
    ``insider.cluster_buy``
        Fired when ``min_cluster`` *distinct* insiders have bought within
        ``cluster_days``. Availability is the filing date of the last purchase
        in the cluster -- the pattern is not observable until then, and dating
        it to the first purchase would be a lookahead bug of exactly the kind
        that makes insider signals look better on paper than in production.
    """

    name = "insiders"
    default_latency = pd.Timedelta(days=2)

    def __init__(
        self,
        *args,
        cluster_days: int = 14,
        min_cluster: int = 2,
        min_value_usd: float = 25_000.0,
        workers: int = 8,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.cluster_days = cluster_days
        self.min_cluster = min_cluster
        self.min_value_usd = min_value_usd
        self.workers = workers

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        start, end = to_utc(start), to_utc(end)
        trades = self._collect_trades(start, end)
        if not trades:
            return []
        events = [e for t in trades if (e := self._to_event(t, start, end))]
        events.extend(self._clusters(trades, start, end))
        return events

    # ------------------------------------------------------------ collection

    def _collect_trades(self, start: pd.Timestamp, end: pd.Timestamp) -> list[InsiderTrade]:
        """Find Form 4 filings per issuer, then fetch and parse their XML."""
        wanted: list[tuple[str, str, str, pd.Timestamp]] = []  # (ticker, cik, url, accepted)
        for ticker in self.universe.tickers:
            cik = self.universe.cik(ticker)
            if not cik:
                continue
            blob = self.client.get(SUBMISSIONS_URL.format(cik=cik))
            if not blob:
                continue
            chunks = [blob.get("filings", {}).get("recent", {})]
            for extra in blob.get("filings", {}).get("files", []):
                older = self.client.get(f"https://data.sec.gov/submissions/{extra['name']}")
                if older:
                    chunks.append(older)
            for rec in chunks:
                forms = rec.get("form", [])
                for i, form in enumerate(forms):
                    if form != "4":
                        continue
                    acc_raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
                    if not acc_raw:
                        continue
                    accepted = dissemination_ts(to_utc(acc_raw))
                    if not (start <= accepted < end):
                        continue
                    accession = rec.get("accessionNumber", [""] * len(forms))[i]
                    doc = rec.get("primaryDocument", [""] * len(forms))[i]
                    if not doc:
                        continue
                    # primaryDocument points at the XSL-rendered view; the raw
                    # XML sits at the same path without the renderer segment.
                    doc = doc.split("/")[-1]
                    url = (
                        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{accession.replace('-', '')}/{doc}"
                    )
                    wanted.append((ticker, cik, url, accepted))

        log.info("insiders: %d Form 4 documents to fetch", len(wanted))
        bodies = self.client.get_many(
            [w[2] for w in wanted], parse="text", workers=self.workers
        )

        trades: list[InsiderTrade] = []
        for ticker, _cik, url, accepted in wanted:
            body = bodies.get(url)
            if not body:
                continue
            parsed = parse_form4(body, accepted, url.rsplit("/", 2)[-2])
            for t in parsed:
                # Trust our own ticker mapping over the filer's free-text symbol
                # field, which is frequently stale or blank on small caps.
                t.ticker = ticker
            trades.extend(parsed)
        log.info("insiders: parsed %d qualifying transactions", len(trades))
        return trades

    # ---------------------------------------------------------------- events

    def _to_event(self, t: InsiderTrade, start: pd.Timestamp, end: pd.Timestamp) -> Event | None:
        value = t.value_usd
        if value is not None and value < self.min_value_usd:
            return None
        if not (start <= t.accepted_ts < end):
            return None

        base = TRANSACTION_WEIGHTS.get(t.code, 0.0)
        weight = base * ROLE_WEIGHTS.get(t.role, 0.6)
        # Scale mildly with dollar size. A $5m purchase is a stronger statement
        # than a $30k one, but the relationship is far from linear -- a small-cap
        # CFO putting in $200k may be risking a large share of their net worth.
        if value:
            weight *= min(1.0 + (value / 1_000_000.0) ** 0.5, 3.0)

        kind = "insider.buy" if t.code == "P" else "insider.sell"
        return Event(
            source=self.name,
            kind=kind,
            ticker=t.ticker,
            event_ts=_transaction_ts(t.transaction_date, t.accepted_ts),
            available_ts=t.accepted_ts,
            payload={
                "id": f"{t.accession}:{t.owner_cik}:{t.transaction_date:%Y%m%d}:{t.code}",
                "owner": t.owner,
                "role": t.role,
                "code": t.code,
                "shares": t.shares,
                "price": t.price,
                "value_usd": value,
                "filing_lag_days": (t.accepted_ts - to_utc(t.transaction_date)).days,
            },
            weight=weight,
        )

    def _clusters(
        self, trades: list[InsiderTrade], start: pd.Timestamp, end: pd.Timestamp
    ) -> list[Event]:
        """Detect multiple distinct insiders buying inside a rolling window."""
        buys: dict[str, list[InsiderTrade]] = defaultdict(list)
        for t in trades:
            if t.code == "P" and (t.value_usd or 0) >= self.min_value_usd:
                buys[t.ticker].append(t)

        out: list[Event] = []
        for ticker, ts in buys.items():
            ts.sort(key=lambda x: x.accepted_ts)
            for i, anchor in enumerate(ts):
                window_end = anchor.accepted_ts
                window_start = window_end - pd.Timedelta(days=self.cluster_days)
                members = [
                    t for t in ts[: i + 1] if t.accepted_ts >= window_start
                ]
                distinct = {t.owner_cik or t.owner for t in members}
                if len(distinct) < self.min_cluster:
                    continue
                if not (start <= window_end < end):
                    continue
                total = sum(t.value_usd or 0 for t in members)
                out.append(
                    Event(
                        source=self.name,
                        kind="insider.cluster_buy",
                        ticker=ticker,
                        # The cluster becomes knowable when the last member is
                        # filed, not when the first purchase happened.
                        event_ts=_transaction_ts(
                            max(t.transaction_date for t in members), window_end
                        ),
                        available_ts=window_end,
                        payload={
                            "id": f"cluster:{ticker}:{window_end:%Y%m%d%H%M}:{len(distinct)}",
                            "n_insiders": len(distinct),
                            "n_trades": len(members),
                            "total_usd": total,
                            "roles": sorted({t.role for t in members}),
                        },
                        # Cluster strength scales with how many independent
                        # people acted, which is the whole point of the signal.
                        weight=3.0 + 1.5 * (len(distinct) - 1),
                    )
                )
        # One cluster event per ticker per day is plenty; consecutive days in the
        # same window would otherwise emit a near-duplicate every session.
        seen: set[tuple[str, str]] = set()
        deduped = []
        for e in sorted(out, key=lambda x: x.available_ts):
            key = (e.ticker, e.available_ts.strftime("%Y%m%d"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        log.info("insiders: %d cluster-buy events", len(deduped))
        return deduped
