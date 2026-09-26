"""Transparent exploration priority.

priority = w_q * query_relevance + w_d * dependency_relevance + w_r * source_reliability
           + w_t * temporal_applicability + w_g * information_gain - w_c * retrieval_cost - w_x * redundancy

Every component is in [0, 1], is defined below, and is logged for every scored candidate. The weights
are hand-set heuristics, not calibrated probabilities; the score only orders the frontier and the
evidence. Permissions are not a component: a record the requester may not see is never scored,
because the SQL that loads candidates already excludes it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import numpy as np

# How strongly a relationship kind carries relevance from one record to the next (per hop, multiplied along a path).
EDGE_WEIGHT = {"depends_on": 1.0, "blocks": 0.9, "governed_by": 0.9, "supplies": 0.85, "contradicts": 0.85,
               "supports": 0.75, "supersedes": 0.7, "derived_from": 0.7, "owned_by": 0.35}
PROVENANCE_FACTOR = {"explicit": 1.0, "rule": 0.9, "inferred": 0.5}
# Reliability of the system a record came from (attrs.source_system); generated text is lowest.
SOURCE_RELIABILITY = {"erp": 1.0, "contract_repository": 1.0, "inventory": 1.0, "project_tracker": 0.9, "document": 0.8,
                      "email": 0.6, "chat": 0.5, "generated": 0.2}
VERIFICATION_FACTOR = {"verified": 1.0, "unverified": 0.85, "disputed": 0.5, "rejected": 0.1}


@dataclass
class Weights:
    query: float = 1.0
    dependency: float = 1.0
    reliability: float = 0.5
    temporal: float = 0.5
    gain: float = 0.5
    cost: float = 0.5
    redundancy: float = 0.75

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Weights:
        d = d or {}
        return cls(**{k: float(v) for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Components:
    query_relevance: float
    dependency_relevance: float
    source_reliability: float
    temporal_applicability: float
    information_gain: float
    retrieval_cost: float
    redundancy: float

    def score(self, w: Weights) -> float:
        return round(w.query * self.query_relevance + w.dependency * self.dependency_relevance
                     + w.reliability * self.source_reliability + w.temporal * self.temporal_applicability
                     + w.gain * self.information_gain - w.cost * self.retrieval_cost - w.redundancy * self.redundancy, 4)

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 4) for k, v in asdict(self).items()}


def cosine(a, b) -> float:
    if a is None or b is None:
        return 0.0
    a = np.asarray(a.to_numpy() if hasattr(a, "to_numpy") else a, dtype=np.float32)
    b = np.asarray(b.to_numpy() if hasattr(b, "to_numpy") else b, dtype=np.float32)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, float(a @ b) / (na * nb))


def path_relevance(edges: list[tuple[str, str]]) -> float:
    """Product of per-hop weights along a path of (kind, provenance) steps; 1.0 for a search hit (empty path)."""
    r = 1.0
    for kind, prov in edges:
        r *= EDGE_WEIGHT.get(kind, 0.3) * PROVENANCE_FACTOR.get(prov, 0.5)
    return r


def reliability(node) -> float:
    base = SOURCE_RELIABILITY.get(str(node.attrs.get("source_system", "document")), 0.7)
    if not node.authoritative:
        base = min(base, SOURCE_RELIABILITY["generated"])
    return base * VERIFICATION_FACTOR.get(node.verification, 0.85)


def temporal(node, as_of: datetime | None) -> float:
    if node.review_status in ("invalidated", "needs_review"):
        return 0.3
    if as_of is None:
        return 1.0 if node.valid_to is None else 0.5
    if node.valid_from is not None and node.valid_from > as_of:
        return 0.2  # not yet in force at the requested time
    if node.valid_to is not None and node.valid_to <= as_of:
        return 0.25  # superseded or expired: still useful for chronology, not as the current value
    return 1.0


def information_gain(node, covered_sources: set[str]) -> float:
    roots = set(node.root_sources) or {f"node:{node.id}"}
    new = len(roots - covered_sources) / len(roots)
    bonus = 0.25 if node.type in ("claim", "risk", "requirement") else 0.0
    return min(1.0, new + bonus)


def redundancy(node, covered_sources: set[str]) -> float:
    roots = set(node.root_sources)
    if not roots:
        return 0.0
    return len(roots & covered_sources) / len(roots)


def cost(node, max_tokens: int, fanout: int | None = None) -> float:
    from cie.rem.budget import est_tokens

    # a whole document costs what reading it costs (attrs.tokens, set at ingest), not the length of its title
    tokens = int(node.attrs.get("tokens") or 0) or est_tokens(node.text())
    c = min(1.0, tokens / max(1, max_tokens))
    if fanout:
        c += min(0.5, np.log1p(fanout) / np.log(1000) * 0.5)  # hubs cost more to expand
    return min(1.0, c)


def components(node, *, qrel: float, path: list[tuple[str, str]], as_of, covered: set[str], max_tokens: int,
               fanout: int | None = None) -> Components:
    return Components(query_relevance=qrel, dependency_relevance=path_relevance(path), source_reliability=reliability(node),
                      temporal_applicability=temporal(node, as_of), information_gain=information_gain(node, covered),
                      retrieval_cost=cost(node, max_tokens, fanout), redundancy=redundancy(node, covered))
