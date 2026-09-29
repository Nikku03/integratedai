"""Consistency steps every change goes through, whatever analysis runs after it.

* Generated content (``authoritative`` false) that is derived from a record gets that record's access when the
  record becomes more restricted, because it may carry the record's content. This is a permission rule, so it
  lives here and not in an optional analysis.
* Generated content derived from a changed, deleted or restricted record is marked ``invalidated``.
* Cached results that used a changed record are marked stale, with the reason.
"""

from __future__ import annotations

import uuid
from collections import deque

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cie.state.models import RemResult, RemResultDep
from cie.state.store import GraphReader, GraphWriter

CONTENT_FIELDS = ("name", "summary", "attrs", "source_pointers")
MAX_DERIVED_DEPTH = 4


def propagate_access(writer: GraphWriter, restricted: list[uuid.UUID], seq: int, max_depth: int = 10) -> list[uuid.UUID]:
    """Narrow the access of generated content derived (transitively) from restricted records. Returns the ids narrowed."""
    reader = GraphReader(writer.s, writer.tenant_id, None, seq=seq)
    narrowed: list[uuid.UUID] = []
    seen = set(restricted)
    queue = deque((r, 0) for r in restricted)
    while queue:
        nid, depth = queue.popleft()
        if depth >= max_depth:
            continue
        src = writer.current(nid)
        if src is None:
            continue
        edges, views, _ = reader.edges([nid], kinds=("derived_from",), direction="in")
        for e in edges:
            dep = views.get(e.src)
            if dep is None or dep.authoritative or dep.id in seen:
                continue
            cur = writer.current(dep.id)
            if cur is None:
                continue
            acl = (cur.acl if cur.acl else None) or dict(src.acl or {})
            if cur.scope_id != src.scope_id or cur.sensitivity < src.sensitivity or (cur.acl or {}) != acl:
                writer.revise(dep.id, scope_id=src.scope_id, sensitivity=max(cur.sensitivity, src.sensitivity), acl=acl)
                narrowed.append(dep.id)
            seen.add(dep.id)
            queue.append((dep.id, depth + 1))
    return narrowed


def invalidate_derived(writer: GraphWriter, changed: dict[uuid.UUID, list[str]], deleted: list[uuid.UUID],
                       restricted: list[uuid.UUID], seq: int) -> list[uuid.UUID]:
    """Mark generated content derived from a changed, deleted or restricted record as ``invalidated``.

    A content change reaches generated content through chains of ``derived_from`` (up to ``MAX_DERIVED_DEPTH``);
    a deletion or restriction reaches the content derived directly from the record. Claims are skipped: a claim
    quotes its passage and is re-checked against the record instead."""
    now = GraphReader(writer.s, writer.tenant_id, None, seq=seq)
    before = GraphReader(writer.s, writer.tenant_id, None, seq=seq - 1)
    marked: list[uuid.UUID] = []
    starts: list[tuple[uuid.UUID, int, GraphReader]] = []
    for nid, fields in changed.items():
        if nid in deleted or "created" in fields:
            continue
        if any(f.split(".")[0] in CONTENT_FIELDS for f in fields):
            starts.append((nid, MAX_DERIVED_DEPTH, now))
    starts += [(d, 1, before) for d in deleted] + [(r, 1, now) for r in restricted]
    for start, limit, reader in starts:
        seen = {start}
        queue = deque([(start, 1)])
        while queue:
            nid, depth = queue.popleft()
            if depth > limit:
                continue
            edges, views, _ = reader.edges([nid], kinds=("derived_from",), direction="in")
            for e in edges:
                d = views.get(e.src)
                if d is None or d.id in seen or d.type == "claim":
                    continue
                seen.add(d.id)
                if not d.authoritative:
                    cur = writer.current(d.id)
                    if cur is not None and cur.review_status != "invalidated":
                        writer.revise(d.id, review_status="invalidated")
                        marked.append(d.id)
                queue.append((d.id, depth + 1))
    return marked


def invalidate_results(session: Session, tenant_id: uuid.UUID, changed: list[uuid.UUID], restricted: list[uuid.UUID], seq: int,
                       event_id: uuid.UUID) -> int:
    """Mark cached results that used a changed record as stale (and say why)."""
    if not changed and not restricted:
        return 0
    ids = set(changed) | set(restricted)
    res = session.execute(update(RemResult).where(
        RemResult.tenant_id == tenant_id, RemResult.stale.is_(False),
        RemResult.id.in_(select(RemResultDep.result_id).where(RemResultDep.node_id.in_(ids))))
        .values(stale=True, stale_reason=f"records it used changed at seq {seq} (event {event_id})"))
    return res.rowcount or 0
