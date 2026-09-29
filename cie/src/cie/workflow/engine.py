"""The task lifecycle, enforced.

    proposed -> ready -> running -> review -> completed
                  ^  \\      |  \\      |
                  |   blocked  |  failed <- (review, running)
                  |            v
                  +------ (lease expired: ready again, progress kept)

* **proposed -> ready/blocked**: a proposed task is accepted into the plan; it is ``blocked`` until every
  ``requires`` dependency is completed and every ``after`` dependency is settled. A ``requires`` dependency on
  named outputs is met as soon as those outputs are released, while the dependency is still running.
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

**Outputs released early.** A running task releases named results as soon as it has them (``publish_output``),
for example logistics' ``expedite_cost`` long before its full plan is done. Tasks that need only that result
become ready at once and record the version they used. Releasing the same value again changes nothing. A changed
value reopens or flags only the tasks that used the earlier version. When a task is reopened, its outputs are
``revising``: tasks that have not started wait, and tasks that already used them are disturbed only if a changed
value is released. A reopened task must re-release every output before it can complete.

**Work requests** (``request_work``). A running task can ask another role for work it cannot do itself: logistics
asks finance to check a budget. The request is a proposed task on the requester's behalf, answered by releasing
an ``answer`` output. The head (or a person) accepts it, merges it into an equivalent open request, or declines
it (``decide_request``). With ``wait``, the requester depends on the answer and steps aside (``blocked``, its
progress kept); it becomes ready again when the answer is released, and reads it in its context. A declined,
failed or cancelled request releases the requester, which is told why. Requests are bounded: at most
``REQUEST_MAX_PER_TASK`` per task and ``REQUEST_MAX_DEPTH`` requests deep.

**Scheduling** (``schedule``). Ready tasks are ordered by their priority, then by their deadline slack (the latest
start that still meets every deadline downstream, from task estimates), then by the longest chain of work waiting
behind them, then by how many tasks they unblock. Each place in the order comes with its reason. ``claim`` takes
the first task in this order that no other worker holds.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cie.core.models import Approval, Task, TaskDependency, TaskStatus
from cie.workflow.models import TaskInput, TaskOutput, TaskTransition

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
DEFAULT_ESTIMATE_SECONDS = 600.0  # a task's expected duration when it gives none (metrics.estimate_seconds)
REQUEST_MAX_PER_TASK = 5  # work requests one task may make
REQUEST_MAX_DEPTH = 3  # a request made by a requested task made by ... at most this deep


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
    if to in SETTLED and (t.metrics or {}).get("requested_by_task"):
        _request_settled(session, t, reason)
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
            depends_on: list[tuple] | None = None, verifies_task_id: uuid.UUID | None = None,
            parent_id: uuid.UUID | None = None, metrics: dict | None = None, max_attempts: int = 3, max_review_rounds: int = 1,
            actor: str = "system") -> Task:
    t = Task(tenant_id=tenant_id, project_id=project_id, scope_id=scope_id, task_type=task_type, title=title, brief=brief,
             status=S.proposed, priority=priority, risk_level=risk_level, acceptance=acceptance or {}, limits=limits or {},
             deadline_at=deadline_at, owner_principal_id=owner_principal_id, verifies_task_id=verifies_task_id, parent_id=parent_id,
             metrics=metrics or {}, max_attempts=max_attempts, max_review_rounds=max_review_rounds, progress={}, attempts=0,
             review_rounds=0, revision=0)
    session.add(t)
    session.flush()
    for dep in depends_on or []:
        dep_id, kind, outputs = (tuple(dep) + ([],))[:3]
        add_dependency(session, t, dep_id, kind, outputs)
    _log(session, t, S.proposed, S.proposed, actor, "proposed", {"title": title})
    session.flush()
    return t


def add_dependency(session: Session, t: Task, dep_id: uuid.UUID, kind: str = "requires", outputs: list[str] | None = None) -> None:
    """``t`` depends on task ``dep_id``: ``requires`` (completed, or only the named ``outputs`` released) or
    ``after`` (settled)."""
    if kind not in ("requires", "after"):
        raise ValueError("dependency kind must be 'requires' or 'after'")
    if outputs and kind != "requires":
        raise ValueError("only a 'requires' dependency can name outputs")
    session.add(TaskDependency(task_id=t.id, depends_on_id=dep_id, kind=kind, outputs=sorted(set(outputs or []))))


class Dep(NamedTuple):
    task: Task
    kind: str
    outputs: list[str]


def dependencies(session: Session, task_ids) -> dict[uuid.UUID, list[Dep]]:
    ids = list(task_ids)
    out: dict[uuid.UUID, list[Dep]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = session.execute(select(TaskDependency, Task).join(Task, Task.id == TaskDependency.depends_on_id)
                           .where(TaskDependency.task_id.in_(ids))).all()
    for d, dep in rows:
        out[d.task_id].append(Dep(dep, d.kind or "requires", list(d.outputs or [])))
    return out


def released(session: Session, task_ids) -> dict[tuple[uuid.UUID, str], TaskOutput]:
    """The outputs these tasks have released, by (task id, key)."""
    ids = list(set(task_ids))
    if not ids:
        return {}
    return {(o.task_id, o.key): o for o in session.scalars(select(TaskOutput).where(TaskOutput.task_id.in_(ids)))}


def awaiting_person(t: Task) -> bool:
    return t.status == S.review and (t.verification or {}).get("awaiting") == "human"


def unmet(deps: list[Dep], outs: dict[tuple[uuid.UUID, str], TaskOutput] | None = None) -> list[str]:
    """``requires`` needs the dependency completed, or, when it names outputs, those outputs released and current
    (not being revised) and the dependency not failed or cancelled; ``after`` needs it settled or waiting on a
    person's decision."""
    outs = outs or {}
    waiting = []
    for dep, kind, names in deps:
        if kind == "after":
            if dep.status not in SETTLED and not awaiting_person(dep):
                waiting.append(f"{dep.title} ({dep.status.value})")
        elif not names:
            if dep.status != S.completed:
                waiting.append(f"{dep.title} ({dep.status.value})")
        elif dep.status in (S.failed, S.cancelled):
            waiting.append(f"{dep.title} ({dep.status.value})")
        else:
            missing = [k for k in names if (o := outs.get((dep.id, k))) is None or o.status != "current"]
            if missing:
                how = "being revised" if all(outs.get((dep.id, k)) is not None for k in missing) else "not released yet"
                waiting.append(f"{dep.title}: {', '.join(missing)} ({how})")
    return waiting


def waiting_for(session: Session, task_ids) -> dict[uuid.UUID, list[str]]:
    """What each task still waits for among its dependencies."""
    deps = dependencies(session, task_ids)
    outs = released(session, [d.task.id for ds in deps.values() for d in ds if d.outputs])
    return {i: unmet(ds, outs) for i, ds in deps.items()}


def accept(session: Session, t: Task, *, actor: str) -> Task:
    """proposed -> ready, or blocked while dependencies are not met."""
    waiting = waiting_for(session, [t.id])[t.id]
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
    waits = waiting_for(session, [t.id for t in tasks])
    changed = []
    for t in tasks:
        waiting = waits[t.id]
        if t.status == S.ready and waiting:
            changed.append(transition(session, t, S.blocked, actor=actor, reason="waiting for " + ", ".join(waiting)))
        elif t.status == S.blocked and not waiting:
            changed.append(transition(session, t, S.ready, actor=actor, reason="dependencies met"))
    return changed


def dependants(session: Session, task_id: uuid.UUID) -> list[Dep]:
    """The tasks that depend on ``task_id``, with the kind of dependency and the outputs they need."""
    rows = session.execute(select(Task, TaskDependency.kind, TaskDependency.outputs).join(TaskDependency, TaskDependency.task_id == Task.id)
                           .where(TaskDependency.depends_on_id == task_id)).all()
    return [Dep(t, k or "requires", list(o or [])) for t, k, o in rows]


# ---------------------------------------------------------------------------------------------- running
def claim_task(session: Session, task_id: uuid.UUID, *, worker: str, agent_id: uuid.UUID | None = None,
               lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Task:
    t = locked(session, task_id)
    if t.status != S.ready:
        raise TransitionError(f"task {t.id} is {t.status.value}, not ready")
    return _start(session, t, worker, agent_id, lease_seconds)


def claim(session: Session, tenant_id: uuid.UUID, *, worker: str, agent_id: uuid.UUID | None = None, task_types=None,
          project_id: uuid.UUID | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS, order: str = "schedule",
          at: datetime | None = None) -> Task | None:
    """The next ready task: in ``schedule`` order (the default), or by priority then age (``order="fifo"``).
    ``SKIP LOCKED``: concurrent workers never claim the same task."""
    if order == "fifo":
        q = select(Task).where(Task.tenant_id == tenant_id, Task.status == S.ready)
        if task_types:
            q = q.where(Task.task_type.in_(list(task_types)))
        if project_id is not None:
            q = q.where(Task.project_id == project_id)
        t = session.scalar(q.order_by(Task.priority, Task.created_at).limit(1).with_for_update(skip_locked=True))
        return None if t is None else _start(session, t, worker, agent_id, lease_seconds)
    for cand, why in schedule(session, tenant_id=tenant_id, project_id=project_id, task_types=task_types, at=at):
        t = session.scalar(select(Task).where(Task.id == cand.id, Task.status == S.ready).with_for_update(skip_locked=True)
                           .execution_options(populate_existing=True))
        if t is not None:
            return _start(session, t, worker, agent_id, lease_seconds, why=why)
    return None


def _estimate(t: Task) -> float:
    try:
        return max(0.0, float((t.metrics or {}).get("estimate_seconds") or DEFAULT_ESTIMATE_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_ESTIMATE_SECONDS


def schedule(session: Session, *, tenant_id: uuid.UUID, project_id: uuid.UUID | None = None, task_types=None,
             at: datetime | None = None) -> list[tuple[Task, dict[str, Any]]]:
    """The ready tasks in the order to run them, each with its reason: priority (lower first), then deadline slack
    (seconds between now and the latest start that still meets every deadline downstream; none = no deadline
    depends on it), then the longest chain of estimated work from it through the tasks waiting on it, then how many
    unfinished tasks wait on it, then age."""
    at = at or now()
    q = select(Task).where(Task.tenant_id == tenant_id, Task.status.not_in(list(SETTLED)))
    if project_id is not None:
        q = q.where(Task.project_id == project_id)
    open_ = {t.id: t for t in session.scalars(q)}
    if not open_:
        return []
    kids: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for d in session.scalars(select(TaskDependency).where(TaskDependency.depends_on_id.in_(list(open_)))):
        if d.task_id in open_:
            kids[d.depends_on_id].append(d.task_id)
    path: dict[uuid.UUID, float] = {}
    latest: dict[uuid.UUID, float | None] = {}
    below: dict[uuid.UUID, frozenset] = {}

    def walk(i: uuid.UUID, trail: frozenset) -> None:
        if i in path:
            return
        t, est = open_[i], _estimate(open_[i])
        cs = [c for c in kids[i] if c not in trail]  # a cycle is cut, not followed
        for c in cs:
            walk(c, trail | {i})
        path[i] = est + max((path[c] for c in cs), default=0.0)
        below[i] = frozenset(cs).union(*(below[c] for c in cs)) if cs else frozenset()
        starts = [latest[c] - est for c in cs if latest[c] is not None]
        if t.deadline_at is not None:
            starts.append((t.deadline_at - at).total_seconds() - est)
        latest[i] = min(starts) if starts else None

    for i in open_:
        walk(i, frozenset())
    ready = [t for t in open_.values() if t.status == S.ready and (not task_types or t.task_type in set(task_types))]
    ready.sort(key=lambda t: (t.priority, latest[t.id] is None, latest[t.id] or 0.0, -path[t.id], -len(below[t.id]), t.created_at))
    return [(t, {"rank": n + 1, "priority": t.priority, "slack_s": None if latest[t.id] is None else round(latest[t.id], 1),
                 "critical_path_s": round(path[t.id], 1), "unblocks": len(below[t.id])}) for n, t in enumerate(ready)]


def clear_record_inputs(session: Session, t: Task) -> None:
    """A task about to run (again) rebuilds its context, so the records and outputs an earlier run read are no longer
    its inputs. Without this, a record deleted or changed since the earlier run would keep the new run from ever
    completing."""
    session.execute(delete(TaskInput).where(TaskInput.task_id == t.id, TaskInput.ref_kind.in_(["record", "output"])))
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


def _start(session: Session, t: Task, worker: str, agent_id: uuid.UUID | None, lease_seconds: int, why: dict | None = None) -> Task:
    clear_record_inputs(session, t)
    t.attempts = (t.attempts or 0) + 1
    if agent_id is not None:
        t.assigned_agent_id = agent_id
    details = {**({"resumed_from": t.progress.get("checkpoint")} if (t.progress or {}).get("checkpoint") else {}),
               **({"schedule": why} if why else {})}
    transition(session, t, S.running, actor=worker, reason=f"claimed (attempt {t.attempts})", details=details or None)
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
                  tasks: list[Task] | None = None, seq: int | None = None, outputs: list[tuple[TaskOutput, str]] | None = None) -> None:
    """Remember which versions a task's work was based on: live-state records (with the snapshot ``seq`` they were
    read at, so changes that add no version, such as a stock count or a new relationship, are caught too), other
    tasks' results, and other tasks' released outputs (with a label)."""
    if records and seq is None:
        from cie.state.store import current_seq

        seq = current_seq(session, t.tenant_id)
    rows = [("record", nid, v, label, seq) for nid, (v, label) in (records or {}).items()]
    rows += [("task", d.id, d.revision or 0, d.title[:300], None) for d in tasks or []]
    rows += [("output", o.id, o.version, label[:300], None) for o, label in outputs or []]
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
        elif i.ref_kind == "output":  # a released value that has since changed (being revised is not yet a change)
            o = session.get(TaskOutput, i.ref_id)
            if o is None or o.version != i.version:
                out.append({"kind": "output", "id": str(i.ref_id), "label": i.label, "used": i.version, "now": o.version if o else None})
    return out


# ---------------------------------------------------------------------------------------------- outputs
def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def publish_output(session: Session, task_id: uuid.UUID, *, worker: str, key: str, value: Any, summary: str = "",
                   state_refs: list[dict] | None = None) -> tuple[TaskOutput, bool]:
    """A running task releases a named result now, so the tasks that need only this result can start. Returns the
    output and whether its value changed. The same value again changes nothing downstream; a changed value reopens
    or flags only the tasks that used the earlier version (``cie.workflow.routing.route_output``)."""
    t = _held(session, task_id, worker)
    return _release(session, t, key, value, summary, state_refs, by=worker)


def _release(session: Session, t: Task, key: str, value: Any, summary: str, state_refs: list[dict] | None, by: str) -> tuple[TaskOutput, bool]:
    if not key or len(key) > 64:
        raise ValueError("an output key is 1 to 64 characters")
    v = _json(value)
    o = session.scalar(select(TaskOutput).where(TaskOutput.task_id == t.id, TaskOutput.key == key).with_for_update())
    first = o is None
    if first:
        o = TaskOutput(tenant_id=t.tenant_id, task_id=t.id, key=key, version=1, value=v)
        session.add(o)
    changed = first or o.value != v
    if changed and not first:
        o.version, o.value = o.version + 1, v
    o.status, o.summary, o.state_refs = "current", (summary or "")[:4000], state_refs or []
    o.produced_by, o.task_revision, o.updated_at = by[:120], t.revision or 0, now()
    session.flush()
    from cie.workflow.routing import route_output

    route_output(session, t, o, changed=changed, first=first)
    return o, changed


def upstream(session: Session, t: Task, *, record: bool = True) -> list[dict[str, Any]]:
    """What the task's dependencies have handed over: the released outputs it needs (recorded as its inputs, with
    their versions, when ``record``) and the summaries of whole tasks it required."""
    deps = dependencies(session, [t.id])[t.id]
    outs = released(session, [d.task.id for d in deps if d.outputs])
    items, used = [], []
    for dep, kind, names in deps:
        if names:
            for k in names:
                o = outs.get((dep.id, k))
                items.append({"task_id": str(dep.id), "task": dep.title, "output": k, "status": o.status if o else "not released",
                              "version": o.version if o else None, "value": o.value if o else None, "summary": o.summary if o else ""})
                if o is not None and o.status == "current":
                    used.append((o, f"{dep.title[:200]}: {k}"))
        elif kind == "requires" and dep.status == S.completed:
            items.append({"task_id": str(dep.id), "task": dep.title, "status": dep.status.value,
                          "summary": ((dep.result or {}).get("summary") or "")[:1000]})
    if record and used:
        record_inputs(session, t, outputs=used)
    return items


def deliverables(session: Session, t: Task) -> list[dict[str, Any]]:
    """The outputs this task should release, most awaited first: the ones its acceptance declares and the ones other
    tasks wait for, each with who waits and whether it is released."""
    declared = list((t.acceptance or {}).get("outputs") or [])
    waiters: dict[str, list[Task]] = defaultdict(list)
    for d, _kind, names in dependants(session, t.id):
        for k in names:
            waiters[k].append(d)
    outs = released(session, [t.id])
    keys = list(dict.fromkeys(declared + sorted(waiters)))
    rows = []
    for k in keys:
        o = outs.get((t.id, k))
        ws = waiters.get(k, [])
        rows.append({"output": k, "released": o is not None and o.status == "current", "version": o.version if o else None,
                     "waiting": sum(1 for d in ws if d.status in (S.blocked, S.proposed)),
                     "needed_by": [{"task_id": str(d.id), "title": d.title, "status": d.status.value} for d in ws]})
    rows.sort(key=lambda r: (r["released"], -r["waiting"], -len(r["needed_by"]), keys.index(r["output"])))
    return rows


# ---------------------------------------------------------------------------------------------- work requests
def request_depth(t: Task, session: Session) -> int:
    """How many requests deep ``t`` is: 0 for planned work, 1 for a request made by planned work, and so on."""
    d, seen, cur = 0, set(), t
    while (rid := (cur.metrics or {}).get("requested_by_task")) and rid not in seen and d < 50:
        seen.add(rid)
        cur = session.get(Task, uuid.UUID(rid))
        if cur is None:
            break
        d += 1
    return d


def request_work(session: Session, requester_id: uuid.UUID, *, worker: str, task_type: str, title: str, brief: str = "",
                 wait: bool = True, agent_name: str | None = None, block_now: bool = True) -> Task:
    """The running task ``requester_id`` asks another role (``task_type``) for work: a proposed task, answered by
    releasing its ``answer`` output. With ``wait`` the requester depends on the answer and is blocked, its progress
    kept, until it is released (``block_now=False`` leaves the blocking to the caller, after several requests).
    Raises ``ValueError`` past the limits on requests."""
    r = _held(session, requester_id, worker)
    made = list((r.progress or {}).get("requests", []))
    if len(made) >= REQUEST_MAX_PER_TASK:
        raise ValueError(f"a task makes at most {REQUEST_MAX_PER_TASK} work requests")
    depth = request_depth(r, session) + 1
    if depth > REQUEST_MAX_DEPTH:
        raise ValueError(f"requests go at most {REQUEST_MAX_DEPTH} deep")
    who = agent_name or worker
    t = propose(session, tenant_id=r.tenant_id, project_id=r.project_id, scope_id=r.scope_id, task_type=task_type, title=title[:500],
                brief=f"Requested by {who} for the task '{r.title}'. {brief}".strip(), priority=r.priority, risk_level="low",
                acceptance={"outputs": ["answer"]}, deadline_at=r.deadline_at, parent_id=r.id,
                metrics={"requested_by_task": str(r.id), "requested_by": who, "wait": wait, "depth": depth,
                         **({"estimate_seconds": (r.metrics or {})["estimate_seconds"] / 2} if (r.metrics or {}).get("estimate_seconds") else {})},
                actor=who)
    r.progress = {**(r.progress or {}), "requests": made + [{"task_id": str(t.id), "task_type": task_type, "title": title[:300], "wait": wait,
                                                             "status": "proposed"}]}
    if wait:
        add_dependency(session, r, t.id, "requires", ["answer"])
        session.flush()
        if block_now:
            block(session, r.id, worker=worker, reason=f"waiting for the answer of {task_type} to '{title[:200]}'")
    session.flush()
    return t


def decide_request(session: Session, request_id: uuid.UUID, *, decision: str, actor: str, reason: str = "",
                   into: uuid.UUID | None = None) -> Task:
    """The head's or a person's decision on a proposed request: ``accept`` it into the plan, ``merge`` it ``into``
    an equivalent open request (the requester then waits for that one's answer), or ``decline`` it (the requester is
    released and told why)."""
    t = locked(session, request_id)
    rid = (t.metrics or {}).get("requested_by_task")
    if not rid or t.status != S.proposed:
        raise TransitionError(f"task {t.id} is not a request awaiting a decision")
    _request_note(session, t, {"decision": decision, "reason": reason, "by": actor})
    if decision == "accept":
        return accept(session, t, actor=actor)
    if decision == "merge":
        other = session.get(Task, into) if into else None
        if other is None or other.project_id != t.project_id or not (other.metrics or {}).get("requested_by_task") or other.status in SETTLED:
            raise ValueError("a request merges only into an open request of the same project")
        requester = session.get(Task, uuid.UUID(rid))
        if (t.metrics or {}).get("wait") and requester is not None and session.get(TaskDependency, (requester.id, other.id)) is None:
            add_dependency(session, requester, other.id, "requires", ["answer"])
            session.flush()
        return cancel(session, t.id, actor=actor, reason=f"merged into '{other.title}' ({other.id})")
    if decision == "decline":
        return cancel(session, t.id, actor=actor, reason=f"declined: {reason}" if reason else "declined")
    raise ValueError("decision must be accept, merge or decline")


def _request_note(session: Session, t: Task, note: dict[str, Any]) -> None:
    """Update the requester's record of this request."""
    rid = (t.metrics or {}).get("requested_by_task")
    requester = session.get(Task, uuid.UUID(rid)) if rid else None
    if requester is None:
        return
    reqs = [({**x, **note} if x.get("task_id") == str(t.id) else x) for x in (requester.progress or {}).get("requests", [])]
    requester.progress = {**(requester.progress or {}), "requests": reqs}


def _request_settled(session: Session, t: Task, reason: str) -> None:
    """A requested task ended. Completed: the requester has its answer. Failed or cancelled: the requester stops
    waiting for it (the dependency is removed) and its agent is told why."""
    requester = session.get(Task, uuid.UUID(t.metrics["requested_by_task"]))
    if requester is None:
        return
    _request_note(session, t, {"status": t.status.value, **({"reason": reason} if t.status != S.completed else {})})
    if t.status == S.completed:
        return
    session.execute(delete(TaskDependency).where(TaskDependency.task_id == requester.id, TaskDependency.depends_on_id == t.id))
    session.flush()
    refresh(session, task_ids=[requester.id], actor="requests")
    if requester.assigned_agent_id:
        from cie.agents import messages
        from cie.core.models import Agent, MessageKind

        agent = session.get(Agent, requester.assigned_agent_id)
        if agent is not None:
            messages.send(session, tenant_id=requester.tenant_id, project_id=requester.project_id, kind=MessageKind.work_decision,
                          task_id=requester.id, to_agent=agent,
                          payload={"task_id": str(requester.id), "request_task_id": str(t.id), "decision": t.status.value,
                                   "reason": reason[:500]})


def output_gaps(session: Session, t: Task) -> list[str]:
    """Outputs the task has not (re-)released: declared in its acceptance but missing, or left ``revising`` after
    it was reopened (re-release them, even unchanged, so the tasks waiting on them can go on)."""
    outs = {k: o for (_, k), o in released(session, [t.id]).items()}
    gaps = [f"output '{k}' not released" for k in (t.acceptance or {}).get("outputs") or [] if k not in outs]
    return gaps + [f"output '{k}' not re-released since the task was reopened" for k, o in sorted(outs.items()) if o.status == "revising"]


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
    for key, v in (result.get("outputs") or {}).items():  # outputs in the result are released now, if not already
        spec = v if isinstance(v, dict) and "value" in v else {"value": v}
        _release(session, t, key, spec["value"], spec.get("summary", ""), spec.get("state_refs"), by=worker)
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
    missing = check_acceptance(t, result) + output_gaps(session, t)
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
    refresh(session, task_ids=[d.task.id for d in deps], actor="engine")
    for d, *_ in deps:
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
    waiting = waiting_for(session, [t.id])[t.id]
    return transition(session, t, S.blocked if waiting else S.ready, actor=str(authorized_by), reason=f"retry authorised: {reason}".strip(": "))


def cancel(session: Session, task_id: uuid.UUID, *, actor: str, reason: str) -> Task:
    t = locked(session, task_id)
    return transition(session, t, S.cancelled, actor=actor, reason=reason)


def reopen(session: Session, task_id: uuid.UUID, *, actor: str, reason: str, details: dict | None = None,
           _seen: set | None = None) -> list[Task]:
    """completed -> ready because an input changed. Dependants that required the whole task are reopened (if
    completed) or blocked (if waiting). Its released outputs become ``revising``: dependants that need only those
    outputs and have not started wait; the ones that used them are disturbed only if a changed value is released.
    Returns every task reopened or blocked."""
    seen = _seen if _seen is not None else set()
    if task_id in seen:
        return []
    seen.add(task_id)
    t = locked(session, task_id)
    if t.status != S.completed:
        return []
    t.progress = {**(t.progress or {}), "reopened": {"reason": reason, "details": details or {}, "at": now().isoformat()}}
    t.review_rounds = 0
    waiting = waiting_for(session, [t.id])[t.id]
    out = [transition(session, t, S.blocked if waiting else S.ready, actor=actor, reason=reason, details=details)]
    for o in session.scalars(select(TaskOutput).where(TaskOutput.task_id == t.id)):
        o.status = "revising"
    session.flush()
    for d, kind, names in dependants(session, t.id):
        if kind != "requires":
            continue
        if names:  # waits only for the named outputs: not started yet -> waits for them to be re-released
            if d.status == S.ready:
                out.append(transition(session, d, S.blocked, actor=actor, reason=f"'{t.title}' is revising {', '.join(names)}"))
        elif d.status == S.completed:
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


