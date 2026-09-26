"""Bounded exploration of the business graph from permission-filtered search results.

Horizons (hop distance from the start set):

* H1: the start records' immediate dependencies (depends_on, blocks, supplies, governed_by), their own sources
  (derived_from), versions (supersedes), contradictions, and owners (owned_by, H1 only: owners are hubs).
* H2: dependencies of those, plus supporting evidence (supports, derived_from, contradicts, supersedes).
* H3: dependencies only, and only records outside the start set's projects and departments: cross-project or
  cross-department consequences.

Policies, all under the same limits, batch size and permission filter:

* ``search``      (arm A): the search hits only, no traversal.
* ``traversal``   (arm B): typed breadth-first expansion, first-in first-out.
* ``rem``         (arm C): best-first expansion ordered by the logged priority score (``cie.rem.priority``).
* ``rem+routing`` (arm D): arm C plus routing shortcuts as navigation candidates. A node reached by a shortcut
  starts a new path: the shortcut is never reported as a relationship, never used as evidence of one, and the
  node behind it is loaded through the same permission filter as any other.

Cycles terminate because a node is expanded at most once; a node reached by several paths keeps every path
(up to ``MAX_PATHS``) but is scored and returned once, so extra paths cannot inflate anything.
"""

from __future__ import annotations

import heapq
import itertools
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cie.rem import priority as pr
from cie.rem.budget import Budget, est_tokens
from cie.rem.store import EdgeView, GraphReader, NodeView

DEP_KINDS = ("depends_on", "blocks", "supplies", "governed_by")
HORIZON_KINDS = {
    1: DEP_KINDS + ("derived_from", "supersedes", "contradicts", "owned_by"),
    2: DEP_KINDS + ("supports", "derived_from", "contradicts", "supersedes"),
    3: DEP_KINDS,
}
POLICIES = ("search", "traversal", "rem", "rem+routing")
BATCH = 8  # nodes expanded per database round trip, identical for every policy
PER_NODE = 60  # edges followed per node per expansion; a cut node makes the result incomplete
MAX_PATHS = 4
# what may be returned as evidence: source text, and statements from systems of record with exact pointers
EVIDENCE_TYPES = ("passage", "document", "claim", "order", "milestone", "requirement", "contract", "invoice", "fact", "decision")


@dataclass
class Visit:
    node: NodeView
    hop: int
    via: str  # search | targeted_search | edge | routing
    qrel: float
    paths: list[list[dict[str, Any]]] = field(default_factory=list)
    comps: pr.Components | None = None
    score: float = 0.0
    expanded: bool = False
    cross_boundary: bool = False
    order: int = 0

    @property
    def path(self) -> list[dict[str, Any]]:
        return self.paths[0] if self.paths else []


def _step(e: EdgeView, frm: uuid.UUID) -> dict[str, Any]:
    forward = e.src == frm
    return {"edge_id": str(e.id), "kind": e.kind, "provenance": e.provenance, "status": e.status,
            "from": str(frm), "to": str(e.dst if forward else e.src), "direction": "out" if forward else "in",
            "hypothesis": e.hypothesis}


@dataclass
class Exploration:
    visits: dict[uuid.UUID, Visit]
    status: str
    stopping_reason: str
    frontier: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    truncated: set[uuid.UUID]
    edges: dict[uuid.UUID, EdgeView]
    routing_hops: int = 0


class Explorer:
    def __init__(self, reader: GraphReader, *, policy: str, budget: Budget, weights: pr.Weights | None = None,
                 qvec=None, as_of: datetime | None = None, scope_projects: set[uuid.UUID] | None = None):
        if policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}")
        self.r = reader
        self.policy = policy
        self.budget = budget
        self.w = weights or pr.Weights()
        self.qvec = qvec
        self.as_of = as_of
        self.scope_projects = set(scope_projects or ())
        self.visits: dict[uuid.UUID, Visit] = {}
        self.edges: dict[uuid.UUID, EdgeView] = {}
        self.trace: list[dict[str, Any]] = []
        self.truncated: set[uuid.UUID] = set()
        self._order = itertools.count()
        self._covered: set[str] = set()
        self._start_groups: set[uuid.UUID] = set()
        self.routing_hops = 0

    # ------------------------------------------------------------------ scoring
    def _qrel(self, node: NodeView, search_score: float | None = None) -> float:
        if search_score is not None:
            return max(0.0, min(1.0, search_score))
        return pr.cosine(self.qvec, node.embedding) if self.qvec is not None else 0.0

    def _score(self, v: Visit) -> None:
        steps = [(s["kind"], s["provenance"]) for s in v.path if s["kind"] != "routing"]
        routed = any(s["kind"] == "routing" for s in v.path)
        c = pr.components(v.node, qrel=v.qrel, path=steps, as_of=self.as_of, covered=self._covered,
                          max_tokens=self.budget.limits.max_tokens)
        if routed:
            c.dependency_relevance *= 0.5  # a shortcut says nothing about how the records are related
        edge_t = min((self._edge_temporal(s) for s in v.path if s["kind"] != "routing"), default=1.0)
        c.temporal_applicability = min(c.temporal_applicability, edge_t)
        v.comps, v.score = c, c.score(self.w)

    def _edge_temporal(self, step: dict[str, Any]) -> float:
        e = self.edges.get(uuid.UUID(step["edge_id"]))
        if e is None or self.as_of is None:
            return 1.0
        if e.valid_to is not None and e.valid_to <= self.as_of:
            return 0.25
        if e.valid_from is not None and e.valid_from > self.as_of:
            return 0.2
        return 1.0

    def _groups(self, n: NodeView) -> set[uuid.UUID]:
        g = set(n.project_ids) | set(n.department_ids)
        if n.type in ("project", "department"):
            g.add(n.id)
        return g

    # ------------------------------------------------------------------ admission
    def _admit(self, node: NodeView, hop: int, via: str, qrel: float, path: list[dict[str, Any]]) -> Visit | None:
        v = self.visits.get(node.id)
        if v is not None:
            if path and len(v.paths) < MAX_PATHS and path not in v.paths:
                v.paths.append(path)  # another route to the same record: kept for explanation, not counted twice
            return None
        if hop == 3 and self.policy != "search":
            groups = self._groups(node)
            if not groups or groups <= self._start_groups:
                return None  # H3 is reserved for consequences outside the start set's projects and departments
        v = Visit(node=node, hop=hop, via=via, qrel=qrel, paths=[path] if path else [], order=next(self._order))
        v.cross_boundary = bool(self._groups(node) - self._start_groups) and hop > 0
        self._score(v)
        self.visits[node.id] = v
        self.budget.usage.visited += 1
        self.budget.usage.depth = max(self.budget.usage.depth, hop)
        return v

    def start(self, hits: list[tuple[NodeView, float, str]]) -> None:
        for node, score, how in hits:
            if self.scope_projects and node.project_ids and not (set(node.project_ids) & self.scope_projects) \
                    and node.id not in self.scope_projects:
                continue  # outside the requested project scope
            self._start_groups |= self._groups(node)
            v = self._admit(node, 0, how, self._qrel(node, score), [])
            if v is not None:
                self.trace.append({"event": "start", "node": str(node.id), "type": node.type, "how": how,
                                   "score": v.score, "components": v.comps.as_dict()})
        if self.scope_projects:
            self._start_groups |= self.scope_projects

    # ------------------------------------------------------------------ main loop
    def run(self) -> Exploration:
        stop = None
        if self.policy != "search":
            stop = self._expand_all()
        self.budget.tick(self.r.counter.db_calls)
        frontier = self._frontier_items()
        if stop is None and self.truncated:
            stop = "fanout_cap"
        status = "complete" if stop is None else "incomplete"
        return Exploration(visits=self.visits, status=status, stopping_reason=stop or "frontier_exhausted", frontier=frontier,
                           trace=self.trace, truncated=self.truncated, edges=self.edges, routing_hops=self.routing_hops)

    def _pending(self) -> list[Visit]:
        return [v for v in self.visits.values() if not v.expanded and v.hop < self.budget.limits.max_depth]

    def _next_batch(self) -> list[Visit]:
        pending = self._pending()
        if self.policy == "traversal":
            pending.sort(key=lambda v: (v.hop, v.order))  # breadth first, discovery order
        else:
            for v in pending:
                self._score(v)  # redundancy and gain depend on what is already covered
            pending = heapq.nlargest(BATCH, pending, key=lambda v: (v.score, -v.order))
        return pending[:BATCH]

    def _expand_all(self) -> str | None:
        while True:
            self.budget.tick(self.r.counter.db_calls)
            reason = self.budget.exceeded()
            if reason:
                return reason
            batch = self._next_batch()
            if not batch:
                return None
            by_hop: dict[int, list[Visit]] = {}
            for v in batch:
                v.expanded = True
                by_hop.setdefault(v.hop + 1, []).append(v)
                if v.node.root_sources:
                    self._covered |= set(v.node.root_sources)
                self.trace.append({"event": "expand", "node": str(v.node.id), "type": v.node.type, "hop": v.hop,
                                   "score": v.score, "components": v.comps.as_dict() if v.comps else None})
            for hop, group in sorted(by_hop.items()):
                self._expand(group, hop)
                if self.policy == "rem+routing":
                    self._route(group, hop)

    def _expand(self, group: list[Visit], hop: int) -> None:
        anchors = {v.node.id: v for v in group}
        kinds = HORIZON_KINDS.get(hop, DEP_KINDS)
        edges, views, cut = self.r.edges(anchors, kinds=kinds, per_node=PER_NODE, with_embedding=self.qvec is not None)
        self.truncated |= cut
        for e in edges:
            self.edges[e.id] = e
            anchor_id = e.src if e.src in anchors else e.dst
            other = e.dst if anchor_id == e.src else e.src
            node = views.get(other) or (self.visits[other].node if other in self.visits else None)
            if node is None:
                continue
            parent = anchors[anchor_id]
            path = parent.path + [_step(e, anchor_id)]
            self._admit(node, hop, "edge", self._qrel(node), path)

    def _route(self, group: list[Visit], hop: int) -> None:
        shortcuts = self.r.routing([v.node.id for v in group])
        new = {dst for _, dst, _ in shortcuts if dst not in self.visits}
        views = self.r.nodes(new, with_embedding=self.qvec is not None)
        for src, dst, builder in shortcuts:
            if dst in views:
                path = [{"edge_id": None, "kind": "routing", "provenance": builder, "status": "navigation",
                         "from": str(src), "to": str(dst), "direction": "out", "hypothesis": False}]
                if self._admit(views[dst], hop, "routing", self._qrel(views[dst]), path) is not None:
                    self.routing_hops += 1

    # ------------------------------------------------------------------ resume
    def _frontier_items(self) -> list[dict[str, Any]]:
        return [{"node": str(v.node.id), "hop": v.hop, "via": v.via, "qrel": v.qrel, "paths": v.paths}
                for v in self._pending()]

    def resume(self, state: dict[str, Any]) -> None:
        """Reload a saved exploration: visited records are marked expanded, the frontier is re-admitted with its
        paths. Records the requester can no longer see are dropped by the permission filter on reload."""
        ids = [uuid.UUID(x) for x in state.get("expanded", [])] + [uuid.UUID(f["node"]) for f in state.get("frontier", [])]
        views = self.r.nodes(ids, with_embedding=self.qvec is not None)
        self._start_groups = {uuid.UUID(x) for x in state.get("start_groups", [])}
        self._covered = set(state.get("covered", []))
        for x in state.get("expanded", []):
            n = views.get(uuid.UUID(x["node"]) if isinstance(x, dict) else uuid.UUID(x))
            if n is not None:
                v = Visit(node=n, hop=0, via="resumed", qrel=self._qrel(n), expanded=True, order=next(self._order))
                self._score(v)
                self.visits[n.id] = v
        for f in state.get("frontier", []):
            n = views.get(uuid.UUID(f["node"]))
            if n is not None and n.id not in self.visits:
                v = Visit(node=n, hop=int(f["hop"]), via=f["via"], qrel=float(f["qrel"]), paths=f.get("paths", []),
                          order=next(self._order))
                self._score(v)
                self.visits[n.id] = v

    def state(self) -> dict[str, Any]:
        return {"expanded": [str(k) for k, v in self.visits.items() if v.expanded or v.hop >= self.budget.limits.max_depth],
                "frontier": self._frontier_items(), "start_groups": [str(x) for x in self._start_groups],
                "covered": sorted(self._covered)}


def pack_evidence(visits: list[Visit], policy: str, max_tokens: int, weights: pr.Weights, as_of) -> tuple[list[Visit], int, bool]:
    """Choose the evidence records to return within the token budget. Search and traversal keep their own order
    (rank, then discovery); the REM policies re-score greedily so a second summary of an already-cited source
    loses priority (redundancy) instead of counting as corroboration. Returns (chosen, tokens, cut_by_budget)."""
    cands = [v for v in visits if v.node.type in EVIDENCE_TYPES and (v.node.source_pointers or v.node.type == "passage")
             and v.node.authoritative and v.node.review_status != "invalidated"]
    chosen, used, cut = [], 0, False
    if policy in ("search", "traversal"):
        ordered = sorted(cands, key=lambda v: (v.hop, v.order) if policy == "traversal" else (-v.qrel, v.order))
        for v in ordered:
            t = est_tokens(v.node.text())
            if used + t > max_tokens:
                cut = True
                continue
            chosen.append(v)
            used += t
        return chosen, used, cut
    covered: set[str] = set()
    pool = list(cands)
    while pool:
        for v in pool:
            steps = [(s["kind"], s["provenance"]) for s in v.path if s["kind"] != "routing"]
            v.comps = pr.components(v.node, qrel=v.qrel, path=steps, as_of=as_of, covered=covered, max_tokens=max_tokens)
            v.score = v.comps.score(weights)
        pool.sort(key=lambda v: (-v.score, v.order))
        v = pool.pop(0)
        t = est_tokens(v.node.text())
        if used + t > max_tokens:
            cut = True
            continue
        chosen.append(v)
        used += t
        covered |= set(v.node.root_sources) or {f"node:{v.node.id}"}
    return chosen, used, cut
