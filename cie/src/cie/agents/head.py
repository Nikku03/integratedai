"""The project-head agent.

start(project, objective): ledger objective → plan (task DAG) → tasks proposed to the workflow engine and accepted
(ready, or blocked on their dependencies).
step(): for every ready task: route it with an explanation, claim it for the chosen agent (a lease), build the
evidence packet with the *agent's* principal (so agent permissions apply), send a task_request, run the specialist
strategy, check it for conflicts with other agents' findings, and submit it to the engine, which reviews it against
the task's acceptance criteria, limits and input versions. High-risk or conflicting work waits in review for a
different agent's verification; changes requested by a reviewer are addressed and resubmitted; a task that still
fails goes to a person. Finally the synthesis reports every task's outcome. Everything is written to the ledger.
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
from cie.workflow import engine

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
    @property
    def worker(self) -> str:
        return f"head:{self.project.id}"

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

    @staticmethod
    def acceptance_for(sp: TaskSpec) -> dict[str, Any]:
        if sp.task_type == "synthesis":
            return {"required_fields": ["answer"], "review": "auto"}
        return {"citations_required": True, "max_unsupported": 0, "review": "agent" if sp.risk_level == "high" else "auto"}

    def limits_for(self, sp: TaskSpec) -> dict[str, Any]:
        tools = ["retrieval"] + (["llm"] if isinstance(self.strategy, LLMStrategy) else [])
        return {"tools": tools, "max_tokens": 200_000, "max_cost_usd": 5.0}

    def _persist(self, specs: list[TaskSpec]) -> list[Task]:
        p = self.project
        by_key: dict[str, Task] = {}
        for sp in specs:
            t = engine.propose(self.s, tenant_id=p.tenant_id, project_id=p.id, scope_id=p.scope_id, task_type=sp.task_type, title=sp.title,
                               brief=sp.brief, priority=sp.priority, risk_level=sp.risk_level, acceptance=self.acceptance_for(sp),
                               limits=self.limits_for(sp), metrics={"query": sp.query}, actor="head")
            by_key[sp.key] = t
        for sp in specs:
            for d in sp.depends_on:
                if d in by_key:  # the synthesis reports every outcome, so it waits for settled work, not success
                    self.s.add(TaskDependency(task_id=by_key[sp.key].id, depends_on_id=by_key[d].id,
                                              kind="after" if sp.task_type == "synthesis" else "requires"))
        self.s.flush()
        for sp in specs:
            t = engine.accept(self.s, by_key[sp.key], actor="head")
            ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="task",
                          content={"task_id": str(t.id), "key": sp.key, "type": sp.task_type, "title": sp.title,
                                   "risk": sp.risk_level, "status": t.status.value}, actor="head")
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
        engine.refresh(self.s, project_id=self.project.id, actor="head")
        return [t for t in self._tasks() if t.status == TaskStatus.ready]

    def step(self, max_tasks: int = 10) -> StepReport:
        engine.reclaim_expired(self.s, tenant_id=self.project.tenant_id)
        # work sent back by a reviewer comes first: the same agent addresses the review
        reruns = [t for t in self._tasks() if t.status == TaskStatus.running and t.lease_owner == self.worker
                  and (t.progress or {}).get("changes_requested")]
        ran, conflicts, verifications = [], 0, 0
        for t in reruns[:max_tasks]:
            res = self._execute(t, rerun=True)
            conflicts += int(bool(res and res[1]))
            ran.append(t.id)
        for t in self.ready_tasks()[:max(0, max_tasks - len(ran))]:
            if t.task_type == "synthesis":
                self._synthesize(t)
            elif t.task_type == "verification":
                verifications += self._verify(t)
            else:
                res = self._execute(t)
                conflicts += res[1] if res else 0
            ran.append(t.id)
        tasks = self._tasks()
        blocked = sum(1 for t in tasks if t.status in (TaskStatus.blocked, TaskStatus.ready, TaskStatus.proposed))
        done = all(t.status in engine.SETTLED or engine.awaiting_person(t) for t in tasks)
        return StepReport(ran, blocked, done, conflicts, verifications)

    def run(self, max_steps: int = 20) -> dict[str, Any]:
        for _ in range(max_steps):
            rep = self.step()
            if rep.done:
                break
            if not rep.ran:
                # nothing runnable and not done: stagnation → record blocker and stop (anti-loop)
                ledger.append(self.s, tenant_id=self.project.tenant_id, project_id=self.project.id, kind="blocker",
                              content={"reason": "no runnable task; dependencies unresolved, reviews pending or all agents at capacity"},
                              actor="head")
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

    def _execute(self, t: Task, rerun: bool = False) -> tuple[TaskResult, int] | None:
        p = self.project
        if rerun:
            agent = self.s.get(Agent, t.assigned_agent_id)
        else:
            agent, reason = select_agent(self.s, t, self.agents)
            t = engine.claim_task(self.s, t.id, worker=self.worker, agent_id=agent.id if agent else None)
            t.assignment_reason = reason
            if agent is None:
                engine.fail(self.s, t.id, actor="head", error="no eligible agent")
                ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="failure",
                              content={"task_id": str(t.id), "error": "no eligible agent", "reason": reason}, actor="head")
                return None
            ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="assignment",
                          content={"task_id": str(t.id), "agent": agent.name, "decision": reason["decision"]}, actor="head")
        if not engine.tool_allowed(t, "retrieval"):
            self._fail(t, agent, "retrieval is not an allowed tool for this task")
            return None
        query = (t.metrics or {}).get("query") or t.title
        packet = self._packet(agent, t, query)
        if packet is None:
            self._fail(t, agent, "agent has no permission on the project scope", report=False)
            return None
        t.evidence_packet_id = packet.id
        deps = [d for d in (self.s.get(Task, i) for i in self._deps().get(t.id, set())) if d is not None]
        engine.record_inputs(self.s, t, tasks=[d for d in deps if d.status == TaskStatus.completed])
        if not rerun:
            messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.task_request, task_id=t.id,
                          from_agent=self.head, to_agent=agent,
                          payload={"task_id": str(t.id), "brief": t.brief, "evidence_packet_id": str(packet.id), "risk": t.risk_level,
                                   "acceptance": t.acceptance, "limits": t.limits})
            # hand over the compact outcome of each finished dependency (never the dependency's full context)
            for dep in deps:
                messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.dependency_notification,
                              task_id=t.id, from_agent=self.head, to_agent=agent,
                              payload={"task_id": str(t.id), "depends_on_task_id": str(dep.id), "status": dep.status.value,
                                       "summary": (dep.result or {}).get("summary", "")[:600],
                                       "open_questions": (dep.result or {}).get("open_questions", [])[:5]})
        t0 = time.perf_counter()
        try:
            result = self.strategy.run(agent, t, packet)
        except Exception as e:  # noqa: BLE001
            self._fail(t, agent, str(e))
            record_outcome(self.s, agent, t.task_type, Outcome(completed=False, latency_ms=(time.perf_counter() - t0) * 1000))
            return None
        result.latency_ms = (time.perf_counter() - t0) * 1000
        changes = (t.progress or {}).get("changes_requested") if rerun else None
        if changes:
            _address_review(result, changes)
        engine.checkpoint(self.s, t.id, worker=self.worker, progress={"evidence_packet_id": str(packet.id), "findings": len(result.findings)})
        conflicts = self._detect_conflicts(t, result)
        if conflicts and (t.acceptance or {}).get("review", "auto") == "auto":
            t.acceptance = {**(t.acceptance or {}), "review": "agent"}  # disagreement with another agent: verify independently
        out = result.as_dict()
        usage = {"tokens": result.tokens_in + result.tokens_out, "cost_usd": result.cost_usd, "seconds": round(result.latency_ms / 1000, 3),
                 "tools": ["retrieval"] + (["llm"] if isinstance(self.strategy, LLMStrategy) else []),
                 "packet_tokens": packet.token_estimate, "packet_items": len(packet.items)}
        t.metrics = {**(t.metrics or {}), **out["metrics"]}
        for req in result.evidence_requests:
            messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.evidence_request, task_id=t.id,
                          from_agent=agent, to_agent=self.head, payload={"task_id": str(t.id), "query": req})
        messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.final_result, task_id=t.id,
                      from_agent=agent, to_agent=self.head,
                      payload={"task_id": str(t.id), "result": {"summary": result.summary, "n_findings": len(result.findings),
                                                                "open_questions": result.open_questions}})
        t = engine.submit(self.s, t.id, worker=self.worker, result=out, usage=usage)
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="result",
                      content={"task_id": str(t.id), "agent": agent.name, "summary": result.summary, "n_findings": len(result.findings),
                               "status": t.status.value, "review": (t.verification or {}).get("last_review", {}).get("notes", ""),
                               "unsupported": len(result.unsupported_claims)}, actor=agent.name)
        cited = sum(1 for f in result.findings if f.citations)
        record_outcome(self.s, agent, t.task_type, Outcome(
            citation_quality=cited / len(result.findings) if result.findings else None, completed=True,
            latency_ms=result.latency_ms, tokens=result.tokens_in + result.tokens_out, compute_cost=result.cost_usd,
            hallucinated=bool(result.unsupported_claims)))
        for m, v in (("agent_task_tokens", result.tokens_in + result.tokens_out), ("agent_task_latency_ms", result.latency_ms),
                     ("agent_task_cost_usd", result.cost_usd)):
            self.s.add(Metric(tenant_id=p.tenant_id, name=m, value=float(v), labels={"agent": agent.name, "task_type": t.task_type}))
        if t.status == TaskStatus.review and (t.verification or {}).get("awaiting") == "agent":
            self._spawn_verification(t)
        self._notify_dependants(t)
        # store agent findings as memory records in the project scope (agent memory)
        for f in result.findings[:8]:
            create_record(self.s, tenant_id=p.tenant_id, scope_id=p.scope_id, type=RecordType.result,
                          summary=f"[{agent.name}] {f.claim[:160]}", content={"task_id": str(t.id), "kind": f.kind, "value": f.value},
                          detail=f.claim, source_document_id=uuid.UUID(f.citations[0]["document_id"]) if f.citations and f.citations[0].get("document_id") else None,
                          source_locations=f.citations, producing_agent=agent.name, confidence=f.confidence, embedder=self.embedder)
        return result, conflicts

    def _fail(self, t: Task, agent: Agent | None, error: str, report: bool = True) -> None:
        p = self.project
        engine.fail(self.s, t.id, actor=agent.name if agent else "head", error=error)
        if report and agent is not None:
            messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.failure_report, task_id=t.id,
                          from_agent=agent, to_agent=self.head, payload={"task_id": str(t.id), "error": error})
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="failure", content={"task_id": str(t.id), "error": error},
                      actor=agent.name if agent else "head")

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
        others = self.s.scalars(select(Task).where(Task.project_id == p.id, Task.id != t.id, Task.result.is_not(None),
                                                   Task.task_type != "verification"))
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
                    n += 1
        return n

    def _spawn_verification(self, t: Task) -> Task:
        p = self.project
        v = engine.propose(self.s, tenant_id=p.tenant_id, project_id=p.id, scope_id=p.scope_id, task_type="verification",
                           title=f"Verify: {t.title}", brief=f"Independently verify every finding of task {t.id} against the original sources.",
                           priority=2, risk_level="medium", verifies_task_id=t.id, acceptance={"required_fields": ["score"], "review": "auto"},
                           limits={"tools": ["retrieval"]}, actor="head")
        engine.accept(self.s, v, actor="head")
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="task",
                      content={"task_id": str(v.id), "type": "verification", "title": v.title, "verifies": str(t.id), "status": v.status.value},
                      actor="head")
        return v

    def _verify(self, v: Task) -> int:
        p = self.project
        target = self.s.get(Task, v.verifies_task_id) if v.verifies_task_id else None
        if target is None or target.status != TaskStatus.review:
            engine.cancel(self.s, v.id, actor="head", reason="nothing to verify: the task is no longer in review")
            return 0
        agent, reason = select_agent(self.s, v, self.agents, exclude={target.assigned_agent_id})
        if agent is None:
            engine.cancel(self.s, v.id, actor="head", reason="no agent other than the producer can verify")
            engine.escalate(self.s, target.id, actor="head", reason=f"No agent free to verify {target.title}")
            return 0
        v = engine.claim_task(self.s, v.id, worker=self.worker, agent_id=agent.id)
        v.assignment_reason = reason
        messages.send(self.s, tenant_id=p.tenant_id, project_id=p.id, kind=MessageKind.verification_request, task_id=v.id,
                      from_agent=self.head, to_agent=agent, payload={"task_id": str(v.id), "verifies_task_id": str(target.id)})
        verdict = verify_result(self.s, target.result or {})
        engine.submit(self.s, v.id, worker=self.worker, result=verdict.as_dict(), usage={"tools": ["retrieval"]})
        failed = [d for d in verdict.details if d["status"] != "verified"]
        target = engine.review(self.s, target.id, reviewer=agent.name, verdict="passed" if verdict.passed else "changes_requested",
                               notes=f"{verdict.verified} verified, {verdict.failed} failed", details={"score": verdict.score, "failed_findings": failed})
        target.verification = {**(target.verification or {}), "by": agent.name, **verdict.as_dict()}
        producer = self.s.get(Agent, target.assigned_agent_id) if target.assigned_agent_id else None
        if producer is not None:
            record_outcome(self.s, producer, target.task_type, Outcome(accuracy=verdict.score, verification_score=verdict.score,
                                                                       hallucinated=verdict.failed > 0))
        record_outcome(self.s, agent, "verification", Outcome(completed=True, accuracy=1.0, citation_quality=1.0))
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="verification",
                      content={"task_id": str(target.id), "verifier": agent.name, "verdict": "passed" if verdict.passed else "failed",
                               "score": verdict.score, "failed": verdict.failed, "status": target.status.value}, actor=agent.name)
        return 1

    # ------------------------------------------------------------------ synthesis
    def _synthesize(self, t: Task) -> None:
        p = self.project
        t = engine.claim_task(self.s, t.id, worker=self.worker, agent_id=self.head.id if self.head else None)
        tasks = [x for x in self._tasks() if x.id != t.id and x.task_type not in ("synthesis", "verification")]
        engine.record_inputs(self.s, t, tasks=tasks)
        sections, citations, uncertainties = [], [], []
        for x in tasks:
            r = x.result or {}
            last = (x.verification or {}).get("last_review", {})
            verified = x.status == TaskStatus.completed and last.get("reviewer") not in (None, "engine")
            flag = "verified" if verified else ("UNVERIFIED" if x.risk_level == "high" else "not independently verified")
            if engine.awaiting_person(x):
                flag = "FAILED VERIFICATION – awaiting a person's decision"
                uncertainties.append(f"{x.title}: verification failed")
            elif x.status == TaskStatus.failed:
                flag = "FAILED"
                uncertainties.append(f"{x.title}: failed ({(x.progress or {}).get('last_error', 'see task')})"[:300])
            sections.append(f"{x.title} ({flag}): {r.get('summary', 'no result')}")
            for f in r.get("findings", [])[:6]:
                citations.extend(f.get("citations", [])[:1])
            uncertainties.extend(r.get("open_questions", [])[:3])
        answer = " \n".join(sections) if sections else "No specialist produced a result."
        state = ledger.state(self.s, p.id)
        pending = sum(1 for x in tasks if engine.awaiting_person(x) or x.status == TaskStatus.failed)
        result = {"answer": answer, "citations": citations[:40], "uncertainty": sorted(set(uncertainties))[:12],
                  "contradictions": len(state["contradictions"]), "tasks": len(tasks),
                  "confidence": round(max(0.1, 0.9 - 0.15 * len(state["contradictions"]) - 0.1 * pending), 3)}
        engine.submit(self.s, t.id, worker=self.worker, result=result, usage={"tools": ["retrieval"]})
        ledger.append(self.s, tenant_id=p.tenant_id, project_id=p.id, kind="synthesis", content={"task_id": str(t.id), **result}, actor="head")
        p.status = "completed"
        create_record(self.s, tenant_id=p.tenant_id, scope_id=p.scope_id, type=RecordType.result, summary=f"Project synthesis: {p.objective[:120]}",
                      content={"task_id": str(t.id), "confidence": result["confidence"], "contradictions": result["contradictions"]},
                      detail=answer[:4000], source_locations=citations[:10], producing_agent="head", confidence=result["confidence"],
                      embedder=self.embedder)


def _address_review(result: TaskResult, changes: dict[str, Any]) -> None:
    """Act on a reviewer's request: drop the findings the verifier could not support and those without a citation,
    and say so in the open questions."""
    failed = {d.get("claim") for d in (changes.get("details") or {}).get("failed_findings", [])}
    keep = [f for f in result.findings if f.claim not in failed and f.citations]
    dropped = len(result.findings) - len(keep)
    if dropped:
        result.findings = keep
        result.open_questions = list(result.open_questions) + [f"{dropped} finding(s) removed after review: {changes.get('notes', '')}"[:300]]


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
