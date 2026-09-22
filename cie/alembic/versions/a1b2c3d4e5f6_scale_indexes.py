"""scale indexes: trigram on document titles, composite on records

Revision ID: a1b2c3d4e5f6
Revises: eba369ef2e57
Create Date: 2026-09-22
"""
from __future__ import annotations

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "eba369ef2e57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_title_trgm ON documents USING gin (title gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_filename_trgm ON documents USING gin (original_filename gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_records_tenant_scope_type ON memory_records (tenant_id, scope_id, type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_records_source_doc_type ON memory_records (source_document_id, type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sections_tenant_scope ON sections (tenant_id, scope_id)")


def downgrade() -> None:
    for name in ("ix_documents_title_trgm", "ix_documents_filename_trgm", "ix_records_tenant_scope_type",
                 "ix_records_source_doc_type", "ix_sections_tenant_scope"):
        op.execute(f"DROP INDEX IF EXISTS {name}")
