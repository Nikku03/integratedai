"""A smaller memory bank: 16-bit stored vectors, and keyword indexes on expressions instead of stored tsvectors.

On the 5,000-document bank (docs/STORAGE.md), sections took 5.9 KB and records 6.6 KB each, indexes included. Most of
that went into finding the text, not into the text itself:
- 32-bit vectors of 1,540 bytes, too large to stay in the row, moved to TOAST at 2.8-3.2 KB a row;
- stored tsvectors of 1,292 bytes per section, more than the section's text.

This migration:
* stores the embeddings of sections, memory_records and section_facts as halfvec(384), the precision the HNSW indexes
  already compared at. The HNSW indexes are rebuilt on the column itself;
* drops the tsv columns. Keyword search uses GIN indexes on cie_section_tsv(title, text),
  cie_record_tsv(summary, keywords, detail) and cie_facts_tsv(text) (cie.memory.text).

Each table is rewritten once, which takes an exclusive lock and temporary disk of about the new table's size.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-10-05
"""

from alembic import op
from cie.memory.text import TSV_FUNCTIONS

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None

# table: (HNSW index or None, GIN index, keyword expression, the tsvector the stored column held)
TABLES = {
    "sections": ("ix_sections_embedding_hnsw", "ix_sections_tsv", "cie_section_tsv(title, text)",
                 "setweight(to_tsvector('english', coalesce(title, '')), 'A') || setweight(to_tsvector('english', text), 'B')"),
    "memory_records": ("ix_records_embedding_hnsw", "ix_records_tsv", "cie_record_tsv(summary, keywords, detail)",
                       "setweight(to_tsvector('english', summary), 'A') || setweight(to_tsvector('english', array_to_string(keywords, ' ')), 'A') "
                       "|| setweight(to_tsvector('english', left(detail, 20000)), 'B')"),
    "section_facts": (None, "ix_section_facts_tsv", "cie_facts_tsv(text)", "to_tsvector('english', text)"),
}

BINARY = {"sections": "ix_sections_embedding_bq", "memory_records": "ix_records_embedding_bq"}  # cie.memory.compact


def upgrade() -> None:
    v = op.get_bind().exec_driver_sql("SELECT extversion FROM pg_extension WHERE extname = 'vector'").scalar() or "0.0"
    if tuple(int(x) for x in v.split(".")[:2]) < (0, 7):
        raise RuntimeError(f"16-bit vectors need pgvector 0.7 or newer (installed: {v}); upgrade the extension first")
    op.execute("SET maintenance_work_mem = '1GB'")
    for sql in TSV_FUNCTIONS.values():
        op.execute(sql)
    for table, (hnsw, gin, expr, _old) in TABLES.items():
        if hnsw:
            op.execute(f"DROP INDEX IF EXISTS {hnsw}")
        op.execute(f"DROP INDEX IF EXISTS {gin}")
        op.execute(f"DROP INDEX IF EXISTS {BINARY.get(table, '_none_')}")
        # the column is dropped before the type change, so the one rewrite that follows also reclaims its space
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tsv")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE halfvec(384) USING embedding::halfvec(384)")
        op.execute(f"CREATE INDEX {gin} ON {table} USING gin ({expr})")
        if hnsw:
            op.execute(f"CREATE INDEX {hnsw} ON {table} USING hnsw (embedding halfvec_cosine_ops)")
        op.execute(f"ANALYZE {table}")


def downgrade() -> None:
    op.execute("SET maintenance_work_mem = '1GB'")
    for table, (hnsw, gin, _expr, old) in TABLES.items():
        if hnsw:
            op.execute(f"DROP INDEX IF EXISTS {hnsw}")
        op.execute(f"DROP INDEX IF EXISTS {BINARY.get(table, '_none_')}")
        op.execute(f"DROP INDEX IF EXISTS {gin}")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)")
        op.execute(f"ALTER TABLE {table} ADD COLUMN tsv tsvector")
        op.execute(f"UPDATE {table} SET tsv = {old}")
        op.execute(f"CREATE INDEX {gin} ON {table} USING gin (tsv)")
        if hnsw:
            op.execute(f"CREATE INDEX {hnsw} ON {table} USING hnsw ((embedding::halfvec(384)) halfvec_cosine_ops)")
    for name in TSV_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {name}")
