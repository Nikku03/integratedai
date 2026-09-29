"""Entity views: one record as the business sees it now, with where every value came from.

The view is read under the caller's permissions: an invisible record returns nothing, and dependencies whose
other end the caller may not see are left out.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.state.fields import RESERVED_FIELDS
from cie.state.models import StateConflict, StateField
from cie.state.store import GraphReader, NodeView

DEPENDENCY_KINDS = ("depends_on", "blocks", "supplies", "governed_by", "owned_by", "derived_from", "supports", "contradicts",
                    "supersedes")


def _statement(r: StateField | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {"statement_id": str(r.id), "value": r.value, "source": {"system": r.source_system, "record": r.source_record,
                                                                  "kind": r.source_kind, "method": r.method},
            "rank": r.rank, "effective_at": r.effective_at.isoformat() if r.effective_at else None, "recorded_seq": r.recorded_seq,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None, "status": r.status, "decision": r.decision,
            "verification": r.verification, "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            "evidence": r.evidence or []}


def entity_view(session: Session, reader: GraphReader, type_: str, key: str, *, history: bool = False) -> dict[str, Any] | None:
    n = reader.node_by_key(type_, key)
    if n is None:
        return None
    return view_of(session, reader, n, history=history)


def view_of(session: Session, reader: GraphReader, n: NodeView, *, history: bool = False) -> dict[str, Any]:
    rows = list(session.scalars(select(StateField).where(StateField.tenant_id == reader.tenant_id, StateField.node_id == n.id)
                                .order_by(StateField.recorded_seq, StateField.recorded_at)))
    current = {r.field: r for r in rows if r.status == "current"}
    facts = {}
    for name, value in sorted((n.attrs or {}).items()):
        if name in RESERVED_FIELDS:
            continue
        st = current.get(name)
        facts[name] = {"value": value,
                       "statement": _statement(st) if st is not None else {"value": value, "source": {
                           "system": str((n.attrs or {}).get("source_system") or "direct"), "record": n.key, "kind": "unknown",
                           "method": "direct_write"}, "recorded_seq": n.sys_from, "status": "current",
                           "decision": "written directly on the record; no separate statement recorded",
                           "verification": n.verification, "evidence": n.source_pointers[:5]},
                       "other_statements": [_statement(r) for r in rows if r.field == name and r.status != "current"]
                       if history else sum(1 for r in rows if r.field == name and r.status != "current")}
    conflicts = list(session.scalars(select(StateConflict).where(StateConflict.tenant_id == reader.tenant_id, StateConflict.node_id == n.id,
                                                                 StateConflict.status == "open").order_by(StateConflict.opened_seq)))
    by_id = {r.id: r for r in rows}
    unresolved = [{"conflict_id": str(c.id), "field": c.field, "reason": c.reason, "opened_seq": c.opened_seq,
                   "current": _statement(by_id.get(c.current_field_id)), "challenger": _statement(by_id.get(c.challenger_field_id))}
                  for c in conflicts]
    edges, views, cut = reader.edges([n.id], kinds=DEPENDENCY_KINDS, direction="both", per_node=200)
    deps = []
    for e in edges:
        other = views.get(e.dst if e.src == n.id else e.src)
        if other is None:
            continue
        deps.append({"relation": e.kind, "direction": "out" if e.src == n.id else "in", "id": str(other.id), "type": other.type,
                     "key": other.key, "name": other.name, "status": (other.attrs or {}).get("status"), "version": other.version,
                     "provenance": e.provenance, "hypothesis": e.hypothesis})
    evidence = list(n.source_pointers or [])
    for r in current.values():
        evidence += [p for p in (r.evidence or []) if p not in evidence]
    return {
        "entity_id": f"{n.type}:{n.key}", "id": str(n.id), "type": n.type, "key": n.key, "name": n.name,
        "status": (n.attrs or {}).get("status"), "owner": (n.attrs or {}).get("owner"), "version": n.version,
        "as_of_seq": reader.seq, "project_ids": [str(p) for p in n.project_ids], "facts": facts, "dependencies": deps,
        "dependencies_truncated": bool(cut), "evidence": evidence, "unresolved": unresolved,
        "last_verified_at": (n.attrs or {}).get("last_verified_at"), "verification": n.verification,
        "review_status": n.review_status, "authoritative": n.authoritative,
    }


def open_conflicts(session: Session, reader: GraphReader, entity_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Open conflicts on records the reader may see."""
    q = select(StateConflict).where(StateConflict.tenant_id == reader.tenant_id, StateConflict.status == "open")
    rows = list(session.scalars(q.order_by(StateConflict.opened_seq.desc()).limit(limit * 3)))
    visible = reader.nodes({c.node_id for c in rows})
    out = []
    for c in rows:
        n = visible.get(c.node_id)
        if n is None or (entity_type and n.type != entity_type):
            continue
        cur = session.get(StateField, c.current_field_id) if c.current_field_id else None
        ch = session.get(StateField, c.challenger_field_id)
        out.append({"conflict_id": str(c.id), "entity_id": f"{n.type}:{n.key}", "name": n.name, "field": c.field, "reason": c.reason,
                    "opened_seq": c.opened_seq, "current": _statement(cur), "challenger": _statement(ch)})
        if len(out) >= limit:
            break
    return out

