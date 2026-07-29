"""Institutional ownership: 13F holdings and 13D/G stake disclosures.

Read this before wiring 13F into a short-horizon strategy
---------------------------------------------------------
13F-HR is filed **45 days after quarter end**. A position opened on 5 January
appears on 15 May. By the time you can see it, the information is between 45
and 135 days old, and the fund has had a full quarter to finish accumulating
or to leave entirely.

For a two-week holding period, that is not a timing signal, and this module
says so in :meth:`ThirteenF.health` rather than quietly contributing a feature
that looks fine in a backtest fitted on it. What 13F *is* good for:

* **Context, not triggers.** "Is this name already crowded with funds?" is a
  useful conditioning variable for how much follow-through to expect from a
  catalyst.
* **Ownership change regime.** Rising institutional ownership over several
  quarters is a slow variable, and slow variables are fine as *features* as
  long as you do not treat them as events.

SC 13D is a different animal: due **10 days** after crossing 5%, and it carries
*intent*. A 13D says someone bought a fifth of a small-cap company and plans to
do something about it. That is short-horizon tradable and it is why 13D carries
a much higher prior weight than 13G, the passive cousin.

Point-in-time handling
----------------------
Every date here is the filing acceptance timestamp, never the period covered.
Dating a 13F to its report date instead of its filing date hands the model 45
days of hindsight and is the single most common error in ownership research.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from xml.etree import ElementTree

import pandas as pd

from ..core.types import Event, to_utc
from .base import EventSource
from .edgar import SUBMISSIONS_URL, dissemination_ts

log = logging.getLogger(__name__)

#: 13F is filed 45 days after quarter end. Modelled explicitly so nobody can
#: accidentally treat the report period as the availability date.
THIRTEEN_F_LAG = pd.Timedelta(days=45)

_NS = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS.sub("", tag)


def parse_13f_table(xml_text: str) -> list[dict]:
    """Parse a 13F information table into holdings.

    The schema is namespaced and filers vary in which namespace they declare,
    so tags are compared after stripping it rather than by qualified name.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    out = []
    for node in root.iter():
        if _strip_ns(node.tag) != "infoTable":
            continue
        rec: dict = {}
        for child in node.iter():
            tag = _strip_ns(child.tag)
            if tag in ("nameOfIssuer", "cusip", "titleOfClass"):
                rec[tag] = (child.text or "").strip()
            elif tag == "value":
                try:
                    rec["value"] = float((child.text or "0").replace(",", ""))
                except ValueError:
                    pass
            elif tag == "sshPrnamt":
                try:
                    rec["shares"] = float((child.text or "0").replace(",", ""))
                except ValueError:
                    pass
        if rec.get("cusip"):
            out.append(rec)
    return out


class ThirteenF(EventSource):
    """Quarter-over-quarter institutional position changes, by CUSIP.

    Disabled by default for short-horizon work. Enable deliberately, with
    ``allow_stale=True``, and only as a slow conditioning feature.

    Requires a ``cusip_to_ticker`` map. CUSIPs are not free to redistribute in
    bulk (CUSIP Global Services licenses them), which is a genuine obstacle:
    build the map from your own holdings data, from SEC filing cover pages, or
    from a vendor. Without it every holding is unattributable and the source
    reports why rather than silently returning nothing.
    """

    name = "institutional"
    default_latency = THIRTEEN_F_LAG

    def __init__(
        self,
        *args,
        filer_ciks: list[str] | None = None,
        cusip_to_ticker: dict[str, str] | None = None,
        allow_stale: bool = False,
        min_change_pct: float = 0.25,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.filer_ciks = filer_ciks or []
        self.cusip_to_ticker = {k.upper(): v.upper() for k, v in (cusip_to_ticker or {}).items()}
        self.allow_stale = allow_stale
        self.min_change_pct = min_change_pct
        self.enabled = bool(self.filer_ciks and self.cusip_to_ticker and allow_stale)

    def health(self) -> dict:
        if not self.allow_stale:
            reason = (
                "OFF by design: 13F is 45-135 days stale, which is not a timing signal "
                "for a days-to-weeks trade. Pass allow_stale=True to use as slow context."
            )
        elif not self.filer_ciks:
            reason = "no filer CIKs configured (which funds do you want to track?)"
        elif not self.cusip_to_ticker:
            reason = "no CUSIP->ticker map; holdings cannot be attributed"
        else:
            reason = ""
        return {"name": self.name, "enabled": self.enabled, "reason": reason}

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        # filer -> report period -> {ticker: shares}
        history: dict[str, dict[pd.Timestamp, dict[str, float]]] = defaultdict(dict)
        filed_at: dict[tuple[str, pd.Timestamp], pd.Timestamp] = {}

        for cik in self.filer_ciks:
            blob = self.client.get(SUBMISSIONS_URL.format(cik=str(cik).lstrip("0").zfill(10)))
            if not blob:
                continue
            rec = blob.get("filings", {}).get("recent", {})
            forms = rec.get("form", [])
            for i, form in enumerate(forms):
                if not form.startswith("13F-HR"):
                    continue
                acc_raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
                period = rec.get("reportDate", [None] * len(forms))[i]
                if not acc_raw or not period:
                    continue
                accepted = dissemination_ts(to_utc(acc_raw))
                if accepted > end:
                    continue
                accession = rec.get("accessionNumber", [""] * len(forms))[i]
                holdings = self._holdings(cik, accession)
                if holdings:
                    key = pd.Timestamp(period)
                    history[cik][key] = holdings
                    filed_at[(cik, key)] = accepted

        return self._changes(history, filed_at, start, end)

    def _holdings(self, cik: str, accession: str) -> dict[str, float]:
        """Fetch and parse one filing's information table."""
        acc = accession.replace("-", "")
        index = self.client.get(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/index.json"
        )
        if not index:
            return {}
        xml_name = None
        for item in index.get("directory", {}).get("item", []):
            n = item.get("name", "")
            if n.endswith(".xml") and "primary_doc" not in n:
                xml_name = n
                break
        if not xml_name:
            return {}
        body = self.client.get(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{xml_name}", parse="text"
        )
        if not body:
            return {}
        agg: dict[str, float] = defaultdict(float)
        for row in parse_13f_table(body):
            ticker = self.cusip_to_ticker.get(row.get("cusip", "").upper())
            if ticker:
                agg[ticker] += row.get("shares", 0.0)
        return dict(agg)

    def _changes(self, history, filed_at, start, end) -> list[Event]:
        out: list[Event] = []
        for cik, periods in history.items():
            ordered = sorted(periods)
            for prev_p, cur_p in zip(ordered[:-1], ordered[1:], strict=False):
                accepted = filed_at.get((cik, cur_p))
                if accepted is None or not (start <= accepted < end):
                    continue
                prev, cur = periods[prev_p], periods[cur_p]
                for ticker in set(prev) | set(cur):
                    before, after = prev.get(ticker, 0.0), cur.get(ticker, 0.0)
                    if before == 0 and after == 0:
                        continue
                    change = (after - before) / before if before > 0 else 1.0
                    if abs(change) < self.min_change_pct:
                        continue
                    new_position = before == 0
                    exited = after == 0
                    kind = (
                        "institutional.new_position" if new_position
                        else "institutional.exit" if exited
                        else "institutional.increase" if change > 0
                        else "institutional.decrease"
                    )
                    out.append(
                        Event(
                            source=self.name,
                            kind=kind,
                            ticker=ticker,
                            # The report period is when the position existed;
                            # the filing is when we could know. Use the filing.
                            event_ts=to_utc(pd.Timestamp(cur_p).tz_localize("America/New_York")),
                            available_ts=accepted,
                            payload={
                                "id": f"13f:{cik}:{cur_p:%Y%m%d}:{ticker}",
                                "filer_cik": cik,
                                "shares_before": before,
                                "shares_after": after,
                                "change_pct": change,
                                "report_period": str(pd.Timestamp(cur_p).date()),
                                "staleness_days": (accepted - to_utc(pd.Timestamp(cur_p).tz_localize("UTC"))).days,
                            },
                            weight=min(1.0 + abs(change), 3.0) * (1.5 if new_position else 1.0),
                        )
                    )
        return out


#: 13D/G forms and their priors. 13D means intent to influence; 13G means
#: passive. The difference is the entire signal.
STAKE_FORMS: dict[str, tuple[str, float]] = {
    "SC 13D": ("stake.activist", 3.0),
    "SC 13D/A": ("stake.activist_amend", 2.0),
    "SC 13G": ("stake.passive", 0.8),
    "SC 13G/A": ("stake.passive_amend", 0.5),
}


class StakeDisclosures(EventSource):
    """SC 13D/G filings against issuers in the universe.

    Complements :class:`~iai.sources.edgar.EdgarFilings`, which sees these
    forms only when the *issuer* files them. 13D/G are filed by the acquirer
    against the issuer, so they appear on the issuer's filing history but with
    the acquirer as filer -- this class exists to give them their own kind
    namespace and weights rather than being lumped into generic form events.
    """

    name = "stakes"
    default_latency = pd.Timedelta(days=10)

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        start, end = to_utc(start), to_utc(end)
        out: list[Event] = []
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
                    if form not in STAKE_FORMS:
                        continue
                    acc_raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
                    if not acc_raw:
                        continue
                    event_ts = to_utc(acc_raw)
                    available = dissemination_ts(event_ts)
                    if not (start <= available < end):
                        continue
                    kind, weight = STAKE_FORMS[form]
                    out.append(
                        Event(
                            source=self.name,
                            kind=kind,
                            ticker=ticker,
                            event_ts=event_ts,
                            available_ts=available,
                            payload={
                                "id": rec.get("accessionNumber", [""] * len(forms))[i],
                                "form": form,
                            },
                            weight=weight,
                        )
                    )
        return out
