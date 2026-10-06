"""Playbooks: company rules that decide yes, no or unknown, and the decisions made with them.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB
    op.create_table(
        "playbooks",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("spec", jsonb, nullable=False, server_default="{}"),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("problems", jsonb, nullable=False, server_default="[]"),
        sa.Column("quotes", jsonb, nullable=False, server_default="{}"),
        sa.Column("source_document_ids", postgresql.ARRAY(uid), nullable=False, server_default="{}"),
        sa.Column("drafted_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("approval_id", uid),
        sa.Column("approved_by", uid, sa.ForeignKey("principals.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "key", "version", name="uq_playbook_version"),
    )
    op.create_index("ix_playbook_key_status", "playbooks", ["tenant_id", "key", "status"])
    op.create_table(
        "playbook_decisions",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("playbook_id", uid, sa.ForeignKey("playbooks.id"), nullable=False, index=True),
        sa.Column("playbook_key", sa.String(120), nullable=False),
        sa.Column("goal", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("answer", sa.String(8), nullable=False),
        sa.Column("given", jsonb, nullable=False, server_default="{}"),
        sa.Column("inputs", jsonb, nullable=False, server_default="{}"),
        sa.Column("sources", jsonb, nullable=False, server_default="{}"),
        sa.Column("proof", jsonb, nullable=False, server_default="{}"),
        sa.Column("why", jsonb, nullable=False, server_default="[]"),
        sa.Column("missing", jsonb, nullable=False, server_default="[]"),
        sa.Column("notes", jsonb, nullable=False, server_default="[]"),
        sa.Column("based_on", jsonb, nullable=False, server_default="{}"),
        sa.Column("record_keys", postgresql.ARRAY(sa.String(340)), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="current"),
        sa.Column("superseded_by", uid),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("principal_id", uid, sa.ForeignKey("principals.id")),
        sa.Column("requested_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("seq", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pb_decision_subject", "playbook_decisions", ["tenant_id", "playbook_key", "goal", "subject", "status"])
    op.create_index("ix_pb_decision_records", "playbook_decisions", ["record_keys"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("playbook_decisions")
    op.drop_table("playbooks")
