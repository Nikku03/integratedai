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
        # job results are readable by every principal of the tenant: no names, reasons or counts here
        return {"event_id": job.payload["event_id"], "seq": summary.get("seq"), "status": summary.get("status")}
    if job.kind == "agent_task":
        from cie.agents.runtime import run_task_job

        return run_task_job(session, job)
    raise RuntimeError(f"unknown job kind {job.kind}")


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
