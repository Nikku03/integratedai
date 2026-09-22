"""Heuristic reranker. Combines fusion score with type prior, verification,
confidence, recency, superseded status and a hub penalty.

This is not a cross-encoder. It is deterministic and cheap; the interface
(``rerank(candidates, intent) -> ordered``) is where a learned reranker plugs in.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cie.core.models import MemoryRecord, VerificationStatus
from cie.core.util import utcnow
from cie.retrieval.intent import Intent


@dataclass
class Candidate:
    record: MemoryRecord | None
    section: Any | None
    fused: float
    sources: dict[str, Any] = field(default_factory=dict)
    horizon: int = 0
    via: str | None = None
    degree: int = 0
    final: float = 0.0
    support: float = 0.0  # model-independent evidence strength in [0, 1]
    reasons: dict[str, float] = field(default_factory=dict)

    @property
    def id(self):
        return self.record.id if self.record is not None else self.section.id

    @property
    def kind(self) -> str:
        return "record" if self.record is not None else "section"


def _doc_id(c: Candidate):
    return c.record.source_document_id if c.record is not None else c.section.document_id


_VERIF = {VerificationStatus.verified: 0.15, VerificationStatus.unverified: 0.0,
          VerificationStatus.disputed: -0.1, VerificationStatus.rejected: -0.5}


_STOP = {"what", "when", "who", "which", "how", "does", "the", "and", "for", "with", "about", "this", "that",
         "are", "was", "were", "have", "has", "from", "into", "under", "according", "say", "says", "did", "will",
         "current", "currently", "latest", "history", "list", "all", "any", "much", "many", "date", "there", "their"}


def query_terms(query: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{3,}", query.lower()) if w not in _STOP]


_GENERIC = {"supplier", "agreement", "company", "contract", "document", "party", "parties", "services", "service", "acme"}


def _key(t: str) -> str:
    """Prefix key so inflections match ('payments'~'payment', 'terminate'~'termination')
    without conflating short stems ('receive' vs 'receipt')."""
    return t[:6] if len(t) > 6 else t


def entity_terms(query: str) -> set[str]:
    """Lower-cased tokens of capitalised spans in the query (names of documents,
    suppliers, people). They identify *where* to look, not *what* is asked."""
    from cie.retrieval.exact import _capitalised_spans

    out = set()
    for span in _capitalised_spans(query):
        out.update(w.lower() for w in span.split() if len(w) >= 3)
    return out


def prefix_index(text: str) -> set[str]:
    """Word-prefix set (lengths 3..6) so query terms match whole-word inflections
    but never substrings inside other words ('rating' must not match 'Operating')."""
    out: set[str] = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        for k in range(3, 7):
            if len(w) >= k:
                out.add(w[:k])
    return out


def coverage(query: str, text: str | set[str], weights: dict[str, float] | None = None, exclude: set[str] | None = None,
             present: set[str] | None = None) -> float:
    """Weighted fraction of the query's *informative* content words present in
    ``text``. Weights are IDF over the candidate pool; entity and generic terms
    are excluded when other content terms exist. Terms that no candidate
    contains at all (``present`` given and term not in it) are left out of the
    denominator: they cannot discriminate between candidates. If *no*
    informative term is present anywhere the question is unanswerable from the
    pool and coverage is 0 for every candidate. Independent of the embedding model."""
    terms = query_terms(query)
    exclude = exclude or set()
    content = [t for t in terms if t not in exclude and t not in _GENERIC]
    if content:
        terms = content
    if not terms:
        return 1.0
    if present is not None:
        terms = [t for t in terms if t in present]
        if not terms:
            return 0.0
    hay = text if isinstance(text, set) else prefix_index(text)
    w = weights or {}
    tw = sorted((w.get(t, 1.0) for t in terms), reverse=True)
    total = sum(tw[:6])  # a record covering the six most informative present terms counts as full support
    hit = sum(w.get(t, 1.0) for t in terms if _key(t) in hay)
    return min(1.0, hit / total) if total else 0.0


def _text_of(c: Candidate) -> str:
    if c.record is not None:
        return f"{c.record.summary} {c.record.detail} {c.record.content}"
    return f"{c.section.title or ''} {c.section.text}"


def idf_weights(query: str, cands: list[Candidate], indexes: list[set[str]] | None = None) -> tuple[dict[str, float], set[str]]:
    """IDF per query term over the candidate pool, and the set of terms present in at least one candidate."""
    terms = query_terms(query)
    n = max(len(cands), 1)
    idx = indexes if indexes is not None else [prefix_index(_text_of(c)) for c in cands]
    df = {t: sum(1 for x in idx if _key(t) in x) for t in terms}
    return {t: math.log(1.0 + n / (1 + df[t])) for t in terms}, {t for t, d in df.items() if d > 0}


def support_of(c: Candidate, query: str, weights: dict[str, float] | None = None, exclude: set[str] | None = None,
               present: set[str] | None = None, index: set[str] | None = None) -> float:
    """Evidence support in [0, 1]: exact-lookup hit or informative-term coverage.
    Vector similarity is deliberately *not* support: neural cosine scores are
    high for topically related text that does not answer the question, which
    is exactly the failure mode that produces confident wrong answers."""
    cov = coverage(query, index if index is not None else _text_of(c), weights, exclude, present)
    exact = 1.0 if "exact" in c.sources and c.sources["exact"][1] >= 3.0 else 0.0
    return max(exact, cov)


def rerank(cands: list[Candidate], intent: Intent, query: str = "", now: datetime | None = None,
           hub_threshold: int = 40, doc_titles: dict[Any, str] | None = None,
           doc_types: dict[Any, str] | None = None, vector_threshold: float = 0.8) -> list[Candidate]:
    now = now or utcnow()
    doc_types = doc_types or {}
    asks_draft = "draft" in query.lower()
    max_fused = max((c.fused for c in cands), default=1.0) or 1.0
    indexes = [prefix_index(_text_of(c)) for c in cands]
    weights, present = idf_weights(query, cands, indexes) if query else ({}, set())
    ents = entity_terms(query) if query else set()
    doc_titles = doc_titles or {}
    # does any candidate's document carry a name from the query? then the query targets specific documents
    targeted = bool(ents) and any(any(e in (doc_titles.get(_doc_id(c)) or "").lower() for e in ents) for c in cands)
    for c, index in zip(cands, indexes, strict=True):
        base = c.fused / max_fused
        c.support = round(support_of(c, query, weights, ents, present, index), 3) if query else 1.0
        # retrieval rank and bonuses matter only insofar as the item actually covers the question
        reasons = {"fused": round(base * (0.35 + 0.65 * c.support), 4)}
        bonus_scale = 0.3 + 0.7 * c.support
        if ents:
            title = (doc_titles.get(_doc_id(c)) or "").lower()
            text = _text_of(c).lower()
            if any(e in title for e in ents):
                reasons["document_affinity"] = round(0.3 * bonus_scale, 4)
            elif any(e in text for e in ents):
                reasons["entity_affinity"] = round(0.15 * bonus_scale, 4)
            elif targeted:
                reasons["other_document"] = -0.1  # mild: the named entity may be a topic, not the file holding the answer
        is_draft = doc_types.get(_doc_id(c), "").lower() in ("draft", "superseded", "template")
        if is_draft and not asks_draft:
            reasons["draft_document"] = -0.3
        elif is_draft and asks_draft:
            reasons["draft_requested"] = 0.3
        if c.record is not None:
            r = c.record
            if intent.type_hints and r.type.value in intent.type_hints:
                reasons["type_match"] = round(0.25 * bonus_scale, 4)
            if r.type.value in ("organization", "person", "entity") and not intent.wants_entities:
                reasons["entity_not_asked"] = -0.25
            reasons["verification"] = _VERIF.get(r.verification, 0.0)
            reasons["confidence"] = 0.2 * (float(r.confidence) - 0.5)
            if r.superseded_by_id is not None:
                reasons["superseded"] = -0.05 if intent.include_history else -0.6
            if intent.kind == "temporal" and r.valid_from:
                age_days = max((now - r.valid_from).days, 0)
                reasons["recency"] = 0.15 * math.exp(-age_days / 365.0)
            if c.degree > hub_threshold:
                reasons["hub_penalty"] = -0.1 * math.log10(c.degree / hub_threshold + 1)
            if r.type.value == "document":
                reasons["document_record"] = -0.35  # prefer specific facts over whole-document stubs
        else:
            reasons["section"] = -0.05
        if c.horizon:
            reasons["graph_horizon"] = -0.08 * c.horizon
        c.reasons = reasons
        c.final = sum(reasons.values())
    return sorted(cands, key=lambda c: -c.final)
