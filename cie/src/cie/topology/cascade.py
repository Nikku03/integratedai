"""The "sandcastle" recruitment cascade as a retrieval stage.

A stimulus recruits cliques in order: pairs and triples first (signal reception),
then the mid-dimensional simplices they complete (feature integration), and last
the sinks of the highest-dimensional simplices, where the activity converges
(peak synchronisation), before everything collapses. Here the stimulus is the set
of records the lexical, vector and exact stages activated; the tissue is their
one-hop neighbourhood in the record graph; recruitment follows the same order and
is capped by the same log(N) budget as the REM expansion it replaces, so the two
can be compared on equal terms.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cie.core.models import MemoryRecord, RecordLink
from cie.topology.cliques import Complex, activation_order, directed_flag_complex

_STAGE_WEIGHT = {1: 1.0, 2: 0.8, 3: 0.7}


@dataclass
class Recruited:
    record_id: uuid.UUID
    stage: int  # 1 rods/planks, 2 feature integration, 3 peak (sink)
    via: uuid.UUID
    kind: str
    score: float
    dim: int


def recruit(session: Session, seeds: dict[uuid.UUID, float], *, base_filter, cross_scope_filter, budget: int,
            per_node_cap: int = 8, max_dim: int = 5) -> tuple[list[Recruited], Complex, dict[str, Any]]:
    """``seeds``: {record_id: activation}. Returns the recruited records (at most
    ``budget``), the directed flag complex of the activated tissue, and per-node
    topological features for every node in it (seeds included)."""
    if not seeds:
        return [], directed_flag_complex([], []), {}
    ids = list(seeds)
    edges = list(session.execute(select(RecordLink.src_id, RecordLink.dst_id, RecordLink.kind, RecordLink.weight).where(
        or_(RecordLink.src_id.in_(ids), RecordLink.dst_id.in_(ids)))).all())
    # bound the tissue: the strongest per_node_cap links of each seed
    per_node: dict[uuid.UUID, int] = {}
    tissue: set[uuid.UUID] = set(seeds)
    kept: list[tuple] = []
    via: dict[uuid.UUID, tuple[uuid.UUID, str, float]] = {}
    for src, dst, kind, w in sorted(edges, key=lambda e: -float(e[3])):
        for a, b in ((src, dst), (dst, src)):
            if a in seeds and b not in seeds:
                if per_node.get(a, 0) >= per_node_cap:
                    continue
                per_node[a] = per_node.get(a, 0) + 1
                tissue.add(b)
                s = seeds[a] * float(w)
                if b not in via or via[b][2] < s:
                    via[b] = (a, kind.value, s)
        kept.append((src, dst))
    neighbours = [n for n in tissue if n not in seeds]
    if neighbours:
        # links among the neighbours themselves: they decide which simplices close
        more = session.execute(select(RecordLink.src_id, RecordLink.dst_id).where(
            RecordLink.src_id.in_(neighbours), RecordLink.dst_id.in_(list(tissue)))).all()
        kept.extend((a, b) for a, b in more)
    edge_list = [(a, b) for a, b in kept if a in tissue and b in tissue]
    cx = directed_flag_complex(list(tissue), edge_list, max_dim=max_dim)
    stage = activation_order(cx, set(seeds))
    features = {v: {"dim": cx.max_dim.get(v, 0), "count": cx.count.get(v, 0), "sink_of": cx.sink_of.get(v, 0),
                    "source_of": cx.source_of.get(v, 0), "stage": stage.get(v, 0)} for v in tissue}
    cand = {v: st for v, st in stage.items() if v not in seeds}
    if not cand:
        return [], cx, features
    # a recruit's activation: what its activated clique-mates carried, scaled by the dimension it reached and its stage
    mates: dict[uuid.UUID, float] = {}
    for sx in cx.simplices:
        members = set(sx)
        act = [m for m in members if m in seeds]
        if len(act) < 2:
            continue
        mass = sum(seeds[m] for m in act) / len(act)
        d = len(sx) - 1
        for m in members:
            if m in cand:
                mates[m] = max(mates.get(m, 0.0), mass * (1 + 0.15 * d))
    scored = {v: mates.get(v, via.get(v, (None, "", 0.0))[2]) * _STAGE_WEIGHT[cand[v]] for v in cand}
    # permission and scope: stages 1-2 stay in the addressable scopes, sinks may reach across (cavities route globally)
    allowed_scoped = set(session.scalars(select(MemoryRecord.id).where(base_filter, MemoryRecord.id.in_(list(cand)))))
    sinks = [v for v, st in cand.items() if st == 3 and v not in allowed_scoped]
    allowed_cross = set(session.scalars(select(MemoryRecord.id).where(cross_scope_filter, MemoryRecord.id.in_(sinks)))) if sinks else set()
    picked = sorted(((v, s) for v, s in scored.items() if v in allowed_scoped or v in allowed_cross), key=lambda kv: -kv[1])[:budget]
    out = []
    for v, s in picked:
        src, kind, _ = via.get(v, (next(iter(seeds)), "clique", 0.0))
        out.append(Recruited(v, cand[v], src, kind, s, cx.max_dim.get(v, 0)))
    return out, cx, features
