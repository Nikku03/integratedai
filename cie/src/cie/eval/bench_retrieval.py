"""Retrieval benchmark on the synthetic corpus.

Arms: full-context (token load only; answers not produced without a model),
vector-only, BM25-only (in-memory Okapi BM25), hybrid (exact + lexical +
vector), hybrid + unbounded graph expansion, and the default REM-inspired
hybrid + bounded-horizon expansion (budget ceil(c·log2 N)).

Metrics: recall@20 on (document, page) ground truth, exact-field accuracy of
the strict extractive answer, citation correctness (quote found on cited page),
status accuracy (insufficient-evidence / conflict detection), permission leaks,
retrieval latency p50/p95, packet tokens, warm metadata lookup p95, storage.

Every number is measured; nothing is asserted.
"""

from __future__ import annotations

import json
import re
import statistics
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from cie.agents.providers import estimate_cost
from cie.core.db import session_scope
from cie.core.models import (
    Blob,
    Document,
    MemoryRecord,
    Page,
    Permission,
    Principal,
    PrincipalKind,
    ScopeKind,
    Section,
    Tenant,
)
from cie.core.settings import get_settings
from cie.core.util import estimate_tokens
from cie.eval.corpus import QA, SynthDoc, build
from cie.extraction.pipeline import run_extraction
from cie.extraction.registry import build_ocr
from cie.governance.permissions import ensure_role, grant_role, visible_scopes
from cie.memory.embeddings import get_embedding_provider
from cie.memory.scopes import addressable_scope_ids, create_scope
from cie.retrieval import packet as packet_mod
from cie.retrieval import rerank as rerank_mod
from cie.retrieval.answer import extractive
from cie.retrieval.intent import classify
from cie.retrieval.lexical import BM25Index
from cie.retrieval.pipeline import Retriever
from cie.vault.service import VaultService


@dataclass
class World:
    tenant: Tenant
    scopes: dict[str, Any]
    principals: dict[str, Principal]
    docs: dict[str, Document]


def ingest_corpus(s: Session, docs: list[SynthDoc], *, embedder, ocr, tag: str = "bench") -> World:
    tenant = Tenant(name=f"{tag}-{uuid.uuid4().hex[:6]}")
    s.add(tenant)
    s.flush()
    company = create_scope(s, tenant.id, ScopeKind.company, "Acme")
    scopes = {"company": company}
    for name in ("Legal", "Finance", "Engineering", "HR"):
        scopes[name.lower()] = create_scope(s, tenant.id, ScopeKind.department, name, company)
    scopes["restricted"] = scopes["hr"]
    admin_role = ensure_role(s, tenant.id, "admin", Permission.admin, 4)
    reader = ensure_role(s, tenant.id, "reader", Permission.read, 2)
    principals = {}
    for name, grants in (("admin", [(admin_role, company)]), ("analyst", [(reader, scopes["legal"])]), ("finance_reader", [(reader, scopes["finance"])])):
        p = Principal(tenant_id=tenant.id, kind=PrincipalKind.user, name=name)
        s.add(p)
        s.flush()
        for role, sc in grants:
            grant_role(s, tenant_id=tenant.id, principal=p, role=role, scope=sc)
        principals[name] = p
    vault = VaultService()
    out: dict[str, Document] = {}
    families: dict[str, uuid.UUID] = {}
    for d in sorted(docs, key=lambda x: (x.family or x.key, x.version)):
        fam = families.get(d.family) if d.family else None
        res = vault.ingest(s, tenant_id=tenant.id, data=d.data, filename=d.filename, scope_id=scopes[d.scope].id, doc_type=d.doc_type,
                           sensitivity=d.sensitivity, family_id=fam, file_created_at=d.file_created_at)
        if d.family and d.family not in families:
            families[d.family] = res.document.family_id
        s.commit()
        run_extraction(s, res.document, vault=vault, embedder=embedder, ocr=ocr)
        out[d.key] = res.document
    # version 2 supersedes version 1 records that carry the same metric name/clause: mark v1 document records as superseded
    _supersede_versions(s, out, docs)
    s.commit()
    return World(tenant, scopes, principals, out)


def _supersede_versions(s: Session, docs: dict[str, Document], synth: list[SynthDoc]) -> None:
    """Version supersession happens in the ingestion pipeline (records.supersede_previous_version);
    this re-applies it idempotently so the benchmark does not depend on ingest order."""
    from cie.memory.records import supersede_previous_version

    by_family: dict[str, list[SynthDoc]] = {}
    for d in synth:
        if d.family:
            by_family.setdefault(d.family, []).append(d)
    for versions in by_family.values():
        versions.sort(key=lambda x: x.version)
        for old, new in zip(versions, versions[1:], strict=False):
            supersede_previous_version(s, docs[old.key].id, docs[new.key].id, docs[new.key].file_created_at)


# ---------------------------------------------------------------- metrics helpers
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _covered_pairs(items: list[dict], docs: dict[str, Document], top: int = 20) -> set[tuple[str, int]]:
    by_id = {str(d.id): k for k, d in docs.items()}
    pairs = set()
    for it in items[:top]:
        key = by_id.get(str(it.get("document_id")))
        if key is None:
            continue
        for c in it.get("citations") or []:
            if c.get("page_no"):
                pairs.add((key, int(c["page_no"])))
    return pairs


def _citation_ok(s: Session, cite: dict) -> bool:
    if not cite.get("document_id"):
        return False
    rec = s.get(MemoryRecord, uuid.UUID(cite["item_id"])) if cite.get("kind") == "record" else None
    page = s.scalar(select(Page).where(Page.document_id == uuid.UUID(cite["document_id"]), Page.page_no == cite.get("page_no")).order_by(Page.id.desc())) if cite.get("page_no") else None
    if page is None:
        return False
    q = _norm(cite.get("quote") or "")[:60]
    if not q:
        return True
    return q in _norm(page.text) or (rec is not None and q in _norm(rec.detail))


def _p(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1)))], 2)


# ---------------------------------------------------------------- arms
def _bm25_arm(s: Session, retriever: Retriever, principal: Principal, scope_id, q: QA, at=None) -> tuple[Any, float]:
    """BM25 over all visible records and sections; packet built from top hits."""
    t0 = time.perf_counter()
    vis = visible_scopes(s, principal)
    allowed = [x for x in addressable_scope_ids(s, scope_id) if x in vis.scope_ids]
    if not allowed:
        raise PermissionError("no scopes")
    intent = classify(q.question)
    rec_filter, _ = retriever._record_filter(vis, allowed, principal.tenant_id, intent, at, {})
    recs = list(s.scalars(select(MemoryRecord).where(rec_filter)))
    idx = BM25Index()
    for r in recs:
        idx.add(("rec", r.id), f"{r.summary} {r.detail}")
    secs = list(s.scalars(select(Section).where(Section.tenant_id == principal.tenant_id, Section.scope_id.in_(allowed),
                                                  vis.sql_filter(Section.scope_id, Section.sensitivity))))
    for sec in secs:
        idx.add(("sec", sec.id), f"{sec.title or ''} {sec.text}")
    hits = idx.search(q.question, k=50)
    rmap = {r.id: r for r in recs}
    smap = {x.id: x for x in secs}
    cands = []
    for (kind, rid), score in hits:
        if kind == "rec" and rid in rmap:
            cands.append(rerank_mod.Candidate(rmap[rid], None, score, {"bm25": (0, score)}))
        elif kind == "sec" and rid in smap:
            cands.append(rerank_mod.Candidate(None, smap[rid], score, {"bm25": (0, score)}))
    ranked = rerank_mod.rerank(cands, intent, q.question)
    pk = packet_mod.build(s, tenant_id=principal.tenant_id, principal_id=principal.id, query=q.question, intent=intent.kind, scope_ids=allowed,
                          filters={"arm": "bm25"}, ranked=ranked, conflicts={}, min_records=20, max_records=100, token_budget=12000,
                          trace={"arm": "bm25"}, latency_ms=0.0)
    lat = (time.perf_counter() - t0) * 1000
    return (pk, intent), lat


ARMS: dict[str, dict[str, Any]] = {
    "vector-only": {"use_lexical": False, "use_exact": False, "use_graph": False},
    "bm25-only": {"bm25": True},
    "hybrid": {"use_graph": False},
    "hybrid+graph(unbounded)": {"use_graph": True, "coef": 10_000.0},
    "hybrid+graph(bounded, REM)": {"use_graph": True},
    "hybrid+cliques(topological)": {"use_graph": True, "graph_mode": "cliques"},
    "hybrid+cliques+bonus": {"use_graph": True, "graph_mode": "cliques+bonus"},
}


def run(out: Path, scale: int = 1, embedder=None, ocr=None, docs_qas=None) -> dict[str, Any]:
    settings = get_settings()
    embedder = embedder or get_embedding_provider(settings)
    ocr = ocr or build_ocr(settings)
    docs, qas = docs_qas or build(n_filler=6 * scale)
    report: dict[str, Any] = {"embedding_provider": getattr(embedder, "name", "?"), "ocr": getattr(ocr, "name", None), "docs": len(docs), "questions": len(qas)}
    with session_scope() as s:
        t0 = time.perf_counter()
        world = ingest_corpus(s, docs, embedder=embedder, ocr=ocr)
        report["ingest_seconds"] = round(time.perf_counter() - t0, 1)
        tid = world.tenant.id
        report["storage"] = _storage(s, tid)
        # full-context arm: how many tokens a model would have to hold per principal
        full_ctx = {}
        for pname, p in world.principals.items():
            vis = visible_scopes(s, p)
            pages = s.scalars(select(Page).join(Document, Document.id == Page.document_id).where(Document.tenant_id == tid, Document.deleted_at.is_(None),
                                                                                                vis.sql_filter(Document.scope_id, Document.sensitivity)))
            toks = sum(estimate_tokens(pg.text) for pg in pages)
            full_ctx[pname] = {"tokens_per_question": toks, "est_cost_per_question_usd(claude-sonnet-5)": estimate_cost("claude-sonnet-5", toks, 300)}
        report["full-context"] = {**full_ctx, "answers_measured": False, "note": "no LLM provider configured in this build; token load and cost are reported, answer quality is not"}
        # warm metadata lookup latency
        doc_ids = [d.id for d in world.docs.values()]
        lat = []
        for i in range(200):
            t = time.perf_counter()
            s.get(Document, doc_ids[i % len(doc_ids)])
            s.execute(select(MemoryRecord.id).where(MemoryRecord.source_document_id == doc_ids[i % len(doc_ids)]).limit(5)).all()
            lat.append((time.perf_counter() - t) * 1000)
        report["warm_metadata_lookup_ms"] = {"p50": _p(lat, 0.5), "p95": _p(lat, 0.95)}
        arms_out = {}
        for arm, cfg in ARMS.items():
            arms_out[arm] = _run_arm(s, world, qas, arm, cfg, embedder)
        report["arms"] = arms_out
        report["per_question"] = {arm: v.pop("per_question") for arm, v in arms_out.items()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench_retrieval.json").write_text(json.dumps(report, indent=2, default=str))
    md = to_markdown(report)
    (out / "bench_retrieval.md").write_text(md)
    print(md)
    return report


def _run_arm(s: Session, world: World, qas: list[QA], arm: str, cfg: dict, embedder) -> dict[str, Any]:
    settings = get_settings()
    if "coef" in cfg:
        settings = settings.model_copy(update={"graph_budget_coefficient": cfg["coef"]})
    retriever = Retriever(s, settings, embedder=embedder)
    recalls, exact_ok, exact_n, cite_ok, cite_n, status_ok, lats, toks, leaks = [], 0, 0, 0, 0, 0, [], [], 0
    per_q = []
    for q in qas:
        principal = world.principals[q.principal]
        scope_id = world.scopes[q.scope].id
        try:
            if cfg.get("bm25"):
                (pk, intent), lat = _bm25_arm(s, retriever, principal, scope_id, q)
                result = extractive(pk, intent)
            else:
                t0 = time.perf_counter()
                res = retriever.retrieve(q.question, principal, scope_id, **{k: v for k, v in cfg.items() if k.startswith("use_") or k == "graph_mode"})
                lat = (time.perf_counter() - t0) * 1000
                pk, intent = res.packet, res.intent
                result = extractive(pk, intent)
        except PermissionError:
            pk, result, lat = None, None, 0.0
        status = result.status if result else "insufficient_evidence"
        answer = result.answer if result else ""
        items = pk.items if pk else []
        lats.append(lat)
        toks.append(pk.token_estimate if pk else 0)
        if q.relevant:
            covered = _covered_pairs(items, world.docs)
            recalls.append(len(covered & set(q.relevant)) / len(q.relevant))
        status_ok += int(status == q.expected_status)
        if q.expected_status == "answered":
            exact_n += 1
            good = status == "answered" and any(sub in answer for sub in q.expected_substrings) and not any(f in answer for f in q.forbidden_substrings)
            exact_ok += int(good)
        bad_cites = []
        if result and result.status in ("answered", "conflict"):
            for c in result.citations:
                cite_n += 1
                ok = _citation_ok(s, c)
                cite_ok += int(ok)
                if not ok:
                    bad_cites.append({"kind": c.get("kind"), "type": c.get("type"), "page_no": c.get("page_no"), "quote": (c.get("quote") or "")[:100]})
        if q.kind == "permission" and q.principal != "admin":
            restricted_ids = {str(d.id) for k, d in world.docs.items() if k == "hr_restricted"}
            leaks += sum(1 for it in items if it.get("document_id") in restricted_ids)
            leaks += sum(1 for f in q.forbidden_substrings if f in answer)
        per_q.append({"qid": q.qid, "kind": q.kind, "expected": q.expected_status, "got": status, "correct": (status == q.expected_status) and
                      (q.expected_status != "answered" or any(sub in answer for sub in q.expected_substrings)), "latency_ms": round(lat, 1),
                      "packet_items": len(items), "answer": answer[:160], "bad_citations": bad_cites})
    n = len(qas)
    return {"recall@20": round(statistics.mean(recalls), 4) if recalls else None, "exact_field_accuracy": round(exact_ok / exact_n, 4) if exact_n else None,
            "exact_n": exact_n, "citation_correctness": round(cite_ok / cite_n, 4) if cite_n else None, "citations_checked": cite_n,
            "status_accuracy": round(status_ok / n, 4), "insufficient_evidence_detection": round(
                sum(1 for p_ in per_q if p_["expected"] == "insufficient_evidence" and p_["got"] == "insufficient_evidence") /
                max(1, sum(1 for p_ in per_q if p_["expected"] == "insufficient_evidence")), 4),
            "conflict_detection": round(sum(1 for p_ in per_q if p_["expected"] == "conflict" and p_["got"] == "conflict") /
                                        max(1, sum(1 for p_ in per_q if p_["expected"] == "conflict")), 4),
            "permission_leaks": leaks, "latency_ms_p50": _p(lats, 0.5), "latency_ms_p95": _p(lats, 0.95),
            "packet_tokens_avg": round(statistics.mean(toks), 1) if toks else 0, "per_question": per_q}


def _storage(s: Session, tid) -> dict[str, Any]:
    raw = s.execute(select(func.count(Blob.id), func.coalesce(func.sum(Blob.size_bytes), 0)).where(Blob.tenant_id == tid)).one()
    sizes = {}
    per_row = {}
    for table in ("pages", "blocks", "sections", "memory_records", "record_links", "evidence_packets"):
        sizes[table] = int(s.execute(func.pg_total_relation_size(table)).scalar() or 0)
        rows = int(s.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
        per_row[table] = round(sizes[table] / rows, 1) if rows else None
    counts = {"documents": s.scalar(select(func.count(Document.id)).where(Document.tenant_id == tid)),
              "pages": s.scalar(select(func.count(Page.id)).join(Document, Document.id == Page.document_id).where(Document.tenant_id == tid)),
              "sections": s.scalar(select(func.count(Section.id)).where(Section.tenant_id == tid)),
              "records": s.scalar(select(func.count(MemoryRecord.id)).where(MemoryRecord.tenant_id == tid))}
    return {"raw_blobs": int(raw[0]), "raw_bytes": int(raw[1]), "table_bytes_total_db": sizes, "bytes_per_row": per_row, "counts": counts}


def to_markdown(rep: dict) -> str:
    lines = [f"### Retrieval benchmark ({rep['docs']} documents, {rep['questions']} questions, embeddings={rep['embedding_provider']}, ocr={rep['ocr']}, ingest {rep['ingest_seconds']}s)", "",
             "| arm | recall@20 | exact-field acc | citation correctness | status acc | insufficient-evidence det. | conflict det. | permission leaks | p50 ms | p95 ms | packet tokens |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, v in rep["arms"].items():
        lines.append(f"| {arm} | {v['recall@20']} | {v['exact_field_accuracy']} (n={v['exact_n']}) | {v['citation_correctness']} (n={v['citations_checked']}) | {v['status_accuracy']} | "
                     f"{v['insufficient_evidence_detection']} | {v['conflict_detection']} | {v['permission_leaks']} | {v['latency_ms_p50']} | {v['latency_ms_p95']} | {v['packet_tokens_avg']} |")
    fc = rep["full-context"]
    lines += ["", "Full-context prompting (what a model would need to hold per question, by principal):", ""]
    for pname, v in fc.items():
        if isinstance(v, dict):
            lines.append(f"- {pname}: ~{v['tokens_per_question']:,} tokens/question, est. ${v['est_cost_per_question_usd(claude-sonnet-5)']:.4f}/question at claude-sonnet-5 prices")
    lines += [f"- {fc['note']}", "", f"Warm metadata lookup: p50 {rep['warm_metadata_lookup_ms']['p50']} ms, p95 {rep['warm_metadata_lookup_ms']['p95']} ms.",
              "", f"Storage: raw {rep['storage']['raw_bytes']:,} bytes in {rep['storage']['raw_blobs']} blobs; counts {rep['storage']['counts']}."]
    return "\n".join(lines)


def main(out: Path, scale: int = 1) -> dict:
    return run(out, scale=scale)
