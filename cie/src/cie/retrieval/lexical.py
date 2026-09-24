"""Lexical search: PostgreSQL full text (default) and an in-memory BM25 for benchmarks."""

from __future__ import annotations

import math
import re
import time
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from cie.core.models import MemoryRecord, Section
from cie.retrieval.bounded import run_bounded


def _terms(q: str) -> list[str]:
    from cie.retrieval.rerank import query_terms

    return [t for t in (re.sub(r"[^a-z0-9]", "", x) for x in query_terms(q)) if t]


def _anchor(q: str, terms: list[str]) -> list[str]:
    """Tokens of the most specific capitalised span in the query (the longest one whose
    words are all content terms): "Northwind Logistics 37" in "...the Northwind Logistics 37
    contract?". A name says *where* the answer lives; the anchored tier searches only there."""
    from cie.retrieval.exact import _capitalised_spans
    from cie.retrieval.rerank import _GENERIC

    best: list[str] = []
    for span in _capitalised_spans(q):
        toks = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in span.split()]
        toks = [t for t in toks if t in terms and t not in _GENERIC]
        if len(toks) > len(best):
            best = toks
    return best


COMMON_ROWS = 5000  # a lexeme expected in more rows than this is weight, not evidence: it does not discriminate
PARTIAL_TERMS = 6
TIER_MS = 4000  # time limit of one full-match tier query
PARTIAL_TIER_MS = 1500  # time limit of the partial (OR) tier  # the partial-match tier ORs at most this many terms, the rarest when statistics say which
_STATS_TTL = 300.0
_stats_cache: dict[tuple[str, str, str], tuple[float, dict[str, float]]] = {}
_lexeme_cache: dict[str, str] = {}


def common_lexemes(session: Session, table: str, tenant_id: uuid.UUID | None = None) -> dict[str, float]:
    """Expected number of rows per lexeme *within the tenant*, from the planner's own
    statistics: ``pg_stats.most_common_elems`` gives the fraction of rows holding a
    lexeme, ``pg_class.reltuples`` the row estimate, and the ``tenant_id`` column's
    most-common-values list the tenant's share of the table (a tenant absent from that
    list gets the share left over by the listed ones, an upper bound). Free, corpus-derived
    IDF: it is the selectivity the planner assigns to ``tenant_id = X AND tsv @@ lexeme``.
    Empty until the table has been analysed. The criterion is absolute rows, not a
    fraction: in a 300-record tenant a word in 5% of rows is still a handful of rows,
    while at a million it is a scan."""
    key = (str(session.get_bind().url), table, str(tenant_id))
    now = time.monotonic()
    hit = _stats_cache.get(key)
    if hit and now - hit[0] < _STATS_TTL:
        return hit[1]
    try:
        rows = session.execute(text(
            "WITH n AS (SELECT reltuples AS rows FROM pg_class WHERE relname = :t), "
            "share AS (SELECT COALESCE(most_common_freqs[array_position(most_common_vals::text::text[], :tenant)], "
            "  1.0 - (SELECT COALESCE(sum(f), 0) FROM unnest(most_common_freqs) AS f)) AS s "
            "  FROM pg_stats WHERE tablename = :t AND attname = 'tenant_id') "
            "SELECT e, f * n.rows * COALESCE((SELECT s FROM share), 1.0) FROM pg_stats, n, "
            "unnest(most_common_elems::text::text[], "
            "most_common_elem_freqs[1:array_length(most_common_elems::text::text[], 1)]) AS u(e, f) "
            "WHERE tablename = :t AND attname = 'tsv'"), {"t": table, "tenant": str(tenant_id) if tenant_id else ""}).all()
        expected = {e: float(n) for e, n in rows}
    except Exception:  # noqa: BLE001 - statistics are an optimisation, never a dependency
        session.rollback()
        expected = {}
    _stats_cache[key] = (now, expected)
    return expected


def lexemes(session: Session, terms: list[str]) -> dict[str, str]:
    """Each term's lexeme under the same configuration ``to_tsquery`` uses (stop words map to '')."""
    missing = [t for t in terms if t not in _lexeme_cache]
    if missing:
        rows = session.execute(text("SELECT w, array_to_string(tsvector_to_array(to_tsvector('english', w)), ' ') "
                                    "FROM unnest(CAST(:w AS text[])) AS w"), {"w": missing}).all()
        if len(_lexeme_cache) > 20000:
            _lexeme_cache.clear()
        for w, lx in rows:
            _lexeme_cache[w] = lx or ""
    return {t: _lexeme_cache.get(t, t) for t in terms}


def _tsqueries(q: str, session: Session | None = None, table: str = "memory_records",
               tenant_id: uuid.UUID | None = None) -> list[tuple[Any, str]]:
    """Lexical query tiers, cheapest and strictest first; each is (tsquery, kind).

    ``all``: AND of every content term (a GIN intersection, cheap at any scale).
    ``informative``: AND of the informative terms (drops generic words such as "agreement").
    ``anchored``: AND of the named entity's tokens with an OR of the remaining content
       terms. The name is rare, so the intersection stays cheap, while the answer
       need not repeat every word of the question ("notice period" vs "days written notice").
    ``partial``: OR of the informative terms that are rare in this table (planner
       statistics; a word expected in thousands of rows only adds cost, not evidence),
       bounded by a statement timeout. A record rarely repeats the name of its
       document ("monthly fee of USD 140,000" says nothing about Northwind), so this
       tier always runs; it is skipped only when every term is common."""
    if '"' in q or " OR " in q or " -" in q:
        return [(func.websearch_to_tsquery("english", q), "all")]
    from cie.retrieval.rerank import _GENERIC

    terms = _terms(q)
    if not terms:
        return [(func.plainto_tsquery("english", q), "all")]
    tiers: list[tuple[Any, str]] = [(func.to_tsquery("english", " & ".join(terms)), "all")]
    informative = [t for t in terms if t not in _GENERIC]
    if informative and len(informative) < len(terms):
        tiers.append((func.to_tsquery("english", " & ".join(informative)), "informative"))
    anchor = _anchor(q, terms)
    content = [t for t in informative if t not in anchor]
    if anchor and content:
        tiers.append((func.to_tsquery("english", " & ".join(anchor) + " & (" + " | ".join(content) + ")"), "anchored"))
    partial = informative or terms
    if session is not None:
        expected = common_lexemes(session, table, tenant_id)
        if expected:
            lx = lexemes(session, partial)
            partial = [t for t in partial if expected.get(lx.get(t, t), 0.0) < COMMON_ROWS]
            partial = sorted(partial, key=lambda t: expected.get(lx.get(t, t), 0.0))  # rarest first
    partial = partial[:PARTIAL_TERMS]  # a long question is not a longer OR: the rarest words carry it
    if len(partial) > 1 or (partial and partial != (informative or terms)):
        tiers.append((func.to_tsquery("english", " | ".join(partial)), "partial"))
    return tiers


def _search(session: Session, model, q: str, base_filter, k: int, tenant_id: uuid.UUID | None = None) -> list[tuple[uuid.UUID, float]]:
    out: list[tuple[uuid.UUID, float]] = []
    seen: set = set()
    tiers = _tsqueries(q, session, model.__tablename__, tenant_id)
    for tier, (tsq, kind) in enumerate(tiers):
        bounded = kind == "partial"
        if bounded and len(out) >= k:
            break
        rank = func.ts_rank_cd(model.tsv, tsq, 32)
        stmt = (select(model.id, rank).where(base_filter, model.tsv.op("@@")(tsq)).order_by(rank.desc()).limit(k))
        # every tier ranks all rows that match it, which at millions of rows can take long for common words: each tier
        # has its own time limit (the OR tier the tightest), and a tier that runs out contributes nothing
        rows = run_bounded(session, stmt, PARTIAL_TIER_MS if bounded else TIER_MS, name="lex_tier") or []
        for rid, sc in rows:
            if rid not in seen:
                seen.add(rid)
                out.append((rid, float(sc) + (len(tiers) - tier) * 0.5))  # fuller matches rank above partial ones
    return out[:k]


def search_records(session: Session, q: str, base_filter, k: int = 50, at=None, tenant_id: uuid.UUID | None = None) -> list[tuple[uuid.UUID, float]]:
    return _search(session, MemoryRecord, q, base_filter, k, tenant_id)


def search_sections(session: Session, q: str, base_filter, k: int = 50, tenant_id: uuid.UUID | None = None) -> list[tuple[uuid.UUID, float]]:
    return _search(session, Section, q, base_filter, k, tenant_id)


class BM25Index:
    """Plain Okapi BM25 over in-memory documents (benchmark arm and offline fallback)."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: dict[Any, Counter] = {}
        self.len: dict[Any, int] = {}
        self.df: Counter = Counter()
        self.avg = 0.0

    @staticmethod
    def tokens(text: str) -> list[str]:
        return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1]

    def add(self, doc_id: Any, text: str) -> None:
        toks = self.tokens(text)
        c = Counter(toks)
        self.docs[doc_id] = c
        self.len[doc_id] = len(toks)
        for t in c:
            self.df[t] += 1
        self.avg = sum(self.len.values()) / max(len(self.len), 1)

    def search(self, q: str, k: int = 50) -> list[tuple[Any, float]]:
        qt = self.tokens(q)
        n = len(self.docs)
        scores: dict[Any, float] = {}
        for t in set(qt):
            if t not in self.df:
                continue
            idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            for d, c in self.docs.items():
                tf = c.get(t)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.len[d] / max(self.avg, 1))
                scores[d] = scores.get(d, 0.0) + idf * tf * (self.k1 + 1) / denom
        return sorted(scores.items(), key=lambda kv: -kv[1])[:k]


class OpenSearchIndex:  # pragma: no cover - adapter skeleton
    """NOT IMPLEMENTED. Placeholder documenting the swap point for OpenSearch/Elasticsearch.
    Raises on use so it can never silently return fake results."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("OpenSearch lexical index is not implemented in this build; see docs/ROADMAP.md")
