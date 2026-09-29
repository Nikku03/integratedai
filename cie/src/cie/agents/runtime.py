"""Queue integration: run a project's head, or an agent's own turn, as a durable job.

**An agent's turn** (``run_agent_turn``, job ``agent_turn``, or ``python -m cie.cli agents``): the agent works on its
own, without waiting for the head to run.
1. Answers that arrived for tasks it already completed reopen those tasks, so it reconsiders with the answer.
2. It claims the next ready task it can do, in schedule order, across the tenant's projects (never the head's
   planning, verification or synthesis).
3. It runs the task exactly as the head would: its messages, context, evidence round, requests to other agents,
   questions, decisions within its authority, released results and proposed actions.
""" 

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from cie.agents.head import HeadAgent
from cie.agents.providers import get_provider
from cie.core.models import Job, Project
from cie.memory.embeddings import get_embedding_provider


def run_task_job(session: Session, job: Job) -> dict:
    project = session.get(Project, uuid.UUID(job.payload["project_id"]))
    if project is None:
        raise RuntimeError("project not found")
    provider = get_provider()
    head = HeadAgent(session, project, embedder=get_embedding_provider(), provider=provider if provider.name != "none" else None)
    if job.payload.get("objective") and not (job.checkpoint or {}).get("started"):
        head.start(job.payload["objective"])
        job.checkpoint = {**(job.checkpoint or {}), "started": True}
        session.commit()
    state = head.run(max_steps=int(job.payload.get("max_steps", 20)))
    return {"entries": state["entries"], "synthesis": bool(state["synthesis"]), "contradictions": len(state["contradictions"])}


HEAD_WORK = ("plan", "synthesis", "verification")


def run_agent_turn(session: Session, agent, *, provider=None, embedder=None) -> dict:
    """One turn of ``agent`` working on its own (see the module docstring). Returns what it did."""
    from sqlalchemy import select

    from cie.agents import messages
    from cie.core.models import MessageKind, Task, TaskStatus
    from cie.workflow import engine

    reopened = []
    for m in messages.inbox(session, agent, kinds=[MessageKind.answer], unread_only=True):
        t = session.get(Task, m.task_id) if m.task_id else None
        if t is not None and t.status == TaskStatus.completed and t.assigned_agent_id == agent.id:
            engine.reopen(session, t.id, actor=agent.name, reason="an answer to its question arrived after it completed")
            reopened.append(str(t.id))  # the answer stays unread: it is delivered when the task runs again
    kinds = [k for k in (agent.task_types or []) if k not in HEAD_WORK]
    if not kinds or agent.role == "head":
        return {"agent": agent.name, "reopened": reopened, "task_id": None}
    for pid in list(session.scalars(select(Task.project_id).where(Task.tenant_id == agent.tenant_id, Task.status == TaskStatus.blocked)
                                   .distinct())):
        engine.refresh(session, project_id=pid, actor=agent.name)  # whatever its dependencies released meanwhile
    worker = f"agent:{agent.name}"
    t = engine.claim(session, agent.tenant_id, worker=worker, agent_id=agent.id, task_types=kinds)
    if t is None:
        return {"agent": agent.name, "reopened": reopened, "task_id": None}
    project = session.get(Project, t.project_id)
    if provider is None:
        p = get_provider()
        provider = p if p.name != "none" else None
    head = HeadAgent(session, project, embedder=embedder or get_embedding_provider(), provider=provider, worker=worker)
    head.run_claimed(t, agent)
    head.review_requests()  # what it asked of others is decided now, so they can start
    return {"agent": agent.name, "reopened": reopened, "task_id": str(t.id), "status": t.status.value}


def run_agents(session: Session, tenant_id: uuid.UUID, *, max_turns: int = 50, provider=None, embedder=None, log=print) -> list[dict]:
    """Every active agent takes turns until none has anything to do (or ``max_turns`` is reached)."""
    from cie.agents.registry import agents_for_tenant

    done = []
    while len(done) < max_turns:
        busy = False
        for a in agents_for_tenant(session, tenant_id):
            r = run_agent_turn(session, a, provider=provider, embedder=embedder)
            session.commit()
            if r["task_id"] or r["reopened"]:
                busy = True
                done.append(r)
                log(r)
            if len(done) >= max_turns:
                break
        if not busy:
            break
    return done


def run_agent_job(session: Session, job: Job) -> dict:
    from cie.core.models import Agent

    agent = session.get(Agent, uuid.UUID(job.payload["agent_id"]))
    if agent is None or not agent.active:
        return {"agent": None}
    return run_agent_turn(session, agent)
