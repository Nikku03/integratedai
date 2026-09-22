"""Retention policies, legal holds and the deletion workflow.

Deletion is a workflow, not a DELETE: a request is recorded, blocked by a
legal hold, gated by human approval, and executed as a soft delete of the
document plus its derived sections/records with the blob removed only when no
other document references it. Every step is audited.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from cie.core.models import Approval, Blob, DeletionRequest, Document, MemoryRecord, Section
from cie.core.util import utcnow
from cie.governance.audit import audit

POLICIES: dict[str, timedelta | None] = {
    "default": None,  # keep until deleted
    "7y": timedelta(days=365 * 7),
    "3y": timedelta(days=365 * 3),
    "1y": timedelta(days=365),
    "90d": timedelta(days=90),
}


def apply_policy(doc: Document, policy: str) -> None:
    if policy not in POLICIES:
        raise ValueError(f"unknown retention policy {policy}")
    doc.retention_policy = policy
    span = POLICIES[policy]
    doc.retain_until = (utcnow() + span) if span else None


def set_legal_hold(session: Session, doc: Document, on: bool, principal_id: uuid.UUID) -> None:
    doc.legal_hold = on
    audit(session, tenant_id=doc.tenant_id, principal_id=principal_id, action="legal_hold.set" if on else "legal_hold.clear",
          resource_kind="document", resource_id=doc.id)


def request_deletion(session: Session, doc: Document, principal_id: uuid.UUID, reason: str) -> DeletionRequest:
    req = DeletionRequest(tenant_id=doc.tenant_id, document_id=doc.id, requested_by=principal_id, reason=reason)
    if doc.legal_hold:
        req.status = "blocked_hold"
    else:
        approval = Approval(tenant_id=doc.tenant_id, kind="deletion", subject_id=str(doc.id), summary=f"Delete '{doc.title}': {reason}",
                            requested_by=str(principal_id))
        session.add(approval)
        session.flush()
        req.approval_id = approval.id
    session.add(req)
    session.flush()
    audit(session, tenant_id=doc.tenant_id, principal_id=principal_id, action="deletion.request", resource_kind="document",
          resource_id=doc.id, details={"status": req.status, "reason": reason})
    return req


def execute_deletion(session: Session, req: DeletionRequest, principal_id: uuid.UUID, vault=None) -> bool:
    doc = session.get(Document, req.document_id)
    if doc is None:
        return False
    if doc.legal_hold:
        req.status = "blocked_hold"
        return False
    approval = session.get(Approval, req.approval_id) if req.approval_id else None
    if approval is None or approval.status != "approved":
        return False
    now = utcnow()
    doc.deleted_at = now
    doc.status = "deleted"
    session.execute(update(MemoryRecord).where(MemoryRecord.source_document_id == doc.id).values(deleted_at=now))
    session.execute(Section.__table__.delete().where(Section.document_id == doc.id))
    refs = session.scalar(select(func.count(Document.id)).where(Document.blob_id == doc.blob_id, Document.deleted_at.is_(None))) or 0
    if refs == 0 and vault is not None:
        blob = session.get(Blob, doc.blob_id)
        if blob is not None:
            vault.backend.delete(blob.storage_uri)
            blob.storage_uri = "deleted://" + blob.sha256
    req.status = "executed"
    req.executed_at = now
    audit(session, tenant_id=doc.tenant_id, principal_id=principal_id, action="deletion.execute", resource_kind="document",
          resource_id=doc.id, details={"blob_removed": refs == 0})
    return True


def expired_documents(session: Session, tenant_id: uuid.UUID) -> list[Document]:
    return list(session.scalars(select(Document).where(Document.tenant_id == tenant_id, Document.deleted_at.is_(None),
                                                       Document.legal_hold.is_(False), Document.retain_until.is_not(None),
                                                       Document.retain_until < utcnow())))
