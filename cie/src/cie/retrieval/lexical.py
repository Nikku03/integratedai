"""Lexical search: PostgreSQL full text (default) and an in-memory BM25 for benchmarks."""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cie.core.models import MemoryRecord, Section


def _tsquery(q: str):
    """OR of the query's content terms (BM25-like recall); ts_rank_cd rewards
    records that match more of them. Falls back to websearch syntax when the
    query carries quotes or operators."""
    from cie.retrieval.rerank import query_terms

    if '"' in q or " OR " in q or " -" in q:
        return func.websearch_to_tsquery("english", q)
    terms = [re.sub(r"[^a-z0-9]", "", t) for t in query_terms(q)]
    terms = [t for t in terms if t]
    if not terms:
        return func.plainto_tsquery("english", q)
    return func.to_tsquery("english", " | ".join(terms))


def search_records(session: Session, q: str, base_filter, k: int = 50, at=None) -> list[tuple[uuid.UUID, float]]:
    tsq = _tsquery(q)
    rank = func.ts_rank_cd(MemoryRecord.tsv, tsq, 32)
    stmt = (select(MemoryRecord.id, rank).where(base_filter, MemoryRecord.tsv.op("@@")(tsq))
            .order_by(rank.desc()).limit(k))
    return [(r[0], float(r[1])) for r in session.execute(stmt)]


def search_sections(session: Session, q: str, base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    tsq = _tsquery(q)
    rank = func.ts_rank_cd(Section.tsv, tsq, 32)
    stmt = (select(Section.id, rank).where(base_filter, Section.tsv.op("@@")(tsq)).order_by(rank.desc()).limit(k))
    return [(r[0], float(r[1])) for r in session.execute(stmt)]


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
