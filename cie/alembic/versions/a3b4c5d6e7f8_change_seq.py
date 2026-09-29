"""Change stamps: rem_nodes.changed_seq (any change, including relationships and stock counts) and the snapshot a
task input was read at; task invalidations are unique per change.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-29
"""

import sqlalchemy as sa

from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rem_nodes", sa.Column("changed_seq", sa.BigInteger))
    op.execute("UPDATE rem_nodes n SET changed_seq = GREATEST(n.created_seq, COALESCE(n.deleted_seq, 0), "
               "COALESCE((SELECT max(v.sys_from) FROM rem_node_versions v WHERE v.node_id = n.id), 0))")
    op.add_column("task_inputs", sa.Column("seq", sa.BigInteger))
    op.drop_constraint("uq_task_invalidation", "task_invalidations", type_="unique")
    op.create_unique_constraint("uq_task_invalidation_seq", "task_invalidations", ["task_id", "ref_id", "seq"])


def downgrade() -> None:
    op.drop_constraint("uq_task_invalidation_seq", "task_invalidations", type_="unique")
    op.create_unique_constraint("uq_task_invalidation", "task_invalidations", ["task_id", "ref_id", "to_version"])
    op.drop_column("task_inputs", "seq")
    op.drop_column("rem_nodes", "changed_seq")
