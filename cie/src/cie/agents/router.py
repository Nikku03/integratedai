"""Task routing with an explanation for every assignment.

score(agent, task) = skill_match × permission_ok × availability
                     × (0.55 · task-type scorecard + 0.25 · skill overlap + 0.20 · cost factor)
Every candidate's factors are stored in ``task.assignment_reason`` together
with the runner-up, so the UI can show *why* an agent was chosen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cie.agents.scorecards import get_or_create, routing_score
from cie.core.models import Agent, Principal, Task, TaskStatus
from cie.governance.permissions import visible_scopes


@dataclass
class Candidate:
    agent: Agent
    score: float
    factors: dict[str, float | bool | str] = field(default_factory=dict)
    eligible: bool = True
    reason_excluded: str | None = None


def _skill_overlap(agent: Agent, task: Task) -> float:
    words = set((task.title + " " + task.brief + " " + task.task_type).lower().replace("_", " ").split())
    skills = set(s.lower() for s in (agent.skills or []))
    if not skills:
        return 0.0
    return len(words & skills) / len(skills)


def _running(session: Session, agent: Agent) -> int:
    return session.scalar(select(func.count(Task.id)).where(Task.assigned_agent_id == agent.id,
                                                            Task.status.in_([TaskStatus.assigned, TaskStatus.running]))) or 0


def rank_candidates(session: Session, task: Task, agents: list[Agent], exclude: set | None = None) -> list[Candidate]:
    exclude = exclude or set()
    max_cost = max((a.cost_per_1k_tokens for a in agents), default=0.0) or 1.0
    out: list[Candidate] = []
    for a in agents:
        c = Candidate(agent=a, score=0.0)
        if a.id in exclude:
            c.eligible, c.reason_excluded = False, "excluded (produced the result under verification)"
            out.append(c)
            continue
        if a.role == "head" and task.task_type not in ("plan", "synthesis"):
            c.eligible, c.reason_excluded = False, "head agent does not execute specialist tasks"
            out.append(c)
            continue
        if task.task_type not in (a.task_types or []):
            c.eligible, c.reason_excluded = False, f"task type '{task.task_type}' not in agent task types"
            out.append(c)
            continue
        principal = session.get(Principal, a.principal_id)
        vis = visible_scopes(session, principal) if principal else None
        if task.scope_id is not None and (vis is None or task.scope_id not in vis.scope_ids):
            c.eligible, c.reason_excluded = False, "agent lacks permission on the task scope"
            out.append(c)
            continue
        running = _running(session, a)
        if running >= a.max_concurrency:
            c.eligible, c.reason_excluded = False, f"at capacity ({running}/{a.max_concurrency})"
            out.append(c)
            continue
        sc = get_or_create(session, a, task.task_type)
        hist, comps, low_support = routing_score(sc)
        overlap = _skill_overlap(a, task)
        cost_factor = 1.0 - (a.cost_per_1k_tokens / max_cost) * 0.5
        c.score = round(0.55 * hist + 0.25 * overlap + 0.20 * cost_factor, 4)
        c.factors = {"scorecard": round(hist, 3), "scorecard_low_support": low_support, "scorecard_n": sc.n_tasks,
                     "skill_overlap": round(overlap, 3), "cost_factor": round(cost_factor, 3), "running": running,
                     **{f"sc_{k}": round(v, 3) for k, v in comps.items()}}
        out.append(c)
    return sorted(out, key=lambda c: (-c.eligible, -c.score))


def select_agent(session: Session, task: Task, agents: list[Agent], exclude: set | None = None) -> tuple[Agent | None, dict]:
    ranked = rank_candidates(session, task, agents, exclude)
    eligible = [c for c in ranked if c.eligible]
    reason = {
        "task_type": task.task_type,
        "candidates": [{"agent": c.agent.name, "score": c.score, "eligible": c.eligible, "excluded": c.reason_excluded,
                        **c.factors} for c in ranked],
    }
    if not eligible:
        reason["decision"] = "no eligible agent"
        return None, reason
    best = eligible[0]
    runner = eligible[1] if len(eligible) > 1 else None
    reason["decision"] = (f"{best.agent.name} chosen for '{task.task_type}': score {best.score}"
                          + (f" vs runner-up {runner.agent.name} {runner.score}" if runner else "")
                          + (" (scorecard low-support: routed on skills, permissions and cost)" if best.factors.get("scorecard_low_support") else ""))
    reason["chosen"] = best.agent.name
    return best.agent, reason
