"""Task outputs released early: task_outputs, the outputs a dependency needs, and message read status.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("value", postgresql.JSONB),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("state_refs", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(12), nullable=False, server_default="current"),
        sa.Column("produced_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("task_revision", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "key", name="uq_task_output_key"),
    )
    op.add_column("task_dependencies", sa.Column("outputs", postgresql.JSONB, nullable=False, server_default="[]"))
    op.add_column("agent_messages", sa.Column("read_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("agent_messages", "read_at")
    op.drop_column("task_dependencies", "outputs")
    op.drop_table("task_outputs")
