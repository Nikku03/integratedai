"""REM suggestions: details (the scope and clearance of exact values a task shows).

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rem_suggestions", sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                                               server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("rem_suggestions", "details")
