"""Reading and writing the REM graph.

Reads (``GraphReader``) always happen at a snapshot: the tenant's change sequence number at the moment the
query started. A row belongs to snapshot S when ``sys_from <= S`` and (``sys_to`` is NULL or ``sys_to > S``).
Permissions are applied in SQL before anything is returned: a node the reader may not see is never loaded,
and an edge is returned only when both its ends are visible, so paths cannot leak through hidden records.
Every SQL statement is counted, because database calls are a budget of their own.

Writes (``GraphWriter``) are versioned: a changed node gets a new version row and the old one is closed at
the change's sequence number; nothing is overwritten or deleted outright. Each applied change takes the
next number of the tenant's sequence under a transaction-scoped advisory lock, so sequence order equals
commit order and a snapshot read is reproducible later.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

from cie.governance.permissions import Visibility, _acl_allows
from cie.rem.models import (
    BUSINESS_EDGE_KINDS,
    NODE_TYPES,
    PROVENANCE,
    RemEdge,
    RemNode,
    RemNodeVersion,
    RemRoutingEdge,
    RemStock,
    RemTenantState,
)


@dataclass
class NodeView:
    id: uuid.UUID
    type: str
    key: str
    version: int
    name: str
    summary: str
    attrs: dict[str, Any]
    project_ids: list[uuid.UUID]
    department_ids: list[uuid.UUID]
    scope_id: uuid.UUID
    sensitivity: int
    source_pointers: list[dict[str, Any]]
    root_sources: list[str]
    verification: str
    authoritative: bool
    valid_from: datetime | None
    valid_to: datetime | None
    recorded_at: datetime | None
    review_status: str | None
    sys_from: int
    embedding: Any = None

    def text(self) -> str:
        return f"{self.name}. {self.summary}".strip()


@dataclass
class EdgeView:
    id: uuid.UUID
    src: uuid.UUID
    dst: uuid.UUID
    kind: str
    provenance: str
    status: str
    attrs: dict[str, Any]
    source_pointers: list[dict[str, Any]]
    derivation: dict[str, Any]
    valid_from: datetime | None
    valid_to: datetime | None
    sys_from: int

    @property
    def hypothesis(self) -> bool:
        return self.status == "hypothesis" or (self.provenance == "inferred" and self.status != "verified")


@dataclass
class CallCounter:
    db_calls: int = 0
    ms_in_db: float = 0.0
    log: list[str] = field(default_factory=list)


def _at(model, seq: int):
    return and_(model.sys_from <= seq, or_(model.sys_to.is_(None), model.sys_to > seq))


class GraphReader:
    """Snapshot-consistent, permission-filtered reads. ``visibility`` None means the system itself (event processing)."""

    def __init__(self, session: Session, tenant_id: uuid.UUID, visibility: Visibility | None, seq: int | None = None,
                 counter: CallCounter | None = None):
        self.s = session
        self.tenant_id = tenant_id
        self.vis = visibility
        self.counter = counter or CallCounter()
        self.seq = seq if seq is not None else current_seq(session, tenant_id, self.counter)

    # -------------------------------------------------------------- plumbing
    def _run(self, stmt, params: dict | None = None, label: str = ""):
        t = time.perf_counter()
        rows = self.s.execute(stmt, params or {}).all()
        self.counter.db_calls += 1
        self.counter.ms_in_db += (time.perf_counter() - t) * 1000
        if label:
            self.counter.log.append(label)
        return rows

    def _visible_filter(self):
        if self.vis is None:
            return None
        return self.vis.sql_filter(RemNodeVersion.scope_id, RemNodeVersion.sensitivity)

    def _acl_ok(self, acl: dict | None) -> bool:
        return self.vis is None or self.vis.is_admin or _acl_allows(acl, self.vis.principal_id)

    @staticmethod
    def _view(nv: RemNodeVersion, node: RemNode, with_embedding: bool = False) -> NodeView:
        return NodeView(id=nv.node_id, type=node.type, key=node.key, version=nv.version, name=nv.name, summary=nv.summary or "",
                        attrs=nv.attrs or {}, project_ids=list(nv.project_ids or []), department_ids=list(nv.department_ids or []),
                        scope_id=nv.scope_id, sensitivity=nv.sensitivity, source_pointers=list(nv.source_pointers or []),
                        root_sources=list(nv.root_sources or []), verification=nv.verification, authoritative=nv.authoritative,
                        valid_from=nv.valid_from, valid_to=nv.valid_to, recorded_at=nv.recorded_at, review_status=nv.review_status,
                        sys_from=nv.sys_from, embedding=nv.embedding if with_embedding else None)

    # -------------------------------------------------------------- nodes
    def nodes(self, ids, with_embedding: bool = False) -> dict[uuid.UUID, NodeView]:
        ids = [i for i in dict.fromkeys(ids)]
        if not ids:
            return {}
        stmt = (select(RemNodeVersion, RemNode).join(RemNode, RemNode.id == RemNodeVersion.node_id)
                .where(RemNodeVersion.tenant_id == self.tenant_id, RemNodeVersion.node_id.in_(ids), _at(RemNodeVersion, self.seq)))
        vf = self._visible_filter()
        if vf is not None:
            stmt = stmt.where(vf)
        out = {}
        for nv, node in self._run(stmt, label=f"nodes[{len(ids)}]"):
            if self._acl_ok(nv.acl):
                out[nv.node_id] = self._view(nv, node, with_embedding)
        return out

    def node_by_key(self, type_: str, key: str) -> NodeView | None:
        stmt = (select(RemNodeVersion, RemNode).join(RemNode, RemNode.id == RemNodeVersion.node_id)
                .where(RemNode.tenant_id == self.tenant_id, RemNode.type == type_, RemNode.key == key, _at(RemNodeVersion, self.seq)))
        vf = self._visible_filter()
        if vf is not None:
            stmt = stmt.where(vf)
        rows = self._run(stmt, label="node_by_key")
        for nv, node in rows:
            if self._acl_ok(nv.acl):
                return self._view(nv, node, True)
        return None

    def visible_ids(self, ids) -> set[uuid.UUID]:
        return set(self.nodes(ids))

    # -------------------------------------------------------------- edges
    def edges(self, node_ids, kinds=BUSINESS_EDGE_KINDS, direction: str = "both", per_node: int | None = None,
              with_embedding: bool = False) -> tuple[list[EdgeView], dict[uuid.UUID, NodeView], set[uuid.UUID]]:
        """Business edges touching ``node_ids`` at the snapshot whose other end the reader may see, the visible
        neighbours themselves, and the anchors whose edge list was cut by ``per_node``. ``direction`` is relative
        to the given nodes: 'out' (node is src), 'in' (node is dst) or 'both'. Two statements."""
        ids = list(dict.fromkeys(node_ids))
        if not ids:
            return [], {}, set()
        conds = []
        if direction in ("out", "both"):
            conds.append(RemEdge.src_id.in_(ids))
        if direction in ("in", "both"):
            conds.append(RemEdge.dst_id.in_(ids))
        stmt = (select(RemEdge).where(RemEdge.tenant_id == self.tenant_id, or_(*conds), RemEdge.kind.in_(list(kinds)),
                                      RemEdge.status != "rejected", _at(RemEdge, self.seq))
                .order_by(RemEdge.sys_from, RemEdge.id))
        rows = [r[0] for r in self._run(stmt, label=f"edges[{len(ids)}]")]
        idset = set(ids)
        others = {e.dst_id if e.src_id in idset else e.src_id for e in rows}
        views = self.nodes(others, with_embedding=with_embedding)  # the permission check: invisible ends are not loaded
        out, per, cut = [], {}, set()
        for e in rows:
            other = e.dst_id if e.src_id in idset else e.src_id
            if other not in views and other not in idset:
                continue  # an edge to a record the reader may not see does not exist for this reader
            anchor = e.src_id if e.src_id in idset else e.dst_id
            if per_node is not None:
                if per.get(anchor, 0) >= per_node:
                    cut.add(anchor)
                    continue
                per[anchor] = per.get(anchor, 0) + 1
            out.append(EdgeView(id=e.id, src=e.src_id, dst=e.dst_id, kind=e.kind, provenance=e.provenance, status=e.status,
                                attrs=e.attrs or {}, source_pointers=list(e.source_pointers or []), derivation=e.derivation or {},
                                valid_from=e.valid_from, valid_to=e.valid_to, sys_from=e.sys_from))
        return out, views, cut

    def routing(self, node_ids, per_node: int = 6) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
        """Routing shortcuts from ``node_ids`` to visible nodes. Navigation only: never a relationship or a permission."""
        ids = list(dict.fromkeys(node_ids))
        if not ids:
            return []
        stmt = select(RemRoutingEdge).where(RemRoutingEdge.tenant_id == self.tenant_id, RemRoutingEdge.src_id.in_(ids),
                                            _at(RemRoutingEdge, self.seq))
        rows = [r[0] for r in self._run(stmt, label="routing")]
        visible = self.visible_ids({r.dst_id for r in rows}) if self.vis is not None else {r.dst_id for r in rows}
        out, per = [], {}
        for r in rows:
            if r.dst_id in visible and per.get(r.src_id, 0) < per_node:
                per[r.src_id] = per.get(r.src_id, 0) + 1
                out.append((r.src_id, r.dst_id, r.builder))
        return out

    # -------------------------------------------------------------- exact values
    def stock(self, product_id: uuid.UUID, holder_ids) -> dict[uuid.UUID, dict[str, Any]]:
        stmt = select(RemStock).where(RemStock.tenant_id == self.tenant_id, RemStock.product_id == product_id,
                                      RemStock.holder_id.in_(list(holder_ids)), _at(RemStock, self.seq))
        if self.vis is not None:
            stmt = stmt.where(self.vis.sql_filter(RemStock.scope_id, RemStock.sensitivity))
        out = {}
        for (row,) in self._run(stmt, label="stock"):
            out[row.holder_id] = {"on_hand": float(row.qty_on_hand), "reserved": float(row.qty_reserved or 0),
                                  "available": float(row.qty_on_hand) - float(row.qty_reserved or 0),
                                  "source_pointers": list(row.source_pointers or []), "sys_from": row.sys_from}
        return out

    # -------------------------------------------------------------- search over the graph
    def search(self, question: str, qvec=None, k: int = 10, types: list[str] | None = None) -> list[tuple[uuid.UUID, float, str]]:
        """Keyword and semantic search over node names and summaries at the snapshot (permission-filtered).
        Returns (node id, score, how) with scores in [0, 1]."""
        out: dict[uuid.UUID, tuple[float, str]] = {}
        base = [RemNodeVersion.tenant_id == self.tenant_id, _at(RemNodeVersion, self.seq)]
        vf = self._visible_filter()
        if vf is not None:
            base.append(vf)
        tq = func.websearch_to_tsquery("english", question)
        or_q = func.to_tsquery("english", func.array_to_string(func.tsvector_to_array(func.to_tsvector("english", question)), " | "))
        rank = func.ts_rank_cd(RemNodeVersion.tsv, or_q, 32)
        stmt = select(RemNodeVersion.node_id, rank, RemNodeVersion.acl).where(*base, RemNodeVersion.tsv.op("@@")(or_q))
        if types:
            stmt = stmt.join(RemNode, RemNode.id == RemNodeVersion.node_id).where(RemNode.type.in_(types))
        _ = tq
        rows = self._run(stmt.order_by(rank.desc()).limit(k), label="search_lexical")
        top = max((float(r[1]) for r in rows), default=0.0) or 1.0
        for nid, sc, acl in rows:
            if self._acl_ok(acl):
                out[nid] = (0.5 * float(sc) / top, "keyword")
        if qvec is not None:
            dist = RemNodeVersion.embedding.cosine_distance(list(map(float, qvec)))
            stmt = select(RemNodeVersion.node_id, dist, RemNodeVersion.acl).where(*base, RemNodeVersion.embedding.is_not(None))
            if types:
                stmt = stmt.join(RemNode, RemNode.id == RemNodeVersion.node_id).where(RemNode.type.in_(types))
            for nid, d, acl in self._run(stmt.order_by(dist).limit(k), label="search_vector"):
                if self._acl_ok(acl):
                    sim = 1.0 - float(d)
                    prev = out.get(nid, (0.0, ""))
                    out[nid] = (prev[0] + sim, "keyword+semantic" if prev[1] else "semantic")
        return sorted(((nid, round(sc, 4), how) for nid, (sc, how) in out.items()), key=lambda x: -x[1])[:k]


def current_seq(session: Session, tenant_id: uuid.UUID, counter: CallCounter | None = None) -> int:
    row = session.scalar(select(RemTenantState.last_seq).where(RemTenantState.tenant_id == tenant_id))
    if counter is not None:
        counter.db_calls += 1
    return int(row or 0)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _content(v: dict[str, Any]) -> dict[str, Any]:
    keys = ("name", "summary", "attrs", "project_ids", "department_ids", "scope_id", "sensitivity", "acl", "source_pointers",
            "root_sources", "verification", "authoritative", "valid_from", "valid_to", "review_status")
    return {k: v.get(k) for k in keys}


class GraphWriter:
    """Versioned writes. Call ``begin()`` once per change (event): it takes the tenant lock and the next sequence number,
    which every write of that change shares."""

    def __init__(self, session: Session, tenant_id: uuid.UUID, embedder=None, event_id: uuid.UUID | None = None):
        self.s = session
        self.tenant_id = tenant_id
        self.embedder = embedder
        self.event_id = event_id
        self.seq: int | None = None
        self.changed: dict[uuid.UUID, list[str]] = {}  # node id -> changed field names in this change

    def begin(self) -> int:
        self.s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:t, 7))"), {"t": str(self.tenant_id)})
        st = self.s.get(RemTenantState, self.tenant_id, with_for_update=True)
        if st is None:
            st = RemTenantState(tenant_id=self.tenant_id, last_seq=0)
            self.s.add(st)
        st.last_seq = int(st.last_seq or 0) + 1
        self.s.flush()
        self.seq = st.last_seq
        return self.seq

    def _need_seq(self) -> int:
        if self.seq is None:
            raise RuntimeError("GraphWriter.begin() must be called before writing")
        return self.seq

    # -------------------------------------------------------------- nodes
    def node_id(self, type_: str, key: str) -> uuid.UUID | None:
        return self.s.scalar(select(RemNode.id).where(RemNode.tenant_id == self.tenant_id, RemNode.type == type_, RemNode.key == key))

    def current(self, node_id: uuid.UUID) -> RemNodeVersion | None:
        return self.s.scalar(select(RemNodeVersion).where(RemNodeVersion.node_id == node_id, RemNodeVersion.sys_to.is_(None)))

    def upsert_node(self, type_: str, key: str, *, name: str, scope_id: uuid.UUID, summary: str = "", attrs: dict | None = None,
                    sensitivity: int = 1, acl: dict | None = None, project_ids=None, department_ids=None, source_pointers=None,
                    root_sources=None, verification: str = "unverified", authoritative: bool = True, valid_from=None, valid_to=None,
                    review_status: str | None = None, embed: bool = True) -> tuple[uuid.UUID, int, list[str]]:
        """Create the node or add a version when anything changed. Returns (node id, version, changed field names);
        an identical re-submission changes nothing and returns an empty list."""
        if type_ not in NODE_TYPES:
            raise ValueError(f"unknown node type {type_!r}")
        seq = self._need_seq()
        new = {"name": name, "summary": summary or "", "attrs": attrs or {}, "project_ids": [str(x) for x in project_ids or []],
               "department_ids": [str(x) for x in department_ids or []], "scope_id": str(scope_id), "sensitivity": sensitivity,
               "acl": acl or {}, "source_pointers": source_pointers or [], "root_sources": list(root_sources or []),
               "verification": verification, "authoritative": authoritative, "valid_from": valid_from, "valid_to": valid_to,
               "review_status": review_status}
        nid = self.node_id(type_, key)
        cur = self.current(nid) if nid else None
        if cur is not None:
            old = {"name": cur.name, "summary": cur.summary or "", "attrs": cur.attrs or {}, "project_ids": [str(x) for x in cur.project_ids or []],
                   "department_ids": [str(x) for x in cur.department_ids or []], "scope_id": str(cur.scope_id), "sensitivity": cur.sensitivity,
                   "acl": cur.acl or {}, "source_pointers": cur.source_pointers or [], "root_sources": list(cur.root_sources or []),
                   "verification": cur.verification, "authoritative": cur.authoritative, "valid_from": cur.valid_from,
                   "valid_to": cur.valid_to, "review_status": cur.review_status}
            if _hash(_content(old)) == _hash(_content(new)):
                return nid, cur.version, []
            changed = [k for k in new if _hash(old.get(k)) != _hash(new.get(k)) and k != "attrs"]
            changed += [f"attrs.{a}" for a in sorted(set(old["attrs"]) | set(new["attrs"])) if _hash(old["attrs"].get(a)) != _hash(new["attrs"].get(a))]
            cur.sys_to = seq
            version = cur.version + 1
            emb = cur.embedding if (cur.name == name and (cur.summary or "") == (summary or "")) else None
        else:
            if nid is None:
                node = RemNode(tenant_id=self.tenant_id, type=type_, key=key, created_seq=seq)
                self.s.add(node)
                self.s.flush()
                nid = node.id
            changed, version, emb = ["created"], 1, None
        if emb is None and embed and self.embedder is not None:
            emb = self.embedder.embed([f"{name}. {summary or ''}"])[0]
        nv = RemNodeVersion(tenant_id=self.tenant_id, node_id=nid, version=version, sys_from=seq, name=name, summary=summary or "",
                            attrs=attrs or {}, project_ids=list(project_ids or []), department_ids=list(department_ids or []),
                            scope_id=scope_id, sensitivity=sensitivity, acl=acl or {}, source_pointers=source_pointers or [],
                            root_sources=list(root_sources or []), verification=verification, authoritative=authoritative,
                            valid_from=valid_from, valid_to=valid_to, event_id=self.event_id, review_status=review_status,
                            embedding=emb,
                            tsv=func.to_tsvector("english", f"{name} {summary or ''} {' '.join(str(v) for v in (attrs or {}).values())}"))
        self.s.add(nv)
        self.s.flush()
        self.changed.setdefault(nid, []).extend(changed)
        return nid, version, changed

    def revise(self, node_id: uuid.UUID, **changes) -> list[str]:
        """New version of an existing node with some fields changed (``attrs`` merges)."""
        cur = self.current(node_id)
        if cur is None:
            raise KeyError(node_id)
        node = self.s.get(RemNode, node_id)
        attrs = {**(cur.attrs or {}), **(changes.pop("attrs", None) or {})}
        kw = {"name": cur.name, "summary": cur.summary, "attrs": attrs, "scope_id": cur.scope_id, "sensitivity": cur.sensitivity,
              "acl": cur.acl, "project_ids": cur.project_ids, "department_ids": cur.department_ids, "source_pointers": cur.source_pointers,
              "root_sources": cur.root_sources, "verification": cur.verification, "authoritative": cur.authoritative,
              "valid_from": cur.valid_from, "valid_to": cur.valid_to, "review_status": cur.review_status}
        kw.update(changes)
        _, _, changed = self.upsert_node(node.type, node.key, **kw)
        return changed

    def delete_node(self, node_id: uuid.UUID) -> None:
        """Close the node and every edge touching it. History stays readable at earlier snapshots."""
        seq = self._need_seq()
        self.s.execute(update(RemNodeVersion).where(RemNodeVersion.node_id == node_id, RemNodeVersion.sys_to.is_(None)).values(sys_to=seq))
        self.s.execute(update(RemEdge).where(or_(RemEdge.src_id == node_id, RemEdge.dst_id == node_id), RemEdge.sys_to.is_(None))
                       .values(sys_to=seq))
        self.s.execute(update(RemRoutingEdge).where(or_(RemRoutingEdge.src_id == node_id, RemRoutingEdge.dst_id == node_id),
                                                    RemRoutingEdge.sys_to.is_(None)).values(sys_to=seq))
        self.s.execute(update(RemNode).where(RemNode.id == node_id).values(deleted_seq=seq))
        self.changed.setdefault(node_id, []).append("deleted")

    # -------------------------------------------------------------- edges
    def upsert_edge(self, src: uuid.UUID, kind: str, dst: uuid.UUID, *, provenance: str = "explicit", status: str | None = None,
                    attrs: dict | None = None, source_pointers=None, derivation: dict | None = None, valid_from=None, valid_to=None,
                    source_key: str = "") -> uuid.UUID:
        if kind not in BUSINESS_EDGE_KINDS:
            raise ValueError(f"{kind!r} is not a business relationship; routing shortcuts go through add_routing()")
        if provenance not in PROVENANCE:
            raise ValueError(f"provenance must be one of {PROVENANCE}")
        if provenance in ("rule", "inferred") and not derivation:
            raise ValueError("a derived relationship must record its provenance (rule or model, and its inputs)")
        status = status or ("hypothesis" if provenance == "inferred" else "asserted")
        seq = self._need_seq()
        key = f"{src}|{kind}|{dst}|{provenance}|{source_key}"
        cur = self.s.scalar(select(RemEdge).where(RemEdge.tenant_id == self.tenant_id, RemEdge.edge_key == key, RemEdge.sys_to.is_(None)))
        body = {"status": status, "attrs": attrs or {}, "source_pointers": source_pointers or [], "derivation": derivation or {},
                "valid_from": valid_from, "valid_to": valid_to}
        if cur is not None:
            old = {"status": cur.status, "attrs": cur.attrs or {}, "source_pointers": cur.source_pointers or [],
                   "derivation": cur.derivation or {}, "valid_from": cur.valid_from, "valid_to": cur.valid_to}
            if _hash(old) == _hash(body):
                return cur.id
            cur.sys_to = seq
        e = RemEdge(tenant_id=self.tenant_id, src_id=src, dst_id=dst, kind=kind, provenance=provenance, edge_key=key, sys_from=seq,
                    event_id=self.event_id, **body)
        self.s.add(e)
        self.s.flush()
        for n in (src, dst):
            self.changed.setdefault(n, []).append(f"edge:{kind}")
        return e.id

    def close_edges(self, src: uuid.UUID | None = None, dst: uuid.UUID | None = None, kind: str | None = None) -> int:
        seq = self._need_seq()
        conds = [RemEdge.tenant_id == self.tenant_id, RemEdge.sys_to.is_(None)]
        if src is not None:
            conds.append(RemEdge.src_id == src)
        if dst is not None:
            conds.append(RemEdge.dst_id == dst)
        if kind is not None:
            conds.append(RemEdge.kind == kind)
        res = self.s.execute(update(RemEdge).where(*conds).values(sys_to=seq))
        return res.rowcount or 0

    def add_routing(self, src: uuid.UUID, dst: uuid.UUID, builder: str, weight: float = 1.0) -> None:
        self.s.add(RemRoutingEdge(tenant_id=self.tenant_id, src_id=src, dst_id=dst, builder=builder, weight=weight, sys_from=self._need_seq()))

    # -------------------------------------------------------------- exact values
    def set_stock(self, product_id: uuid.UUID, holder_id: uuid.UUID, *, on_hand: float, reserved: float = 0.0,
                  scope_id: uuid.UUID, sensitivity: int = 1, source_pointers=None) -> bool:
        seq = self._need_seq()
        cur = self.s.scalar(select(RemStock).where(RemStock.tenant_id == self.tenant_id, RemStock.product_id == product_id,
                                                   RemStock.holder_id == holder_id, RemStock.sys_to.is_(None)))
        if cur is not None:
            if float(cur.qty_on_hand) == float(on_hand) and float(cur.qty_reserved or 0) == float(reserved) and cur.scope_id == scope_id \
                    and cur.sensitivity == sensitivity:
                return False
            cur.sys_to = seq
        self.s.add(RemStock(tenant_id=self.tenant_id, product_id=product_id, holder_id=holder_id, qty_on_hand=on_hand,
                            qty_reserved=reserved, scope_id=scope_id, sensitivity=sensitivity, source_pointers=source_pointers or [],
                            sys_from=seq, event_id=self.event_id))
        self.s.flush()
        for n in (product_id, holder_id):
            self.changed.setdefault(n, []).append("stock")
        return True
