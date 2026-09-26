"""Question-conditioned subgraphs for the learned explorer.

For each question the candidate pool is what ordinary typed traversal (arm B) reaches from the same start hits
under the same permission filter: the network re-ranks and chooses computation inside that pool, so any gain is
attributable to the network and not to a larger pool. Edges between pool records are added in both directions
with separate relation ids; routing shortcuts between pool records are an extra relation (navigation only).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from cie.rem import priority as pr
from cie.rem.budget import Budget, Limits, est_tokens
from cie.rem.explore import EVIDENCE_TYPES, Explorer
from cie.rem.models import BUSINESS_EDGE_KINDS, NODE_TYPES
from cie.rem.store import GraphReader

R = len(BUSINESS_EDGE_KINDS)
ROUTING_REL = 2 * R  # relation id of routing shortcuts
N_RELS = 2 * R + 1
INHIBITORY_KINDS = ("contradicts", "supersedes")
TYPE_INDEX = {t: i for i, t in enumerate(NODE_TYPES)}
FEATS = len(NODE_TYPES) + 3 + 4 + 5  # type, start (3), hop (4), flags/scalars (5)


@dataclass
class Sample:
    qid: str
    question: str
    qvec: np.ndarray  # [384]
    node_ids: list[str]
    keys: list[str]  # "type:key"
    docs: list[str | None]  # document a record belongs to (ERB), or its own key
    emb: np.ndarray  # [N, 384]
    feats: np.ndarray  # [N, FEATS]
    tokens: np.ndarray  # [N]
    evidence_ok: np.ndarray  # [N] bool: may be returned as evidence
    is_start: np.ndarray  # [N] bool
    src: np.ndarray  # [E]
    dst: np.ndarray  # [E]
    rel: np.ndarray  # [E]
    edge_keys: list[str]
    labels: np.ndarray  # [N] 1 = gold evidence
    gold: list[str] = field(default_factory=list)  # gold keys (controlled) or documents (ERB)
    extract_ms: float = 0.0
    db_calls: int = 0
    baselines: dict = field(default_factory=dict)  # {budget: {arm: {"units": [...], "ms", "db_calls", "visited"}}}
    kind: str = ""
    split: str = ""
    search_ms: float = 0.0

    @property
    def n(self) -> int:
        return len(self.node_ids)


def _evidence_ok(n) -> bool:
    return n.type in EVIDENCE_TYPES and (bool(n.source_pointers) or n.type == "passage") and n.authoritative \
        and n.review_status != "invalidated"


def extract(reader: GraphReader, *, qid: str, question: str, qvec, start_hits: list[tuple[uuid.UUID, float]],
            gold: set[str], label_of, doc_of, max_nodes: int = 300, max_depth: int = 2, routing: bool = True) -> Sample:
    """``label_of(node) -> bool`` marks gold records; ``doc_of(node) -> str|None`` names the unit evaluated."""
    import time

    t0 = time.perf_counter()
    views = reader.nodes([h for h, _ in start_hits], with_embedding=True)
    hits = [(views[h], s, "search") for h, s in start_hits if h in views]
    budget = Budget(Limits(max_depth=max_depth, max_visited=max_nodes, max_tokens=10**9, max_db_calls=400, max_ms=60000))
    ex = Explorer(reader, policy="traversal", budget=budget, qvec=qvec)
    ex.start(hits)
    exp = ex.run()
    visits = sorted(exp.visits.values(), key=lambda v: v.order)
    ids = [v.node.id for v in visits]
    index = {nid: i for i, nid in enumerate(ids)}
    # every business edge between pool records (the traversal only kept the ones it followed)
    edges, _, _ = reader.edges(ids, direction="out")
    src, dst, rel, ekeys = [], [], [], []
    for e in edges:
        if e.src in index and e.dst in index:
            k = BUSINESS_EDGE_KINDS.index(e.kind)
            src += [index[e.src], index[e.dst]]
            dst += [index[e.dst], index[e.src]]
            rel += [k, k + R]
            ekeys += [f"{e.id}:f", f"{e.id}:r"]
    if routing:
        for a, b, _builder in reader.routing(ids, per_node=4):
            if a in index and b in index:
                src.append(index[a])
                dst.append(index[b])
                rel.append(ROUTING_REL)
                ekeys.append(f"route:{a}:{b}")
    deg = np.bincount(np.array(dst, dtype=np.int64), minlength=len(ids)) if dst else np.zeros(len(ids), dtype=np.int64)
    q = np.asarray(qvec, dtype=np.float32)
    emb = np.zeros((len(ids), 384), dtype=np.float32)
    feats = np.zeros((len(ids), FEATS), dtype=np.float32)
    tokens, ok, start, labels, keys, docs = [], [], [], [], [], []
    start_rank = {h: r for r, (h, _) in enumerate(start_hits)}
    for i, v in enumerate(visits):
        n = v.node
        if n.embedding is not None:
            emb[i] = np.asarray(n.embedding.to_numpy() if hasattr(n.embedding, "to_numpy") else n.embedding, dtype=np.float32)
        f = feats[i]
        f[TYPE_INDEX.get(n.type, 0)] = 1.0
        o = len(NODE_TYPES)
        is_start = n.id in start_rank
        f[o] = float(is_start)
        f[o + 1] = v.anchor if is_start else 0.0
        f[o + 2] = 1.0 / (1 + start_rank[n.id]) if is_start else 0.0
        f[o + 3 + min(v.hop, 3)] = 1.0
        o += 7
        f[o] = float(n.authoritative)
        f[o + 1] = pr.reliability(n)
        f[o + 2] = float(n.verification == "verified")
        f[o + 3] = math.log1p(int(deg[i])) / math.log(100)
        f[o + 4] = float(pr.cosine(q, emb[i])) if n.embedding is not None else 0.0
        tokens.append(est_tokens(n.text()))
        ok.append(_evidence_ok(n))
        start.append(is_start)
        labels.append(float(label_of(n)))
        keys.append(f"{n.type}:{n.key}")
        docs.append(doc_of(n))
    return Sample(qid=qid, question=question, qvec=q, node_ids=[str(x) for x in ids], keys=keys, docs=docs, emb=emb, feats=feats,
                  tokens=np.array(tokens, dtype=np.int32), evidence_ok=np.array(ok, dtype=bool), is_start=np.array(start, dtype=bool),
                  src=np.array(src, dtype=np.int64), dst=np.array(dst, dtype=np.int64), rel=np.array(rel, dtype=np.int64),
                  edge_keys=ekeys, labels=np.array(labels, dtype=np.float32), gold=sorted(gold),
                  extract_ms=(time.perf_counter() - t0) * 1000, db_calls=reader.counter.db_calls)


def pack(sample: Sample, order: list[int], max_tokens: int) -> list[int]:
    """Evidence records in ``order`` within the token budget (the same rule as the REM evidence packer)."""
    chosen, used = [], 0
    for i in order:
        if not sample.evidence_ok[i]:
            continue
        t = int(sample.tokens[i])
        if used + t > max_tokens:
            continue
        chosen.append(i)
        used += t
    return chosen


def metrics(sample: Sample, chosen: list[int], unit: str = "key") -> dict[str, Any]:
    """Evidence recall/precision over gold keys (``unit='key'``) or gold documents (``unit='doc'``, with recall@10 and
    reciprocal rank of the first gold document in packet order)."""
    gold = set(sample.gold)
    items = [sample.keys[i] if unit == "key" else sample.docs[i] for i in chosen]
    seen: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.append(x)
    hit = gold & set(seen)
    first = next((r for r, x in enumerate(seen) if x in gold), None)
    return {"evidence_recall": len(hit) / len(gold) if gold else None, "evidence_precision": len(hit) / len(seen) if seen else 0.0,
            "recall10": len(gold & set(seen[:10])) / len(gold) if gold else None, "rr": 1.0 / (first + 1) if first is not None else 0.0,
            "returned": len(seen)}
