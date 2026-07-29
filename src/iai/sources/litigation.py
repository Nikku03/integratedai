"""Federal litigation via CourtListener / RECAP.

What this is good for
---------------------
Securities class actions, patent suits, antitrust, and government enforcement
are slow-moving, publicly docketed, and systematically under-priced in the
first days after filing for small and mid caps. The filing of a complaint is a
discrete, timestamped, public event -- exactly the shape this pipeline wants.

What this is not good for
-------------------------
State courts, which are where a lot of commercial disputes actually live, are
largely absent from RECAP. Coverage is a function of whether *someone* bought
the document off PACER and contributed it, so absence of a docket entry is
weak evidence of absence of litigation. Treat these features as one-sided:
a hit is informative, a miss is not.

Point-in-time handling
----------------------
``date_filed`` is the event. Availability is materially later and uneven:
RECAP ingests when a subscriber pulls the document, so the practical lag runs
from minutes (heavily-watched dockets) to days. :data:`RECAP_LAG` encodes a
deliberately pessimistic default. If you upgrade to a direct PACER feed, drop
it to an hour and re-run -- the delta between those two backtests is a good
estimate of how much of the edge is pure speed.
"""

from __future__ import annotations

import logging

import pandas as pd

from ..core.types import Event, to_utc
from ..core.universe import normalize_name
from .base import EventSource

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
DOCKET_URL = "https://www.courtlistener.com/api/rest/v4/dockets/"

#: Assumed delay between a complaint being filed and it appearing in RECAP.
RECAP_LAG = pd.Timedelta(days=1)

#: Nature-of-suit codes worth distinguishing. The number is the prior weight.
NATURE_OF_SUIT: dict[str, tuple[str, float]] = {
    "850": ("securities", 3.0),
    "410": ("antitrust", 2.5),
    "830": ("patent", 2.0),
    "820": ("copyright", 1.2),
    "840": ("trademark", 1.0),
    "365": ("product_liability", 2.2),
    "360": ("personal_injury", 1.2),
    "422": ("bankruptcy_appeal", 2.5),
    "710": ("labor", 0.8),
    "890": ("statutory_action", 1.0),
}

#: Cause-of-action substrings that upgrade severity regardless of NOS code.
CAUSE_FLAGS: dict[str, tuple[str, float]] = {
    "securities fraud": ("securities_fraud", 3.0),
    "15:78": ("exchange_act", 3.0),
    "15:77": ("securities_act", 2.8),
    "racketeer": ("rico", 2.8),
    "false claims": ("false_claims", 2.5),
    "antitrust": ("antitrust", 2.5),
    "patent infringement": ("patent", 2.0),
}


class CourtListenerDockets(EventSource):
    """Search RECAP dockets by party name and emit one event per matched case."""

    name = "litigation"
    default_latency = RECAP_LAG

    def __init__(self, *args, page_size: int = 50, max_pages: int = 4, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.page_size = page_size
        self.max_pages = max_pages
        token = self.cfg.data.courtlistener_token
        self.headers = {"Authorization": f"Token {token}"} if token else {}
        if not token:
            # The anonymous tier works but is throttled to roughly a query a
            # second and omits some fields. Fine for research, not for a daily
            # sweep of 3,000 issuers.
            log.info("no COURTLISTENER_TOKEN set; using anonymous tier (throttled)")

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": "" if self.headers else "anonymous tier: heavily rate limited",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        start, end = to_utc(start), to_utc(end)
        events: list[Event] = []
        for ticker in self.universe.tickers:
            rec = self.universe.by_ticker[ticker]
            events.extend(self._for_company(ticker, rec["name"], start, end))
        return events

    def _for_company(
        self, ticker: str, company: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> list[Event]:
        # Search on the filed date, then filter on availability, because the
        # API has no notion of "when did this become visible".
        search_start = (start - RECAP_LAG - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        search_end = end.strftime("%Y-%m-%d")
        out: list[Event] = []
        cursor: str | None = None

        for _ in range(self.max_pages):
            params = {
                "type": "r",
                "q": f'party_name:("{company}")',
                "filed_after": search_start,
                "filed_before": search_end,
                "page_size": self.page_size,
                "order_by": "dateFiled desc",
            }
            if cursor:
                params["cursor"] = cursor
            blob = self.client.get(SEARCH_URL, params=params, headers=self.headers)
            if not blob:
                break
            for res in blob.get("results", []):
                ev = self._to_event(ticker, company, res, start, end)
                if ev:
                    out.append(ev)
            nxt = blob.get("next")
            if not nxt:
                break
            cursor = nxt.split("cursor=")[-1].split("&")[0] if "cursor=" in nxt else None
            if not cursor:
                break
        return out

    def _to_event(
        self,
        ticker: str,
        company: str,
        res: dict,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> Event | None:
        filed = res.get("dateFiled") or res.get("date_filed")
        if not filed:
            return None
        event_ts = to_utc(pd.Timestamp(filed).tz_localize("America/New_York").replace(hour=17))
        available = event_ts + RECAP_LAG
        if not (start <= available < end):
            return None

        # Guard against the search engine's fuzzy party matching pulling in a
        # different company with a similar name. An unfiltered party search for
        # "Apple Inc." returns suits against "Apple Valley Sanitation".
        parties = " ".join(str(p) for p in (res.get("party") or []))
        if parties and normalize_name(company) not in normalize_name(parties):
            case_name = str(res.get("caseName", ""))
            if normalize_name(company) not in normalize_name(case_name):
                return None

        nos = str(res.get("suitNature") or res.get("nature_of_suit") or "").strip()
        nos_code = nos.split()[0] if nos and nos.split()[0].isdigit() else ""
        kind, weight = NATURE_OF_SUIT.get(nos_code, ("other", 1.0))

        cause = str(res.get("cause", "")).lower()
        for needle, (flag, w) in CAUSE_FLAGS.items():
            if needle in cause:
                kind, weight = flag, max(weight, w)
                break

        # Defendant-side is materially worse news than plaintiff-side. The
        # search payload does not label sides reliably, so infer from the
        # caption: "X v. Y" puts the defendant second.
        case_name = str(res.get("caseName", ""))
        role = "unknown"
        if " v. " in case_name or " v " in case_name:
            head, _, tail = case_name.partition(" v")
            norm = normalize_name(company)
            if norm and norm in normalize_name(tail):
                role = "defendant"
            elif norm and norm in normalize_name(head):
                role = "plaintiff"
        if role == "plaintiff":
            weight *= 0.5

        return Event(
            source=self.name,
            kind=f"docket.{kind}",
            ticker=ticker,
            event_ts=event_ts,
            available_ts=available,
            payload={
                "id": str(res.get("docket_id") or res.get("id") or case_name),
                "case_name": case_name,
                "court": res.get("court", ""),
                "nature_of_suit": nos,
                "cause": res.get("cause", ""),
                "role": role,
                "docket_number": res.get("docketNumber", ""),
            },
            weight=weight,
        )
