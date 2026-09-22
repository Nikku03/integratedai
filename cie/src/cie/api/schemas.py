"""Pydantic request/response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScopeIn(BaseModel):
    kind: str
    name: str
    parent_id: uuid.UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ScopeOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    parent_id: uuid.UUID | None
    path: str


class DocumentOut(BaseModel):
    id: uuid.UUID
    family_id: uuid.UUID
    version: int
    title: str
    original_filename: str
    original_location: str | None
    source: str
    scope_id: uuid.UUID
    department_id: uuid.UUID | None
    project_id: uuid.UUID | None
    doc_type: str | None
    language: str | None
    sensitivity: int
    status: str
    sha256: str
    size_bytes: int
    media_type: str
    ingested_at: datetime
    file_created_at: datetime | None
    retention_policy: str
    legal_hold: bool
    injection_flags: int
    pii_flags: int


class IngestOut(BaseModel):
    document: DocumentOut
    created: bool
    deduplicated: bool
    job_id: uuid.UUID | None


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    progress: float
    attempts: int
    checkpoint: dict[str, Any]
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class RecordIn(BaseModel):
    scope_id: uuid.UUID
    type: str
    summary: str
    content: dict[str, Any] = Field(default_factory=dict)
    detail: str = ""
    source_document_id: uuid.UUID | None = None
    source_locations: list[dict[str, Any]] = Field(default_factory=list)
    event_time: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float = 0.5
    sensitivity: int = 1
    keywords: list[str] = Field(default_factory=list)
    acl: dict[str, Any] = Field(default_factory=dict)


class RecordOut(BaseModel):
    id: uuid.UUID
    scope_id: uuid.UUID
    type: str
    summary: str
    content: dict[str, Any]
    detail: str
    source_document_id: uuid.UUID | None
    source_locations: list[dict[str, Any]]
    event_time: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    recorded_at: datetime
    producing_agent: str | None
    confidence: float
    verification: str
    sensitivity: int
    version: int
    family_id: uuid.UUID
    superseded_by_id: uuid.UUID | None
    supersedes_id: uuid.UUID | None
    keywords: list[str]
    glyph: dict[str, Any]


class ReviseIn(BaseModel):
    new_record: RecordIn
    justification: str | None = None


class LinkIn(BaseModel):
    other_id: uuid.UUID
    reason: str = ""


class SearchIn(BaseModel):
    query: str
    scope_id: uuid.UUID
    filters: dict[str, Any] = Field(default_factory=dict)
    k: int = 50
    as_of: datetime | None = None
    use_graph: bool = True
    use_vector: bool = True
    use_lexical: bool = True
    max_records: int | None = None
    token_budget: int | None = None


class PacketOut(BaseModel):
    id: uuid.UUID
    query: str
    intent: str
    items: list[dict[str, Any]]
    token_estimate: int
    latency_ms: float
    trace: dict[str, Any]


class AnswerIn(SearchIn):
    mode: str = "strict"  # strict | assisted


class AnswerOut(BaseModel):
    id: uuid.UUID
    packet_id: uuid.UUID
    question: str
    answer: str
    status: str
    citations: list[dict[str, Any]]
    confidence: float
    mode: str
    model: str | None
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd: float
    usage_is_estimate: bool
    unsupported_claims: list[str]


class PageOut(BaseModel):
    document_id: uuid.UUID
    page_no: int
    width: float
    height: float
    method: str
    confidence: float | None
    text: str
    blocks: list[dict[str, Any]]
    corrections: list[dict[str, Any]]


class GrantIn(BaseModel):
    principal_name: str
    role: str
    scope_id: uuid.UUID


class PrincipalIn(BaseModel):
    name: str
    kind: str = "user"
    email: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class AuditOut(BaseModel):
    id: int
    principal_id: uuid.UUID | None
    action: str
    resource_kind: str | None
    resource_id: str | None
    details: dict[str, Any]
    outcome: str
    created_at: datetime
