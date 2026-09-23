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

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Session
from sqlalchemy.types import String

from cie.core.models import LinkKind, MemoryRecord, RecordLink, RecordType

HORIZON_KINDS: dict[int, set[LinkKind]] = {
    1: {LinkKind.depends_on, LinkKind.part_of, LinkKind.supersedes, LinkKind.contradicts, LinkKind.confirms,
        LinkKind.extends, LinkKind.coactivated, LinkKind.references, LinkKind.near_duplicate},
    2: {LinkKind.relates_to, LinkKind.mentions, LinkKind.precedes, LinkKind.assigned_to, LinkKind.derived_from},
    3: {LinkKind.causes, LinkKind.shortcut, LinkKind.relates_to, LinkKind.depends_on},
}
_HORIZON_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.4}
# records that many others point at (a person, a customer, a project): as seeds they are followed at horizon 1 only,
# since at horizon 2 their thousands of ``mentions`` edges would all tie and flood the candidates
HUB_TYPES = {RecordType.person, RecordType.organization, RecordType.entity, RecordType.project}
FETCH_FACTOR = 4  # edges fetched per frontier node and direction, before visited neighbours are skipped

# the strongest edges of each frontier node, capped per node in SQL so a hub never loads its whole neighbourhood
_EDGES = text("""
SELECT e.src_id, e.dst_id, e.kind::text AS kind, e.weight, n.id AS node
FROM unnest(:ids) AS n(id)
CROSS JOIN LATERAL (
  (SELECT src_id, dst_id, kind, weight FROM record_links
    WHERE src_id = n.id AND kind::text = ANY(:kinds) ORDER BY weight DESC, created_at DESC LIMIT :cap)
  UNION ALL
  (SELECT src_id, dst_id, kind, weight FROM record_links
    WHERE dst_id = n.id AND kind::text = ANY(:kinds) ORDER BY weight DESC, created_at DESC LIMIT :cap)
) AS e
""").bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))), bindparam("kinds", type_=ARRAY(String)))


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
    hubs = set(session.scalars(select(MemoryRecord.id).where(MemoryRecord.id.in_(list(seeds)), MemoryRecord.type.in_(HUB_TYPES)))) if seeds else set()
    reactivated = {k: v for k, v in seeds.items() if k not in hubs}
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
        if h > 1:
            frontier = {**reactivated, **frontier}
        if frontier:
            rows = session.execute(_EDGES, {"ids": list(frontier), "kinds": sorted(k.value for k in kinds),
                                            "cap": per_node_cap * FETCH_FACTOR}).all()
            per_node: dict[uuid.UUID, int] = {}
            for src_id, dst_id, kind, weight, node in sorted(rows, key=lambda r: -r.weight):
                other = dst_id if src_id == node else src_id
                if other in visited or other == node or per_node.get(node, 0) >= per_node_cap:
                    continue
                s = frontier[node] * weight * _HORIZON_WEIGHT[h]
                if other not in cand or cand[other][0] < s:
                    cand[other] = (s, node, kind)
                per_node[node] = per_node.get(node, 0) + 1
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
                if rid not in allowed and (rid not in deferred or deferred[rid][0] < v[0]):
                    deferred[rid] = v  # out of scope now; cross-scope candidate for the last horizon (strongest route kept)
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
