"""Exact lookups: ids, clause numbers, entity names, keywords, quoted phrases."""

from __future__ import annotations

import uuid

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from cie.core.models import MemoryRecord, RecordType
from cie.retrieval.intent import Intent

_ENTITY_TYPES = [RecordType.person, RecordType.organization, RecordType.entity, RecordType.project]


def lookup(session: Session, intent: Intent, query: str, base_filter, k: int = 30) -> list[tuple[uuid.UUID, float]]:
    hits: dict[uuid.UUID, float] = {}
    if intent.record_ids:
        for rid in session.scalars(select(MemoryRecord.id).where(base_filter, MemoryRecord.id.in_(intent.record_ids))):
            hits[rid] = 10.0
    for num in intent.clause_numbers:
        stmt = select(MemoryRecord.id).where(base_filter, MemoryRecord.type == RecordType.contract_clause,
                                             MemoryRecord.content["clause_number"].astext == num)
        for rid in session.scalars(stmt.limit(k)):
            hits[rid] = max(hits.get(rid, 0), 5.0)
        # clauses nested under a section (e.g. 2.2 inside "2. Term"): the number is a token in the GIN-indexed tsvector
        stmt2 = select(MemoryRecord.id).where(base_filter, MemoryRecord.tsv.op("@@")(func.plainto_tsquery("english", num)))
        for rid in session.scalars(stmt2.limit(k)):
            hits[rid] = max(hits.get(rid, 0), 3.0)
    for phrase in intent.quoted:
        # phrase search through the GIN index, then confirm the literal substring on the few candidates
        stmt = (select(MemoryRecord.id, MemoryRecord.summary, MemoryRecord.detail)
                .where(base_filter, MemoryRecord.tsv.op("@@")(func.phraseto_tsquery("english", phrase))).limit(k * 2))
        low = phrase.lower()
        for rid, summ, det in session.execute(stmt):
            if low in (summ or "").lower() or low in (det or "").lower():
                hits[rid] = max(hits.get(rid, 0), 4.0)
    # entity names by trigram similarity against capitalised tokens in the query (the % operator uses the GIN trigram index)
    caps = _capitalised_spans(query)
    for name in caps:
        # cheap exact substring first (trigram GIN serves ILIKE); similarity only when nothing matches literally
        found = list(session.scalars(select(MemoryRecord.id).where(base_filter, MemoryRecord.type.in_(_ENTITY_TYPES),
                                                                    MemoryRecord.summary.ilike(f"%{name}%")).limit(5)))
        for rid in found:
            hits[rid] = max(hits.get(rid, 0), 2.9)  # locates an entity; not evidence for the question (support needs >= 3.0)
        if found:
            continue
        sim = func.similarity(MemoryRecord.summary, name)
        stmt = (select(MemoryRecord.id, sim).where(base_filter, MemoryRecord.type.in_(_ENTITY_TYPES),
                                                   MemoryRecord.summary.op("%")(name))
                .order_by(sim.desc()).limit(5))
        # fuzzy matching over every entity summary is bounded: on a cold cache at a million rows it can take seconds
        from sqlalchemy import text as _text

        try:
            session.execute(_text("SAVEPOINT ent_sim"))
            session.execute(_text("SET LOCAL statement_timeout = '400ms'"))
            rows = session.execute(stmt).all()
            session.execute(_text("SET LOCAL statement_timeout = 0"))
            session.execute(_text("RELEASE SAVEPOINT ent_sim"))
        except Exception:  # noqa: BLE001 - the bound is the point
            session.execute(_text("ROLLBACK TO SAVEPOINT ent_sim"))
            rows = []
        for rid, s in rows:
            if float(s) > 0.35:
                hits[rid] = max(hits.get(rid, 0), 2.0 + float(s))
    # keyword overlap (GIN index on the keywords array)
    kws = [w.lower() for w in query.split() if len(w) > 3][:8]
    if kws:
        stmt = (select(MemoryRecord.id).where(base_filter, MemoryRecord.keywords.op("&&")(cast(kws, MemoryRecord.keywords.type)))
                .limit(k))
        for rid in session.scalars(stmt):
            hits[rid] = max(hits.get(rid, 0), 1.0)
    return sorted(hits.items(), key=lambda kv: -kv[1])[:k]


def _capitalised_spans(q: str) -> list[str]:
    import re

    spans = re.findall(r"\b([A-Z][A-Za-z0-9&'\-]+(?:\s+(?:of|and|&|the)?\s*[A-Z][A-Za-z0-9&'\-\.]+){0,4}(?:\s+\d{1,4})?)", q)
    out = []
    for s in spans:
        words = s.split()
        while words and (words[0].lower() in _DATE_WORDS or words[0].isdigit()):
            words = words[1:]  # "March 1" is a date, not a name; "May Northwind ..." still names Northwind
        s = " ".join(words)
        if len(s) > 3 and s.lower() not in ("what", "when", "who", "which", "how", "list", "compare", "does", "is"):
            out.append(s)
    return out[:5]


_DATE_WORDS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
               "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}


def by_ids(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, MemoryRecord]:
    """Load candidate records without their embeddings and tsvectors (never read back by retrieval)."""
    from sqlalchemy.orm import defer

    if not ids:
        return {}
    stmt = select(MemoryRecord).where(MemoryRecord.id.in_(ids)).options(defer(MemoryRecord.embedding), defer(MemoryRecord.tsv))
    return {r.id: r for r in session.scalars(stmt)}


_ = (String,)
