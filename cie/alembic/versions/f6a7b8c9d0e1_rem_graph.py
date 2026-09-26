"""REM business graph: typed versioned nodes, business edges with provenance, routing edges kept apart,
exact stock quantities, change events, impacts, suggested tasks, results and their dependencies.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from __future__ import annotations

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rem_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_rem_event_key"),
    )
    op.create_index(op.f("ix_rem_events_tenant_id"), "rem_events", ["tenant_id"], unique=False)
    op.create_table(
        "rem_nodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("created_seq", sa.BigInteger(), nullable=False),
        sa.Column("deleted_seq", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "type", "key", name="uq_rem_node_key"),
    )
    op.create_index(op.f("ix_rem_nodes_tenant_id"), "rem_nodes", ["tenant_id"], unique=False)
    op.create_table(
        "rem_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=True),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("policy", sa.String(length=24), nullable=False),
        sa.Column("snapshot_seq", sa.BigInteger(), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stopping_reason", sa.String(length=60), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("stale_reason", sa.Text(), nullable=True),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rem_results_tenant_id"), "rem_results", ["tenant_id"], unique=False)
    op.create_table(
        "rem_suggestions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=400), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("result_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("target_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requires", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("rule_id", sa.String(length=60), nullable=True),
        sa.Column("roots", postgresql.ARRAY(sa.String(length=64)), nullable=False),
        sa.Column("created_seq", sa.BigInteger(), nullable=True),
        sa.Column("superseded_seq", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_rem_suggestion"),
    )
    op.create_index(
        op.f("ix_rem_suggestions_event_id"), "rem_suggestions", ["event_id"], unique=False
    )
    op.create_index(
        op.f("ix_rem_suggestions_result_id"), "rem_suggestions", ["result_id"], unique=False
    )
    op.create_index(
        op.f("ix_rem_suggestions_tenant_id"), "rem_suggestions", ["tenant_id"], unique=False
    )
    op.create_table(
        "rem_tenant_state",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "rem_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("src_id", sa.UUID(), nullable=False),
        sa.Column("dst_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("provenance", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_pointers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("derivation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("edge_key", sa.String(length=400), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sys_from", sa.BigInteger(), nullable=False),
        sa.Column("sys_to", sa.BigInteger(), nullable=True),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dst_id"],
            ["rem_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["src_id"],
            ["rem_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rem_edges_dst", "rem_edges", ["tenant_id", "dst_id", "sys_to"], unique=False
    )
    op.create_index("ix_rem_edges_key", "rem_edges", ["tenant_id", "edge_key"], unique=False)
    op.create_index(
        "ix_rem_edges_src", "rem_edges", ["tenant_id", "src_id", "sys_to"], unique=False
    )
    op.create_index(op.f("ix_rem_edges_tenant_id"), "rem_edges", ["tenant_id"], unique=False)
    op.create_table(
        "rem_impacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("impact", sa.String(length=24), nullable=False),
        sa.Column("rule_id", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("paths", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("superseded_by", sa.UUID(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hypothesis", sa.Boolean(), nullable=False),
        sa.Column("requires", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("created_seq", sa.BigInteger(), nullable=False),
        sa.Column("superseded_seq", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["rem_events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["rem_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "target_id", "impact", name="uq_rem_impact"),
    )
    op.create_index(op.f("ix_rem_impacts_event_id"), "rem_impacts", ["event_id"], unique=False)
    op.create_index(op.f("ix_rem_impacts_target_id"), "rem_impacts", ["target_id"], unique=False)
    op.create_index(op.f("ix_rem_impacts_tenant_id"), "rem_impacts", ["tenant_id"], unique=False)
    op.create_table(
        "rem_node_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sys_from", sa.BigInteger(), nullable=False),
        sa.Column("sys_to", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("project_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("department_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("sensitivity", sa.Integer(), nullable=False),
        sa.Column("acl", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_pointers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("root_sources", postgresql.ARRAY(sa.String(length=300)), nullable=False),
        sa.Column("verification", sa.String(length=16), nullable=False),
        sa.Column("authoritative", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("review_status", sa.String(length=24), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["rem_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", "version", name="uq_rem_node_version"),
    )
    op.create_index(
        op.f("ix_rem_node_versions_node_id"), "rem_node_versions", ["node_id"], unique=False
    )
    op.create_index(
        op.f("ix_rem_node_versions_scope_id"), "rem_node_versions", ["scope_id"], unique=False
    )
    op.create_index(
        op.f("ix_rem_node_versions_tenant_id"), "rem_node_versions", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_rem_nv_current",
        "rem_node_versions",
        ["tenant_id", "node_id"],
        unique=False,
        postgresql_where="sys_to IS NULL",
    )
    op.create_index(
        "ix_rem_nv_sys", "rem_node_versions", ["node_id", "sys_from", "sys_to"], unique=False
    )
    op.create_index(
        "ix_rem_nv_tsv", "rem_node_versions", ["tsv"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "rem_result_deps",
        sa.Column("result_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["result_id"],
            ["rem_results.id"],
        ),
        sa.PrimaryKeyConstraint("result_id", "node_id"),
    )
    op.create_index("ix_rem_result_deps_node", "rem_result_deps", ["node_id"], unique=False)
    op.create_table(
        "rem_routing_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("src_id", sa.UUID(), nullable=False),
        sa.Column("dst_id", sa.UUID(), nullable=False),
        sa.Column("builder", sa.String(length=40), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("sys_from", sa.BigInteger(), nullable=False),
        sa.Column("sys_to", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dst_id"],
            ["rem_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["src_id"],
            ["rem_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rem_routing_edges_tenant_id"), "rem_routing_edges", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_rem_routing_src", "rem_routing_edges", ["tenant_id", "src_id", "sys_to"], unique=False
    )
    op.create_table(
        "rem_stock",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("holder_id", sa.UUID(), nullable=False),
        sa.Column("qty_on_hand", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("qty_reserved", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("sensitivity", sa.Integer(), nullable=False),
        sa.Column("source_pointers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sys_from", sa.BigInteger(), nullable=False),
        sa.Column("sys_to", sa.BigInteger(), nullable=True),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["holder_id"],
            ["rem_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["rem_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rem_stock_product", "rem_stock", ["tenant_id", "product_id", "sys_to"], unique=False
    )
    op.create_index(op.f("ix_rem_stock_tenant_id"), "rem_stock", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rem_stock_tenant_id"), table_name="rem_stock")
    op.drop_index("ix_rem_stock_product", table_name="rem_stock")
    op.drop_table("rem_stock")
    op.drop_index("ix_rem_routing_src", table_name="rem_routing_edges")
    op.drop_index(op.f("ix_rem_routing_edges_tenant_id"), table_name="rem_routing_edges")
    op.drop_table("rem_routing_edges")
    op.drop_index("ix_rem_result_deps_node", table_name="rem_result_deps")
    op.drop_table("rem_result_deps")
    op.drop_index("ix_rem_nv_tsv", table_name="rem_node_versions", postgresql_using="gin")
    op.drop_index("ix_rem_nv_sys", table_name="rem_node_versions")
    op.drop_index(
        "ix_rem_nv_current", table_name="rem_node_versions", postgresql_where="sys_to IS NULL"
    )
    op.drop_index(op.f("ix_rem_node_versions_tenant_id"), table_name="rem_node_versions")
    op.drop_index(op.f("ix_rem_node_versions_scope_id"), table_name="rem_node_versions")
    op.drop_index(op.f("ix_rem_node_versions_node_id"), table_name="rem_node_versions")
    op.drop_table("rem_node_versions")
    op.drop_index(op.f("ix_rem_impacts_tenant_id"), table_name="rem_impacts")
    op.drop_index(op.f("ix_rem_impacts_target_id"), table_name="rem_impacts")
    op.drop_index(op.f("ix_rem_impacts_event_id"), table_name="rem_impacts")
    op.drop_table("rem_impacts")
    op.drop_index(op.f("ix_rem_edges_tenant_id"), table_name="rem_edges")
    op.drop_index("ix_rem_edges_src", table_name="rem_edges")
    op.drop_index("ix_rem_edges_key", table_name="rem_edges")
    op.drop_index("ix_rem_edges_dst", table_name="rem_edges")
    op.drop_table("rem_edges")
    op.drop_table("rem_tenant_state")
    op.drop_index(op.f("ix_rem_suggestions_tenant_id"), table_name="rem_suggestions")
    op.drop_index(op.f("ix_rem_suggestions_result_id"), table_name="rem_suggestions")
    op.drop_index(op.f("ix_rem_suggestions_event_id"), table_name="rem_suggestions")
    op.drop_table("rem_suggestions")
    op.drop_index(op.f("ix_rem_results_tenant_id"), table_name="rem_results")
    op.drop_table("rem_results")
    op.drop_index(op.f("ix_rem_nodes_tenant_id"), table_name="rem_nodes")
    op.drop_table("rem_nodes")
    op.drop_index(op.f("ix_rem_events_tenant_id"), table_name="rem_events")
    op.drop_table("rem_events")
