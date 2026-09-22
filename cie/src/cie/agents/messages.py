"""Structured agent messages. Point to point; payloads are small and typed."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Agent, AgentMessage, MessageKind
from cie.core.util import estimate_tokens

REQUIRED_FIELDS: dict[MessageKind, set[str]] = {
    MessageKind.task_request: {"task_id", "brief", "evidence_packet_id"},
    MessageKind.evidence_request: {"task_id", "query"},
    MessageKind.intermediate_result: {"task_id", "findings"},
    MessageKind.dependency_notification: {"task_id", "depends_on_task_id", "status"},
    MessageKind.contradiction: {"task_id", "record_a", "record_b", "reason"},
    MessageKind.verification_request: {"task_id", "verifies_task_id"},
    MessageKind.final_result: {"task_id", "result"},
    MessageKind.failure_report: {"task_id", "error"},
}


def send(session: Session, *, tenant_id: uuid.UUID, project_id: uuid.UUID, kind: MessageKind | str, payload: dict,
         from_agent: Agent | None = None, to_agent: Agent | None = None, task_id: uuid.UUID | None = None) -> AgentMessage:
    kind = MessageKind(kind)
    missing = REQUIRED_FIELDS[kind] - set(payload)
    if missing:
        raise ValueError(f"{kind.value} message missing fields: {sorted(missing)}")
    import orjson

    msg = AgentMessage(tenant_id=tenant_id, project_id=project_id, task_id=task_id,
                       from_agent_id=from_agent.id if from_agent else None, to_agent_id=to_agent.id if to_agent else None,
                       kind=kind, payload=payload, token_estimate=estimate_tokens(orjson.dumps(payload).decode()))
    session.add(msg)
    session.flush()
    return msg


def inbox(session: Session, agent: Agent, project_id: uuid.UUID | None = None, kinds: list[MessageKind] | None = None) -> list[AgentMessage]:
    stmt = select(AgentMessage).where(AgentMessage.to_agent_id == agent.id)
    if project_id:
        stmt = stmt.where(AgentMessage.project_id == project_id)
    if kinds:
        stmt = stmt.where(AgentMessage.kind.in_(kinds))
    return list(session.scalars(stmt.order_by(AgentMessage.created_at)))
