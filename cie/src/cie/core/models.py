"""Database schema for the Company Intelligence Engine.

Layers (see docs/SCHEMA.md):

* Tenancy and access control: tenants, principals, roles, grants, scopes
* Immutable raw vault: blobs (content-addressed), documents (metadata + versions)
* Processing: jobs (durable queue with checkpoints), extractions, pages, blocks,
  corrections, sections
* Structured memory: memory_records (typed, versioned, bitemporal), record_links
  (sparse graph), glyphs live inside memory_records.glyph
* Agents: agents, agent_scorecards, projects, tasks, task_dependencies,
  agent_messages, ledger_entries, evidence_packets, answers
* Governance: audit_log, approvals, deletion_requests, prompt_versions, metrics

Nothing important is overwritten: records are superseded, contradicted,
confirmed or extended by new records; the ledger and audit log are append-only.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    DDL,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from cie.memory.text import TSV_FUNCTIONS

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ts_created():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# --------------------------------------------------------------------------
# Tenancy, principals, scopes, permissions
# --------------------------------------------------------------------------


class ScopeKind(str, enum.Enum):
    company = "company"
    department = "department"
    project = "project"
    agent = "agent"
    task = "task"


class PrincipalKind(str, enum.Enum):
    user = "user"
    agent = "agent"
    service = "service"


class Permission(str, enum.Enum):
    read = "read"
    write = "write"
    admin = "admin"


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = _ts_created()


class Principal(Base):
    """A user, agent or service that can hold permissions."""

    __tablename__ = "principals"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[PrincipalKind] = mapped_column(Enum(PrincipalKind, name="principal_kind"))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # ABAC attrs
    api_key_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_principal_name"),)


class Scope(Base):
    """Memory hierarchy node: company > department > project > agent > task.

    Information is inherited by permission and relevance along the parent chain,
    never physically copied per level.
    """

    __tablename__ = "scopes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[ScopeKind] = mapped_column(Enum(ScopeKind, name="scope_kind"))
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scopes.id"), index=True)
    path: Mapped[str] = mapped_column(Text, index=True)  # materialized path of ids
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (UniqueConstraint("tenant_id", "parent_id", "name", name="uq_scope_name"),)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    permission: Mapped[Permission] = mapped_column(Enum(Permission, name="permission"))
    max_sensitivity: Mapped[int] = mapped_column(Integer, default=1)  # ABAC: clearance
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_role_name"),)


class Grant(Base):
    """principal has role within scope (and all descendant scopes)."""

    __tablename__ = "grants"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))
    scope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scopes.id"), index=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (
        UniqueConstraint("principal_id", "role_id", "scope_id", name="uq_grant"),
    )


# --------------------------------------------------------------------------
# Immutable raw vault
# --------------------------------------------------------------------------


class Blob(Base):
    """Content-addressed immutable bytes. Deduplicated by sha256 per tenant."""

    __tablename__ = "blobs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(200))
    storage_uri: Mapped[str] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (UniqueConstraint("tenant_id", "sha256", name="uq_blob_sha"),)


class Document(Base):
    """A file as it exists in the organization. Points at an immutable blob.

    New versions of the same logical file get a new Document row with
    ``previous_version_id`` set and the same ``family_id``.
    """

    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    blob_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blobs.id"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    title: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(Text)
    original_location: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100), default="upload")  # upload|connector:x
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    scope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scopes.id"), index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scopes.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scopes.id"))
    doc_type: Mapped[str | None] = mapped_column(String(100))  # contract|email|report|...
    language: Mapped[str | None] = mapped_column(String(16))
    sensitivity: Mapped[int] = mapped_column(Integer, default=1)  # 0 public .. 4 restricted
    acl: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # explicit allow/deny
    retention_policy: Mapped[str] = mapped_column(String(100), default="default")
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    file_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = _ts_created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="ingested")  # ingested|extracting|indexed|failed
    injection_flags: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    pii_flags: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    blob: Mapped[Blob] = relationship()


# --------------------------------------------------------------------------
# Durable jobs and document processing
# --------------------------------------------------------------------------


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class Job(Base):
    """Durable task queue row. Checkpoints let interrupted work resume."""

    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="job_status"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = _ts_created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (Index("ix_jobs_pick", "status", "run_after"),)


class Extraction(Base):
    """One run of an extractor over a document. Kept separate from corrections."""

    __tablename__ = "extractions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    extractor: Mapped[str] = mapped_column(String(100))  # pymupdf|tesseract|unlimited_ocr|...
    extractor_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(32), default="running")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str | None] = mapped_column(String(16))
    mean_confidence: Mapped[float | None] = mapped_column(Float)
    completeness: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _ts_created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Page(Base):
    __tablename__ = "pages"
    id: Mapped[uuid.UUID] = _uuid_pk()
    extraction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extractions.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)  # 1-based
    width: Mapped[float] = mapped_column(Float, default=0.0)
    height: Mapped[float] = mapped_column(Float, default=0.0)
    text: Mapped[str] = mapped_column(Text, default="")
    text_sha256: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(50))  # text|ocr
    image_uri: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("extraction_id", "page_no", name="uq_page"),)


class Block(Base):
    """Layout block on a page with a bounding box in page coordinates (points)."""

    __tablename__ = "blocks"
    id: Mapped[uuid.UUID] = _uuid_pk()
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    order_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))  # text|table|figure|signature|formula|heading
    bbox: Mapped[list[Any]] = mapped_column(JSONB)  # [x0, y0, x1, y1]
    text: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # table cells etc.
    confidence: Mapped[float | None] = mapped_column(Float)


class Correction(Base):
    """An OCR correction. The original block text is never modified."""

    __tablename__ = "corrections"
    id: Mapped[uuid.UUID] = _uuid_pk()
    block_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blocks.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    original_text: Mapped[str] = mapped_column(Text)
    corrected_text: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(50))
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = _ts_created()


class Section(Base):
    """Semantic section of a document: the retrievable unit above pages.

    ``spans`` holds exact provenance: [{page_no, block_ids, bbox}].
    """

    __tablename__ = "sections"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    extraction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extractions.id"), index=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scopes.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer, default=1)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64), index=True)
    token_estimate: Mapped[int] = mapped_column(Integer)
    spans: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # 16-bit floats: half the bytes of 32-bit ones, and what the vector index compares anyway. Keyword search uses the
    # GIN index on cie_section_tsv(title, text) (cie.memory.text); no tsvector is stored.
    embedding: Mapped[Any] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=True)
    sensitivity: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        Index("ix_sections_trgm", "title", postgresql_using="gin",
              postgresql_ops={"title": "gin_trgm_ops"}),
    )


class SectionFacts(Base):
    """The facts a language model extracted from one section, for one extractor (cie.memory.facts).

    One row per section and extractor ``signature`` (model, revision, prompt, output cap): a run that stops halfway
    leaves rows for what it finished, and the next run extracts only the sections without one. ``facts`` holds each
    line with the checks made when it was written (numbers not in the section, word support, tag line), so reading
    never checks again. ``input_sha256`` is the hash of exactly what the model was given: a section whose input
    matches one already extracted (a new version of a document, with this part unchanged) takes those facts without
    asking the model. Scope and sensitivity are the section's, copied for permission filters.
    """

    __tablename__ = "section_facts"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scopes.id"), index=True)
    sensitivity: Mapped[int] = mapped_column(Integer, default=1)
    extractor: Mapped[str] = mapped_column(String(200))  # readable: model@revision
    signature: Mapped[str] = mapped_column(String(32))  # hash of the extractor's settings, see cie.memory.facts.signature
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    section_sha256: Mapped[str] = mapped_column(String(64))  # the section's text when it was extracted
    input_sha256: Mapped[str] = mapped_column(String(64))  # what the model was given (instructions, titles, text)
    status: Mapped[str] = mapped_column(String(16))  # done|empty|capped|skipped
    facts: Mapped[list[Any]] = mapped_column(JSONB, default=list)  # [{"text", "numbers_in_section", "support", "tag"}]
    text: Mapped[str] = mapped_column(Text, default="")  # the fact lines, one per line, for search
    n_facts: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[Any] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (
        UniqueConstraint("section_id", "signature", name="uq_section_facts"),
        Index("ix_section_facts_input", "tenant_id", "signature", "input_sha256"),
    )


# --------------------------------------------------------------------------
# Structured memory: typed records, glyphs, sparse graph
# --------------------------------------------------------------------------


class RecordType(str, enum.Enum):
    fact = "fact"
    entity = "entity"
    person = "person"
    organization = "organization"
    document = "document"
    project = "project"
    task = "task"
    decision = "decision"
    requirement = "requirement"
    deadline = "deadline"
    metric = "metric"
    contract_clause = "contract_clause"
    risk = "risk"
    hypothesis = "hypothesis"
    experiment = "experiment"
    result = "result"
    failure = "failure"
    contradiction = "contradiction"
    dependency = "dependency"
    code_artifact = "code_artifact"
    agent_message = "agent_message"
    open_question = "open_question"


class VerificationStatus(str, enum.Enum):
    unverified = "unverified"
    verified = "verified"
    disputed = "disputed"
    rejected = "rejected"


class MemoryRecord(Base):
    """Typed, versioned, bitemporal memory record.

    * ``event_time`` / ``valid_from`` / ``valid_to``: when the fact holds in the world.
    * ``recorded_at``: when the system learned it (transaction time).
    * ``superseded_by_id``: set when a newer record replaces this one; the row is kept.
    * ``glyph``: compact machine-readable memory card (see cie.memory.glyph).
    """

    __tablename__ = "memory_records"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scopes.id"), index=True)
    type: Mapped[RecordType] = mapped_column(Enum(RecordType, name="record_type"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # typed payload
    detail: Mapped[str] = mapped_column(Text, default="")
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    source_locations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # [{"page_no": 3, "bbox": [..], "section_id": "...", "block_id": "...", "quote": "..."}]
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = _ts_created()
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    producing_agent: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    verification: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status"),
        default=VerificationStatus.unverified,
    )
    sensitivity: Mapped[int] = mapped_column(Integer, default=1)
    acl: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_records.id"), index=True
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memory_records.id"))
    entity_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    glyph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding: Mapped[Any] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=True)  # keyword index: cie_record_tsv
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(100))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_records_keywords", "keywords", postgresql_using="gin"),
        Index("ix_records_summary_trgm", "summary", postgresql_using="gin",
              postgresql_ops={"summary": "gin_trgm_ops"}),
        Index("ix_records_scope_type", "scope_id", "type"),
        Index("ix_records_time", "valid_from", "valid_to"),
    )


# Keyword indexes on expressions, not on stored tsvectors (cie.memory.text). The functions are created before the
# tables, so that create_all (tests, fresh installs) can build these indexes; migrations create them too.
for _sql in TSV_FUNCTIONS.values():
    event.listen(Base.metadata, "before_create", DDL(_sql))
Index("ix_sections_tsv", func.cie_section_tsv(Section.title, Section.text), postgresql_using="gin")
Index("ix_records_tsv", func.cie_record_tsv(MemoryRecord.summary, MemoryRecord.keywords, MemoryRecord.detail), postgresql_using="gin")
Index("ix_section_facts_tsv", func.cie_facts_tsv(SectionFacts.text), postgresql_using="gin")


class LinkKind(str, enum.Enum):
    depends_on = "depends_on"
    relates_to = "relates_to"
    mentions = "mentions"
    causes = "causes"
    precedes = "precedes"
    supersedes = "supersedes"
    contradicts = "contradicts"
    confirms = "confirms"
    extends = "extends"
    part_of = "part_of"
    assigned_to = "assigned_to"
    derived_from = "derived_from"
    shortcut = "shortcut"  # long-range edge, only with justification
    coactivated = "coactivated"  # formed by the bank itself when records fire together (cie.topology.dynamic)
    references = "references"  # one document explicitly cites another (ticket key, PR, page, CRM id)
    near_duplicate = "near_duplicate"  # two documents say nearly the same thing (possibly with different facts)


class RecordLink(Base):
    """Sparse memory graph edge."""

    __tablename__ = "record_links"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    src_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memory_records.id"), index=True)
    dst_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memory_records.id"), index=True)
    kind: Mapped[LinkKind] = mapped_column(Enum(LinkKind, name="link_kind"))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    justification: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (UniqueConstraint("src_id", "dst_id", "kind", name="uq_link"),)


# --------------------------------------------------------------------------
# Agents, projects, tasks, messages, ledger
# --------------------------------------------------------------------------


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(50))  # head|research|finance|legal|operations|engineering
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    task_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    strategy: Mapped[str] = mapped_column(String(50), default="extractive")  # extractive|llm
    model: Mapped[str | None] = mapped_column(String(100))
    cost_per_1k_tokens: Mapped[float] = mapped_column(Float, default=0.0)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=2)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    memory_scope_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scopes.id"))
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_agent_name"),)


class AgentScorecard(Base):
    """Per (agent, task_type) running performance. Routing reads these."""

    __tablename__ = "agent_scorecards"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(64))
    n_tasks: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.5)
    citation_quality: Mapped[float] = mapped_column(Float, default=0.5)
    completion_rate: Mapped[float] = mapped_column(Float, default=0.5)
    latency_ms_avg: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_avg: Mapped[float] = mapped_column(Float, default=0.0)
    compute_cost_avg: Mapped[float] = mapped_column(Float, default=0.0)
    human_corrections: Mapped[int] = mapped_column(Integer, default=0)
    hallucination_rate: Mapped[float] = mapped_column(Float, default=0.0)
    verification_score: Mapped[float] = mapped_column(Float, default=0.5)
    last_task_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (UniqueConstraint("agent_id", "task_type", name="uq_scorecard"),)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scopes.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    head_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    token_budget: Mapped[int] = mapped_column(BigInteger, default=200_000_000)
    created_at: Mapped[datetime] = _ts_created()


class TaskStatus(str, enum.Enum):
    """Proposed -> Ready -> Running -> Review -> Completed, with Blocked, Failed and Cancelled; transitions are
    enforced by ``cie.workflow.engine``. (Earlier values pending, assigned, needs_verification, verified, done and
    awaiting_approval remain in the database type but are no longer used.)"""

    proposed = "proposed"
    ready = "ready"
    running = "running"
    blocked = "blocked"
    review = "review"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"))
    scope_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scopes.id"))
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    brief: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")  # low|medium|high
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    assignment_reason: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_packet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    verification: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    verifies_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # tokens, latency, cost
    # workflow engine (cie.workflow.engine)
    owner_principal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # who answers for the outcome
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acceptance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # criteria checked at review
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # max_tokens, max_cost_usd, max_seconds, tools
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # checkpoints; kept across reassignment
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    review_rounds: Mapped[int] = mapped_column(Integer, default=0)
    max_review_rounds: Mapped[int] = mapped_column(Integer, default=1)
    retry_authorized_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, default=0)  # +1 on every transition
    created_at: Mapped[datetime] = _ts_created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (Index("ix_tasks_ready", "tenant_id", "status", "priority", "created_at"),
                      Index("ix_tasks_lease", "status", "lease_expires_at"))


class TaskDependency(Base):
    """``requires``: the dependency must be completed, or, when ``outputs`` names some of its outputs, only those
    must be released (``cie.workflow.engine.publish_output``), so the dependant can start while the dependency is
    still running. ``after``: it must be settled (completed, failed or cancelled), e.g. a synthesis that reports
    failures instead of waiting for them forever."""

    __tablename__ = "task_dependencies"
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    depends_on_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12), default="requires")
    outputs: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")


class MessageKind(str, enum.Enum):
    task_request = "task_request"
    evidence_request = "evidence_request"
    intermediate_result = "intermediate_result"
    dependency_notification = "dependency_notification"
    contradiction = "contradiction"
    verification_request = "verification_request"
    final_result = "final_result"
    failure_report = "failure_report"
    input_changed = "input_changed"  # a record the task used changed (cie.workflow.routing)
    work_request = "work_request"  # an agent asks another role for work (cie.workflow.engine.request_work)
    work_decision = "work_decision"  # a request was accepted, merged, declined, or ended without an answer
    question = "question"  # an agent asks the head (or a person) something it cannot decide itself
    answer = "answer"  # the reply to a question


class AgentMessage(Base):
    """Structured point-to-point message. Agents never broadcast full context."""

    __tablename__ = "agent_messages"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    from_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    to_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    kind: Mapped[MessageKind] = mapped_column(Enum(MessageKind, name="message_kind"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _ts_created()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the recipient read it


class LedgerEntry(Base):
    """Append-only, hash-chained project ledger."""

    __tablename__ = "ledger_entries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    # objective|requirement|plan|task|assignment|hypothesis|test|result|failure|decision|
    # artifact|commit|blocker|next_action
    label: Mapped[str | None] = mapped_column(String(64))  # e.g. H17
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    refs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # links to records/tasks
    actor: Mapped[str | None] = mapped_column(String(100))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (UniqueConstraint("project_id", "seq", name="uq_ledger_seq"),)


class EvidencePacket(Base):
    """The compact set of records handed to a model. Reproducible by id."""

    __tablename__ = "evidence_packets"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    query: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(32))
    scope_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    items: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = _ts_created()


class Answer(Base):
    __tablename__ = "answers"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    packet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_packets.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[str] = mapped_column(String(64))  # strict|assisted|extractive (model declined)|extractive (model answer not verifiable)
    status: Mapped[str] = mapped_column(String(32))  # answered|insufficient_evidence|conflict
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    unsupported_claims: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _ts_created()


# --------------------------------------------------------------------------
# Governance
# --------------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_kind: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    outcome: Mapped[str] = mapped_column(String(16), default="ok")  # ok|denied|error
    created_at: Mapped[datetime] = _ts_created()


class Approval(Base):
    """Human approval gate."""

    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))  # task_result|deletion|high_risk_answer
    subject_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")
    requested_by: Mapped[str | None] = mapped_column(String(100))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_created()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|blocked_hold|approved|executed|rejected
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id"))
    created_at: Mapped[datetime] = _ts_created()
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts_created()
    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompt_version"),)


class Metric(Base):
    """Token, latency, compute and storage measurements."""

    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[float] = mapped_column(Float)
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _ts_created()


__all__ = [name for name in dir() if not name.startswith("_")]

# Keep unused-import linters quiet for names re-exported through __all__.
_ = (JSON, text)


# Live-state tables (the versioned business graph) live in cie.state; importing registers them with Base.metadata.
from cie.actions import models as _action_models  # noqa: E402,F401
from cie.context import models as _context_models  # noqa: E402,F401
from cie.playbooks import models as _playbook_models  # noqa: E402,F401
from cie.retrieval import lexical_models as _lexical_models  # noqa: E402,F401
from cie.state import models as _state_models  # noqa: E402,F401
from cie.workflow import models as _workflow_models  # noqa: E402,F401
