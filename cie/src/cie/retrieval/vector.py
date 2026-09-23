"""Vector similarity over pgvector (cosine, HNSW).

With pgvector 0.7+ the HNSW indexes are built on ``embedding::halfvec`` (16-bit
floats): half the index size and a faster build for a recall loss that the scale
benchmark measures as none on normalised 384-d embeddings. The query must use the
same expression as the index for the planner to pick it, so the module checks
once per process which kind of index the database has.

The index is shared by every tenant and scope, and the tenant/permission filter is
applied to what the index returns. Without an iterative scan HNSW returns at most
``ef_search`` candidates, and a tenant or scope that holds a small share of the
vectors keeps only its share of them: relevant rows are silently lost. From pgvector
0.8 the scan continues until ``k`` rows pass the filter (``hnsw.iterative_scan``,
bounded by ``hnsw.max_scan_tuples``); results come back in relaxed order and are
re-sorted here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import cast, select, text
from sqlalchemy.orm import Session

from cie.core.models import EMBEDDING_DIM, MemoryRecord, Section

_halfvec_cache: dict[str, bool] = {}
_iterative_cache: dict[str, bool] = {}
MAX_SCAN_TUPLES = 40_000  # an iterative scan stops after this many index tuples even if k rows have not passed the filter


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


def supports_iterative_scan(session: Session) -> bool:
    """pgvector 0.8 or later (iterative index scans)."""
    key = str(session.get_bind().url)
    if key not in _iterative_cache:
        try:
            v = session.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar() or "0.0"
            major, minor = (int(x) for x in v.split(".")[:2])
            _iterative_cache[key] = (major, minor) >= (0, 8)
        except Exception:  # noqa: BLE001
            session.rollback()
            _iterative_cache[key] = False
    return _iterative_cache[key]


def _ef(session: Session, k: int) -> None:
    """ef_search exceeds k with headroom; where the server supports it, the scan also continues past ef_search until
    k rows pass the tenant/permission/time filter (see the module docstring)."""
    session.execute(text(f"SET LOCAL hnsw.ef_search = {max(100, min(1000, 4 * k))}"))
    if supports_iterative_scan(session):
        session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        session.execute(text(f"SET LOCAL hnsw.max_scan_tuples = {MAX_SCAN_TUPLES}"))


def search_records(session: Session, vec: list[float], base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    _ef(session, k)
    dist = _distance(session, MemoryRecord.embedding, vec)
    stmt = (select(MemoryRecord.id, dist).where(base_filter, MemoryRecord.embedding.is_not(None))
            .order_by(dist).limit(k))
    return sorted(((r[0], 1.0 - float(r[1])) for r in session.execute(stmt)), key=lambda x: -x[1])


def search_sections(session: Session, vec: list[float], base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    _ef(session, k)
    dist = _distance(session, Section.embedding, vec)
    stmt = select(Section.id, dist).where(base_filter, Section.embedding.is_not(None)).order_by(dist).limit(k)
    return sorted(((r[0], 1.0 - float(r[1])) for r in session.execute(stmt)), key=lambda x: -x[1])
