"""Answer mode holds the fallback reason (e.g. 'extractive (model answer not verifiable)'): widen to 64 characters.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

import sqlalchemy as sa

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("answers", "mode", type_=sa.String(64), existing_type=sa.String(16))


def downgrade() -> None:
    op.alter_column("answers", "mode", type_=sa.String(16), existing_type=sa.String(64))
