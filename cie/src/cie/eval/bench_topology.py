"""Topological memory bank versus the standard one, and the clique network versus a
deep network. Runs against the largest scale tenant an earlier ``bench_scale`` run
loaded (default: the 1M tenant), so every number is measured, not projected.

1. Retrieval arms REM vs cliques vs cliques+bonus are measured by ``bench_scale``
   (``--remeasure``) and read from its JSON; this module adds the two experiments
   the arms cannot express:
2. Plasticity: STDP-like potentiation/depression of links from what retrieval
   used, then the same and unseen questions on the same documents, weights restored.
3. A learned reranker: per-candidate features from the retrieval traces (fusion,
   support, sources, document affinity, graph and clique statistics) with the
   target document/type as label, split by document; the clique-cascade network
   (back-propagation and a local Hebbian rule) against a deep MLP and the
   hand-written reranker.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select

from cie.core.db import session_scope
from cie.core.models import Document, Principal, Scope, Tenant
from cie.core.settings import get_settings
from cie.eval.bench_scale import DEPTS, _p, _q, short_name, supplier_name
from cie.memory.embeddings import get_embedding_provider
from cie.retrieval.pipeline import Retriever
from cie.topology import plasticity
from cie.topology.cliquenet import (
    MLP,
    CliqueNet,
    auc,
    n_params,
    predict,
    ranking_quality,
    train_backprop,
    train_hebbian,
)

FEATURES = ["fused", "support", "exact", "lex_rec", "vec_rec", "lex_doc", "vec_doc", "lex_sec", "vec_sec", "graph", "horizon", "log_degree",
            "document_affinity", "entity_affinity", "other_document", "type_match", "verification", "confidence", "recency", "hub_penalty",
            "draft_document", "clique_dim", "sink_of", "source_of", "q_betti1", "q_max_dim", "q_nodes", "is_record"]


def _features(c, trace: dict) -> list[float]:
    src = c.sources or {}
    tp = trace.get("topology") or {}
    r = c.reasons or {}

    def rank_feat(name: str) -> float:
        v = src.get(name)
        return 1.0 / (1 + v[0]) if v else 0.0

    return [float(c.fused), float(c.support), rank_feat("exact"), rank_feat("lex_rec"), rank_feat("vec_rec"), rank_feat("lex_doc"), rank_feat("vec_doc"),
            rank_feat("lex_sec"), rank_feat("vec_sec"), rank_feat("graph"), float(c.horizon), float(np.log1p(c.degree)),
            r.get("document_affinity", 0.0), r.get("entity_affinity", 0.0), r.get("other_document", 0.0), r.get("type_match", 0.0),
            r.get("verification", 0.0), r.get("confidence", 0.0), r.get("recency", 0.0), r.get("hub_penalty", 0.0), r.get("draft_document", 0.0),
            float(c.clique_dim), float(c.sink_of), float(c.source_of), float(tp.get("betti1", 0)), float(tp.get("max_dim", 0)), float(tp.get("nodes", 0)),
            1.0 if c.record is not None else 0.0]


def _tenant(s, prefix: str):
    tenant = s.scalars(select(Tenant).where(Tenant.name.like(prefix + "%")).order_by(Tenant.created_at.desc())).first()
    if tenant is None:
        raise SystemExit(f"no tenant matching {prefix}: run bench_scale first")
    company = s.scalar(select(Scope).where(Scope.tenant_id == tenant.id, Scope.parent_id.is_(None)))
    dept0 = s.scalar(select(Scope).where(Scope.tenant_id == tenant.id, Scope.name == DEPTS[0]))
    admin = s.scalar(select(Principal).where(Principal.tenant_id == tenant.id, Principal.name == "admin"))
    docs = list(s.scalars(select(Document).where(Document.tenant_id == tenant.id)))
    by_title = {d.title: d.id for d in docs}
    doc_ids = [by_title.get(f"{short_name(supplier_name(i))} Master Services Agreement") for i in range(len(docs))]
    return tenant, company, dept0, admin, doc_ids


def _questions_for(docs: list[int], kinds: list[str]) -> list[dict[str, Any]]:
    out = []
    for d in docs:
        short = short_name(supplier_name(d))
        for kind in kinds:
            q = {"fee": f"What is the monthly fee in the {short} agreement?", "notice": f"What is the termination notice period under the {short} agreement?",
                 "penalty": f"What late payment penalty applies in the {short} contract?", "signed": f"Who signed the {short} agreement for Acme Robotics?",
                 "liability": f"How is liability limited in the {short} agreement?", "term": f"What is the initial term of the {short} agreement?"}[kind]
            rtype = {"fee": "metric", "notice": "deadline", "penalty": "metric", "signed": "fact", "liability": "risk", "term": "requirement"}[kind]
            out.append({"q": q, "doc": d, "type": rtype, "kind": kind})
    return out


def _measure(s, retriever, admin, scope_id, questions, doc_ids, **cfg) -> dict[str, Any]:
    hits = 0
    rr, lat, graph_ms = [], [], []
    for q in questions:
        t = time.perf_counter()
        res = retriever.retrieve(q["q"], admin, scope_id, **cfg)
        lat.append((time.perf_counter() - t) * 1000)
        graph_ms.append(res.trace["timings_ms"].get("graph_ms", 0.0))
        target = str(doc_ids[q["doc"]])
        pos = next((i for i, it in enumerate(res.packet.items) if it.get("document_id") == target and it.get("type") == q["type"]), None)
        hits += pos is not None and pos < 20
        rr.append(1.0 / (pos + 1) if pos is not None else 0.0)
        s.rollback()
    return {"hit_at_20": round(hits / len(questions), 3), "mrr": round(float(np.mean(rr)), 3), "p50_ms": _p(lat, 0.5), "graph_ms_p50": _p(graph_ms, 0.5)}


def plasticity_experiment(s, retriever, tenant, admin, company, doc_ids, n_docs: int = 40, seed: int = 5) -> dict[str, Any]:
    """Learn from one set of questions about a set of documents, then ask the same
    questions (in-sample) and different questions about the same documents (the
    generalisation a re-routed pathway should give). Weights are restored afterwards."""
    rng = random.Random(seed + 23)
    docs = sorted(rng.sample(range(len(doc_ids)), n_docs))
    train = _questions_for(docs, ["fee", "penalty", "notice"])
    test = _questions_for(docs, ["signed", "liability", "term"])
    out: dict[str, Any] = {"documents": n_docs, "train_questions": len(train), "test_questions": len(test), "arms": {}}
    previous: dict[str, float] = {}
    for mode in ("rem", "cliques"):
        before = {"train": _measure(s, retriever, admin, company.id, train, doc_ids, graph_mode=mode),
                  "test": _measure(s, retriever, admin, company.id, test, doc_ids, graph_mode=mode)}
        pot = dep = 0
        for q in train:  # learning pass: what the packet used is what fired
            res = retriever.retrieve(q["q"], admin, company.id, graph_mode=mode)
            fired = [uuid.UUID(it["id"]) for it in res.packet.items[:8] if it.get("kind") == "record"]
            walked = [(uuid.UUID(a), uuid.UUID(b)) for a, b in res.trace.get("edges_used", [])]
            upd = plasticity.stdp_update(s, fired, walked)
            for k, v in upd["previous"].items():
                previous.setdefault(k, v)
            pot += upd["potentiated"]
            dep += upd["depressed"]
        s.commit()
        after = {"train": _measure(s, retriever, admin, company.id, train, doc_ids, graph_mode=mode),
                 "test": _measure(s, retriever, admin, company.id, test, doc_ids, graph_mode=mode)}
        plasticity.restore(s, previous)
        s.commit()
        previous = {}
        out["arms"][mode] = {"before": before, "after": after, "links_potentiated": pot, "links_depressed": dep}
    return out


def build_dataset(s, retriever, admin, company, doc_ids, n_questions: int = 240, seed: int = 5) -> dict[str, Any]:
    """Per-candidate feature rows from retrieval traces (topological mode, so clique
    statistics are populated), labelled by the benchmark's target document and type."""
    n_docs = len(doc_ids)
    questions = [q for q in (_q(random.Random(seed + 7 + i), n_docs) for i in range(1 + n_questions // 50)) for q in q][:n_questions * 2]
    questions = [q for q in questions if q["doc"] is not None][:n_questions]
    rows, labels, groups, heuristic = [], [], [], []
    for gi, q in enumerate(questions):
        res = retriever.retrieve(q["q"], admin, company.id, graph_mode="cliques")
        target = str(doc_ids[q["doc"]])
        for c in res.ranked:
            if c.record is None:
                continue
            rows.append(_features(c, res.trace))
            labels.append(1.0 if (str(c.record.source_document_id) == target and c.record.type.value == q["type"]) else 0.0)
            groups.append(gi)
            heuristic.append(float(c.final))
        s.rollback()
    X = np.array(rows, dtype=np.float32)
    y = np.array(labels, dtype=np.float32)
    g = np.array(groups)
    h = np.array(heuristic, dtype=np.float32)
    # split by document: a question about a document in the test set never appears in training
    docs_by_group = np.array([q["doc"] for q in questions])
    test_docs = {d for d in set(docs_by_group.tolist()) if d % 3 == 0}
    test_mask = np.array([docs_by_group[gi] in test_docs for gi in g])
    return {"X": X, "y": y, "groups": g, "heuristic": h, "test_mask": test_mask, "features": FEATURES,
            "n_questions": len(questions), "n_rows": len(rows), "positives": int(y.sum())}


def compare_models(ds: dict[str, Any], epochs: int = 30) -> dict[str, Any]:
    X, y, g, h, tm = ds["X"], ds["y"], ds["groups"], ds["heuristic"], ds["test_mask"]
    mu, sd = X[~tm].mean(0), X[~tm].std(0) + 1e-6
    Xn = (X - mu) / sd
    out: dict[str, Any] = {"train_rows": int((~tm).sum()), "test_rows": int(tm.sum()), "test_queries": len(np.unique(g[tm])), "models": {}}
    out["models"]["heuristic reranker (hand-written)"] = {"params": 0, "train_seconds": 0.0, "rule": "none",
                                                          "auc": round(auc(h[tm], y[tm]), 3), **ranking_quality(h[tm], y[tm], g[tm])}
    n_in = X.shape[1]
    for name, model, trainer in (("clique network / backprop", CliqueNet(n_in), train_backprop),
                                 ("clique network / Hebbian (local)", CliqueNet(n_in), train_hebbian),
                                 ("deep MLP (4x64) / backprop", MLP(n_in), train_backprop)):
        info = trainer(model, Xn[~tm], y[~tm], epochs=epochs) if trainer is train_backprop else trainer(model, Xn[~tm], y[~tm])
        sc = predict(model, Xn[tm])
        out["models"][name] = {"params": n_params(model), **info, "auc": round(auc(sc, y[tm]), 3), **ranking_quality(sc, y[tm], g[tm])}
    return out


def run(out: Path, tenant_prefix: str = "scale-1000000-", n_docs: int = 40, n_questions: int = 240) -> dict[str, Any]:
    settings = get_settings()
    embedder = get_embedding_provider(settings)
    report: dict[str, Any] = {"tenant_prefix": tenant_prefix}
    scale = out.parent / "scale" / "bench_scale.json"
    if scale.exists():
        rep = json.loads(scale.read_text())
        key = next((k for k in rep["sizes"] if k.startswith(tenant_prefix.split("-")[1]) and "re-measured" in k), None) or tenant_prefix.split("-")[1]
        arms = rep["sizes"].get(key, {}).get("admin@company", {})
        report["retrieval_arms"] = {a: {k: v for k, v in arms[a].items() if k != "stage_ms_p50"} for a in arms if a in
                                    ("hybrid+graph(bounded)", "hybrid+cliques(topological)", "hybrid+cliques+bonus")}
        report["retrieval_arms_source"] = key
    with session_scope() as s:
        tenant, company, dept0, admin, doc_ids = _tenant(s, tenant_prefix)
        retriever = Retriever(s, settings, embedder=embedder)
        report["plasticity"] = plasticity_experiment(s, retriever, tenant, admin, company, doc_ids, n_docs=n_docs)
        ds = build_dataset(s, retriever, admin, company, doc_ids, n_questions=n_questions)
        report["dataset"] = {k: ds[k] for k in ("features", "n_questions", "n_rows", "positives")}
        s.rollback()
    report["reranker_models"] = compare_models(ds, epochs=15)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench_topology.json").write_text(json.dumps(report, indent=2, default=str))
    md = to_markdown(report)
    (out / "bench_topology.md").write_text(md)
    print(md)
    return report


def to_markdown(rep: dict[str, Any]) -> str:
    lines = ["### Topological memory bank vs standard (largest loaded tenant)", ""]
    if rep.get("retrieval_arms"):
        lines += [f"Retrieval arms (admin over the whole company, from `bench_scale` row `{rep.get('retrieval_arms_source')}`):", "",
                  "| arm | warm p50 ms | warm p95 ms | hit@20 | MRR | topology p50 (nodes / max dim / cavities) |", "|---|---|---|---|---|---|"]
        for a, v in rep["retrieval_arms"].items():
            tp = v.get("topology_p50") or {}
            tps = f"{tp.get('nodes')} / {tp.get('max_dim')} / {tp.get('betti1')}" if tp else "-"
            lines.append(f"| {a} | {v['warm_p50_ms']} | {v['warm_p95_ms']} | {v['hit_at_20']} | {v.get('mrr', '-')} | {tps} |")
    pl = rep.get("plasticity")
    if pl:
        lines += ["", f"Plasticity (STDP-like): {pl['documents']} documents, {pl['train_questions']} learning questions, {pl['test_questions']} unseen questions "
                  "about the same documents; links potentiated/depressed from what the packets used; weights restored afterwards.", "",
                  "| arm | set | hit@20 before → after | MRR before → after | p50 ms before → after | graph stage p50 ms before → after | links +/− |",
                  "|---|---|---|---|---|---|---|"]
        for mode, v in pl["arms"].items():
            for which in ("train", "test"):
                b, a = v["before"][which], v["after"][which]
                lines.append(f"| {mode} | {'same questions' if which == 'train' else 'unseen questions, same documents'} | {b['hit_at_20']} → {a['hit_at_20']} | "
                             f"{b['mrr']} → {a['mrr']} | {b['p50_ms']} → {a['p50_ms']} | {b['graph_ms_p50']} → {a['graph_ms_p50']} | "
                             f"{v['links_potentiated']} / {v['links_depressed']} |")
    m = rep.get("reranker_models")
    if m:
        ds = rep.get("dataset", {})
        lines += ["", f"Learned reranker on retrieval traces: {ds.get('n_questions')} questions, {ds.get('n_rows'):,} candidate rows "
                  f"({ds.get('positives')} positives), {len(ds.get('features', []))} features; split by document "
                  f"({m['train_rows']:,} training rows, {m['test_rows']:,} test rows over {m['test_queries']} unseen-document queries).", "",
                  "| model | parameters | learning rule | train s | AUC (test) | hit@1 | hit@5 | MRR |", "|---|---|---|---|---|---|---|---|"]
        for name, v in m["models"].items():
            lines.append(f"| {name} | {v['params']:,} | {v['rule']} | {v['train_seconds']} | {v['auc']} | {v['hit@1']} | {v['hit@5']} | {v['mrr']} |")
    return "\n".join(lines)


def main(out: Path = Path("eval_out/topology"), **kw) -> dict:
    return run(out, **kw)


if __name__ == "__main__":  # pragma: no cover
    import sys

    main(Path("eval_out/topology"), **({"tenant_prefix": sys.argv[1]} if len(sys.argv) > 1 else {}))
