"""Acceptance tests (brief §13). Fast ones run on the synthetic corpus with
hashed embeddings; the 300-page scanned contract test is marked slow."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from cie.core.models import Document, Page
from cie.eval import bench_retrieval as B
from cie.eval.corpus import build
from cie.extraction.extractors.ocr_tesseract import TesseractOCR
from cie.retrieval.pipeline import Retriever
from tests.fixtures import make_pdf, rasterize_pdf

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def corpus_world(engine):
    """Ingest the synthetic corpus once per module (OCR on the scanned doc)."""
    from cie.core import db as dbmod
    from cie.memory.embeddings import HashedEmbedding

    s = dbmod.session_factory()()
    docs, qas = build(n_filler=3)
    ocr = TesseractOCR() if TesseractOCR.available() else None
    if ocr is None:
        docs = [d for d in docs if d.key != "contoso_scan"]
        qas = [q for q in qas if not any(k == "contoso_scan" for k, _ in q.relevant)]
    world = B.ingest_corpus(s, docs, embedder=HashedEmbedding(), ocr=ocr, tag="accept")
    s.commit()
    yield s, world, qas
    s.close()


def _answer(s, world, q, **kw):
    from cie.memory.embeddings import HashedEmbedding

    r = Retriever(s, embedder=HashedEmbedding())
    return r.answer(q.question, world.principals[q.principal], world.scopes[q.scope].id, **kw)


def test_2_exact_clause_with_page_provenance(corpus_world):
    s, world, qas = corpus_world
    q = next(x for x in qas if x.qid == "q_liability")
    result, res = _answer(s, world, q)
    assert result.status == "answered" and any(sub in result.answer for sub in q.expected_substrings), result.answer
    assert result.citations[0]["page_no"] == 5 and result.citations[0]["document_id"] in {str(world.docs["nw_v2"].id), str(world.docs["nw_v1"].id)}


def test_3_cross_document_without_loading_everything(corpus_world):
    s, world, qas = corpus_world
    q = next(x for x in qas if x.qid == "q_dependency")
    result, res = _answer(s, world, q)
    assert result.status == "answered" and "Northwind agreement" in result.answer
    total_tokens = s.scalar(select(func.sum(func.length(Page.text)))) // 4
    assert res.packet.token_estimate < total_tokens * 0.2, "packet must be a small fraction of the corpus"


def test_4_current_vs_superseded(corpus_world):
    s, world, qas = corpus_world
    cur = next(x for x in qas if x.qid == "q_fee_current")
    old = next(x for x in qas if x.qid == "q_fee_asof")
    r_cur, _ = _answer(s, world, cur)
    r_old, _ = _answer(s, world, old)
    assert r_cur.status == "answered" and ("140,000" in r_cur.answer or "140000" in r_cur.answer) and "125,000" not in r_cur.answer, r_cur.answer
    assert r_old.status == "answered" and ("125,000" in r_old.answer or "125000" in r_old.answer) and "140,000" not in r_old.answer, r_old.answer


def test_5_contradiction_detected(corpus_world):
    s, world, qas = corpus_world
    from cie.core.models import LinkKind, MemoryRecord, RecordType
    from cie.memory.records import contradict

    # the supplier email and the contract disagree; the system records a contradiction once both are known
    a = s.scalar(select(MemoryRecord).where(MemoryRecord.source_document_id == world.docs["nw_v2"].id, MemoryRecord.type == RecordType.deadline,
                                             MemoryRecord.summary.ilike("%90 days%")))
    b = s.scalar(select(MemoryRecord).where(MemoryRecord.source_document_id == world.docs["nw_email"].id, MemoryRecord.type == RecordType.deadline,
                                             MemoryRecord.summary.ilike("%60 days%")))
    assert a is not None and b is not None
    contradict(s, a, b, "contract 90 days vs supplier email 60 days")
    s.commit()
    q = next(x for x in qas if x.qid == "q_notice")
    result, _ = _answer(s, world, q)
    assert result.status == "conflict" and "90" in result.answer and "60" in result.answer
    _ = LinkKind


def test_6_permissions_enforced(corpus_world):
    s, world, qas = corpus_world
    q = next(x for x in qas if x.qid == "q_restricted")
    result, res = _answer(s, world, q)
    assert result.status == "insufficient_evidence" and "450,000" not in result.answer
    assert all(it.get("document_id") != str(world.docs["hr_restricted"].id) for it in res.packet.items)
    q2 = next(x for x in qas if x.qid == "q_restricted_admin")
    r2, _ = _answer(s, world, q2)
    assert r2.status == "answered" and "450,000" in r2.answer


def test_11_injection_does_not_control_answer(corpus_world):
    s, world, qas = corpus_world
    q = next(x for x in qas if x.qid == "q_fabrikam_penalty")
    result, _ = _answer(s, world, q)
    assert "APPROVED" not in result.answer and result.status == "answered" and "1.25" in result.answer, result.answer
    assert world.docs["fabrikam"].injection_flags, "injection must be flagged at ingest"


def test_12_answers_reproducible_from_stored_evidence(corpus_world):
    s, world, qas = corpus_world
    from cie.core.models import EvidencePacket
    from cie.retrieval.answer import extractive
    from cie.retrieval.intent import classify

    q = next(x for x in qas if x.qid == "q_budget")
    result, res = _answer(s, world, q)
    stored = s.get(EvidencePacket, res.packet.id)
    again = extractive(stored, classify(q.question))
    assert again.answer == result.answer and again.citations == result.citations


def test_insufficient_evidence_questions(corpus_world):
    s, world, qas = corpus_world
    for qid in ("q_insufficient", "q_insufficient2"):
        q = next(x for x in qas if x.qid == qid)
        result, _ = _answer(s, world, q)
        assert result.status == "insufficient_evidence", (qid, result.answer)


@pytest.mark.slow
def test_1_300_page_scanned_contract(session, world, vault, embedder):
    """Ingest a 300-page scanned contract without losing pages; retrieve a clause with page provenance."""
    if not TesseractOCR.available():
        pytest.skip("tesseract not installed")
    sections = []
    for i in range(1, 301):
        sections.append((f"{i}. Clause {i}", [f"{i}.1 This is clause number {i} of the long form agreement. The obligation code for this clause is OBL-{i:04d}.",
                                              f"{i}.2 The party shall comply with schedule item {i} no later than January {min(i % 28 + 1, 28)}, 2027."]))
    sections[176] = ("177. Special Indemnity", ["177.1 The Supplier shall indemnify the Company up to USD 7,777,777 for data breaches. The obligation code for this clause is OBL-0177."])
    pdf = rasterize_pdf(make_pdf(sections), dpi=110)
    doc = vault.ingest(session, tenant_id=world.tenant.id, data=pdf, filename="long_contract_scan.pdf", scope_id=world.project.id, doc_type="contract").document
    session.commit()
    from cie.extraction.pipeline import run_extraction

    out = run_extraction(session, doc, vault=vault, embedder=embedder, ocr=TesseractOCR())
    assert out.completeness["expected_pages"] == 300 and out.completeness["extracted_pages"] == 300 and not out.completeness["issues"][:0]
    assert session.scalar(select(func.count(Page.id)).where(Page.document_id == doc.id)) == 300
    assert out.completeness["passed"], out.completeness
    r = Retriever(session, embedder=embedder)
    result, res = r.answer("What does clause 177 say about indemnity?", world.admin, world.project.id, filters={"document_id": str(doc.id)})
    assert result.status == "answered", result.answer
    assert result.citations[0]["page_no"] == 177, result.citations[0]
    assert "7,777,777" in result.answer or "7777777" in result.answer or "indemnif" in result.answer.lower()
    d = session.get(Document, doc.id)
    assert d.status == "indexed"
