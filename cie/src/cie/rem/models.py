"""REM storage: a versioned, typed business graph of the company, kept apart from routing shortcuts.

G(t) = (V(t), E_business(t), E_routing(t)).

* ``rem_nodes`` hold identity (stable id, tenant, type, business key); every change writes a new
  ``rem_node_versions`` row, so the graph at any recorded moment can be read back.
* ``rem_edges`` are business relationships (depends_on, blocks, supplies, governed_by, owned_by,
  supports, contradicts, supersedes, derived_from), each with direction, source, validity interval and
  provenance class (explicit, rule-derived, model-inferred). Model-inferred edges are hypotheses until
  verified.
* ``rem_routing_edges`` are navigation shortcuts only. They are a separate table so that no query can
  mistake one for a business relationship, a causal link, or a grant of access.
* ``rem_stock`` holds exact business quantities (inventory); rules read numbers from here, not from text.
* Time: ``valid_from/valid_to`` is business validity; ``sys_from/sys_to`` is the tenant's monotonically
  increasing change sequence (recorded time), which makes snapshot-consistent reads and reproducible
  explanations possible. ``sys_to`` NULL means current.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cie.core.models import EMBEDDING_DIM, Base

NODE_TYPES = ("company", "department", "project", "person", "team", "agent", "customer", "supplier", "product", "contract",
              "order", "invoice", "task", "milestone", "requirement", "fact", "claim", "decision", "risk", "document",
              "passage", "artifact")
BUSINESS_EDGE_KINDS = ("depends_on", "blocks", "supplies", "governed_by", "owned_by", "supports", "contradicts",
                       "supersedes", "derived_from")
PROVENANCE = ("explicit", "rule", "inferred")  # explicit in a source record; derived by a named rule; proposed by a model
EDGE_STATUS = ("asserted", "hypothesis", "verified", "rejected")
VERIFICATION = ("unverified", "verified", "disputed", "rejected")


def _pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _tenant():
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)


class RemTenantState(Base):
    """The tenant's change sequence: every applied event advances it by one, under a per-tenant lock."""

    __tablename__ = "rem_tenant_state"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)


class RemNode(Base):
    __tablename__ = "rem_nodes"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    type: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(300))  # stable business key, e.g. "erp:PO-1042"
    created_seq: Mapped[int] = mapped_column(BigInteger)
    deleted_seq: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("tenant_id", "type", "key", name="uq_rem_node_key"),)


class RemNodeVersion(Base):
    __tablename__ = "rem_node_versions"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_nodes.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    sys_from: Mapped[int] = mapped_column(BigInteger)
    sys_to: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    project_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)  # membership: project nodes
    department_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scopes.id"), index=True)  # permission scope
    sensitivity: Mapped[int] = mapped_column(Integer, default=1)
    acl: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_pointers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    root_sources: Mapped[list[str]] = mapped_column(ARRAY(String(300)), default=list)  # original sources behind this node
    verification: Mapped[str] = mapped_column(String(16), default="unverified")
    authoritative: Mapped[bool] = mapped_column(Boolean, default=True)  # False for generated summaries and model output
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    review_status: Mapped[str | None] = mapped_column(String(24))  # needs_review / invalidated after a change upstream
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    __table_args__ = (
        UniqueConstraint("node_id", "version", name="uq_rem_node_version"),
        Index("ix_rem_nv_current", "tenant_id", "node_id", postgresql_where="sys_to IS NULL"),
        Index("ix_rem_nv_sys", "node_id", "sys_from", "sys_to"),
        Index("ix_rem_nv_tsv", "tsv", postgresql_using="gin"),
    )


class RemEdge(Base):
    """A business relationship, versioned like nodes. ``kind`` is one of BUSINESS_EDGE_KINDS."""

    __tablename__ = "rem_edges"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    src_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_nodes.id"))
    dst_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_nodes.id"))
    kind: Mapped[str] = mapped_column(String(24))
    provenance: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="asserted")
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_pointers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    derivation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # rule id / model and inputs, for derived edges
    edge_key: Mapped[str] = mapped_column(String(400))  # identity across versions: src|kind|dst|provenance|source
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sys_from: Mapped[int] = mapped_column(BigInteger)
    sys_to: Mapped[int | None] = mapped_column(BigInteger)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        Index("ix_rem_edges_src", "tenant_id", "src_id", "sys_to"),
        Index("ix_rem_edges_dst", "tenant_id", "dst_id", "sys_to"),
        Index("ix_rem_edges_key", "tenant_id", "edge_key"),
    )


class RemRoutingEdge(Base):
    """Navigation shortcut. Never a business relationship, never evidence, never a grant of access."""

    __tablename__ = "rem_routing_edges"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    src_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_nodes.id"))
    dst_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_nodes.id"))
    builder: Mapped[str] = mapped_column(String(40))  # e.g. "expander-d6"
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    sys_from: Mapped[int] = mapped_column(BigInteger)
    sys_to: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (Index("ix_rem_routing_src", "tenant_id", "src_id", "sys_to"),)


class RemStock(Base):
    """Exact inventory quantities from the system of record (a database value, not a graph relationship)."""

    __tablename__ = "rem_stock"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_nodes.id"))
    holder_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_nodes.id"))  # project (or site) holding it
    qty_on_hand: Mapped[float] = mapped_column(Numeric(18, 3))
    qty_reserved: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scopes.id"))
    sensitivity: Mapped[int] = mapped_column(Integer, default=1)
    source_pointers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    sys_from: Mapped[int] = mapped_column(BigInteger)
    sys_to: Mapped[int | None] = mapped_column(BigInteger)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (Index("ix_rem_stock_product", "tenant_id", "product_id", "sys_to"),)


class RemEvent(Base):
    """A change event. ``idempotency_key`` makes submission safe to repeat; ``seq`` is set when it is applied."""

    __tablename__ = "rem_events"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    idempotency_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | processing | done | failed
    seq: Mapped[int | None] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_rem_event_key"),)


class RemImpact(Base):
    """A candidate consequence of a change event for one node, with every path that reached it (paths do not add up)."""

    __tablename__ = "rem_impacts"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_events.id"), index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_nodes.id"), index=True)
    impact: Mapped[str] = mapped_column(String(24))  # at_risk | needs_review | covered | unblocked | invalidated | resolved
    rule_id: Mapped[str] = mapped_column(String(60))
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    paths: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16), default="candidate")  # candidate | superseded
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # rule inputs; "roots" = milestones it follows from
    hypothesis: Mapped[bool] = mapped_column(Boolean, default=False)  # reached through an unverified inferred relationship
    requires: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)  # every node it reveals
    created_seq: Mapped[int] = mapped_column(BigInteger)
    superseded_seq: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("event_id", "target_id", "impact", name="uq_rem_impact"),)


class RemSuggestion(Base):
    """A suggested verification task. REM names the capability needed; the head agent decides who does it."""

    __tablename__ = "rem_suggestions"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    dedupe_key: Mapped[str] = mapped_column(String(400))
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(Text)
    capability: Mapped[str] = mapped_column(String(40))
    target_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    reason: Mapped[str] = mapped_column(Text)
    priority: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(16), default="suggested")  # suggested | superseded
    requires: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)  # every node it reveals
    rule_id: Mapped[str | None] = mapped_column(String(60))
    roots: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)  # milestones whose assessment it follows from
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # requires_scopes: [scope, clearance] of exact values it shows
    created_seq: Mapped[int | None] = mapped_column(BigInteger)
    superseded_seq: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("tenant_id", "dedupe_key", name="uq_rem_suggestion"),)


class RemResult(Base):
    """A query or change-mode result, as returned to its requester, with the snapshot it read and its trace."""

    __tablename__ = "rem_results"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    principal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(8))  # query | change
    policy: Mapped[str] = mapped_column(String(24))  # search | traversal | rem | rem+routing
    snapshot_seq: Mapped[int] = mapped_column(BigInteger)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # frontier and visited set, for resuming
    status: Mapped[str] = mapped_column(String(16))  # complete | incomplete
    stopping_reason: Mapped[str] = mapped_column(String(60))
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    stale_reason: Mapped[str | None] = mapped_column(Text)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RemResultDep(Base):
    """Which node versions a result used, so a change can mark every result that depended on it as stale."""

    __tablename__ = "rem_result_deps"
    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rem_results.id"), primary_key=True)
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    __table_args__ = (Index("ix_rem_result_deps_node", "node_id"),)
