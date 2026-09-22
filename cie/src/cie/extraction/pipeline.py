"""Streaming, checkpointed document processing.

Stage ``pages``: one page at a time → pages/blocks/corrections, checkpoint
after every page. Stage ``index``: sections (FTS + embeddings), derived
records, scanners, completeness. Both stages are idempotent so an interrupted
job resumes where it stopped. OCR state is per page; nothing is carried across
documents.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cie.core.logging import get_logger
from cie.core.models import (
    Blob,
    Block,
    Correction,
    Document,
    Extraction,
    Job,
    MemoryRecord,
    Page,
    RecordType,
    Section,
)
from cie.core.settings import Settings, get_settings
from cie.core.util import estimate_tokens, sha256_text, utcnow
from cie.extraction.checks import check_completeness
from cie.extraction.corrections import propose
from cie.extraction.detect import detect_language
from cie.extraction.facts import derive_records, keywords_for
from cie.extraction.registry import extractor_for
from cie.extraction.sectioning import BlockRef, build_sections
from cie.governance.scanners import scan_text
from cie.memory.autolink import autolink
from cie.memory.embeddings import EmbeddingProvider, get_embedding_provider
from cie.memory.entities import remember_alias, resolve
from cie.memory.records import create_record
from cie.memory.text import tsvector_expr
from cie.vault.service import VaultService
from cie.workers import queue

log = get_logger(__name__)


@dataclass
class ExtractionOutcome:
    extraction: Extraction
    sections: int
    records: int
    completeness: dict[str, Any]


def run_extraction(
    session: Session,
    document: Document,
    *,
    vault: VaultService | None = None,
    job: Job | None = None,
    embedder: EmbeddingProvider | None = None,
    settings: Settings | None = None,
    ocr=None,
    fail_after_pages: int | None = None,  # test hook to simulate a crash
) -> ExtractionOutcome:
    settings = settings or get_settings()
    vault = vault or VaultService(settings)
    embedder = embedder or get_embedding_provider(settings)
    blob = session.get(Blob, document.blob_id)
    assert blob is not None
    data = vault.read(session, document)
    extractor = extractor_for(blob.media_type, settings, ocr=ocr)

    # --- resume or start an extraction row
    ck = dict(job.checkpoint or {}) if job else {}
    extraction = session.get(Extraction, uuid.UUID(ck["extraction_id"])) if ck.get("extraction_id") else None
    if extraction is None:
        extraction = Extraction(tenant_id=document.tenant_id, document_id=document.id, extractor=extractor.name,
                                extractor_version=str(extractor.version), status="running",
                                page_count=extractor.page_count(data))
        session.add(extraction)
        session.flush()
        document.status = "extracting"
        if job:
            queue.checkpoint(session, job, {"extraction_id": str(extraction.id), "stage": "pages"}, 0.0)
        else:
            session.commit()

    # --- stage: pages
    if ck.get("stage", "pages") == "pages":
        start = extraction.pages_done
        rng = range(start, extraction.page_count)
        for page in extractor.extract(data, rng):
            _store_page(session, document, extraction, page)
            extraction.pages_done = page.page_no
            if job:
                queue.checkpoint(session, job, {"pages_done": page.page_no},
                                 progress=0.8 * page.page_no / max(extraction.page_count, 1))
            else:
                session.commit()
            if fail_after_pages is not None and page.page_no >= fail_after_pages:
                raise RuntimeError(f"simulated crash after page {page.page_no}")
        if job:
            queue.checkpoint(session, job, {"stage": "index"}, 0.8)
        ck["stage"] = "index"

    # --- stage: index (idempotent)
    pages = list(session.scalars(select(Page).where(Page.extraction_id == extraction.id).order_by(Page.page_no)))
    sample = "\n".join(p.text[:2000] for p in pages[:10])
    extraction.language = detect_language(sample)
    document.language = document.language or extraction.language
    report = check_completeness(extraction.page_count,
                                [(p.page_no, p.text, p.confidence, p.method, p.text_sha256) for p in pages])
    extraction.completeness = report.as_dict()
    extraction.mean_confidence = report.mean_confidence

    blocks = list(session.scalars(select(Block).where(Block.document_id == document.id)
                                  .join(Page, Page.id == Block.page_id).where(Page.extraction_id == extraction.id)
                                  .order_by(Block.page_no, Block.order_index)))
    corrected = {c.block_id: c.corrected_text for c in session.scalars(
        select(Correction).where(Correction.document_id == document.id))}
    refs = [BlockRef(b.id, b.page_no, b.bbox, b.kind, corrected.get(b.id, b.text), (b.content or {}).get("leading_heading")) for b in blocks]
    drafts = build_sections(refs, settings.section_target_tokens, settings.section_max_tokens)

    session.execute(delete(Section).where(Section.extraction_id == extraction.id))
    section_rows: list[tuple[Section, Any]] = []
    texts = [f"{d.title or ''}\n{d.text}"[:4000] for d in drafts]
    vectors = embedder.embed(texts) if texts else []
    for i, (d, vec) in enumerate(zip(drafts, vectors, strict=False)):
        sec = Section(tenant_id=document.tenant_id, document_id=document.id, extraction_id=extraction.id,
                      scope_id=document.scope_id, order_index=i, title=d.title, level=d.level,
                      page_start=d.page_start, page_end=d.page_end, text=d.text,
                      text_sha256=sha256_text(d.text), token_estimate=estimate_tokens(d.text),
                      spans=d.spans(), tsv=tsvector_expr(d.title, d.text), embedding=vec,
                      sensitivity=document.sensitivity)
        session.add(sec)
        section_rows.append((sec, d))
    session.flush()

    # scanners
    flags = []
    for p in pages:
        flags.extend(f.as_dict() for f in scan_text(p.text, p.page_no))
    document.injection_flags = [f for f in flags if f["kind"] == "injection"][:100]
    document.pii_flags = [f for f in flags if f["kind"] in ("pii", "secret")][:200]

    # derived records
    n_records = _derive(session, document, extraction, section_rows, embedder)

    extraction.status = "done" if report.passed else "done_with_issues"
    extraction.finished_at = utcnow()
    extraction.stats = {"blocks": len(blocks), "sections": len(section_rows), "records": n_records,
                        "flags": {"injection": len(document.injection_flags), "pii": len(document.pii_flags)}}
    document.status = "indexed"
    if job:
        queue.checkpoint(session, job, {"stage": "done"}, 1.0)
    session.commit()
    log.info("extraction.done", document_id=str(document.id), pages=extraction.page_count,
             sections=len(section_rows), records=n_records, passed=report.passed)
    return ExtractionOutcome(extraction, len(section_rows), n_records, extraction.completeness)


def _store_page(session: Session, document: Document, extraction: Extraction, page) -> None:
    existing = session.scalar(select(Page).where(Page.extraction_id == extraction.id, Page.page_no == page.page_no))
    if existing is not None:
        return  # already stored before a crash; idempotent resume
    text_ = page.text
    row = Page(extraction_id=extraction.id, document_id=document.id, page_no=page.page_no, width=page.width,
               height=page.height, text=text_, text_sha256=sha256_text(text_), confidence=page.confidence,
               method=page.method)
    session.add(row)
    session.flush()
    for i, b in enumerate(page.blocks):
        blk = Block(page_id=row.id, document_id=document.id, page_no=page.page_no, order_index=i, kind=b.kind,
                    bbox=[float(x) for x in (b.bbox or [0, 0, 0, 0])], text=b.text, content=b.content or {},
                    confidence=b.confidence)
        session.add(blk)
        session.flush()
        if page.method == "ocr" and b.text:
            prop = propose(b.text)
            if prop:
                session.add(Correction(block_id=blk.id, document_id=document.id, original_text=prop.original,
                                       corrected_text=prop.corrected, method=prop.method, confidence=prop.confidence))


def _derive(session: Session, document: Document, extraction: Extraction, section_rows, embedder) -> int:
    drafts = derive_records([(str(sec.id), d) for sec, d in section_rows], document_title=document.title,
                            doc_type=document.doc_type)
    first_page = section_rows[0][0].page_start if section_rows else None
    doc_rec = create_record(
        session, tenant_id=document.tenant_id, scope_id=document.scope_id, type=RecordType.document,
        summary=document.title, detail=(section_rows[0][1].text[:1500] if section_rows else ""),
        content={"filename": document.original_filename, "version": document.version, "pages": extraction.page_count,
                 "doc_type": document.doc_type, "language": extraction.language, "family_id": str(document.family_id)},
        source_document_id=document.id,
        source_locations=[{"page_no": first_page, "bbox": None,
                           "quote": (section_rows[0][1].blocks[0].text[:200] if section_rows and section_rows[0][1].blocks else document.title)}],
        event_time=document.file_created_at, valid_from=document.file_created_at, producing_agent="ingest",
        confidence=1.0, sensitivity=document.sensitivity, acl=document.acl,
        keywords=keywords_for(document.title + " " + (section_rows[0][1].text if section_rows else ""), 10),
        embedder=embedder,
    )
    if not drafts:
        return 1
    vectors = embedder.embed([f"{d.type}: {d.summary}\n{d.detail[:1200]}" for d in drafts])
    n = 1
    created: list[MemoryRecord] = [doc_rec]
    entities: dict[str, MemoryRecord] = {}
    for d, vec in zip(drafts, vectors, strict=False):
        if d.type in ("organization", "person"):
            name = d.content.get("name", d.summary)
            ent, status = resolve(session, document.tenant_id, document.scope_id, name, RecordType(d.type))
            if status == "matched" and ent is not None:
                # inherit the canonical entity instead of duplicating it; keep the alias and the new evidence
                remember_alias(ent, name)
                locs = list(ent.source_locations or [])
                if len(locs) < 20:
                    ent.source_locations = locs + [{**d.source_locations[0], "document_id": str(document.id)}]
                entities[name] = ent
                fact = _entity_fact(session, document, d, ent, vec)
                if fact is not None:
                    created.append(fact)
                    n += 1
                continue
        rec = create_record(
            session, tenant_id=document.tenant_id, scope_id=document.scope_id, type=d.type, summary=d.summary,
            content=d.content, detail=d.detail, source_document_id=document.id, source_locations=d.source_locations,
            event_time=d.event_time or document.file_created_at, valid_from=d.valid_from or document.file_created_at,
            valid_to=d.valid_to, producing_agent="rule_extractor_v1",
            confidence=d.confidence, sensitivity=document.sensitivity, acl=document.acl, keywords=d.keywords,
            embedding=vec,
        )
        if rec is not None:
            n += 1
            created.append(rec)
            if d.type in ("organization", "person"):
                entities[d.content.get("name", d.summary)] = rec
    autolink(session, doc_rec, created, entities)
    if document.previous_version_id is not None:
        from cie.memory.records import supersede_previous_version

        supersede_previous_version(session, document.previous_version_id, document.id, document.file_created_at)
    return n


def _entity_fact(session: Session, document: Document, d, ent: MemoryRecord, vec) -> MemoryRecord | None:
    """The entity exists once; *this document's* relationship to it is a fact of its own
    (signatory, party), so 'who signed X' resolves to the right document."""
    ctx = (d.content or {}).get("context", "") or d.detail
    role = (d.content or {}).get("role")
    if d.type == "person" and role == "signatory":
        summary = f"{ent.summary} signed {document.title}"
        detail = f"Signed by {ent.summary} (signatory) in {document.title}. {ctx}"
        kws = ["signed", "signatory", *ent.summary.lower().split()]
    elif d.type == "organization" and any(w in ctx.lower() for w in ("between", "entered into", "party", "parties")):
        summary = f"{ent.summary} is a party to {document.title}"
        detail = f"{ent.summary} is a party to {document.title}. {ctx}"
        kws = ["party", *ent.summary.lower().split()]
    else:
        return None
    rec = create_record(session, tenant_id=document.tenant_id, scope_id=document.scope_id, type=RecordType.fact, summary=summary[:200],
                        content={"entity_id": str(ent.id), "role": role or "party", "document": document.title}, detail=detail[:1500],
                        source_document_id=document.id, source_locations=d.source_locations, event_time=document.file_created_at,
                        valid_from=document.file_created_at, producing_agent="rule_extractor_v1", confidence=0.7,
                        sensitivity=document.sensitivity, acl=document.acl, keywords=kws[:8], entity_ids=[str(ent.id)], embedding=vec)
    return rec


def documents_needing_extraction(session: Session, tenant_id: uuid.UUID) -> list[Document]:
    return list(session.scalars(select(Document).where(Document.tenant_id == tenant_id, Document.status == "ingested")))


def record_count(session: Session, document_id: uuid.UUID) -> int:
    return session.scalar(select(MemoryRecord.id).where(MemoryRecord.source_document_id == document_id).count()) or 0
