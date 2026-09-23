"""REM-inspired bounded-horizon expansion over the sparse record graph.

Horizon 1: direct facts, requirements, tasks, dependencies (structural edges).
Horizon 2: related decisions, people, documents, results (associative edges).
Horizon 3: cross-project / cross-department consequences (causal + shortcut
edges, allowed to leave the query scope).

The total number of expanded nodes is capped by ``budget = ceil(c * log2(N))``
where N is the number of addressable records, so expansion cost grows with
log(N) rather than with N.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cie.core.models import LinkKind, MemoryRecord, RecordLink

HORIZON_KINDS: dict[int, set[LinkKind]] = {
    1: {LinkKind.depends_on, LinkKind.part_of, LinkKind.supersedes, LinkKind.contradicts, LinkKind.confirms,
        LinkKind.extends, LinkKind.coactivated, LinkKind.references, LinkKind.near_duplicate},
    2: {LinkKind.relates_to, LinkKind.mentions, LinkKind.precedes, LinkKind.assigned_to, LinkKind.derived_from},
    3: {LinkKind.causes, LinkKind.shortcut, LinkKind.relates_to, LinkKind.depends_on},
}
_HORIZON_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.4}


@dataclass
class Expanded:
    record_id: uuid.UUID
    horizon: int
    via: uuid.UUID
    kind: str
    score: float


def budget_for(n_records: int, coefficient: float) -> int:
    return max(4, math.ceil(coefficient * math.log2(max(n_records, 2))))


def expand(session: Session, seeds: dict[uuid.UUID, float], *, base_filter, cross_scope_filter, budget: int,
           max_horizon: int = 3, per_node_cap: int = 8) -> list[Expanded]:
    """``seeds``: {record_id: seed_score}. ``base_filter`` restricts horizons 1–2
    to the addressable scopes; ``cross_scope_filter`` is the permission-only
    filter used at horizon 3. Neighbours reached at horizons 1–2 that lie
    outside the addressable scopes are deferred and admitted at horizon 3 as
    cross-project consequences (permission permitting)."""
    visited: set[uuid.UUID] = set(seeds)
    frontier: dict[uuid.UUID, float] = dict(seeds)
    out: list[Expanded] = []
    deferred: dict[uuid.UUID, tuple[float, uuid.UUID, str]] = {}
    remaining = budget
    for h in range(1, max_horizon + 1):
        if remaining <= 0:
            break
        kinds = HORIZON_KINDS[h]
        cand: dict[uuid.UUID, tuple[float, uuid.UUID, str]] = {}
        # the seeds stay active at every horizon: a horizon is a tier of edge kinds reached from what the query
        # activated, not only a hop count, so a seed's associative edges are followed even when its structural ones are not
        frontier = {**{k: v for k, v in seeds.items() if h > 1}, **frontier}
        if frontier:
            ids = list(frontier)
            edges = list(session.scalars(select(RecordLink).where(
                RecordLink.kind.in_(kinds), or_(RecordLink.src_id.in_(ids), RecordLink.dst_id.in_(ids)))))
            per_node: dict[uuid.UUID, int] = {}
            for e in sorted(edges, key=lambda e: -e.weight):
                for src, dst in ((e.src_id, e.dst_id), (e.dst_id, e.src_id)):
                    if src in frontier and dst not in visited:
                        if per_node.get(src, 0) >= per_node_cap:
                            continue
                        s = frontier[src] * e.weight * _HORIZON_WEIGHT[h]
                        if dst not in cand or cand[dst][0] < s:
                            cand[dst] = (s, src, e.kind.value)
                        per_node[src] = per_node.get(src, 0) + 1
        if h == max_horizon:
            for rid, v in deferred.items():
                if rid not in visited and (rid not in cand or cand[rid][0] < v[0]):
                    cand[rid] = v
            deferred = {}
        if not cand:
            frontier = {}
            continue
        filt = cross_scope_filter if h == max_horizon else base_filter
        allowed = set(session.scalars(select(MemoryRecord.id).where(filt, MemoryRecord.id.in_(list(cand)))))
        if h < max_horizon:
            for rid, v in cand.items():
                if rid not in allowed:
                    deferred[rid] = v  # out of scope now; cross-scope candidate for the last horizon
        picked = sorted(((rid, v) for rid, v in cand.items() if rid in allowed), key=lambda kv: -kv[1][0])[:remaining]
        frontier = {}
        for rid, (s, via, kind) in picked:
            visited.add(rid)
            frontier[rid] = s
            out.append(Expanded(rid, h, via, kind, s))
        remaining -= len(picked)
    return out


def degree(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    from sqlalchemy import func

    rows = session.execute(select(RecordLink.src_id, func.count()).where(RecordLink.src_id.in_(ids)).group_by(RecordLink.src_id)).all()
    rows2 = session.execute(select(RecordLink.dst_id, func.count()).where(RecordLink.dst_id.in_(ids)).group_by(RecordLink.dst_id)).all()
    d: dict[uuid.UUID, int] = {}
    for rid, c in rows + rows2:
        d[rid] = d.get(rid, 0) + int(c)
    return d
