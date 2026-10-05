"""The binary vector index (cie.memory.compact): search takes the Hamming-nearest from it and re-sorts them by exact
cosine distance, so on a few rows (all inside the re-sort window) it returns what the 16-bit layout returns."""

from __future__ import annotations

import pytest
from sqlalchemy import and_, text

from cie.core.models import MemoryRecord
from cie.memory import compact
from cie.memory.embeddings import HashedEmbedding
from cie.memory.facts import _connect
from cie.retrieval import vector
from tests.conftest import TEST_URL
from tests.test_bm25 import rec

TOPICS = ["freight contract renewal", "warehouse lease Leipzig", "carrier delay Hamburg", "supplier audit findings",
          "quarterly revenue forecast", "payroll system migration", "customer churn analysis", "data retention policy",
          "office relocation budget", "security incident review", "pricing uplift proposal", "inventory write-off"]


@pytest.mark.db
def test_binary_index_returns_the_exact_nearest_and_switches_back(session, world):
    emb = HashedEmbedding(384)
    texts = [f"{t} {n}" for t in TOPICS for n in ("north", "south")]
    for t, v in zip(texts, emb.embed(texts), strict=True):
        rec(session, world, t, t).embedding = v
    session.commit()
    base = and_(MemoryRecord.tenant_id == world.tenant.id, MemoryRecord.deleted_at.is_(None))
    q = emb.embed(["carrier delay at the Hamburg warehouse"])[0]

    def ix(name):
        return session.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname = :i"), {"i": name})

    had = ix(compact.HALFVEC_INDEX["memory_records"]), ix(compact.HALFVEC_INDEX["sections"])
    vector._kind_cache.clear()
    assert vector.index_kind(session, "memory_records") == "halfvec"
    exact = vector.search_records(session, q, base, 5)
    session.commit()
    assert len(exact) == 5

    conn = _connect(TEST_URL)
    try:
        res = compact.set_vector_index(conn, "binary", log=lambda *a: None)
        assert set(res["indexes"]) >= {"ix_records_embedding_bq", "ix_sections_embedding_bq"}
        assert not set(res["indexes"]) & set(compact.HALFVEC_INDEX.values())
        vector._kind_cache.clear()
        assert vector.index_kind(session, "memory_records") == "binary"
        got = vector.search_records(session, q, base, 5)
        session.commit()
        assert [i for i, _ in got] == [i for i, _ in exact]
        assert [round(s, 4) for _, s in got] == [round(s, 4) for _, s in exact]
    finally:
        session.rollback()
        compact.set_vector_index(conn, "halfvec", log=lambda *a: None)
        for name, keep in zip(compact.HALFVEC_INDEX.values(), had, strict=True):
            if not keep:  # the test database had no 16-bit index here: leave it as found
                conn.execute(f"DROP INDEX IF EXISTS {name}")
        conn.commit()
        conn.close()
        vector._kind_cache.clear()
    assert vector.index_kind(session, "memory_records") == "halfvec"
