"""Vector similarity over pgvector (cosine, HNSW)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import MemoryRecord, Section


def _ef(session: Session, k: int) -> None:
    """HNSW returns at most ef_search candidates before the WHERE filter is applied
    (pgvector 0.6 has no iterative scan), so ef_search must exceed k, with headroom
    for rows the permission/time filter removes."""
    from sqlalchemy import text

    session.execute(text(f"SET LOCAL hnsw.ef_search = {max(100, min(1000, 4 * k))}"))


def search_records(session: Session, vec: list[float], base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    _ef(session, k)
    dist = MemoryRecord.embedding.cosine_distance(vec)
    stmt = (select(MemoryRecord.id, dist).where(base_filter, MemoryRecord.embedding.is_not(None))
            .order_by(dist).limit(k))
    return [(r[0], 1.0 - float(r[1])) for r in session.execute(stmt)]


def search_sections(session: Session, vec: list[float], base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    _ef(session, k)
    dist = Section.embedding.cosine_distance(vec)
    stmt = select(Section.id, dist).where(base_filter, Section.embedding.is_not(None)).order_by(dist).limit(k)
    return [(r[0], 1.0 - float(r[1])) for r in session.execute(stmt)]
