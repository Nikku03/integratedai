"""Tables of the BM25 keyword index (cie.retrieval.bm25): the queue of rows the index has not taken in yet, and the
state of each tenant's index. The index itself lives on the filesystem."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cie.core.models import Base


class LexicalQueue(Base):
    """A record or section written or re-worded since the index last took it in. Filled by triggers on
    memory_records and sections in the writing transaction (``bm25.install``), emptied by ``bm25.sync`` and
    ``bm25.build``. Until then, keyword search scores these rows straight from the database."""

    __tablename__ = "lexical_queue"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(1))  # r: memory record, s: section
    row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_lexical_queue_tenant", "tenant_id", "kind", "row_id"),)


class LexicalState(Base):
    """One row per tenant with a BM25 index: ``building`` until the first build finishes, then ``ready``."""

    __tablename__ = "lexical_state"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="building")
    version: Mapped[str | None] = mapped_column(String(64))
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    docs: Mapped[int] = mapped_column(BigInteger, default=0)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
