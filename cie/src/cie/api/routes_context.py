"""Context routes: build a task's or question's context, or scan a whole collection with recorded coverage.

POST /context, GET /context/runs/{id}. Everything is read with the caller's permissions.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cie.api.deps import Auth, current_auth, db
from cie.core.settings import Settings, get_settings
from cie.governance.audit import audit

router = APIRouter(prefix="/context", tags=["context"])


class ContextIn(BaseModel):
    question: str = Field("", max_length=4000)
    task_id: uuid.UUID | None = None
    entities: list[Any] = []
    project_keys: list[str] = []
    scope_id: uuid.UUID | None = None
    mode: Literal["focused", "exhaustive"] = "focused"
    collection: dict[str, Any] | None = None
    check: dict[str, Any] | None = None
    budget_tokens: int | None = Field(None, ge=200, le=200_000)
    model: str | None = None
    cursor: str | None = None


@router.post("")
def build(body: ContextIn, auth: Auth = Depends(current_auth), session: Session = Depends(db), settings: Settings = Depends(get_settings)):
    from cie.context.builder import ContextRequest, build_context
    from cie.core.models import Task
    from cie.memory.embeddings import get_embedding_provider

    if body.task_id is not None:
        t = session.get(Task, body.task_id)
        if t is None or t.tenant_id != auth.tenant_id or (t.scope_id is not None and not auth.visibility.can_write(t.scope_id)):
            raise HTTPException(404, "task not found")  # recording a task's inputs needs write access to it
    if body.scope_id is not None and body.scope_id not in auth.visibility.scope_ids:
        raise HTTPException(403, "no access to scope")
    if body.mode == "focused" and not (body.question or body.task_id or body.entities):
        raise HTTPException(400, "give a question, a task or entities")
    req = ContextRequest(question=body.question, task_id=body.task_id, entities=body.entities, project_keys=body.project_keys,
                         scope_id=body.scope_id, mode=body.mode, collection=body.collection, check=body.check,
                         budget_tokens=body.budget_tokens, model=body.model, cursor=body.cursor)
    try:
        ctx = build_context(session, auth.tenant_id, auth.principal, req, embedder=get_embedding_provider(settings), settings=settings)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, str(e)) from None
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="context.build", resource_kind="context_run",
          resource_id=ctx.run_id, details={"mode": body.mode, "complete": ctx.data.get("complete", ctx.data.get("coverage", {}).get("complete"))})
    return ctx.data


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.context.models import ContextRun

    r = session.get(ContextRun, run_id)
    if r is None or r.tenant_id != auth.tenant_id or (r.principal_id != auth.principal.id and not auth.visibility.is_admin):
        raise HTTPException(404, "not found")
    return {"id": str(r.id), "mode": r.mode, "task_id": str(r.task_id) if r.task_id else None, "request": r.request, "sources": r.sources,
            "coverage": r.coverage, "complete": r.complete, "snapshot_seq": r.snapshot_seq, "token_estimate": r.token_estimate,
            "created_at": r.created_at.isoformat() if r.created_at else None}
