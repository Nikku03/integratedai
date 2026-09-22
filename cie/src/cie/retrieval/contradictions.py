"""Contradiction check for a candidate set: every ``contradicts`` edge touching a
candidate pulls the other side into the packet and marks both."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cie.core.models import LinkKind, MemoryRecord, RecordLink


def find(session: Session, ids: list[uuid.UUID], base_filter) -> tuple[dict[uuid.UUID, list[uuid.UUID]], list[MemoryRecord]]:
    if not ids:
        return {}, []
    edges = list(session.scalars(select(RecordLink).where(
        RecordLink.kind == LinkKind.contradicts, or_(RecordLink.src_id.in_(ids), RecordLink.dst_id.in_(ids)))))
    conflicts: dict[uuid.UUID, list[uuid.UUID]] = {}
    missing: set[uuid.UUID] = set()
    idset = set(ids)
    for e in edges:
        for x, y in ((e.src_id, e.dst_id), (e.dst_id, e.src_id)):
            if y not in conflicts.setdefault(x, []):
                conflicts[x].append(y)
        for x in (e.src_id, e.dst_id):
            if x not in idset:
                missing.add(x)
    extra = list(session.scalars(select(MemoryRecord).where(base_filter, MemoryRecord.id.in_(list(missing))))) if missing else []
    return conflicts, extra
