"""Change mode: idempotent events -> versioned graph updates -> rule-based candidate impacts and verification tasks.

An event is stored once per (tenant, idempotency key); submitting it again returns the stored event. Processing
happens in one transaction under the tenant lock: the event takes the next sequence number, its operations write
new versions (nothing is overwritten or removed), the rules run against the snapshot that includes them, and
impacts, suggestions, stale marks and the audit entry are written with it. A crash rolls all of it back and the
worker's retry applies it once; a processed event is never applied twice.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cie.core.models import Scope
from cie.governance.audit import audit
from cie.rem import domain
from cie.rem.budget import Budget, Limits
from cie.rem.models import RemEvent, RemImpact, RemResult, RemResultDep, RemSuggestion
from cie.rem.rules import RuleEngine, reachability_baseline
from cie.rem.store import GraphReader, GraphWriter

EVENT_KINDS = ("ops", "supplier_delay", "stock_count", "task_status", "restrict")


class IdempotencyConflict(ValueError):
    """The idempotency key was already used for a different payload."""


def _digest(kind: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([kind, payload], sort_keys=True, default=str).encode()).hexdigest()


def submit_event(session: Session, tenant_id: uuid.UUID, *, kind: str, payload: dict[str, Any], idempotency_key: str,
                 principal_id: uuid.UUID | None = None) -> tuple[RemEvent, bool]:
    """Store an event once. Returns (event, created). Re-submitting the same key and payload is a no-op."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"event kind must be one of {EVENT_KINDS}")
    digest = _digest(kind, payload)
    ev = session.scalar(select(RemEvent).where(RemEvent.tenant_id == tenant_id, RemEvent.idempotency_key == idempotency_key))
    if ev is not None:
        if (ev.summary or {}).get("payload_sha256") not in (None, digest):
            raise IdempotencyConflict(f"idempotency key {idempotency_key!r} was used for a different event")
        return ev, False
    ev = RemEvent(tenant_id=tenant_id, idempotency_key=idempotency_key, kind=kind, payload=payload, principal_id=principal_id,
                  status="queued", summary={"payload_sha256": digest})
    session.add(ev)
    session.flush()
    return ev, True


# ---------------------------------------------------------------------------------------------- operations
def _scope_id(session: Session, tenant_id: uuid.UUID, scope: Any, cache: dict) -> uuid.UUID:
    if isinstance(scope, uuid.UUID):
        return scope
    s = str(scope)
    if s in cache:
        return cache[s]
    try:
        sid = uuid.UUID(s)
    except ValueError:
        sid = session.scalar(select(Scope.id).where(Scope.tenant_id == tenant_id, Scope.name == s))
        if sid is None:
            raise ValueError(f"unknown scope {s!r}") from None
    cache[s] = sid
    return sid


def _ref(writer: GraphWriter, ref) -> uuid.UUID:
    if isinstance(ref, uuid.UUID):
        return ref
    if isinstance(ref, str):
        return uuid.UUID(ref)
    nid = writer.node_id(ref[0], ref[1])
    if nid is None:
        raise ValueError(f"unknown record {ref[0]}:{ref[1]}")
    return nid


def translate(kind: str, payload: dict[str, Any], reader: GraphReader) -> list[dict[str, Any]]:
    """Domain events -> generic operations. Every translation is explicit and reads exact values from the graph."""
    if kind == "ops":
        return list(payload.get("ops", []))
    if kind == "supplier_delay":
        sup = reader.node_by_key("supplier", payload["supplier"])
        if sup is None:
            raise ValueError(f"unknown supplier {payload['supplier']!r}")
        new_date = domain.as_date(payload["new_date"])
        ops: list[dict[str, Any]] = list(payload.get("ops", []))  # e.g. the notice document and its passage
        edges, views, _ = reader.edges([sup.id], kinds=("depends_on",), direction="in")
        for e in edges:
            o = views.get(e.src)
            if o is None or o.type != "order" or not domain.is_open_order(o.attrs):
                continue
            if payload.get("product") and str(o.attrs.get("product")) != payload["product"]:
                continue
            cur = domain.as_date(o.attrs.get("promised_date"))
            if cur is not None and cur >= new_date:
                continue
            ops.append({"op": "revise_node", "ref": ["order", o.key],
                        "attrs": {"promised_date": new_date.isoformat(), "delay_notice": payload.get("notice"),
                                  "revision": int(o.attrs.get("revision") or 1) + 1,
                                  "source_date": payload.get("notice_date", new_date.isoformat())},
                        "add_source_pointers": payload.get("source_pointers", [])})
        return ops
    if kind == "stock_count":
        return [{"op": "set_stock", **payload}]
    if kind == "task_status":
        return [{"op": "revise_node", "ref": ["task", payload["task"]], "attrs": {"status": payload["status"]}}]
    if kind == "restrict":
        return [{"op": "restrict_node", **payload}]
    raise ValueError(kind)


def apply_ops(session: Session, writer: GraphWriter, ops: list[dict[str, Any]]) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Apply operations at the writer's sequence number. Returns (deleted ids, restricted ids)."""
    scopes: dict = {}
    deleted, restricted = [], []
    for op in ops:
        kind = op["op"]
        if kind == "upsert_node":
            projects = [_ref(writer, ["project", k]) for k in op.get("project_keys", [])]
            departments = [_ref(writer, ["department", k]) for k in op.get("department_keys", [])]
            writer.upsert_node(op["type"], op["key"], name=op["name"], summary=op.get("summary", ""), attrs=op.get("attrs", {}),
                               scope_id=_scope_id(session, writer.tenant_id, op["scope"], scopes),
                               sensitivity=int(op.get("sensitivity", 1)), acl=op.get("acl"), project_ids=projects,
                               department_ids=departments, source_pointers=op.get("source_pointers", []),
                               root_sources=op.get("root_sources", []), verification=op.get("verification", "unverified"),
                               authoritative=bool(op.get("authoritative", True)), valid_from=op.get("valid_from"),
                               valid_to=op.get("valid_to"))
        elif kind == "revise_node":
            nid = _ref(writer, op["ref"])
            cur = writer.current(nid)
            changes: dict[str, Any] = {}
            if "attrs" in op:
                changes["attrs"] = op["attrs"]
            for f in ("name", "summary", "verification", "valid_from", "valid_to", "authoritative", "root_sources"):
                if f in op:
                    changes[f] = op[f]
            if op.get("add_source_pointers"):
                changes["source_pointers"] = list(cur.source_pointers or []) + [p for p in op["add_source_pointers"]
                                                                                if p not in (cur.source_pointers or [])]
            writer.revise(nid, **changes)
        elif kind == "upsert_edge":
            writer.upsert_edge(_ref(writer, op["src"]), op["kind"], _ref(writer, op["dst"]), provenance=op.get("provenance", "explicit"),
                               status=op.get("status"), attrs=op.get("attrs"), source_pointers=op.get("source_pointers"),
                               derivation=op.get("derivation"), valid_from=op.get("valid_from"), valid_to=op.get("valid_to"),
                               source_key=op.get("source_key", ""))
        elif kind == "close_edge":
            writer.close_edges(src=_ref(writer, op["src"]), dst=_ref(writer, op["dst"]), kind=op.get("kind"))
            for r in (op["src"], op["dst"]):
                writer.changed.setdefault(_ref(writer, r), []).append(f"edge:{op.get('kind')}")
        elif kind == "set_stock":
            writer.set_stock(_ref(writer, ["product", op["product"]]), _ref(writer, op["holder"]), on_hand=float(op["on_hand"]),
                             reserved=float(op.get("reserved", 0)), scope_id=_scope_id(session, writer.tenant_id, op["scope"], scopes),
                             sensitivity=int(op.get("sensitivity", 1)), source_pointers=op.get("source_pointers", []))
        elif kind == "delete_node":
            nid = _ref(writer, op["ref"])
            writer.delete_node(nid)
            deleted.append(nid)
        elif kind == "restrict_node":
            nid = _ref(writer, op["ref"])
            changes = {}
            if "scope" in op:
                changes["scope_id"] = _scope_id(session, writer.tenant_id, op["scope"], scopes)
            if "sensitivity" in op:
                changes["sensitivity"] = int(op["sensitivity"])
            if "acl" in op:
                changes["acl"] = op["acl"]
            writer.revise(nid, **changes)
            restricted.append(nid)
        else:
            raise ValueError(f"unknown operation {kind!r}")
    return deleted, restricted


# ---------------------------------------------------------------------------------------------- processing
def process_event(session: Session, event_id: uuid.UUID, *, embedder=None, policy: str = "rules",
                  limits: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply one event and evaluate its consequences. ``policy`` 'rules' (REM) or 'reachability' (baseline B)."""
    ev = session.get(RemEvent, event_id, with_for_update=True)
    if ev is None:
        raise KeyError(event_id)
    if ev.status == "done":
        return ev.summary
    ev.attempts = (ev.attempts or 0) + 1
    writer = GraphWriter(session, ev.tenant_id, embedder=embedder, event_id=ev.id)
    seq = writer.begin()
    prev = GraphReader(session, ev.tenant_id, None, seq=seq - 1)
    ops = translate(ev.kind, ev.payload, prev)
    deleted, restricted = apply_ops(session, writer, ops)
    reader = GraphReader(session, ev.tenant_id, None, seq=seq)
    budget = Budget(Limits.from_dict({"max_visited": 5000, "max_db_calls": 2000, "max_ms": 30000, **(limits or {})}))
    changed = {k: v for k, v in writer.changed.items() if k not in deleted}
    extra = [("deleted", d, (), []) for d in deleted] + [("restricted", r, (), []) for r in restricted]
    if policy == "reachability":
        affected = reachability_baseline(reader, list(changed) + deleted, budget, max_depth=budget.limits.max_depth)
        drafts = {}
        from cie.rem.rules import ImpactDraft

        for nid, hop in affected.items():
            drafts[(nid, "affected")] = ImpactDraft(nid, "affected", "reachability", f"reachable from a changed record in {hop} hops",
                                                    0.0, requires={nid})
        engine = None
        stop = budget.exceeded()
    else:
        engine = RuleEngine(reader, writer, budget)
        engine.run(changed, extra)
        drafts = engine.impacts
        stop = engine.stop
    impacts = _persist(session, ev, seq, drafts, engine)
    stale = invalidate_results(session, ev.tenant_id, list(writer.changed), restricted, seq, ev.id)
    budget.tick(reader.counter.db_calls + prev.counter.db_calls)
    ev.seq = seq
    ev.status = "done"
    ev.processed_at = datetime.now(UTC)
    ev.summary = {**(ev.summary or {}), "seq": seq, "policy": policy, "operations": len(ops),
                  "changed": {str(k): sorted(set(v)) for k, v in writer.changed.items()},
                  "deleted": [str(d) for d in deleted], "restricted": [str(r) for r in restricted],
                  "impacts": len(impacts), "suggestions": len(engine.suggestions) if engine else 0,
                  "stale_results": stale, "status": "incomplete" if stop else "complete",
                  "stopping_reason": stop or "no_more_triggers", "budget": budget.report(),
                  "rule_log": engine.log if engine else []}
    audit(session, tenant_id=ev.tenant_id, principal_id=ev.principal_id, action="rem.change", resource_kind="rem_event",
          resource_id=ev.id, details={"seq": seq, "kind": ev.kind, "impacts": len(impacts), "policy": policy})
    session.flush()
    return ev.summary


def _persist(session: Session, ev: RemEvent, seq: int, drafts: dict, engine: RuleEngine | None) -> list[RemImpact]:
    rows: list[RemImpact] = []
    for d in drafts.values():
        row = RemImpact(tenant_id=ev.tenant_id, event_id=ev.id, target_id=d.target, impact=d.impact, rule_id=d.rule_id,
                        confidence=d.confidence, reason=d.reason, paths=d.paths, evidence=d.evidence, details=d.details,
                        hypothesis=d.hypothesis, requires=sorted(d.requires, key=str), created_seq=seq, status="candidate")
        session.add(row)
        rows.append(row)
    session.flush()
    if engine is None:
        return rows
    # the supply assessment of every milestone re-evaluated here replaces earlier assessments that followed from it
    roots = engine.evaluated_roots
    if roots:
        new_by_target = {(r.target_id): r.id for r in rows}
        prior = session.scalars(select(RemImpact).where(RemImpact.tenant_id == ev.tenant_id, RemImpact.status == "candidate",
                                                        RemImpact.event_id != ev.id, RemImpact.rule_id.in_(("R1", "R2", "R3"))))
        for p in prior:
            proots = set((p.details or {}).get("roots", []))
            if proots and proots <= roots:
                p.status, p.superseded_seq, p.superseded_by = "superseded", seq, new_by_target.get(p.target_id)
    # suggested tasks: one per key, however many paths or events lead to it
    kept = set()
    for s in engine.suggestions.values():
        kept.add(s.key)
        row = session.scalar(select(RemSuggestion).where(RemSuggestion.tenant_id == ev.tenant_id, RemSuggestion.dedupe_key == s.key))
        if row is None:
            session.add(RemSuggestion(tenant_id=ev.tenant_id, dedupe_key=s.key, event_id=ev.id, title=s.title, capability=s.capability,
                                      target_ids=s.targets, reason=s.reason, priority=s.priority, status="suggested",
                                      requires=sorted(s.requires, key=str), rule_id=s.rule_id, roots=sorted(s.roots), created_seq=seq))
        elif row.status != "suggested":
            row.status, row.superseded_seq, row.event_id, row.created_seq = "suggested", None, ev.id, seq
            row.title, row.reason, row.requires, row.roots = s.title, s.reason, sorted(s.requires, key=str), sorted(s.roots)
    if roots:
        for row in session.scalars(select(RemSuggestion).where(RemSuggestion.tenant_id == ev.tenant_id, RemSuggestion.status == "suggested",
                                                               RemSuggestion.rule_id.in_(("R1", "R2", "R3")))):
            if row.dedupe_key not in kept and row.roots and set(row.roots) <= roots:
                row.status, row.superseded_seq = "superseded", seq
    session.flush()
    ev.summary = {**(ev.summary or {}), "suggestion_keys": sorted(kept)}
    return rows


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


# ---------------------------------------------------------------------------------------------- reading
def visible_impacts(session: Session, reader: GraphReader, event_id: uuid.UUID | None = None, target_ids=None,
                    include_superseded: bool = False, suggestion_keys: list[str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Impacts and suggested tasks as the reader may see them, at the reader's snapshot. An item is returned only if
    the reader may see every record it reveals (target, path, evidence); otherwise it is left out entirely, with no
    placeholder and no count, so its existence does not leak either."""
    s = reader.seq
    q = select(RemImpact).where(RemImpact.tenant_id == reader.tenant_id, RemImpact.created_seq <= s)
    if not include_superseded:
        q = q.where((RemImpact.superseded_seq.is_(None)) | (RemImpact.superseded_seq > s))
    if event_id is not None:
        q = q.where(RemImpact.event_id == event_id)
    if target_ids is not None:
        q = q.where(RemImpact.target_id.in_(list(target_ids)))
    rows = list(session.scalars(q.order_by(RemImpact.created_seq, RemImpact.rule_id)))
    reader.counter.db_calls += 1
    sq = select(RemSuggestion).where(RemSuggestion.tenant_id == reader.tenant_id, RemSuggestion.created_seq <= s,
                                     (RemSuggestion.superseded_seq.is_(None)) | (RemSuggestion.superseded_seq > s))
    if suggestion_keys is not None:
        sq = sq.where(RemSuggestion.dedupe_key.in_(suggestion_keys))
    elif event_id is not None:
        sq = sq.where(RemSuggestion.event_id == event_id)
    sugg = list(session.scalars(sq))
    reader.counter.db_calls += 1
    need = {n for r in rows for n in r.requires} | {n for x in sugg for n in x.requires}
    visible = reader.nodes(need) if need else {}
    out = []
    for r in rows:
        if not set(r.requires) <= set(visible):
            continue
        t = visible[r.target_id]
        out.append({"impact_id": str(r.id), "event_id": str(r.event_id), "target": {"id": str(t.id), "type": t.type, "key": t.key, "name": t.name},
                    "impact": r.impact, "rule": r.rule_id, "grade": r.confidence, "hypothesis": r.hypothesis, "reason": r.reason,
                    "paths": r.paths, "evidence": r.evidence, "details": r.details, "status": "candidate" if r.superseded_seq is None
                    or r.superseded_seq > s else "superseded", "superseded_by": str(r.superseded_by) if r.superseded_by else None,
                    "created_seq": r.created_seq})
    tasks = []
    for x in sorted(sugg, key=lambda x: -x.priority):
        if not set(x.requires) <= set(visible):
            continue
        tasks.append({"suggestion_id": str(x.id), "title": x.title, "capability": x.capability, "reason": x.reason,
                      "priority": x.priority, "targets": [str(t) for t in x.target_ids], "rule": x.rule_id,
                      "dedupe_key": x.dedupe_key, "event_id": str(x.event_id) if x.event_id else None})
    return out, tasks
