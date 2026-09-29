"""Live state routes: events, entity views, conflicts and source authority.

POST /state/events, POST /state/domain-events, GET /state/events/{id}, GET /state/entities/{type}/{key}, GET /state/conflicts,
POST /state/conflicts/{id}/resolve, GET and PUT /state/authority, POST /state/identity/resolve,
GET /state/identity/proposals, POST /state/identity/proposals/{id}/confirm and /reject. Reads are filtered by the
caller's permissions.
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


class DomainEventIn(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    entity: Any
    version: int | None = None  # the record version the sender saw; a newer one refuses the event
    source: dict[str, Any]
    occurred_at: str | None = None
    data: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    idempotency_key: str | None = Field(None, max_length=200)
    analysis: Literal["none", "rules", "reachability"] = "none"


class ResolveIn(BaseModel):
    accept: Literal["current", "challenger"]
    note: str = Field("", max_length=2000)
    idempotency_key: str | None = Field(None, max_length=200)


class IdentityIn(BaseModel):
    type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=300)
    identifiers: dict[str, str] = {}


class DecideIn(BaseModel):
    canonical: uuid.UUID | None = None
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
    mine = ev.principal_id == auth.principal.id
    return {"event_id": str(ev.id), "created": created, "status": ev.status, "seq": ev.seq, "job_id": job_id,
            "field_decisions": s.get("field_decisions", []) if mine else [], "identity": s.get("identity", []) if mine else []}


@router.post("/events", status_code=202)
def post_event(body: EventIn, auth: Auth = Depends(current_auth), session: Session = Depends(db),
               settings: Settings = Depends(get_settings)):
    return _submit(session, auth, settings, body.kind, body.payload, body.idempotency_key, body.analysis, body.wait)


@router.post("/domain-events", status_code=202)
def post_domain_event(body: DomainEventIn, auth: Auth = Depends(current_auth), session: Session = Depends(db),
                      settings: Settings = Depends(get_settings)):
    """A typed business event (payment.confirmed, delivery.date_changed, ...). Without an idempotency key, the source
    system and record identify it, so the same notification delivered twice is applied once."""
    key = body.idempotency_key or (f"{body.type}:{body.source.get('system')}:{body.source['record']}" if body.source.get("record") else None)
    if not key:
        raise HTTPException(400, "give an idempotency_key or source.record")
    payload = body.model_dump(exclude={"idempotency_key", "analysis"})
    return _submit(session, auth, settings, "domain", payload, key, body.analysis, True)


@router.get("/events/{event_id}")
def get_event(event_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    """The submitter (or an administrator) sees the outcome; for anyone else the event does not exist."""
    from cie.state.models import RemEvent

    ev = session.get(RemEvent, event_id)
    if ev is None or ev.tenant_id != auth.tenant_id or not (ev.principal_id == auth.principal.id or auth.visibility.is_admin):
        raise HTTPException(404, "event not found")
    s = ev.summary or {}
    return {"event_id": str(ev.id), "kind": ev.kind, "status": ev.status, "seq": ev.seq, "error": ev.error,
            "field_decisions": s.get("field_decisions", []), "identity": s.get("identity", []), "tasks": s.get("tasks", {}),
            "stale_results": s.get("stale_results", 0)}


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


@router.post("/identity/resolve")
def identity_resolve(body: IdentityIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    """Dry run: would this description match a known entity? Nothing is written. Possible matches are reported only
    for records the caller may see; a match on a record the caller may not see is reported without details."""
    from cie.state.identity import resolve_entity
    from cie.state.store import GraphReader

    reader = GraphReader(session, auth.tenant_id, auth.visibility)
    try:
        res = resolve_entity(session, auth.tenant_id, body.type, body.name, body.identifiers, reader=reader)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    node = reader.nodes([res.node_id]).get(res.node_id) if res.node_id else None
    return {"status": res.status, "method": res.method,
            "record": {"id": str(node.id), "key": node.key, "name": node.name} if node else None,
            "note": "matches a record you may not see" if res.node_id and node is None else "",
            "possible_matches": [{"id": str(c.node_id), "key": c.key, "name": c.name, "score": c.score, "method": c.method,
                                  "reasons": c.reasons} for c in res.candidates],
            "distinct_from": res.distinct if res.status != "conflicting_identifiers" else []}


@router.get("/identity/proposals")
def identity_proposals(status: str = "proposed", limit: int = 100, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.state.models import StateMatchProposal
    from cie.state.store import GraphReader

    rows = list(session.scalars(select(StateMatchProposal).where(StateMatchProposal.tenant_id == auth.tenant_id,
                                                                 StateMatchProposal.status == status)
                                .order_by(StateMatchProposal.score.desc()).limit(min(max(limit, 1), 500) * 3)))
    reader = GraphReader(session, auth.tenant_id, auth.visibility)
    nodes = reader.nodes({r.a_id for r in rows} | {r.b_id for r in rows})
    out = []
    for r in rows:
        a, b = nodes.get(r.a_id), nodes.get(r.b_id)
        if a is None or b is None:
            continue  # both records must be visible
        out.append({"proposal_id": str(r.id), "type": r.entity_type, "score": r.score, "method": r.method, "reasons": r.reasons,
                    "status": r.status, "a": {"id": str(a.id), "key": a.key, "name": a.name}, "b": {"id": str(b.id), "key": b.key, "name": b.name}})
    return {"proposals": out[:limit]}


@router.post("/identity/proposals/{proposal_id}/confirm")
def identity_confirm(proposal_id: uuid.UUID, body: DecideIn, auth: Auth = Depends(current_auth), session: Session = Depends(db),
                     settings: Settings = Depends(get_settings)):
    op = {"op": "confirm_match", "proposal": str(proposal_id), "note": body.note, **({"canonical": str(body.canonical)} if body.canonical else {})}
    return _submit(session, auth, settings, "ops", {"ops": [op]}, body.idempotency_key or f"confirm:{proposal_id}", "none", True)


@router.post("/identity/proposals/{proposal_id}/reject")
def identity_reject(proposal_id: uuid.UUID, body: DecideIn, auth: Auth = Depends(current_auth), session: Session = Depends(db),
                    settings: Settings = Depends(get_settings)):
    op = {"op": "reject_match", "proposal": str(proposal_id), "note": body.note}
    return _submit(session, auth, settings, "ops", {"ops": [op]}, body.idempotency_key or f"reject:{proposal_id}", "none", True)
