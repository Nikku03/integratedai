"""Automatic sparse graph construction for records derived from one document.

Edges added (all local, no all-to-all):
* every derived record ``part_of`` the document record,
* records in the same section ``relates_to`` each other (capped),
* deadlines/metrics/requirements ``derived_from`` the clause record of their section,
* entity mentions via ``cie.memory.entities``,
* a contradiction edge when two metric records of the same name in the same
  document disagree on the value.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import LinkKind, MemoryRecord, RecordType
from cie.memory.records import contradict, link

MAX_SIBLINGS = 4


def autolink(session: Session, document_record: MemoryRecord, records: list[MemoryRecord],
             entities: dict[str, MemoryRecord] | None = None) -> dict[str, int]:
    """``entities``: name -> canonical entity record (created or inherited)."""
    stats = defaultdict(int)
    entities = entities or {}
    by_section: dict[str | None, list[MemoryRecord]] = defaultdict(list)
    for r in records:
        if r.id == document_record.id:
            continue
        link(session, r, document_record, LinkKind.part_of)
        stats["part_of"] += 1
        sec = (r.source_locations or [{}])[0].get("section_id")
        by_section[sec].append(r)
    for recs in by_section.values():
        clause = next((r for r in recs if r.type == RecordType.contract_clause), None)
        for r in recs:
            if clause is not None and r.id != clause.id and r.type in (RecordType.deadline, RecordType.metric, RecordType.requirement, RecordType.risk):
                link(session, r, clause, LinkKind.derived_from)
                stats["derived_from"] += 1
        # sibling relations, capped so a long section does not become a clique
        core = [r for r in recs if r.type not in (RecordType.organization, RecordType.person)][:MAX_SIBLINGS + 1]
        for i, a in enumerate(core):
            for b in core[i + 1:i + 1 + MAX_SIBLINGS]:
                link(session, a, b, LinkKind.relates_to, weight=0.5)
                stats["relates_to"] += 1
    # entity mentions: link every non-entity record whose text names a known entity
    for r in records:
        if r.type in (RecordType.organization, RecordType.person, RecordType.document):
            continue
        text = f"{r.summary} {r.detail}"
        for name, ent in entities.items():
            first = name.split()[0]
            if (name in text or (len(first) > 4 and first in text)) and ent.id != r.id:
                link(session, r, ent, LinkKind.mentions)
                if str(ent.id) not in (r.entity_ids or []):
                    r.entity_ids = list(r.entity_ids or []) + [str(ent.id)]
                stats["mentions"] += 1
    # inherited entities also belong to this document's graph neighbourhood
    for ent in entities.values():
        if ent not in records:
            link(session, document_record, ent, LinkKind.mentions)
    # same-document metric disagreement
    metrics: dict[str, list[MemoryRecord]] = defaultdict(list)
    for r in records:
        if r.type == RecordType.metric and (r.content or {}).get("name") and "value" in (r.content or {}):
            metrics[r.content["name"]].append(r)
    for name, ms in metrics.items():
        if name in ("amount", "percentage"):
            continue
        vals = {float(m.content["value"]) for m in ms}
        if len(vals) > 1 and len(ms) == 2:
            contradict(session, ms[0], ms[1], f"metric '{name}' has conflicting values {sorted(vals)} in the same document",
                       producing_agent="autolink_v1")
            stats["contradictions"] += 1
    stats["cross_document_contradictions"] = detect_cross_document_contradictions(session, records)
    return dict(stats)


_TOPIC_STOP = {"shall", "must", "party", "parties", "agreement", "company", "supplier", "this", "that", "with", "under",
               "than", "later", "days", "written", "either", "may", "any", "case", "before", "after"}


def _topic(r: MemoryRecord) -> set[str]:
    import re

    words = re.findall(r"[a-z]{5,}", f"{r.summary} {r.detail}".lower())
    return {w[:6] for w in words if w not in _TOPIC_STOP}


def _value(r: MemoryRecord):
    c = r.content or {}
    for k in ("duration_days", "value", "date"):
        if c.get(k) is not None:
            return k, c[k]
    return None, None


def _doc_entities(session: Session, doc_id) -> set[str]:
    """Entities mentioned anywhere in a document (a clause inherits its document's parties)."""
    out: set[str] = set()
    for (ids,) in session.execute(select(MemoryRecord.entity_ids).where(MemoryRecord.source_document_id == doc_id)):
        out.update(ids or [])
    return out


def _discriminative_entities(session: Session, tenant_id, max_doc_share: float = 0.34, min_docs_for_share: int = 4) -> set[str] | None:
    """Entity ids that appear in a minority of the tenant's documents. An entity
    present in most documents (the company itself, its CFO) identifies nothing.
    Returns None when the tenant is too small to judge (then all entities count)."""
    from sqlalchemy import func

    rows = session.execute(select(MemoryRecord.source_document_id, MemoryRecord.entity_ids).where(
        MemoryRecord.tenant_id == tenant_id, MemoryRecord.source_document_id.is_not(None), MemoryRecord.deleted_at.is_(None))).all()
    docs_by_entity: dict[str, set] = {}
    all_docs = set()
    for doc_id, ids in rows:
        all_docs.add(doc_id)
        for e in ids or []:
            docs_by_entity.setdefault(e, set()).add(doc_id)
    n_docs = len(all_docs)
    _ = func
    if n_docs < min_docs_for_share:
        return None
    return {e for e, ds in docs_by_entity.items() if len(ds) / n_docs <= max_doc_share}


def detect_cross_document_contradictions(session: Session, records: list[MemoryRecord], min_shared: int = 2) -> int:
    """Conservative check: a new deadline/metric record contradicts an existing
    current record of the same type from *another document* in the same scope
    tree when they share the same value kind, ≥ ``min_shared`` topic words and
    a mentioned entity, but carry different values."""
    from cie.core.models import RecordType
    from cie.memory.scopes import addressable_scope_ids

    n = 0
    doc_ents: dict = {}
    discriminative = None
    if records:
        discriminative = _discriminative_entities(session, records[0].tenant_id)
    for r in records:
        if r.type not in (RecordType.deadline, RecordType.metric):
            continue
        kind, val = _value(r)
        if kind is None:
            continue
        from cie.core.models import Document

        my_doc = session.get(Document, r.source_document_id)
        if my_doc is None or (my_doc.doc_type or "").lower() in ("draft", "template", "superseded"):
            continue  # a never-executed draft contradicts nothing
        if r.source_document_id not in doc_ents:
            doc_ents[r.source_document_id] = _doc_entities(session, r.source_document_id)
        # record-level entities always count; document-level ones only when the tenant is large enough
        # to know which entities are discriminative (the company itself appears in every contract)
        my_ents = set(r.entity_ids or [])
        if discriminative is not None:
            my_ents |= doc_ents[r.source_document_id] & discriminative
        if not my_ents:
            continue
        scopes = list(addressable_scope_ids(session, r.scope_id))
        peers = session.scalars(select(MemoryRecord).where(
            MemoryRecord.tenant_id == r.tenant_id, MemoryRecord.type == r.type, MemoryRecord.id != r.id,
            MemoryRecord.scope_id.in_(scopes), MemoryRecord.deleted_at.is_(None), MemoryRecord.superseded_by_id.is_(None),
            MemoryRecord.source_document_id != r.source_document_id, MemoryRecord.source_document_id.is_not(None)))
        mine = _topic(r)
        for p in peers:
            pk, pv = _value(p)
            if pk != kind or str(pv) == str(val):
                continue
            p_doc = session.get(Document, p.source_document_id)
            if p_doc is None or (p_doc.doc_type or "").lower() in ("draft", "template", "superseded"):
                continue
            if p_doc.family_id == my_doc.family_id:
                continue  # versions of one document are supersessions, not contradictions
            governing = ("contract", "agreement", "policy", "amendment")
            if (my_doc.doc_type or "").lower() in governing and (p_doc.doc_type or "").lower() in governing:
                continue  # two executed instruments are separate documents, not a contradiction about one of them
            if p.source_document_id not in doc_ents:
                doc_ents[p.source_document_id] = _doc_entities(session, p.source_document_id)
            p_ents = set(p.entity_ids or [])
            if discriminative is not None:
                p_ents |= doc_ents[p.source_document_id] & discriminative
            if not (p_ents & my_ents):
                continue
            if len(mine & _topic(p)) < min_shared:
                continue
            if p.type == RecordType.metric and (p.content or {}).get("name") != (r.content or {}).get("name"):
                continue
            contradict(session, r, p, f"{r.type.value} disagrees across documents: {val} vs {pv}", producing_agent="autolink_v1")
            n += 1
            if n >= 3 * (len(records) or 1):
                break
    return n
