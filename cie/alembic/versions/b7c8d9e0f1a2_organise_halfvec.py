"""Organisation views and half-precision vector indexes.

* GIN index on ``memory_records.entity_ids`` (jsonb_path_ops) so "everything about
  entity X" is a containment lookup at any size.
* With pgvector 0.7 or newer, the HNSW indexes are rebuilt on ``embedding::halfvec``
  (16-bit floats): half the index size, faster build, same recall on normalised
  embeddings (measured by the scale benchmark). Older pgvector keeps the float indexes.

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
"""

from __future__ import annotations

from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

DIM = 384


def _pgvector_at_least(major: int, minor: int) -> bool:
    row = op.get_bind().execute(__import__("sqlalchemy").text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
    if not row:
        return False
    parts = [int(x) for x in row.split(".")[:2]]
    return (parts[0], parts[1]) >= (major, minor)


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_records_entity_ids ON memory_records USING gin (entity_ids jsonb_path_ops)")
    if _pgvector_at_least(0, 7):
        op.execute("DROP INDEX IF EXISTS ix_records_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS ix_sections_embedding_hnsw")
        op.execute(f"CREATE INDEX ix_records_embedding_hnsw ON memory_records USING hnsw ((embedding::halfvec({DIM})) halfvec_cosine_ops)")
        op.execute(f"CREATE INDEX ix_sections_embedding_hnsw ON sections USING hnsw ((embedding::halfvec({DIM})) halfvec_cosine_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_records_entity_ids")
    if _pgvector_at_least(0, 7):
        op.execute("DROP INDEX IF EXISTS ix_records_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS ix_sections_embedding_hnsw")
        op.execute("CREATE INDEX ix_records_embedding_hnsw ON memory_records USING hnsw (embedding vector_cosine_ops)")
        op.execute("CREATE INDEX ix_sections_embedding_hnsw ON sections USING hnsw (embedding vector_cosine_ops)")
