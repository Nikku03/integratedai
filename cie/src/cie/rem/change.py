"""REM change analysis: after the live state applies an event, rules find the records it may affect.

The live state (``cie.state.events``) owns the event: idempotency, the sequence number, version checks, the
operations, access propagation and stale marks. This module adds the optional analysis on top: change rules R0-R8
(or plain reachability, baseline B) produce candidate impacts and suggested verification tasks. Impacts are
candidates for people and agents to check; they never change identity, permissions or task status.

``process_event`` here is the state processor with the REM analysis attached; the state functions are re-exported
so existing callers keep working.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.rem.budget import Budget, Limits
from cie.rem.rules import RuleEngine, reachability_baseline
from cie.state import events as _events
from cie.state.consistency import invalidate_results  # noqa: F401
from cie.state.events import (  # noqa: F401
    EVENT_KINDS,
    AnalysisWriter,
    ChangeSet,
    IdempotencyConflict,
    StaleWrite,
    Unauthorized,
    apply_ops,
    authorize_ops,
    submit_event,
    translate,
)
from cie.state.models import RemEvent, RemImpact, RemSuggestion
from cie.state.store import GraphReader

POLICIES = ("rules", "reachability", "none")


def rem_analysis(policy: str = "rules"):
    """The analysis hook for ``cie.state.events.process_event``: 'rules' (REM) or 'reachability' (baseline B)."""
    if policy not in ("rules", "reachability"):
        raise ValueError(f"policy must be one of {POLICIES}")

    def run(session: Session, cs: ChangeSet, writer: AnalysisWriter, limits: dict[str, Any]) -> dict[str, Any]:
        t = time.perf_counter()
        ev, seq = cs.event, cs.seq
        reader = GraphReader(session, ev.tenant_id, None, seq=seq)
        budget = Budget(Limits.from_dict({"max_visited": 5000, "max_db_calls": 2000, "max_ms": 30000, **(limits or {})}))
        extra = [("deleted", d, (), []) for d in cs.deleted] + [("restricted", r, (), []) for r in cs.restricted]
        if policy == "reachability":
            from cie.rem.rules import ImpactDraft

            affected = reachability_baseline(reader, list(cs.changed) + cs.deleted, budget, max_depth=budget.limits.max_depth)
            drafts = {(nid, "affected"): ImpactDraft(nid, "affected", "reachability", f"reachable from a changed record in {hop} hops",
                                                     0.0, requires={nid}) for nid, hop in affected.items()}
            engine, stop = None, budget.exceeded()
        else:
            engine = RuleEngine(reader, writer, budget)
            engine.run(cs.changed, extra)
            drafts, stop = engine.impacts, engine.stop
        impacts = _persist(session, ev, seq, drafts, engine)
        budget.tick(reader.counter.db_calls + cs.prev.counter.db_calls)
        return {"impacts": len(impacts), "suggestions": len(engine.suggestions) if engine else 0,
                "status": "incomplete" if stop else "complete", "stopping_reason": stop or "no_more_triggers",
                "budget": budget.report(), "rule_log": engine.log if engine else [],
                "analysis_ms": round((time.perf_counter() - t) * 1000, 1)}

    return run


def process_event(session: Session, event_id: uuid.UUID, *, embedder=None, policy: str = "rules",
                  limits: dict[str, Any] | None = None, route_tasks: bool = True) -> dict[str, Any]:
    """Apply one event to the live state and run the REM analysis. ``policy`` 'rules' (REM), 'reachability'
    (baseline B) or 'none' (state change only)."""
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}")
    return _events.process_event(session, event_id, embedder=embedder, analysis=None if policy == "none" else rem_analysis(policy),
                                 analysis_name=policy, limits=limits, route_tasks=route_tasks)


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
    # the supply assessment of every milestone re-evaluated here replaces earlier assessments that followed from it;
    # not when the rules stopped on a budget, because the replacement may be incomplete
    roots = engine.evaluated_roots if not engine.stop else set()
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
                                      requires=sorted(s.requires, key=str), rule_id=s.rule_id, roots=sorted(s.roots), created_seq=seq,
                                      details={"requires_scopes": s.requires_scopes}))
        elif row.status != "suggested":
            row.status, row.superseded_seq, row.event_id, row.created_seq = "suggested", None, ev.id, seq
            row.title, row.reason, row.requires, row.roots = s.title, s.reason, sorted(s.requires, key=str), sorted(s.roots)
            row.details = {"requires_scopes": s.requires_scopes}
        else:  # still open: keep one task, with the current wording and what it now reveals
            row.title, row.reason, row.requires = s.title, s.reason, sorted(set(row.requires) | s.requires, key=str)
            row.details = {"requires_scopes": sorted({tuple(x) for x in (row.details or {}).get("requires_scopes", [])} | {tuple(x) for x in s.requires_scopes})}
    if roots:
        for row in session.scalars(select(RemSuggestion).where(RemSuggestion.tenant_id == ev.tenant_id, RemSuggestion.status == "suggested",
                                                               RemSuggestion.rule_id.in_(("R1", "R2", "R3")))):
            if row.dedupe_key not in kept and row.roots and set(row.roots) <= roots:
                row.status, row.superseded_seq = "superseded", seq
    session.flush()
    ev.summary = {**(ev.summary or {}), "suggestion_keys": sorted(kept)}
    return rows


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
    if set(need) - set(visible):  # records deleted since: judged on their last recorded version
        visible.update(reader.nodes_latest(set(need) - set(visible)))

    def scopes_ok(details) -> bool:  # exact values (stock rows) carry their own scope and clearance
        return reader.vis is None or all(reader.vis.can_read(uuid.UUID(sc), int(sens)) for sc, sens in (details or {}).get("requires_scopes", []))

    out = []
    for r in rows:
        if not set(r.requires) <= set(visible) or not scopes_ok(r.details):
            continue
        t = visible[r.target_id]
        out.append({"impact_id": str(r.id), "event_id": str(r.event_id), "target": {"id": str(t.id), "type": t.type, "key": t.key, "name": t.name},
                    "impact": r.impact, "rule": r.rule_id, "grade": r.confidence, "hypothesis": r.hypothesis, "reason": r.reason,
                    "paths": r.paths, "evidence": r.evidence, "details": r.details, "status": "candidate" if r.superseded_seq is None
                    or r.superseded_seq > s else "superseded", "superseded_by": str(r.superseded_by) if r.superseded_by else None,
                    "created_seq": r.created_seq, "requires": [str(n) for n in r.requires]})
    tasks = []
    for x in sorted(sugg, key=lambda x: -x.priority):
        if not set(x.requires) <= set(visible) or not scopes_ok(x.details):
            continue
        tasks.append({"suggestion_id": str(x.id), "title": x.title, "capability": x.capability, "reason": x.reason,
                      "priority": x.priority, "targets": [str(t) for t in x.target_ids], "rule": x.rule_id,
                      "dedupe_key": x.dedupe_key, "event_id": str(x.event_id) if x.event_id else None,
                      "requires": sorted({str(n) for n in x.requires} | {str(t) for t in x.target_ids})})
    return out, tasks
