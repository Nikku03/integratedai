"""The memory bank's vector index: 16-bit HNSW, or binary HNSW for about a third of the memory.

``python -m cie.memory.compact vector-index binary`` builds an HNSW index on ``binary_quantize(embedding)::bit(384)``
(one bit per dimension) for sections and memory records, then drops the 16-bit HNSW indexes. Search
(``cie.retrieval.vector``) sees the binary index and, for each query, takes the ``RERANK_WINDOW`` nearest by Hamming
distance and re-sorts them by the exact cosine distance of their stored 16-bit vectors. ``vector-index halfvec`` goes
back. ``status`` reports the sizes. What the binary index costs in recall and gains in memory is measured in
``docs/STORAGE.md``.

The stored vectors stay 16-bit in both cases: only the index, the part that must be in memory, changes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterable
from typing import Any

from cie.retrieval.vector import BINARY_INDEX

HALFVEC_INDEX = {"memory_records": "ix_records_embedding_hnsw", "sections": "ix_sections_embedding_hnsw"}


def set_vector_index(conn, kind: str, log=print) -> dict[str, Any]:
    """Build the ``kind`` index (``binary`` or ``halfvec``) on both tables, then drop the other kind."""
    if kind not in ("binary", "halfvec"):
        raise ValueError(f"kind is binary or halfvec, not {kind!r}")
    out: dict[str, Any] = {}
    conn.execute("SET maintenance_work_mem = '1GB'")
    for table in ("sections", "memory_records"):
        t = time.time()
        if kind == "binary":
            conn.execute(f"CREATE INDEX IF NOT EXISTS {BINARY_INDEX[table]} ON {table} "
                         "USING hnsw ((binary_quantize(embedding)::bit(384)) bit_hamming_ops)")
            conn.execute(f"DROP INDEX IF EXISTS {HALFVEC_INDEX[table]}")
        else:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {HALFVEC_INDEX[table]} ON {table} USING hnsw (embedding halfvec_cosine_ops)")
            conn.execute(f"DROP INDEX IF EXISTS {BINARY_INDEX[table]}")
        conn.commit()
        out[table] = round(time.time() - t, 1)
        log(f"  {table}: {kind} index in {out[table]} s")
    return {"kind": kind, "build_seconds": out, **sizes(conn)}


def sizes(conn) -> dict[str, Any]:
    """Bytes of each table (heap, TOAST, indexes) and of each vector and keyword index."""
    tables = {r[0]: {"heap": r[1], "toast": r[2], "indexes": r[3], "total": r[4]} for r in conn.execute(
        "SELECT c.relname, pg_relation_size(c.oid), coalesce(pg_relation_size(c.reltoastrelid), 0), pg_indexes_size(c.oid), "
        "pg_total_relation_size(c.oid) FROM pg_class c WHERE c.relname IN ('sections', 'memory_records', 'section_facts')")}
    indexes = {r[0]: r[1] for r in conn.execute(
        "SELECT indexrelname, pg_relation_size(indexrelid) FROM pg_stat_user_indexes "
        "WHERE relname IN ('sections', 'memory_records', 'section_facts') AND (indexrelname LIKE '%embedding%' OR indexrelname LIKE '%tsv%')")}
    return {"tables": tables, "indexes": indexes}


def main(argv: Iterable[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(description="the memory bank's vector index")
    ap.add_argument("--db", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vector-index", help="switch the vector index kind")
    v.add_argument("kind", choices=["binary", "halfvec"])
    sub.add_parser("status", help="table and index sizes")
    a = ap.parse_args(list(argv) if argv is not None else None)
    from cie.memory.facts import _connect

    if a.db is None:
        from cie.core.settings import get_settings

        a.db = get_settings().database_url
    conn = _connect(a.db)
    res = set_vector_index(conn, a.kind) if a.cmd == "vector-index" else sizes(conn)
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if main() is not None else 1)
