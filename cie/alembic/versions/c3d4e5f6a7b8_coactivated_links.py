"""Dynamic memory: the ``coactivated`` link kind.

Links the bank forms itself when records fire together in answers (structural
plasticity), oriented towards the record that ranked highest, weighted by how
often the pair co-fired, pruned when they stop. See cie.topology.dynamic.

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
"""

from __future__ import annotations

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE link_kind ADD VALUE IF NOT EXISTS 'coactivated'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value; the links of that kind are removed instead
    op.execute("DELETE FROM record_links WHERE kind = 'coactivated'")
