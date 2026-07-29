"""Identifier resolution: ticker <-> CIK <-> company name, plus entity aliases.

Almost every failure mode in alt-data is an identifier failure. The complaint
names "Alphabet Inc." but the ticker is GOOGL; the bill of lading says "SAMSUNG
ELECTRONICS AMERICA INC" and the listed parent is a Korean issuer with no US
line; the jet is registered to a Delaware LLC that shares nothing with the
operating company's name. Everything here is best-effort and explicitly
reports what it could not match, because a silently unmatched entity is an
event that quietly never reaches the model.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .http import HttpClient

log = logging.getLogger(__name__)

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"

_SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|lp|plc|holdings?|"
    r"group|sa|nv|ag|se|spa|pte|pty|kk|gmbh|international|technologies|technology|"
    r"pharmaceuticals?|therapeutics|labs?|laboratories)\b",
    re.I,
)
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Aggressively normalise a legal entity name for fuzzy matching."""
    s = name.lower()
    s = s.replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    s = _SUFFIXES.sub(" ", s)
    return _WS.sub(" ", s).strip()


@dataclass
class Universe:
    """Bidirectional identifier map for a set of issuers."""

    by_ticker: dict[str, dict] = field(default_factory=dict)
    by_cik: dict[str, str] = field(default_factory=dict)
    by_name: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)

    @property
    def tickers(self) -> list[str]:
        return sorted(self.by_ticker)

    def cik(self, ticker: str) -> str | None:
        rec = self.by_ticker.get(ticker.upper())
        return rec["cik"] if rec else None

    def ticker_for_cik(self, cik: str) -> str | None:
        return self.by_cik.get(str(cik).lstrip("0").zfill(10))

    def resolve_name(self, name: str, *, record_misses: bool = True) -> str | None:
        """Map a free-text company name to a ticker.

        Exact normalised match first, then a containment match that requires the
        candidate to be at least two tokens long — "co" matching sixty issuers
        is worse than no match at all.
        """
        norm = normalize_name(name)
        if not norm:
            return None
        if norm in self.by_name:
            return self.by_name[norm]
        tokens = norm.split()
        if len(tokens) >= 2:
            for cand, tkr in self.by_name.items():
                if len(cand) >= 6 and (cand in norm or norm in cand):
                    return tkr
        if record_misses:
            self.unresolved.append(name)
        return None

    def add(self, ticker: str, cik: str, name: str, **extra) -> None:
        ticker = ticker.upper().strip()
        cik = str(cik).lstrip("0").zfill(10)
        self.by_ticker[ticker] = {"ticker": ticker, "cik": cik, "name": name, **extra}
        self.by_cik.setdefault(cik, ticker)
        self.by_name.setdefault(normalize_name(name), ticker)

    def subset(self, tickers: list[str]) -> Universe:
        out = Universe()
        for t in tickers:
            rec = self.by_ticker.get(t.upper())
            if rec:
                out.add(**rec)
        return out

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(list(self.by_ticker.values()), indent=1))

    @classmethod
    def load(cls, path: Path) -> Universe:
        uni = cls()
        for rec in json.loads(Path(path).read_text()):
            uni.add(**rec)
        return uni

    @classmethod
    def from_sec(cls, client: HttpClient, limit: int | None = None) -> Universe:
        """Build from the SEC's canonical ticker->CIK mapping (free, complete)."""
        blob = client.get(SEC_TICKER_URL)
        uni = cls()
        if not blob:
            log.error("could not fetch SEC ticker map; universe is empty")
            return uni
        records = blob.values() if isinstance(blob, dict) else blob
        for i, rec in enumerate(records):
            if limit is not None and i >= limit:
                break
            uni.add(
                ticker=str(rec["ticker"]),
                cik=str(rec["cik_str"]),
                name=str(rec["title"]),
            )
        log.info("universe: %d issuers from SEC", len(uni.by_ticker))
        return uni
