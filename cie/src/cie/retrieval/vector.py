"""Vector similarity over pgvector (cosine, HNSW).

With pgvector 0.7+ the HNSW indexes are built on ``embedding::halfvec`` (16-bit
floats): half the index size and a faster build for a recall loss that the scale
benchmark measures as none on normalised 384-d embeddings. The query must use the
same expression as the index for the planner to pick it, so the module checks
once per process which kind of index the database has.
"""

from __future__ import annotations

import uuid

from sqlalchemy import cast, select, text
from sqlalchemy.orm import Session

from cie.core.models import EMBEDDING_DIM, MemoryRecord, Section

_halfvec_cache: dict[str, bool] = {}


def uses_halfvec(session: Session) -> bool:
    """True when the records' HNSW index is a halfvec expression index."""
    key = str(session.get_bind().url)
    if key not in _halfvec_cache:
        try:
            row = session.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename = 'memory_records' "
                                       "AND indexname = 'ix_records_embedding_hnsw' AND indexdef LIKE '%halfvec%'")).scalar()
            _halfvec_cache[key] = bool(row)
        except Exception:  # noqa: BLE001 - no catalogue access means no index either
            session.rollback()
            _halfvec_cache[key] = False
    return _halfvec_cache[key]


def _distance(session: Session, column, vec: list[float]):
    if uses_halfvec(session):
        from pgvector.sqlalchemy import HALFVEC

        half = HALFVEC(EMBEDDING_DIM)
        return cast(column, half).cosine_distance(cast(vec, half))
    return column.cosine_distance(vec)


def _ef(session: Session, k: int) -> None:
    """HNSW returns at most ef_search candidates before the WHERE filter is applied
    (no iterative scan is requested), so ef_search must exceed k, with headroom
    for rows the permission/time filter removes."""
    session.execute(text(f"SET LOCAL hnsw.ef_search = {max(100, min(1000, 4 * k))}"))


def search_records(session: Session, vec: list[float], base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    _ef(session, k)
    dist = _distance(session, MemoryRecord.embedding, vec)
    stmt = (select(MemoryRecord.id, dist).where(base_filter, MemoryRecord.embedding.is_not(None))
            .order_by(dist).limit(k))
    return [(r[0], 1.0 - float(r[1])) for r in session.execute(stmt)]


def search_sections(session: Session, vec: list[float], base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    _ef(session, k)
    dist = _distance(session, Section.embedding, vec)
    stmt = select(Section.id, dist).where(base_filter, Section.embedding.is_not(None)).order_by(dist).limit(k)
    return [(r[0], 1.0 - float(r[1])) for r in session.execute(stmt)]
