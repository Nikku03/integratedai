"""Append-only, hash-chained project ledger.

Entry kinds: objective, requirement, plan, task, assignment, hypothesis, test,
result, failure, decision, artifact, commit, blocker, next_action,
contradiction, verification, synthesis. ``state()`` folds the chain into the
current project view so any agent sees where things stand without the
conversation history.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import orjson
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cie.core.models import LedgerEntry

KINDS = {"objective", "requirement", "plan", "task", "assignment", "hypothesis", "test", "result", "failure", "decision",
         "artifact", "commit", "blocker", "next_action", "contradiction", "verification", "synthesis", "message"}


def _hash(prev: str | None, seq: int, kind: str, label: str | None, content: dict, refs: dict, actor: str | None) -> str:
    body = orjson.dumps({"prev": prev, "seq": seq, "kind": kind, "label": label, "content": content, "refs": refs, "actor": actor},
                        option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(body).hexdigest()


def append(session: Session, *, tenant_id: uuid.UUID, project_id: uuid.UUID, kind: str, content: dict[str, Any],
           label: str | None = None, refs: dict[str, Any] | None = None, actor: str | None = None) -> LedgerEntry:
    if kind not in KINDS:
        raise ValueError(f"unknown ledger kind {kind}")
    refs = refs or {}
    last = session.scalar(select(LedgerEntry).where(LedgerEntry.project_id == project_id).order_by(LedgerEntry.seq.desc()).limit(1))
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else None
    entry = LedgerEntry(tenant_id=tenant_id, project_id=project_id, seq=seq, kind=kind, label=label, content=content, refs=refs,
                        actor=actor, prev_hash=prev, hash=_hash(prev, seq, kind, label, content, refs, actor))
    session.add(entry)
    session.flush()
    return entry


def entries(session: Session, project_id: uuid.UUID) -> list[LedgerEntry]:
    return list(session.scalars(select(LedgerEntry).where(LedgerEntry.project_id == project_id).order_by(LedgerEntry.seq)))


def verify_chain(session: Session, project_id: uuid.UUID) -> tuple[bool, int | None]:
    prev = None
    for e in entries(session, project_id):
        if e.prev_hash != prev or e.hash != _hash(prev, e.seq, e.kind, e.label, e.content, e.refs, e.actor):
            return False, e.seq
        prev = e.hash
    return True, None


def next_label(session: Session, project_id: uuid.UUID, prefix: str) -> str:
    n = session.scalar(select(func.count(LedgerEntry.id)).where(LedgerEntry.project_id == project_id, LedgerEntry.label.like(f"{prefix}%"))) or 0
    return f"{prefix}{n + 1}"


def state(session: Session, project_id: uuid.UUID) -> dict[str, Any]:
    """Current project state folded from the ledger."""
    st: dict[str, Any] = {"objectives": [], "requirements": [], "plans": [], "tasks": {}, "assignments": {}, "hypotheses": {},
                          "tests": [], "results": [], "failures": [], "decisions": [], "artifacts": [], "commits": [],
                          "blockers": [], "next_actions": [], "contradictions": [], "verifications": [], "synthesis": None,
                          "entries": 0, "head_hash": None}
    for e in entries(session, project_id):
        st["entries"] = e.seq
        st["head_hash"] = e.hash
        c = {**e.content, "seq": e.seq, "label": e.label, "at": e.created_at.isoformat(), "actor": e.actor, "refs": e.refs}
        if e.kind == "objective":
            st["objectives"].append(c)
        elif e.kind == "requirement":
            st["requirements"].append(c)
        elif e.kind == "plan":
            st["plans"].append(c)
        elif e.kind == "task":
            st["tasks"][c.get("task_id")] = {**st["tasks"].get(c.get("task_id"), {}), **c}
        elif e.kind == "assignment":
            st["assignments"][c.get("task_id")] = c
            if c.get("task_id") in st["tasks"]:
                st["tasks"][c["task_id"]]["assigned_to"] = c.get("agent")
        elif e.kind == "hypothesis":
            st["hypotheses"][e.label] = {**c, "tests": [], "results": []}
        elif e.kind == "test":
            st["tests"].append(c)
            if c.get("hypothesis") in st["hypotheses"]:
                st["hypotheses"][c["hypothesis"]]["tests"].append(c)
        elif e.kind == "result":
            st["results"].append(c)
            tid = c.get("task_id")
            if tid in st["tasks"]:
                st["tasks"][tid]["status"] = c.get("status", "done")
            if c.get("hypothesis") in st["hypotheses"]:
                st["hypotheses"][c["hypothesis"]]["results"].append(c)
        elif e.kind == "failure":
            st["failures"].append(c)
            if c.get("task_id") in st["tasks"]:
                st["tasks"][c["task_id"]]["status"] = "failed"
        elif e.kind == "decision":
            st["decisions"].append(c)
        elif e.kind == "artifact":
            st["artifacts"].append(c)
        elif e.kind == "commit":
            st["commits"].append(c)
        elif e.kind == "blocker":
            st["blockers"].append(c)
        elif e.kind == "next_action":
            st["next_actions"].append(c)
        elif e.kind == "contradiction":
            st["contradictions"].append(c)
        elif e.kind == "verification":
            st["verifications"].append(c)
            if c.get("task_id") in st["tasks"]:
                st["tasks"][c["task_id"]]["verification"] = c.get("verdict")
        elif e.kind == "synthesis":
            st["synthesis"] = c
    # open blockers = blockers without a later result on the same task
    resolved = {r.get("task_id") for r in st["results"]}
    st["open_blockers"] = [b for b in st["blockers"] if b.get("task_id") not in resolved]
    return st
