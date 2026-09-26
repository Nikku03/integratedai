"""Query mode: question + identity + project scope + time scope -> an evidence packet within a token budget.

1. Read at one snapshot (the tenant's change sequence number), so the answer can be reproduced later.
2. Start from permission-filtered search (keyword and semantic) over the graph's records and source passages,
   or from start hits supplied by the caller (for example the engine's hybrid document search).
3. Explore relationships within the horizon limits (``cie.rem.explore``), under the requested policy.
4. Return entities, candidate affected projects and tasks, current assessments from change mode, evidence
   passages with exact source pointers, relationship paths, confirmed facts versus hypotheses, contradictions
   with their chronology, missing evidence, and suggested next tasks with the capability they need.

Questions that ask for company-wide aggregates (counts, totals) are not answered by traversal: they are routed to
a database aggregate over the permission-filtered records.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cie.governance.permissions import Visibility
from cie.rem import domain
from cie.rem import priority as pr
from cie.rem.budget import Budget, Limits, est_tokens
from cie.rem.change import visible_impacts
from cie.rem.explore import Exploration, Explorer, pack_evidence
from cie.rem.models import RemNode, RemNodeVersion, RemResult, RemResultDep, RemSuggestion
from cie.rem.store import GraphReader, NodeView, _at

STATEMENT_TYPES = ("fact", "claim", "order", "milestone", "task", "requirement", "contract", "decision", "risk", "invoice",
                   "artifact")
AGGREGATE = re.compile(r"\b(how many|number of|count of|total (?:number|value|amount)|sum of|average|in total)\b", re.I)


@dataclass
class QueryRequest:
    question: str
    policy: str = "rem"
    project_keys: list[str] = field(default_factory=list)
    as_of: datetime | None = None
    snapshot_seq: int | None = None
    limits: dict[str, Any] = field(default_factory=dict)
    weights: dict[str, Any] = field(default_factory=dict)
    start_k: int = 12
    targeted_searches: list[str] = field(default_factory=list)
    resume_from: uuid.UUID | None = None
    start_hits: list[tuple[uuid.UUID, float]] | None = None  # caller-supplied start set (e.g. hybrid document search)
    save: bool = True


def _node_ref(n: NodeView) -> dict[str, Any]:
    return {"id": str(n.id), "type": n.type, "key": n.key, "name": n.name, "version": n.version}


def _statement(n: NodeView) -> str:
    a = n.attrs
    if n.type == "order":
        return f"{n.name}: {a.get('qty')} x {a.get('product')} from {a.get('supplier')}, promised {a.get('promised_date')} (status {a.get('status', 'open')}, rev {a.get('revision', 1)})"
    if n.type == "milestone":
        return f"{n.name}: due {a.get('due_date')}" + (f" (+{a.get('slack_days')} days slack)" if a.get("slack_days") else "")
    if n.type == "claim":
        return f"{n.name}: states {a.get('attr')} = {a.get('value')} for {a.get('subject_key')} (stated {a.get('stated_on')})"
    if n.type == "task":
        return f"{n.name}: status {a.get('status', 'open')}"
    return f"{n.name}. {n.summary}".strip()


def run_query(session: Session, tenant_id: uuid.UUID, visibility: Visibility | None, req: QueryRequest, *, embedder,
              principal_id: uuid.UUID | None = None) -> dict[str, Any]:
    parent = session.get(RemResult, req.resume_from) if req.resume_from else None
    if parent is not None and (parent.tenant_id != tenant_id or parent.principal_id != principal_id):
        raise PermissionError("a result can only be resumed by the principal that created it")
    seq = parent.snapshot_seq if parent is not None else req.snapshot_seq
    reader = GraphReader(session, tenant_id, visibility, seq=seq)
    budget = Budget(Limits.from_dict(req.limits))
    weights = pr.Weights.from_dict(req.weights)
    result_id = uuid.uuid4()
    base = {"result_id": str(result_id), "mode": "query", "policy": req.policy, "question": req.question,
            "snapshot_seq": reader.seq, "as_of": req.as_of.isoformat() if req.as_of else None,
            "resumed_from": str(parent.id) if parent else None}

    if AGGREGATE.search(req.question) and parent is None:
        out = {**base, **_aggregate(reader, req.question), "budget": None}
        budget.tick(reader.counter.db_calls)
        out["budget"] = budget.report()
        if req.save:
            _save(session, tenant_id, principal_id, req, out, {}, {}, [], reader.seq, result_id, parent)
        return out

    qvec = embedder.embed([req.question])[0] if embedder is not None else None
    budget.usage.model_calls = 0  # embeddings only; no generative model is called in query mode
    scope_projects = set()
    for k in req.project_keys:
        p = reader.node_by_key("project", k)
        if p is not None:
            scope_projects.add(p.id)
    hits = _start_hits(reader, req, qvec)
    explorer = Explorer(reader, policy=req.policy, budget=budget, weights=weights, qvec=qvec, as_of=req.as_of,
                        scope_projects=scope_projects)
    if parent is not None:
        explorer.resume(parent.state or {})
    explorer.start(hits)
    exp = explorer.run()
    visits = sorted(exp.visits.values(), key=lambda v: (-v.score, v.order) if req.policy.startswith("rem")
                    else ((v.hop, v.order) if req.policy == "traversal" else (-v.qrel, v.order)))
    chosen, used, cut = pack_evidence(visits, req.policy, budget.limits.max_tokens, weights, req.as_of)
    budget.usage.tokens = used
    out = {**base, **_assemble(session, reader, exp, visits, chosen, cut, req)}
    budget.tick(reader.counter.db_calls)
    status, reason = exp.status, exp.stopping_reason
    if cut and status == "complete":
        status, reason = "incomplete", "budget:max_tokens"
    out.update({"status": status, "stopping_reason": reason, "budget": budget.report()})
    if req.save:
        _save(session, tenant_id, principal_id, req, out, {"exploration": exp.trace, "evidence_selection": [
            {"node": str(v.node.id), "score": v.score, "components": v.comps.as_dict() if v.comps else None} for v in chosen]},
            explorer.state(), [(v.node.id, v.node.version) for v in visits], reader.seq, result_id, parent)
    return out


def _start_hits(reader: GraphReader, req: QueryRequest, qvec) -> list[tuple[NodeView, float, str]]:
    found: dict[uuid.UUID, tuple[float, str]] = {}
    if req.start_hits is not None:
        for nid, sc in req.start_hits:
            found[nid] = (float(sc), "search")
    else:
        for nid, sc, how in reader.search(req.question, qvec, k=req.start_k):
            found[nid] = (sc, how)
    for q in req.targeted_searches:
        for nid, sc, _how in reader.search(q, None, k=max(3, req.start_k // 2)):
            if nid not in found:
                found[nid] = (sc, "targeted_search")
    views = reader.nodes(found, with_embedding=True)  # the permission filter applies to caller-supplied hits too
    return [(views[n], sc, how) for n, (sc, how) in found.items() if n in views]


def _aggregate(reader: GraphReader, question: str) -> dict[str, Any]:
    words = " or ".join(re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", question)) or question
    tq = func.websearch_to_tsquery("english", words)
    stmt = (select(RemNode.type, func.count()).join(RemNodeVersion, RemNodeVersion.node_id == RemNode.id)
            .where(RemNodeVersion.tenant_id == reader.tenant_id, _at(RemNodeVersion, reader.seq), RemNodeVersion.tsv.op("@@")(tq))
            .group_by(RemNode.type))
    if reader.vis is not None:
        stmt = stmt.where(reader.vis.sql_filter(RemNodeVersion.scope_id, RemNodeVersion.sensitivity))
    counts = {t: int(c) for t, c in reader._run(stmt, label="aggregate")}
    return {"status": "routed", "stopping_reason": "aggregate_routed_to_database",
            "aggregate": {"matching_records_by_type": counts,
                          "note": "Counted in the database over records you may see; not computed by graph traversal."},
            "entities": [], "evidence": [], "facts": [], "hypotheses": [], "contradictions": [], "missing_evidence": [],
            "suggested_tasks": [], "candidate_affected": {"projects": [], "tasks": []}, "assessments": []}


# ---------------------------------------------------------------------------------------------- assembly
def _assemble(session: Session, reader: GraphReader, exp: Exploration, visits, chosen, cut: bool, req: QueryRequest) -> dict[str, Any]:
    by_id = {v.node.id: v for v in visits}
    edges = exp.edges
    supports: dict[uuid.UUID, list[uuid.UUID]] = {}
    superseded: dict[uuid.UUID, uuid.UUID] = {}
    for e in edges.values():
        if e.kind == "supports":
            supports.setdefault(e.dst, []).append(e.src)
        elif e.kind == "derived_from" and e.src in by_id and by_id[e.src].node.type == "passage":
            supports.setdefault(e.dst, []).append(e.src)  # the passage a record's text comes from
        elif e.kind == "supersedes":
            superseded[e.dst] = e.src

    entities = [{**_node_ref(v.node), "horizon": v.hop, "via": v.via, "score": v.score, "priority": v.comps.as_dict() if v.comps else None,
                 "cross_boundary": v.cross_boundary, "authoritative": v.node.authoritative, "verification": v.node.verification,
                 "review_status": v.node.review_status, "paths": v.paths, "requires": [str(v.node.id)] + _path_ids(v.paths)}
                for v in visits[:80]]

    evidence = []
    for v in chosen:
        n = v.node
        evidence.append({"evidence_id": f"{n.id}@{n.version}", "node": _node_ref(n), "text": n.text(),
                         "source_pointers": n.source_pointers, "authoritative": n.authoritative,
                         "root_sources": n.root_sources, "reliability": round(pr.reliability(n), 3), "horizon": v.hop,
                         "path": v.path, "tokens": est_tokens(n.text()), "priority": v.comps.as_dict() if v.comps else None,
                         "requires": [str(n.id)] + _path_ids([v.path])})
    ev_ids = {v.node.id for v in chosen}

    facts, hypotheses = [], []
    for v in visits:
        n = v.node
        if n.type not in STATEMENT_TYPES:
            continue
        sup = [s for s in supports.get(n.id, []) if s in by_id]
        roots = set(n.root_sources)
        for s in sup:
            roots |= set(by_id[s].node.root_sources)
        item = {"node": _node_ref(n), "statement": _statement(n), "evidence_ids": [f"{s}@{by_id[s].node.version}" for s in sup if s in ev_ids],
                "source_pointers": n.source_pointers, "independent_sources": len(roots), "requires": [str(n.id)] + [str(s) for s in sup]}
        hyp_edges = [s for s in v.path if s.get("hypothesis")]
        if not n.authoritative:
            hypotheses.append({**item, "kind": "generated_summary", "note": "generated content: not evidence; check its sources",
                               "review_status": n.review_status})
        elif n.id in superseded:
            continue  # reported under contradictions with its chronology
        elif n.type == "claim" and n.verification != "verified":
            hypotheses.append({**item, "kind": "unverified_claim"})
        elif hyp_edges:
            hypotheses.append({**item, "kind": "reached_through_inferred_relationship", "edges": hyp_edges})
        elif n.source_pointers or sup:
            facts.append(item)
    for e in edges.values():
        if e.hypothesis and e.src in by_id and e.dst in by_id:
            hypotheses.append({"kind": "inferred_relationship", "edge": {"id": str(e.id), "kind": e.kind, "from": _node_ref(by_id[e.src].node),
                               "to": _node_ref(by_id[e.dst].node), "derivation": e.derivation},
                               "requires": [str(e.src), str(e.dst)]})

    contradictions = []
    for e in edges.values():
        if e.kind != "contradicts" or e.src not in by_id or e.dst not in by_id:
            continue
        a, b = by_id[e.src].node, by_id[e.dst].node
        if superseded.get(a.id) == b.id or superseded.get(b.id) == a.id:
            cur, old = (b, a) if superseded.get(a.id) == b.id else (a, b)
            res = {"status": "resolved", "current": _node_ref(cur), "history": _node_ref(old),
                   "why": f"{cur.name} (dated {cur.attrs.get('source_date') or cur.attrs.get('stated_on')}) is the later system-of-record statement; "
                          f"{old.name} (dated {old.attrs.get('source_date') or old.attrs.get('stated_on')}) is kept as history, not deleted."}
        else:
            order = domain.later_record(a.attrs, a.authoritative, b.attrs, b.authoritative)
            if order:
                cur, old = (a, b) if order > 0 else (b, a)
                res = {"status": "resolved", "current": _node_ref(cur), "history": _node_ref(old),
                       "why": f"{cur.name} is the later authoritative statement; {old.name} is kept as history."}
            else:
                res = {"status": "unresolved", "why": "neither statement is a later system-of-record statement"}
        contradictions.append({"edge_id": str(e.id), "a": _node_ref(a), "b": _node_ref(b), "derivation": e.derivation,
                               "provenance": e.provenance, **res, "requires": [str(a.id), str(b.id)]})

    missing = []
    for v in visits:
        n = v.node
        if n.type in STATEMENT_TYPES and n.authoritative and not n.source_pointers and not supports.get(n.id):
            missing.append({"about": _node_ref(n), "what": "no source passage or system-of-record pointer",
                            "suggested_search": n.name, "requires": [str(n.id)]})
    for c in contradictions:
        if c["status"] == "unresolved":
            missing.append({"about": c["a"], "what": f"conflict with {c['b']['name']} has no later authoritative statement",
                            "suggested_search": f"{c['a']['name']} {c['b']['name']}", "requires": c["requires"]})
    for h in hypotheses:
        if h["kind"] == "inferred_relationship":
            missing.append({"about": h["edge"]["from"], "what": f"inferred relationship {h['edge']['kind']} -> {h['edge']['to']['name']} is unverified",
                            "suggested_search": f"{h['edge']['from']['name']} {h['edge']['to']['name']}", "requires": h["requires"]})
    if exp.frontier:
        missing.append({"about": None, "what": f"{len(exp.frontier)} records at the exploration frontier were not expanded "
                        f"({exp.stopping_reason}); resume this result to continue", "suggested_search": None, "requires": []})
    if exp.truncated:
        missing.append({"about": None, "what": f"{len(exp.truncated)} records had more relationships than the per-record cap",
                        "suggested_search": None, "requires": [str(x) for x in exp.truncated]})
    if cut:
        missing.append({"about": None, "what": "some evidence was left out by the token budget", "suggested_search": None, "requires": []})

    # candidate affected projects and tasks among the explored records (membership included)
    proj_ids = {v.node.id for v in visits if v.node.type == "project"}
    for v in visits:
        proj_ids |= set(v.node.project_ids)
    projects = reader.nodes(proj_ids - set(by_id)) if proj_ids - set(by_id) else {}
    projects.update({i: by_id[i].node for i in proj_ids if i in by_id})
    target_ids = set(by_id) | set(projects)
    assessments, stored_tasks = visible_impacts(session, reader, target_ids=target_ids)
    assessed = {(a["target"]["id"]): a for a in assessments}
    cand_projects = [{**_node_ref(p), "assessment": assessed.get(str(p.id), {}).get("impact"),
                      "reason": assessed.get(str(p.id), {}).get("reason"),
                      "paths": by_id[p.id].paths if p.id in by_id else [], "requires": [str(p.id)]} for p in projects.values()]
    cand_tasks = [{**_node_ref(v.node), "status": v.node.attrs.get("status", "open"), "assessment": assessed.get(str(v.node.id), {}).get("impact"),
                   "paths": v.paths, "requires": [str(v.node.id)] + _path_ids(v.paths)} for v in visits if v.node.type == "task"]
    rel_targets = {str(i) for i in target_ids}
    tasks, seen = [], set()
    for t in [t for t in stored_tasks if set(t["targets"]) & rel_targets] + _query_tasks(hypotheses, contradictions, missing):
        if t["dedupe_key"] not in seen:  # one task per key, however many paths or earlier results proposed it
            seen.add(t["dedupe_key"])
            tasks.append(t)
    return {"entities": entities, "candidate_affected": {"projects": cand_projects, "tasks": cand_tasks},
            "assessments": [a for a in assessments], "evidence": evidence, "facts": facts, "hypotheses": hypotheses,
            "contradictions": contradictions, "missing_evidence": missing, "suggested_tasks": tasks,
            "routing": {"shortcuts_followed": exp.routing_hops,
                        "note": "routing shortcuts are navigation only; they are not relationships, evidence or access"}}


def _path_ids(paths) -> list[str]:
    out = []
    for p in paths:
        for s in p:
            for k in ("from", "to"):
                if s.get(k) and s[k] not in out:
                    out.append(s[k])
    return out


def _query_tasks(hypotheses, contradictions, missing) -> list[dict[str, Any]]:
    tasks = []
    for h in hypotheses:
        if h["kind"] == "inferred_relationship":
            f = h["edge"]["from"]
            tasks.append({"title": f"Verify that {f['name']} {h['edge']['kind'].replace('_', ' ')} {h['edge']['to']['name']}",
                          "capability": domain.capability_for(f["type"]), "reason": "inferred relationship used in this result",
                          "priority": 0.6, "targets": [f["id"], h["edge"]["to"]["id"]], "rule": "query:verify_inferred",
                          "dedupe_key": f"Q:verify:{h['edge']['id']}", "requires": h["requires"]})
    for c in contradictions:
        if c["status"] == "unresolved":
            tasks.append({"title": f"Resolve the conflict between {c['a']['name']} and {c['b']['name']}",
                          "capability": domain.capability_for(c["b"]["type"]), "reason": "conflicting statements, no later authoritative source",
                          "priority": 0.7, "targets": [c["a"]["id"], c["b"]["id"]], "rule": "query:resolve_conflict",
                          "dedupe_key": f"Q:conflict:{c['edge_id']}", "requires": c["requires"]})
    for m in missing:
        if m["about"] and m["what"].startswith("no source"):
            tasks.append({"title": f"Find the source for {m['about']['name']}", "capability": "research",
                          "reason": m["what"], "priority": 0.4, "targets": [m["about"]["id"]], "rule": "query:find_source",
                          "dedupe_key": f"Q:source:{m['about']['id']}", "requires": m["requires"]})
    return tasks


def _save(session, tenant_id, principal_id, req: QueryRequest, out, trace, state, deps, seq, result_id, parent) -> None:
    request = {"question": req.question, "policy": req.policy, "project_keys": req.project_keys,
               "as_of": req.as_of.isoformat() if req.as_of else None, "limits": req.limits, "weights": req.weights,
               "targeted_searches": req.targeted_searches, "start_k": req.start_k}
    row = RemResult(id=result_id, tenant_id=tenant_id, principal_id=principal_id, mode="query", policy=req.policy, snapshot_seq=seq,
                    request=request, output=out, trace=trace, state=state, status=out.get("status", "complete"),
                    stopping_reason=out.get("stopping_reason", ""), parent_id=parent.id if parent else None)
    session.add(row)
    session.flush()
    for nid, ver in dict(deps).items():
        session.add(RemResultDep(result_id=result_id, node_id=nid, version=ver))
    for t in out.get("suggested_tasks", []):
        if t.get("rule", "").startswith("query:"):
            exists = session.scalar(select(RemSuggestion.id).where(RemSuggestion.tenant_id == tenant_id,
                                                                   RemSuggestion.dedupe_key == t["dedupe_key"]))
            if exists is None:
                session.add(RemSuggestion(tenant_id=tenant_id, dedupe_key=t["dedupe_key"], result_id=result_id, title=t["title"],
                                          capability=t["capability"], target_ids=[uuid.UUID(x) for x in t["targets"]],
                                          reason=t["reason"], priority=t["priority"], status="suggested",
                                          requires=[uuid.UUID(x) for x in t["requires"]], rule_id=t["rule"], roots=[],
                                          created_seq=seq))
    session.flush()


def redact(output: dict[str, Any], visible: set[str]) -> dict[str, Any]:
    """Re-apply the permission filter to a stored output: drop every item that reveals a record not in ``visible``."""
    def ok(item) -> bool:
        return not isinstance(item, dict) or all(r in visible for r in item.get("requires", []))

    out = dict(output)
    for k in ("entities", "evidence", "facts", "hypotheses", "contradictions", "missing_evidence", "suggested_tasks", "assessments"):
        if isinstance(out.get(k), list):
            out[k] = [x for x in out[k] if ok(x) and (k != "assessments" or _impact_ok(x, visible))]
    ca = out.get("candidate_affected")
    if isinstance(ca, dict):
        out["candidate_affected"] = {k: [x for x in v if ok(x)] for k, v in ca.items()}
    return out


def _impact_ok(a: dict[str, Any], visible: set[str]) -> bool:
    ids = {a["target"]["id"]}
    for p in a.get("paths", []):
        for s in p:
            ids |= {s.get("from"), s.get("to")} - {None}
    for e in a.get("evidence", []):
        if e.get("node_id"):
            ids.add(e["node_id"])
        ids |= set(e.get("requires", []))
    return ids <= visible


def requires_of(output: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for k in ("entities", "evidence", "facts", "hypotheses", "contradictions", "missing_evidence", "suggested_tasks"):
        for x in output.get(k, []) or []:
            ids |= set(x.get("requires", []))
    for x in (output.get("candidate_affected") or {}).values():
        for y in x:
            ids |= set(y.get("requires", []))
    for a in output.get("assessments", []) or []:
        ids.add(a["target"]["id"])
        for p in a.get("paths", []):
            for s in p:
                ids |= {s.get("from"), s.get("to")} - {None}
        for e in a.get("evidence", []):
            if e.get("node_id"):
                ids.add(e["node_id"])
            ids |= set(e.get("requires", []))
    return ids
