"""Worker loop: claims jobs and dispatches by kind."""

from __future__ import annotations

import socket
import time
import traceback
import uuid

from sqlalchemy.orm import Session

from cie.core.db import session_scope
from cie.core.logging import get_logger
from cie.core.models import Document, Job
from cie.workers import queue

log = get_logger(__name__)


def handle(session: Session, job: Job, **deps) -> dict:
    if job.kind == "extract_document":
        from cie.extraction.pipeline import run_extraction

        doc = session.get(Document, uuid.UUID(job.payload["document_id"]))
        if doc is None:
            raise RuntimeError("document not found")
        out = run_extraction(session, doc, job=job, **{k: v for k, v in deps.items() if k in ("vault", "embedder", "settings", "ocr")})
        return {"sections": out.sections, "records": out.records, "completeness": out.completeness}
    if job.kind == "rem_change":
        from cie.memory.embeddings import get_embedding_provider
        from cie.rem.change import process_event

        summary = process_event(session, uuid.UUID(job.payload["event_id"]), embedder=deps.get("embedder") or get_embedding_provider())
        resume_projects(session, job.tenant_id, summary)
        # job results are readable by every principal of the tenant: no names, reasons or counts here
        return {"event_id": job.payload["event_id"], "seq": summary.get("seq"), "status": summary.get("status")}
    if job.kind == "state_event":
        from cie.memory.embeddings import get_embedding_provider
        from cie.rem.change import process_event

        summary = process_event(session, uuid.UUID(job.payload["event_id"]), embedder=deps.get("embedder") or get_embedding_provider(),
                                policy=job.payload.get("analysis", "none"))
        resume_projects(session, job.tenant_id, summary)
        return {"event_id": job.payload["event_id"], "seq": summary.get("seq"), "status": summary.get("status")}
    if job.kind == "agent_task":
        from cie.agents.runtime import run_task_job

        return run_task_job(session, job)
    if job.kind == "execute_action":
        from cie.actions.connectors import connectors_from_settings
        from cie.actions.gateway import execute
        from cie.core.settings import get_settings

        a = execute(session, uuid.UUID(job.payload["action_id"]), connectors=deps.get("connectors") or connectors_from_settings(get_settings()),
                    actor=f"worker:{job.id}")
        return {"action_id": str(a.id), "status": a.status}
    raise RuntimeError(f"unknown job kind {job.kind}")


def queue_head_run(session: Session, tenant_id: uuid.UUID, project_id: uuid.UUID, reason: str) -> bool:
    """Queue one run of the project's head, unless one is already queued. Returns whether one was queued."""
    from sqlalchemy import select

    from cie.core.models import Job, JobStatus
    from cie.workers import queue

    queued = {j.payload.get("project_id") for j in session.scalars(select(Job).where(
        Job.tenant_id == tenant_id, Job.kind == "agent_task", Job.status == JobStatus.queued))}
    if str(project_id) in queued:
        return False
    queue.enqueue(session, tenant_id, "agent_task", {"project_id": str(project_id), "max_steps": 20, "reason": reason})
    return True


def resume_projects(session: Session, tenant_id: uuid.UUID, summary: dict) -> list[uuid.UUID]:
    """A change reopened tasks: queue a run of each project's head, so the reopened work is redone without anyone
    asking. A project that already has a run queued is not queued again."""
    from sqlalchemy import select

    from cie.core.models import Task

    ids = [uuid.UUID(x) for x in (summary.get("tasks") or {}).get("reopened", [])]
    if not ids:
        return []
    projects = {p for (p,) in session.execute(select(Task.project_id).where(Task.id.in_(ids))).all()}
    return [p for p in sorted(projects, key=str) if queue_head_run(session, tenant_id, p, "inputs changed")]


def run_once(session: Session, worker_id: str, kinds: list[str] | None = None, **deps) -> Job | None:
    job = queue.claim(session, worker_id, kinds)
    if job is None:
        return None
    try:
        result = handle(session, job, **deps)
        queue.complete(session, job, result)
        session.commit()
    except Exception as e:  # noqa: BLE001 - worker must survive any job failure
        session.rollback()
        job = session.get(Job, job.id)
        queue.fail(session, job, f"{e}\n{traceback.format_exc()[-2000:]}")
        session.commit()
        log.warning("job.failed", job_id=str(job.id), kind=job.kind, error=str(e))
    return job


def drain(session_factory=session_scope, worker_id: str | None = None, kinds: list[str] | None = None, **deps) -> int:
    """Run until the queue is empty. Returns number of jobs processed."""
    worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
    n = 0
    while True:
        with session_factory() as s:
            job = run_once(s, worker_id, kinds, **deps)
        if job is None:
            return n
        n += 1


def main_loop(poll_seconds: float = 2.0) -> None:  # pragma: no cover - service entrypoint
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
    log.info("worker.start", worker_id=worker_id)
    while True:
        n = drain(worker_id=worker_id)
        if n == 0:
            time.sleep(poll_seconds)
