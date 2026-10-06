"""Governance routes: approvals, legal holds, retention, deletion workflow, scanners."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.api.deps import Auth, current_auth, db
from cie.api.routes_core import _get_doc, _vault
from cie.core.models import Approval, DeletionRequest
from cie.core.util import utcnow
from cie.governance import retention
from cie.governance.audit import audit

router = APIRouter()


class Decision(BaseModel):
    approve: bool
    reason: str | None = None


class DeletionIn(BaseModel):
    document_id: uuid.UUID
    reason: str


@router.get("/approvals")
def list_approvals(status: str | None = "pending", auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    stmt = select(Approval).where(Approval.tenant_id == auth.tenant_id)
    if status:
        stmt = stmt.where(Approval.status == status)
    rows = session.scalars(stmt.order_by(Approval.created_at.desc()).limit(200))
    return [{"id": str(a.id), "kind": a.kind, "subject_id": a.subject_id, "status": a.status, "summary": a.summary,
             "requested_by": a.requested_by, "created_at": a.created_at.isoformat(),
             "decided_at": a.decided_at.isoformat() if a.decided_at else None, "reason": a.reason} for a in rows]


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: uuid.UUID, body: Decision, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    if not auth.visibility.is_admin:
        raise HTTPException(403, "admin only")
    a = session.get(Approval, approval_id)
    if a is None or a.tenant_id != auth.tenant_id:
        raise HTTPException(404, "approval not found")
    if a.status != "pending":
        raise HTTPException(409, "already decided")
    a.status = "approved" if body.approve else "rejected"
    a.decided_by, a.decided_at, a.reason = auth.principal.id, utcnow(), body.reason
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="approval.decide", resource_kind="approval",
          resource_id=a.id, details={"status": a.status, "kind": a.kind, "subject": a.subject_id})
    if a.kind == "deletion":
        req = session.scalar(select(DeletionRequest).where(DeletionRequest.approval_id == a.id))
        if req is not None:
            if body.approve:
                retention.execute_deletion(session, req, auth.principal.id, vault=_vault())
            else:
                req.status = "rejected"
    if a.kind == "question":  # the person's reason is the answer; it goes to the asking agent's inbox
        from cie.agents import messages
        from cie.core.models import Agent, AgentMessage, MessageKind

        q = session.get(AgentMessage, uuid.UUID(a.subject_id))
        asker = session.get(Agent, q.from_agent_id) if q is not None and q.from_agent_id else None
        if asker is not None:
            messages.send(session, tenant_id=a.tenant_id, project_id=q.project_id, kind=MessageKind.answer, task_id=q.task_id, to_agent=asker,
                          payload={"task_id": str(q.task_id), "question": q.payload.get("question", ""),
                                   "answer": (body.reason or "") if body.approve else f"not answered: {body.reason or 'declined'}",
                                   "by": auth.principal.name})
        if q is not None and q.task_id:  # a task waiting for this answer goes on; the project's work is resumed
            from cie.workers.worker import queue_head_run
            from cie.workflow import engine

            engine.answered(session, q.task_id, q.id)
            queue_head_run(session, a.tenant_id, q.project_id, reason="a question was answered")
    if a.kind == "action":  # approve: the action may be executed (the worker does it); reject: it never is
        from cie.actions import gateway

        try:
            gateway.decide(session, uuid.UUID(a.subject_id), approve=body.approve, by=f"user:{auth.principal.name}", reason=body.reason or "")
        except ValueError:
            pass  # no longer awaiting approval (cancelled meanwhile): the approval is still recorded
    if a.kind == "playbook":  # approve: this version decides from now on; reject: it never does
        from cie.playbooks import store as playbooks

        try:
            playbooks.approve(session, uuid.UUID(a.subject_id), approve=body.approve, by=f"user:{auth.principal.name}",
                              principal_id=auth.principal.id, reason=body.reason or "")
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
    if a.kind == "replan":  # approve: accept the best option found; reject: drop the task (relaxing is POST /tasks/{id}/replan)
        from cie.core.models import Task, TaskStatus
        from cie.workflow import engine

        t = session.get(Task, uuid.UUID(a.subject_id))
        if t is not None and t.status == TaskStatus.review and (t.verification or {}).get("infeasible"):
            a.status = "pending"  # resolve_infeasible closes it with the decision
            engine.resolve_infeasible(session, t.id, decision="accept_best" if body.approve else "drop", actor=f"user:{auth.principal.name}",
                                      reason=body.reason or "")
            a.status = "approved" if body.approve else "rejected"
    if a.kind == "task_result":
        from cie.core.models import Task, TaskStatus
        from cie.workflow import engine

        t = session.get(Task, uuid.UUID(a.subject_id))
        if t is not None and t.status == TaskStatus.review:  # the person is the reviewer of last resort
            engine.review(session, t.id, reviewer=f"user:{auth.principal.name}", verdict="passed" if body.approve else "failed",
                          notes=body.reason or ("approved" if body.approve else "rejected"))
            t.verification = {**(t.verification or {}), ("human_approved_by" if body.approve else "human_rejected_by"): auth.principal.name}
            if t.status == TaskStatus.completed:
                from cie.agents.publication import publish

                publish(session, t, verifier=f"user:{auth.principal.name}", human=True)
    return {"id": str(a.id), "status": a.status}


@router.post("/documents/{document_id}/legal-hold")
def legal_hold(document_id: uuid.UUID, on: bool = True, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    if not auth.visibility.is_admin:
        raise HTTPException(403, "admin only")
    d = _get_doc(session, auth, document_id)
    retention.set_legal_hold(session, d, on, auth.principal.id)
    return {"id": str(d.id), "legal_hold": d.legal_hold}


@router.post("/documents/{document_id}/retention")
def set_retention(document_id: uuid.UUID, policy: str, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    d = _get_doc(session, auth, document_id)
    if not auth.visibility.can_write(d.scope_id):
        raise HTTPException(403, "write access required")
    try:
        retention.apply_policy(d, policy)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="retention.set", resource_kind="document",
          resource_id=d.id, details={"policy": policy})
    return {"id": str(d.id), "retention_policy": d.retention_policy, "retain_until": d.retain_until.isoformat() if d.retain_until else None}


@router.post("/deletion-requests")
def request_deletion(body: DeletionIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    d = _get_doc(session, auth, body.document_id)
    if not auth.visibility.can_write(d.scope_id):
        raise HTTPException(403, "write access required")
    req = retention.request_deletion(session, d, auth.principal.id, body.reason)
    return {"id": str(req.id), "status": req.status, "approval_id": str(req.approval_id) if req.approval_id else None}


@router.get("/deletion-requests")
def list_deletion_requests(auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    rows = session.scalars(select(DeletionRequest).where(DeletionRequest.tenant_id == auth.tenant_id).order_by(DeletionRequest.created_at.desc()))
    return [{"id": str(r.id), "document_id": str(r.document_id), "status": r.status, "reason": r.reason,
             "approval_id": str(r.approval_id) if r.approval_id else None, "created_at": r.created_at.isoformat(),
             "executed_at": r.executed_at.isoformat() if r.executed_at else None} for r in rows]


@router.get("/documents/{document_id}/flags")
def document_flags(document_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    d = _get_doc(session, auth, document_id)
    return {"injection": d.injection_flags, "pii_and_secrets": d.pii_flags}


@router.get("/retention/expired")
def expired(auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    if not auth.visibility.is_admin:
        raise HTTPException(403, "admin only")
    return [{"id": str(d.id), "title": d.title, "retain_until": d.retain_until.isoformat()} for d in retention.expired_documents(session, auth.tenant_id)]
