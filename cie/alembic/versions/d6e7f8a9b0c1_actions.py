"""The action gateway: actions on external systems, with every check they passed or failed.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "actions",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("project_id", uid, sa.ForeignKey("projects.id"), index=True),
        sa.Column("task_id", uid, sa.ForeignKey("tasks.id"), index=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("requested_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("agent_id", uid, sa.ForeignKey("agents.id")),
        sa.Column("principal_id", uid, sa.ForeignKey("principals.id")),
        sa.Column("amount", sa.Float),
        sa.Column("authority_kind", sa.String(64)),
        sa.Column("based_on", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("checks", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("approval_id", uid),
        sa.Column("receipt", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_key"),
    )


def downgrade() -> None:
    op.drop_table("actions")
