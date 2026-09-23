"""EnterpriseRAG-Bench (onyx-dot-app) through the Company Intelligence Engine.

The benchmark simulates a company ("Redwood Inference") with about 512k
documents from nine sources (Slack, Gmail, Linear, Google Drive, HubSpot,
Fireflies, GitHub, Jira, Confluence) and 500 questions in ten categories, each
with the gold document ids and a gold answer. Its official scores (correctness,
completeness) need an LLM judge; document recall and extra documents do not.

This module loads a haystack (every gold document plus a stratified sample of
the rest, or the whole corpus), runs the questions through the full retrieval
pipeline in the extractive mode, computes the document metrics itself and writes
the answers file the benchmark's judge expects, so the LLM-judged scores can be
produced with the benchmark's own scripts and an API key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import statistics
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb
from sqlalchemy import select, text

from cie.core.db import session_scope
from cie.core.models import (
    Document,
    MemoryRecord,
    Permission,
    Principal,
    PrincipalKind,
    RecordType,
    ScopeKind,
    Tenant,
    VerificationStatus,
)
from cie.core.settings import get_settings
from cie.eval.bench_scale import _p
from cie.governance.permissions import ensure_role, grant_role
from cie.memory.embeddings import get_embedding_provider
from cie.memory.scopes import create_scope
from cie.retrieval.pipeline import Retriever

SOURCES = ["slack", "gmail", "linear", "google_drive", "hubspot", "fireflies", "github", "jira", "confluence"]
ENTITY_FIELDS = {"person": ["author", "owner", "creator", "assignee", "reporter", "mailbox_owner", "redwood_owner", "account_owner"],
                 "organization": ["customer_company", "related_account", "company_name", "company"]}
ARMS = {"hybrid+graph(REM)": {}, "hybrid+cliques+bonus": {"graph_mode": "cliques+bonus"},
        "vector-only": {"use_lexical": False, "use_exact": False, "use_graph": False},
        "lexical-only": {"use_vector": False, "use_exact": False, "use_graph": False}}
ASSISTED_ARM = "hybrid+graph(REM), composed answers"  # added by --assisted: the default arm with answers composed by the configured model


# ------------------------------------------------------------------ corpus
def read_doc(path: Path) -> dict[str, Any]:
    """Title, body and flat metadata of one exported record (JSON or plain-text layout)."""
    from cie.ingest.sources import read

    d = read(path, path.name)
    meta = {k: (v if isinstance(v, str | int | float | bool) else ", ".join(map(str, v)) if isinstance(v, list) and len(v) <= 12 else None)
            for k, v in d.meta.items()}
    meta = {k: str(v)[:200] for k, v in meta.items() if v not in (None, "", [])}
    return {"dsid": d.dsid, "title": d.title, "content": d.body, "meta": meta, "raw_keys": list(d.meta.keys())}


_SOURCE_HINTS = [("channel", "slack"), ("thread_ts", "slack"), ("mailbox_owner", "gmail"), ("thread_id", "gmail"), ("pr_number", "github"), ("repo", "github"),
                 ("meeting_id", "fireflies"), ("transcript", "fireflies"), ("space", "confluence"), ("drive_area", "google_drive"), ("doc_type", "google_drive"),
                 ("issue_type", "jira"), ("severity", "jira"), ("cycle", "linear"), ("estimate", "linear"), ("stage", "hubspot"), ("domain", "hubspot")]


def infer_source(rel: str, d: dict) -> str:
    """The source system: the top-level folder when the corpus is laid out per source,
    otherwise the field names that only that system produces (the release archives are flat)."""
    head = rel.split("/")[0]
    if head in SOURCES:
        return head
    for field, src in _SOURCE_HINTS:
        if field in d:
            return src
    return "google_drive"


def chunk(text: str, size: int = 1000, overlap: int = 120) -> list[str]:
    """Chunks of about ``size`` characters cut at sentence or line boundaries, with a small overlap."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out = []
    i = 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            cut = max(text.rfind("\n", i + size // 2, j), text.rfind(". ", i + size // 2, j))
            if cut > i:
                j = cut + 1
        out.append(text[i:j].strip())
        if j >= len(text):
            break
        i = max(j - overlap, i + 1)
    return [c for c in out if c]


def select_docs(index: dict[str, str], questions: list[dict], n_docs: int | None, seed: int) -> list[str]:
    """Every gold document plus a sample stratified by source in the corpus proportions."""
    gold = {d for q in questions for d in q["expected_doc_ids"]}
    if n_docs is None or n_docs >= len(index):
        return sorted(index)
    rng = random.Random(seed)
    by_src: dict[str, list[str]] = defaultdict(list)
    for dsid, rel in index.items():
        if dsid not in gold:
            by_src[rel.split("/")[0] if rel.split("/")[0] in SOURCES else "flat"].append(dsid)
    total = sum(len(v) for v in by_src.values())
    want = max(0, n_docs - len(gold))
    picked = set(gold)
    for pool in by_src.values():
        k = min(len(pool), round(want * len(pool) / total))
        picked.update(rng.sample(pool, k))
    return sorted(picked)


def build_index(root: Path, cache: Path | None = None, must_contain: set[str] | None = None, log=print) -> dict[str, str]:
    """dataset_doc_uuid -> path relative to ``root``, scanning every JSON once. A cached
    index is used only if it holds every id in ``must_contain`` (the gold documents):
    a cache written before the corpus was in place would otherwise silence the run."""
    if cache and cache.exists():
        blob = json.loads(cache.read_text())
        cached = blob.get("index", {})
        same_root = blob.get("root") == str(root.resolve())
        sample = list(cached.values())[:: max(1, len(cached) // 20)][:20]
        if cached and same_root and all((root / r).exists() for r in sample) and (not must_contain or must_contain <= set(cached)):
            return cached
        log(f"  cached index at {cache} is empty, incomplete or for another corpus location; rescanning {root}")
    index = {}
    for dirpath, _, files in os.walk(root):
        for name in files:
            p = Path(dirpath) / name
            if name.endswith(".txt") and name.startswith("dsid_"):  # plain-text release layout: the id is in the file name
                index[name[:37]] = str(p.relative_to(root))
                continue
            if not name.endswith(".json"):
                continue
            raw = p.read_bytes()
            i = raw.find(b"dsid_")
            if i >= 0:
                index[raw[i:i + 37].decode()] = str(p.relative_to(root))
    if cache and index:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"root": str(root.resolve()), "index": index}))
    return index


# ------------------------------------------------------------------ load
def new_tenant(tenant_name: str) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    """A tenant with one company scope, a department scope per source system and an admin."""
    with session_scope() as s:
        tenant = Tenant(name=tenant_name)
        s.add(tenant)
        s.flush()
        company = create_scope(s, tenant.id, ScopeKind.company, "Redwood Inference")
        scopes = {src: create_scope(s, tenant.id, ScopeKind.department, src, company) for src in SOURCES + ["unknown"]}
        admin = Principal(tenant_id=tenant.id, kind=PrincipalKind.user, name="admin")
        s.add(admin)
        s.flush()
        grant_role(s, tenant_id=tenant.id, principal=admin, role=ensure_role(s, tenant.id, "admin", Permission.admin, 4), scope=company)
        s.commit()
        return tenant.id, company.id, {src: sc.id for src, sc in scopes.items()}


def _build_batch(args: tuple[str, list[str]]) -> tuple[list, int]:
    """Worker: read and build the memory of a batch of documents (no database)."""
    from cie.ingest.builder import build
    from cie.ingest.sources import read

    root, rels = args
    out, failed = [], 0
    for rel in rels:
        try:
            out.append(build(read(Path(root) / rel, rel)))
        except Exception:  # noqa: BLE001 - one malformed export must not stop a 500k-document load
            failed += 1
    return out, failed


def load_full(url: str, root: Path, index: dict[str, str], dsids: list[str], embedder, *, tenant_name: str, batch: int = 64,
              workers: int | None = None, cache: Path | None = None, rebuild_indexes_above: int = 20_000, log=print) -> dict[str, Any]:
    """The full memory bank (cie.ingest): field-aware sections, extractive summaries and tags,
    typed records, company-wide entities and projects, cross-document references,
    near-duplicates and the facts they disagree on. Documents are built in worker
    processes while the main process embeds and writes; at most two batches per worker
    are in flight, so memory stays flat at any corpus size."""
    from cie.eval.bench_scale import build_indexes, drop_indexes
    from cie.ingest.bulk import BulkLoader, CachedEmbedder

    t0 = time.perf_counter()
    tenant_id, company_id, scope_ids = new_tenant(tenant_name)
    rebuild = len(dsids) > rebuild_indexes_above
    cached = CachedEmbedder(embedder, cache)
    loader = BulkLoader(url, tenant_id=tenant_id, company_id=company_id, scope_ids=scope_ids, embedder=cached, log=log)
    if rebuild:
        with psycopg.connect(url) as conn:
            log("  dropping vector/text indexes for the bulk load (rebuilt afterwards)")
            drop_indexes(conn)
    index_build: dict[str, float] = {}
    try:
        stats, failed = _fill(loader, cached, root, index, dsids, batch=batch, workers=workers, t0=t0, log=log)
    finally:  # the indexes are shared by every tenant: never leave them dropped, even when the load fails
        loader.close()
        if rebuild:
            log("  rebuilding indexes ...")
            with psycopg.connect(url) as conn:
                index_build = build_indexes(conn)
            log(f"  indexes rebuilt in {sum(index_build.values()):.0f} s")
    records = sum(v for k, v in stats.items() if k.startswith("rec_"))
    return {"tenant_id": str(tenant_id), "tenant_name": tenant_name, "company_id": str(company_id), "memory": "full",
            "documents": stats.get("documents", 0), "failed": failed + stats.get("documents_failed", 0),
            "sections": stats.get("sections", 0), "records": records, "records_by_type": {k[4:]: v for k, v in stats.items() if k.startswith("rec_")},
            "links_by_kind": {k[5:]: v for k, v in stats.items() if k.startswith("link_")}, "entities": stats.get("entities", 0),
            "restricted_entities": stats.get("restricted_entities", 0), "projects": stats.get("projects", 0),
            "near_duplicate_pairs": stats.get("near_duplicate_pairs", 0), "contradictions": stats.get("contradictions", 0),
            "contradiction_records": stats.get("contradiction_records", 0), "refs_unresolved": stats.get("refs_unresolved", 0),
            "refs_ambiguous": stats.get("refs_ambiguous", 0), "same_key_collisions": stats.get("same_key_collisions", 0),
            "load_seconds": round(time.perf_counter() - t0, 1), "embed_seconds": round(loader.t_embed, 1),
            "embedding_cache_hits": cached.hits, "embedded_texts": cached.misses, "finish_seconds": stats.get("finish_seconds"),
            "index_build_seconds": index_build}


def _fill(loader, cached, root: Path, index: dict[str, str], dsids: list[str], *, batch: int, workers: int | None, t0: float,
          log) -> tuple[dict[str, Any], int]:
    from collections import deque
    from concurrent.futures import ProcessPoolExecutor

    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    rels = [index[d] for d in dsids]
    batches = [(str(root), rels[i:i + batch]) for i in range(0, len(rels), batch)]
    failed = done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        pending: deque = deque()
        it = iter(batches)
        for b in it:
            pending.append(ex.submit(_build_batch, b))
            if len(pending) >= 2 * workers:
                break
        while pending:
            mems, f = pending.popleft().result()
            nxt = next(it, None)
            if nxt is not None:
                pending.append(ex.submit(_build_batch, nxt))
            loader.write_batch(mems)
            failed += f
            done += len(mems) + f
            if done % (batch * 20) < batch or not pending:
                el = time.perf_counter() - t0
                log(f"  loaded {done:,}/{len(dsids):,} documents, {loader.stats['sections']:,} sections, "
                    f"{sum(v for k, v in loader.stats.items() if k.startswith('rec_')):,} records; {loader.t_embed:.0f} s embedding "
                    f"(cache hits {cached.hits:,}), {el:.0f} s total, ~{el / max(done, 1) * (len(dsids) - done) / 60:.0f} min left")
    log("  linking documents, near-duplicates, conflicting facts, entity profiles ...")
    return loader.finish(), failed


def load(url: str, root: Path, index: dict[str, str], dsids: list[str], embedder, *, tenant_name: str, batch: int = 64,
         entities: bool = True, rebuild_indexes_above: int = 20_000, log=print) -> dict[str, Any]:
    """Above ``rebuild_indexes_above`` documents the vector and text indexes are dropped
    before the load and rebuilt after it (an insert into an HNSW index costs far more
    than its share of a bulk build)."""
    from cie.eval.bench_scale import build_indexes, drop_indexes

    t0 = time.perf_counter()
    rebuild = len(dsids) > rebuild_indexes_above
    tenant_id, company_id, scope_ids = new_tenant(tenant_name)
    n_sections = n_records = 0
    embed_s = 0.0
    T0 = None
    index_build: dict[str, float] = {}
    with psycopg.connect(url) as conn:
        register_vector(conn)
        if rebuild:
            log("  dropping vector/text indexes for the bulk load (rebuilt afterwards)")
            drop_indexes(conn)
        from psycopg.types.enum import EnumInfo, register_enum
        from psycopg.types.string import StrBinaryDumperVarchar

        for tname, py in (("record_type", RecordType), ("verification_status", VerificationStatus)):
            register_enum(EnumInfo.fetch(conn, tname), conn, py)
        conn.adapters.register_dumper(str, StrBinaryDumperVarchar)
        ext_id = None
        doc_meta: dict[uuid.UUID, dict] = {}
        for start in range(0, len(dsids), batch):
            group = dsids[start:start + batch]
            docs = []
            for dsid in group:
                rel = index[dsid]
                d = read_doc(root / rel)
                d["rel"], d["source"] = rel, infer_source(rel, dict.fromkeys(d.pop("raw_keys")))  # noqa: E501
                docs.append(d)
            # texts to embed: each section (title + chunk) and the document record (source, title, opening)
            sec_texts, sec_ref = [], []
            for di, d in enumerate(docs):
                header = " | ".join(f"{k}: {v}" for k, v in list(d["meta"].items())[:12])
                chunks = chunk(d["content"]) or [""]
                d["chunks"] = chunks
                d["header"] = header
                for ci, c in enumerate(chunks):
                    sec_texts.append(f"{d['title']}\n{c}")
                    sec_ref.append((di, ci))
            rec_texts = [f"{d['source']}: {d['title']}\n{d['content'][:400]}" for d in docs]
            t = time.perf_counter()
            vecs = embedder.embed(sec_texts + rec_texts)
            embed_s += time.perf_counter() - t
            sec_vecs, rec_vecs = vecs[:len(sec_texts)], vecs[len(sec_texts):]
            with conn.cursor() as cur:
                cur.execute("SET LOCAL synchronous_commit = off")
                doc_ids = [uuid.uuid4() for _ in docs]
                blob_ids = [uuid.uuid4() for _ in docs]
                with cur.copy("COPY blobs (id, tenant_id, sha256, size_bytes, media_type, storage_uri, encrypted, created_at) FROM STDIN WITH (FORMAT BINARY)") as cp:
                    cp.set_types(["uuid", "uuid", "text", "int8", "text", "text", "bool", "timestamptz"])
                    for d, bid in zip(docs, blob_ids, strict=True):
                        sha = hashlib.sha256(d["rel"].encode()).hexdigest()
                        cp.write_row((bid, tenant_id, sha, len(d["content"]), "application/json", f"file://{root / d['rel']}", False, T0 or _now()))
                with cur.copy("COPY documents (id, tenant_id, blob_id, family_id, version, title, original_filename, source, scope_id, sensitivity, acl, "
                              "retention_policy, legal_hold, ingested_at, extra, status, injection_flags, pii_flags, doc_type, file_created_at) FROM STDIN WITH (FORMAT BINARY)") as cp:
                    cp.set_types(["uuid", "uuid", "uuid", "uuid", "int4", "text", "text", "text", "uuid", "int4", "jsonb", "text", "bool", "timestamptz",
                                  "jsonb", "text", "jsonb", "jsonb", "text", "timestamptz"])
                    for d, did, bid in zip(docs, doc_ids, blob_ids, strict=True):
                        ident = d["meta"].get("key") or d["dsid"] or d["title"][:120]  # never the export path: it would steer retrieval
                        cp.write_row((did, tenant_id, bid, uuid.uuid4(), 1, d["title"][:500], f"{d['source']}:{ident}"[:500], "enterprise-rag-bench",
                                      scope_ids[d["source"]], 1, Jsonb({}),
                                      "default", False, _now(), Jsonb({"dsid": d["dsid"], "source": d["source"], **{k: v for k, v in list(d["meta"].items())[:20]}}),
                                      "indexed", Jsonb([]), Jsonb([]), d["source"], None))
                        doc_meta[did] = {"dsid": d["dsid"], "meta": d["meta"], "source": d["source"], "title": d["title"]}
                if ext_id is None:
                    ext_id = uuid.uuid4()
                    cur.execute("INSERT INTO extractions (id, tenant_id, document_id, extractor, extractor_version, status, page_count, pages_done, completeness, stats, created_at) "
                                "VALUES (%s, %s, %s, 'enterprise_loader', '1', 'done', 1, 1, '{}', '{}', %s)", (ext_id, tenant_id, doc_ids[0], _now()))
                with cur.copy("COPY sections (id, tenant_id, document_id, extraction_id, scope_id, order_index, title, level, page_start, page_end, text, text_sha256, "
                              "token_estimate, spans, embedding, sensitivity) FROM STDIN WITH (FORMAT BINARY)") as cp:
                    cp.set_types(["uuid", "uuid", "uuid", "uuid", "uuid", "int4", "text", "int4", "int4", "int4", "text", "text", "int4", "jsonb", "vector", "int4"])
                    for (di, ci), vec in zip(sec_ref, sec_vecs, strict=True):
                        d = docs[di]
                        body = (d["header"] + "\n\n" if ci == 0 and d["header"] else "") + d["chunks"][ci]
                        cp.write_row((uuid.uuid4(), tenant_id, doc_ids[di], ext_id, scope_ids[d["source"]], ci, d["title"][:300], 1, 1, 1, body,
                                      hashlib.sha256(body.encode()).hexdigest(), len(body) // 4, Jsonb([{"page_no": 1, "block_ids": [], "bbox": [0, 0, 0, 0]}]),
                                      vec, 1))
                        n_sections += 1
                cols = ("id, tenant_id, scope_id, type, summary, content, detail, source_document_id, source_locations, event_time, valid_from, valid_to, recorded_at, "
                        "producing_agent, confidence, verification, sensitivity, acl, version, family_id, entity_ids, keywords, glyph, embedding, content_sha256")
                with cur.copy(f"COPY memory_records ({cols}) FROM STDIN WITH (FORMAT BINARY)") as cp:
                    cp.set_types(["uuid", "uuid", "uuid", "record_type", "text", "jsonb", "text", "uuid", "jsonb", "timestamptz", "timestamptz", "timestamptz", "timestamptz",
                                  "text", "float8", "verification_status", "int4", "jsonb", "int4", "uuid", "jsonb", "varchar[]", "jsonb", "vector", "text"])
                    for d, did, vec in zip(docs, doc_ids, rec_vecs, strict=True):
                        rid = uuid.uuid4()
                        kws = [w for w in re.findall(r"[a-z][a-z0-9_-]{3,}", d["title"].lower())][:8]
                        summary = f"{d['source']}: {d['title']}"[:400]
                        detail = (d["header"] + "\n\n" if d["header"] else "") + d["content"][:2000]
                        glyph = {"v": 1, "id": str(rid), "type": "document", "what": summary[:120], "confidence": 0.8, "status": "current"}
                        cp.write_row((rid, tenant_id, scope_ids[d["source"]], RecordType.document, summary, Jsonb({"dsid": d["dsid"], "source": d["source"], "title": d["title"]}),
                                      detail, did, Jsonb([{"page_no": 1, "quote": d["title"][:120]}]), None, None, None, _now(), "enterprise_loader", 0.8,
                                      VerificationStatus.unverified, 1, Jsonb({}), 1, uuid.uuid4(), Jsonb([]), kws, Jsonb(glyph), vec,
                                      hashlib.sha256(detail.encode()).hexdigest()))
                        n_records += 1
            conn.commit()
            done = start + len(group)
            if done % (batch * 10) == 0 or done == len(dsids):
                log(f"  loaded {done}/{len(dsids)} documents, {n_sections} sections, {embed_s:.0f} s embedding, {time.perf_counter() - t0:.0f} s total")
        with conn.cursor() as cur:
            cur.execute("UPDATE memory_records SET tsv = setweight(to_tsvector('english', summary), 'A') || setweight(to_tsvector('english', left(detail, 20000)), 'B') "
                        "WHERE tenant_id = %s AND tsv IS NULL", (tenant_id,))
            cur.execute("UPDATE sections SET tsv = setweight(to_tsvector('english', coalesce(title, '')), 'A') || setweight(to_tsvector('english', text), 'B') "
                        "WHERE tenant_id = %s AND tsv IS NULL", (tenant_id,))
            cur.execute("ANALYZE memory_records")
            cur.execute("ANALYZE sections")
            cur.execute("ANALYZE documents")
        conn.commit()
        if rebuild:
            log("  rebuilding indexes ...")
            index_build = build_indexes(conn)
            log(f"  indexes rebuilt in {sum(index_build.values()):.0f} s: {index_build}")
    n_entities = 0
    if entities:
        n_entities = _link_entities(tenant_id, doc_meta, log)
    return {"tenant_id": str(tenant_id), "company_id": str(company_id), "documents": len(dsids), "sections": n_sections, "records": n_records,
            "entities": n_entities, "load_seconds": round(time.perf_counter() - t0, 1), "embed_seconds": round(embed_s, 1),
            "embed_texts_per_s": round((n_sections + n_records) / max(embed_s, 1e-6), 1), "index_build_seconds": index_build}


def _link_entities(tenant_id, doc_meta: dict, log) -> int:
    """People and companies named in the metadata become canonical entity records
    (resolved across the tenant) mentioned by the document record."""
    from cie.memory.entities import attach_entities

    n = 0
    with session_scope() as s:
        recs = {r.source_document_id: r for r in s.scalars(select(MemoryRecord).where(MemoryRecord.tenant_id == tenant_id, MemoryRecord.type == RecordType.document))}
        for i, (did, dm) in enumerate(doc_meta.items()):
            rec = recs.get(did)
            if rec is None:
                continue
            for rtype, fields in ENTITY_FIELDS.items():
                names = [dm["meta"][f] for f in fields if dm["meta"].get(f) and 2 < len(dm["meta"][f]) < 80 and "," not in dm["meta"][f]]
                if names:
                    n += len(attach_entities(s, rec, names[:2], RecordType(rtype)))
            if (i + 1) % 2000 == 0:
                s.commit()
                log(f"  entities: {i + 1}/{len(doc_meta)} documents, {n} links")
        s.commit()
    return n


def _now():
    from cie.core.util import utcnow

    return utcnow()


# ------------------------------------------------------------------ evaluate
def evaluate(session, retriever: Retriever, admin, company_id, questions: list[dict], dsid_of: dict[str, str], *, arms: dict, k: int = 10,
             out: Path, log=print) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for arm, cfg in arms.items():
        cfg = dict(cfg)
        mode = cfg.pop("mode", "strict")
        provider = None
        if mode == "assisted":
            provider = assisted_provider(retriever.settings)
        spend = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "declined": 0, "cost_unknown": 0}
        per_cat: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        answers = []
        lat = []
        for qi, q in enumerate(questions):
            gold = set(q["expected_doc_ids"])
            t = time.perf_counter()
            try:
                session.execute(text("SET LOCAL statement_timeout = '60s'"))
                result, res = retriever.answer(q["question"], admin, company_id, mode=mode, provider=provider, **cfg)
                spend["tokens_in"] += result.tokens_in or 0
                spend["tokens_out"] += result.tokens_out or 0
                spend["cost_usd"] += result.cost_usd or 0.0
                spend["cost_unknown"] += int(mode == "assisted" and bool(result.tokens_in) and not getattr(result, "cost_known", True))
                spend["declined"] += "declined" in (result.mode or "")
                ms = (time.perf_counter() - t) * 1000
                docs: list[str] = []
                if result.status != "insufficient_evidence":
                    for it in res.packet.items:
                        d = dsid_of.get(str(it.get("document_id")))
                        if d and d not in docs:
                            docs.append(d)
                        if len(docs) >= k:
                            break
                answer_text = result.answer
                status = result.status
            except Exception as e:  # noqa: BLE001 - a failed question is a result (zero recall), never an abstention
                session.rollback()
                ms, docs, answer_text, status = 60_000.0, [], f"error: {type(e).__name__}: {e}"[:300], "error"
                log(f"  [{arm}] question {q['question_id']} failed: {answer_text}")
            session.rollback()  # no packets, answers or audit rows from the benchmark stay behind
            lat.append(ms)
            cat = q["question_type"]
            c = per_cat[cat]
            c["n"].append(1)
            c["latency"].append(ms)
            c["errors"].append(1 if status == "error" else 0)
            if status != "error":
                c["abstained"].append(1 if not docs else 0)
            if gold:
                c["recall"].append(len(gold & set(docs)) / len(gold))
                c["recall5"].append(len(gold & set(docs[:5])) / len(gold))
                first = next((i for i, d in enumerate(docs) if d in gold), None)
                c["hit1"].append(1 if first == 0 else 0)
                c["hit5"].append(1 if first is not None and first < 5 else 0)
                c["hit10"].append(1 if first is not None and first < 10 else 0)
                c["rr"].append(1.0 / (first + 1) if first is not None else 0.0)
                c["extras"].append(len([d for d in docs if d not in gold]))
                c["full"].append(1 if gold <= set(docs) else 0)
            answers.append({"question_id": q["question_id"], "answer": answer_text, "document_ids": docs, "status": status, "category": cat})
            if (qi + 1) % 100 == 0:
                log(f"  [{arm}] {qi + 1}/{len(questions)} questions")
        summary = {}
        for cat, c in per_cat.items():
            summary[cat] = {"n": len(c["n"]), "recall@10": _mean(c["recall"]), "recall@5": _mean(c["recall5"]), "hit@1": _mean(c["hit1"]), "hit@5": _mean(c["hit5"]),
                            "hit@10": _mean(c["hit10"]), "mrr": _mean(c["rr"]), "all_gold_found": _mean(c["full"]), "extras@10": _mean(c["extras"]),
                            "abstained": _mean(c["abstained"]), "errors": sum(c["errors"]), "p50_ms": _p(c["latency"], 0.5)}
        with_gold = [c for cat, c in per_cat.items() if c["recall"]]
        overall = {"questions": len(questions), "with_gold": sum(len(c["recall"]) for c in with_gold),
                   "recall@10": _mean([x for c in with_gold for x in c["recall"]]), "recall@5": _mean([x for c in with_gold for x in c["recall5"]]),
                   "mrr": _mean([x for c in with_gold for x in c["rr"]]), "hit@10": _mean([x for c in with_gold for x in c["hit10"]]),
                   "hit@1": _mean([x for c in with_gold for x in c["hit1"]]), "extras@10": _mean([x for c in with_gold for x in c["extras"]]),
                   "all_gold_found": _mean([x for c in with_gold for x in c["full"]]),
                   "abstained_on_info_not_found": _mean(per_cat["info_not_found"]["abstained"]) if "info_not_found" in per_cat else None,
                   "false_abstentions": _mean([a for cat, c in per_cat.items() if c["recall"] for a in c["abstained"]]),
                   "errors": sum(sum(c["errors"]) for c in per_cat.values()),
                   "p50_ms": _p(lat, 0.5), "p95_ms": _p(lat, 0.95)}
        if mode == "assisted":
            overall["answer_mode"] = "assisted"
            overall["llm"] = {**spend, "cost_usd": round(spend["cost_usd"], 2), "model": getattr(provider, "model", None),
                              "cost_complete": spend["cost_unknown"] == 0}
        results[arm] = {"overall": overall, "by_category": summary}
        out.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^a-z0-9]+", "_", arm.lower()).strip("_")
        (out / f"answers_{safe}.jsonl").write_text("\n".join(json.dumps({k_: v for k_, v in a.items() if k_ in ("question_id", "answer", "document_ids")}) for a in answers) + "\n")
        (out / f"answers_{safe}_detail.jsonl").write_text("\n".join(json.dumps(a) for a in answers) + "\n")
        log(f"[{arm}] recall@10 {overall['recall@10']} mrr {overall['mrr']} extras {overall['extras@10']} p50 {overall['p50_ms']} ms")
    return results


def assisted_provider(settings):
    """The model that composes answers; a run that asked for composed answers without one fails before loading anything."""
    from cie.agents.providers import NoProvider, get_provider

    provider = get_provider(settings)
    if isinstance(provider, NoProvider):
        raise SystemExit("--assisted needs a model: set CIE_LLM_PROVIDER (e.g. anthropic), CIE_LLM_MODEL and the provider's API key")
    return provider


def code_version() -> str:
    """The commit the benchmark ran on (or the package version outside a checkout)."""
    import subprocess

    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                             cwd=Path(__file__).resolve().parent).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=5,
                               cwd=Path(__file__).resolve().parent).stdout.strip()
        if sha:
            return sha + ("+modified" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        pass
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("cie")
    except PackageNotFoundError:
        return "unknown"


def _mean(xs):
    return round(statistics.mean(xs), 3) if xs else None


# ------------------------------------------------------------------ run
def run(root: Path, out: Path, n_docs: int | None, questions_file: Path | None = None, arms: dict | None = None, seed: int = 5,
        entities: bool = True, reuse_tenant: str | None = None, n_questions: int | None = None, batch: int = 64, memory: str = "full",
        workers: int | None = None, log=print) -> dict[str, Any]:
    settings = get_settings()
    if any((cfg or {}).get("mode") == "assisted" for cfg in (arms or ARMS).values()):
        assisted_provider(settings)
    embedder = get_embedding_provider(settings)
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    from cie.eval.bench_scale import ensure_indexes

    with psycopg.connect(url) as conn:
        built = ensure_indexes(conn)  # an earlier run that died mid-load may have left them dropped
        if built:
            log(f"  rebuilt missing indexes: {built}")
    questions = [json.loads(line) for line in (questions_file or root / "questions.jsonl").read_text().splitlines() if line.strip()]
    if n_questions:
        questions = questions[:n_questions]
    sources_root = root / "generated_data" / "sources"
    gold = {d for q in questions for d in q["expected_doc_ids"]}
    index = build_index(sources_root, cache=out / "index.json", must_contain=gold, log=log)
    missing = gold - set(index)
    if not index or missing:
        raise SystemExit(f"corpus not found or incomplete under {sources_root}: {len(index):,} documents indexed, "
                         f"{len(missing)} of {len(gold)} gold documents missing (clone https://github.com/onyx-dot-app/EnterpriseRAG-Bench, "
                         f"whose generated_data/sources holds the JSON records with their metadata)")
    report: dict[str, Any] = {"benchmark": "EnterpriseRAG-Bench (onyx-dot-app)", "corpus_documents": len(index), "questions": len(questions),
                              "question_ids_sha1": hashlib.sha1(",".join(q["question_id"] for q in questions).encode()).hexdigest()[:12],
                              "embedding": getattr(embedder, "name", "?"), "code_version": code_version()}
    if reuse_tenant:
        with session_scope() as s:
            tenant = s.scalar(select(Tenant).where(Tenant.name == reuse_tenant))
            if tenant is None:
                raise SystemExit(f"no tenant named {reuse_tenant!r} in this database")
            company = s.scalar(select(text("id")).select_from(text("scopes")).where(text("tenant_id = :t AND parent_id IS NULL")).params(t=tenant.id))
            report["load"] = {"tenant_id": str(tenant.id), "tenant_name": reuse_tenant, "company_id": str(company),
                              "documents": s.scalar(select(text("count(*)")).select_from(text("documents")).where(text("tenant_id = :t")).params(t=tenant.id)),
                              "reused": True}
    else:
        dsids = select_docs(index, questions, n_docs, seed)
        log(f"loading {len(dsids)} documents ({len({d for q in questions for d in q['expected_doc_ids']})} gold) into a new tenant ...")
        if memory == "full":
            report["load"] = load_full(url, sources_root, index, dsids, embedder, tenant_name=f"erbfull-{len(dsids)}-{uuid.uuid4().hex[:6]}",
                                       batch=batch, workers=workers, cache=out / "emb_cache.sqlite", log=log)
        else:
            report["load"] = load(url, sources_root, index, dsids, embedder, tenant_name=f"erb-{len(dsids)}-{uuid.uuid4().hex[:6]}",
                                  entities=entities, batch=batch, log=log)
        log(f"loaded: {report['load']}")
    with session_scope() as s:
        tenant_id = uuid.UUID(report["load"]["tenant_id"])
        company_id = uuid.UUID(report["load"]["company_id"])
        admin = s.scalar(select(Principal).where(Principal.tenant_id == tenant_id, Principal.name == "admin"))
        dsid_of = {str(d_id): extra.get("dsid") for d_id, extra in s.execute(select(Document.id, Document.extra).where(Document.tenant_id == tenant_id)).all()}
        report["haystack_documents"] = len(dsid_of)
        report["haystack_sha1"] = hashlib.sha1(",".join(sorted(d for d in dsid_of.values() if d)).encode()).hexdigest()[:12]
        retriever = Retriever(s, settings, embedder=embedder)
        report["arms"] = evaluate(s, retriever, admin, company_id, questions, dsid_of, arms=arms or ARMS, out=out, log=log)
        s.rollback()
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench_enterprise.json").write_text(json.dumps(report, indent=2, default=str))
    md = to_markdown(report)
    (out / "bench_enterprise.md").write_text(md)
    print(md)
    return report


def to_markdown(rep: dict[str, Any]) -> str:
    ld = rep["load"]
    lines = [f"### EnterpriseRAG-Bench through CIE (haystack {rep.get('haystack_documents', ld.get('documents')):,} of {rep['corpus_documents']:,} documents, "
             f"{rep['questions']} questions, embeddings={rep['embedding']})", ""]
    if not ld.get("reused") and ld.get("memory") == "full":
        lines += [f"Load (full memory bank): {ld['documents']:,} documents → {ld['sections']:,} sections and {ld['records']:,} memory records "
                  f"({', '.join(f'{k} {v:,}' for k, v in sorted(ld['records_by_type'].items(), key=lambda kv: -kv[1]))}); "
                  f"{ld['entities']:,} people and companies, {ld['projects']:,} projects; links: "
                  f"{', '.join(f'{k} {v:,}' for k, v in sorted(ld['links_by_kind'].items(), key=lambda kv: -kv[1]))}; "
                  f"{ld['near_duplicate_pairs']:,} near-duplicate document pairs, {ld['contradictions']:,} conflicting facts; "
                  f"{ld['load_seconds']} s ({ld['embed_seconds']} s embedding).", ""]
    elif not ld.get("reused"):
        lines += [f"Load: {ld['documents']:,} documents → {ld['sections']:,} sections, {ld['records']:,} document records, {ld['entities']:,} entity links; "
                  f"{ld['load_seconds']} s ({ld['embed_seconds']} s embedding, {ld['embed_texts_per_s']} texts/s).", ""]
    lines += ["| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, v in rep["arms"].items():
        o = v["overall"]
        lines.append(f"| {arm} | {o['recall@10']} | {o['recall@5']} | {o['mrr']} | {o['hit@1']} | {o['hit@10']} | {o['all_gold_found']} | {o['extras@10']} | "
                     f"{o['abstained_on_info_not_found']} | {o['false_abstentions']} | {o['p50_ms']} / {o['p95_ms']} |")
    first = next(iter(rep["arms"]))
    lines += ["", f"By category ({first}):", "", "| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for cat, c in rep["arms"][first]["by_category"].items():
        lines.append(f"| {cat} | {c['n']} | {c['recall@10']} | {c['mrr']} | {c['hit@1']} | {c['hit@10']} | {c['all_gold_found']} | {c['extras@10']} | {c['abstained']} | {c['p50_ms']} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True, help="path to the EnterpriseRAG-Bench checkout (with generated_data/sources and questions.jsonl)")
    ap.add_argument("--out", default="eval_out/enterprise")
    ap.add_argument("--docs", type=int, default=None, help="haystack size (every gold document plus a stratified sample); default: the whole corpus")
    ap.add_argument("--questions", type=int, default=None, help="only the first N questions (smoke tests)")
    ap.add_argument("--no-entities", action="store_true")
    ap.add_argument("--reuse-tenant", default=None, help="evaluate an already loaded tenant by name instead of loading")
    ap.add_argument("--arms", default=None, help="comma-separated arm names (default: all)")
    ap.add_argument("--batch", type=int, default=64, help="documents per load batch (256 is right for a GPU embedder)")
    ap.add_argument("--memory", choices=["full", "chunks"], default="full",
                    help="full: the full memory bank (summaries, tags, typed records, entities, projects, references, contradictions); chunks: sections only")
    ap.add_argument("--workers", type=int, default=None, help="document-building processes (default: CPUs - 1)")
    ap.add_argument("--assisted", action="store_true",
                    help="also compose answers with the configured model (CIE_LLM_PROVIDER / CIE_LLM_MODEL and its API key) on the default arm")
    a = ap.parse_args(argv)
    wanted = [x.strip() for x in a.arms.split(",") if x.strip()] if a.arms else list(ARMS)
    unknown = [x for x in wanted if x not in ARMS]
    if unknown or not wanted:
        raise SystemExit(f"unknown arm(s) {unknown}; choose from: {', '.join(ARMS)}")
    arms = {k: ARMS[k] for k in wanted}
    if a.assisted:
        arms[ASSISTED_ARM] = {"mode": "assisted"}
    return run(Path(a.root), Path(a.out), a.docs, arms=arms, entities=not a.no_entities, reuse_tenant=a.reuse_tenant, n_questions=a.questions,
               batch=a.batch, memory=a.memory, workers=a.workers)


if __name__ == "__main__":  # pragma: no cover
    main()
