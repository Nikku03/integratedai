"""The action gateway: nothing acts on an external system without passing these checks, and every check is recorded
on the action.

**Proposing** (``propose``):
1. *Idempotency.* The key (given, or derived from the task, kind, target and payload) is unique per tenant: the same
   action proposed twice is one action.
2. *Permission.* An agent may propose only the action kinds granted to it (``Agent.config["actions"]``). A person
   needs write access to the project (checked by the API).
3. *Approval.* A person must approve when the kind always needs one (``CIE_ACTIONS_ALWAYS_APPROVE``: payments,
   contract signatures and external messages by default), or when the amount is above the agent's authority for
   ``authority_kind`` (``Agent.config["authority"]``). Otherwise it is approved as proposed.

**Executing** (``execute``, run by the worker for approved actions, or through the API):
4. *Permission again*, in case the grant was withdrawn.
5. *Freshness.* The live-state records it rests on must still be at the versions it was based on, and the task that
   proposed it still completed at the same revision (not reopened). Otherwise it is ``stale`` and not executed.
6. *Already executed.* An action executed before is not executed again. The status is committed as ``executing``
   before the connector is called, so after a crash the next attempt first asks the connector whether it went
   through, and the connector gets the idempotency key either way.
7. *Result confirmed.* After executing, the connector reads back what the other side holds: ``confirmed`` or
   ``unconfirmed`` (the receipt is kept; a person should look).

A task proposes actions by listing them in its result (``actions``); they are proposed when the task completes,
with the records its result relied on as their basis.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.actions.connectors import ActionConnector
from cie.actions.models import Action
from cie.core.models import Agent, Approval, Task, TaskStatus
from cie.core.util import utcnow


def _check(a: Action, name: str, ok: bool, detail: str) -> bool:
    a.checks = list(a.checks or []) + [{"check": name, "ok": bool(ok), "detail": detail[:500], "at": utcnow().isoformat()}]
    return ok


def default_key(task_id: uuid.UUID | None, kind: str, target: str, payload: dict[str, Any], proposer: str = "") -> str:
    body = json.dumps({"task": str(task_id) if task_id else None, "kind": kind, "target": target, "payload": payload, "by": proposer},
                      sort_keys=True, default=str)
    return "act-" + hashlib.sha256(body.encode()).hexdigest()[:40]


def _covers(limit: Any, amount: float | None) -> bool:
    return limit is True or (isinstance(limit, (int, float)) and not isinstance(limit, bool) and amount is not None and amount <= limit)


def _record(session: Session, a: Action, what: str, actor: str) -> None:
    from cie.agents import ledger
    from cie.governance.audit import audit

    if a.project_id:
        ledger.append(session, tenant_id=a.tenant_id, project_id=a.project_id, kind="decision",
                      content={"action_id": str(a.id), "kind": a.kind, "target": a.target, "status": a.status, "what": what}, actor=actor[:100])
    audit(session, tenant_id=a.tenant_id, principal_id=a.principal_id, action=f"action.{what}", resource_kind="action", resource_id=a.id,
          details={"kind": a.kind, "target": a.target, "status": a.status})


def propose(session: Session, *, tenant_id: uuid.UUID, kind: str, target: str, payload: dict[str, Any], requested_by: str,
            agent: Agent | None = None, principal_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None, task: Task | None = None,
            amount: float | None = None, authority_kind: str = "spend_usd", records: list[dict[str, Any]] | None = None,
            idempotency_key: str | None = None, settings=None) -> Action:
    """Propose an action: the idempotency, permission and approval checks (see the module docstring)."""
    from cie.core.settings import get_settings

    settings = settings or get_settings()
    key = idempotency_key or default_key(task.id if task else None, kind, target, payload, requested_by)
    basis = {"records": [{"ref": str(r["ref"]), "version": int(r["version"]), **({"label": r["label"]} if r.get("label") else {})}
                         for r in records or [] if r.get("ref") is not None and r.get("version") is not None],
             **({"task": {"id": str(task.id), "revision": task.revision}} if task else {})}
    a = session.scalar(select(Action).where(Action.tenant_id == tenant_id, Action.idempotency_key == key).with_for_update())
    if a is not None and a.status not in ("refused", "stale"):
        _check(a, "idempotency", True, f"proposed again by {requested_by}: the same action, not a new one")
        return a  # awaiting, approved, executed or decided by a person: it stands
    if a is not None:  # refused (a grant may have been given since) or stale (a new basis): checked again as proposed now
        _check(a, "idempotency", True, f"proposed again by {requested_by} after it was {a.status}: checked again")
        a.status, a.based_on, a.amount, a.approval_id = "awaiting_approval", basis, amount, None
        a.authority_kind = authority_kind if amount is not None else None
    else:
        a = Action(tenant_id=tenant_id, project_id=project_id or (task.project_id if task else None), task_id=task.id if task else None,
                   kind=kind, target=target, payload=payload, idempotency_key=key, status="awaiting_approval", requested_by=requested_by[:120],
                   agent_id=agent.id if agent else None, principal_id=principal_id or (agent.principal_id if agent else None), amount=amount,
                   authority_kind=authority_kind if amount is not None else None, checks=[], attempts=0, based_on=basis)
        a.id = uuid.uuid4()
        session.add(a)
        _check(a, "idempotency", True, f"key {key}")
    if agent is not None:
        allowed = list((agent.config or {}).get("actions") or [])
        if not _check(a, "permission", kind in allowed or "*" in allowed,
                      f"{agent.name} may propose {', '.join(allowed) or 'no actions'}"):
            a.status = "refused"
            session.flush()
            _record(session, a, "refused", requested_by)
            return a
    else:
        _check(a, "permission", True, f"proposed by {requested_by}, with write access to the project")
    needs = []
    if kind in (settings.actions_always_approve or []):
        needs.append(f"'{kind}' always needs a person's approval")
    if agent is not None and amount is not None:
        limit = ((agent.config or {}).get("authority") or {}).get(authority_kind)
        if not _covers(limit, amount):
            needs.append(f"{amount:g} is above {agent.name}'s {authority_kind} authority ({limit if limit is not None else 'none'})")
    if needs:
        _check(a, "approval", False, "; ".join(needs))
        ap = Approval(tenant_id=tenant_id, kind="action", subject_id=str(a.id), requested_by=requested_by[:100],
                      summary=f"{requested_by} proposes {kind} via {target}: {json.dumps(payload, default=str)[:600]}. " + "; ".join(needs))
        session.add(ap)
        session.flush()
        a.approval_id = ap.id
    else:
        a.status = "approved"
        _check(a, "approval", True, "within the proposer's permission and authority")
    session.flush()
    _record(session, a, "proposed", requested_by)
    if a.status == "approved":
        enqueue(session, a)
    return a


def decide(session: Session, action_id: uuid.UUID, *, approve: bool, by: str, reason: str = "") -> Action:
    """A person's decision on an action awaiting approval."""
    a = session.get(Action, action_id, with_for_update=True)
    if a is None or a.status != "awaiting_approval":
        raise ValueError("no action awaiting approval")
    a.status = "approved" if approve else "rejected"
    _check(a, "approval", approve, f"{'approved' if approve else 'rejected'} by {by}: {reason}")
    session.flush()
    _record(session, a, a.status, by)
    if approve:
        enqueue(session, a)
    return a


def enqueue(session: Session, a: Action) -> None:
    from cie.workers import queue

    queue.enqueue(session, a.tenant_id, "execute_action", {"action_id": str(a.id)})


def freshness(session: Session, a: Action) -> list[str]:
    """What moved on since the action was based on it: records at a new version (or gone), or its task reopened."""
    from cie.state.models import RemNodeVersion

    out = []
    recs = (a.based_on or {}).get("records") or []
    if recs:
        cur = dict(session.execute(select(RemNodeVersion.node_id, RemNodeVersion.version).where(
            RemNodeVersion.node_id.in_([uuid.UUID(r["ref"]) for r in recs]), RemNodeVersion.sys_to.is_(None))).all())
        for r in recs:
            now_v = cur.get(uuid.UUID(r["ref"]))
            if now_v != r["version"]:
                out.append(f"{r.get('label') or r['ref']} is at version {now_v if now_v is not None else 'none (deleted)'}, not {r['version']}")
    tk = (a.based_on or {}).get("task")
    if tk:
        t = session.get(Task, uuid.UUID(tk["id"]))
        if t is None or t.status != TaskStatus.completed or t.revision != tk["revision"]:
            out.append(f"the task that proposed it is {t.status.value if t else 'gone'} at revision {t.revision if t else '-'}, "
                       f"not completed at {tk['revision']}")
    return out


def execute(session: Session, action_id: uuid.UUID, *, connectors: dict[str, ActionConnector], actor: str) -> Action:
    """Carry out an approved action: the permission, freshness, already-executed and confirmation checks (see the
    module docstring). Commits before calling the connector."""
    a = session.get(Action, action_id, with_for_update=True, populate_existing=True)
    if a is None:
        raise ValueError("no such action")
    if a.status in ("executed", "confirmed", "unconfirmed"):
        _check(a, "already_executed", True, f"asked again by {actor}: not executed twice")
        return a
    if a.status not in ("approved", "failed", "executing"):
        raise ValueError(f"the action is {a.status}; only an approved action is executed")
    conn = connectors.get(a.target)
    if not _check(a, "connector", conn is not None, f"connector '{a.target}'" + ("" if conn else " is not configured")):
        a.status, a.error = "failed", f"no connector '{a.target}'"
        session.flush()
        return a
    if a.agent_id is not None:
        agent = session.get(Agent, a.agent_id)
        allowed = list((agent.config or {}).get("actions") or []) if agent else []
        if not _check(a, "permission", agent is not None and agent.active and (a.kind in allowed or "*" in allowed),
                      "the proposing agent still holds the grant" if agent else "the proposing agent is gone"):
            a.status = "refused"
            session.flush()
            _record(session, a, "refused", actor)
            return a
    stale = freshness(session, a)
    if not _check(a, "freshness", not stale, "; ".join(stale) or "every record and the task are as they were"):
        a.status = "stale"
        session.flush()
        _record(session, a, "stale", actor)
        return a
    if a.status == "executing":  # an earlier attempt may have gone through before it could record that
        ok, detail = conn.confirm(a)
        if _check(a, "already_executed", ok, f"earlier attempt: {detail}"):
            a.status, a.confirmed_at = "confirmed", utcnow()
            session.flush()
            _record(session, a, "confirmed", actor)
            return a
    a.status, a.attempts, a.error = "executing", (a.attempts or 0) + 1, ""
    session.commit()  # recorded before the other side is touched
    try:
        receipt = conn.execute(a)
    except Exception as e:  # noqa: BLE001 - any connector failure: retried with the same key
        a.status, a.error = "failed", str(e)[:2000]
        _check(a, "executed", False, a.error)
        session.flush()
        _record(session, a, "failed", actor)
        return a
    a.receipt, a.status, a.executed_at = receipt or {}, "executed", utcnow()
    _check(a, "executed", True, json.dumps(receipt, default=str)[:400])
    ok, detail = conn.confirm(a)
    a.status = "confirmed" if ok else "unconfirmed"
    if ok:
        a.confirmed_at = utcnow()
    _check(a, "confirmed", ok, detail)
    session.flush()
    _record(session, a, a.status, actor)
    return a


def propose_from_result(session: Session, t: Task) -> list[Action]:
    """A completed task's result listed actions: propose each, by its agent, based on the records its result
    relied on and on the task's revision."""
    from cie.workflow import engine

    specs = [x for x in (t.result or {}).get("actions") or [] if isinstance(x, dict) and x.get("kind")]
    if not specs:
        return []
    agent = session.get(Agent, t.assigned_agent_id) if t.assigned_agent_id else None
    relied = engine.relied_on(session, t, t.result or {})
    records = [{"ref": str(nid), "version": v, "label": label} for nid, (v, label) in relied.items()]
    out = []
    for x in specs[:10]:
        out.append(propose(session, tenant_id=t.tenant_id, kind=str(x["kind"])[:64], target=str(x.get("target") or "outbox")[:64],
                           payload=x.get("payload") if isinstance(x.get("payload"), dict) else {"value": x.get("payload")},
                           requested_by=agent.name if agent else (t.lease_owner or "task"), agent=agent, task=t,
                           amount=engine._amount(x.get("amount")), authority_kind=str(x.get("authority_kind") or "spend_usd"),
                           records=records))
    return out
