"""The context builder.

Permissions come first: every channel reads through the requester's visibility (scope, clearance and access list,
in SQL), so nothing the requester may not see is loaded, counted or summarised. The channels:

1. **structured**: entity views of the records named in the request (current values with their sources,
   dependencies, unresolved conflicts, possible identity matches);
2. **traversal**: typed traversal of the live state from the question (``cie.rem.query``, policy ``traversal``),
   with relationship paths, confirmed facts versus hypotheses, contradictions and missing evidence;
3. **keyword and semantic**: hybrid search over knowledge memory (``cie.retrieval``), whose items cite the
   original source (document, page, quote);
4. **original sources**: the documents those citations point to.

Each channel gets a share of the token budget, which comes from the model's context window. When it does not fit,
the context says so (``complete: false``) and returns a cursor that continues where it stopped. Live-state records
placed in a task's context are recorded as the task's inputs with their versions, so a later change to them
reopens or flags the task.

**Exhaustive mode** answers questions about a whole collection ("which open orders of project A arrive after
October 15?"). It scans every record of the collection the requester may see, in id order at one snapshot, applies
a deterministic check (``cie.context.checks``) and records coverage: records visible, scanned, matched and
unreadable, and whether the scan was complete. Records the requester may not see are neither scanned nor counted.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from cie.context import checks
from cie.context.models import ContextRun
from cie.core.models import EvidencePacket, Principal, Task
from cie.core.util import estimate_tokens
from cie.governance.permissions import visible_scopes
from cie.state.models import RemNode, RemNodeVersion
from cie.state.store import GraphReader, _at

# the share of a model's context window given to evidence; the rest is for instructions, reasoning and the answer
CONTEXT_SHARE = 0.25
MODEL_WINDOWS = {"claude": 200_000, "gpt-4o": 128_000, "gpt-4.1": 1_000_000, "llama3.1": 128_000, "llama3": 8_192, "qwen2.5": 32_768,
                 "mistral": 32_768, "extractive": 32_000}
SHARES = {"structured": 0.3, "traversal": 0.3, "retrieval": 0.4}
MAX_LISTED = 200  # exhaustive mode: records listed per page (the scan itself is never truncated)


def budget_for_model(model: str | None, default: int = 8000) -> int:
    if not model:
        return default
    m = model.lower()
    window = next((w for k, w in sorted(MODEL_WINDOWS.items(), key=lambda kv: -len(kv[0])) if k in m), None)
    return int(min(60_000, window * CONTEXT_SHARE)) if window else default


@dataclass
class ContextRequest:
    question: str = ""
    task_id: uuid.UUID | None = None
    entities: list[Any] = field(default_factory=list)  # [type, key], ids or {"type", "scheme", "value"}
    project_keys: list[str] = field(default_factory=list)
    scope_id: uuid.UUID | None = None  # knowledge-memory scope for search; defaults to the task's
    mode: str = "focused"  # focused | exhaustive
    collection: dict[str, Any] | None = None  # exhaustive: {"type": "order", "project_key": "p1"}
    check: dict[str, Any] | None = None  # exhaustive: see cie.context.checks
    budget_tokens: int | None = None
    model: str | None = None
    cursor: str | None = None
    channels: tuple[str, ...] = ("structured", "traversal", "retrieval")


@dataclass
class Context:
    data: dict[str, Any]
    packet: EvidencePacket | None = None  # the knowledge-memory packet, for strategies that take one
    run_id: uuid.UUID | None = None


def _cursor_in(c: str | None) -> dict[str, Any]:
    if not c:
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(c.encode()).decode())
    except (ValueError, json.JSONDecodeError):
        raise ValueError("invalid cursor") from None


def _cursor_out(d: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(d, sort_keys=True).encode()).decode()


def _tokens(obj: Any) -> int:
    return estimate_tokens(json.dumps(obj, default=str))


def _take(items: list[Any], start: int, budget: int) -> tuple[list[Any], int, int]:
    """Items from ``start`` that fit ``budget`` (at least one, so progress is always made). Returns (items, next, used)."""
    out, used, i = [], 0, start
    while i < len(items):
        t = _tokens(items[i])
        if out and used + t > budget:
            break
        out.append(items[i])
        used += t
        i += 1
    return out, i, used


def build_context(session: Session, tenant_id: uuid.UUID, principal: Principal, req: ContextRequest, *, embedder=None,
                  settings=None, record: bool = True) -> Context:
    if req.mode == "exhaustive":
        return exhaustive(session, tenant_id, principal, req, record=record)
    t0 = time.perf_counter()
    vis = visible_scopes(session, principal)
    cur = _cursor_in(req.cursor)
    reader = GraphReader(session, tenant_id, vis, seq=cur.get("seq"))
    task = session.get(Task, req.task_id) if req.task_id else None
    if task is not None and task.tenant_id != tenant_id:
        raise PermissionError("unknown task")
    budget = int(req.budget_tokens or budget_for_model(req.model))
    question = req.question or (task.title + ". " + (task.brief or "") if task else "")
    data: dict[str, Any] = {"question": question, "snapshot_seq": reader.seq, "budget_tokens": budget, "sources": {}}
    if task is not None:
        data["task"] = {"id": str(task.id), "title": task.title, "brief": task.brief, "type": task.task_type, "status": task.status.value,
                        "acceptance": task.acceptance, "limits": task.limits,
                        "deadline_at": task.deadline_at.isoformat() if task.deadline_at else None, "revision": task.revision}
    used_total, nxt, complete = _tokens(data), {"seq": reader.seq}, True
    live: dict[uuid.UUID, tuple[int, str]] = {}
    spare = 0

    # 1. structured: the records the request names
    if "structured" in req.channels:
        from cie.state.domain_events import _view
        from cie.state.views import view_of

        views = []
        for ref in req.entities:
            try:
                n = _view(reader, ref)
            except (ValueError, KeyError):
                n = None
            if n is not None:
                views.append(view_of(session, reader, n))
        share = int(budget * SHARES["structured"])
        got, i, used = _take(views, cur.get("structured", 0), share)
        data["entities"] = got
        data["sources"]["structured"] = {"requested": len(req.entities), "visible": len(views), "returned": len(got)}
        for v in got:
            live[uuid.UUID(v["id"])] = (v["version"], v["entity_id"])
        if i < len(views):
            complete, nxt["structured"] = False, i
        spare = max(0, share - used)
        used_total += used

    # 2. traversal of the live state
    if "traversal" in req.channels and question:
        from cie.rem.query import QueryRequest, run_query

        share = int(budget * SHARES["traversal"]) + spare
        out = run_query(session, tenant_id, vis, QueryRequest(question=question, policy="traversal", project_keys=req.project_keys,
                                                              snapshot_seq=reader.seq, limits={"max_tokens": max(200, share)}, save=False),
                        embedder=embedder, principal_id=principal.id)
        ev = out.get("evidence", [])
        got, i, used = _take(ev, cur.get("traversal", 0), share)
        data["state_evidence"] = got
        data["facts"], data["hypotheses"] = out.get("facts", [])[:40], out.get("hypotheses", [])[:40]
        data["contradictions"], data["missing_evidence"] = out.get("contradictions", [])[:20], out.get("missing_evidence", [])[:20]
        data["sources"]["traversal"] = {"visited": len(out.get("entities", [])), "evidence": len(ev), "returned": len(got),
                                        "stopping_reason": out.get("stopping_reason"), "status": out.get("status")}
        for e in got:
            live[uuid.UUID(e["node"]["id"])] = (e["node"]["version"], f"{e['node']['type']}:{e['node']['key']}")
        if i < len(ev) or out.get("status") == "incomplete":
            complete, nxt["traversal"] = False, i
        spare = max(0, share - used)
        used_total += used

    # 3. keyword and semantic search over knowledge memory, citing original sources
    packet = None
    scope_id = req.scope_id or (task.scope_id if task is not None else None)
    if "retrieval" in req.channels and question:
        if scope_id is None:
            data["sources"]["retrieval"] = {"skipped": "no knowledge-memory scope given"}
        else:
            from cie.retrieval.pipeline import Retriever

            share = int(budget * SHARES["retrieval"]) + spare
            try:
                res = Retriever(session, settings, embedder=embedder).retrieve(question, principal, scope_id, max_records=60,
                                                                               token_budget=share)
                packet = res.packet
            except PermissionError:
                data["sources"]["retrieval"] = {"skipped": "no access to the scope"}
            if packet is not None:
                items = list(packet.items or [])
                got, i, used = _take(items, cur.get("retrieval", 0), share)
                data["memory_evidence"] = got
                data["sources"]["retrieval"] = {"packet_id": str(packet.id), "items": len(items), "returned": len(got)}
                if i < len(items):
                    complete, nxt["retrieval"] = False, i
                used_total += used
                docs = {}
                for it in got:
                    for c in it.get("citations") or []:
                        d = it.get("document_id")
                        if d:
                            docs.setdefault(d, set()).add(c.get("page_no"))
                data["original_sources"] = [{"document_id": d, "pages": sorted(p for p in pages if p is not None)} for d, pages in docs.items()]

    unresolved = [dict(u, entity_id=v["entity_id"]) for v in data.get("entities", []) for u in v.get("unresolved", [])]
    data["unresolved"] = unresolved
    data["complete"] = complete
    data["cursor"] = None if complete else _cursor_out(nxt)
    data["token_estimate"] = used_total
    data["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if task is not None and live:
        from cie.workflow import engine

        engine.record_inputs(session, task, records=live)
    data["inputs_recorded"] = len(live) if task is not None else 0
    run = _record(session, tenant_id, principal, req, data, {}, complete, reader.seq, used_total) if record else None
    if run is not None:
        data["context_run_id"] = str(run.id)
    return Context(data=data, packet=packet, run_id=run.id if run else None)


def _record(session: Session, tenant_id: uuid.UUID, principal: Principal, req: ContextRequest, data: dict, coverage: dict,
            complete: bool, seq: int, tokens: int) -> ContextRun:
    run = ContextRun(tenant_id=tenant_id, task_id=req.task_id, principal_id=principal.id, mode=req.mode,
                     request={"question": req.question, "entities": req.entities, "project_keys": req.project_keys, "collection": req.collection,
                              "check": req.check, "budget_tokens": req.budget_tokens, "model": req.model, "cursor": bool(req.cursor)},
                     sources=data.get("sources", {}), coverage=coverage, complete=complete, snapshot_seq=seq, token_estimate=tokens)
    session.add(run)
    session.flush()
    return run


# ---------------------------------------------------------------------------------------------- exhaustive
def exhaustive(session: Session, tenant_id: uuid.UUID, principal: Principal, req: ContextRequest, *, record: bool = True,
               batch: int = 500) -> Context:
    coll = dict(req.collection or {})
    if not coll.get("type"):
        raise ValueError("exhaustive mode needs a collection with a record type")
    check = req.check or {"field": "type", "op": "eq", "value": coll["type"]}
    checks.validate(check)
    vis = visible_scopes(session, principal)
    cur = _cursor_in(req.cursor)
    reader = GraphReader(session, tenant_id, vis, seq=cur.get("seq"))
    t0 = time.perf_counter()
    base = (select(RemNodeVersion, RemNode).join(RemNode, RemNode.id == RemNodeVersion.node_id)
            .where(RemNodeVersion.tenant_id == tenant_id, RemNode.type == coll["type"], _at(RemNodeVersion, reader.seq)))
    vf = reader._visible_filter()
    if vf is not None:
        base = base.where(vf)  # records the requester may not see are neither scanned nor counted
    if coll.get("project_key"):
        pid = session.scalar(select(RemNode.id).where(RemNode.tenant_id == tenant_id, RemNode.type == "project", RemNode.key == coll["project_key"]))
        base = base.where(RemNodeVersion.project_ids.any(pid)) if pid is not None else base.where(false())
    visible = session.scalar(select(func.count()).select_from(base.with_only_columns(RemNodeVersion.id).subquery())) or 0
    scanned = matched = unreadable = hidden_since = 0
    matches, unread = [], []
    after = None
    while True:
        q = base.order_by(RemNode.id).limit(batch)
        if after is not None:
            q = q.where(RemNode.id > after)
        rows = session.execute(q).all()
        if not rows:
            break
        # reading an earlier snapshot: a record restricted since then is left out, as it would be now
        allowed = reader._still_visible([nv.node_id for nv, _ in rows]) if reader.historical else None
        for nv, node in rows:
            if allowed is not None and nv.node_id not in allowed:
                hidden_since += 1
                continue
            v = GraphReader._view(nv, node)
            scanned += 1
            try:
                ok = checks.evaluate(check, v)
            except checks.Unreadable as e:
                unreadable += 1
                unread.append({"id": str(v.id), "entity_id": f"{v.type}:{v.key}", "name": v.name, "version": v.version, "reason": str(e)})
                continue
            if ok:
                matched += 1
                matches.append({"id": str(v.id), "entity_id": f"{v.type}:{v.key}", "name": v.name, "version": v.version,
                                "attrs": {k: x for k, x in (v.attrs or {}).items() if k not in ("verified_by",)}})
        after = rows[-1][1].id
    visible -= hidden_since  # never counted, like any record the requester may not see
    start = int(cur.get("listed", 0))
    page = matches[start:start + MAX_LISTED]
    more = start + MAX_LISTED < len(matches)
    coverage = {"collection": coll, "check": check, "snapshot_seq": reader.seq, "visible_records": visible, "scanned": scanned,
                "matched": matched, "unreadable": unreadable, "complete": scanned == visible,
                "note": "counts cover only records the requester may see"}
    data = {"mode": "exhaustive", "coverage": coverage, "matches": page, "unreadable_records": unread[:MAX_LISTED],
            "listed": {"from": start, "count": len(page), "more": more},
            "cursor": _cursor_out({"seq": reader.seq, "listed": start + MAX_LISTED}) if more else None,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "sources": {"exhaustive": {"scanned": scanned}}}
    task = session.get(Task, req.task_id) if req.task_id else None
    if task is not None and task.tenant_id == tenant_id:
        from cie.workflow import engine

        engine.record_inputs(session, task, records={uuid.UUID(m["id"]): (m["version"], m["entity_id"]) for m in page})
        progress = dict(task.progress or {})
        progress["coverage"] = list(progress.get("coverage", []))[-9:] + [coverage]
        task.progress = progress
    run = _record(session, tenant_id, principal, req, data, coverage, coverage["complete"], reader.seq, _tokens(page)) if record else None
    if run is not None:
        data["context_run_id"] = str(run.id)
    return Context(data=data, run_id=run.id if run else None)
