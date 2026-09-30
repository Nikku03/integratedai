"""BM25 keyword index: the queue of rows waiting for it, each tenant's index state, and the triggers that fill the
queue (cie.retrieval.bm25).

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "lexical_queue",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("kind", sa.String(1), nullable=False),
        sa.Column("row_id", uid, nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_lexical_queue_tenant", "lexical_queue", ["tenant_id", "kind", "row_id"])
    op.create_table(
        "lexical_state",
        sa.Column("tenant_id", uid, primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="building"),
        sa.Column("version", sa.String(64)),
        sa.Column("built_at", sa.DateTime(timezone=True)),
        sa.Column("docs", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    from cie.retrieval.bm25 import INSTALL_SQL

    op.execute(INSTALL_SQL)


def downgrade() -> None:
    from cie.retrieval.bm25 import UNINSTALL_SQL

    op.execute(UNINSTALL_SQL)
    op.drop_table("lexical_state")
    op.drop_index("ix_lexical_queue_tenant", table_name="lexical_queue")
    op.drop_table("lexical_queue")
