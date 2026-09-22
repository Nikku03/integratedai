"""Core routes: health, scopes, ingestion, documents, jobs/OCR status, memory
records, search, evidence, answers, source viewing, audit, permissions, metrics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cie.api import schemas as S
from cie.api.deps import Auth, current_auth, db, require_scope_write
from cie.core.models import (
    Answer,
    AuditLog,
    Block,
    Correction,
    Document,
    EvidencePacket,
    Extraction,
    Job,
    JobStatus,
    LinkKind,
    MemoryRecord,
    Metric,
    Page,
    Permission,
    Principal,
    PrincipalKind,
    Role,
    Scope,
)
from cie.core.settings import get_settings
from cie.governance.audit import audit
from cie.governance.permissions import AccessDenied, ensure_role, grant_role
from cie.memory import records as R
from cie.memory.embeddings import get_embedding_provider
from cie.memory.scopes import create_scope
from cie.retrieval.pipeline import Retriever
from cie.vault.service import VaultService
from cie.workers import queue

router = APIRouter()


def _vault() -> VaultService:
    return VaultService(get_settings())


@router.get("/health")
def health(session: Session = Depends(db)) -> dict:
    session.execute(select(1))
    return {"status": "ok", "version": "0.1.0"}


# ---------------------------------------------------------------- scopes
@router.post("/scopes", response_model=S.ScopeOut)
def create_scope_route(body: S.ScopeIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    if body.parent_id is not None:
        require_scope_write(auth, body.parent_id)
    elif not auth.visibility.is_admin:
        raise HTTPException(403, "only admins create company scopes")
    sc = create_scope(session, auth.tenant_id, body.kind, body.name, body.parent_id, body.attributes)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="scope.create", resource_kind="scope", resource_id=sc.id)
    return S.ScopeOut(id=sc.id, kind=sc.kind.value, name=sc.name, parent_id=sc.parent_id, path=sc.path)


@router.get("/scopes", response_model=list[S.ScopeOut])
def list_scopes(auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    ids = list(auth.visibility.scope_ids)
    rows = session.scalars(select(Scope).where(Scope.id.in_(ids)).order_by(Scope.path)) if ids else []
    return [S.ScopeOut(id=s.id, kind=s.kind.value, name=s.name, parent_id=s.parent_id, path=s.path) for s in rows]


# ---------------------------------------------------------------- ingestion
def _doc_out(session: Session, d: Document) -> S.DocumentOut:
    b = d.blob
    return S.DocumentOut(
        id=d.id, family_id=d.family_id, version=d.version, title=d.title, original_filename=d.original_filename,
        original_location=d.original_location, source=d.source, scope_id=d.scope_id, department_id=d.department_id,
        project_id=d.project_id, doc_type=d.doc_type, language=d.language, sensitivity=d.sensitivity, status=d.status,
        sha256=b.sha256, size_bytes=b.size_bytes, media_type=b.media_type, ingested_at=d.ingested_at,
        file_created_at=d.file_created_at, retention_policy=d.retention_policy, legal_hold=d.legal_hold,
        injection_flags=len(d.injection_flags or []), pii_flags=len(d.pii_flags or []))


@router.post("/ingest", response_model=S.IngestOut)
async def ingest(file: UploadFile = File(...), scope_id: uuid.UUID = Form(...), title: str | None = Form(None),
                 doc_type: str | None = Form(None), sensitivity: int = Form(1), source: str = Form("upload"),
                 original_location: str | None = Form(None), family_id: uuid.UUID | None = Form(None),
                 retention_policy: str = Form("default"), file_created_at: datetime | None = Form(None),
                 auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    require_scope_write(auth, scope_id)
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    res = _vault().ingest(session, tenant_id=auth.tenant_id, data=data, filename=file.filename or "upload",
                          scope_id=scope_id, owner_id=auth.principal.id, source=source, original_location=original_location,
                          title=title, doc_type=doc_type, sensitivity=sensitivity, retention_policy=retention_policy,
                          file_created_at=file_created_at, family_id=family_id)
    job = None
    if res.created:
        job = queue.enqueue(session, auth.tenant_id, "extract_document", {"document_id": str(res.document.id)})
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="ingest", resource_kind="document",
          resource_id=res.document.id, details={"created": res.created, "dedup": res.deduplicated, "job": str(job.id) if job else None})
    return S.IngestOut(document=_doc_out(session, res.document), created=res.created, deduplicated=res.deduplicated,
                       job_id=job.id if job else None)


@router.get("/documents", response_model=list[S.DocumentOut])
def list_documents(scope_id: uuid.UUID | None = None, status: str | None = None, limit: int = 100,
                   auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    ids = list(auth.visibility.scope_ids)
    if not ids:
        return []
    stmt = select(Document).where(Document.tenant_id == auth.tenant_id, Document.deleted_at.is_(None),
                                  auth.visibility.sql_filter(Document.scope_id, Document.sensitivity))
    if scope_id:
        stmt = stmt.where(Document.scope_id == scope_id)
    if status:
        stmt = stmt.where(Document.status == status)
    docs = session.scalars(stmt.order_by(Document.ingested_at.desc()).limit(limit))
    return [_doc_out(session, d) for d in docs if auth.visibility.can_read(d.scope_id, d.sensitivity, d.acl)]


def _get_doc(session: Session, auth: Auth, document_id: uuid.UUID) -> Document:
    d = session.get(Document, document_id)
    if d is None or d.tenant_id != auth.tenant_id or d.deleted_at is not None:
        raise HTTPException(404, "document not found")
    if not auth.visibility.can_read(d.scope_id, d.sensitivity, d.acl):
        audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="document.read",
              resource_kind="document", resource_id=d.id, outcome="denied")
        session.commit()  # denials are audited even though the request fails
        raise HTTPException(403, "no access to document")
    return d


@router.get("/documents/{document_id}", response_model=S.DocumentOut)
def get_document(document_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    return _doc_out(session, _get_doc(session, auth, document_id))


@router.get("/documents/{document_id}/versions", response_model=list[S.DocumentOut])
def document_versions(document_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    d = _get_doc(session, auth, document_id)
    return [_doc_out(session, v) for v in _vault().versions(session, d.family_id)]


@router.get("/documents/{document_id}/extraction")
def extraction_status(document_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    d = _get_doc(session, auth, document_id)
    ex = session.scalar(select(Extraction).where(Extraction.document_id == d.id).order_by(Extraction.created_at.desc()))
    job = session.scalar(select(Job).where(Job.payload["document_id"].astext == str(d.id)).order_by(Job.created_at.desc()))
    return {"document_id": str(d.id), "status": d.status,
            "extraction": None if ex is None else {"id": str(ex.id), "extractor": ex.extractor, "status": ex.status,
                                                    "page_count": ex.page_count, "pages_done": ex.pages_done,
                                                    "language": ex.language, "mean_confidence": ex.mean_confidence,
                                                    "completeness": ex.completeness, "stats": ex.stats},
            "job": None if job is None else _job_out(job).model_dump()}


def _job_out(j: Job) -> S.JobOut:
    return S.JobOut(id=j.id, kind=j.kind, status=j.status.value, progress=j.progress, attempts=j.attempts,
                    checkpoint=j.checkpoint or {}, last_error=j.last_error, created_at=j.created_at, updated_at=j.updated_at)


@router.get("/jobs", response_model=list[S.JobOut])
def list_jobs(status: str | None = None, limit: int = 100, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    stmt = select(Job).where(Job.tenant_id == auth.tenant_id)
    if status:
        stmt = stmt.where(Job.status == JobStatus(status))
    return [_job_out(j) for j in session.scalars(stmt.order_by(Job.created_at.desc()).limit(limit))]


@router.get("/jobs/{job_id}", response_model=S.JobOut)
def get_job(job_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    j = session.get(Job, job_id)
    if j is None or j.tenant_id != auth.tenant_id:
        raise HTTPException(404, "job not found")
    return _job_out(j)


@router.post("/jobs/run", summary="Process queued jobs inline (development helper)")
def run_jobs(max_jobs: int = 10, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.workers.worker import run_once

    if not auth.visibility.is_admin:
        raise HTTPException(403, "admin only")
    done = []
    for _ in range(max_jobs):
        j = run_once(session, f"api-{auth.principal.id.hex[:6]}", vault=_vault(), embedder=get_embedding_provider())
        if j is None:
            break
        done.append(_job_out(j))
    return done


# ---------------------------------------------------------------- memory records
def _rec_out(r: MemoryRecord) -> S.RecordOut:
    return S.RecordOut(id=r.id, scope_id=r.scope_id, type=r.type.value, summary=r.summary, content=r.content, detail=r.detail,
                       source_document_id=r.source_document_id, source_locations=r.source_locations, event_time=r.event_time,
                       valid_from=r.valid_from, valid_to=r.valid_to, recorded_at=r.recorded_at, producing_agent=r.producing_agent,
                       confidence=r.confidence, verification=r.verification.value, sensitivity=r.sensitivity, version=r.version,
                       family_id=r.family_id, superseded_by_id=r.superseded_by_id, supersedes_id=r.supersedes_id,
                       keywords=list(r.keywords or []), glyph=r.glyph or {})


def _get_rec(session: Session, auth: Auth, rid: uuid.UUID) -> MemoryRecord:
    r = session.get(MemoryRecord, rid)
    if r is None or r.tenant_id != auth.tenant_id or r.deleted_at is not None:
        raise HTTPException(404, "record not found")
    if not auth.visibility.can_read(r.scope_id, r.sensitivity, r.acl):
        raise HTTPException(403, "no access to record")
    return r


def _make(session: Session, auth: Auth, body: S.RecordIn, **extra) -> MemoryRecord:
    require_scope_write(auth, body.scope_id)
    return R.create_record(session, tenant_id=auth.tenant_id, scope_id=body.scope_id, type=body.type, summary=body.summary,
                           content=body.content, detail=body.detail, source_document_id=body.source_document_id,
                           source_locations=body.source_locations, event_time=body.event_time, valid_from=body.valid_from,
                           valid_to=body.valid_to, author_id=auth.principal.id, producing_agent=f"user:{auth.principal.name}",
                           confidence=body.confidence, sensitivity=body.sensitivity, keywords=body.keywords, acl=body.acl,
                           embedder=get_embedding_provider(), dedup=False, **extra)


@router.post("/memory/records", response_model=S.RecordOut)
def create_record_route(body: S.RecordIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    r = _make(session, auth, body)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="record.create", resource_kind="record", resource_id=r.id)
    return _rec_out(r)


@router.get("/memory/records/{record_id}", response_model=S.RecordOut)
def get_record(record_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    r = _get_rec(session, auth, record_id)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="record.read", resource_kind="record", resource_id=r.id)
    return _rec_out(r)


@router.get("/memory/records/{record_id}/history", response_model=list[S.RecordOut])
def record_history(record_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    r = _get_rec(session, auth, record_id)
    return [_rec_out(x) for x in R.history(session, r.family_id)]


@router.get("/memory/records/{record_id}/links")
def record_links(record_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from sqlalchemy import or_

    from cie.core.models import RecordLink

    r = _get_rec(session, auth, record_id)
    edges = session.scalars(select(RecordLink).where(or_(RecordLink.src_id == r.id, RecordLink.dst_id == r.id)))
    return [{"id": str(e.id), "src_id": str(e.src_id), "dst_id": str(e.dst_id), "kind": e.kind.value, "weight": e.weight,
             "justification": e.justification} for e in edges]


@router.post("/memory/records/{record_id}/supersede", response_model=S.RecordOut)
def supersede_route(record_id: uuid.UUID, body: S.ReviseIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    old = _get_rec(session, auth, record_id)
    new = _make(session, auth, body.new_record)
    R.supersede(session, old, new, justification=body.justification)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="record.supersede", resource_kind="record",
          resource_id=old.id, details={"new": str(new.id)})
    return _rec_out(new)


@router.post("/memory/records/{record_id}/contradict", response_model=S.RecordOut)
def contradict_route(record_id: uuid.UUID, body: S.LinkIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    a = _get_rec(session, auth, record_id)
    b = _get_rec(session, auth, body.other_id)
    require_scope_write(auth, a.scope_id)
    c = R.contradict(session, a, b, body.reason or "flagged by user", producing_agent=f"user:{auth.principal.name}")
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="record.contradict", resource_kind="record", resource_id=c.id)
    return _rec_out(c)


@router.post("/memory/records/{record_id}/confirm")
def confirm_route(record_id: uuid.UUID, body: S.LinkIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    a = _get_rec(session, auth, record_id)
    by = _get_rec(session, auth, body.other_id)
    require_scope_write(auth, a.scope_id)
    R.confirm(session, a, by)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="record.confirm", resource_kind="record", resource_id=a.id)
    return {"ok": True, "confidence": a.confidence, "verification": a.verification.value}


@router.post("/memory/records/{record_id}/extend")
def extend_route(record_id: uuid.UUID, body: S.LinkIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    base = _get_rec(session, auth, record_id)
    ext = _get_rec(session, auth, body.other_id)
    require_scope_write(auth, base.scope_id)
    R.extend(session, base, ext)
    return {"ok": True}


@router.post("/memory/records/{record_id}/link")
def link_route(record_id: uuid.UUID, body: S.LinkIn, kind: str = Query(...), auth: Auth = Depends(current_auth),
               session: Session = Depends(db)):
    a = _get_rec(session, auth, record_id)
    b = _get_rec(session, auth, body.other_id)
    require_scope_write(auth, a.scope_id)
    e = R.link(session, a, b, LinkKind(kind), justification=body.reason or None)
    return {"id": str(e.id), "kind": e.kind.value}


@router.get("/memory/records", response_model=list[S.RecordOut])
def list_records(scope_id: uuid.UUID | None = None, type: str | None = None, document_id: uuid.UUID | None = None,
                 include_history: bool = False, limit: int = 100, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    stmt = select(MemoryRecord).where(MemoryRecord.tenant_id == auth.tenant_id, MemoryRecord.deleted_at.is_(None),
                                      auth.visibility.sql_filter(MemoryRecord.scope_id, MemoryRecord.sensitivity))
    if scope_id:
        stmt = stmt.where(MemoryRecord.scope_id == scope_id)
    if type:
        stmt = stmt.where(MemoryRecord.type == type)
    if document_id:
        stmt = stmt.where(MemoryRecord.source_document_id == document_id)
    if not include_history:
        stmt = R.current_only(stmt)
    rows = session.scalars(stmt.order_by(MemoryRecord.recorded_at.desc()).limit(limit))
    return [_rec_out(r) for r in rows if auth.visibility.can_read(r.scope_id, r.sensitivity, r.acl)]


# ---------------------------------------------------------------- organisation views
@router.get("/memory/entities", summary="Find entities (organisations, people) by name or alias")
def find_entities(q: str = Query(min_length=2), type: str | None = None, limit: int = 10,
                  auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.core.models import RecordType
    from cie.memory import organise

    rtype = RecordType(type) if type else None
    return organise.find_entities(session, auth.tenant_id, auth.visibility, q, rtype, limit=min(limit, 50))


@router.get("/memory/entities/{entity_id}/profile", summary="Everything the memory holds about one entity")
def entity_profile(entity_id: uuid.UUID, at: datetime | None = None, include_history: bool = False, per_type: int = 5,
                   auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.memory import organise

    ent = _get_rec(session, auth, entity_id)
    if ent.type not in organise.ENTITY_TYPES:
        raise HTTPException(400, "record is not an entity")
    out = organise.entity_profile(session, auth.tenant_id, auth.visibility, ent, at=at, include_history=include_history, per_type=per_type)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="entity.profile", resource_kind="record",
          resource_id=ent.id, outcome="ok", details={"records": out["record_count"]})
    session.commit()
    return out


@router.get("/documents/{document_id}/card", summary="What one document contributed to memory")
def document_card(document_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.memory import organise

    return organise.document_card(session, auth.tenant_id, auth.visibility, _get_doc(session, auth, document_id))


@router.get("/scopes/{scope_id}/digest", summary="What a scope's memory holds: counts, entities, newest documents, conflicts")
def scope_digest(scope_id: uuid.UUID, at: datetime | None = None, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.memory import organise

    scope = session.get(Scope, scope_id)
    if scope is None or scope.tenant_id != auth.tenant_id:
        raise HTTPException(404, "scope not found")
    if scope.id not in auth.visibility.scope_ids:
        raise HTTPException(403, "no access to scope")
    return organise.scope_digest(session, auth.tenant_id, auth.visibility, scope, at=at)


# ---------------------------------------------------------------- search / answer
@router.post("/search", response_model=S.PacketOut)
def search(body: S.SearchIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    try:
        res = Retriever(session).retrieve(body.query, auth.principal, body.scope_id, filters=body.filters, k=body.k,
                                          at=body.as_of, use_graph=body.use_graph, use_vector=body.use_vector,
                                          use_lexical=body.use_lexical, max_records=body.max_records, token_budget=body.token_budget)
    except AccessDenied as e:
        session.commit()  # keep the denial audit row
        raise HTTPException(403, str(e)) from e
    p = res.packet
    return S.PacketOut(id=p.id, query=p.query, intent=p.intent, items=p.items, token_estimate=p.token_estimate,
                       latency_ms=p.latency_ms, trace=p.trace)


@router.get("/evidence/{packet_id}", response_model=S.PacketOut)
def get_packet(packet_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    p = session.get(EvidencePacket, packet_id)
    if p is None or p.tenant_id != auth.tenant_id:
        raise HTTPException(404, "packet not found")
    if p.principal_id != auth.principal.id and not auth.visibility.is_admin:
        raise HTTPException(403, "not your packet")
    return S.PacketOut(id=p.id, query=p.query, intent=p.intent, items=p.items, token_estimate=p.token_estimate,
                       latency_ms=p.latency_ms, trace=p.trace)


@router.post("/answer", response_model=S.AnswerOut)
def answer(body: S.AnswerIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    from cie.agents.providers import get_provider

    provider = get_provider() if body.mode == "assisted" else None
    if body.mode == "assisted" and provider.name == "none":
        raise HTTPException(400, "assisted mode requires CIE_LLM_PROVIDER; strict mode is available")
    try:
        result, res = Retriever(session).answer(body.query, auth.principal, body.scope_id, mode=body.mode, provider=provider,
                                                filters=body.filters, k=body.k, at=body.as_of, use_graph=body.use_graph,
                                                use_vector=body.use_vector, use_lexical=body.use_lexical,
                                                max_records=body.max_records, token_budget=body.token_budget)
    except AccessDenied as e:
        session.commit()
        raise HTTPException(403, str(e)) from e
    return S.AnswerOut(id=result.answer_id, packet_id=res.packet.id, question=body.query, answer=result.answer,
                       status=result.status, citations=result.citations, confidence=result.confidence, mode=result.mode,
                       model=result.model, tokens_in=result.tokens_in, tokens_out=result.tokens_out, latency_ms=result.latency_ms,
                       cost_usd=result.cost_usd, usage_is_estimate=result.usage_is_estimate, unsupported_claims=result.unsupported_claims)


@router.get("/answers/{answer_id}", response_model=S.AnswerOut)
def get_answer(answer_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    a = session.get(Answer, answer_id)
    if a is None or a.tenant_id != auth.tenant_id:
        raise HTTPException(404, "answer not found")
    return S.AnswerOut(id=a.id, packet_id=a.packet_id, question=a.question, answer=a.answer, status=a.status, citations=a.citations,
                       confidence=a.confidence, mode=a.mode, model=a.model, tokens_in=a.tokens_in, tokens_out=a.tokens_out,
                       latency_ms=a.latency_ms, cost_usd=a.cost_usd, usage_is_estimate=a.mode != "assisted",
                       unsupported_claims=a.unsupported_claims)


# ---------------------------------------------------------------- source viewing
@router.get("/sources/{document_id}/pages/{page_no}", response_model=S.PageOut)
def source_page(document_id: uuid.UUID, page_no: int, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    d = _get_doc(session, auth, document_id)
    ex = session.scalar(select(Extraction).where(Extraction.document_id == d.id).order_by(Extraction.created_at.desc()))
    if ex is None:
        raise HTTPException(404, "not extracted yet")
    page = session.scalar(select(Page).where(Page.extraction_id == ex.id, Page.page_no == page_no))
    if page is None:
        raise HTTPException(404, "page not found")
    blocks = list(session.scalars(select(Block).where(Block.page_id == page.id).order_by(Block.order_index)))
    corr = list(session.scalars(select(Correction).where(Correction.block_id.in_([b.id for b in blocks])))) if blocks else []
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="source.view", resource_kind="document",
          resource_id=d.id, details={"page_no": page_no})
    return S.PageOut(document_id=d.id, page_no=page.page_no, width=page.width, height=page.height, method=page.method,
                     confidence=page.confidence, text=page.text,
                     blocks=[{"id": str(b.id), "kind": b.kind, "bbox": b.bbox, "text": b.text, "content": b.content,
                              "confidence": b.confidence} for b in blocks],
                     corrections=[{"block_id": str(c.block_id), "original": c.original_text, "corrected": c.corrected_text,
                                   "method": c.method, "confidence": c.confidence} for c in corr])


@router.get("/sources/{document_id}/pages/{page_no}/image")
def source_page_image(document_id: uuid.UUID, page_no: int, dpi: int = 110, auth: Auth = Depends(current_auth),
                      session: Session = Depends(db)):
    d = _get_doc(session, auth, document_id)
    data = _vault().read(session, d)
    if d.blob.media_type == "application/pdf":
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if page_no < 1 or page_no > pdf.page_count:
                raise HTTPException(404, "page out of range")
            png = pdf[page_no - 1].get_pixmap(dpi=dpi).tobytes("png")
        return Response(content=png, media_type="image/png")
    if d.blob.media_type.startswith("image/"):
        return Response(content=data, media_type=d.blob.media_type)
    raise HTTPException(415, "no page image for this media type; use the text view")


@router.get("/sources/{document_id}/download")
def source_download(document_id: uuid.UUID, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    d = _get_doc(session, auth, document_id)
    data = _vault().read(session, d)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="source.download", resource_kind="document", resource_id=d.id)
    return Response(content=data, media_type=d.blob.media_type,
                    headers={"Content-Disposition": f'attachment; filename="{d.original_filename}"', "X-Checksum-SHA256": d.blob.sha256})


# ---------------------------------------------------------------- audit / permissions / metrics
@router.get("/audit", response_model=list[S.AuditOut])
def audit_history(resource_id: str | None = None, action: str | None = None, limit: int = 200,
                  auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    stmt = select(AuditLog).where(AuditLog.tenant_id == auth.tenant_id)
    if not auth.visibility.is_admin:
        stmt = stmt.where(AuditLog.principal_id == auth.principal.id)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = session.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit))
    return [S.AuditOut(id=a.id, principal_id=a.principal_id, action=a.action, resource_kind=a.resource_kind, resource_id=a.resource_id,
                       details=a.details, outcome=a.outcome, created_at=a.created_at) for a in rows]


@router.post("/permissions/principals")
def create_principal(body: S.PrincipalIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    import secrets

    from cie.api.deps import hash_key

    if not auth.visibility.is_admin:
        raise HTTPException(403, "admin only")
    key = secrets.token_urlsafe(32)
    p = Principal(tenant_id=auth.tenant_id, kind=PrincipalKind(body.kind), name=body.name, email=body.email,
                  attributes=body.attributes, api_key_hash=hash_key(key))
    session.add(p)
    session.flush()
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="principal.create", resource_kind="principal", resource_id=p.id)
    return {"id": str(p.id), "name": p.name, "api_key": key}


@router.post("/permissions/grant")
def grant(body: S.GrantIn, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    if auth.visibility.level_by_scope.get(body.scope_id, 0) < 3:
        raise HTTPException(403, "admin on scope required")
    p = session.scalar(select(Principal).where(Principal.tenant_id == auth.tenant_id, Principal.name == body.principal_name))
    role = session.scalar(select(Role).where(Role.tenant_id == auth.tenant_id, Role.name == body.role))
    scope = session.get(Scope, body.scope_id)
    if p is None or role is None or scope is None:
        raise HTTPException(404, "principal, role or scope not found")
    g = grant_role(session, tenant_id=auth.tenant_id, principal=p, role=role, scope=scope, granted_by=auth.principal.id)
    audit(session, tenant_id=auth.tenant_id, principal_id=auth.principal.id, action="permission.grant", resource_kind="grant",
          resource_id=g.id, details={"principal": p.name, "role": role.name, "scope": str(scope.id)})
    return {"id": str(g.id)}


@router.post("/permissions/roles")
def create_role(name: str, permission: str, max_sensitivity: int = 1, auth: Auth = Depends(current_auth), session: Session = Depends(db)):
    if not auth.visibility.is_admin:
        raise HTTPException(403, "admin only")
    r = ensure_role(session, auth.tenant_id, name, Permission(permission), max_sensitivity)
    return {"id": str(r.id), "name": r.name}


@router.get("/permissions/me")
def me(auth: Auth = Depends(current_auth)):
    return {"principal": {"id": str(auth.principal.id), "name": auth.principal.name, "kind": auth.principal.kind.value},
            "is_admin": auth.visibility.is_admin,
            "scopes": {str(k): {"clearance": v, "level": auth.visibility.level_by_scope.get(k, 0)} for k, v in auth.visibility.clearance_by_scope.items()}}


@router.get("/metrics/summary")
def metrics_summary(auth: Auth = Depends(current_auth), session: Session = Depends(db)) -> dict[str, Any]:
    from cie.core.models import Blob, Section

    t = auth.tenant_id
    rows = session.execute(select(Metric.name, func.count(), func.avg(Metric.value), func.percentile_cont(0.95).within_group(Metric.value),
                                  func.sum(Metric.value)).where(Metric.tenant_id == t).group_by(Metric.name)).all()
    storage = session.execute(select(func.count(Blob.id), func.coalesce(func.sum(Blob.size_bytes), 0)).where(Blob.tenant_id == t)).one()
    counts = {
        "documents": session.scalar(select(func.count(Document.id)).where(Document.tenant_id == t)),
        "sections": session.scalar(select(func.count(Section.id)).where(Section.tenant_id == t)),
        "records": session.scalar(select(func.count(MemoryRecord.id)).where(MemoryRecord.tenant_id == t)),
        "jobs": queue.stats(session, t),
    }
    return {"metrics": {name: {"n": int(n), "avg": float(avg or 0), "p95": float(p95 or 0), "sum": float(s or 0)} for name, n, avg, p95, s in rows},
            "storage": {"blobs": int(storage[0]), "raw_bytes": int(storage[1])}, "counts": counts}
