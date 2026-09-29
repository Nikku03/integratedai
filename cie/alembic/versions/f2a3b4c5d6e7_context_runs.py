"""Context runs: what was assembled for whom, with coverage for exhaustive scans.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "context_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("task_id", UUID, index=True),
        sa.Column("principal_id", UUID),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("request", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sources", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("coverage", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("complete", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("snapshot_seq", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("token_estimate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("context_runs")
