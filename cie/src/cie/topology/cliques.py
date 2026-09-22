"""Directed flag complex of a small record graph: simplices, sinks, sources, cavities.

Everything here runs on the few hundred records a query activates, never on the
whole bank, so exact enumeration is affordable: a directed n-simplex is a chain
v0 -> v1 -> ... -> vn in which every earlier node links to every later one
(Reimann et al. 2017, "directed cliques"). v0 is its source, vn its sink.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Complex:
    nodes: list[Hashable]
    simplices: list[tuple[Hashable, ...]]  # each ordered source -> sink; dimension = len - 1
    max_dim: dict[Hashable, int] = field(default_factory=dict)  # highest dimension a node belongs to
    count: dict[Hashable, int] = field(default_factory=dict)  # simplices (dim >= 1) containing the node
    sink_of: dict[Hashable, int] = field(default_factory=dict)  # times the node is the sink of a simplex of dim >= 2
    source_of: dict[Hashable, int] = field(default_factory=dict)
    by_dim: dict[int, int] = field(default_factory=dict)
    betti1: int = 0  # independent cycles of the 2-skeleton no triangle fills: the "cavities" of dimension 1
    truncated: bool = False

    def stats(self) -> dict[str, Any]:
        return {"nodes": len(self.nodes), "simplices_by_dim": dict(sorted(self.by_dim.items())),
                "max_dim": max(self.by_dim, default=0), "betti1": self.betti1, "truncated": self.truncated}


def directed_flag_complex(nodes: list[Hashable], edges: list[tuple[Hashable, Hashable]], max_dim: int = 5,
                          max_simplices: int = 50_000) -> Complex:
    """Enumerate the directed simplices of the graph up to ``max_dim`` (bounded by
    ``max_simplices``; the flag says whether the bound cut the enumeration)."""
    out_adj: dict[Hashable, set] = defaultdict(set)
    node_set = set(nodes)
    for a, b in edges:
        if a in node_set and b in node_set and a != b:
            out_adj[a].add(b)
    cx = Complex(nodes=list(nodes), simplices=[])
    simplices: list[tuple] = []

    def extend(chain: list, candidates: set) -> None:
        # candidates: nodes every member of the chain links to; adding one keeps the chain a directed simplex
        for v in sorted(candidates, key=str):
            if len(simplices) >= max_simplices:
                cx.truncated = True
                return
            new_chain = chain + [v]
            simplices.append(tuple(new_chain))
            if len(new_chain) - 1 < max_dim:
                extend(new_chain, candidates & out_adj[v])

    for v in sorted(node_set, key=str):
        if out_adj[v]:
            extend([v], set(out_adj[v]))
    cx.simplices = simplices
    for sx in simplices:
        d = len(sx) - 1
        cx.by_dim[d] = cx.by_dim.get(d, 0) + 1
        for v in sx:
            cx.max_dim[v] = max(cx.max_dim.get(v, 0), d)
            cx.count[v] = cx.count.get(v, 0) + 1
        if d >= 2:
            cx.sink_of[sx[-1]] = cx.sink_of.get(sx[-1], 0) + 1
            cx.source_of[sx[0]] = cx.source_of.get(sx[0], 0) + 1
    cx.betti1 = betti1(nodes, edges, [sx for sx in simplices if len(sx) == 3])
    return cx


def _rank_gf2(rows: list[set[int]], n_cols: int) -> int:
    """Rank over GF(2) of a sparse boolean matrix given as row supports."""
    pivots: dict[int, set[int]] = {}
    rank = 0
    for r in rows:
        r = set(r)
        while r:
            p = min(r)
            if p in pivots:
                r ^= pivots[p]
            else:
                pivots[p] = r
                rank += 1
                break
    return rank


def betti1(nodes: list[Hashable], edges: list[tuple[Hashable, Hashable]], triangles: list[tuple]) -> int:
    """First Betti number of the 2-skeleton (undirected): cycles of links that no
    triangle of links fills. Computed as E - V + C - rank(boundary_2) over GF(2)."""
    node_set = set(nodes)
    und = {frozenset((a, b)) for a, b in edges if a in node_set and b in node_set and a != b}
    if not und:
        return 0
    idx = {e: i for i, e in enumerate(sorted(und, key=lambda e: tuple(sorted(map(str, e)))))}
    # components by union-find
    parent: dict[Hashable, Hashable] = {v: v for v in node_set}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in und:
        a, b = tuple(e)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    components = len({find(v) for v in node_set})
    rows = []
    seen_tri = set()
    for t in triangles:
        key = frozenset(t)
        if len(key) != 3 or key in seen_tri:
            continue
        seen_tri.add(key)
        a, b, c = tuple(key)
        support = {idx[frozenset(p)] for p in ((a, b), (b, c), (a, c)) if frozenset(p) in idx}
        if len(support) == 3:
            rows.append(support)
    rank2 = _rank_gf2(rows, len(idx))
    return max(0, len(und) - len(node_set) + components - rank2)


def activation_order(cx: Complex, seeds: set[Hashable]) -> dict[Hashable, int]:
    """The stage at which a node would be recruited by the sandcastle cascade:
    1 for seeds sharing a link with another seed (rods and planks), 2 for nodes in a
    simplex of dimension >= 2 with at least two seeds (feature integration), 3 for the
    sinks of the highest-dimensional simplices that contain at least three activated
    nodes (peak synchronisation). Nodes never reached are absent."""
    stage: dict[Hashable, int] = {}
    for sx in cx.simplices:
        members = set(sx)
        n_seed = len(members & seeds)
        d = len(sx) - 1
        if d == 1 and n_seed == 2:
            for v in sx:
                stage[v] = min(stage.get(v, 9), 1)
        elif d >= 2 and n_seed >= 2:
            for v in sx:
                if v not in seeds:
                    stage[v] = min(stage.get(v, 9), 2)
    activated = seeds | set(stage)
    top = max((len(sx) - 1 for sx in cx.simplices if len(set(sx) & activated) >= 3), default=0)
    if top >= 2:
        for sx in cx.simplices:
            if len(sx) - 1 == top and len(set(sx) & activated) >= 3:
                v = sx[-1]
                if v not in seeds:
                    stage[v] = min(stage.get(v, 9), 3)
    return stage


def as_array(cx: Complex, order: list[Hashable]) -> np.ndarray:
    """Per-node topological features in a fixed order: [max_dim, count, sink_of, source_of]."""
    return np.array([[cx.max_dim.get(v, 0), cx.count.get(v, 0), cx.sink_of.get(v, 0), cx.source_of.get(v, 0)] for v in order], dtype=float)
