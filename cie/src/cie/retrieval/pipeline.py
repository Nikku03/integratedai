"""The hybrid retrieval pipeline.

    classify intent → resolve scopes + permissions → exact lookup
    → lexical ∥ vector (records and sections) → RRF fusion
    → bounded graph expansion → rerank → contradiction check
    → evidence packet → (optional) cited answer
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from cie.core.models import EvidencePacket, MemoryRecord, Metric, Principal, Section
from cie.core.settings import Settings, get_settings
from cie.governance.audit import audit
from cie.governance.permissions import AccessDenied, Visibility, visible_scopes
from cie.memory.embeddings import EmbeddingProvider, get_embedding_provider
from cie.memory.records import current_only
from cie.memory.scopes import addressable_scope_ids
from cie.retrieval import contradictions, exact, fusion, graph, lexical, packet, rerank, vector
from cie.retrieval.answer import AnswerResult, assisted, extractive, persist
from cie.retrieval.intent import Intent, classify


@dataclass
class RetrievalResult:
    packet: EvidencePacket
    intent: Intent
    ranked: list[rerank.Candidate]
    trace: dict[str, Any]


def _pull_partners(ranked, conflicts):
    """Place every recorded contradiction partner directly after the highest-ranked
    item it contradicts, so the packet budget can never separate the two sides.
    Order within the rest of the list is preserved."""
    pos = {c.record.id: i for i, c in enumerate(ranked) if c.record is not None}
    moved: set = set()
    out = []
    for c in ranked:
        if c.record is not None and c.record.id in moved:
            continue
        out.append(c)
        if c.record is None:
            continue
        for pid in conflicts.get(c.record.id, []):
            j = pos.get(pid)
            if j is not None and j > pos[c.record.id] and pid not in moved:
                out.append(ranked[j])
                moved.add(pid)
    return out


class Retriever:
    def __init__(self, session: Session, settings: Settings | None = None, embedder: EmbeddingProvider | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.embedder = embedder or get_embedding_provider(self.settings)

    # ------------------------------------------------------------------
    def retrieve(self, query: str, principal: Principal, scope_id: uuid.UUID, *, filters: dict | None = None,
                 k: int = 80, at: datetime | None = None, use_graph: bool = True, use_vector: bool = True,
                 use_lexical: bool = True, use_sections: bool = True, use_exact: bool = True, max_records: int | None = None,
                 min_records: int | None = None, token_budget: int | None = None, graph_mode: str = "rem") -> RetrievalResult:
        """``graph_mode``: ``rem`` (bounded-horizon expansion), ``cliques`` (the topological
        recruitment cascade in its place) or ``cliques+bonus`` (cascade plus a rerank bonus
        for records inside high-dimensional activated simplices)."""
        t0 = time.perf_counter()
        s = self.session
        filters = filters or {}
        intent = classify(query)
        at = at or intent.as_of
        vis = visible_scopes(s, principal)
        requested = addressable_scope_ids(s, scope_id)
        allowed = [sid for sid in requested if sid in vis.scope_ids]
        if not allowed:
            audit(s, tenant_id=principal.tenant_id, principal_id=principal.id, action="search", resource_kind="scope",
                  resource_id=scope_id, details={"query": query}, outcome="denied")
            raise AccessDenied("principal has no visible scopes under the requested scope")
        rec_filter, perm_only = self._record_filter(vis, allowed, principal.tenant_id, intent, at, filters)
        sec_filter = and_(Section.tenant_id == principal.tenant_id, Section.scope_id.in_(allowed),
                          vis.sql_filter(Section.scope_id, Section.sensitivity))
        if filters.get("document_id"):
            sec_filter = and_(sec_filter, Section.document_id == uuid.UUID(str(filters["document_id"])))
        timings: dict[str, float] = {}

        # 1–3. exact
        t = time.perf_counter()
        exact_hits = exact.lookup(s, intent, query, rec_filter, k=min(k, 30)) if use_exact else []
        timings["exact_ms"] = (time.perf_counter() - t) * 1000

        # 4. lexical ∥ vector
        # exact matches (ids, clause numbers, quoted phrases, entity names) are strong evidence; a keyword-array overlap
        # (the exact stage's 1.0 hits) is weak evidence and must not ride on the exact list's weight
        lists: dict[str, list] = {"exact": [(rid, sc) for rid, sc in exact_hits if sc >= 2.0],
                                  "keywords": [(rid, sc) for rid, sc in exact_hits if sc < 2.0]}
        if use_lexical:
            t = time.perf_counter()
            lists["lex_rec"] = lexical.search_records(s, query, rec_filter, k, tenant_id=principal.tenant_id)
            if use_sections:
                lists["lex_sec"] = [(("sec", i), sc) for i, sc in lexical.search_sections(s, query, sec_filter, k, tenant_id=principal.tenant_id)]
            timings["lexical_ms"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        qvec = self.embedder.embed([query])[0] if use_vector else None
        timings["embed_ms"] = (time.perf_counter() - t) * 1000
        if use_vector:
            t = time.perf_counter()
            lists["vec_rec"] = vector.search_records(s, qvec, rec_filter, k)
            if use_sections:
                lists["vec_sec"] = [(("sec", i), sc) for i, sc in vector.search_sections(s, qvec, sec_filter, k)]
            timings["vector_ms"] = (time.perf_counter() - t) * 1000
        # named documents/suppliers: templated files tie on text, so search the named documents explicitly
        named_docs = self._named_documents(query, principal.tenant_id, allowed, vis)
        if named_docs:
            t = time.perf_counter()
            doc_rec = and_(rec_filter, MemoryRecord.source_document_id.in_(named_docs))
            doc_sec = and_(sec_filter, Section.document_id.in_(named_docs))
            kd = max(k, 300)  # the named-document pool is small; do not let ties cut it
            if use_lexical:
                lists["lex_doc"] = lexical.search_records(s, query, doc_rec, kd, tenant_id=principal.tenant_id)
                if use_sections:
                    lists["lex_doc_sec"] = [(("sec", i), sc) for i, sc in lexical.search_sections(s, query, doc_sec, kd, tenant_id=principal.tenant_id)]
            if use_vector:
                lists["vec_doc"] = vector.search_records(s, qvec, doc_rec, kd)
            timings["named_docs_ms"] = (time.perf_counter() - t) * 1000
        # records and sections fuse on equal terms: which of them carries the evidence depends on the corpus
        # (typed records in contracts, chunks in tickets and threads); the reranker's type and document reasons decide after
        fused = fusion.rrf(lists, weights={"exact": 2.0, "keywords": 0.5, "lex_rec": 1.0, "vec_rec": 1.0, "lex_sec": 1.0, "vec_sec": 1.0,
                                           "lex_doc": 1.5, "vec_doc": 1.5, "lex_doc_sec": 1.5})

        # 5. graph expansion (REM horizons) or topological recruitment (clique cascade)
        expanded: list = []
        budget = 0
        topo_features: dict = {}
        topo_stats: dict = {}
        if use_graph:
            t = time.perf_counter()
            seeds = {rid: v["score"] for rid, v in fused.items() if not isinstance(rid, tuple)}
            seeds = dict(sorted(seeds.items(), key=lambda kv: -kv[1])[:20])
            # the budget only needs log2(N): use the planner's row estimate, never a COUNT(*) per query
            n_records = int(s.execute(text("SELECT reltuples FROM pg_class WHERE relname = 'memory_records'")).scalar() or 0)
            budget = graph.budget_for(max(n_records, 16), self.settings.graph_budget_coefficient)
            if graph_mode.startswith("cliques"):
                from cie.topology import cascade

                recruited, cx, topo_features = cascade.recruit(s, seeds, base_filter=rec_filter, cross_scope_filter=perm_only, budget=budget)
                expanded = [graph.Expanded(r.record_id, r.stage, r.via, f"clique{r.dim}:{r.kind}", r.score) for r in recruited]
                topo_stats = cx.stats()
            else:
                expanded = graph.expand(s, seeds, base_filter=rec_filter, cross_scope_filter=perm_only, budget=budget)
            timings["graph_ms"] = (time.perf_counter() - t) * 1000

        # materialise candidates
        t = time.perf_counter()
        rec_ids = [rid for rid in fused if not isinstance(rid, tuple)] + [e.record_id for e in expanded]
        sec_ids = [rid[1] for rid in fused if isinstance(rid, tuple)]
        recs = exact.by_ids(s, rec_ids)
        from sqlalchemy.orm import defer

        secs = {x.id: x for x in s.scalars(select(Section).where(Section.id.in_(sec_ids))
                                           .options(defer(Section.embedding), defer(Section.tsv)))} if sec_ids else {}
        degrees = graph.degree(s, list(recs))
        cands: list[rerank.Candidate] = []
        for rid, v in fused.items():
            if isinstance(rid, tuple):
                if rid[1] in secs:
                    cands.append(rerank.Candidate(None, secs[rid[1]], v["score"], v["sources"]))
            elif rid in recs:
                cands.append(rerank.Candidate(recs[rid], None, v["score"], v["sources"], degree=degrees.get(rid, 0)))
        seen = {c.id for c in cands}
        for e in expanded:
            if e.record_id in recs and e.record_id not in seen:
                cands.append(rerank.Candidate(recs[e.record_id], None, e.score * 0.5, {"graph": (e.horizon, e.score)},
                                              horizon=e.horizon, via=f"{e.kind}:{e.via}", degree=degrees.get(e.record_id, 0)))
                seen.add(e.record_id)
        # defence in depth: per-record ACL check in Python as well as SQL
        cands = [c for c in cands if c.record is None or vis.can_read(c.record.scope_id, c.record.sensitivity, c.record.acl)]
        if topo_features:
            for c in cands:
                f = topo_features.get(c.id)
                if f:
                    c.clique_dim, c.sink_of, c.source_of = f["dim"], f["sink_of"], f["source_of"]

        timings["materialise_ms"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        # 6. rerank (document titles/types let a named supplier disambiguate similar files and demote drafts)
        doc_ids = {c.record.source_document_id if c.record is not None else c.section.document_id for c in cands}
        doc_ids.discard(None)
        titles: dict = {}
        doc_types: dict = {}
        if doc_ids:
            from cie.core.models import Document

            rows = s.execute(select(Document.id, Document.title, Document.original_filename, Document.doc_type)
                             .where(Document.id.in_(list(doc_ids)))).all()
            titles = {d_id: f"{title} {fname}" for d_id, title, fname, _ in rows}
            doc_types = {d_id: (dt or "") for d_id, _, _, dt in rows}
        ranked = rerank.rerank(cands, intent, query, doc_titles=titles, doc_types=doc_types, clique_bonus=graph_mode == "cliques+bonus")

        timings["rerank_ms"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        # 7. contradictions
        conflicts, extra = contradictions.find(s, [c.record.id for c in ranked if c.record is not None][:max_records or self.settings.packet_max_records], rec_filter)
        for r in extra:
            if r.id not in seen and vis.can_read(r.scope_id, r.sensitivity, r.acl):
                partner = rerank.Candidate(r, None, 0.0, {"contradiction": (0, 0.0)}, horizon=1, via="contradicts")
                partner.support = 1.0  # it is the other side of a recorded contradiction with an item that has support
                ranked.append(partner)
                seen.add(r.id)
        ranked = _pull_partners(ranked, conflicts)

        timings["contradictions_ms"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        # 8. packet
        latency = (time.perf_counter() - t0) * 1000
        trace = {"timings_ms": timings, "graph_budget": budget, "expanded": len(expanded), "candidates": len(cands),
                 "lists": {k_: len(v) for k_, v in lists.items()}, "as_of": at.isoformat() if at else None,
                 "embedding_provider": getattr(self.embedder, "name", "?"), "scopes_allowed": len(allowed),
                 "arms": {"exact": use_exact, "lexical": use_lexical, "vector": use_vector, "graph": use_graph, "graph_mode": graph_mode},
                 "topology": topo_stats, "edges_used": [(str(e.via), str(e.record_id)) for e in expanded]}
        pk = packet.build(s, tenant_id=principal.tenant_id, principal_id=principal.id, query=query, intent=intent.kind,
                          scope_ids=allowed, filters=filters, ranked=ranked, conflicts=conflicts,
                          min_records=min_records or self.settings.packet_min_records,
                          max_records=max_records or self.settings.packet_max_records,
                          token_budget=token_budget or self.settings.packet_token_budget, trace=trace, latency_ms=latency)
        pk.trace["timings_ms"]["packet_ms"] = (time.perf_counter() - t) * 1000
        audit(s, tenant_id=principal.tenant_id, principal_id=principal.id, action="search", resource_kind="evidence_packet",
              resource_id=pk.id, details={"query": query, "scope_id": str(scope_id), "items": len(pk.items)})
        s.add(Metric(tenant_id=principal.tenant_id, name="retrieval_latency_ms", value=latency,
                     labels={"intent": intent.kind, "graph": use_graph}))
        s.add(Metric(tenant_id=principal.tenant_id, name="packet_tokens", value=pk.token_estimate, labels={}))
        return RetrievalResult(pk, intent, ranked, trace)

    # ------------------------------------------------------------------
    def answer(self, query: str, principal: Principal, scope_id: uuid.UUID, *, mode: str = "strict",
               provider=None, **kw) -> tuple[AnswerResult, RetrievalResult]:
        res = self.retrieve(query, principal, scope_id, **kw)
        if mode == "assisted" and provider is not None:
            result = assisted(res.packet, res.intent, provider, strict=self.settings.strict_evidence_mode)
        else:
            result = extractive(res.packet, res.intent)
        row = persist(self.session, res.packet, result, principal.id, query)
        if self.settings.dynamic_memory and result.status in ("answered", "conflict"):
            from cie.topology import dynamic

            fired = dynamic.fired_records(res.packet.items, result.citations, max_fired=self.settings.dynamic_max_fired,
                                          min_support=self.settings.dynamic_min_support,
                                          max_docs=2 if result.status == "conflict" else (3 if res.intent.kind == "compare" else 1))
            res.trace["dynamic"] = dynamic.observe(self.session, tenant_id=principal.tenant_id, principal_id=principal.id, fired=fired,
                                                   query=query, max_degree=self.settings.dynamic_max_degree)
        audit(self.session, tenant_id=principal.tenant_id, principal_id=principal.id, action="answer",
              resource_kind="answer", resource_id=row.id, details={"status": result.status, "mode": result.mode,
                                                                    "packet_id": str(res.packet.id)})
        for name, val in (("answer_tokens_in", result.tokens_in), ("answer_tokens_out", result.tokens_out),
                          ("answer_cost_usd", result.cost_usd), ("answer_latency_ms", result.latency_ms)):
            self.session.add(Metric(tenant_id=principal.tenant_id, name=name, value=float(val), labels={"mode": result.mode}))
        result.answer_id = row.id  # type: ignore[attr-defined]
        return result, res

    def _named_documents(self, query: str, tenant_id: uuid.UUID, allowed: list[uuid.UUID], vis: Visibility) -> list[uuid.UUID]:
        """Documents whose title or filename carries a capitalised name from the query.
        Words go through the trigram-indexed ILIKE on each column (never a scan of every
        document); numerals in a name ("Project 37") count only as whole words, so a
        namesake ("Project 3") does not tie with the named file."""
        from sqlalchemy import case, or_

        from cie.core.models import Document

        ents = sorted(rerank.entity_terms(query))
        words = [e for e in ents if len(e) >= 4 and not e.isdigit()][:5]
        nums = [e for e in ents if e.isdigit()][:3]
        if not words:
            return []
        conds = [or_(Document.title.ilike(f"%{w}%"), Document.original_filename.ilike(f"%{w}%")) for w in words]
        hay = func.concat(Document.title, " ", Document.original_filename)
        matches = sum(case((c, 1), else_=0) for c in conds)  # documents matching more of the name rank first
        for n in nums:
            matches = matches + case((hay.op("~")(rf"\m{n}\M"), 1), else_=0)
        base = (Document.tenant_id == tenant_id, Document.deleted_at.is_(None), Document.scope_id.in_(allowed),
                vis.sql_filter(Document.scope_id, Document.sensitivity))
        # every word of the name first: a handful of rows even when each word alone matches thousands of files;
        # any word only when no file carries the whole name
        rows = self.session.execute(select(Document.id, matches).where(*base, and_(*conds)).order_by(matches.desc()).limit(40)).all()
        if not rows and len(conds) > 1:
            rows = self.session.execute(select(Document.id, matches).where(*base, or_(*conds)).order_by(matches.desc()).limit(40)).all()
        if not rows:
            return []
        best = rows[0][1]
        # only the best-matching documents: if one file carries the whole name, its namesakes are other documents
        return [d_id for d_id, m in rows if m == best][:20]

    # ------------------------------------------------------------------
    @staticmethod
    def _record_filter(vis: Visibility, allowed: list[uuid.UUID], tenant_id: uuid.UUID, intent: Intent,
                       at: datetime | None, filters: dict):
        """Returns (scoped_filter, permission_only_filter). Both apply tenant,
        permission, deletion and time rules; only the first restricts scopes."""
        f = and_(MemoryRecord.tenant_id == tenant_id,
                 vis.sql_filter(MemoryRecord.scope_id, MemoryRecord.sensitivity), MemoryRecord.deleted_at.is_(None))
        if filters.get("types"):
            from cie.core.models import RecordType

            f = and_(f, MemoryRecord.type.in_([RecordType(t) for t in filters["types"]]))
        if filters.get("document_id"):
            f = and_(f, MemoryRecord.source_document_id == uuid.UUID(str(filters["document_id"])))
        if filters.get("verified_only"):
            from cie.core.models import VerificationStatus

            f = and_(f, MemoryRecord.verification == VerificationStatus.verified)
        if at is not None:
            stmt = current_only(select(MemoryRecord.id), at)
            f = and_(f, *stmt.whereclause.clauses)  # type: ignore[union-attr]
        elif not intent.include_history and not filters.get("include_history"):
            # current facts only: not superseded, valid now
            stmt = current_only(select(MemoryRecord.id))
            f = and_(f, *stmt.whereclause.clauses)  # type: ignore[union-attr]
        return and_(f, MemoryRecord.scope_id.in_(allowed)), f
