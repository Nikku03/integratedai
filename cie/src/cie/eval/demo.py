"""End-to-end vertical slice on the synthetic corpus:

file → extraction → memory records → retrieval → cited answer → audit trail.

Creates its own tenant, ingests the corpus, answers a handful of questions in
strict mode, prints citations with page numbers and the audit rows, and writes
``demo.json``. No LLM is required.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from sqlalchemy import select

from cie.core.db import session_scope
from cie.core.models import AuditLog, Page
from cie.core.settings import get_settings
from cie.eval.bench_retrieval import ingest_corpus
from cie.eval.corpus import build
from cie.extraction.registry import build_ocr
from cie.memory.embeddings import get_embedding_provider
from cie.retrieval.pipeline import Retriever

QUESTIONS = ["q_fee_current", "q_fee_asof", "q_contoso_fee", "q_who_signed", "q_freeze", "q_restricted", "q_insufficient"]


def run_demo(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    embedder = get_embedding_provider(settings)
    ocr = build_ocr(settings)
    docs, qas = build(n_filler=2)
    if ocr is None:
        docs = [d for d in docs if d.key != "contoso_scan"]
    report: dict = {"embedding": getattr(embedder, "name", "?"), "ocr": getattr(ocr, "name", None), "steps": []}
    with session_scope() as s:
        t0 = time.perf_counter()
        world = ingest_corpus(s, docs, embedder=embedder, ocr=ocr, tag="demo")
        report["steps"].append({"step": "file → vault → extraction → records", "documents": len(world.docs),
                                "pages": s.scalar(select(Page.id).where(Page.document_id.in_([d.id for d in world.docs.values()])).count()) if False else None,
                                "seconds": round(time.perf_counter() - t0, 1)})
        r = Retriever(s, settings, embedder=embedder)
        for qid in QUESTIONS:
            q = next((x for x in qas if x.qid == qid), None)
            if q is None or (q.scope == "restricted" and q.principal != "admin" and False):
                continue
            scope = world.scopes[q.scope if q.scope != "restricted" else "hr"]
            result, res = r.answer(q.question, world.principals[q.principal], scope.id)
            cites = []
            for c in result.citations[:3]:
                page = s.scalar(select(Page).where(Page.document_id == c["document_id"], Page.page_no == c["page_no"])) if c.get("document_id") and c.get("page_no") else None
                cites.append({"document": next((k for k, d in world.docs.items() if str(d.id) == c.get("document_id")), None), "page_no": c.get("page_no"),
                              "bbox": c.get("bbox"), "quote": (c.get("quote") or "")[:120], "quote_found_on_page": bool(page and (c.get("quote") or "")[:40].lower() in " ".join(page.text.lower().split()))})
            report["steps"].append({"question": q.question, "principal": q.principal, "status": result.status, "expected": q.expected_status,
                                    "answer": result.answer[:300], "confidence": result.confidence, "packet_items": len(res.packet.items),
                                    "packet_tokens": res.packet.token_estimate, "latency_ms": round(res.packet.latency_ms, 1), "citations": cites})
        audit_rows = list(s.scalars(select(AuditLog).where(AuditLog.tenant_id == world.tenant.id).order_by(AuditLog.id.desc()).limit(8)))
        report["audit_tail"] = [{"action": a.action, "resource_kind": a.resource_kind, "outcome": a.outcome} for a in audit_rows]
        s.commit()
    (out_dir / "demo.json").write_text(json.dumps(report, indent=2, default=str))
    for st in report["steps"]:
        if "question" in st:
            print(f"Q: {st['question']}\n   [{st['status']} / expected {st['expected']}] {st['answer'][:160]}")
            for c in st["citations"]:
                print(f"   ↳ {c['document']} p.{c['page_no']} bbox={c['bbox']} quote_found={c['quote_found_on_page']}")
    print("audit tail:", [a["action"] for a in report["audit_tail"]])
    return report
