"""Scale benchmark for the memory bank and retrieval only.

For each size N it creates a fresh tenant (company → 5 departments → 20
projects), bulk-loads N memory records, N/4 sections, N/20 documents and ~3N
sparse graph edges through binary COPY, recomputes tsvectors in SQL, rebuilds
the GIN and HNSW indexes the way a bulk load should, and then measures:

* end-to-end hybrid retrieval latency (p50/p95/max, cold and warm) for an admin
  at company scope and for an analyst confined to one department,
* vector-only and lexical-only latency,
* per-stage timings from the retrieval trace,
* hit@20: whether the record the question targets (known from generation) is
  in the packet,
* warm metadata lookups, table and index sizes, load and index-build times.

Embeddings: 4,000 template sentences are embedded with the real model; every
record gets its template's vector plus Gaussian noise (σ=0.08), renormalised.
Query vectors come from the real model. This keeps the vector distribution
clustered like real text while loading a million rows in minutes. Text is
built from supplier names, clause templates and a Zipfian vocabulary so term
frequencies are skewed like real corpora. No OCR or extraction runs.

Between sizes the previous tenant's rows are deleted so each measurement sees
exactly N rows.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb
from sqlalchemy import func, select, text

from cie.core.db import session_scope
from cie.core.models import (
    Document,
    MemoryRecord,
    Permission,
    Principal,
    PrincipalKind,
    ScopeKind,
    Section,
    Tenant,
)
from cie.core.settings import get_settings
from cie.governance.permissions import ensure_role, grant_role
from cie.memory.embeddings import get_embedding_provider
from cie.memory.scopes import create_scope
from cie.retrieval.pipeline import Retriever

SUPPLIER_A = ["Northwind", "Contoso", "Fabrikam", "Tailspin", "Woodgrove", "Adatum", "Litware", "Proseware", "Margie", "Alpine", "Coho", "Lucerne",
              "Wingtip", "Trey", "Humongous", "Southridge", "Graphic", "Blue", "Consolidated", "Fourth"]
SUPPLIER_B = ["Logistics", "Freight", "Robotics", "Analytics", "Facilities", "Cloud", "Systems", "Holdings", "Partners", "Industries",
              "Networks", "Labs", "Dynamics", "Foods", "Energy", "Medical", "Marine", "Aero", "Textiles", "Retail"]
SUFFIX = ["Ltd.", "Inc.", "GmbH", "LLC", "plc", "S.A.", "B.V.", "AG"]
DEPTS = ["Legal", "Finance", "Engineering", "Operations", "HR"]
VOCAB = ("services agreement supplier company party parties notice termination liability indemnity fee payment invoice budget approval board "
         "decision quarter delivery warehouse automation integration api requirement risk penalty schedule milestone audit compliance data "
         "processing renewal amendment clause exhibit confidential insurance warranty dispute arbitration governing law force majeure assignment "
         "subcontract escrow license support maintenance uptime incident breach remedy cure default interest currency tax withholding").split()


T0 = datetime(2025, 1, 15, tzinfo=UTC)


def zipf_words(rng: random.Random, n: int) -> str:
    return " ".join(VOCAB[min(len(VOCAB) - 1, int(rng.paretovariate(1.2)) - 1)] for _ in range(n))


def supplier_name(i: int) -> str:
    base = f"{SUPPLIER_A[i % 20]} {SUPPLIER_B[(i // 20) % 20]}"
    if i >= 400:
        base += f" {i // 400}"  # keeps names unique beyond 400 suppliers ("Northwind Logistics 3")
    return base + " " + SUFFIX[i % 8]


def short_name(sup: str) -> str:
    return sup.rsplit(" ", 1)[0]  # drop the legal suffix only


# record templates: (type, summary template, detail template, content builder, keywords)
def _templates(rng: random.Random, sup: str, short: str, doc_title: str) -> list[tuple[str, str, str, dict, list[str]]]:
    fee = 10_000 + 500 * rng.randint(0, 400)
    cap = fee * rng.randint(20, 60)
    notice = rng.choice([30, 45, 60, 90, 120, 180])
    pen = rng.choice([0.5, 0.75, 1.0, 1.25, 1.5, 2.0])
    months = rng.choice([12, 24, 36, 48, 60])
    officer = rng.choice(["Jane Whitfield", "Marcus Lindqvist", "Priya Raman", "John Smith", "Jane Smith", "Tomás Herrera", "Aiko Tanaka", "Omar Haddad"])
    return [
        ("contract_clause", "Clause 3: Fees", f"3.1 The Supplier shall be paid a monthly fee of USD {fee:,} for the Services. 3.2 The total fees under this Agreement shall not exceed ${cap:,}.", {"clause_number": "3", "title": "Fees"}, ["fees", "clause"]),
        ("metric", f"Fees 3.1 The Supplier shall be paid a monthly fee of USD {fee:,} for the Services.", f"3.1 The Supplier shall be paid a monthly fee of USD {fee:,} for the Services under the {short} agreement.", {"value": float(fee), "currency": "USD", "name": "fee"}, ["monthly", "fee", short.lower()]),
        ("metric", f"3.3 A late payment penalty of {pen}% per month applies to overdue amounts.", f"3.3 A late payment penalty of {pen}% per month applies to overdue amounts owed to {sup}.", {"value": pen, "unit": "%", "name": "penalty"}, ["penalty", "late", "payment"]),
        ("deadline", f"2.2 Either party may terminate this Agreement by giving no later than {notice} days written notice.", f"2.2 Either party may terminate this Agreement for convenience by giving no later than {notice} days written notice to {sup}.", {"duration_days": notice, "trigger": "no later than"}, ["termination", "notice", short.lower()]),
        ("requirement", f"2.1 The initial term of this Agreement is {months} months from the Effective Date.", f"2.1 The initial term of this Agreement with {sup} is {months} months from the Effective Date.", {"modal": "shall"}, ["term", "months"]),
        ("risk", "4.1 The Supplier's aggregate liability shall be limited to the fees paid in the twelve months preceding the claim.", f"4.1 The aggregate liability of {sup} shall be limited to the fees paid in the twelve months preceding the claim. {zipf_words(rng, 12)}.", {"marker": "liability"}, ["liability", "limited"]),
        ("decision", f"The board approved the {short} engagement on {rng.randint(1, 28)} {rng.choice(['January', 'March', 'June', 'September'])} 2025.", f"The board approved the {short} engagement and its budget; {zipf_words(rng, 14)}.", {"marker": "approved"}, ["board", "approved", short.lower()]),
        ("organization", sup, f"{sup} is a party to {doc_title}.", {"name": sup}, [short.lower(), "party"]),
        ("person", officer, f"Signed by {officer} (signatory) in {doc_title}. By: {officer}, Chief Operating Officer, Acme Robotics Inc.", {"name": officer, "role": "signatory"}, ["signed", "signatory"]),
        ("fact", f"{officer} signed {doc_title}", f"Signed by {officer} (signatory) in {doc_title}.", {"role": "signatory"}, ["signed", officer.split()[0].lower()]),
        ("open_question", f"Failover region for the {short} integration is TBD.", f"The failover region for the {short} warehouse integration is TBD; {zipf_words(rng, 10)}.", {"marker": "TBD"}, ["failover", "tbd"]),
        ("fact", f"{short} note: {zipf_words(rng, 6)}", f"{zipf_words(rng, 40)}.", {}, [short.lower()]),
    ]


def _q(rng: random.Random, n_docs: int) -> list[dict[str, Any]]:
    """60 questions with the generated ground truth (target document index + record type)."""
    out = []
    for _ in range(50):
        d = rng.randrange(n_docs)
        sup = supplier_name(d)
        short = short_name(sup)
        kind = rng.choice(["fee", "notice", "penalty", "signed", "liability", "term"])
        q = {"fee": f"What is the monthly fee in the {short} agreement?", "notice": f"What is the termination notice period under the {short} agreement?",
             "penalty": f"What late payment penalty applies in the {short} contract?", "signed": f"Who signed the {short} agreement for Acme Robotics?",
             "liability": f"How is liability limited in the {short} agreement?", "term": f"What is the initial term of the {short} agreement?"}[kind]
        rtype = {"fee": "metric", "notice": "deadline", "penalty": "metric", "signed": "fact", "liability": "risk", "term": "requirement"}[kind]
        out.append({"q": q, "doc": d, "type": rtype, "kind": kind})
    for _ in range(10):
        out.append({"q": rng.choice(["What is the CEO's favourite colour?", "How many employees does the supplier have?", "What is the credit rating of the counterparty?",
                                     "Which planet is the data centre on?"]), "doc": None, "type": None, "kind": "insufficient"})
    return out


def _load(conn: psycopg.Connection, tenant_id, scope_ids: list, n: int, embedder, rng: random.Random, seed: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    register_vector(conn)
    from psycopg.types.enum import EnumInfo, register_enum

    from cie.core.models import LinkKind, RecordType, VerificationStatus

    for tname, py in (("record_type", RecordType), ("verification_status", VerificationStatus), ("link_kind", LinkKind)):
        register_enum(EnumInfo.fetch(conn, tname), conn, py)
    from psycopg.types.string import StrBinaryDumperVarchar

    conn.adapters.register_dumper(str, StrBinaryDumperVarchar)  # keywords is varchar[]; binary arrays carry the element oid
    n_docs = max(1, n // 12)  # twelve records per document, no document written twice
    n_secs = max(1, n // 4)
    # template vectors from the real model
    tpl_texts = []
    tpl_rng = random.Random(seed + 1)
    for i in range(400):
        sup = supplier_name(i)
        short = short_name(sup)
        for t, summ, det, _, _ in _templates(tpl_rng, sup, short, f"{short} MSA"):
            tpl_texts.append(f"{t}: {summ}\n{det[:300]}")
    t1 = time.perf_counter()
    tpl_vecs = np.array(embedder.embed(tpl_texts), dtype=np.float32)  # 400 suppliers × 12 templates = 4800
    embed_s = time.perf_counter() - t1
    np_rng = np.random.default_rng(seed)
    dim = tpl_vecs.shape[1]

    def noisy(base_idx: int) -> np.ndarray:
        v = tpl_vecs[base_idx] + np_rng.normal(0, 0.08, dim).astype(np.float32)
        return v / np.linalg.norm(v)

    doc_ids = [uuid.uuid4() for _ in range(n_docs)]
    blob_ids = [uuid.uuid4() for _ in range(n_docs)]
    doc_scope = [scope_ids[i % len(scope_ids)] for i in range(n_docs)]
    with conn.cursor() as cur:
        cur.execute("SET LOCAL synchronous_commit = off")
        with cur.copy("COPY blobs (id, tenant_id, sha256, size_bytes, media_type, storage_uri, encrypted, created_at) FROM STDIN WITH (FORMAT BINARY)") as cp:
            cp.set_types(["uuid", "uuid", "text", "int8", "text", "text", "bool", "timestamptz"])
            for i in range(n_docs):
                sha = hashlib.sha256(f"{tenant_id}-{i}".encode()).hexdigest()
                cp.write_row((blob_ids[i], tenant_id, sha, 180_000, "application/pdf", f"scale://{sha}", False, T0))
        with cur.copy("COPY documents (id, tenant_id, blob_id, family_id, version, title, original_filename, source, scope_id, sensitivity, acl, "
                      "retention_policy, legal_hold, ingested_at, extra, status, injection_flags, pii_flags, doc_type, file_created_at) FROM STDIN WITH (FORMAT BINARY)") as cp:
            cp.set_types(["uuid", "uuid", "uuid", "uuid", "int4", "text", "text", "text", "uuid", "int4", "jsonb", "text", "bool", "timestamptz",
                          "jsonb", "text", "jsonb", "jsonb", "text", "timestamptz"])
            for i in range(n_docs):
                sup = supplier_name(i)
                short = short_name(sup)
                cp.write_row((doc_ids[i], tenant_id, blob_ids[i], uuid.uuid4(), 1, f"{short} Master Services Agreement", f"{short.replace(' ', '_')}_MSA.pdf",
                              "scale", doc_scope[i], 1, Jsonb({}), "default", False, T0, Jsonb({}), "indexed", Jsonb([]), Jsonb([]),
                              "contract", T0))
        # records
        rec_ids: list[uuid.UUID] = []
        rec_doc: list[int] = []
        rec_org: list[uuid.UUID | None] = []  # the document's organisation record each record mentions (None for the organisation itself)
        cols = ("id, tenant_id, scope_id, type, summary, content, detail, source_document_id, source_locations, event_time, valid_from, valid_to, recorded_at, "
                "producing_agent, confidence, verification, sensitivity, acl, version, family_id, entity_ids, keywords, glyph, embedding, content_sha256")
        with cur.copy(f"COPY memory_records ({cols}) FROM STDIN WITH (FORMAT BINARY)") as cp:
            cp.set_types(["uuid", "uuid", "uuid", "record_type", "text", "jsonb", "text", "uuid", "jsonb", "timestamptz", "timestamptz", "timestamptz", "timestamptz",
                          "text", "float8", "verification_status", "int4", "jsonb", "int4", "uuid", "jsonb", "varchar[]", "jsonb", "vector", "text"])
            i = 0
            d = 0
            while i < n:
                sup = supplier_name(d)
                short = short_name(sup)
                tpls = _templates(rng, sup, short, f"{short} Master Services Agreement")
                org_idx = next(j for j, tpl in enumerate(tpls) if tpl[0] == "organization")
                org_rid = uuid.uuid4() if i + org_idx < n else None  # the organisation record exists only if the document is complete that far
                for j, (t, summ, det, content, kws) in enumerate(tpls):
                    if i >= n:
                        break
                    rid = org_rid if (j == org_idx and org_rid is not None) else uuid.uuid4()
                    rec_ids.append(rid)
                    rec_doc.append(d)
                    rec_org.append(org_rid if j != org_idx else None)
                    base_idx = ((d % 400) * 12 + j) % len(tpl_vecs)
                    glyph = {"v": 1, "id": str(rid), "type": t, "what": summ[:120], "confidence": 0.7, "status": "current"}
                    ents = [str(org_rid)] if (org_rid is not None and j != org_idx) else []
                    cp.write_row((rid, tenant_id, doc_scope[d], RecordType(t), summ[:400], Jsonb(content), det[:2000], doc_ids[d],
                                  Jsonb([{"page_no": 1 + j % 6, "bbox": [72.0, 100.0 + 20 * j, 540.0, 118.0 + 20 * j], "quote": summ[:120]}]),
                                  T0, T0, None, T0, "scale_generator", 0.7, VerificationStatus.unverified,
                                  1, Jsonb({}), 1, uuid.uuid4(), Jsonb(ents), kws, Jsonb(glyph), noisy(base_idx),
                                  hashlib.sha256(f"{rid}".encode()).hexdigest()))
                    i += 1
                d = (d + 1) % n_docs
        # sections (one synthetic extraction row satisfies the foreign key)
        ext_id = uuid.uuid4()
        cur.execute("INSERT INTO extractions (id, tenant_id, document_id, extractor, extractor_version, status, page_count, pages_done, completeness, stats, created_at) "
                    "VALUES (%s, %s, %s, 'scale_generator', '1', 'done', 6, 6, '{}', '{}', %s)", (ext_id, tenant_id, doc_ids[0], T0))
        with cur.copy("COPY sections (id, tenant_id, document_id, extraction_id, scope_id, order_index, title, level, page_start, page_end, text, text_sha256, "
                      "token_estimate, spans, embedding, sensitivity) FROM STDIN WITH (FORMAT BINARY)") as cp:
            cp.set_types(["uuid", "uuid", "uuid", "uuid", "uuid", "int4", "text", "int4", "int4", "int4", "text", "text", "int4", "jsonb", "vector", "int4"])
            for k in range(n_secs):
                d = k % n_docs
                sup = supplier_name(d)
                short = short_name(sup)
                title = rng.choice(["1. Definitions", "2. Term and Termination", "3. Fees", "4. Liability", "5. Data Processing", "Signatures"])
                body = f"{title} {zipf_words(rng, 60)} {sup} {zipf_words(rng, 40)}."
                cp.write_row((uuid.uuid4(), tenant_id, doc_ids[d], ext_id, doc_scope[d], k % 6, title, 1, 1 + k % 6, 1 + k % 6, body,
                              hashlib.sha256(body.encode()).hexdigest(), 90, Jsonb([{"page_no": 1 + k % 6, "block_ids": [], "bbox": [72, 72, 540, 700]}]),
                              noisy(rng.randrange(len(tpl_vecs))), 1))
        # sparse graph: part_of chain within a document (consecutive records) + a few relates_to + rare cross-document depends_on
        with cur.copy("COPY record_links (id, tenant_id, src_id, dst_id, kind, weight, evidence, created_at) FROM STDIN WITH (FORMAT BINARY)") as cp:
            cp.set_types(["uuid", "uuid", "uuid", "uuid", "link_kind", "float8", "jsonb", "timestamptz"])
            for idx in range(1, len(rec_ids)):
                if rec_doc[idx] == rec_doc[idx - 1]:
                    cp.write_row((uuid.uuid4(), tenant_id, rec_ids[idx], rec_ids[idx - 1], LinkKind.relates_to, 0.5, Jsonb({}), T0))
                if rec_org[idx] is not None:  # every record of a document mentions the document's organisation
                    cp.write_row((uuid.uuid4(), tenant_id, rec_ids[idx], rec_org[idx], LinkKind.mentions, 1.0, Jsonb({}), T0))
                if idx % 3 == 0 and idx >= 12 and rec_doc[idx] == rec_doc[idx - 12 + (idx % 12)]:
                    cp.write_row((uuid.uuid4(), tenant_id, rec_ids[idx], rec_ids[idx - (idx % 12)], LinkKind.part_of, 1.0, Jsonb({}), T0))
                if idx % 50 == 0:
                    cp.write_row((uuid.uuid4(), tenant_id, rec_ids[idx], rec_ids[rng.randrange(idx)], LinkKind.depends_on, 1.0, Jsonb({}), T0))
    conn.commit()
    load_s = time.perf_counter() - t0
    t2 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute("UPDATE memory_records SET tsv = setweight(to_tsvector('english', summary), 'A') || setweight(to_tsvector('english', left(detail, 20000)), 'B') "
                    "WHERE tenant_id = %s AND tsv IS NULL", (tenant_id,))
        cur.execute("UPDATE sections SET tsv = setweight(to_tsvector('english', coalesce(title, '')), 'A') || setweight(to_tsvector('english', text), 'B') "
                    "WHERE tenant_id = %s AND tsv IS NULL", (tenant_id,))
    conn.commit()
    tsv_s = time.perf_counter() - t2
    return {"n_records": n, "n_sections": n_secs, "n_documents": n_docs, "n_edges_approx": int(len(rec_ids) * 1.35), "copy_seconds": round(load_s, 1),
            "template_embed_seconds": round(embed_s, 1), "tsvector_seconds": round(tsv_s, 1), "doc_ids": doc_ids}


INDEXES = {
    "ix_records_embedding_hnsw": "CREATE INDEX ix_records_embedding_hnsw ON memory_records USING hnsw (embedding vector_cosine_ops)",
    "ix_sections_embedding_hnsw": "CREATE INDEX ix_sections_embedding_hnsw ON sections USING hnsw (embedding vector_cosine_ops)",
    "ix_records_tsv": "CREATE INDEX ix_records_tsv ON memory_records USING gin (tsv)",
    "ix_sections_tsv": "CREATE INDEX ix_sections_tsv ON sections USING gin (tsv)",
    "ix_records_keywords": "CREATE INDEX ix_records_keywords ON memory_records USING gin (keywords)",
    "ix_records_summary_trgm": "CREATE INDEX ix_records_summary_trgm ON memory_records USING gin (summary gin_trgm_ops)",
    "ix_records_entity_ids": "CREATE INDEX ix_records_entity_ids ON memory_records USING gin (entity_ids jsonb_path_ops)",
    "ix_sections_trgm": "CREATE INDEX ix_sections_trgm ON sections USING gin (title gin_trgm_ops)",
}
HALFVEC_INDEXES = {
    "ix_records_embedding_hnsw": "CREATE INDEX ix_records_embedding_hnsw ON memory_records USING hnsw ((embedding::halfvec(384)) halfvec_cosine_ops)",
    "ix_sections_embedding_hnsw": "CREATE INDEX ix_sections_embedding_hnsw ON sections USING hnsw ((embedding::halfvec(384)) halfvec_cosine_ops)",
}


def pgvector_version(conn: psycopg.Connection) -> tuple[int, int]:
    row = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    parts = [int(x) for x in (row[0] if row else "0.0").split(".")[:2]]
    return parts[0], parts[1]


def index_ddl(conn: psycopg.Connection) -> dict[str, str]:
    """The indexes the migration would build on this server: half-precision HNSW
    (half the size, faster build) from pgvector 0.7 on, float32 HNSW before."""
    ddl = dict(INDEXES)
    if pgvector_version(conn) >= (0, 7):
        ddl.update(HALFVEC_INDEXES)
    return ddl


def drop_indexes(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for name in INDEXES:
            cur.execute(f"DROP INDEX IF EXISTS {name}")
    conn.commit()


def ensure_indexes(conn: psycopg.Connection) -> dict[str, float]:
    """Build any of the shared indexes that are missing (a load that died after dropping them); returns build times."""
    present = {r[0] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")}
    missing = {n: d for n, d in index_ddl(conn).items() if n not in present}
    if not missing:
        return {}
    return build_indexes(conn, only=missing)


def build_indexes(conn: psycopg.Connection, only: dict[str, str] | None = None) -> dict[str, float]:
    import os

    times = {}
    with conn.cursor() as cur:
        # large machines (a Colab A100 VM) build much faster with more memory and workers; defaults suit a 4-core box
        cur.execute(f"SET maintenance_work_mem = '{os.environ.get('CIE_INDEX_BUILD_MEM', '4GB')}'")
        cur.execute(f"SET max_parallel_maintenance_workers = {int(os.environ.get('CIE_INDEX_BUILD_WORKERS', '3'))}")
        for name, ddl in (only or index_ddl(conn)).items():
            t = time.perf_counter()
            cur.execute(ddl.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
            conn.commit()
            times[name] = round(time.perf_counter() - t, 1)
        cur.execute("ANALYZE memory_records")
        cur.execute("ANALYZE sections")
        cur.execute("ANALYZE documents")
        conn.commit()
    return times


def _p(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1)))], 1)


def measure(s, principal: Principal, scope_id, questions: list[dict], doc_ids: list, retriever: Retriever, label: str, arms: dict,
            visible=lambda d: True) -> dict[str, Any]:
    out: dict[str, Any] = {}
    doc_str = [str(d) for d in doc_ids]
    for arm, cfg in arms.items():
        lat_cold, lat_warm, hits, n_hit_q, stage = [], [], 0, 0, {}
        timeouts = 0
        topo: dict[str, list] = {}
        rr = []
        for rep in range(3):
            for q in questions:
                try:
                    s.execute(text("SET LOCAL statement_timeout = '60s'"))
                    t = time.perf_counter()
                    res = retriever.retrieve(q["q"], principal, scope_id, **cfg)
                    ms = (time.perf_counter() - t) * 1000
                except Exception as e:  # noqa: BLE001 - a timeout is a result here
                    s.rollback()
                    timeouts += 1
                    ms = 60_000.0
                    res = None
                    _ = e
                (lat_cold if rep == 0 else lat_warm).append(ms)
                if res is not None and rep == 0:
                    for k, v in res.trace["timings_ms"].items():
                        stage.setdefault(k, []).append(v)
                    for tk, tv in (res.trace.get("topology") or {}).items():
                        if tk in ("max_dim", "betti1", "nodes"):
                            topo.setdefault(tk, []).append(tv)
                    if q["doc"] is not None and visible(q["doc"]):
                        n_hit_q += 1
                        target = doc_str[q["doc"]]
                        pos = next((i for i, it in enumerate(res.packet.items) if it.get("document_id") == target and it.get("type") == q["type"]), None)
                        if pos is not None and pos < 20:
                            hits += 1
                        rr.append(1.0 / (pos + 1) if pos is not None else 0.0)
                s.rollback()  # do not keep benchmark packets/audit rows
        out[arm] = {"cold_p50_ms": _p(lat_cold, 0.5), "cold_p95_ms": _p(lat_cold, 0.95), "warm_p50_ms": _p(lat_warm, 0.5), "warm_p95_ms": _p(lat_warm, 0.95),
                    "warm_max_ms": _p(lat_warm, 1.0), "hit_at_20": round(hits / n_hit_q, 3) if n_hit_q else None, "timeouts": timeouts,
                    "mrr": round(sum(rr) / len(rr), 3) if rr else None,
                    "stage_ms_p50": {k: _p(v, 0.5) for k, v in stage.items()},
                    "topology_p50": {k: _p(v, 0.5) for k, v in topo.items()}}
    return out


def measure_organisation(s, tenant_id, admin: Principal, company_id, dept_id, doc_ids: list, n_names: int = 50, seed: int = 5) -> dict[str, Any]:
    """Can the bank organise at this size? Times, against the loaded tenant:
    * entity resolution of a differently spelled supplier name (index-served prefilter + fuzzy scoring),
    * the entity profile of a supplier (everything the bank holds about it, grouped and current),
    * the digest of the whole company scope and of one department (counts, top entities, newest documents, conflicts)."""
    from cie.core.models import RecordType, Scope
    from cie.governance.permissions import visible_scopes
    from cie.memory import organise
    from cie.memory.entities import resolve

    vis = visible_scopes(s, admin)
    rng = random.Random(seed + 11)
    picks = [rng.randrange(len(doc_ids)) for _ in range(n_names)]
    res_ms, matched = [], 0
    for d in picks:
        sup = supplier_name(d)
        spelled = short_name(sup) + " " + {"Ltd": "Limited", "Inc": "Incorporated", "GmbH": "Gmbh", "LLC": "L.L.C.", "AG": "AG.", "SA": "S.A.",
                                            "BV": "B.V.", "Corp": "Corporation"}.get(sup.rsplit(" ", 1)[1], sup.rsplit(" ", 1)[1])
        t = time.perf_counter()
        ent, status = resolve(s, tenant_id, company_id, spelled, RecordType.organization)
        res_ms.append((time.perf_counter() - t) * 1000)
        matched += int(status == "matched" and ent is not None and ent.source_document_id == doc_ids[d])
    prof_ms, prof_records = [], []
    for d in picks:
        org = s.scalar(select(MemoryRecord).where(MemoryRecord.source_document_id == doc_ids[d], MemoryRecord.type == RecordType.organization))
        t = time.perf_counter()
        prof = organise.entity_profile(s, tenant_id, vis, org)
        prof_ms.append((time.perf_counter() - t) * 1000)
        prof_records.append(prof["record_count"])
    digest = {}
    for label, sid in (("company", company_id), ("department", dept_id)):
        scope = s.get(Scope, sid)
        t = time.perf_counter()
        dg = organise.scope_digest(s, tenant_id, vis, scope)
        digest[label] = {"ms": round((time.perf_counter() - t) * 1000, 1), "records": dg["records_total"], "documents": dg["documents"],
                         "top_entity_mentions": dg["top_entities"][0]["mentions"] if dg["top_entities"] else 0}
    s.rollback()
    return {"resolve_ms": {"p50": _p(res_ms, 0.5), "p95": _p(res_ms, 0.95)}, "resolved_correctly": round(matched / n_names, 3),
            "profile_ms": {"p50": _p(prof_ms, 0.5), "p95": _p(prof_ms, 0.95)}, "profile_records_p50": _p(prof_records, 0.5), "digest": digest}


def run(out: Path, sizes: list[int], seed: int = 5) -> dict[str, Any]:
    settings = get_settings()
    embedder = get_embedding_provider(settings)
    report: dict[str, Any] = {"embedding": getattr(embedder, "name", "?"), "sizes": {}, "postgres": {}}
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SHOW shared_buffers")
        report["postgres"]["shared_buffers"] = cur.fetchone()[0]
        cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
        report["postgres"]["pgvector"] = cur.fetchone()[0]
    previous_tenant = None
    for n in sizes:
        rng = random.Random(seed)
        size_rep: dict[str, Any] = {}
        with session_scope() as s:
            if previous_tenant is not None:
                t = time.perf_counter()
                s.execute(text("DELETE FROM blocks WHERE document_id IN (SELECT id FROM documents WHERE tenant_id = :t)"), {"t": previous_tenant})
                s.execute(text("DELETE FROM corrections WHERE document_id IN (SELECT id FROM documents WHERE tenant_id = :t)"), {"t": previous_tenant})
                s.execute(text("DELETE FROM pages WHERE document_id IN (SELECT id FROM documents WHERE tenant_id = :t)"), {"t": previous_tenant})
                for tbl in ("audit_log", "metrics", "answers", "evidence_packets", "agent_messages", "ledger_entries", "task_dependencies_x",
                            "tasks", "projects", "agent_scorecards", "agents", "approvals", "deletion_requests", "record_links", "memory_records",
                            "sections", "extractions", "documents", "blobs", "grants", "roles", "principals", "scopes"):
                    if tbl == "task_dependencies_x":
                        s.execute(text("DELETE FROM task_dependencies WHERE task_id IN (SELECT id FROM tasks WHERE tenant_id = :t)"), {"t": previous_tenant})
                        continue
                    s.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :t"), {"t": previous_tenant})
                s.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": previous_tenant})
                s.commit()
                size_rep["delete_previous_seconds"] = round(time.perf_counter() - t, 1)
            tenant = Tenant(name=f"scale-{n}-{uuid.uuid4().hex[:6]}")
            s.add(tenant)
            s.flush()
            company = create_scope(s, tenant.id, ScopeKind.company, "ScaleCo")
            depts = [create_scope(s, tenant.id, ScopeKind.department, d_, company) for d_ in DEPTS]
            projects = [create_scope(s, tenant.id, ScopeKind.project, f"Project {i}", depts[i % 5]) for i in range(20)]
            admin = Principal(tenant_id=tenant.id, kind=PrincipalKind.user, name="admin")
            analyst = Principal(tenant_id=tenant.id, kind=PrincipalKind.user, name="analyst")
            s.add_all([admin, analyst])
            s.flush()
            grant_role(s, tenant_id=tenant.id, principal=admin, role=ensure_role(s, tenant.id, "admin", Permission.admin, 4), scope=company)
            grant_role(s, tenant_id=tenant.id, principal=analyst, role=ensure_role(s, tenant.id, "reader", Permission.read, 2), scope=depts[0])
            s.commit()
            tenant_id, company_id, dept0_id = tenant.id, company.id, depts[0].id
            scope_ids = [p.id for p in projects]
        with psycopg.connect(url) as conn:
            conn.execute("SET maintenance_work_mem = '4GB'")
            drop_indexes(conn)
            size_rep["load"] = _load(conn, tenant_id, scope_ids, n, embedder, rng, seed)
            doc_ids = size_rep["load"].pop("doc_ids")
            t = time.perf_counter()
            size_rep["index_build_seconds"] = build_indexes(conn)
            size_rep["index_build_total_seconds"] = round(time.perf_counter() - t, 1)
            with conn.cursor() as cur:
                sizes_sql = {}
                for tbl in ("memory_records", "sections", "record_links", "documents"):
                    cur.execute(f"SELECT pg_total_relation_size('{tbl}'), pg_relation_size('{tbl}')")
                    tot, heap = cur.fetchone()
                    sizes_sql[tbl] = {"total_bytes": int(tot), "heap_bytes": int(heap), "index_bytes": int(tot) - int(heap)}
                cur.execute("SELECT pg_relation_size('ix_records_embedding_hnsw'), pg_relation_size('ix_records_tsv')")
                hnsw, gin = cur.fetchone()
                sizes_sql["ix_records_embedding_hnsw_bytes"] = int(hnsw)
                sizes_sql["ix_records_tsv_bytes"] = int(gin)
                sizes_sql["hnsw_kind"] = "halfvec" if pgvector_version(conn) >= (0, 7) else "vector"
            size_rep["storage"] = sizes_sql
        questions = _q(random.Random(seed + 7), size_rep["load"]["n_documents"])
        with session_scope() as s:
            admin = s.scalar(select(Principal).where(Principal.tenant_id == tenant_id, Principal.name == "admin"))
            analyst = s.scalar(select(Principal).where(Principal.tenant_id == tenant_id, Principal.name == "analyst"))
            retriever = Retriever(s, settings, embedder=embedder)
            arms = {"hybrid+graph(bounded)": {}, "hybrid(no graph)": {"use_graph": False}, "vector-only": {"use_lexical": False, "use_exact": False, "use_graph": False},
                    "lexical-only": {"use_vector": False, "use_exact": False, "use_graph": False},
                    "hybrid+cliques(topological)": {"graph_mode": "cliques"}, "hybrid+cliques+bonus": {"graph_mode": "cliques+bonus"}}
            size_rep["admin@company"] = measure(s, admin, company_id, questions, doc_ids, retriever, "admin", arms)
            size_rep["analyst@department(20%)"] = measure(s, analyst, dept0_id, questions, doc_ids, retriever, "analyst",
                                                          {"hybrid+graph(bounded)": {}, "vector-only": arms["vector-only"]}, visible=lambda d: d % 5 == 0)
            # warm metadata lookups
            ids = list(s.scalars(select(MemoryRecord.id).where(MemoryRecord.tenant_id == tenant_id).limit(500)))
            lat = []
            for i in range(300):
                t = time.perf_counter()
                s.get(MemoryRecord, ids[i % len(ids)])
                s.execute(select(Document.id, Document.title).where(Document.id == doc_ids[i % len(doc_ids)])).first()
                lat.append((time.perf_counter() - t) * 1000)
            size_rep["warm_metadata_lookup_ms"] = {"p50": _p(lat, 0.5), "p95": _p(lat, 0.95)}
            size_rep["counts"] = {"records": s.scalar(select(func.count(MemoryRecord.id)).where(MemoryRecord.tenant_id == tenant_id)),
                                  "sections": s.scalar(select(func.count(Section.id)).where(Section.tenant_id == tenant_id))}
            s.rollback()
            size_rep["organisation"] = measure_organisation(s, tenant_id, admin, company_id, dept0_id, doc_ids, seed=seed)
        report["sizes"][str(n)] = size_rep
        previous_tenant = tenant_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "bench_scale.json").write_text(json.dumps(report, indent=2, default=str))
        print(to_markdown(report), flush=True)
    (out / "bench_scale.md").write_text(to_markdown(report))
    return report


def remeasure(out: Path, tenant_prefix: str = "scale-1000000-", label: str = "1000000 (after fixes)", seed: int = 5) -> dict:
    """Re-run the measurement phase against an existing scale tenant (no reload)."""
    settings = get_settings()
    embedder = get_embedding_provider(settings)
    rep_path = out / "bench_scale.json"
    report = json.loads(rep_path.read_text()) if rep_path.exists() else {"embedding": getattr(embedder, "name", "?"), "sizes": {}, "postgres": {}}
    with session_scope() as s:
        tenant = s.scalars(select(Tenant).where(Tenant.name.like(tenant_prefix + "%")).order_by(Tenant.created_at.desc())).first()
        if tenant is None:
            raise SystemExit(f"no tenant matching {tenant_prefix}")
        from cie.core.models import Scope

        company = s.scalar(select(Scope).where(Scope.tenant_id == tenant.id, Scope.parent_id.is_(None)))
        dept0 = s.scalar(select(Scope).where(Scope.tenant_id == tenant.id, Scope.name == DEPTS[0]))
        admin = s.scalar(select(Principal).where(Principal.tenant_id == tenant.id, Principal.name == "admin"))
        analyst = s.scalar(select(Principal).where(Principal.tenant_id == tenant.id, Principal.name == "analyst"))
        docs = list(s.scalars(select(Document).where(Document.tenant_id == tenant.id)))
        by_title = {d.title: d.id for d in docs}
        doc_ids = [by_title.get(f"{short_name(supplier_name(i))} Master Services Agreement") for i in range(len(docs))]
        questions = _q(random.Random(seed + 7), len(docs))
        retriever = Retriever(s, settings, embedder=embedder)
        arms = {"hybrid+graph(bounded)": {}, "hybrid(no graph)": {"use_graph": False}, "vector-only": {"use_lexical": False, "use_exact": False, "use_graph": False},
                "lexical-only": {"use_vector": False, "use_exact": False, "use_graph": False},
                "hybrid+cliques(topological)": {"graph_mode": "cliques"}, "hybrid+cliques+bonus": {"graph_mode": "cliques+bonus"}}
        size_rep = {"load": report["sizes"].get(tenant_prefix.split("-")[1], {}).get("load", {"n_sections": "?"}), "storage": report["sizes"].get(tenant_prefix.split("-")[1], {}).get("storage", {}),
                    "index_build_seconds": {}, "index_build_total_seconds": "-"}
        size_rep["admin@company"] = measure(s, admin, company.id, questions, doc_ids, retriever, "admin", arms)
        size_rep["analyst@department(20%)"] = measure(s, analyst, dept0.id, questions, doc_ids, retriever, "analyst",
                                                      {"hybrid+graph(bounded)": {}, "vector-only": arms["vector-only"]}, visible=lambda d: d % 5 == 0)
        lat = []
        ids = list(s.scalars(select(MemoryRecord.id).where(MemoryRecord.tenant_id == tenant.id).limit(500)))
        for i in range(300):
            t = time.perf_counter()
            s.get(MemoryRecord, ids[i % len(ids)])
            lat.append((time.perf_counter() - t) * 1000)
        size_rep["warm_metadata_lookup_ms"] = {"p50": _p(lat, 0.5), "p95": _p(lat, 0.95)}
        s.rollback()
        size_rep["organisation"] = measure_organisation(s, tenant.id, admin, company.id, dept0.id, doc_ids, seed=seed)
    report["sizes"][label] = size_rep
    rep_path.write_text(json.dumps(report, indent=2, default=str))
    md = to_markdown(report)
    (out / "bench_scale.md").write_text(md)
    print(md)
    return report


def to_markdown(rep: dict) -> str:
    lines = [f"### Scale benchmark: memory bank and retrieval (embeddings={rep['embedding']}, pgvector {rep['postgres'].get('pgvector')}, "
             f"shared_buffers {rep['postgres'].get('shared_buffers')})", "",
             "| records | sections | load s | tsvector s | HNSW build s (records) | all indexes s | records table+idx | HNSW idx | GIN tsv idx |", "|---|---|---|---|---|---|---|---|---|"]
    for n, r in rep["sizes"].items():
        if not r.get("index_build_seconds"):
            continue  # re-measurement rows have no load/build phase
        st = r["storage"]
        lines.append(f"| {n} | {r['load']['n_sections']:,} | {r['load']['copy_seconds']} | {r['load']['tsvector_seconds']} | "
                     f"{r['index_build_seconds'].get('ix_records_embedding_hnsw')} | {r['index_build_total_seconds']} | "
                     f"{st['memory_records']['total_bytes'] / 1e9:.2f} GB | {st['ix_records_embedding_hnsw_bytes'] / 1e6:.0f} MB ({st.get('hnsw_kind', 'vector')}) | "
                     f"{st['ix_records_tsv_bytes'] / 1e6:.0f} MB |")
    lines += ["", "| records | principal | arm | cold p50 | cold p95 | warm p50 | warm p95 | warm max | hit@20 | MRR | timeouts | topology (p50: nodes / max dim / cavities) |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in rep["sizes"].items():
        for who in ("admin@company", "analyst@department(20%)"):
            for arm, v in r[who].items():
                tp = v.get("topology_p50") or {}
                tps = f"{tp.get('nodes')} / {tp.get('max_dim')} / {tp.get('betti1')}" if tp else "-"
                lines.append(f"| {n} | {who} | {arm} | {v['cold_p50_ms']} | {v['cold_p95_ms']} | {v['warm_p50_ms']} | {v['warm_p95_ms']} | {v['warm_max_ms']} | "
                             f"{v['hit_at_20']} | {v.get('mrr', '-')} | {v['timeouts']} | {tps} |")
    lines += ["", "| records | stage (admin, hybrid, cold p50 ms) |", "|---|---|"]
    for n, r in rep["sizes"].items():
        st = r["admin@company"]["hybrid+graph(bounded)"]["stage_ms_p50"]
        lines.append(f"| {n} | " + ", ".join(f"{k}={v}" for k, v in st.items()) + f"; metadata lookup p95 {r['warm_metadata_lookup_ms']['p95']} ms |")
    if any("organisation" in r for r in rep["sizes"].values()):
        lines += ["", "| records | resolve name p50 / p95 ms | resolved to the right supplier | entity profile p50 / p95 ms | profile records (p50) | "
                  "company digest ms (records) | department digest ms (records) |", "|---|---|---|---|---|---|---|"]
        for n, r in rep["sizes"].items():
            o = r.get("organisation")
            if not o:
                continue
            dg = o["digest"]
            lines.append(f"| {n} | {o['resolve_ms']['p50']} / {o['resolve_ms']['p95']} | {o['resolved_correctly']} | {o['profile_ms']['p50']} / {o['profile_ms']['p95']} | "
                         f"{o['profile_records_p50']} | {dg['company']['ms']} ({dg['company']['records']:,}) | {dg['department']['ms']} ({dg['department']['records']:,}) |")
    return "\n".join(lines)


def main(out: Path, sizes: list[int] | None = None) -> dict:
    return run(out, sizes or [10_000, 100_000, 1_000_000])


if __name__ == "__main__":  # pragma: no cover
    import sys

    argv = sys.argv[1:]
    if "--remeasure" in argv:
        # re-run only the measurement phase against tenants an earlier run loaded (no reload, no index build)
        argv.remove("--remeasure")
        for n in [int(x) for x in argv] or [1_000_000]:
            remeasure(Path("eval_out/scale"), tenant_prefix=f"scale-{n}-", label=f"{n} (re-measured)")
    else:
        main(Path("eval_out/scale"), [int(x) for x in argv] or None)
