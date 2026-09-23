"""Structured-source memory: ``references`` and ``near_duplicate`` link kinds.

``references``: one document explicitly cites another (a ticket key, a pull request,
a wiki page, a CRM account). ``near_duplicate``: two documents say nearly the same
thing, possibly with different facts (the input to cross-document contradiction
detection). See cie.ingest.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

from __future__ import annotations

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE link_kind ADD VALUE IF NOT EXISTS 'references'")
        op.execute("ALTER TYPE link_kind ADD VALUE IF NOT EXISTS 'near_duplicate'")


def downgrade() -> None:
    op.execute("DELETE FROM record_links WHERE kind IN ('references', 'near_duplicate')")
