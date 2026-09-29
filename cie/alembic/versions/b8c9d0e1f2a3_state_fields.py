"""Live state: field-level statements, source authority rules and open conflicts.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "state_authority",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.UniqueConstraint("tenant_id", "entity_type", "field", "source_system", name="uq_state_authority"),
    )
    op.create_table(
        "state_fields",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("node_id", UUID, sa.ForeignKey("rem_nodes.id"), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("value", JSONB, nullable=True),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("source_record", sa.String(300), nullable=False, server_default=""),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("method", sa.String(40), nullable=False, server_default=""),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("recorded_seq", sa.BigInteger, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decision", sa.Text, nullable=False, server_default=""),
        sa.Column("verification", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_seq", sa.BigInteger),
        sa.Column("event_id", UUID),
    )
    op.create_index("ix_state_fields_node_field", "state_fields", ["tenant_id", "node_id", "field", "status"])
    op.create_table(
        "state_conflicts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("node_id", UUID, sa.ForeignKey("rem_nodes.id"), nullable=False, index=True),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("current_field_id", UUID),
        sa.Column("challenger_field_id", UUID, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("resolution", sa.String(24)),
        sa.Column("resolved_by", UUID),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("opened_seq", sa.BigInteger, nullable=False),
        sa.Column("resolved_seq", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("state_conflicts")
    op.drop_index("ix_state_fields_node_field", table_name="state_fields")
    op.drop_table("state_fields")
    op.drop_table("state_authority")
