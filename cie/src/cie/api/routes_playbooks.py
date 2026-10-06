"""Playbook routes: drafts, decisions and their proofs.

GET /playbooks, POST /playbooks (a draft from a spec), POST /playbooks/draft (a draft written by the configured model
from a document), GET /playbooks/{id}, POST /playbooks/{key}/decide, GET /playbooks/decisions/{id},
POST /playbooks/decisions/{id}/verify. A draft is approved or rejected through POST /approvals/{id}/decide
(kind ``playbook``). Writing playbooks is for admins; anyone may ask for a decision, which reads the live state under
their own permissions.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.api.deps import Auth, current_auth, db
from cie.playbooks import store
from cie.playbooks.models import Playbook, PlaybookDecision

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


class PlaybookIn(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    spec: dict[str, Any]
    source_document_ids: list[uuid.UUID] = []
    note: str = Field("", max_length=4000)


class DraftIn(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=1000)
    facts: dict[str, dict[str, Any]]
    decision: str = Field("may_proceed", max_length=64)
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)


class DecideIn(BaseModel):
    facts: dict[str, Any] = {}
    goal: str | None = Field(None, max_length=64)
    subject: str = Field("", max_length=300)


def _admin(auth: Auth) -> None:
    if not auth.visibility.is_admin:
        raise HTTPException(403, "admin only")


def _texts(session: Session, auth: Auth, ids: list[uuid.UUID]) -> list[tuple[str, str]]:
    from cie.api.routes_core import _get_doc
    from cie.core.models import Extraction, Section

    out = []
    for i in ids:
        d = _get_doc(session, auth, i)
        ex = session.scalar(select(Extraction.id).where(Extraction.document_id == d.id).order_by(Extraction.created_at.desc()).limit(1))
        secs = session.scalars(select(Section.text).where(Section.document_id == d.id, Section.extraction_id == ex).order_by(Section.order_index))
        out.append((d.title, "\n\n".join(secs)))
    return out


@router.get("")
def list_playbooks(status: str | None = None, key: str | None = None, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    stmt = select(Playbook).where(Playbook.tenant_id == auth.tenant_id)
    if status:
        stmt = stmt.where(Playbook.status == status)
    if key:
        stmt = stmt.where(Playbook.key == key)
    return [store.playbook_view(r) for r in session.scalars(stmt.order_by(Playbook.key, Playbook.version.desc()).limit(500))]


@router.post("", status_code=201)
def create_playbook(body: PlaybookIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    _admin(auth)
    texts = [t for _, t in _texts(session, auth, body.source_document_ids)] if body.source_document_ids else None
    row = store.save(session, auth.tenant_id, body.key, body.spec, drafted_by=f"user:{auth.principal.name}",
                     source_document_ids=body.source_document_ids, source_texts=texts, note=body.note, principal_id=auth.principal.id)
    return store.playbook_view(row, full=True)


@router.post("/draft", status_code=201)
def draft_playbook(body: DraftIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    """The configured model drafts the rules from the documents; the draft is stored for a person to approve."""
    from cie.agents.providers import get_provider
    from cie.core.settings import get_settings
    from cie.playbooks import draft

    _admin(auth)
    settings = get_settings()
    if settings.llm_provider == "none":
        raise HTTPException(409, "no language model is configured (CIE_LLM_PROVIDER): write the spec and POST /playbooks")
    docs = _texts(session, auth, body.document_ids)
    text = "\n\n".join(f"# {title}\n\n{t}" for title, t in docs)
    d = draft.draft(draft.from_provider(get_provider(settings)), text, question=body.question, facts=body.facts, decision=body.decision,
                    name=body.key, title="; ".join(t for t, _ in docs))
    row = store.save(session, auth.tenant_id, body.key, d.spec, drafted_by=f"model:{settings.llm_model}", source_document_ids=body.document_ids,
                     source_texts=[t for _, t in docs], note=("gaps: " + "; ".join(d.gaps)) if d.gaps else "", principal_id=auth.principal.id)
    return {**store.playbook_view(row, full=True), "gaps": d.gaps, "attempts": d.attempts}


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: uuid.UUID, proof: bool = False, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    dec = session.get(PlaybookDecision, decision_id)
    if dec is None or dec.tenant_id != auth.tenant_id or (dec.principal_id != auth.principal.id and not auth.visibility.is_admin):
        raise HTTPException(404, "decision not found")
    out = store.decision_view(dec, session.get(Playbook, dec.playbook_id))
    if proof:
        out["proof"] = dec.proof
    return out


@router.post("/decisions/{decision_id}/verify")
def verify_decision(decision_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    dec = session.get(PlaybookDecision, decision_id)
    if dec is None or dec.tenant_id != auth.tenant_id or (dec.principal_id != auth.principal.id and not auth.visibility.is_admin):
        raise HTTPException(404, "decision not found")
    errs = store.verify_decision(session, dec)
    return {"ok": not errs, "problems": errs, "steps": len((dec.proof or {}).get("steps") or [])}


@router.get("/{playbook_id}")
def get_playbook(playbook_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    row = session.get(Playbook, playbook_id)
    if row is None or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "playbook not found")
    return store.playbook_view(row, full=True)


@router.post("/{key}/decide")
def decide(key: str, body: DecideIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    try:
        dec = store.decide(session, auth.tenant_id, key, given=body.facts, goal=body.goal, subject=body.subject,
                           principal_id=auth.principal.id, requested_by=f"user:{auth.principal.name}")
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return store.decision_view(dec, session.get(Playbook, dec.playbook_id))
