"""Workflow tables: what each task used, every transition it went through, and invalidations by state changes."""

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cie.core.models import Base


class TaskInput(Base):
    """A versioned input of a task: a live-state record (``record``, version = record version), another task's
    result (``task``, version = that task's revision when it was used) or another task's released output
    (``output``, version = the output's version). A task whose inputs moved on cannot complete."""

    __tablename__ = "task_inputs"
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), primary_key=True)
    ref_kind: Mapped[str] = mapped_column(String(8), primary_key=True)  # record | task | output
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int | None] = mapped_column(BigInteger)  # the state snapshot it was read at (records)
    label: Mapped[str] = mapped_column(String(300), default="")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_task_inputs_ref", "ref_kind", "ref_id"),)


class TaskOutput(Base):
    """A named result a task releases while it runs (``engine.publish_output``), so the tasks that need only that
    result can start before the whole task is done. ``version`` goes up only when the value changes: releasing the
    same value again disturbs nobody. ``revising``: the task was reopened and has not re-released it yet."""

    __tablename__ = "task_outputs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    value: Mapped[Any] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text, default="")
    state_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)  # the live-state records it rests on
    status: Mapped[str] = mapped_column(String(12), default="current")  # current | revising
    produced_by: Mapped[str] = mapped_column(String(120), default="")
    task_revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("task_id", "key", name="uq_task_output_key"),)


class TaskTransition(Base):
    __tablename__ = "task_transitions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskInvalidation(Base):
    """A state change that invalidated a task's input. Unique per (task, input, change sequence number), so
    re-delivering or re-processing the same change never reopens a task twice."""

    __tablename__ = "task_invalidations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), index=True)
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    from_version: Mapped[int] = mapped_column(Integer)
    to_version: Mapped[int] = mapped_column(Integer)  # 0 when the record was deleted or hidden
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    seq: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(24))  # reopened | flagged | blocked | noted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("task_id", "ref_id", "seq", name="uq_task_invalidation_seq"),)
