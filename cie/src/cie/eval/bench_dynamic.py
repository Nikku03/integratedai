"""Dynamic memory bank versus the static one, measured on the largest loaded
scale tenant.

Phase 0 (static): three question sets on the same documents, each arm measured:
  * learning questions (fee, penalty, notice),
  * the same questions re-worded (a bank that learnt from use should recognise them),
  * unseen questions about the same documents (signatory, liability, term).
Phase 1 (use): the learning questions are answered ``rounds`` times with dynamic
memory on; the bank wires the records that fire together, potentiates, decays and
prunes. Phase 2 (dynamic): the three sets measured again; the shapes the bank
formed are reported (dynamic links, simplices by dimension, cavities, examples).
Every dynamic link is then removed.

Arms: the standard REM expansion, the clique cascade with bonus, and a weak
reader (vector-only plus graph) to see whether learnt links let a poorer
retriever find what the stronger one found.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from cie.core.db import session_scope
from cie.core.settings import get_settings
from cie.eval.bench_scale import _p, short_name, supplier_name
from cie.eval.bench_topology import _questions_for, _tenant
from cie.governance.permissions import visible_scopes
from cie.memory.embeddings import get_embedding_provider
from cie.retrieval.pipeline import Retriever
from cie.topology import dynamic

ARMS = {"hybrid+graph(REM)": {"graph_mode": "rem"}, "hybrid+cliques+bonus": {"graph_mode": "cliques+bonus"},
        "weak reader: vector-only+graph": {"use_lexical": False, "use_exact": False, "graph_mode": "cliques+bonus"}}

REWORDED = {"fee": "How much does {short} charge per month?", "penalty": "What is the late payment percentage for {short}?",
            "notice": "How many days of notice does {short} need to end the deal?"}


def _reworded(docs: list[int]) -> list[dict[str, Any]]:
    out = []
    for d in docs:
        short = short_name(supplier_name(d))
        for kind, tpl in REWORDED.items():
            out.append({"q": tpl.format(short=short), "doc": d, "type": {"fee": "metric", "penalty": "metric", "notice": "deadline"}[kind], "kind": kind})
    return out


def _measure(s, retriever, admin, scope_id, questions, doc_ids, **cfg) -> dict[str, Any]:
    hits5 = hits20 = 0
    rr, lat = [], []
    for q in questions:
        t = time.perf_counter()
        res = retriever.retrieve(q["q"], admin, scope_id, **cfg)
        lat.append((time.perf_counter() - t) * 1000)
        target = str(doc_ids[q["doc"]])
        pos = next((i for i, it in enumerate(res.packet.items) if it.get("document_id") == target and it.get("type") == q["type"]), None)
        hits20 += pos is not None and pos < 20
        hits5 += pos is not None and pos < 5
        rr.append(1.0 / (pos + 1) if pos is not None else 0.0)
        s.rollback()
    return {"hit_at_5": round(hits5 / len(questions), 3), "hit_at_20": round(hits20 / len(questions), 3), "mrr": round(float(np.mean(rr)), 3),
            "p50_ms": _p(lat, 0.5), "p95_ms": _p(lat, 0.95)}


def run(out: Path, tenant_prefix: str = "scale-1000000-", n_docs: int = 40, rounds: int = 3, seed: int = 5) -> dict[str, Any]:
    settings = get_settings().model_copy(update={"dynamic_memory": True})
    embedder = get_embedding_provider(settings)
    rng = random.Random(seed + 41)
    report: dict[str, Any] = {"tenant_prefix": tenant_prefix, "documents": n_docs, "rounds": rounds}
    with session_scope() as s:
        tenant, company, dept0, admin, doc_ids = _tenant(s, tenant_prefix)
        docs = sorted(rng.sample(range(len(doc_ids)), n_docs))
        sets = {"learning": _questions_for(docs, ["fee", "penalty", "notice"]), "reworded": _reworded(docs),
                "unseen": _questions_for(docs, ["signed", "liability", "term"])}
        report["questions"] = {k: len(v) for k, v in sets.items()}
        retriever = Retriever(s, settings, embedder=embedder)
        vis = visible_scopes(s, admin)
        dynamic.reset(s, tenant.id, admin.id)
        s.commit()
        report["static"] = {arm: {name: _measure(s, retriever, admin, company.id, qs, doc_ids, **cfg) for name, qs in sets.items()} for arm, cfg in ARMS.items()}
        # phase 1: use
        t0 = time.perf_counter()
        wiring = {"formed": 0, "potentiated": 0, "pruned": 0, "answers": 0, "observe_ms": []}
        for _ in range(rounds):
            for q in sets["learning"]:
                t = time.perf_counter()
                result, res = retriever.answer(q["q"], admin, company.id)
                wiring["observe_ms"].append((time.perf_counter() - t) * 1000)
                d = res.trace.get("dynamic") or {}
                for k in ("formed", "potentiated", "pruned"):
                    wiring[k] += d.get(k, 0)
                wiring["answers"] += 1
                s.commit()
        report["use"] = {**{k: v for k, v in wiring.items() if k != "observe_ms"}, "answer_plus_wiring_ms_p50": _p(wiring["observe_ms"], 0.5),
                         "seconds": round(time.perf_counter() - t0, 1)}
        report["shapes"] = dynamic.shapes(s, tenant.id, vis, limit=5)
        report["dynamic"] = {arm: {name: _measure(s, retriever, admin, company.id, qs, doc_ids, **cfg) for name, qs in sets.items()} for arm, cfg in ARMS.items()}
        report["reset_removed"] = dynamic.reset(s, tenant.id, admin.id)
        s.commit()
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench_dynamic.json").write_text(json.dumps(report, indent=2, default=str))
    md = to_markdown(report)
    (out / "bench_dynamic.md").write_text(md)
    print(md)
    return report


def to_markdown(rep: dict[str, Any]) -> str:
    q = rep["questions"]
    lines = [f"### Dynamic memory bank vs static (largest loaded tenant; {rep['documents']} documents, {q['learning']} learning questions answered "
             f"{rep['rounds']} times, {q['reworded']} re-worded and {q['unseen']} unseen questions on the same documents)", "",
             "| arm | question set | hit@5 static → dynamic | hit@20 static → dynamic | MRR static → dynamic | p50 ms static → dynamic |", "|---|---|---|---|---|---|"]
    for arm in rep["static"]:
        for name in ("learning", "reworded", "unseen"):
            a, b = rep["static"][arm][name], rep["dynamic"][arm][name]
            lines.append(f"| {arm} | {name} | {a['hit_at_5']} → {b['hit_at_5']} | {a['hit_at_20']} → {b['hit_at_20']} | {a['mrr']} → {b['mrr']} | {a['p50_ms']} → {b['p50_ms']} |")
    u, sh = rep["use"], rep["shapes"]
    lines += ["", f"Use: {u['answers']} answers wired {u['formed']} new links, potentiated {u['potentiated']}, pruned {u['pruned']}; "
              f"answer + wiring p50 {u['answer_plus_wiring_ms_p50']} ms; {u['seconds']} s in total. Reset removed {rep['reset_removed']} links.", "",
              f"Shapes formed: {sh['dynamic_links']} dynamic links over {sh['records']} records; simplices by dimension {sh['simplices_by_dim']}; "
              f"highest dimension {sh['max_dim']}; cavities {sh['cavities']}; highest dynamic degree {sh['max_degree']}.", ""]
    for x in sh.get("shapes", [])[:3]:
        lines.append(f"* {x['dimension']}-simplex, strength {x['strength']}: sink **{x['sink']['type']}: {x['sink']['summary'][:70]}** ← "
                     + ", ".join(f"{m['type']}: {m['summary'][:40]}" for m in x["members"][:-1]))
    return "\n".join(lines)


def main(out: Path = Path("eval_out/dynamic"), **kw) -> dict:
    return run(out, **kw)


if __name__ == "__main__":  # pragma: no cover
    import sys

    main(Path("eval_out/dynamic"), **({"tenant_prefix": sys.argv[1]} if len(sys.argv) > 1 else {}))
