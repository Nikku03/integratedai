"""REM routes: dependency exploration, evidence selection and change-impact tracking.

POST /rem/query, POST /rem/changes, GET /rem/impacts/{event_id}, GET /rem/explanations/{result_id}.
Every read is filtered by the caller's permissions at read time, including stored results and impacts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cie.api.deps import Auth, current_auth, db
from cie.core.settings import Settings, get_settings
from cie.governance.audit import audit

router = APIRouter(prefix="/rem", tags=["rem"])


class Limits(BaseModel):
    max_depth: int = Field(3, ge=0, le=3)
    max_visited: int = Field(400, ge=1, le=20000)
    max_tokens: int = Field(4000, ge=50, le=200000)
    max_db_calls: int = Field(120, ge=1, le=5000)
    max_ms: int = Field(5000, ge=10, le=120000)


class QueryIn(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    policy: Literal["search", "traversal", "rem", "rem+routing"] | None = None
    project_keys: list[str] = []
    as_of: datetime | None = None
    snapshot_seq: int | None = None
    limits: Limits = Limits()
    weights: dict[str, float] = {}
    start_k: int = Field(12, ge=1, le=200)
    targeted_searches: list[str] = []
    resume_from: uuid.UUID | None = None


class ChangeIn(BaseModel):
    kind: Literal["ops", "supplier_delay", "stock_count", "task_status", "restrict"]
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=200)
    wait: bool = False  # process now instead of through the worker queue


def _policy(requested: str | None, settings: Settings) -> str:
    policy = requested or ("rem" if settings.rem_policy_enabled else "traversal")
    if policy == "rem" and not settings.rem_policy_enabled:
        raise HTTPException(400, "the REM priority policy is disabled (CIE_REM_POLICY_ENABLED); use 'traversal' or 'search'")
    if policy == "rem+routing" and not settings.rem_routing_enabled:
        raise HTTPException(400, "routing shortcuts are disabled (CIE_REM_ROUTING_ENABLED)")
    return policy


@router.post("/query")
def rem_query(body: QueryIn, auth: Auth = Depends(current_auth), session: Session = Depends(db),
              settings: Settings = Depends(get_settings)):
    from cie.memory.embeddings import get_embedding_provider
    from cie.rem.query import QueryRequest, run_query

    req = QueryRequest(question=body.question, policy=_policy(body.policy, settings), project_keys=body.project_keys,
                       as_of=body.as_of, snapshot_seq=body.snapshot_seq, limits=body.limits.model_dump(), weights=body.weights,
                       start_k=body.start_k, targeted_searches=body.targeted_searches, resume_from=body.resume_from)
    try:
        out = run_query(session, auth.tenant_id, auth.visibility, req, embedder=get_embedding_provider(settings),
                        principal_id=auth.principal.id)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from None
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="rem.query", resource_kind="rem_result",
          resource_id=out["result_id"], details={"policy": req.policy, "status": out.get("status"), "snapshot_seq": out["snapshot_seq"]})
    return out


def _check_write(session: Session, auth: Auth, body: ChangeIn) -> None:
    """A change may only touch scopes the caller can write to."""
    from sqlalchemy import select

    from cie.core.models import Scope

    names = set()
    for op in body.payload.get("ops", []) if isinstance(body.payload, dict) else []:
        if op.get("scope"):
            names.add(str(op["scope"]))
    if body.payload.get("scope"):
        names.add(str(body.payload["scope"]))
    if not names and not any(auth.visibility.can_write(s) for s in auth.visibility.scope_ids):
        raise HTTPException(403, "write access required")
    for n in names:
        try:
            sid = uuid.UUID(n)
        except ValueError:
            sid = session.scalar(select(Scope.id).where(Scope.tenant_id == auth.tenant_id, Scope.name == n))
        if sid is None or not auth.visibility.can_write(sid):
            raise HTTPException(403, f"write access required on scope {n!r}")


@router.post("/changes", status_code=202)
def rem_change(body: ChangeIn, auth: Auth = Depends(current_auth), session: Session = Depends(db),
               settings: Settings = Depends(get_settings)):
    from cie.rem.change import IdempotencyConflict, process_event, submit_event
    from cie.workers import queue

    _check_write(session, auth, body)
    try:
        ev, created = submit_event(session, auth.tenant_id, kind=body.kind, payload=body.payload,
                                   idempotency_key=body.idempotency_key, principal_id=auth.principal.id)
    except IdempotencyConflict as e:
        raise HTTPException(409, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    job_id = None
    if created and body.wait:
        from cie.memory.embeddings import get_embedding_provider

        try:
            process_event(session, ev.id, embedder=get_embedding_provider(settings))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    elif created:
        job_id = str(queue.enqueue(session, auth.tenant_id, "rem_change", {"event_id": str(ev.id)}).id)
    return {"event_id": str(ev.id), "created": created, "status": ev.status, "seq": ev.seq, "job_id": job_id}


@router.get("/impacts/{event_id}")
def rem_impacts(event_id: uuid.UUID, include_superseded: bool = False, auth: Auth = Depends(current_auth),
                session: Session = Depends(db)):
    from cie.rem.change import visible_impacts
    from cie.rem.models import RemEvent
    from cie.rem.store import GraphReader

    ev = session.get(RemEvent, event_id)
    if ev is None or ev.tenant_id != auth.tenant_id:
        raise HTTPException(404, "event not found")
    reader = GraphReader(session, auth.tenant_id, auth.visibility)
    impacts, tasks = visible_impacts(session, reader, ev.id, include_superseded=include_superseded,
                                     suggestion_keys=(ev.summary or {}).get("suggestion_keys"))
    changed = [uuid.UUID(x) for x in (ev.summary or {}).get("changed", {})]
    seen = reader.nodes(changed) if changed else {}
    s = ev.summary or {}
    return {"event_id": str(ev.id), "kind": ev.kind, "status": ev.status, "seq": ev.seq, "snapshot_seq": reader.seq,
            "processing": {k: s.get(k) for k in ("status", "stopping_reason", "budget", "policy")},
            "changed": [{"id": str(n.id), "type": n.type, "key": n.key, "name": n.name, "fields": s["changed"][str(n.id)]}
                        for n in seen.values()],
            "impacts": impacts, "suggested_tasks": tasks,
            "note": "items that would reveal records you may not see are omitted"}


@router.get("/explanations/{result_id}")
def rem_explanation(result_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.rem.models import RemResult
    from cie.rem.query import redact, requires_of
    from cie.rem.store import GraphReader

    r = session.get(RemResult, result_id)
    if r is None or r.tenant_id != auth.tenant_id:
        raise HTTPException(404, "result not found")
    if r.principal_id != auth.principal.id and not auth.visibility.is_admin:
        raise HTTPException(403, "only the requester or an administrator can read this explanation")
    reader = GraphReader(session, auth.tenant_id, auth.visibility)  # current permissions, current snapshot
    ids = requires_of(r.output or {})
    trace_ids = {x.get("node") for part in (r.trace or {}).values() for x in part if isinstance(x, dict)}
    ids |= {i for i in trace_ids if i}
    wanted = [uuid.UUID(i) for i in ids]
    seen = reader.nodes(wanted) if wanted else {}
    if set(wanted) - set(seen):  # records deleted since the result: judged on their last recorded version
        seen.update(reader.nodes_latest(set(wanted) - set(seen)))
    visible = {str(k) for k in seen}
    trace = {k: [x for x in v if not isinstance(x, dict) or x.get("node") in visible] for k, v in (r.trace or {}).items()}
    return {"result_id": str(r.id), "mode": r.mode, "policy": r.policy, "snapshot_seq": r.snapshot_seq, "current_seq": reader.seq,
            "request": r.request, "status": r.status, "stopping_reason": r.stopping_reason, "stale": r.stale,
            "stale_reason": r.stale_reason, "parent_id": str(r.parent_id) if r.parent_id else None,
            "output": redact(r.output or {}, visible), "trace": trace,
            "reproduce": {"endpoint": "POST /rem/query", "body": {**r.request, "snapshot_seq": r.snapshot_seq}},
            "note": "filtered with your current permissions; re-running the request at snapshot_seq reproduces the read"}
