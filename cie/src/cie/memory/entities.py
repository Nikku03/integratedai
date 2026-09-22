"""Entity resolution: canonical person/organization records and mention edges.

Names are normalised (case, punctuation, corporate suffixes) and matched with
RapidFuzz against existing entity records in the addressable scope tree
(company-wide for organizations, department-wide for people). A confident
match links the new record with a ``mentions`` edge instead of creating a
duplicate entity. Ambiguous names (two candidates above threshold with no
clear winner) are recorded as an ``open_question`` rather than guessed.
"""

from __future__ import annotations

import re
import uuid

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import LinkKind, MemoryRecord, RecordType
from cie.memory.records import create_record, link
from cie.memory.scopes import ancestors

_SUFFIX = re.compile(r"\b(inc|ltd|llc|l\.l\.c|gmbh|corp|corporation|limited|plc|s\.a|b\.v|ag|co)\.?$", re.I)


def normalise(name: str) -> str:
    n = re.sub(r"[^\w\s]", " ", name.lower())
    n = _SUFFIX.sub("", n.strip()).strip()
    return re.sub(r"\s+", " ", n)


def candidates(session: Session, tenant_id: uuid.UUID, scope_id: uuid.UUID, rtype: RecordType,
               name: str | None = None, limit: int = 50) -> list[MemoryRecord]:
    """Entity records visible from the scope's ancestor chain (inherited memory).

    With ``name``, only the entities whose canonical name shares trigrams with it
    (the GIN trigram index on ``summary``) or whose recorded aliases contain it
    (the GIN index on ``keywords``, where aliases are kept normalised), most
    similar first. Resolution then scores a few dozen rows instead of every
    organisation the company has ever met."""
    from sqlalchemy import cast, func, or_

    chain = [s.id for s in ancestors(session, scope_id)]
    stmt = select(MemoryRecord).where(
        MemoryRecord.tenant_id == tenant_id, MemoryRecord.type == rtype, MemoryRecord.scope_id.in_(chain),
        MemoryRecord.deleted_at.is_(None), MemoryRecord.superseded_by_id.is_(None))
    if name:
        key = normalise(name)
        sim = func.similarity(MemoryRecord.summary, name)
        stmt = (stmt.where(or_(MemoryRecord.summary.op("%")(name),
                               MemoryRecord.keywords.op("&&")(cast([key], MemoryRecord.keywords.type))))
                .order_by(sim.desc()).limit(limit))
    return list(session.scalars(stmt))


def remember_alias(ent: MemoryRecord, name: str) -> None:
    """Record ``name`` as an alias of ``ent``: in the content for people, and in the
    indexed keywords so the next resolution of that spelling is index-served."""
    aliases = list((ent.content or {}).get("aliases", []))
    if name != ent.summary and name not in aliases:
        ent.content = {**(ent.content or {}), "aliases": aliases + [name]}
    key = normalise(name)
    if key and key not in (ent.keywords or []):
        ent.keywords = list(ent.keywords or []) + [key]


def resolve(session: Session, tenant_id: uuid.UUID, scope_id: uuid.UUID, name: str, rtype: RecordType,
            threshold: int = 90, ambiguity_gap: int = 5) -> tuple[MemoryRecord | None, str]:
    """Returns (matched_entity_or_None, status) where status is
    ``matched`` | ``ambiguous`` | ``new``."""
    key = normalise(name)
    scored = []
    for c in candidates(session, tenant_id, scope_id, rtype, name=name):
        aliases = [c.summary] + list((c.content or {}).get("aliases", []))
        best = max(fuzz.token_sort_ratio(key, normalise(a)) for a in aliases)
        scored.append((best, c))
    scored.sort(key=lambda t: -t[0])
    if not scored or scored[0][0] < threshold:
        return None, "new"
    if len(scored) > 1 and scored[1][0] >= threshold and scored[0][0] - scored[1][0] < ambiguity_gap:
        return None, "ambiguous"
    return scored[0][1], "matched"


def attach_entities(session: Session, record: MemoryRecord, names: list[str], rtype: RecordType,
                    producing_agent: str = "entity_resolver_v1") -> list[MemoryRecord]:
    """Link ``record`` to canonical entities for ``names``; create them if new."""
    out = []
    for name in names:
        ent, status = resolve(session, record.tenant_id, record.scope_id, name, rtype)
        if status == "ambiguous":
            q = create_record(session, tenant_id=record.tenant_id, scope_id=record.scope_id, type=RecordType.open_question,
                              summary=f"Ambiguous entity name: {name}", content={"name": name, "type": rtype.value},
                              detail=f"'{name}' matches more than one known {rtype.value}; resolution needed.",
                              source_document_id=record.source_document_id, source_locations=record.source_locations,
                              producing_agent=producing_agent, confidence=0.5)
            link(session, q, record, LinkKind.relates_to)
            continue
        if ent is None:
            if record.type == rtype and normalise(record.summary) == normalise(name):
                ent = record  # the record itself is the canonical entity
            else:
                ent = create_record(session, tenant_id=record.tenant_id, scope_id=record.scope_id, type=rtype, summary=name,
                                    content={"name": name, "aliases": []}, detail=name,
                                    source_document_id=record.source_document_id, source_locations=record.source_locations,
                                    producing_agent=producing_agent, confidence=0.7)
        elif ent.id != record.id and record.type == rtype:
            remember_alias(ent, name)  # a new mention with a slightly different spelling
        if ent.id != record.id:
            link(session, record, ent, LinkKind.mentions)
            if str(ent.id) not in (record.entity_ids or []):
                record.entity_ids = list(record.entity_ids or []) + [str(ent.id)]
        out.append(ent)
    return out
