"""Lexical search: PostgreSQL full text (default) and an in-memory BM25 for benchmarks."""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from cie.core.models import MemoryRecord, Section


def _terms(q: str) -> list[str]:
    from cie.retrieval.rerank import query_terms

    return [t for t in (re.sub(r"[^a-z0-9]", "", x) for x in query_terms(q)) if t]


def _tsqueries(q: str):
    """Two-tier lexical query. Tier 1: AND of the content terms (a GIN
    intersection, cheap at any scale). Tier 2, only when tier 1 finds fewer
    than half of k: OR of the terms ranked by ts_rank_cd (BM25-like recall,
    but it ranks every partial match and grows with the corpus)."""
    if '"' in q or " OR " in q or " -" in q:
        t = func.websearch_to_tsquery("english", q)
        return [t]
    from cie.retrieval.rerank import _GENERIC

    terms = _terms(q)
    if not terms:
        return [func.plainto_tsquery("english", q)]
    tiers = [func.to_tsquery("english", " & ".join(terms))]
    informative = [t for t in terms if t not in _GENERIC]
    if informative and len(informative) < len(terms):
        tiers.append(func.to_tsquery("english", " & ".join(informative)))
    if len(informative or terms) > 1:
        tiers.append(func.to_tsquery("english", " | ".join(informative or terms)))
    return tiers


def _search(session: Session, model, q: str, base_filter, k: int) -> list[tuple[uuid.UUID, float]]:
    out: list[tuple[uuid.UUID, float]] = []
    seen: set = set()
    tiers = _tsqueries(q)
    for tier, tsq in enumerate(tiers):
        rank = func.ts_rank_cd(model.tsv, tsq, 32)
        stmt = (select(model.id, rank).where(base_filter, model.tsv.op("@@")(tsq)).order_by(rank.desc()).limit(k))
        last = tier == len(tiers) - 1 and len(tiers) > 1
        try:
            if last:
                # the partial-match tier ranks every row that shares a term; bound it so a common word cannot stall retrieval
                session.execute(text("SAVEPOINT lex_or"))
                session.execute(text("SET LOCAL statement_timeout = '1500ms'"))
            rows = session.execute(stmt).all()
            if last:
                session.execute(text("SET LOCAL statement_timeout = 0"))
                session.execute(text("RELEASE SAVEPOINT lex_or"))
        except Exception:  # noqa: BLE001 - a bounded timeout is an accepted outcome here
            session.execute(text("ROLLBACK TO SAVEPOINT lex_or"))
            rows = []
        for rid, sc in rows:
            if rid not in seen:
                seen.add(rid)
                out.append((rid, float(sc) + (2.0 - tier) * 0.5))  # fuller matches rank above partial ones
        if len(out) >= max(5, k // 10):  # enough full-term matches: skip the expensive partial-match tier
            break
    return out[:k]


def search_records(session: Session, q: str, base_filter, k: int = 50, at=None) -> list[tuple[uuid.UUID, float]]:
    return _search(session, MemoryRecord, q, base_filter, k)


def search_sections(session: Session, q: str, base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    return _search(session, Section, q, base_filter, k)


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
