"""Agent message kind input_changed: a record a task used changed.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-09-29
"""

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE message_kind ADD VALUE IF NOT EXISTS 'input_changed'")


def downgrade() -> None:
    pass  # PostgreSQL cannot drop an enum value; it is unused after a downgrade
