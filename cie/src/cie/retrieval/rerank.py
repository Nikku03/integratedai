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


_VERIF = {VerificationStatus.verified: 0.15, VerificationStatus.unverified: 0.0,
          VerificationStatus.disputed: -0.1, VerificationStatus.rejected: -0.5}


_STOP = {"what", "when", "who", "which", "how", "does", "the", "and", "for", "with", "about", "this", "that",
         "are", "was", "were", "have", "has", "from", "into", "under", "according", "say", "says", "did", "will",
         "current", "currently", "latest", "history", "list", "all", "any", "much", "many", "date", "there", "their"}


def query_terms(query: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{3,}", query.lower()) if w not in _STOP]


def coverage(query: str, text: str) -> float:
    """Fraction of query content words present in ``text`` (5-char prefix match
    so 'payments' matches 'payment'). Independent of the embedding model."""
    terms = query_terms(query)
    if not terms:
        return 1.0
    hay = text.lower()
    hits = 0
    for t in terms:
        key = t[:5] if len(t) > 5 else t
        if key in hay:
            hits += 1
    return hits / len(terms)


def support_of(c: Candidate, query: str) -> float:
    if c.record is not None:
        text = f"{c.record.summary} {c.record.detail} {c.record.content}"
    else:
        text = f"{c.section.title or ''} {c.section.text}"
    cov = coverage(query, text)
    exact = 1.0 if "exact" in c.sources and c.sources["exact"][1] >= 3.0 else 0.0
    vec = 0.0
    for name in ("vec_rec", "vec_sec"):
        if name in c.sources:
            sim = float(c.sources[name][1])
            if sim >= 0.6:  # only trust high cosine similarity as support on its own
                vec = max(vec, sim)
    return max(exact, cov, vec)


def rerank(cands: list[Candidate], intent: Intent, query: str = "", now: datetime | None = None,
           hub_threshold: int = 40) -> list[Candidate]:
    now = now or utcnow()
    max_fused = max((c.fused for c in cands), default=1.0) or 1.0
    for c in cands:
        base = c.fused / max_fused
        c.support = round(support_of(c, query), 3) if query else 1.0
        reasons = {"fused": round(base, 4), "support": round(0.3 * c.support, 4)}
        if c.record is not None:
            r = c.record
            if intent.type_hints and r.type.value in intent.type_hints:
                reasons["type_match"] = 0.25
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
                reasons["document_record"] = -0.15  # prefer specific facts over whole-document stubs
        else:
            reasons["section"] = -0.05
        if c.horizon:
            reasons["graph_horizon"] = -0.08 * c.horizon
        c.reasons = reasons
        c.final = sum(reasons.values())
    return sorted(cands, key=lambda c: -c.final)
