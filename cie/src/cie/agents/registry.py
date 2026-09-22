"""Agent registry: the head agent and five default specialists.

Each agent has a principal (so permissions apply to agents exactly as to
people), an agent-level memory scope under the company scope, skills and the
task types it accepts. Specialists are configurable; these are defaults.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Agent, Permission, Principal, PrincipalKind, Scope, ScopeKind
from cie.governance.permissions import ensure_role, grant_role
from cie.memory.scopes import create_scope

DEFAULT_AGENTS: list[dict] = [
    {"name": "head", "role": "head", "skills": ["planning", "decomposition", "routing", "synthesis", "verification"],
     "task_types": ["plan", "synthesis", "verification"], "cost_per_1k_tokens": 0.015},
    {"name": "research", "role": "research", "skills": ["evidence", "search", "summarisation", "citations", "documents"],
     "task_types": ["research", "evidence", "verification", "summary"], "cost_per_1k_tokens": 0.003},
    {"name": "finance", "role": "finance", "skills": ["metrics", "budget", "forecast", "cost", "analytics", "fees"],
     "task_types": ["finance", "analytics", "metrics", "verification"], "cost_per_1k_tokens": 0.003},
    {"name": "legal", "role": "legal", "skills": ["contracts", "clauses", "compliance", "risk", "deadlines", "obligations"],
     "task_types": ["legal", "compliance", "risk", "verification"], "cost_per_1k_tokens": 0.005},
    {"name": "operations", "role": "operations", "skills": ["planning", "timeline", "dependencies", "tasks", "resources"],
     "task_types": ["operations", "project_management", "timeline", "verification"], "cost_per_1k_tokens": 0.003},
    {"name": "engineering", "role": "engineering", "skills": ["implementation", "code", "architecture", "requirements", "testing"],
     "task_types": ["engineering", "implementation", "requirements", "verification"], "cost_per_1k_tokens": 0.005},
]


def ensure_default_agents(session: Session, tenant_id: uuid.UUID, company_scope: Scope, strategy: str = "extractive",
                          model: str | None = None) -> dict[str, Agent]:
    role = ensure_role(session, tenant_id, "agent_reader", Permission.read, 2)
    writer = ensure_role(session, tenant_id, "agent_writer", Permission.write, 2)
    out: dict[str, Agent] = {}
    for spec in DEFAULT_AGENTS:
        agent = session.scalar(select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == spec["name"]))
        if agent is None:
            principal = Principal(tenant_id=tenant_id, kind=PrincipalKind.agent, name=f"agent:{spec['name']}",
                                  attributes={"role": spec["role"]})
            session.add(principal)
            session.flush()
            scope = create_scope(session, tenant_id, ScopeKind.agent, f"agent:{spec['name']}", company_scope)
            grant_role(session, tenant_id=tenant_id, principal=principal, role=role, scope=company_scope)
            grant_role(session, tenant_id=tenant_id, principal=principal, role=writer, scope=scope)
            agent = Agent(tenant_id=tenant_id, principal_id=principal.id, name=spec["name"], role=spec["role"],
                          skills=spec["skills"], task_types=spec["task_types"], strategy=strategy, model=model,
                          cost_per_1k_tokens=spec["cost_per_1k_tokens"], memory_scope_id=scope.id, max_concurrency=2)
            session.add(agent)
            session.flush()
        out[spec["name"]] = agent
    return out


def agents_for_tenant(session: Session, tenant_id: uuid.UUID, active_only: bool = True) -> list[Agent]:
    stmt = select(Agent).where(Agent.tenant_id == tenant_id)
    if active_only:
        stmt = stmt.where(Agent.active.is_(True))
    return list(session.scalars(stmt.order_by(Agent.name)))
