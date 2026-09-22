"""Dynamic memory: the bank forms new connections and shapes from its own use.

Structural plasticity, after the STDP picture: records that fire together in an
answer (the packet's best-supported records and the records the answer cites)
are wired together. A new ``coactivated`` link is oriented from the lower-ranked
record to the higher-ranked one, so evidence flows towards the record that
answered and that record becomes the *sink* of the simplex the group forms, the
Blue Brain reading of an output neuron. Every co-firing potentiates the link;
links that stop co-firing decay and are pruned; a record keeps at most a fixed
number of dynamic links (the weakest go), so the graph stays sparse.

Shapes are what repeated use builds: a group asked about together becomes a full
clique (a directed simplex with the answer as its sink); groups that share
records form larger complexes, and cycles of them that no clique fills are the
bank's cavities. ``shapes`` reports them; ``reset`` removes every dynamic link.

Everything is audited and reversible: dynamic links carry ``evidence.dynamic``.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cie.core.models import LinkKind, MemoryRecord, RecordLink
from cie.core.util import utcnow
from cie.governance.audit import audit
from cie.governance.permissions import Visibility
from cie.topology.cliques import directed_flag_complex

INITIAL_WEIGHT = 0.3
LTP = 0.2  # fraction of the way to the cap per co-firing
CAP = 2.0
DECAY = 0.08  # fraction of the way to zero for a neighbouring dynamic link that did not fire
PRUNE_BELOW = 0.12


def fired_records(packet_items: list[dict], citations: list[dict], *, max_fired: int = 6, min_support: float = 0.5,
                  max_docs: int = 1) -> list[uuid.UUID]:
    """The records that fired: the ones the answer cites, then the packet's
    best-supported records, all *from the documents the answer drew on* (the first
    citation's document; ``max_docs`` of them for conflict and comparison answers),
    ranked so the first is the sink the others will point to.

    The document gate is the difference between memory and confusion: a question
    about one supplier's penalty activates every similar penalty clause in the
    bank, and wiring those together would build shortcuts between suppliers that
    have nothing to do with each other. What fired together *in the answer's
    context* is what gets wired."""
    order: list[uuid.UUID] = []
    seen: set = set()
    by_id = {it["id"]: it for it in packet_items if it.get("kind") == "record"}
    docs: list = []
    for c in citations:
        rid = str(c.get("item_id") or "")
        if not rid or c.get("kind", "record") != "record" or rid in seen or rid not in by_id:
            continue
        doc = by_id[rid].get("document_id")
        if doc and doc not in docs:
            if len(docs) >= max_docs:
                continue  # a citation from a further document: not this answer's context
            docs.append(doc)
        seen.add(rid)
        order.append(uuid.UUID(rid))
    if not order:
        return []
    for it in packet_items:
        if it.get("kind") != "record" or (it.get("support") or 0) < min_support:
            continue
        if docs and it.get("document_id") not in docs:
            continue
        if it["id"] not in seen:
            seen.add(it["id"])
            order.append(uuid.UUID(it["id"]))
        if len(order) >= max_fired:
            break
    return order[:max_fired]


def observe(session: Session, *, tenant_id: uuid.UUID, principal_id: uuid.UUID | None, fired: list[uuid.UUID], query: str,
            max_degree: int = 12) -> dict[str, Any]:
    """Wire the records that fired together. ``fired`` is ranked best first."""
    if len(fired) < 2:
        return {"formed": 0, "potentiated": 0, "pruned": 0}
    fired_set = set(fired)
    rank = {rid: i for i, rid in enumerate(fired)}
    links = list(session.scalars(select(RecordLink).where(
        RecordLink.kind == LinkKind.coactivated, or_(RecordLink.src_id.in_(fired), RecordLink.dst_id.in_(fired)))))
    existing: dict[frozenset, RecordLink] = {}
    touching: dict[uuid.UUID, list[RecordLink]] = {}
    for link in links:
        existing[frozenset((link.src_id, link.dst_id))] = link
        for rid in (link.src_id, link.dst_id):
            if rid in fired_set:
                touching.setdefault(rid, []).append(link)
    now = utcnow()
    formed = potentiated = pruned = 0
    fired_pairs: set[frozenset] = set()
    for i, a in enumerate(fired):
        for b in fired[i + 1:]:
            pair = frozenset((a, b))
            fired_pairs.add(pair)
            link = existing.get(pair)
            if link is not None:
                link.weight = float(link.weight) + LTP * (CAP - float(link.weight))
                ev = dict(link.evidence or {})
                ev["coactivations"] = int(ev.get("coactivations", 1)) + 1
                ev["last"] = now.isoformat()
                link.evidence = ev
                potentiated += 1
                continue
            # orient towards the better-ranked record: evidence flows to the answer, which becomes the sink
            src, dst = (b, a) if rank[a] < rank[b] else (a, b)
            link = RecordLink(tenant_id=tenant_id, src_id=src, dst_id=dst, kind=LinkKind.coactivated, weight=INITIAL_WEIGHT,
                              justification=f"fired together answering: {query[:120]}",
                              evidence={"dynamic": True, "coactivations": 1, "first": now.isoformat(), "last": now.isoformat()})
            session.add(link)
            existing[pair] = link
            touching.setdefault(src, []).append(link)
            touching.setdefault(dst, []).append(link)
            formed += 1
    # decay the dynamic links of the fired records that did not fire this time; prune the faded and the excess
    for rid in fired:
        mine = touching.get(rid, [])
        for link in mine:
            if frozenset((link.src_id, link.dst_id)) not in fired_pairs:
                link.weight = float(link.weight) * (1 - DECAY)
        alive = []
        for link in mine:
            if float(link.weight) < PRUNE_BELOW:
                session.delete(link)
                pruned += 1
            else:
                alive.append(link)
        if len(alive) > max_degree:
            for link in sorted(alive, key=lambda x: float(x.weight))[: len(alive) - max_degree]:
                session.delete(link)
                pruned += 1
    session.flush()
    audit(session, tenant_id=tenant_id, principal_id=principal_id, action="memory.wire", resource_kind="record_links",
          details={"fired": [str(r) for r in fired], "formed": formed, "potentiated": potentiated, "pruned": pruned})
    return {"formed": formed, "potentiated": potentiated, "pruned": pruned}


def shapes(session: Session, tenant_id: uuid.UUID, vis: Visibility, limit: int = 20, max_links: int = 5000) -> dict[str, Any]:
    """The shapes the bank has formed: the directed flag complex of its dynamic links
    (the strongest ``max_links``), with the highest-dimensional simplices and their
    sinks, permission-filtered."""
    links = list(session.execute(select(RecordLink.src_id, RecordLink.dst_id, RecordLink.weight, RecordLink.evidence).where(
        RecordLink.tenant_id == tenant_id, RecordLink.kind == LinkKind.coactivated).order_by(RecordLink.weight.desc()).limit(max_links)).all())
    if not links:
        return {"dynamic_links": 0, "records": 0, "simplices_by_dim": {}, "max_dim": 0, "cavities": 0, "shapes": []}
    ids = {a for a, _, _, _ in links} | {b for _, b, _, _ in links}
    recs = {r.id: r for r in session.scalars(select(MemoryRecord).where(MemoryRecord.id.in_(list(ids)), MemoryRecord.deleted_at.is_(None)))}
    visible = {rid for rid, r in recs.items() if vis.can_read(r.scope_id, r.sensitivity, r.acl)}
    edges = [(a, b) for a, b, _, _ in links if a in visible and b in visible]
    cx = directed_flag_complex(sorted(visible, key=str), edges, max_dim=8, max_simplices=100_000)
    weight = {frozenset((a, b)): float(w) for a, b, w, _ in links}
    top = sorted(cx.simplices, key=lambda sx: (-(len(sx) - 1), -sum(weight.get(frozenset((sx[i], sx[j])), 0.0)
                                                                    for i in range(len(sx)) for j in range(i + 1, len(sx)))))
    out_shapes = []
    seen_sets: set[frozenset] = set()
    for sx in top:
        key = frozenset(sx)
        if key in seen_sets or any(key < other for other in seen_sets):
            continue  # report maximal simplices only
        seen_sets.add(key)
        out_shapes.append({"dimension": len(sx) - 1, "sink": _brief(recs[sx[-1]]), "source": _brief(recs[sx[0]]),
                           "members": [_brief(recs[v]) for v in sx],
                           "strength": round(sum(weight.get(frozenset((sx[i], sx[j])), 0.0) for i in range(len(sx)) for j in range(i + 1, len(sx))), 3)})
        if len(out_shapes) >= limit:
            break
    degree = Counter()
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    return {"dynamic_links": len(links), "records": len(visible), "simplices_by_dim": dict(sorted(cx.by_dim.items())), "max_dim": max(cx.by_dim, default=0),
            "cavities": cx.betti1, "max_degree": max(degree.values(), default=0), "truncated": cx.truncated or len(links) >= max_links,
            "shapes": out_shapes}


def reset(session: Session, tenant_id: uuid.UUID, principal_id: uuid.UUID | None = None) -> int:
    n = 0
    for link in session.scalars(select(RecordLink).where(RecordLink.tenant_id == tenant_id, RecordLink.kind == LinkKind.coactivated)):
        session.delete(link)
        n += 1
    session.flush()
    audit(session, tenant_id=tenant_id, principal_id=principal_id, action="memory.reset_dynamic", resource_kind="record_links", details={"removed": n})
    return n


def _brief(r: MemoryRecord) -> dict[str, Any]:
    return {"id": str(r.id), "type": r.type.value, "summary": r.summary[:120], "document_id": str(r.source_document_id) if r.source_document_id else None}
