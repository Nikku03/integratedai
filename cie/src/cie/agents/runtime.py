"""Queue integration: run a project or a task step as a durable job."""

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
