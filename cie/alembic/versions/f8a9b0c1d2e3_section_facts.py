"""Facts a language model extracted from each section, stored beside the section (cie.memory.facts).

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "section_facts",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("section_id", uid, sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", uid, sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("scope_id", uid, sa.ForeignKey("scopes.id"), nullable=False),
        sa.Column("sensitivity", sa.Integer, nullable=False),
        sa.Column("extractor", sa.String(200), nullable=False),
        sa.Column("signature", sa.String(32), nullable=False),
        sa.Column("settings", postgresql.JSONB, nullable=False),
        sa.Column("section_sha256", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("facts", postgresql.JSONB, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("n_facts", sa.Integer, nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("section_id", "signature", name="uq_section_facts"),
    )
    for col in ("tenant_id", "section_id", "document_id", "scope_id"):
        op.create_index(f"ix_section_facts_{col}", "section_facts", [col])
    op.create_index("ix_section_facts_input", "section_facts", ["tenant_id", "signature", "input_sha256"])
    op.create_index("ix_section_facts_tsv", "section_facts", ["tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("section_facts")
