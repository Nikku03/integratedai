"""Playbook versions and the decisions made with them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cie.core.models import Base

PLAYBOOK_STATUSES = ("draft", "approved", "rejected", "retired")


class Playbook(Base):
    """One version of a playbook. Only an ``approved`` version decides; approving a version retires the one before.
    A draft with problems cannot be approved; ``quotes`` says, for each rule, whether its quote was found in the
    source documents."""

    __tablename__ = "playbooks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))  # what it decides, across versions, e.g. "expense-approval"
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    spec_hash: Mapped[str] = mapped_column(String(64))
    problems: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    quotes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # rule -> quote found in the sources
    source_document_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    drafted_by: Mapped[str] = mapped_column(String(120), default="")
    approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("principals.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("tenant_id", "key", "version", name="uq_playbook_version"),
                      Index("ix_playbook_key_status", "tenant_id", "key", "status"))


class PlaybookDecision(Base):
    """A decision: yes, no or unknown, with its proof and every fact it read. ``given`` holds the facts supplied
    with the request, so the decision can be made again; ``record_keys`` the live-state records it read
    (``type:key``), so a change to one of them makes it again. A decision made again supersedes the one before for
    the same playbook, goal and subject."""

    __tablename__ = "playbook_decisions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    playbook_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("playbooks.id"), index=True)
    playbook_key: Mapped[str] = mapped_column(String(120))
    goal: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(300), default="")
    answer: Mapped[str] = mapped_column(String(8))  # yes | no | unknown
    given: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sources: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    proof: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    why: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    missing: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    notes: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    based_on: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # {"records": [{ref, version, label}]}
    record_keys: Mapped[list[str]] = mapped_column(ARRAY(String(340)), default=list)
    status: Mapped[str] = mapped_column(String(16), default="current")  # current | superseded
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text, default="")  # why it was made (again)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("principals.id"))
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    seq: Mapped[int | None] = mapped_column(BigInteger)  # the live state's change sequence it read
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_pb_decision_subject", "tenant_id", "playbook_key", "goal", "subject", "status"),
                      Index("ix_pb_decision_records", "record_keys", postgresql_using="gin"))
