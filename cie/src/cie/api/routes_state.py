"""Live state routes: events, entity views, conflicts and source authority.

POST /state/events, GET /state/events/{id}, GET /state/entities/{type}/{key}, GET /state/conflicts,
POST /state/conflicts/{id}/resolve, GET and PUT /state/authority. Reads are filtered by the caller's permissions.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.api.deps import Auth, current_auth, db
from cie.core.settings import Settings, get_settings
from cie.governance.audit import audit

router = APIRouter(prefix="/state", tags=["state"])


class EventIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=200)
    analysis: Literal["none", "rules", "reachability"] = "none"
    wait: bool = True  # process now; false queues it for the worker


class ResolveIn(BaseModel):
    accept: Literal["current", "challenger"]
    note: str = Field("", max_length=2000)
    idempotency_key: str | None = Field(None, max_length=200)


class AuthorityIn(BaseModel):
    entity_type: str = Field("*", max_length=32)
    field: str = Field("*", max_length=64)
    source_system: str = Field(min_length=1, max_length=64)
    rank: int = Field(ge=0, le=1000)
    note: str = Field("", max_length=500)


def _submit(session: Session, auth: Auth, settings: Settings, kind: str, payload: dict[str, Any], key: str, analysis: str,
            wait: bool) -> dict[str, Any]:
    from cie.state.events import (
        EVENT_KINDS,
        IdempotencyConflict,
        Unauthorized,
        authorize_ops,
        submit_event,
        translate,
    )
    from cie.state.store import GraphReader
    from cie.workers import queue

    if kind not in EVENT_KINDS:
        raise HTTPException(400, f"kind must be one of {EVENT_KINDS}")
    try:  # refused before it is stored; checked again under the tenant lock when it is applied
        authorize_ops(session, auth.tenant_id, auth.visibility, translate(kind, payload, GraphReader(session, auth.tenant_id, None)))
    except Unauthorized as e:
        raise HTTPException(403, str(e)) from None
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from None
    try:
        ev, created = submit_event(session, auth.tenant_id, kind=kind, payload=payload, idempotency_key=key, principal_id=auth.principal.id)
    except IdempotencyConflict as e:
        raise HTTPException(409, str(e)) from None
    job_id = None
    if created and wait:
        from cie.memory.embeddings import get_embedding_provider
        from cie.rem.change import process_event

        try:
            process_event(session, ev.id, embedder=get_embedding_provider(settings), policy=analysis)
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e)) from None
        if ev.status == "rejected":
            raise HTTPException(403, ev.error or "not allowed")
        if ev.status == "conflict":
            raise HTTPException(409, ev.error or "stale write")
    elif created:
        job_id = str(queue.enqueue(session, auth.tenant_id, "state_event", {"event_id": str(ev.id), "analysis": analysis}).id)
    s = ev.summary or {}
    return {"event_id": str(ev.id), "created": created, "status": ev.status, "seq": ev.seq, "job_id": job_id,
            "field_decisions": s.get("field_decisions", []) if ev.principal_id == auth.principal.id else []}


@router.post("/events", status_code=202)
def post_event(body: EventIn, auth: Auth = Depends(current_auth), session: Session = Depends(db),
               settings: Settings = Depends(get_settings)):
    return _submit(session, auth, settings, body.kind, body.payload, body.idempotency_key, body.analysis, body.wait)


@router.get("/events/{event_id}")
def get_event(event_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    """The submitter (or an administrator) sees the outcome; for anyone else the event does not exist."""
    from cie.state.models import RemEvent

    ev = session.get(RemEvent, event_id)
    if ev is None or ev.tenant_id != auth.tenant_id or not (ev.principal_id == auth.principal.id or auth.visibility.is_admin):
        raise HTTPException(404, "event not found")
    s = ev.summary or {}
    return {"event_id": str(ev.id), "kind": ev.kind, "status": ev.status, "seq": ev.seq, "error": ev.error,
            "field_decisions": s.get("field_decisions", []), "tasks": s.get("tasks", {}), "stale_results": s.get("stale_results", 0)}


@router.get("/entities/{entity_type}/{key}")
def get_entity(entity_type: str, key: str, history: bool = False, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.state.store import GraphReader
    from cie.state.views import entity_view

    view = entity_view(session, GraphReader(session, auth.tenant_id, auth.visibility), entity_type, key, history=history)
    if view is None:
        raise HTTPException(404, "not found")  # unknown and invisible look the same
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="state.read", resource_kind="rem_node",
          resource_id=uuid.UUID(view["id"]), details={"type": entity_type})
    return view


@router.get("/conflicts")
def list_conflicts(entity_type: str | None = None, limit: int = 100, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.state.store import GraphReader
    from cie.state.views import open_conflicts

    return {"conflicts": open_conflicts(session, GraphReader(session, auth.tenant_id, auth.visibility), entity_type, min(max(limit, 1), 500))}


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: uuid.UUID, body: ResolveIn, auth: Auth = Depends(current_auth), session: Session = Depends(db),
                     settings: Settings = Depends(get_settings)):
    key = body.idempotency_key or f"resolve:{conflict_id}:{body.accept}"
    return _submit(session, auth, settings, "ops", {"ops": [{"op": "resolve_conflict", "conflict": str(conflict_id), "accept": body.accept,
                                                             "note": body.note}]}, key, "none", True)


@router.get("/authority")
def get_authority(auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.state.fields import DEFAULT_KIND_RANK
    from cie.state.models import StateAuthority

    rows = session.scalars(select(StateAuthority).where(StateAuthority.tenant_id == auth.tenant_id)
                           .order_by(StateAuthority.entity_type, StateAuthority.field, StateAuthority.rank))
    return {"rules": [{"entity_type": r.entity_type, "field": r.field, "source_system": r.source_system, "rank": r.rank, "note": r.note}
                      for r in rows], "default_ranks": DEFAULT_KIND_RANK}


@router.put("/authority")
def put_authority(body: AuthorityIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.state.models import StateAuthority

    if not auth.visibility.is_admin:
        raise HTTPException(403, "only an administrator can change source authority")
    row = session.scalar(select(StateAuthority).where(StateAuthority.tenant_id == auth.tenant_id, StateAuthority.entity_type == body.entity_type,
                                                      StateAuthority.field == body.field, StateAuthority.source_system == body.source_system))
    if row is None:
        row = StateAuthority(tenant_id=auth.tenant_id, entity_type=body.entity_type, field=body.field, source_system=body.source_system,
                             rank=body.rank, note=body.note)
        session.add(row)
    else:
        row.rank, row.note = body.rank, body.note
    session.flush()
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="state.authority", resource_kind="state_authority",
          resource_id=row.id, details=body.model_dump())
    return {"ok": True}
