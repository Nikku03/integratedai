"""The task lifecycle, enforced.

    proposed -> ready -> running -> review -> completed
                  ^  \\      |  \\      |
                  |   blocked  |  failed <- (review, running)
                  |            v
                  +------ (lease expired: ready again, progress kept)

* **proposed -> ready/blocked**: a proposed task is accepted into the plan; it is ``blocked`` until every
  ``requires`` dependency is completed and every ``after`` dependency is settled.
* **ready -> running**: a worker claims it with a lease. Claims use ``FOR UPDATE SKIP LOCKED``, so two workers
  never run the same task. The worker heartbeats to keep the lease and checkpoints its progress. When a lease
  expires the task returns to ``ready`` with its progress intact, and another worker can pick it up.
* **ready -> running** and **review -> running** clear the record inputs of the earlier run: the worker reads its
  context again, and what it reads now is what counts.
* **running -> review**: the worker submits a result. The records its findings rely on (state references and
  calculation inputs) become task inputs, read at the snapshot of the worker's context. The engine checks the
  acceptance criteria, the cost and tool limits, and whether the task's inputs are still current. Automatic review
  completes the task or asks for changes. An agent or human review leaves it in ``review`` until the reviewer
  decides.
* **review -> running** (changes requested, a bounded number of rounds), **review -> completed**, or
  **review -> failed**. When the rounds run out, a person decides (an approval request).
* **failed -> ready** only with an authorised retry.
* **completed -> ready** only when an input the task used has changed (``reopen``); dependants that required it
  are reopened or blocked too.

Every transition is checked against this table, increments the task's ``revision`` and is logged in
``task_transitions``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Approval, Task, TaskDependency, TaskStatus
from cie.workflow.models import TaskInput, TaskTransition

S = TaskStatus
ALLOWED: dict[TaskStatus, set[TaskStatus]] = {
    S.proposed: {S.ready, S.blocked, S.cancelled},
    S.ready: {S.running, S.blocked, S.cancelled},
    S.blocked: {S.ready, S.cancelled},
    S.running: {S.review, S.blocked, S.failed, S.ready},  # ready: lease expired or released, progress kept
    S.review: {S.running, S.completed, S.failed},
    S.failed: {S.ready, S.blocked},  # authorised retry only
    S.completed: {S.ready, S.blocked},  # an input changed only
    S.cancelled: set(),
}
SETTLED = (S.completed, S.failed, S.cancelled)
DEFAULT_LEASE_SECONDS = 300


class TransitionError(ValueError):
    """The requested change is not allowed from the task's current status."""


class LeaseLost(RuntimeError):
    """The caller no longer holds the task's lease; another worker may have it."""


def now() -> datetime:
    return datetime.now(UTC)


def _log(session: Session, t: Task, frm: TaskStatus, to: TaskStatus, actor: str, reason: str, details: dict | None) -> None:
    session.add(TaskTransition(tenant_id=t.tenant_id, task_id=t.id, from_status=frm.value, to_status=to.value, actor=actor[:120],
                               reason=reason, details=details or {}, revision=t.revision))


def transition(session: Session, t: Task, to: TaskStatus, *, actor: str, reason: str = "", details: dict | None = None) -> Task:
    frm = t.status
    if to not in ALLOWED.get(frm, set()):
        raise TransitionError(f"task {t.id} cannot go from {frm.value} to {to.value}")
    t.status = to
    t.revision = (t.revision or 0) + 1
    if to != S.running:
        t.lease_owner, t.lease_expires_at = None, None
    _log(session, t, frm, to, actor, reason, details)
    session.flush()
    return t


def locked(session: Session, task_id: uuid.UUID) -> Task:
    t = session.get(Task, task_id, with_for_update=True, populate_existing=True)
    if t is None:
        raise KeyError(task_id)
    return t


# ---------------------------------------------------------------------------------------------- planning
def propose(session: Session, *, tenant_id: uuid.UUID, project_id: uuid.UUID, task_type: str, title: str, brief: str = "",
            scope_id: uuid.UUID | None = None, priority: int = 5, risk_level: str = "low", acceptance: dict | None = None,
            limits: dict | None = None, deadline_at: datetime | None = None, owner_principal_id: uuid.UUID | None = None,
            depends_on: list[tuple[uuid.UUID, str]] | None = None, verifies_task_id: uuid.UUID | None = None,
            parent_id: uuid.UUID | None = None, metrics: dict | None = None, max_attempts: int = 3, max_review_rounds: int = 1,
            actor: str = "system") -> Task:
    t = Task(tenant_id=tenant_id, project_id=project_id, scope_id=scope_id, task_type=task_type, title=title, brief=brief,
             status=S.proposed, priority=priority, risk_level=risk_level, acceptance=acceptance or {}, limits=limits or {},
             deadline_at=deadline_at, owner_principal_id=owner_principal_id, verifies_task_id=verifies_task_id, parent_id=parent_id,
             metrics=metrics or {}, max_attempts=max_attempts, max_review_rounds=max_review_rounds, progress={}, attempts=0,
             review_rounds=0, revision=0)
    session.add(t)
    session.flush()
    for dep_id, kind in depends_on or []:
        if kind not in ("requires", "after"):
            raise ValueError("dependency kind must be 'requires' or 'after'")
        session.add(TaskDependency(task_id=t.id, depends_on_id=dep_id, kind=kind))
    _log(session, t, S.proposed, S.proposed, actor, "proposed", {"title": title})
    session.flush()
    return t


def dependencies(session: Session, task_ids) -> dict[uuid.UUID, list[tuple[Task, str]]]:
    ids = list(task_ids)
    out: dict[uuid.UUID, list[tuple[Task, str]]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = session.execute(select(TaskDependency, Task).join(Task, Task.id == TaskDependency.depends_on_id)
                           .where(TaskDependency.task_id.in_(ids))).all()
    for d, dep in rows:
        out[d.task_id].append((dep, d.kind or "requires"))
    return out


def awaiting_person(t: Task) -> bool:
    return t.status == S.review and (t.verification or {}).get("awaiting") == "human"


def unmet(deps: list[tuple[Task, str]]) -> list[str]:
    """``requires`` needs the dependency completed; ``after`` needs it settled or waiting on a person's decision."""
    return [f"{dep.title} ({dep.status.value})" for dep, kind in deps
            if (kind == "requires" and dep.status != S.completed)
            or (kind == "after" and dep.status not in SETTLED and not awaiting_person(dep))]


def accept(session: Session, t: Task, *, actor: str) -> Task:
    """proposed -> ready, or blocked while dependencies are not met."""
    waiting = unmet(dependencies(session, [t.id])[t.id])
    if waiting:
        return transition(session, t, S.blocked, actor=actor, reason="accepted; waiting for " + ", ".join(waiting))
    return transition(session, t, S.ready, actor=actor, reason="accepted")


def refresh(session: Session, *, project_id: uuid.UUID | None = None, task_ids=None, actor: str = "engine") -> list[Task]:
    """Ready tasks whose dependencies are no longer met become blocked; blocked tasks whose dependencies are met become
    ready. Returns the tasks that changed."""
    q = select(Task).where(Task.status.in_([S.ready, S.blocked]))
    if project_id is not None:
        q = q.where(Task.project_id == project_id)
    if task_ids is not None:
        q = q.where(Task.id.in_(list(task_ids)))
    tasks = list(session.scalars(q))
    deps = dependencies(session, [t.id for t in tasks])
    changed = []
    for t in tasks:
        waiting = unmet(deps[t.id])
        if t.status == S.ready and waiting:
            changed.append(transition(session, t, S.blocked, actor=actor, reason="waiting for " + ", ".join(waiting)))
        elif t.status == S.blocked and not waiting:
            changed.append(transition(session, t, S.ready, actor=actor, reason="dependencies met"))
    return changed


def dependants(session: Session, task_id: uuid.UUID) -> list[tuple[Task, str]]:
    rows = session.execute(select(Task, TaskDependency.kind).join(TaskDependency, TaskDependency.task_id == Task.id)
                           .where(TaskDependency.depends_on_id == task_id)).all()
    return [(t, k or "requires") for t, k in rows]


# ---------------------------------------------------------------------------------------------- running
def claim_task(session: Session, task_id: uuid.UUID, *, worker: str, agent_id: uuid.UUID | None = None,
               lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Task:
    t = locked(session, task_id)
    if t.status != S.ready:
        raise TransitionError(f"task {t.id} is {t.status.value}, not ready")
    return _start(session, t, worker, agent_id, lease_seconds)


def claim(session: Session, tenant_id: uuid.UUID, *, worker: str, agent_id: uuid.UUID | None = None, task_types=None,
          project_id: uuid.UUID | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Task | None:
    """The next ready task, by priority then age. ``SKIP LOCKED``: concurrent workers never claim the same task."""
    q = select(Task).where(Task.tenant_id == tenant_id, Task.status == S.ready)
    if task_types:
        q = q.where(Task.task_type.in_(list(task_types)))
    if project_id is not None:
        q = q.where(Task.project_id == project_id)
    t = session.scalar(q.order_by(Task.priority, Task.created_at).limit(1).with_for_update(skip_locked=True))
    if t is None:
        return None
    return _start(session, t, worker, agent_id, lease_seconds)


def clear_record_inputs(session: Session, t: Task) -> None:
    """A task about to run (again) rebuilds its context, so the records an earlier run read are no longer its inputs.
    Without this, a record deleted or changed since the earlier run would keep the new run from ever completing."""
    from sqlalchemy import delete

    session.execute(delete(TaskInput).where(TaskInput.task_id == t.id, TaskInput.ref_kind == "record"))
    if (t.progress or {}).get("context_seq") is not None:
        t.progress = {k: v for k, v in t.progress.items() if k != "context_seq"}


def note_context(t: Task, seq: int) -> None:
    """A context was read at snapshot ``seq``; what the result relies on is judged against the earliest one."""
    cur = (t.progress or {}).get("context_seq")
    t.progress = {**(t.progress or {}), "context_seq": seq if cur is None else min(int(cur), int(seq))}


def relied_on(session: Session, t: Task, result: dict[str, Any]) -> dict[uuid.UUID, tuple[int, str]]:
    """The live-state records a result's findings rely on: their state references and the inputs of their
    calculations, with the version each was read at (the one the finding names, else the one at the context snapshot)."""
    from cie.state.domain_events import _view
    from cie.state.store import GraphReader

    seq = (t.progress or {}).get("context_seq")
    reader = GraphReader(session, t.tenant_id, None, seq=seq)
    refs: list[tuple[Any, int | None]] = []
    for f in result.get("findings") or []:
        refs += [(r.get("ref") or r.get("id"), r.get("version")) for r in f.get("state_refs") or []]
        refs += [(spec.get("ref") or spec.get("id"), None) for spec in ((f.get("calculation") or {}).get("inputs") or {}).values()
                 if isinstance(spec, dict)]
    out: dict[uuid.UUID, tuple[int, str]] = {}
    for ref, version in refs:
        if ref is None:
            continue
        try:
            n = _view(reader, ref)
        except (ValueError, KeyError, TypeError):
            n = None
        if n is None:
            continue  # unknown or invisible: verification fails the finding
        v = int(version) if version is not None else n.version
        if n.id not in out or v < out[n.id][0]:
            out[n.id] = (v, f"{n.type}:{n.key}")
    return out


def _start(session: Session, t: Task, worker: str, agent_id: uuid.UUID | None, lease_seconds: int) -> Task:
    clear_record_inputs(session, t)
    t.attempts = (t.attempts or 0) + 1
    if agent_id is not None:
        t.assigned_agent_id = agent_id
    transition(session, t, S.running, actor=worker, reason=f"claimed (attempt {t.attempts})",
               details={"resumed_from": t.progress.get("checkpoint")} if (t.progress or {}).get("checkpoint") else None)
    t.lease_owner, t.lease_expires_at = worker, now() + timedelta(seconds=lease_seconds)
    session.flush()
    return t


def _held(session: Session, task_id: uuid.UUID, worker: str) -> Task:
    t = locked(session, task_id)
    if t.status != S.running or t.lease_owner != worker:
        raise LeaseLost(f"{worker} does not hold task {task_id} (status {t.status.value}, lease {t.lease_owner})")
    if t.lease_expires_at is not None and t.lease_expires_at < now():
        raise LeaseLost(f"the lease on task {task_id} expired")
    return t


def heartbeat(session: Session, task_id: uuid.UUID, *, worker: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Task:
    t = _held(session, task_id, worker)
    t.lease_expires_at = now() + timedelta(seconds=lease_seconds)
    session.flush()
    return t


def checkpoint(session: Session, task_id: uuid.UUID, *, worker: str, progress: dict[str, Any]) -> Task:
    """Record progress. It survives a lost lease, so the next worker resumes instead of starting over."""
    t = _held(session, task_id, worker)
    t.progress = {**(t.progress or {}), **progress, "checkpoint": (t.progress or {}).get("checkpoint", 0) + 1,
                  "checkpoint_at": now().isoformat(), "checkpoint_by": worker}
    session.flush()
    return t


def release(session: Session, task_id: uuid.UUID, *, worker: str, reason: str = "released") -> Task:
    t = _held(session, task_id, worker)
    return transition(session, t, S.ready, actor=worker, reason=reason)


def block(session: Session, task_id: uuid.UUID, *, worker: str, reason: str) -> Task:
    """The worker cannot continue (missing input, waiting on someone); progress is kept."""
    t = _held(session, task_id, worker)
    t.progress = {**(t.progress or {}), "blocked_reason": reason}
    return transition(session, t, S.blocked, actor=worker, reason=reason)


def reclaim_expired(session: Session, *, tenant_id: uuid.UUID | None = None, at: datetime | None = None) -> list[Task]:
    """Running tasks whose lease expired go back to ready with their progress, or fail once attempts run out."""
    at = at or now()
    q = select(Task).where(Task.status == S.running, Task.lease_expires_at.is_not(None), Task.lease_expires_at < at)
    if tenant_id is not None:
        q = q.where(Task.tenant_id == tenant_id)
    out = []
    for t in session.scalars(q.with_for_update(skip_locked=True)).all():
        who = t.lease_owner or "?"
        if (t.attempts or 0) >= (t.max_attempts or 1):
            out.append(transition(session, t, S.failed, actor="engine", reason=f"lease of {who} expired after {t.attempts} attempts"))
        else:
            out.append(transition(session, t, S.ready, actor="engine", reason=f"lease of {who} expired; progress kept for the next worker"))
    return out


# ---------------------------------------------------------------------------------------------- inputs
def record_inputs(session: Session, t: Task, records: dict[uuid.UUID, tuple[int, str]] | None = None,
                  tasks: list[Task] | None = None, seq: int | None = None) -> None:
    """Remember which versions a task's work was based on: live-state records (with the snapshot ``seq`` they were
    read at, so changes that add no version, such as a stock count or a new relationship, are caught too) and
    other tasks' results."""
    if records and seq is None:
        from cie.state.store import current_seq

        seq = current_seq(session, t.tenant_id)
    rows = [("record", nid, v, label, seq) for nid, (v, label) in (records or {}).items()]
    rows += [("task", d.id, d.revision or 0, d.title[:300], None) for d in tasks or []]
    for kind, rid, version, label, at in rows:
        cur = session.get(TaskInput, (t.id, kind, rid))
        if cur is None:
            session.add(TaskInput(task_id=t.id, ref_kind=kind, ref_id=rid, tenant_id=t.tenant_id, version=version, label=label, seq=at))
        else:
            cur.version, cur.label, cur.seq = version, label, at
    session.flush()


def stale_inputs(session: Session, t: Task) -> list[dict[str, Any]]:
    """Inputs that moved on since the task used them: a record with a newer version (or deleted), or a task whose
    result changed."""
    from cie.state.models import RemNode, RemNodeVersion

    inputs = list(session.scalars(select(TaskInput).where(TaskInput.task_id == t.id)))
    recs = [i for i in inputs if i.ref_kind == "record"]
    out = []
    if recs:
        ids = [i.ref_id for i in recs]
        cur = dict(session.execute(select(RemNodeVersion.node_id, RemNodeVersion.version).where(
            RemNodeVersion.node_id.in_(ids), RemNodeVersion.sys_to.is_(None))).all())
        changed = dict(session.execute(select(RemNode.id, RemNode.changed_seq).where(RemNode.id.in_(ids))).all())
        for i in recs:
            if cur.get(i.ref_id) != i.version:
                out.append({"kind": "record", "id": str(i.ref_id), "label": i.label, "used": i.version, "now": cur.get(i.ref_id)})
            elif i.seq is not None and (changed.get(i.ref_id) or 0) > i.seq:  # a relationship or stock count changed
                out.append({"kind": "record", "id": str(i.ref_id), "label": i.label, "used": i.version, "now": cur.get(i.ref_id),
                            "read_at_seq": i.seq, "changed_at_seq": changed.get(i.ref_id)})
    for i in inputs:
        if i.ref_kind == "task":
            d = session.get(Task, i.ref_id)
            if d is None or (d.revision or 0) != i.version:
                out.append({"kind": "task", "id": str(i.ref_id), "label": i.label, "used": i.version,
                            "now": d.revision if d else None, "status": d.status.value if d else None})
    return out


# ---------------------------------------------------------------------------------------------- results and review
def check_acceptance(t: Task, result: dict[str, Any]) -> list[str]:
    """The task's acceptance criteria against a result. Returns what is not met."""
    a = t.acceptance or {}
    findings = result.get("findings") or []
    out = []
    if len(findings) < int(a.get("min_findings", 0)):
        out.append(f"at least {a['min_findings']} finding(s) required, got {len(findings)}")
    if a.get("citations_required") and any(not f.get("citations") for f in findings):
        out.append(f"{sum(1 for f in findings if not f.get('citations'))} finding(s) without a citation")
    if "max_unsupported" in a and len(result.get("unsupported_claims") or []) > int(a["max_unsupported"]):
        out.append(f"{len(result.get('unsupported_claims') or [])} unsupported claim(s); at most {a['max_unsupported']} allowed")
    for f in a.get("required_fields", []):
        if result.get(f) in (None, "", [], {}):
            out.append(f"result field '{f}' is missing")
    if "min_confidence" in a and float(result.get("confidence", 1.0)) < float(a["min_confidence"]):
        out.append(f"confidence {result.get('confidence')} below {a['min_confidence']}")
    return out


def check_limits(t: Task, usage: dict[str, Any]) -> list[str]:
    lim = t.limits or {}
    out = []
    for key, used in (("max_tokens", usage.get("tokens")), ("max_cost_usd", usage.get("cost_usd")), ("max_seconds", usage.get("seconds"))):
        if key in lim and used is not None and float(used) > float(lim[key]):
            out.append(f"{key.removeprefix('max_')} {used} exceeds the limit {lim[key]}")
    if "tools" in lim:
        extra = sorted(set(usage.get("tools") or []) - set(lim["tools"]))
        if extra:
            out.append(f"tools not allowed for this task: {', '.join(extra)}")
    return out


def tool_allowed(t: Task, tool: str) -> bool:
    return "tools" not in (t.limits or {}) or tool in t.limits["tools"]


def review_mode(t: Task) -> str:
    return str((t.acceptance or {}).get("review") or ("agent" if t.risk_level == "high" else "auto"))


def submit(session: Session, task_id: uuid.UUID, *, worker: str, result: dict[str, Any], usage: dict[str, Any] | None = None) -> Task:
    """running -> review, then the automatic checks. Returns the task in its new status."""
    t = _held(session, task_id, worker)
    usage = usage or {}
    relied = relied_on(session, t, result)
    if relied:  # what the result relies on is an input, whatever else the worker's context held
        record_inputs(session, t, records=relied, seq=(t.progress or {}).get("context_seq"))
    t.result = result
    t.metrics = {**(t.metrics or {}), **{k: v for k, v in usage.items() if k != "tools"}, "tools": usage.get("tools", [])}
    transition(session, t, S.review, actor=worker, reason="result submitted")
    t.lease_owner = worker  # remembered for changes requested; not a lease while in review
    over = check_limits(t, usage)
    if over:
        return _decide(session, t, "failed", "engine", "limits exceeded: " + "; ".join(over), {"limits": over})
    stale = stale_inputs(session, t)
    if stale:
        return _decide(session, t, "changes_requested", "engine", "inputs changed while the task ran", {"stale_inputs": stale})
    missing = check_acceptance(t, result)
    if missing:
        return _decide(session, t, "changes_requested", "engine", "acceptance criteria not met: " + "; ".join(missing), {"acceptance": missing})
    mode = review_mode(t)
    if mode == "auto":
        return _decide(session, t, "passed", "engine", "acceptance criteria met", {"acceptance": "met"})
    t.verification = {**(t.verification or {}), "review": mode, "awaiting": mode}
    if mode == "human":
        _approval(session, t, f"Review the result of '{t.title}'", worker)
    session.flush()
    return t


def review(session: Session, task_id: uuid.UUID, *, reviewer: str, verdict: str, notes: str = "", details: dict | None = None) -> Task:
    """A reviewer's decision on a task in review: 'passed', 'changes_requested' or 'failed'."""
    t = locked(session, task_id)
    if t.status != S.review:
        raise TransitionError(f"task {t.id} is {t.status.value}, not in review")
    return _decide(session, t, verdict, reviewer, notes, details or {})


def _decide(session: Session, t: Task, verdict: str, reviewer: str, notes: str, details: dict) -> Task:
    if verdict == "passed":
        stale = stale_inputs(session, t)
        if stale:  # never complete on inputs that have moved on
            verdict, notes, details = "changes_requested", "inputs changed during review", {**details, "stale_inputs": stale}
    rec = {"reviewer": reviewer, "verdict": verdict, "notes": notes, "details": details, "at": now().isoformat(), "round": t.review_rounds}
    t.verification = {**(t.verification or {}), "last_review": rec, "reviews": list((t.verification or {}).get("reviews", []))[-9:] + [rec]}
    if verdict == "passed":
        t.verification.pop("awaiting", None)
        transition(session, t, S.completed, actor=reviewer, reason=notes or "review passed", details=details)
        t.lease_owner = None
        _settled(session, t)
        return t
    if verdict == "failed":
        t.verification.pop("awaiting", None)
        transition(session, t, S.failed, actor=reviewer, reason=notes or "review failed", details=details)
        _settled(session, t)
        return t
    if verdict != "changes_requested":
        raise ValueError("verdict must be passed, changes_requested or failed")
    if (t.review_rounds or 0) >= (t.max_review_rounds or 0):
        # out of rounds: a person decides; the task stays in review
        t.verification = {**t.verification, "review": "human", "awaiting": "human"}
        _approval(session, t, f"'{t.title}' still fails review after {t.review_rounds} round(s): {notes}", reviewer)
        session.flush()
        return t
    t.review_rounds = (t.review_rounds or 0) + 1
    t.progress = {**(t.progress or {}), "changes_requested": {"by": reviewer, "notes": notes, "details": details, "round": t.review_rounds}}
    clear_record_inputs(session, t)  # the worker addresses the review with a fresh context
    worker = t.lease_owner
    transition(session, t, S.running, actor=reviewer, reason=f"changes requested: {notes}", details=details)
    t.lease_owner, t.lease_expires_at = worker, now() + timedelta(seconds=DEFAULT_LEASE_SECONDS)  # back to the same worker
    session.flush()
    return t


def _settled(session: Session, t: Task) -> None:
    """Unblock dependants; reopen completed dependants that used an earlier revision of this task (for example a
    synthesis that reported it as waiting on a person)."""
    deps = dependants(session, t.id)
    refresh(session, task_ids=[d.id for d, _ in deps], actor="engine")
    for d, _ in deps:
        if d.status != S.completed:
            continue
        used = session.get(TaskInput, (d.id, "task", t.id))
        if used is not None and used.version != t.revision:
            reopen(session, d.id, actor="engine", reason=f"'{t.title}' was decided after it was used",
                   details={"task": str(t.id), "used_revision": used.version, "now": t.revision})


def escalate(session: Session, task_id: uuid.UUID, *, actor: str, reason: str) -> Task:
    """A task in review that no agent can review: a person decides."""
    t = locked(session, task_id)
    if t.status != S.review:
        raise TransitionError(f"task {t.id} is {t.status.value}, not in review")
    t.verification = {**(t.verification or {}), "review": "human", "awaiting": "human"}
    _approval(session, t, reason, actor)
    session.flush()
    return t


def _approval(session: Session, t: Task, summary: str, requested_by: str) -> None:
    exists = session.scalar(select(Approval.id).where(Approval.tenant_id == t.tenant_id, Approval.kind == "task_result",
                                                      Approval.subject_id == str(t.id), Approval.status == "pending"))
    if exists is None:
        session.add(Approval(tenant_id=t.tenant_id, kind="task_result", subject_id=str(t.id), summary=summary[:2000], requested_by=requested_by))


def fail(session: Session, task_id: uuid.UUID, *, actor: str, error: str) -> Task:
    t = locked(session, task_id)
    t.progress = {**(t.progress or {}), "last_error": error[:2000]}
    return transition(session, t, S.failed, actor=actor, reason=error[:2000])


def retry(session: Session, task_id: uuid.UUID, *, authorized_by: uuid.UUID | str, reason: str = "") -> Task:
    """failed -> ready (or blocked), only with someone's authorisation; one more attempt is allowed."""
    t = locked(session, task_id)
    if t.status != S.failed:
        raise TransitionError(f"task {t.id} is {t.status.value}; only a failed task can be retried")
    t.retry_authorized_by = authorized_by if isinstance(authorized_by, uuid.UUID) else None
    t.max_attempts = max(t.max_attempts or 1, (t.attempts or 0) + 1)
    t.review_rounds = 0
    waiting = unmet(dependencies(session, [t.id])[t.id])
    return transition(session, t, S.blocked if waiting else S.ready, actor=str(authorized_by), reason=f"retry authorised: {reason}".strip(": "))


def cancel(session: Session, task_id: uuid.UUID, *, actor: str, reason: str) -> Task:
    t = locked(session, task_id)
    return transition(session, t, S.cancelled, actor=actor, reason=reason)


def reopen(session: Session, task_id: uuid.UUID, *, actor: str, reason: str, details: dict | None = None,
           _seen: set | None = None) -> list[Task]:
    """completed -> ready because an input changed; dependants that required it are reopened (if completed) or
    blocked (if waiting). Returns every task reopened or blocked."""
    seen = _seen if _seen is not None else set()
    if task_id in seen:
        return []
    seen.add(task_id)
    t = locked(session, task_id)
    if t.status != S.completed:
        return []
    t.progress = {**(t.progress or {}), "reopened": {"reason": reason, "details": details or {}, "at": now().isoformat()}}
    t.review_rounds = 0
    waiting = unmet(dependencies(session, [t.id])[t.id])
    out = [transition(session, t, S.blocked if waiting else S.ready, actor=actor, reason=reason, details=details)]
    for d, kind in dependants(session, t.id):
        if kind != "requires":
            continue
        if d.status == S.completed:
            out += reopen(session, d.id, actor=actor, reason=f"its dependency '{t.title}' was reopened", _seen=seen)
        elif d.status == S.ready:
            out.append(transition(session, d, S.blocked, actor=actor, reason=f"its dependency '{t.title}' was reopened"))
    return out


def overdue(session: Session, tenant_id: uuid.UUID, at: datetime | None = None) -> list[Task]:
    at = at or now()
    return list(session.scalars(select(Task).where(Task.tenant_id == tenant_id, Task.deadline_at.is_not(None), Task.deadline_at < at,
                                                   Task.status.not_in(list(SETTLED))).order_by(Task.deadline_at)))


def transitions(session: Session, task_id: uuid.UUID) -> list[TaskTransition]:
    return list(session.scalars(select(TaskTransition).where(TaskTransition.task_id == task_id)
                                .order_by(TaskTransition.revision, TaskTransition.created_at)))


def active_for(session: Session, agent_id: uuid.UUID) -> int:
    from sqlalchemy import func

    return session.scalar(select(func.count(Task.id)).where(Task.assigned_agent_id == agent_id, Task.status == S.running)) or 0


