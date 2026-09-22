"""Agent routes: projects, tasks, agents, scorecards, routing, messages,
verification, ledger, final answer."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.agents import ledger
from cie.agents.head import HeadAgent, create_project
from cie.agents.providers import get_provider
from cie.agents.registry import agents_for_tenant, ensure_default_agents
from cie.agents.router import select_agent
from cie.agents.scorecards import Outcome, record_outcome, scorecards_for
from cie.agents.verification import verify_result
from cie.api.deps import Auth, current_auth, db, require_scope_read, require_scope_write
from cie.core.models import (
    Agent,
    AgentMessage,
    Principal,
    PrincipalKind,
    Project,
    Scope,
    Task,
    TaskDependency,
    TaskStatus,
)
from cie.governance.audit import audit
from cie.memory.embeddings import get_embedding_provider
from cie.workers import queue

router = APIRouter()


class ProjectIn(BaseModel):
    name: str
    parent_scope_id: uuid.UUID
    objective: str = ""


class RunIn(BaseModel):
    objective: str
    max_steps: int = 20
    background: bool = False


class TaskIn(BaseModel):
    project_id: uuid.UUID
    task_type: str
    title: str
    brief: str = ""
    risk_level: str = "low"
    priority: int = 5
    depends_on: list[uuid.UUID] = Field(default_factory=list)


class AgentIn(BaseModel):
    name: str
    role: str
    skills: list[str] = Field(default_factory=list)
    task_types: list[str] = Field(default_factory=list)
    strategy: str = "extractive"
    model: str | None = None
    cost_per_1k_tokens: float = 0.0
    max_concurrency: int = 2


class MessageIn(BaseModel):
    project_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    to_agent: str
    from_agent: str | None = None
    task_id: uuid.UUID | None = None


class OutcomeIn(BaseModel):
    task_type: str
    accuracy: float | None = None
    citation_quality: float | None = None
    completed: bool = True
    human_corrections: int = 0
    hallucinated: bool = False


def _proj(session: Session, auth: Auth, project_id: uuid.UUID) -> Project:
    p = session.get(Project, project_id)
    if p is None or p.tenant_id != auth.tenant_id:
        raise HTTPException(404, "project not found")
    require_scope_read(auth, p.scope_id)
    return p


def _task_out(t: Task, session: Session) -> dict[str, Any]:
    agent = session.get(Agent, t.assigned_agent_id) if t.assigned_agent_id else None
    deps = [str(d.depends_on_id) for d in session.scalars(select(TaskDependency).where(TaskDependency.task_id == t.id))]
    return {"id": str(t.id), "project_id": str(t.project_id), "task_type": t.task_type, "title": t.title, "brief": t.brief,
            "status": t.status.value, "priority": t.priority, "risk_level": t.risk_level, "assigned_agent": agent.name if agent else None,
            "assignment_reason": t.assignment_reason, "evidence_packet_id": str(t.evidence_packet_id) if t.evidence_packet_id else None,
            "result": t.result, "verification": t.verification, "verifies_task_id": str(t.verifies_task_id) if t.verifies_task_id else None,
            "metrics": t.metrics, "depends_on": deps, "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat()}


# ---------------------------------------------------------------- projects
@router.post("/projects")
def create_project_route(body: ProjectIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    require_scope_write(auth, body.parent_scope_id)
    parent = session.get(Scope, body.parent_scope_id)
    p = create_project(session, tenant_id=auth.tenant_id, parent_scope=parent, name=body.name, objective=body.objective)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="project.create", resource_kind="project", resource_id=p.id)
    return {"id": str(p.id), "scope_id": str(p.scope_id), "name": p.name, "objective": p.objective, "status": p.status}


@router.get("/projects")
def list_projects(auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    rows = session.scalars(select(Project).where(Project.tenant_id == auth.tenant_id).order_by(Project.created_at.desc()))
    return [{"id": str(p.id), "scope_id": str(p.scope_id), "name": p.name, "objective": p.objective, "status": p.status,
             "head_agent_id": str(p.head_agent_id) if p.head_agent_id else None, "token_budget": p.token_budget}
            for p in rows if p.scope_id in auth.visibility.scope_ids]


@router.get("/projects/{project_id}")
def get_project(project_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    p = _proj(session, auth, project_id)
    tasks = list(session.scalars(select(Task).where(Task.project_id == p.id).order_by(Task.priority, Task.created_at)))
    return {"id": str(p.id), "scope_id": str(p.scope_id), "name": p.name, "objective": p.objective, "status": p.status,
            "tasks": [_task_out(t, session) for t in tasks], "ledger": ledger.state(session, p.id)}


@router.post("/projects/{project_id}/run")
def run_project(project_id: uuid.UUID, body: RunIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    p = _proj(session, auth, project_id)
    require_scope_write(auth, p.scope_id)
    if not agents_for_tenant(session, auth.tenant_id):
        company = session.scalar(select(Scope).where(Scope.tenant_id == auth.tenant_id, Scope.parent_id.is_(None)))
        ensure_default_agents(session, auth.tenant_id, company)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="project.run", resource_kind="project",
          resource_id=p.id, details={"objective": body.objective, "background": body.background})
    if body.background:
        job = queue.enqueue(session, auth.tenant_id, "agent_task", {"project_id": str(p.id), "objective": body.objective, "max_steps": body.max_steps})
        return {"job_id": str(job.id), "status": "queued"}
    provider = get_provider()
    head = HeadAgent(session, p, embedder=get_embedding_provider(), provider=provider if provider.name != "none" else None)
    head.start(body.objective)
    state = head.run(max_steps=body.max_steps)
    return {"project_id": str(p.id), "status": p.status, "ledger": state}


@router.post("/projects/{project_id}/step")
def step_project(project_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    p = _proj(session, auth, project_id)
    require_scope_write(auth, p.scope_id)
    head = HeadAgent(session, p, embedder=get_embedding_provider())
    rep = head.step()
    return {"ran": [str(x) for x in rep.ran], "blocked": rep.blocked, "done": rep.done, "conflicts": rep.conflicts, "verifications": rep.verifications}


@router.get("/projects/{project_id}/ledger")
def project_ledger(project_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    p = _proj(session, auth, project_id)
    ok, bad = ledger.verify_chain(session, p.id)
    return {"chain_valid": ok, "first_bad_seq": bad, "state": ledger.state(session, p.id),
            "entries": [{"seq": e.seq, "kind": e.kind, "label": e.label, "content": e.content, "refs": e.refs, "actor": e.actor,
                         "hash": e.hash, "prev_hash": e.prev_hash, "created_at": e.created_at.isoformat()} for e in ledger.entries(session, p.id)]}


class LedgerIn(BaseModel):
    kind: str
    content: dict[str, Any]
    label: str | None = None
    refs: dict[str, Any] = Field(default_factory=dict)


@router.post("/projects/{project_id}/ledger")
def append_ledger(project_id: uuid.UUID, body: LedgerIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    p = _proj(session, auth, project_id)
    require_scope_write(auth, p.scope_id)
    try:
        e = ledger.append(session, tenant_id=auth.tenant_id, project_id=p.id, kind=body.kind, content=body.content, label=body.label,
                          refs=body.refs, actor=f"user:{auth.principal.name}")
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return {"seq": e.seq, "hash": e.hash}


@router.get("/projects/{project_id}/final-answer")
def final_answer(project_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    p = _proj(session, auth, project_id)
    st = ledger.state(session, p.id)
    if st["synthesis"] is None:
        raise HTTPException(404, "no synthesis yet")
    return st["synthesis"]


# ---------------------------------------------------------------- tasks
@router.post("/tasks")
def create_task(body: TaskIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    p = _proj(session, auth, body.project_id)
    require_scope_write(auth, p.scope_id)
    t = Task(tenant_id=auth.tenant_id, project_id=p.id, scope_id=p.scope_id, task_type=body.task_type, title=body.title, brief=body.brief,
             status=TaskStatus.blocked if body.depends_on else TaskStatus.pending, priority=body.priority, risk_level=body.risk_level,
             metrics={"query": body.title})
    session.add(t)
    session.flush()
    for d in body.depends_on:
        session.add(TaskDependency(task_id=t.id, depends_on_id=d))
    ledger.append(session, tenant_id=auth.tenant_id, project_id=p.id, kind="task",
                  content={"task_id": str(t.id), "type": t.task_type, "title": t.title, "risk": t.risk_level, "status": t.status.value},
                  actor=f"user:{auth.principal.name}")
    return _task_out(t, session)


@router.get("/tasks")
def list_tasks(project_id: uuid.UUID | None = None, status: str | None = None, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    stmt = select(Task).where(Task.tenant_id == auth.tenant_id)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == TaskStatus(status))
    rows = session.scalars(stmt.order_by(Task.created_at.desc()).limit(500))
    return [_task_out(t, session) for t in rows if t.scope_id is None or t.scope_id in auth.visibility.scope_ids]


@router.get("/tasks/{task_id}")
def get_task(task_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    t = session.get(Task, task_id)
    if t is None or t.tenant_id != auth.tenant_id:
        raise HTTPException(404, "task not found")
    _proj(session, auth, t.project_id)
    return _task_out(t, session)


@router.post("/tasks/{task_id}/route", summary="Explain which agent would get this task and why")
def route_task(task_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    t = session.get(Task, task_id)
    if t is None or t.tenant_id != auth.tenant_id:
        raise HTTPException(404, "task not found")
    _proj(session, auth, t.project_id)
    agent, reason = select_agent(session, t, agents_for_tenant(session, auth.tenant_id))
    return {"chosen": agent.name if agent else None, "reason": reason}


@router.post("/tasks/{task_id}/verify")
def verify_task(task_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    t = session.get(Task, task_id)
    if t is None or t.tenant_id != auth.tenant_id:
        raise HTTPException(404, "task not found")
    _proj(session, auth, t.project_id)
    verdict = verify_result(session, t.result or {})
    t.verification = {**(t.verification or {}), "by": f"user:{auth.principal.name}", **verdict.as_dict()}
    if verdict.passed and t.status in (TaskStatus.done, TaskStatus.needs_verification):
        t.status = TaskStatus.verified
    ledger.append(session, tenant_id=auth.tenant_id, project_id=t.project_id, kind="verification",
                  content={"task_id": str(t.id), "verifier": auth.principal.name, "verdict": "passed" if verdict.passed else "failed",
                           "score": verdict.score, "failed": verdict.failed}, actor=f"user:{auth.principal.name}")
    return verdict.as_dict()


# ---------------------------------------------------------------- agents
@router.post("/agents")
def register_agent(body: AgentIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    if not auth.visibility.is_admin:
        raise HTTPException(403, "admin only")
    from cie.core.models import Permission
    from cie.governance.permissions import ensure_role, grant_role
    from cie.memory.scopes import create_scope

    company = session.scalar(select(Scope).where(Scope.tenant_id == auth.tenant_id, Scope.parent_id.is_(None)))
    principal = Principal(tenant_id=auth.tenant_id, kind=PrincipalKind.agent, name=f"agent:{body.name}", attributes={"role": body.role})
    session.add(principal)
    session.flush()
    scope = create_scope(session, auth.tenant_id, "agent", f"agent:{body.name}", company)
    grant_role(session, tenant_id=auth.tenant_id, principal=principal, role=ensure_role(session, auth.tenant_id, "agent_reader", Permission.read, 2), scope=company)
    a = Agent(tenant_id=auth.tenant_id, principal_id=principal.id, name=body.name, role=body.role, skills=body.skills, task_types=body.task_types,
              strategy=body.strategy, model=body.model, cost_per_1k_tokens=body.cost_per_1k_tokens, max_concurrency=body.max_concurrency,
              memory_scope_id=scope.id)
    session.add(a)
    session.flush()
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="agent.register", resource_kind="agent", resource_id=a.id)
    return _agent_out(a)


def _agent_out(a: Agent) -> dict[str, Any]:
    return {"id": str(a.id), "name": a.name, "role": a.role, "skills": a.skills, "task_types": a.task_types, "strategy": a.strategy,
            "model": a.model, "cost_per_1k_tokens": a.cost_per_1k_tokens, "max_concurrency": a.max_concurrency, "active": a.active,
            "principal_id": str(a.principal_id), "memory_scope_id": str(a.memory_scope_id) if a.memory_scope_id else None}


@router.get("/agents")
def list_agents(auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    agents = agents_for_tenant(session, auth.tenant_id, active_only=False)
    if not agents:
        company = session.scalar(select(Scope).where(Scope.tenant_id == auth.tenant_id, Scope.parent_id.is_(None)))
        if company is not None and auth.visibility.is_admin:
            agents = list(ensure_default_agents(session, auth.tenant_id, company).values())
    running = {a.id: session.scalar(select(Task.id).where(Task.assigned_agent_id == a.id, Task.status.in_([TaskStatus.running, TaskStatus.assigned])).limit(1)) for a in agents}
    return [{**_agent_out(a), "busy": running[a.id] is not None} for a in agents]


@router.get("/agents/{agent_id}/scorecards")
def agent_scorecards(agent_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    a = session.get(Agent, agent_id)
    if a is None or a.tenant_id != auth.tenant_id:
        raise HTTPException(404, "agent not found")
    from cie.agents.scorecards import routing_score

    out = []
    for sc in scorecards_for(session, a.id):
        score, comps, low = routing_score(sc)
        out.append({"task_type": sc.task_type, "n_tasks": sc.n_tasks, "accuracy": sc.accuracy, "citation_quality": sc.citation_quality,
                    "completion_rate": sc.completion_rate, "latency_ms_avg": sc.latency_ms_avg, "tokens_avg": sc.tokens_avg,
                    "compute_cost_avg": sc.compute_cost_avg, "human_corrections": sc.human_corrections, "hallucination_rate": sc.hallucination_rate,
                    "verification_score": sc.verification_score, "last_task_at": sc.last_task_at.isoformat() if sc.last_task_at else None,
                    "routing_score": score, "low_support": low, "components": comps})
    return {"agent": a.name, "scorecards": out}


@router.post("/agents/{agent_id}/outcome", summary="Record a human grading/correction for an agent")
def agent_outcome(agent_id: uuid.UUID, body: OutcomeIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    a = session.get(Agent, agent_id)
    if a is None or a.tenant_id != auth.tenant_id:
        raise HTTPException(404, "agent not found")
    sc = record_outcome(session, a, body.task_type, Outcome(accuracy=body.accuracy, citation_quality=body.citation_quality, completed=body.completed,
                                                            human_corrections=body.human_corrections, hallucinated=body.hallucinated))
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="agent.outcome", resource_kind="agent", resource_id=a.id,
          details=body.model_dump())
    return {"task_type": sc.task_type, "n_tasks": sc.n_tasks, "accuracy": sc.accuracy, "human_corrections": sc.human_corrections}


# ---------------------------------------------------------------- messages
@router.post("/messages")
def post_message(body: MessageIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.agents import messages

    p = _proj(session, auth, body.project_id)
    require_scope_write(auth, p.scope_id)
    agents = {a.name: a for a in agents_for_tenant(session, auth.tenant_id)}
    if body.to_agent not in agents:
        raise HTTPException(404, "unknown agent")
    try:
        m = messages.send(session, tenant_id=auth.tenant_id, project_id=p.id, kind=body.kind, payload=body.payload,
                          from_agent=agents.get(body.from_agent) if body.from_agent else None, to_agent=agents[body.to_agent], task_id=body.task_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"id": str(m.id), "kind": m.kind.value, "token_estimate": m.token_estimate}


@router.get("/messages")
def list_messages(project_id: uuid.UUID, task_id: uuid.UUID | None = None, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    _proj(session, auth, project_id)
    stmt = select(AgentMessage).where(AgentMessage.project_id == project_id)
    if task_id:
        stmt = stmt.where(AgentMessage.task_id == task_id)
    names = {a.id: a.name for a in agents_for_tenant(session, auth.tenant_id, active_only=False)}
    return [{"id": str(m.id), "kind": m.kind.value, "task_id": str(m.task_id) if m.task_id else None, "from": names.get(m.from_agent_id),
             "to": names.get(m.to_agent_id), "payload": m.payload, "token_estimate": m.token_estimate, "created_at": m.created_at.isoformat()}
            for m in session.scalars(stmt.order_by(AgentMessage.created_at))]
