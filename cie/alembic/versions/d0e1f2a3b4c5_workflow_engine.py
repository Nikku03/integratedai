"""Workflow engine: task lifecycle statuses, leases, acceptance, limits, progress; inputs, transitions, invalidations.

Existing tasks move to the new statuses: pending -> ready, assigned -> running, needs_verification and
awaiting_approval -> review, verified and done -> completed. The old enum labels stay in the type (PostgreSQL
cannot drop them) but are no longer used.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NEW = ("proposed", "ready", "review", "completed", "cancelled")
MAP = {"pending": "ready", "assigned": "running", "needs_verification": "review", "awaiting_approval": "review",
       "verified": "completed", "done": "completed"}
BACK = {"proposed": "pending", "ready": "pending", "review": "needs_verification", "completed": "done", "cancelled": "failed"}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for v in NEW:
            op.execute(f"ALTER TYPE task_status ADD VALUE IF NOT EXISTS '{v}'")
    for old, new in MAP.items():
        op.execute(f"UPDATE tasks SET status = '{new}' WHERE status = '{old}'")
    op.execute("UPDATE tasks SET verification = verification || '{\"awaiting\": \"human\", \"review\": \"human\"}'::jsonb "
               "WHERE status = 'review' AND id::text IN (SELECT subject_id FROM approvals WHERE kind = 'task_result' AND status = 'pending')")
    for name, col in (
        ("owner_principal_id", sa.Column("owner_principal_id", UUID)),
        ("deadline_at", sa.Column("deadline_at", sa.DateTime(timezone=True))),
        ("acceptance", sa.Column("acceptance", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"))),
        ("limits", sa.Column("limits", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"))),
        ("progress", sa.Column("progress", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"))),
        ("lease_owner", sa.Column("lease_owner", sa.String(120))),
        ("lease_expires_at", sa.Column("lease_expires_at", sa.DateTime(timezone=True))),
        ("attempts", sa.Column("attempts", sa.Integer, nullable=False, server_default="0")),
        ("max_attempts", sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3")),
        ("review_rounds", sa.Column("review_rounds", sa.Integer, nullable=False, server_default="0")),
        ("max_review_rounds", sa.Column("max_review_rounds", sa.Integer, nullable=False, server_default="1")),
        ("retry_authorized_by", sa.Column("retry_authorized_by", UUID)),
        ("revision", sa.Column("revision", sa.Integer, nullable=False, server_default="0")),
    ):
        op.add_column("tasks", col)
    op.create_index("ix_tasks_ready", "tasks", ["tenant_id", "status", "priority", "created_at"])
    op.create_index("ix_tasks_lease", "tasks", ["status", "lease_expires_at"])
    op.add_column("task_dependencies", sa.Column("kind", sa.String(12), nullable=False, server_default="requires"))
    op.execute("UPDATE task_dependencies d SET kind = 'after' FROM tasks t WHERE t.id = d.task_id AND t.task_type = 'synthesis'")
    op.create_table(
        "task_inputs",
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("ref_kind", sa.String(8), primary_key=True),
        sa.Column("ref_id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("label", sa.String(300), nullable=False, server_default=""),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_inputs_ref", "task_inputs", ["ref_kind", "ref_id"])
    op.create_table(
        "task_transitions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("from_status", sa.String(24), nullable=False),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "task_invalidations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("ref_id", UUID, nullable=False),
        sa.Column("from_version", sa.Integer, nullable=False),
        sa.Column("to_version", sa.Integer, nullable=False),
        sa.Column("event_id", UUID),
        sa.Column("seq", sa.BigInteger),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "ref_id", "to_version", name="uq_task_invalidation"),
    )


def downgrade() -> None:
    op.drop_table("task_invalidations")
    op.drop_table("task_transitions")
    op.drop_index("ix_task_inputs_ref", table_name="task_inputs")
    op.drop_table("task_inputs")
    op.drop_column("task_dependencies", "kind")
    op.drop_index("ix_tasks_lease", table_name="tasks")
    op.drop_index("ix_tasks_ready", table_name="tasks")
    for c in ("revision", "retry_authorized_by", "max_review_rounds", "review_rounds", "max_attempts", "attempts", "lease_expires_at",
              "lease_owner", "progress", "limits", "acceptance", "deadline_at", "owner_principal_id"):
        op.drop_column("tasks", c)
    for new, old in BACK.items():
        op.execute(f"UPDATE tasks SET status = '{old}' WHERE status = '{new}'")
