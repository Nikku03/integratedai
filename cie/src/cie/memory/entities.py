"""Entity resolution: canonical person/organization records and mention edges.

Names are normalised (case, punctuation, corporate suffixes) and matched against
existing entity records, company-wide for organizations and department-wide for
people. The same name once case, punctuation and corporate suffixes are gone is a
match: the new record is linked with a ``mentions`` edge instead of creating a
duplicate entity. A merely similar name (RapidFuzz score above the threshold) is
``probable``: it is linked as an unconfirmed possible match, with its score, and no
alias is recorded, because name similarity alone never merges two entities.
Ambiguous names (two candidates above threshold with no clear winner) are recorded
as an ``open_question`` rather than guessed.

This links mentions in knowledge memory, as a retrieval aid. Business entities in
the live state resolve by identifiers and confirmed matches (``cie.state.identity``).
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

_SUFFIX = re.compile(r"\b(inc|incorporated|ltd|limited|llc|llp|lp|pllc|gmbh|ug|ag|kg|se|corp|corporation|company|co|plc|sa|sas|sarl|"
                     r"spa|srl|bv|nv|ab|oy|pty|pte|kk)$", re.I)
_DOTTED = re.compile(r"\b(?:[a-z]\.){2,}", re.I)  # L.L.C., S.A., B.V.


def normalise(name: str) -> str:
    """Case, punctuation and corporate suffixes removed: "Northwind Logistics Co. Ltd."
    and "NORTHWIND LOGISTICS" are the same key; "L.L.C." and "LLC" too."""
    n = _DOTTED.sub(lambda m: m.group().replace(".", ""), name.lower())
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    for _ in range(2):  # "Co. Ltd." carries two
        stripped = _SUFFIX.sub("", n).strip()
        if stripped == n or not stripped:
            break
        n = stripped
    return n


def candidate_scope_ids(session: Session, scope_id: uuid.UUID, rtype: RecordType) -> list[uuid.UUID] | None:
    """Where a canonical entity may live. Organisations are company-wide (``None``:
    every scope of the tenant), because a supplier first met by one project is the
    same supplier when another project meets it. People are department-wide: the
    scope's ancestor chain plus the subtree of its nearest department."""
    if rtype == RecordType.organization:
        return None
    from cie.core.models import ScopeKind
    from cie.memory.scopes import descendants

    chain = ancestors(session, scope_id)
    ids = {s.id for s in chain}
    dept = next((s for s in chain if s.kind == ScopeKind.department), chain[-1] if chain else None)
    if dept is not None:
        ids |= {dept.id} | {d.id for d in descendants(session, dept)}
    return list(ids)


def candidates(session: Session, tenant_id: uuid.UUID, scope_id: uuid.UUID, rtype: RecordType,
               name: str | None = None, limit: int = 50) -> list[MemoryRecord]:
    """Entity records the mention may resolve to (see ``candidate_scope_ids``).

    With ``name``, only the entities whose canonical name shares trigrams with it
    (the GIN trigram index on ``summary``) or whose recorded aliases contain it
    (the GIN index on ``keywords``, where aliases are kept normalised), most
    similar first. Resolution then scores a few dozen rows instead of every
    organisation the company has ever met."""
    from sqlalchemy import cast, func, or_

    stmt = select(MemoryRecord).where(
        MemoryRecord.tenant_id == tenant_id, MemoryRecord.type == rtype,
        MemoryRecord.deleted_at.is_(None), MemoryRecord.superseded_by_id.is_(None))
    scope_ids = candidate_scope_ids(session, scope_id, rtype)
    if scope_ids is not None:
        stmt = stmt.where(MemoryRecord.scope_id.in_(scope_ids))
    if name:
        key = normalise(name)
        sim = func.similarity(MemoryRecord.summary, name)
        if key:
            # the literal normalised name first: the trigram index serves ILIKE with a handful of rows,
            # where similarity alone would pull every namesake sharing two words
            rows = list(session.scalars(stmt.where(MemoryRecord.summary.ilike(f"%{key}%")).order_by(sim.desc()).limit(limit)))
            if rows:
                return rows
        stmt = (stmt.where(or_(MemoryRecord.summary.op("%")(name),
                               MemoryRecord.keywords.op("&&")(cast([key or name.lower()], MemoryRecord.keywords.type))))
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
    """Returns (entity_or_None, status) where status is ``matched`` (the same normalised name or a recorded alias),
    ``probable`` (a similar name: a possible match, never a merge), ``ambiguous`` or ``new``."""
    key = normalise(name)
    scored = []
    for c in candidates(session, tenant_id, scope_id, rtype, name=name):
        aliases = [c.summary] + list((c.content or {}).get("aliases", []))
        normalised = [normalise(a) for a in aliases]
        if key and key in normalised:
            return c, "matched"  # the same name once suffixes and punctuation are gone: never ambiguous
        best = max(fuzz.token_sort_ratio(key, a) for a in normalised)
        scored.append((best, c))
    scored.sort(key=lambda t: -t[0])
    if not scored or scored[0][0] < threshold:
        return None, "new"
    if len(scored) > 1 and scored[1][0] >= threshold and scored[0][0] - scored[1][0] < ambiguity_gap:
        return None, "ambiguous"
    return scored[0][1], "probable"


def similarity(name: str, ent: MemoryRecord) -> float:
    key = normalise(name)
    names = [ent.summary] + list((ent.content or {}).get("aliases", []))
    return float(max((fuzz.token_sort_ratio(key, normalise(a)) for a in names), default=0.0))


def link_probable(session: Session, record: MemoryRecord, ent: MemoryRecord, name: str) -> None:
    """A possible match found by name similarity: linked for retrieval, marked unconfirmed, never merged."""
    link(session, record, ent, LinkKind.relates_to, weight=0.5,
         evidence={"match": "name_similarity", "score": similarity(name, ent), "name": name, "confirmed": False})


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
        if status == "probable":
            if ent.id != record.id:
                link_probable(session, record, ent, name)
            if record.type == rtype:
                out.append(record)  # a separate entity until a person confirms they are the same
                continue
            ent = None
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
