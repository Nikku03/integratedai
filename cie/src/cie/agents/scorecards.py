"""Per (agent, task_type) scorecards and the routing score derived from them.

Scores are exponential moving averages of observed outcomes. A scorecard with
fewer than ``LOW_SUPPORT_N`` tasks is marked low-support and contributes a
neutral prior to routing instead of its (noisy) values, following the
``low_support`` idea in enzyme_software's scorecard primitives.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Agent, AgentScorecard
from cie.core.util import utcnow

LOW_SUPPORT_N = 5
ALPHA = 0.3  # EMA weight of the newest observation


@dataclass
class Outcome:
    accuracy: float | None = None  # 0..1 (verification agreement or human grading)
    citation_quality: float | None = None  # fraction of claims with valid citations
    completed: bool = True
    latency_ms: float = 0.0
    tokens: int = 0
    compute_cost: float = 0.0
    hallucinated: bool = False
    human_corrections: int = 0
    verification_score: float | None = None


def get_or_create(session: Session, agent: Agent, task_type: str) -> AgentScorecard:
    sc = session.scalar(select(AgentScorecard).where(AgentScorecard.agent_id == agent.id, AgentScorecard.task_type == task_type))
    if sc is None:
        sc = AgentScorecard(tenant_id=agent.tenant_id, agent_id=agent.id, task_type=task_type)
        session.add(sc)
        session.flush()
    return sc


def _ema(old: float, new: float, n: int) -> float:
    if n == 0:
        return new
    return (1 - ALPHA) * old + ALPHA * new


def record_outcome(session: Session, agent: Agent, task_type: str, o: Outcome) -> AgentScorecard:
    sc = get_or_create(session, agent, task_type)
    n = sc.n_tasks
    if o.accuracy is not None:
        sc.accuracy = _ema(sc.accuracy, o.accuracy, n)
    if o.citation_quality is not None:
        sc.citation_quality = _ema(sc.citation_quality, o.citation_quality, n)
    sc.completion_rate = _ema(sc.completion_rate, 1.0 if o.completed else 0.0, n)
    sc.latency_ms_avg = _ema(sc.latency_ms_avg, o.latency_ms, n)
    sc.tokens_avg = _ema(sc.tokens_avg, float(o.tokens), n)
    sc.compute_cost_avg = _ema(sc.compute_cost_avg, o.compute_cost, n)
    sc.hallucination_rate = _ema(sc.hallucination_rate, 1.0 if o.hallucinated else 0.0, n)
    if o.verification_score is not None:
        sc.verification_score = _ema(sc.verification_score, o.verification_score, n)
    sc.human_corrections += o.human_corrections
    sc.n_tasks = n + 1
    sc.last_task_at = utcnow()
    session.flush()
    return sc


def routing_score(sc: AgentScorecard | None) -> tuple[float, dict[str, float], bool]:
    """Returns (score in 0..1, components, low_support)."""
    if sc is None or sc.n_tasks < LOW_SUPPORT_N:
        comps = {"prior": 0.5}
        return 0.5, comps, True
    recency_days = (utcnow() - sc.last_task_at).days if sc.last_task_at else 365
    recency = max(0.0, 1.0 - recency_days / 180.0)
    comps = {
        "accuracy": 0.30 * sc.accuracy,
        "citation_quality": 0.20 * sc.citation_quality,
        "completion_rate": 0.15 * sc.completion_rate,
        "verification_score": 0.15 * sc.verification_score,
        "hallucination_penalty": -0.25 * sc.hallucination_rate,
        "recency": 0.10 * recency,
        "corrections_penalty": -0.02 * min(sc.human_corrections, 10),
    }
    return max(0.0, min(1.0, 0.5 + sum(comps.values()) - 0.45)), comps, False


def scorecards_for(session: Session, agent_id: uuid.UUID) -> list[AgentScorecard]:
    return list(session.scalars(select(AgentScorecard).where(AgentScorecard.agent_id == agent_id).order_by(AgentScorecard.task_type)))
