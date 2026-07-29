"""Partner and counterparty graph, derived rather than purchased.

The idea
--------
When issuer A files an 8-K Item 1.01 announcing a collaboration with issuer B,
the market almost always reprices A immediately -- it is A's filing, A's press
release, A's ticker in the headline. B is repriced late and incompletely,
especially when B is the larger or less-followed name, or when B never files
anything at all because the deal is immaterial to B's revenue but material to
B's option value.

So the tradable object is the *spillover*: A's disclosed catalyst becomes an
event on B's ticker, timestamped to when A disclosed it.

How the graph is built
----------------------
Two passes, neither requiring a paid vendor:

1. **Co-mention.** Pull the primary document of every catalyst filing, extract
   candidate company names, resolve them against the universe. A resolved name
   that is not the filer is a counterparty.
2. **Persistence.** A pair seen once is noise; a pair seen repeatedly across
   quarters is a real commercial relationship. Edge weight is a decayed count,
   so a decade-old one-off decays out while an active supply relationship
   stays warm.

Point-in-time handling
----------------------
The graph is rebuilt as of each date from edges observed strictly before it.
:meth:`PartnerGraph.as_of` enforces this. Building one graph from the full
history and applying it to the whole backtest would leak the future into the
past in the most seductive way possible -- it "obviously" works.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

from ..core.types import Event, to_utc
from ..core.universe import Universe
from .base import EventSource

log = logging.getLogger(__name__)

#: Capitalised multi-word spans ending in a corporate suffix. Deliberately
#: conservative: recall matters less than not creating phantom edges.
_ENTITY_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&.\-]*\s+){0,4}[A-Z][A-Za-z0-9&.\-]*"
    r"\s*(?:Inc|Incorporated|Corp|Corporation|Company|Ltd|Limited|LLC|L\.L\.C\.|PLC|N\.V\.|S\.A\.|AG|SE)\b\.?)"
)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE_MAX_LEN = 80


def extract_entities(html_or_text: str, limit: int = 400) -> list[str]:
    """Pull candidate legal entity names out of a filing body."""
    text = _TAG_RE.sub(" ", html_or_text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    seen: dict[str, None] = {}
    for match in _ENTITY_RE.finditer(text):
        name = match.group(1).strip(" .")
        if 4 <= len(name) <= _ENTITY_RE_MAX_LEN:
            seen.setdefault(name, None)
        if len(seen) >= limit:
            break
    return list(seen)


@dataclass
class PartnerGraph:
    """Time-stamped directed edges between tickers."""

    #: (src, dst) -> list of (observed_ts, weight)
    edges: dict[tuple[str, str], list[tuple[pd.Timestamp, float]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def add(self, src: str, dst: str, ts: pd.Timestamp, weight: float = 1.0) -> None:
        if src == dst:
            return
        self.edges[(src.upper(), dst.upper())].append((to_utc(ts), float(weight)))

    def as_of(self, ts: pd.Timestamp, halflife_days: float = 180.0) -> dict[str, dict[str, float]]:
        """Decayed adjacency using only edges observed strictly before ``ts``."""
        ts = to_utc(ts)
        adj: dict[str, dict[str, float]] = defaultdict(dict)
        for (src, dst), obs in self.edges.items():
            total = 0.0
            for obs_ts, w in obs:
                if obs_ts >= ts:
                    continue
                age_days = (ts - obs_ts).total_seconds() / 86400.0
                total += w * 0.5 ** (age_days / halflife_days)
            if total > 0:
                adj[src][dst] = total
        return adj

    def neighbours(self, ticker: str, ts: pd.Timestamp, halflife_days: float = 180.0) -> dict[str, float]:
        return self.as_of(ts, halflife_days).get(ticker.upper(), {})

    def to_frame(self) -> pd.DataFrame:
        rows = [
            {"src": s, "dst": d, "observed_ts": ts, "weight": w}
            for (s, d), obs in self.edges.items()
            for ts, w in obs
        ]
        return pd.DataFrame(rows, columns=["src", "dst", "observed_ts", "weight"])

    @classmethod
    def from_frame(cls, df: pd.DataFrame) -> PartnerGraph:
        g = cls()
        for row in df.itertuples(index=False):
            g.add(row.src, row.dst, row.observed_ts, row.weight)
        return g


#: Filing kinds whose bodies are worth downloading for counterparty extraction.
DEAL_KINDS = {
    "8-K.1.01",
    "8-K.1.02",
    "8-K.2.01",
    "8-K.5.01",
    "catalyst.collaboration",
    "catalyst.license",
    "catalyst.supply",
    "catalyst.distribution",
    "catalyst.joint_venture",
    "catalyst.merger",
}


class PartnerSpillover(EventSource):
    """Turn one issuer's disclosed deal into a catalyst on its counterparty.

    Consumes an already-collected event frame rather than fetching from
    scratch, because the expensive part (finding the filings) has been done by
    :mod:`iai.sources.edgar`. This source only downloads the bodies of filings
    that plausibly name a counterparty.
    """

    name = "partners"

    def __init__(
        self,
        *args,
        base_events: pd.DataFrame | None = None,
        graph: PartnerGraph | None = None,
        max_documents: int = 500,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.base_events = base_events if base_events is not None else pd.DataFrame()
        self.graph = graph or PartnerGraph()
        self.max_documents = max_documents

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if self.base_events.empty:
            log.info("partners: no base events supplied, nothing to derive")
            return []
        start, end = to_utc(start), to_utc(end)
        df = self.base_events
        mask = df["kind"].isin(DEAL_KINDS) & df["available_ts"].between(start, end, inclusive="left")
        deals = df.loc[mask].head(self.max_documents)

        out: list[Event] = []
        for row in deals.itertuples(index=False):
            url = (row.payload or {}).get("url", "")
            if not url:
                continue
            body = self.client.get(url, parse="text")
            if not body:
                continue
            for name in extract_entities(body):
                counterparty = self.universe.resolve_name(name, record_misses=False)
                if not counterparty or counterparty == row.ticker:
                    continue
                self.graph.add(row.ticker, counterparty, row.available_ts, weight=1.0)
                out.append(
                    Event(
                        source=self.name,
                        kind=f"spillover.{row.kind}",
                        ticker=counterparty,
                        event_ts=row.event_ts,
                        # The counterparty event is knowable exactly when the
                        # filer's document is -- not a second sooner.
                        available_ts=row.available_ts,
                        payload={
                            "id": f"{(row.payload or {}).get('id', '')}:{counterparty}",
                            "origin_ticker": row.ticker,
                            "origin_kind": row.kind,
                            "matched_name": name,
                            "url": url,
                        },
                        # Spillover is a weaker signal than the primary
                        # disclosure: the counterparty may be immaterial to the
                        # deal, and half the time the market has already
                        # connected the dots.
                        weight=float(row.weight) * 0.5,
                    )
                )
        return out


def build_graph_from_events(
    events: pd.DataFrame, universe: Universe, client, max_documents: int = 2000
) -> PartnerGraph:
    """Offline graph construction over a historical event frame."""
    graph = PartnerGraph()
    deals = events[events["kind"].isin(DEAL_KINDS)].head(max_documents)
    for row in deals.itertuples(index=False):
        url = (row.payload or {}).get("url", "")
        if not url:
            continue
        body = client.get(url, parse="text")
        if not body:
            continue
        for name in extract_entities(body):
            other = universe.resolve_name(name, record_misses=False)
            if other and other != row.ticker:
                graph.add(row.ticker, other, row.available_ts)
    return graph
