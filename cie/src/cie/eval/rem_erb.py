"""REM arms on EnterpriseRAG-Bench (document retrieval and cross-document questions).

The REM graph is built from a tenant that ``cie.eval.bench_enterprise`` already loaded (documents, sections,
extracted records, record links), using only relationships that mean what the business kinds mean:

* passage (section) ``derived_from`` document                         explicit (the extractor's own pointer)
* extracted record ``derived_from`` its document                      rule-derived (deterministic extractor)
* a document referenced by another ``supports`` the referencing one   rule-derived (link kind ``references``)
* document ``depends_on`` document, fact ``contradicts`` fact         rule-derived (link kinds of the same name)
* a document's project (link ``part_of`` project)                     membership, not an edge
* near-duplicate documents share one original source (root_sources), so they cannot corroborate each other.

Mentions of people and organisations and ``relates_to`` links are not business relationships and are left out.

Every arm starts from the same hits: the engine's hybrid search (exact, keyword, vector; its own graph expansion
off) mapped to REM records. Arms then pack evidence within the same token budget; documents are ranked by the
first evidence item that cites them.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

RECORD_TYPES = {"task": "task", "decision": "decision", "risk": "risk", "requirement": "requirement", "fact": "fact",
                "metric": "fact", "deadline": "fact", "result": "fact", "open_question": "claim", "project": "project"}
BUDGETS = {"2k": {"max_tokens": 2000, "max_visited": 150, "max_db_calls": 60, "max_ms": 15000},
           "6k": {"max_tokens": 6000, "max_visited": 400, "max_db_calls": 120, "max_ms": 30000}}
ARMS = {"A": "search", "B": "traversal", "C": "rem", "D": "rem+routing"}


def build_graph(session, tenant_id: uuid.UUID, log=print) -> dict[str, Any]:
    """Bulk-build the REM graph for a loaded ERB tenant in one change (one sequence number). Idempotent: an existing
    build is reused."""
    from cie.rem.models import RemNode
    from cie.rem.store import GraphWriter

    have = session.scalar(select(text("count(*)")).select_from(RemNode).where(RemNode.tenant_id == tenant_id))
    if have:
        return {"reused": True, "nodes": int(have)}
    t0 = time.perf_counter()
    w = GraphWriter(session, tenant_id)
    seq = w.begin()
    p = {"t": tenant_id, "seq": seq}
    x = session.execute
    # documents
    x(text("""INSERT INTO rem_nodes (id, tenant_id, type, key, created_seq)
              SELECT gen_random_uuid(), :t, 'document', d.extra->>'dsid', :seq FROM documents d WHERE d.tenant_id = :t"""), p)
    x(text("""INSERT INTO rem_node_versions (id, tenant_id, node_id, version, sys_from, name, summary, attrs, project_ids, department_ids,
                  scope_id, sensitivity, acl, source_pointers, root_sources, verification, authoritative, recorded_at, embedding, tsv)
              SELECT gen_random_uuid(), :t, n.id, 1, :seq, coalesce(d.title, d.original_filename), coalesce(d.extra->>'summary', ''),
                     jsonb_build_object('source_system', coalesce(d.extra->>'source', 'document'), 'tokens',
                                        (SELECT coalesce(sum(s.token_estimate), 0) FROM sections s WHERE s.document_id = d.id)),
                     '{}', '{}', d.scope_id, d.sensitivity, coalesce(d.acl, '{}'::jsonb),
                     jsonb_build_array(jsonb_build_object('document_id', d.id::text, 'filename', d.original_filename)),
                     ARRAY['doc:' || (d.extra->>'dsid')], 'unverified', true, now(),
                     (SELECT r.embedding FROM memory_records r WHERE r.source_document_id = d.id AND r.type = 'document' LIMIT 1),
                     to_tsvector('english', coalesce(d.title, '') || ' ' || coalesce(d.extra->>'summary', ''))
              FROM documents d JOIN rem_nodes n ON n.tenant_id = :t AND n.type = 'document' AND n.key = d.extra->>'dsid'
              WHERE d.tenant_id = :t"""), p)
    x(text("ANALYZE rem_nodes"))
    x(text("ANALYZE rem_node_versions"))
    # passages (sections)
    x(text("""INSERT INTO rem_nodes (id, tenant_id, type, key, created_seq)
              SELECT gen_random_uuid(), :t, 'passage', s.id::text, :seq FROM sections s WHERE s.tenant_id = :t"""), p)
    x(text("""INSERT INTO rem_node_versions (id, tenant_id, node_id, version, sys_from, name, summary, attrs, project_ids, department_ids,
                  scope_id, sensitivity, acl, source_pointers, root_sources, verification, authoritative, recorded_at, embedding, tsv)
              SELECT gen_random_uuid(), :t, n.id, 1, :seq, coalesce(s.title, d.title, d.original_filename), left(s.text, 1500),
                     jsonb_build_object('source_system', coalesce(d.extra->>'source', 'document'), 'tokens', s.token_estimate,
                                        'document', d.extra->>'dsid'),
                     '{}', '{}', s.scope_id, s.sensitivity, coalesce(d.acl, '{}'::jsonb),
                     jsonb_build_array(jsonb_build_object('document_id', d.id::text, 'section_id', s.id::text, 'page_start', s.page_start,
                                                          'page_end', s.page_end)),
                     ARRAY['doc:' || (d.extra->>'dsid')], 'unverified', true, now(), s.embedding, s.tsv
              FROM sections s JOIN documents d ON d.id = s.document_id
              JOIN rem_nodes n ON n.tenant_id = :t AND n.type = 'passage' AND n.key = s.id::text WHERE s.tenant_id = :t"""), p)
    x(text("ANALYZE rem_nodes"))
    x(text("ANALYZE rem_node_versions"))
    x(text("""INSERT INTO rem_edges (id, tenant_id, src_id, dst_id, kind, provenance, status, attrs, source_pointers, derivation, edge_key, sys_from)
              SELECT gen_random_uuid(), :t, pn.id, dn.id, 'derived_from', 'explicit', 'asserted', '{}', '[]', '{}',
                     pn.id::text || '|derived_from|' || dn.id::text || '|explicit|', :seq
              FROM sections s JOIN documents d ON d.id = s.document_id
              JOIN rem_nodes pn ON pn.tenant_id = :t AND pn.type = 'passage' AND pn.key = s.id::text
              JOIN rem_nodes dn ON dn.tenant_id = :t AND dn.type = 'document' AND dn.key = d.extra->>'dsid' WHERE s.tenant_id = :t"""), p)
    # extracted records
    case = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in RECORD_TYPES.items())
    rec = f"""FROM memory_records r JOIN documents d ON d.id = r.source_document_id
              WHERE r.tenant_id = :t AND r.deleted_at IS NULL AND r.type::text IN ({",".join(f"'{k}'" for k in RECORD_TYPES)})"""
    x(text(f"""INSERT INTO rem_nodes (id, tenant_id, type, key, created_seq)
               SELECT gen_random_uuid(), :t, CASE r.type::text {case} END, r.id::text, :seq {rec}"""), p)
    x(text(f"""INSERT INTO rem_node_versions (id, tenant_id, node_id, version, sys_from, name, summary, attrs, project_ids, department_ids,
                   scope_id, sensitivity, acl, source_pointers, root_sources, verification, authoritative, recorded_at, embedding, tsv)
               SELECT gen_random_uuid(), :t, n.id, 1, :seq, left(r.summary, 300), left(r.detail, 1000),
                      jsonb_build_object('source_system', 'extracted', 'record_type', r.type::text, 'document', d.extra->>'dsid'),
                      '{{}}', '{{}}', r.scope_id, r.sensitivity, coalesce(r.acl, '{{}}'::jsonb), r.source_locations,
                      ARRAY['doc:' || (d.extra->>'dsid')], 'unverified', true, now(), r.embedding, r.tsv
               {rec.replace("WHERE r.tenant_id", "JOIN rem_nodes n ON n.tenant_id = :t AND n.key = r.id::text WHERE r.tenant_id")}"""), p)
    x(text("ANALYZE rem_nodes"))
    x(text("ANALYZE rem_node_versions"))
    x(text(f"""INSERT INTO rem_edges (id, tenant_id, src_id, dst_id, kind, provenance, status, attrs, source_pointers, derivation, edge_key, sys_from)
               SELECT gen_random_uuid(), :t, n.id, dn.id, 'derived_from', 'rule', 'asserted', '{{}}', '[]',
                      '{{"extractor": "cie.extraction (deterministic)"}}'::jsonb, n.id::text || '|derived_from|' || dn.id::text || '|rule|', :seq
               {rec.replace("WHERE r.tenant_id", "JOIN rem_nodes n ON n.tenant_id = :t AND n.key = r.id::text JOIN rem_nodes dn ON dn.tenant_id = :t AND dn.type = 'document' AND dn.key = d.extra->>'dsid' WHERE r.tenant_id")}
               AND r.type::text <> 'project'"""), p)
    # links between documents (via their document records) and between facts
    docnode = """(SELECT dn.id FROM memory_records m JOIN documents dd ON dd.id = m.source_document_id
                  JOIN rem_nodes dn ON dn.tenant_id = :t AND dn.type = 'document' AND dn.key = dd.extra->>'dsid' WHERE m.id = {c} LIMIT 1)"""
    for kind, src, dst, rel in (("references", "l.dst_id", "l.src_id", "supports"), ("depends_on", "l.src_id", "l.dst_id", "depends_on")):
        x(text(f"""INSERT INTO rem_edges (id, tenant_id, src_id, dst_id, kind, provenance, status, attrs, source_pointers, derivation, edge_key, sys_from)
                   SELECT gen_random_uuid(), :t, a, b, '{rel}', 'rule', 'asserted', '{{}}', '[]',
                          jsonb_build_object('link', '{kind}', 'justification', j), a::text || '|{rel}|' || b::text || '|rule|{kind}', :seq
                   FROM (SELECT {docnode.format(c=src)} a, {docnode.format(c=dst)} b, l.justification j FROM record_links l
                         WHERE l.tenant_id = :t AND l.kind = '{kind}') q WHERE a IS NOT NULL AND b IS NOT NULL AND a <> b"""), p)
    x(text("""INSERT INTO rem_edges (id, tenant_id, src_id, dst_id, kind, provenance, status, attrs, source_pointers, derivation, edge_key, sys_from)
              SELECT gen_random_uuid(), :t, a.id, b.id, 'contradicts', 'rule', 'asserted', '{}', '[]',
                     jsonb_build_object('link', 'contradicts', 'justification', l.justification), a.id::text || '|contradicts|' || b.id::text || '|rule|', :seq
              FROM record_links l JOIN rem_nodes a ON a.tenant_id = :t AND a.key = l.src_id::text JOIN rem_nodes b ON b.tenant_id = :t AND b.key = l.dst_id::text
              WHERE l.tenant_id = :t AND l.kind = 'contradicts'"""), p)
    x(text("ANALYZE rem_edges"))
    # project membership
    x(text("""UPDATE rem_node_versions v SET project_ids = q.pids FROM (
                SELECT dn.id nid, array_agg(DISTINCT pn.id) pids FROM record_links l
                JOIN memory_records m ON m.id = l.src_id AND m.type = 'document' JOIN documents dd ON dd.id = m.source_document_id
                JOIN rem_nodes dn ON dn.tenant_id = :t AND dn.type = 'document' AND dn.key = dd.extra->>'dsid'
                JOIN rem_nodes pn ON pn.tenant_id = :t AND pn.type = 'project' AND pn.key = l.dst_id::text
                WHERE l.tenant_id = :t AND l.kind = 'part_of' GROUP BY dn.id) q WHERE v.node_id = q.nid"""), p)
    # near-duplicates share one original source
    pairs = x(text("""SELECT da.extra->>'dsid', db.extra->>'dsid' FROM record_links l
                      JOIN memory_records a ON a.id = l.src_id JOIN documents da ON da.id = a.source_document_id
                      JOIN memory_records b ON b.id = l.dst_id JOIN documents db ON db.id = b.source_document_id
                      WHERE l.tenant_id = :t AND l.kind = 'near_duplicate'"""), p).all()
    parent: dict[str, str] = {}

    def find(a):
        while parent.get(a, a) != a:
            a = parent[a]
        return a

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    for dsid in {d for pr in pairs for d in pr}:
        x(text("""UPDATE rem_node_versions SET root_sources = ARRAY[:root] WHERE tenant_id = :t AND sys_to IS NULL
                  AND (attrs->>'document' = :d OR node_id IN (SELECT id FROM rem_nodes WHERE tenant_id = :t AND type = 'document' AND key = :d))"""),
          {**p, "root": f"doc:{find(dsid)}", "d": dsid})
    x(text("ANALYZE rem_node_versions"))
    session.flush()
    counts = dict(x(text("SELECT type, count(*) FROM rem_nodes WHERE tenant_id = :t GROUP BY type"), p).all())
    edges = dict(x(text("SELECT kind || '/' || provenance, count(*) FROM rem_edges WHERE tenant_id = :t GROUP BY 1"), p).all())
    out = {"reused": False, "seq": seq, "build_s": round(time.perf_counter() - t0, 1), "nodes": counts, "edges": edges,
           "near_duplicate_groups": len({find(d) for pr in pairs for d in pr})}
    log(f"REM graph built: {out}")
    return out


def start_hits(session, retriever, admin, company_id, question: str, dsid_node: dict[str, uuid.UUID], key_node: dict[str, uuid.UUID],
               k: int = 20) -> tuple[list[tuple[uuid.UUID, float]], float]:
    """Hybrid search (exact, keyword, vector; the engine's own graph expansion off) mapped to REM records."""
    t = time.perf_counter()
    res = retriever.retrieve(question, admin, company_id, use_graph=False)
    ms = (time.perf_counter() - t) * 1000
    hits: dict[uuid.UUID, float] = {}
    for c in sorted(res.ranked, key=lambda c: -c.final):
        if c.record is not None:
            nid = key_node.get(str(c.record.id))
            if nid is None and c.record.type.value == "document" and c.record.source_document_id is not None:
                nid = dsid_node.get(str(c.record.source_document_id))
        else:
            nid = key_node.get(str(c.section.id))
        if nid is not None and nid not in hits:
            hits[nid] = float(c.final)
        if len(hits) >= k:
            break
    return list(hits.items()), ms


def doc_order(evidence: list[dict[str, Any]], doc_of_node: dict[str, str]) -> list[str]:
    out: list[str] = []
    for e in evidence:
        d = doc_of_node.get(e["node"]["id"])
        if d is None:
            for sp in e.get("source_pointers") or []:
                d = doc_of_node.get(f"docid:{sp.get('document_id')}")
                if d:
                    break
        if d and d not in out:
            out.append(d)
    return out


def split_of(qid: str) -> str:
    return "dev" if int(hashlib.sha1(qid.encode()).hexdigest(), 16) % 2 == 0 else "heldout"


def run(args, out_dir: Path, embedder, factory) -> dict[str, Any]:
    from cie.core.models import Document, Principal, Tenant
    from cie.core.settings import get_settings
    from cie.eval.bench_rem import build_routing, pct
    from cie.governance.permissions import visible_scopes
    from cie.rem.models import RemNode, RemNodeVersion
    from cie.rem.query import QueryRequest, run_query
    from cie.retrieval.pipeline import Retriever

    root = Path(args.erb_root)
    questions = [json.loads(line) for line in (root / "questions.jsonl").read_text().splitlines() if line.strip()]
    questions = [q for q in questions if q["expected_doc_ids"] and split_of(q["question_id"]) == args.split]
    if args.questions:
        questions = questions[: args.questions]
    rows: list[dict[str, Any]] = []
    with factory() as s:
        t = s.scalar(select(Tenant).where(Tenant.name == args.erb_tenant))
        if t is None:
            raise SystemExit(f"unknown tenant {args.erb_tenant!r}; load it with cie.eval.bench_enterprise first")
        before = s.execute(text("SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c WHERE c.relname LIKE 'rem\\_%' AND c.relkind = 'r'")).scalar()
        build = build_graph(s, t.id)
        routing = {"reused": True}
        if not s.scalar(select(text("count(*)")).select_from(text("rem_routing_edges")).where(text("tenant_id = :t")).params(t=t.id)):
            routing = build_routing(s, t.id, degree=4, seed=7)
        s.commit()
        after = s.execute(text("SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c WHERE c.relname LIKE 'rem\\_%' AND c.relkind = 'r'")).scalar()
        company = s.scalar(select(text("id")).select_from(text("scopes")).where(text("tenant_id = :t AND parent_id IS NULL")).params(t=t.id))
        admin = s.scalar(select(Principal).where(Principal.tenant_id == t.id, Principal.name == "admin"))
        vis = visible_scopes(s, admin)
        dsid_of_doc = {str(i): e.get("dsid") for i, e in s.execute(select(Document.id, Document.extra).where(Document.tenant_id == t.id))}
        nodes = s.execute(select(RemNode.id, RemNode.type, RemNode.key).where(RemNode.tenant_id == t.id)).all()
        key_node = {k: i for i, _t, k in nodes}
        dsid_node = {doc_id: key_node[d] for doc_id, d in dsid_of_doc.items() if d in key_node}
        doc_of_node: dict[str, str] = {f"docid:{k}": v for k, v in dsid_of_doc.items()}
        for i, typ, k in nodes:
            if typ == "document":
                doc_of_node[str(i)] = k
        for nid, d in s.execute(select(RemNodeVersion.node_id, RemNodeVersion.attrs["document"].astext)
                                .where(RemNodeVersion.tenant_id == t.id, RemNodeVersion.sys_to.is_(None))):
            if d:
                doc_of_node[str(nid)] = d
        retriever = Retriever(s, get_settings(), embedder=embedder)
        t0 = time.perf_counter()
        for qi, q in enumerate(questions):
            gold = set(q["expected_doc_ids"])
            hits, search_ms = start_hits(s, retriever, admin, company, q["question"], dsid_node, key_node)
            s.rollback()
            for bname, limits in BUDGETS.items():
                for arm, policy in ARMS.items():
                    try:
                        o = run_query(s, t.id, vis, QueryRequest(question=q["question"], policy=policy, limits=limits, start_hits=hits,
                                                                 save=False), embedder=embedder, principal_id=admin.id)
                    except Exception as e:  # noqa: BLE001 - a failed question scores zero, never disappears
                        s.rollback()
                        rows.append({"qid": q["question_id"], "cat": q["question_type"], "budget": bname, "arm": arm, "error": str(e)[:200],
                                     "recall10": 0.0, "evidence_recall": 0.0, "evidence_precision": 0.0, "rr": 0.0, "ms": None})
                        continue
                    docs = doc_order(o["evidence"], doc_of_node)
                    first = next((i for i, d in enumerate(docs) if d in gold), None)
                    rows.append({"qid": q["question_id"], "cat": q["question_type"], "budget": bname, "arm": arm,
                                 "recall10": len(gold & set(docs[:10])) / len(gold), "evidence_recall": len(gold & set(docs)) / len(gold),
                                 "evidence_precision": len(gold & set(docs)) / len(docs) if docs else 0.0,
                                 "rr": 1 / (first + 1) if first is not None else 0.0, "docs": len(docs),
                                 "ms": o["budget"]["used"]["ms"] + search_ms, "rem_ms": o["budget"]["used"]["ms"], "search_ms": search_ms,
                                 "visited": o["budget"]["used"]["visited"], "db_calls": o["budget"]["used"]["db_calls"],
                                 "tokens": o["budget"]["used"]["tokens"], "status": o["status"], "stop": o["stopping_reason"]})
                    s.rollback()
            if (qi + 1) % 25 == 0:
                print(f"  {qi + 1}/{len(questions)} questions, {time.perf_counter() - t0:.0f} s", flush=True)
    summary: dict[str, Any] = {"tenant": args.erb_tenant, "split": args.split, "questions": len(questions), "graph_build": build,
                               "routing_build": routing, "rem_bytes_added": int((after or 0) - (before or 0)), "arms": {}}
    for bname in BUDGETS:
        summary["arms"][bname] = {}
        for arm in ARMS:
            sub = [r for r in rows if r["budget"] == bname and r["arm"] == arm]
            ok = [r for r in sub if r.get("ms") is not None]
            summary["arms"][bname][arm] = {
                "recall@10": round(statistics.mean(r["recall10"] for r in sub), 3), "mrr": round(statistics.mean(r["rr"] for r in sub), 3),
                "evidence_recall": round(statistics.mean(r["evidence_recall"] for r in sub), 3),
                "evidence_precision": round(statistics.mean(r["evidence_precision"] for r in sub), 3),
                "docs_returned_p50": pct([r.get("docs", 0) for r in ok], 0.5), "errors": len(sub) - len(ok),
                "incomplete": sum(r.get("status") == "incomplete" for r in ok),
                "latency_ms_p50": pct([r["ms"] for r in ok], 0.5), "latency_ms_p95": pct([r["ms"] for r in ok], 0.95),
                "rem_ms_p50": pct([r["rem_ms"] for r in ok], 0.5), "visited_p50": pct([r["visited"] for r in ok], 0.5),
                "db_calls_p50": pct([r["db_calls"] for r in ok], 0.5), "tokens_p50": pct([r["tokens"] for r in ok], 0.5)}
    (out_dir / f"erb-{args.split}.json").write_text(json.dumps(summary, indent=2, default=str))
    (out_dir / f"erb-{args.split}-rows.json").write_text(json.dumps(rows, default=str))
    return summary
