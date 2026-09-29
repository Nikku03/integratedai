"""Actions on external systems, and every check they passed or failed on the way."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cie.core.models import Base

# proposed -> awaiting_approval -> approved -> executing -> executed -> confirmed | unconfirmed
#          \-> refused (permission)   \-> rejected   \-> stale (its basis changed)   \-> failed (retry with the same key)
STATUSES = ("awaiting_approval", "approved", "refused", "rejected", "stale", "executing", "executed", "confirmed", "unconfirmed",
            "failed", "cancelled")


class Action(Base):
    """One action on an external system (book a shipment, send a message, create an order). ``idempotency_key`` is
    unique per tenant and is passed to the connector, so an action is carried out at most once. ``based_on`` holds
    the state versions and the task revision it rests on: if any moved on, it is not executed."""

    __tablename__ = "actions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(64))  # the connector
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), index=True)
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    principal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("principals.id"))
    amount: Mapped[float | None] = mapped_column(Float)
    authority_kind: Mapped[str | None] = mapped_column(String(64))
    based_on: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # {"records": [{ref, version}], "task": {id, revision}}
    checks: Mapped[list[Any]] = mapped_column(JSONB, default=list)  # every check run, in order, with its outcome
    approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    receipt: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_key"),)
