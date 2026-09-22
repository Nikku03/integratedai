"""Organisation views over the memory bank: what the bank knows about an entity,
a document, or a scope, assembled from the records it already holds.

Nothing here is generated; every value is a record, a count, or an edge, so the
views are as cheap as the indexes behind them (JSONB containment on
``entity_ids``, the ``mentions`` edges, the scope/type index) and as trustworthy
as the records. They are the browsing layer a "company brain" needs next to
question answering: a supplier page, a document card, a department digest.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import cast, func, or_, select
from sqlalchemy.orm import Session, defer

from cie.core.models import Document, LinkKind, MemoryRecord, RecordLink, RecordType, Scope
from cie.core.util import utcnow
from cie.governance.permissions import Visibility
from cie.memory.entities import normalise
from cie.memory.records import current_only

ENTITY_TYPES = (RecordType.organization, RecordType.person)
_LIGHT = (defer(MemoryRecord.embedding), defer(MemoryRecord.tsv))


def _brief(r: MemoryRecord) -> dict[str, Any]:
    return {"id": str(r.id), "type": r.type.value, "summary": r.summary, "content": r.content or {},
            "document_id": str(r.source_document_id) if r.source_document_id else None,
            "valid_from": r.valid_from, "valid_to": r.valid_to, "recorded_at": r.recorded_at,
            "confidence": r.confidence, "verification": r.verification.value,
            "superseded": r.superseded_by_id is not None, "scope_id": str(r.scope_id)}


def _visible(vis: Visibility, tenant_id: uuid.UUID):
    return (MemoryRecord.tenant_id == tenant_id, MemoryRecord.deleted_at.is_(None),
            vis.sql_filter(MemoryRecord.scope_id, MemoryRecord.sensitivity))


def find_entities(session: Session, tenant_id: uuid.UUID, vis: Visibility, q: str, rtype: RecordType | None = None,
                  limit: int = 10) -> list[dict[str, Any]]:
    """Entities whose name or recorded aliases resemble ``q`` (trigram index on the
    canonical name, keyword index on the normalised aliases), most similar first."""
    key = normalise(q)
    sim = func.similarity(MemoryRecord.summary, q)
    stmt = (select(MemoryRecord, sim).options(*_LIGHT)
            .where(*_visible(vis, tenant_id), MemoryRecord.superseded_by_id.is_(None),
                   MemoryRecord.type.in_([rtype] if rtype else list(ENTITY_TYPES)),
                   or_(MemoryRecord.summary.op("%")(q), MemoryRecord.summary.ilike(f"%{q}%"),
                       MemoryRecord.keywords.op("&&")(cast([key] if key else [q.lower()], MemoryRecord.keywords.type))))
            .order_by(sim.desc()).limit(limit))
    out = []
    for r, s in session.execute(stmt):
        if vis.can_read(r.scope_id, r.sensitivity, r.acl):
            out.append({**_brief(r), "similarity": round(float(s), 3), "aliases": list((r.content or {}).get("aliases", []))})
    return out


def _referencing(session: Session, tenant_id: uuid.UUID, vis: Visibility, entity: MemoryRecord, at: datetime | None,
                 include_history: bool, limit: int):
    """Records that carry the entity in ``entity_ids`` (JSONB containment, GIN-indexed)
    or point at it with a ``mentions`` edge (indexed by destination)."""
    eid = str(entity.id)
    mentioned = select(RecordLink.src_id).where(RecordLink.dst_id == entity.id, RecordLink.kind == LinkKind.mentions)
    stmt = (select(MemoryRecord).options(*_LIGHT)
            .where(*_visible(vis, tenant_id), MemoryRecord.id != entity.id,
                   or_(MemoryRecord.entity_ids.contains([eid]), MemoryRecord.id.in_(mentioned))))
    if not include_history:
        stmt = current_only(stmt, at).where(MemoryRecord.superseded_by_id.is_(None))
    stmt = stmt.order_by(MemoryRecord.valid_from.desc().nulls_last(), MemoryRecord.recorded_at.desc()).limit(limit)
    return [r for r in session.scalars(stmt) if vis.can_read(r.scope_id, r.sensitivity, r.acl)]


def entity_profile(session: Session, tenant_id: uuid.UUID, vis: Visibility, entity: MemoryRecord,
                   at: datetime | None = None, include_history: bool = False, per_type: int = 5,
                   limit: int = 400) -> dict[str, Any]:
    """Everything the addressable memory currently holds about one entity, grouped by
    record type, newest first, with the documents involved, open questions and
    recorded contradictions. Superseded records are left out unless history is asked
    for; ``at`` gives the profile as of a date (bitemporal validity)."""
    recs = _referencing(session, tenant_id, vis, entity, at, include_history, limit)
    by_type: dict[str, list[dict[str, Any]]] = {}
    counts: Counter = Counter()
    for r in recs:
        counts[r.type.value] += 1
        if len(by_type.setdefault(r.type.value, [])) < per_type:
            by_type[r.type.value].append(_brief(r))
    doc_ids = {r.source_document_id for r in recs if r.source_document_id} | ({entity.source_document_id} if entity.source_document_id else set())
    docs = []
    if doc_ids:
        drows = session.execute(select(Document.id, Document.title, Document.doc_type, Document.version, Document.ingested_at, Document.scope_id,
                                       Document.sensitivity, Document.acl)
                                .where(Document.id.in_(list(doc_ids)), Document.deleted_at.is_(None))
                                .order_by(Document.ingested_at.desc()).limit(50)).all()
        docs = [{"id": str(d.id), "title": d.title, "doc_type": d.doc_type, "version": d.version, "ingested_at": d.ingested_at}
                for d in drows if vis.can_read(d.scope_id, d.sensitivity, d.acl)]
    ids = [r.id for r in recs]
    conflicts: list[dict[str, Any]] = []
    if ids:
        crow = session.execute(select(RecordLink.src_id, RecordLink.dst_id).where(
            RecordLink.kind == LinkKind.contradicts, or_(RecordLink.src_id.in_(ids), RecordLink.dst_id.in_(ids))).limit(50)).all()
        conflicts = [{"a": str(a), "b": str(b)} for a, b in crow]
    latest = max((r.recorded_at for r in recs), default=entity.recorded_at)
    return {"entity": {**_brief(entity), "aliases": list((entity.content or {}).get("aliases", []))},
            "as_of": at or utcnow(), "record_count": len(recs), "counts_by_type": dict(counts), "records_by_type": by_type,
            "documents": docs, "open_questions": [x for x in by_type.get("open_question", [])],
            "contradictions": conflicts, "last_recorded_at": latest, "truncated": len(recs) >= limit}


def document_card(session: Session, tenant_id: uuid.UUID, vis: Visibility, document: Document, per_type: int = 5) -> dict[str, Any]:
    """What one document contributed to memory: parties and signatories, key values,
    deadlines, obligations, open questions, conflicts, and its version chain."""
    recs = [r for r in session.scalars(select(MemoryRecord).options(*_LIGHT).where(
        *_visible(vis, tenant_id), MemoryRecord.source_document_id == document.id).order_by(MemoryRecord.recorded_at))
        if vis.can_read(r.scope_id, r.sensitivity, r.acl)]
    by_type: dict[str, list[dict[str, Any]]] = {}
    counts: Counter = Counter()
    for r in recs:
        counts[r.type.value] += 1
        if len(by_type.setdefault(r.type.value, [])) < per_type:
            by_type[r.type.value].append(_brief(r))
    ids = [r.id for r in recs]
    n_conflicts = 0
    if ids:
        n_conflicts = session.scalar(select(func.count()).select_from(RecordLink).where(
            RecordLink.kind == LinkKind.contradicts, or_(RecordLink.src_id.in_(ids), RecordLink.dst_id.in_(ids)))) or 0
    versions = session.execute(select(Document.id, Document.version, Document.ingested_at).where(
        Document.family_id == document.family_id, Document.deleted_at.is_(None)).order_by(Document.version)).all()
    return {"document": {"id": str(document.id), "title": document.title, "doc_type": document.doc_type, "version": document.version,
                         "status": document.status, "ingested_at": document.ingested_at, "scope_id": str(document.scope_id)},
            "record_count": len(recs), "counts_by_type": dict(counts),
            "parties": by_type.get("organization", []), "people": by_type.get("person", []),
            "values": by_type.get("metric", []), "deadlines": by_type.get("deadline", []),
            "obligations": by_type.get("requirement", []), "risks": by_type.get("risk", []),
            "decisions": by_type.get("decision", []), "open_questions": by_type.get("open_question", []),
            "superseded_records": sum(1 for r in recs if r.superseded_by_id is not None), "contradiction_edges": n_conflicts,
            "versions": [{"id": str(i), "version": v, "ingested_at": t} for i, v, t in versions]}


def scope_digest(session: Session, tenant_id: uuid.UUID, vis: Visibility, scope: Scope, at: datetime | None = None,
                 top: int = 10) -> dict[str, Any]:
    """What a scope's memory holds: record and document counts by type, the most
    mentioned entities, the newest documents, open questions and recorded conflicts.
    Counts come from the scope/type index; the entity ranking from the ``mentions``
    edges, so no record text is read."""
    from cie.memory.scopes import descendants

    scope_ids = [s for s in [scope.id] + [d.id for d in descendants(session, scope)] if s in vis.scope_ids]
    if not scope_ids:
        return {"scope": {"id": str(scope.id), "name": scope.name}, "records_by_type": {}, "documents": 0, "top_entities": []}
    rec_scope = (MemoryRecord.tenant_id == tenant_id, MemoryRecord.deleted_at.is_(None), MemoryRecord.scope_id.in_(scope_ids),
                 vis.sql_filter(MemoryRecord.scope_id, MemoryRecord.sensitivity))
    counts = dict(session.execute(select(MemoryRecord.type, func.count()).where(*rec_scope).group_by(MemoryRecord.type)).all())
    current = session.scalar(current_only(select(func.count()).select_from(MemoryRecord).where(*rec_scope), at)
                             .where(MemoryRecord.superseded_by_id.is_(None))) or 0
    n_docs = session.scalar(select(func.count()).select_from(Document).where(
        Document.tenant_id == tenant_id, Document.deleted_at.is_(None), Document.scope_id.in_(scope_ids),
        vis.sql_filter(Document.scope_id, Document.sensitivity))) or 0
    doc_types = dict(session.execute(select(Document.doc_type, func.count()).where(
        Document.tenant_id == tenant_id, Document.deleted_at.is_(None), Document.scope_id.in_(scope_ids)).group_by(Document.doc_type)).all())
    # most mentioned entities: count mentions edges whose destination is an entity in these scopes
    ent = select(MemoryRecord.id, MemoryRecord.summary, MemoryRecord.type).where(*rec_scope, MemoryRecord.type.in_(list(ENTITY_TYPES))).subquery()
    top_rows = session.execute(
        select(ent.c.id, ent.c.summary, ent.c.type, func.count(RecordLink.id).label("n"))
        .join(RecordLink, (RecordLink.dst_id == ent.c.id) & (RecordLink.kind == LinkKind.mentions))
        .group_by(ent.c.id, ent.c.summary, ent.c.type).order_by(func.count(RecordLink.id).desc()).limit(top)).all()
    newest = session.execute(select(Document.id, Document.title, Document.doc_type, Document.ingested_at).where(
        Document.tenant_id == tenant_id, Document.deleted_at.is_(None), Document.scope_id.in_(scope_ids),
        vis.sql_filter(Document.scope_id, Document.sensitivity)).order_by(Document.ingested_at.desc()).limit(top)).all()
    n_conflicts = session.scalar(select(func.count()).select_from(RecordLink).join(MemoryRecord, MemoryRecord.id == RecordLink.src_id).where(
        RecordLink.kind == LinkKind.contradicts, MemoryRecord.scope_id.in_(scope_ids), MemoryRecord.tenant_id == tenant_id)) or 0
    return {"scope": {"id": str(scope.id), "name": scope.name, "kind": scope.kind.value, "descendants": len(scope_ids)},
            "as_of": at or utcnow(), "records_by_type": {t.value: n for t, n in counts.items()}, "records_total": sum(counts.values()),
            "records_current": current, "documents": n_docs, "documents_by_type": doc_types,
            "top_entities": [{"id": str(i), "name": s, "type": t.value, "mentions": n} for i, s, t, n in top_rows],
            "newest_documents": [{"id": str(i), "title": t, "doc_type": d, "ingested_at": a} for i, t, d, a in newest],
            "open_questions": counts.get(RecordType.open_question, 0), "contradiction_edges": n_conflicts}
