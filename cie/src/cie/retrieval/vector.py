"""Vector similarity over pgvector (cosine, HNSW).

The query follows the vector index the database has (``index_kind``, checked once per process and table):

* ``halfvec``: the embedding column holds 16-bit floats, and the HNSW index is on the column itself. This is the
  memory bank's layout from migration ``a9b0c1d2e3f4``.
* ``binary``: an HNSW index on ``binary_quantize(embedding)::bit(384)``, one bit per dimension. The index takes 349
  bytes per vector against 1,170, measured on the 5,000-document bank, so about 3.4 times as many vectors fit in the
  same memory. The index returns the ``rerank_window`` nearest by Hamming distance. Those are re-sorted by the exact
  cosine distance of their stored 16-bit vectors, which are read from the table, not the index. ``cie.memory.compact``
  switches a database between the two kinds; ``docs/STORAGE.md`` has the measurements.
* ``halfvec_expr``: a 32-bit column with an HNSW index on ``embedding::halfvec``, the layout before that migration.
  The query must use the same expression as the index for the planner to pick it.

The index is shared by every tenant and scope, and the tenant/permission filter is applied to what the index returns.
Without an iterative scan HNSW returns at most ``ef_search`` candidates, and a tenant or scope that holds a small share
of the vectors keeps only its share of them: relevant rows are silently lost. From pgvector 0.8 the scan continues
until enough rows pass the filter (``hnsw.iterative_scan``, bounded by ``hnsw.max_scan_tuples``); results come back in
relaxed order and are re-sorted here.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import BIT, HALFVEC
from sqlalchemy import cast, func, select, text
from sqlalchemy.orm import Session

from cie.core.models import EMBEDDING_DIM, MemoryRecord, Section

_kind_cache: dict[tuple[str, str], str] = {}
_iterative_cache: dict[str, bool] = {}
MAX_SCAN_TUPLES = 40_000  # an iterative scan stops after this many index tuples even if k rows have not passed the filter
RERANK_WINDOW = 800  # binary index: candidates re-sorted by exact distance (95.9% of the true top 10 on the 5k bank)
BINARY_INDEX = {"memory_records": "ix_records_embedding_bq", "sections": "ix_sections_embedding_bq"}


def index_kind(session: Session, table: str) -> str:
    """``binary``, ``halfvec``, ``halfvec_expr`` or ``vector`` (no halfvec support): see the module docstring."""
    key = (str(session.get_bind().url), table)
    if key not in _kind_cache:
        try:
            binary = session.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename = :t AND indexname = :i"),
                                     {"t": table, "i": BINARY_INDEX.get(table, "")}).scalar()
            col = session.execute(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                                       "WHERE attrelid = to_regclass(:t) AND attname = 'embedding'"), {"t": table}).scalar() or ""
            expr = session.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename = :t AND indexdef LIKE '%hnsw%' "
                                        "AND indexdef LIKE '%::halfvec%'"), {"t": table}).scalar()
            if binary and col.startswith("halfvec"):
                kind = "binary"
            elif col.startswith("halfvec"):
                kind = "halfvec"
            elif expr:
                kind = "halfvec_expr"
            else:
                kind = "vector"
        except Exception:  # noqa: BLE001 - no catalogue access means no index either
            session.rollback()
            kind = "vector"
        _kind_cache[key] = kind
    return _kind_cache[key]


def uses_halfvec(session: Session) -> bool:
    """True when record vectors are compared as 16-bit floats (any layout but plain 32-bit)."""
    return index_kind(session, "memory_records") != "vector"


def _distance(session: Session, model, vec: list[float]):
    half = HALFVEC(EMBEDDING_DIM)
    kind = index_kind(session, model.__tablename__)
    if kind in ("halfvec", "binary"):
        return model.embedding.cosine_distance(cast(vec, half))
    if kind == "halfvec_expr":
        return cast(model.embedding, half).cosine_distance(cast(vec, half))
    return model.embedding.cosine_distance(vec)


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


def _search(session: Session, model, vec: list[float], base_filter, k: int) -> list[tuple[uuid.UUID, float]]:
    if index_kind(session, model.__tablename__) == "binary":
        window = max(k, RERANK_WINDOW)
        _ef(session, window)
        bits = BIT(EMBEDDING_DIM)
        hamming = cast(func.binary_quantize(model.embedding), bits).op("<~>")(
            cast(func.binary_quantize(cast(vec, HALFVEC(EMBEDDING_DIM))), bits))
        near = (select(model.id.label("id"), model.embedding.label("embedding")).where(base_filter, model.embedding.is_not(None))
                .order_by(hamming).limit(window).subquery())
        dist = near.c.embedding.cosine_distance(cast(vec, HALFVEC(EMBEDDING_DIM)))
        stmt = select(near.c.id, dist).order_by(dist).limit(k)
    else:
        _ef(session, k)
        dist = _distance(session, model, vec)
        stmt = select(model.id, dist).where(base_filter, model.embedding.is_not(None)).order_by(dist).limit(k)
    return sorted(((r[0], 1.0 - float(r[1])) for r in session.execute(stmt)), key=lambda x: -x[1])


def search_records(session: Session, vec: list[float], base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    return _search(session, MemoryRecord, vec, base_filter, k)


def search_sections(session: Session, vec: list[float], base_filter, k: int = 50) -> list[tuple[uuid.UUID, float]]:
    return _search(session, Section, vec, base_filter, k)
