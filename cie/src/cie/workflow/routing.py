"""Routing state changes to the tasks they affect.

After an event is applied, every task that used a changed, deleted or restricted record (``task_inputs``) is
handled according to its status:

* completed: reopened (and its dependants with it), because its result rests on a value that changed;
* running or in review: flagged, and its agent is told. The engine will not complete it on the old version;
* anything else: noted, because it will read current values when it runs.

Each (task, record, new version) is handled once (``task_invalidations`` is unique on it), so a re-delivered event
or a retried job never reopens a task twice. Messages carry record ids and versions only, never values.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from cie.core.models import Agent, MessageKind, Task, TaskStatus
from cie.state.models import RemNode, RemNodeVersion
from cie.workflow import engine
from cie.workflow.models import TaskInput, TaskInvalidation

S = TaskStatus


def route_to_tasks(session: Session, cs) -> dict[str, Any]:
    ev = cs.event
    ids = set(cs.changed) | set(cs.deleted) | set(cs.restricted)
    if not ids:
        return {}
    uses = session.execute(select(TaskInput, Task).join(Task, Task.id == TaskInput.task_id).where(
        TaskInput.tenant_id == ev.tenant_id, TaskInput.ref_kind == "record", TaskInput.ref_id.in_(ids))).all()
    if not uses:
        return {}
    now = dict(session.execute(select(RemNodeVersion.node_id, RemNodeVersion.version).where(
        RemNodeVersion.node_id.in_({u.ref_id for u, _ in uses}), RemNodeVersion.sys_to.is_(None))).all())
    labels = {n.id: f"{n.type}:{n.key}" for n in session.scalars(select(RemNode).where(RemNode.id.in_({u.ref_id for u, _ in uses})))}
    out: dict[str, list[str]] = {"reopened": [], "flagged": [], "noted": []}
    for use, t in uses:
        new_version = 0 if use.ref_id in cs.deleted else int(now.get(use.ref_id, 0))
        if new_version == use.version:
            continue
        what = labels.get(use.ref_id, str(use.ref_id))
        if t.status == S.completed:
            action = "reopened"
        elif t.status in (S.running, S.review):
            action = "flagged"
        elif t.status in (S.failed, S.cancelled):
            continue
        else:
            action = "noted"
        row = session.execute(insert(TaskInvalidation).values(
            id=uuid.uuid4(), tenant_id=ev.tenant_id, task_id=t.id, ref_id=use.ref_id, from_version=use.version, to_version=new_version,
            event_id=ev.id, seq=cs.seq, action=action).on_conflict_do_nothing(constraint="uq_task_invalidation").returning(TaskInvalidation.id)).first()
        if row is None:
            continue  # already handled for this version
        change = f"{what} changed (version {use.version} -> {new_version or 'deleted'}) at seq {cs.seq}"
        details = {"record": str(use.ref_id), "label": what, "from_version": use.version, "to_version": new_version,
                   "event_id": str(ev.id), "seq": cs.seq}
        if action == "reopened":
            from cie.agents.publication import withdraw

            for x in engine.reopen(session, t.id, actor="events", reason=change, details=details):
                withdraw(session, x.id, change)  # its published findings are disputed until it completes again
        elif action == "flagged":
            t.progress = {**(t.progress or {}), "stale_inputs": list((t.progress or {}).get("stale_inputs", []))[-19:] + [details]}
        _tell(session, t, what, use, new_version, action)
        out[action].append(str(t.id))
    return {k: v for k, v in out.items() if v}


def _tell(session: Session, t: Task, what: str, use: TaskInput, new_version: int, action: str) -> None:
    from cie.agents import ledger, messages

    agent = session.get(Agent, t.assigned_agent_id) if t.assigned_agent_id else None
    if agent is not None:
        messages.send(session, tenant_id=t.tenant_id, project_id=t.project_id, kind=MessageKind.input_changed, task_id=t.id, to_agent=agent,
                      payload={"task_id": str(t.id), "record": str(use.ref_id), "label": what, "from_version": use.version,
                               "to_version": new_version, "action": action})
    if action == "reopened":
        ledger.append(session, tenant_id=t.tenant_id, project_id=t.project_id, kind="decision",
                      content={"task_id": str(t.id), "decision": "reopened", "reason": f"input {what} changed",
                               "from_version": use.version, "to_version": new_version}, actor="events")
