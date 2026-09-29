"""Recorded context builds: what was assembled for whom, and how much of a collection was covered."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cie.core.models import Base


class ContextRun(Base):
    __tablename__ = "context_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(16))  # focused | exhaustive
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sources: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # items per channel, and what was skipped
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # exhaustive mode: visible, scanned, matched, unreadable
    complete: Mapped[bool] = mapped_column(Boolean, default=True)
    snapshot_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
