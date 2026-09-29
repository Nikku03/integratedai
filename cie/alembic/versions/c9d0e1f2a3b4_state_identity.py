"""Live state identity: identifiers, match proposals and confirmed aliases.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "state_identifiers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("node_id", UUID, sa.ForeignKey("rem_nodes.id"), nullable=False, index=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("scheme", sa.String(32), nullable=False),
        sa.Column("value", sa.String(300), nullable=False),
        sa.Column("raw", sa.String(300), nullable=False, server_default=""),
        sa.Column("strength", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("source", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("recorded_seq", sa.BigInteger, nullable=False),
    )
    op.create_index("ix_state_identifiers_lookup", "state_identifiers", ["tenant_id", "entity_type", "scheme", "value"])
    op.create_index("uq_state_identifiers_strong", "state_identifiers", ["tenant_id", "entity_type", "scheme", "value"], unique=True,
                    postgresql_where=sa.text("strength = 'strong' AND status = 'active'"))
    op.create_table(
        "state_match_proposals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("a_id", UUID, sa.ForeignKey("rem_nodes.id"), nullable=False),
        sa.Column("b_id", UUID, sa.ForeignKey("rem_nodes.id"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("reasons", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(12), nullable=False, server_default="proposed"),
        sa.Column("decided_by", UUID),
        sa.Column("decided_seq", sa.BigInteger),
        sa.Column("created_seq", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "a_id", "b_id", name="uq_state_match_pair"),
    )
    op.create_table(
        "state_aliases",
        sa.Column("alias_id", UUID, sa.ForeignKey("rem_nodes.id"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("alias_type", sa.String(32), nullable=False),
        sa.Column("alias_key", sa.String(300), nullable=False),
        sa.Column("canonical_id", UUID, sa.ForeignKey("rem_nodes.id"), nullable=False, index=True),
        sa.Column("proposal_id", UUID),
        sa.Column("merged_seq", sa.BigInteger, nullable=False),
        sa.Column("merged_by", UUID),
    )
    op.create_index("ix_state_aliases_key", "state_aliases", ["tenant_id", "alias_type", "alias_key"])


def downgrade() -> None:
    op.drop_index("ix_state_aliases_key", table_name="state_aliases")
    op.drop_table("state_aliases")
    op.drop_table("state_match_proposals")
    op.drop_index("uq_state_identifiers_strong", table_name="state_identifiers")
    op.drop_index("ix_state_identifiers_lookup", table_name="state_identifiers")
    op.drop_table("state_identifiers")
