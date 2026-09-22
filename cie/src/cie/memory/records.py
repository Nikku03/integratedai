"""Memory record service: create, supersede, contradict, confirm, extend.

History is never overwritten. Every mutation is a new row plus a typed edge.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cie.core.models import (
    LinkKind,
    MemoryRecord,
    RecordLink,
    RecordType,
    Scope,
    VerificationStatus,
)
from cie.core.util import sha256_text, utcnow
from cie.memory.embeddings import EmbeddingProvider
from cie.memory.glyph import build_glyph
from cie.memory.text import tsvector_expr


def create_record(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    scope_id: uuid.UUID,
    type: RecordType | str,
    summary: str,
    content: dict[str, Any] | None = None,
    detail: str = "",
    source_document_id: uuid.UUID | None = None,
    source_locations: list[dict[str, Any]] | None = None,
    event_time: datetime | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    author_id: uuid.UUID | None = None,
    producing_agent: str | None = None,
    confidence: float = 0.5,
    verification: VerificationStatus = VerificationStatus.unverified,
    sensitivity: int = 1,
    acl: dict[str, Any] | None = None,
    keywords: list[str] | None = None,
    entity_ids: list[str] | None = None,
    embedding: list[float] | None = None,
    embedder: EmbeddingProvider | None = None,
    prompt_version: str | None = None,
    model_version: str | None = None,
    family_id: uuid.UUID | None = None,
    version: int = 1,
    supersedes_id: uuid.UUID | None = None,
    dedup: bool = True,
) -> MemoryRecord:
    rtype = RecordType(type)
    content = content or {}
    digest = sha256_text(f"{rtype.value}|{summary}|{detail}|{source_document_id}|{sorted(content.items())!r}")
    if dedup:
        existing = session.scalar(select(MemoryRecord).where(
            MemoryRecord.tenant_id == tenant_id, MemoryRecord.content_sha256 == digest,
            MemoryRecord.scope_id == scope_id, MemoryRecord.deleted_at.is_(None)))
        if existing is not None:
            return existing
    if embedding is None and embedder is not None:
        embedding = embedder.embed([f"{rtype.value}: {summary}\n{detail[:1500]}"])[0]
    rec = MemoryRecord(
        tenant_id=tenant_id, scope_id=scope_id, type=rtype, summary=summary, content=content,
        detail=detail, source_document_id=source_document_id, source_locations=source_locations or [],
        event_time=event_time, valid_from=valid_from, valid_to=valid_to, author_id=author_id,
        producing_agent=producing_agent, confidence=confidence, verification=verification,
        sensitivity=sensitivity, acl=acl or {}, version=version, family_id=family_id or uuid.uuid4(),
        supersedes_id=supersedes_id, keywords=keywords or [], entity_ids=entity_ids or [],
        embedding=embedding, content_sha256=digest, prompt_version=prompt_version,
        model_version=model_version, tsv=tsvector_expr(summary, detail),
    )
    session.add(rec)
    session.flush()
    rec.glyph = build_glyph(rec, [], scope_names(session, scope_id))
    session.flush()
    return rec


def scope_names(session: Session, scope_id: uuid.UUID) -> dict[str, str | None]:
    names: dict[str, str | None] = {"project": None, "department": None, "company": None}
    node = session.get(Scope, scope_id)
    while node is not None:
        if node.kind.value in names and names[node.kind.value] is None:
            names[node.kind.value] = node.name
        node = session.get(Scope, node.parent_id) if node.parent_id else None
    return names


def link(session: Session, src: MemoryRecord, dst: MemoryRecord, kind: LinkKind | str,
         weight: float = 1.0, justification: str | None = None, evidence: dict | None = None) -> RecordLink:
    kind = LinkKind(kind)
    existing = session.scalar(select(RecordLink).where(
        RecordLink.src_id == src.id, RecordLink.dst_id == dst.id, RecordLink.kind == kind))
    if existing:
        return existing
    if kind == LinkKind.shortcut and not justification:
        raise ValueError("shortcut edges require a justification")
    edge = RecordLink(tenant_id=src.tenant_id, src_id=src.id, dst_id=dst.id, kind=kind,
                      weight=weight, justification=justification, evidence=evidence or {})
    session.add(edge)
    session.flush()
    refresh_glyph(session, src)
    refresh_glyph(session, dst)
    return edge


def refresh_glyph(session: Session, rec: MemoryRecord) -> None:
    edges = list(session.scalars(select(RecordLink).where(
        or_(RecordLink.src_id == rec.id, RecordLink.dst_id == rec.id))))
    rec.glyph = build_glyph(rec, edges, scope_names(session, rec.scope_id))


def supersede(session: Session, old: MemoryRecord, new: MemoryRecord, at: datetime | None = None,
              justification: str | None = None) -> RecordLink:
    """``new`` replaces ``old``. Old stays queryable as history."""
    at = at or new.valid_from or utcnow()
    old.superseded_by_id = new.id
    if old.valid_to is None or old.valid_to > at:
        old.valid_to = at
    new.supersedes_id = old.id
    new.family_id = old.family_id
    new.version = old.version + 1
    if new.valid_from is None:
        new.valid_from = at
    return link(session, new, old, LinkKind.supersedes, justification=justification)


def contradict(session: Session, a: MemoryRecord, b: MemoryRecord, reason: str,
               producing_agent: str | None = None) -> MemoryRecord:
    """Mark two records as contradictory and create a contradiction record citing both."""
    link(session, a, b, LinkKind.contradicts, justification=reason)
    link(session, b, a, LinkKind.contradicts, justification=reason)
    for r in (a, b):
        if r.verification == VerificationStatus.unverified:
            r.verification = VerificationStatus.disputed
    c = create_record(
        session, tenant_id=a.tenant_id, scope_id=a.scope_id, type=RecordType.contradiction,
        summary=f"Contradiction: {a.summary[:80]} vs {b.summary[:80]}",
        content={"record_a": str(a.id), "record_b": str(b.id), "reason": reason,
                 "a_summary": a.summary, "b_summary": b.summary},
        detail=reason, source_document_id=a.source_document_id,
        source_locations=(a.source_locations or [])[:1] + (b.source_locations or [])[:1],
        producing_agent=producing_agent, confidence=0.8,
    )
    link(session, c, a, LinkKind.relates_to)
    link(session, c, b, LinkKind.relates_to)
    refresh_glyph(session, a)
    refresh_glyph(session, b)
    return c


def confirm(session: Session, a: MemoryRecord, by: MemoryRecord, boost: float = 0.1) -> RecordLink:
    e = link(session, by, a, LinkKind.confirms)
    a.confidence = min(1.0, a.confidence + boost)
    if a.verification == VerificationStatus.unverified:
        a.verification = VerificationStatus.verified
    refresh_glyph(session, a)
    return e


def extend(session: Session, base: MemoryRecord, extension: MemoryRecord) -> RecordLink:
    return link(session, extension, base, LinkKind.extends)


def current_only(stmt, at: datetime | None = None):
    """Filter a MemoryRecord select to records valid at ``at`` (default: now)."""
    at = at or utcnow()
    return stmt.where(
        MemoryRecord.deleted_at.is_(None),
        or_(MemoryRecord.valid_from.is_(None), MemoryRecord.valid_from <= at),
        or_(MemoryRecord.valid_to.is_(None), MemoryRecord.valid_to > at),
    )


def history(session: Session, family_id: uuid.UUID) -> list[MemoryRecord]:
    return list(session.scalars(select(MemoryRecord).where(MemoryRecord.family_id == family_id)
                                .order_by(MemoryRecord.version)))
