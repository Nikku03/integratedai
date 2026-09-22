"""The project-head agent.

start(project, objective): ledger objective → plan (task DAG) → persist tasks.
step(): for every task whose dependencies are done: build the evidence packet
with the *agent's* principal (so agent permissions apply), route with an
explanation, send a task_request, run the specialist strategy, store the
structured result, notify dependants, detect conflicts between agents'
findings, create verification tasks for high-risk work (assigned to a
different agent), and finally synthesize. Everything is written to the ledger.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.agents import ledger, messages
from cie.agents.planner import RulePlanner, TaskSpec
from cie.agents.providers import LLMProvider
from cie.agents.registry import agents_for_tenant
from cie.agents.router import select_agent
from cie.agents.scorecards import Outcome, record_outcome
from cie.agents.specialists import ExtractiveStrategy, LLMStrategy, TaskResult
from cie.agents.verification import verify_result
from cie.core.logging import get_logger
from cie.core.models import (
    Agent,
    Approval,
    EvidencePacket,
    MemoryRecord,
    MessageKind,
    Metric,
    Principal,
    Project,
    RecordType,
    Scope,
    Task,
    TaskDependency,
    TaskStatus,
)
from cie.core.settings import Settings, get_settings
from cie.memory.records import contradict, create_record
from cie.retrieval.pipeline import Retriever

log = get_logger(__name__)


@dataclass
class StepReport:
    ran: list[uuid.UUID]
    blocked: int
    done: bool
    conflicts: int = 0
    verifications: int = 0


class HeadAgent:
    def __init__(self, session: Session, project: Project, *, settings: Settings | None = None, embedder=None,
                 provider: LLMProvider | None = None, planner=None):
        self.s = session
        self.project = project
        self.settings = settings or get_settings()
        self.embedder = embedder
        self.provider = provider
        self.planner = planner or RulePlanner()
        self.agents = agents_for_tenant(session, project.tenant_id)
        self.head = next((a for a in self.agents if a.role == "head"), None)
        self.strategy = LLMStrategy(provider) if provider is not None and provider.name != "none" else ExtractiveStrategy()

    # ------------------------------------------------------------------ planning
    def start(self, objective: str) -> list[Task]:
        p = self.project
        p.objective = objective
        p.head_agent_id = self.head.id if self.head else None
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="objective", content={"objective": objective},
                      actor="head")
        specs = self.planner.plan(objective)
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="plan",
                      content={"planner": getattr(self.planner, "name", "?"),
                               "tasks": [{"key": t.key, "type": t.task_type, "depends_on": t.depends_on, "risk": t.risk_level} for t in specs]},
                      actor="head")
        tasks = self._persist(specs)
        return tasks

    def _persist(self, specs: list[TaskSpec]) -> list[Task]:
        p = self.project
        by_key: dict[str, Task] = {}
        for sp in specs:
            t = Task(tenant_id=p.tenant_id, project_id=p.id, scope_id=p.scope_id, task_type=sp.task_type, title=sp.title,
                     brief=sp.brief, status=TaskStatus.pending if not sp.depends_on else TaskStatus.blocked,
                     priority=sp.priority, risk_level=sp.risk_level, metrics={"query": sp.query})
            self.s.add(t)
            self.s.flush()
            by_key[sp.key] = t
            ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="task",
                          content={"task_id": str(t.id), "key": sp.key, "type": sp.task_type, "title": sp.title,
                                   "risk": sp.risk_level, "status": t.status.value}, actor="head")
        for sp in specs:
            for d in sp.depends_on:
                if d in by_key:
                    self.s.add(TaskDependency(task_id=by_key[sp.key].id, depends_on_id=by_key[d].id))
        self.s.flush()
        return list(by_key.values())

    # ------------------------------------------------------------------ scheduling
    def _tasks(self) -> list[Task]:
        return list(self.s.scalars(select(Task).where(Task.project_id == self.project.id).order_by(Task.priority, Task.created_at)))

    def _deps(self) -> dict[uuid.UUID, set[uuid.UUID]]:
        deps: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for d in self.s.scalars(select(TaskDependency).join(Task, Task.id == TaskDependency.task_id).where(Task.project_id == self.project.id)):
            deps[d.task_id].add(d.depends_on_id)
        return deps

    def ready_tasks(self) -> list[Task]:
        tasks = self._tasks()
        deps = self._deps()
        finished = {TaskStatus.done, TaskStatus.verified}
        status = {t.id: t.status for t in tasks}
        ready = []
        for t in tasks:
            if t.status not in (TaskStatus.pending, TaskStatus.blocked):
                continue
            if all(status.get(d) in finished for d in deps.get(t.id, set())):
                if t.status == TaskStatus.blocked:
                    t.status = TaskStatus.pending
                ready.append(t)
        return ready

    def step(self, max_tasks: int = 10) -> StepReport:
        ready = self.ready_tasks()[:max_tasks]
        ran, conflicts, verifications = [], 0, 0
        for t in ready:
            if t.task_type == "synthesis":
                self._synthesize(t)
            elif t.task_type == "verification":
                verifications += self._verify(t)
            else:
                res = self._execute(t)
                if res is not None:
                    conflicts += self._detect_conflicts(t, res)
                    if t.risk_level == "high" and t.status == TaskStatus.needs_verification:
                        self._spawn_verification(t)
            ran.append(t.id)
        tasks = self._tasks()
        blocked = sum(1 for t in tasks if t.status in (TaskStatus.blocked, TaskStatus.pending))
        done = all(t.status in (TaskStatus.done, TaskStatus.verified, TaskStatus.failed, TaskStatus.awaiting_approval) for t in tasks)
        return StepReport(ran, blocked, done, conflicts, verifications)

    def run(self, max_steps: int = 20) -> dict[str, Any]:
        for _ in range(max_steps):
            rep = self.step()
            if rep.done:
                break
            if not rep.ran:
                # nothing runnable and not done: stagnation → record blocker and stop (anti-loop)
                ledger.append(self.s, tenant_id=self.project.tenant_id, project_id=self.project.id, kind="blocker",
                              content={"reason": "no runnable task; dependencies unresolved or all agents at capacity"}, actor="head")
                break
        return ledger.state(self.s, self.project.id)

    # ------------------------------------------------------------------ execution
    def _agent_principal(self, agent: Agent) -> Principal:
        p = self.s.get(Principal, agent.principal_id)
        assert p is not None
        return p

    def _packet(self, agent: Agent, task: Task, query: str) -> EvidencePacket | None:
        retriever = Retriever(self.s, self.settings, embedder=self.embedder)
        try:
            res = retriever.retrieve(query, self._agent_principal(agent), task.scope_id or self.project.scope_id,
                                     max_records=60, token_budget=8000)
        except PermissionError:
            return None
        return res.packet

    def _execute(self, t: Task) -> TaskResult | None:
        p = self.project
        agent, reason = select_agent(self.s, t, self.agents)
        if agent is None:
            t.status = TaskStatus.failed
            t.assignment_reason = reason
            ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="failure",
                          content={"task_id": str(t.id), "error": "no eligible agent", "reason": reason}, actor="head")
            return None
        t.assigned_agent_id = agent.id
        t.assignment_reason = reason
        t.status = TaskStatus.assigned
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="assignment",
                      content={"task_id": str(t.id), "agent": agent.name, "decision": reason["decision"]}, actor="head")
        query = (t.metrics or {}).get("query") or t.title
        packet = self._packet(agent, t, query)
        if packet is None:
            t.status = TaskStatus.failed
            ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="failure",
                          content={"task_id": str(t.id), "error": "agent has no permission on the project scope"}, actor="head")
            return None
        t.evidence_packet_id = packet.id
        messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.task_request, task_id=t.id,
                      from_agent=self.head, to_agent=agent,
                      payload={"task_id": str(t.id), "brief": t.brief, "evidence_packet_id": str(packet.id), "risk": t.risk_level})
        # hand over the compact outcome of each finished dependency (never the dependency's full context)
        for dep_id in self._deps().get(t.id, set()):
            dep = self.s.get(Task, dep_id)
            if dep is not None:
                messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.dependency_notification,
                              task_id=t.id, from_agent=self.head, to_agent=agent,
                              payload={"task_id": str(t.id), "depends_on_task_id": str(dep.id), "status": dep.status.value,
                                       "summary": (dep.result or {}).get("summary", "")[:600],
                                       "open_questions": (dep.result or {}).get("open_questions", [])[:5]})
        t.status = TaskStatus.running
        t0 = time.perf_counter()
        try:
            result = self.strategy.run(agent, t, packet)
        except Exception as e:  # noqa: BLE001
            t.status = TaskStatus.failed
            messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.failure_report, task_id=t.id,
                          from_agent=agent, to_agent=self.head, payload={"task_id": str(t.id), "error": str(e)})
            ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="failure", content={"task_id": str(t.id), "error": str(e)}, actor=agent.name)
            record_outcome(self.s, agent, t.task_type, Outcome(completed=False, latency_ms=(time.perf_counter() - t0) * 1000))
            return None
        result.latency_ms = (time.perf_counter() - t0) * 1000
        t.result = result.as_dict()
        t.metrics = {**(t.metrics or {}), **result.as_dict()["metrics"], "packet_tokens": packet.token_estimate,
                     "packet_items": len(packet.items)}
        for req in result.evidence_requests:
            messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.evidence_request, task_id=t.id,
                          from_agent=agent, to_agent=self.head, payload={"task_id": str(t.id), "query": req})
        messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.final_result, task_id=t.id,
                      from_agent=agent, to_agent=self.head,
                      payload={"task_id": str(t.id), "result": {"summary": result.summary, "n_findings": len(result.findings),
                                                                "open_questions": result.open_questions}})
        t.status = TaskStatus.needs_verification if t.risk_level == "high" else TaskStatus.done
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="result",
                      content={"task_id": str(t.id), "agent": agent.name, "summary": result.summary, "n_findings": len(result.findings),
                               "status": t.status.value, "unsupported": len(result.unsupported_claims)}, actor=agent.name)
        cited = sum(1 for f in result.findings if f.citations)
        record_outcome(self.s, agent, t.task_type, Outcome(
            citation_quality=cited / len(result.findings) if result.findings else None, completed=True,
            latency_ms=result.latency_ms, tokens=result.tokens_in + result.tokens_out, compute_cost=result.cost_usd,
            hallucinated=bool(result.unsupported_claims)))
        for m, v in (("agent_task_tokens", result.tokens_in + result.tokens_out), ("agent_task_latency_ms", result.latency_ms),
                     ("agent_task_cost_usd", result.cost_usd)):
            self.s.add(Metric(tenant_id=p.tenant_id, name=m, value=float(v), labels={"agent": agent.name, "task_type": t.task_type}))
        self._notify_dependants(t)
        # store agent findings as memory records in the project scope (agent memory)
        for f in result.findings[:8]:
            create_record(self.s, tenant_id=p.tenant_id, scope_id=p.scope_id, type=RecordType.result,
                          summary=f"[{agent.name}] {f.claim[:160]}", content={"task_id": str(t.id), "kind": f.kind, "value": f.value},
                          detail=f.claim, source_document_id=uuid.UUID(f.citations[0]["document_id"]) if f.citations and f.citations[0].get("document_id") else None,
                          source_locations=f.citations, producing_agent=agent.name, confidence=f.confidence, embedder=self.embedder)
        return result

    def _notify_dependants(self, t: Task) -> None:
        p = self.project
        for d in self.s.scalars(select(TaskDependency).where(TaskDependency.depends_on_id == t.id)):
            dep_task = self.s.get(Task, d.task_id)
            if dep_task and dep_task.assigned_agent_id:
                to = self.s.get(Agent, dep_task.assigned_agent_id)
                messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.dependency_notification,
                              task_id=dep_task.id, from_agent=self.head, to_agent=to,
                              payload={"task_id": str(dep_task.id), "depends_on_task_id": str(t.id), "status": t.status.value})

    # ------------------------------------------------------------------ conflicts and verification
    def _detect_conflicts(self, t: Task, result: TaskResult) -> int:
        """Same-kind findings with a numeric/date value that disagree across agents in this project."""
        p = self.project
        n = 0
        mine = {(f.kind, _key(f.claim)): f for f in result.findings if f.value is not None}
        if not mine:
            return 0
        others = self.s.scalars(select(Task).where(Task.project_id == p.id, Task.id != t.id, Task.result.is_not(None)))
        for o in others:
            for f in (o.result or {}).get("findings", []):
                if f.get("value") is None:
                    continue
                k = (f.get("kind"), _key(f.get("claim", "")))
                if k in mine and str(mine[k].value) != str(f["value"]):
                    a_rec = self.s.get(MemoryRecord, uuid.UUID(mine[k].citations[0]["item_id"])) if mine[k].citations else None
                    b_rec = self.s.get(MemoryRecord, uuid.UUID(f["citations"][0]["item_id"])) if f.get("citations") else None
                    reason = f"agents disagree on {k[0]} '{k[1]}': {mine[k].value} vs {f['value']}"
                    if a_rec is not None and b_rec is not None and a_rec.id != b_rec.id:
                        contradict(self.s, a_rec, b_rec, reason, producing_agent="head")
                    messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.contradiction, task_id=t.id,
                                  from_agent=self.head, to_agent=self.s.get(Agent, t.assigned_agent_id),
                                  payload={"task_id": str(t.id), "record_a": str(a_rec.id if a_rec else ""), "record_b": str(b_rec.id if b_rec else ""), "reason": reason})
                    ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="contradiction",
                                  content={"task_id": str(t.id), "other_task_id": str(o.id), "reason": reason}, actor="head")
                    if t.status == TaskStatus.done:
                        t.status = TaskStatus.needs_verification
                    n += 1
        return n

    def _spawn_verification(self, t: Task) -> Task:
        p = self.project
        v = Task(tenant_id=p.tenant_id, project_id=p.id, scope_id=p.scope_id, task_type="verification",
                 title=f"Verify: {t.title}", brief=f"Independently verify every finding of task {t.id} against the original sources.",
                 status=TaskStatus.pending, priority=2, risk_level="medium", verifies_task_id=t.id)
        self.s.add(v)
        self.s.flush()
        # synthesis must wait for the verification too
        for d in list(self.s.scalars(select(TaskDependency).where(TaskDependency.depends_on_id == t.id))):
            self.s.add(TaskDependency(task_id=d.task_id, depends_on_id=v.id))
        self.s.flush()
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="task",
                      content={"task_id": str(v.id), "type": "verification", "title": v.title, "verifies": str(t.id), "status": "pending"}, actor="head")
        return v

    def _verify(self, v: Task) -> int:
        p = self.project
        target = self.s.get(Task, v.verifies_task_id) if v.verifies_task_id else None
        if target is None:
            v.status = TaskStatus.failed
            return 0
        agent, reason = select_agent(self.s, v, self.agents, exclude={target.assigned_agent_id})
        if agent is None:
            v.status = TaskStatus.awaiting_approval
            self.s.add(Approval(tenant_id=p.tenant_id, kind="task_result", subject_id=str(target.id), summary=f"No agent free to verify {target.title}",
                                requested_by="head"))
            return 0
        v.assigned_agent_id, v.assignment_reason, v.status = agent.id, reason, TaskStatus.running
        messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.verification_request, task_id=v.id,
                      from_agent=self.head, to_agent=agent, payload={"task_id": str(v.id), "verifies_task_id": str(target.id)})
        verdict = verify_result(self.s, target.result or {})
        v.result = verdict.as_dict()
        v.status = TaskStatus.done
        target.verification = {"by": agent.name, **verdict.as_dict()}
        producer = self.s.get(Agent, target.assigned_agent_id) if target.assigned_agent_id else None
        if producer is not None:
            record_outcome(self.s, producer, target.task_type, Outcome(accuracy=verdict.score, verification_score=verdict.score,
                                                                       hallucinated=verdict.failed > 0))
        record_outcome(self.s, agent, "verification", Outcome(completed=True, accuracy=1.0, citation_quality=1.0))
        if verdict.passed:
            target.status = TaskStatus.verified
        else:
            target.status = TaskStatus.awaiting_approval
            self.s.add(Approval(tenant_id=p.tenant_id, kind="task_result", subject_id=str(target.id),
                                summary=f"{verdict.failed} finding(s) of '{target.title}' failed verification", requested_by=agent.name))
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="verification",
                      content={"task_id": str(target.id), "verifier": agent.name, "verdict": "passed" if verdict.passed else "failed",
                               "score": verdict.score, "failed": verdict.failed}, actor=agent.name)
        return 1

    # ------------------------------------------------------------------ synthesis
    def _synthesize(self, t: Task) -> None:
        p = self.project
        t.assigned_agent_id = self.head.id if self.head else None
        t.status = TaskStatus.running
        tasks = [x for x in self._tasks() if x.id != t.id and x.task_type not in ("synthesis", "verification")]
        sections, citations, uncertainties = [], [], []
        for x in tasks:
            r = x.result or {}
            verified = x.status == TaskStatus.verified
            flag = "verified" if verified else ("UNVERIFIED" if x.risk_level == "high" else "not independently verified")
            if x.status == TaskStatus.awaiting_approval:
                flag = "FAILED VERIFICATION – awaiting human approval"
                uncertainties.append(f"{x.title}: verification failed")
            sections.append(f"{x.title} ({flag}): {r.get('summary', 'no result')}")
            for f in r.get("findings", [])[:6]:
                citations.extend(f.get("citations", [])[:1])
            uncertainties.extend(r.get("open_questions", [])[:3])
        answer = " \n".join(sections) if sections else "No specialist produced a result."
        state = ledger.state(self.s, p.id)
        result = {"answer": answer, "citations": citations[:40], "uncertainty": sorted(set(uncertainties))[:12],
                  "contradictions": len(state["contradictions"]), "tasks": len(tasks),
                  "confidence": round(max(0.1, 0.9 - 0.15 * len(state["contradictions"]) - 0.1 * sum(1 for x in tasks if x.status == TaskStatus.awaiting_approval)), 3)}
        t.result = result
        t.status = TaskStatus.done
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="synthesis", content={"task_id": str(t.id), **result}, actor="head")
        p.status = "completed"
        create_record(self.s, tenant_id=p.tenant_id, scope_id=p.scope_id, type=RecordType.result, summary=f"Project synthesis: {p.objective[:120]}",
                      content={"task_id": str(t.id), "confidence": result["confidence"], "contradictions": result["contradictions"]},
                      detail=answer[:4000], source_locations=citations[:10], producing_agent="head", confidence=result["confidence"],
                      embedder=self.embedder)


def _key(claim: str) -> str:
    import re

    words = [w for w in re.findall(r"[a-z]{4,}", claim.lower()) if w not in ("with", "that", "this", "from", "shall", "must")]
    return " ".join(words[:3])


def create_project(session: Session, *, tenant_id: uuid.UUID, parent_scope: Scope, name: str, objective: str = "") -> Project:
    from cie.memory.scopes import create_scope

    scope = create_scope(session, tenant_id, "project", name, parent_scope)
    proj = session.scalar(select(Project).where(Project.scope_id == scope.id))
    if proj is None:
        proj = Project(tenant_id=tenant_id, scope_id=scope.id, name=name, objective=objective)
        session.add(proj)
        session.flush()
    return proj
