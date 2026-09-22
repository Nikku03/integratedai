"""Durable job queue on PostgreSQL (SKIP LOCKED leases, checkpoints, retries)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from cie.core.models import Job, JobStatus
from cie.core.util import utcnow

LEASE = timedelta(minutes=10)


def enqueue(session: Session, tenant_id: uuid.UUID, kind: str, payload: dict[str, Any],
            max_attempts: int = 5) -> Job:
    job = Job(tenant_id=tenant_id, kind=kind, status=JobStatus.queued, payload=payload, max_attempts=max_attempts)
    session.add(job)
    session.flush()
    return job


def claim(session: Session, worker_id: str, kinds: list[str] | None = None) -> Job | None:
    """Lease the next runnable job. Stale leases (worker died) are reclaimed."""
    stale = utcnow() - LEASE
    session.execute(
        update(Job).where(Job.status == JobStatus.running, Job.locked_at < stale)
        .values(status=JobStatus.queued, locked_by=None, locked_at=None)
    )
    stmt = (select(Job).where(Job.status == JobStatus.queued, Job.run_after <= utcnow())
            .order_by(Job.created_at).limit(1).with_for_update(skip_locked=True))
    if kinds:
        stmt = stmt.where(Job.kind.in_(kinds))
    job = session.scalar(stmt)
    if job is None:
        return None
    job.status = JobStatus.running
    job.locked_by = worker_id
    job.locked_at = utcnow()
    job.attempts += 1
    session.flush()
    return job


def checkpoint(session: Session, job: Job, data: dict[str, Any], progress: float | None = None) -> None:
    job.checkpoint = {**(job.checkpoint or {}), **data}
    job.locked_at = utcnow()  # heartbeat
    if progress is not None:
        job.progress = progress
    session.flush()
    session.commit()  # checkpoints are durable immediately


def complete(session: Session, job: Job, result: dict[str, Any] | None = None) -> None:
    job.status = JobStatus.done
    job.progress = 1.0
    if result:
        job.checkpoint = {**(job.checkpoint or {}), "result": result}
    job.locked_by = None
    session.flush()


def fail(session: Session, job: Job, error: str) -> None:
    job.last_error = error[:4000]
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.failed
    else:
        job.status = JobStatus.queued
        job.run_after = utcnow() + timedelta(seconds=min(300, 5 * 2 ** job.attempts))
    job.locked_by = None
    session.flush()


def stats(session: Session, tenant_id: uuid.UUID | None = None) -> dict[str, int]:
    q = "SELECT status, count(*) FROM jobs" + (" WHERE tenant_id = :t" if tenant_id else "") + " GROUP BY status"
    rows = session.execute(text(q), {"t": str(tenant_id)} if tenant_id else {}).all()
    return {str(r[0]): int(r[1]) for r in rows}
