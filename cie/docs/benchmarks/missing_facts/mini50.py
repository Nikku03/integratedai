"""A 50-document memory bank, built in memory (no database). Which answer facts fail to reach what the model reads,
and where are they lost?

Documents: development-half questions (odd numbers), one of each question type in turn; a question's gold documents are
added while the set stays within 50 documents. Passages: the memory bank's own sections (cie.ingest.builder). Search per question, as
today's defaults do for passages: BM25 and vector search (bge-small) fused by RRF, then document expansion (the first 3
documents' 5 best BM25 passages placed after the document's first passage). The model reads passages in that order up
to 24,000 characters (each cut at 1,200, plus 120 characters of labels), as evidence_audit.model_view counts.
"""
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from cie.eval.evidence_audit import _stems, present_in_one
from cie.ingest.builder import build
from cie.ingest.sources import read
from cie.retrieval.bm25 import analyze, query_terms

HERE = Path(__file__).parent
ROOT = Path(os.environ.get("CIE_ERB_ROOT", "EnterpriseRAG-Bench"))
INDEX = os.environ.get("ERB_INDEX")
N_DOCS, VIEW, CUT = 50, 24000, 1200

qs = [json.loads(l) for l in open(ROOT / "questions.jsonl") if l.strip()]
dev = [q for q in qs if q["expected_doc_ids"] and int(q["question_id"][4:]) % 2 == 1]
docs: list[str] = []
chosen = []
# the questions file is ordered by type: take one question of each type in turn (id order within a type), adding its
# gold documents while the set stays within 50 documents
by_type = defaultdict(list)
for q in sorted(dev, key=lambda q: q["question_id"]):
    by_type[q["question_type"]].append(q)
queues = [list(v) for _, v in sorted(by_type.items())]
while any(queues) and len(docs) < N_DOCS:
    for qu in queues:
        while qu:
            q = qu.pop(0)
            new = [d for d in q["expected_doc_ids"] if d not in docs]
            if len(docs) + len(new) <= N_DOCS:
                docs += new
                chosen.append(q)
                break
index = json.load(open(INDEX))["index"]
mem = {}
for d in docs:
    m = build(read(ROOT / "generated_data" / "sources" / index[d], index[d]))
    mem[d] = m
units = []  # one per passage
for d in docs:
    for k, (title, stored, _emb) in enumerate(mem[d].sections):
        units.append({"id": f"{d}#{k}", "doc": d, "title": title or "", "text": stored or "", "source": mem[d].source})
print(f"{len(docs)} documents, {len(units)} passages, {sum(len(u['text']) for u in units):,} characters; {len(chosen)} questions")

# vector index
from cie.core.settings import get_settings
from cie.memory.embeddings import get_embedding_provider

emb = get_embedding_provider(get_settings())
vecs = emb.embed([f"{u['title']}\n{u['text']}"[:2000] for u in units])
import numpy as np

V = np.array([np.asarray(v, dtype=float) for v in vecs])
V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-9
toks = [analyze(f"{u['title']} {u['text']}") for u in units]
df = Counter(t for tk in toks for t in set(tk))
avg = sum(len(t) for t in toks) / len(toks)


def bm25(q, idx):
    qt = [t for t in query_terms(q) if len(t) > 1]
    n = len(units)
    out = []
    for i in idx:
        tf = Counter(toks[i])
        out.append(sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(toks[i]) / avg))
                       for t in qt if tf[t]))
    return out


rows = []
views = {}
for q in chosen:
    allidx = list(range(len(units)))
    b = bm25(q["question"], allidx)
    qv = np.asarray(emb.embed([q["question"]])[0], dtype=float)
    qv /= np.linalg.norm(qv) + 1e-9
    v = V @ qv
    rb = {i: r for r, i in enumerate(sorted(allidx, key=lambda i: -b[i])[:80])}
    rv = {i: r for r, i in enumerate(sorted(allidx, key=lambda i: -v[i])[:80])}
    fused = sorted(set(rb) | set(rv), key=lambda i: -(1 / (60 + rb[i]) if i in rb else 0) - (1 / (60 + rv[i]) if i in rv else 0))
    # document expansion: the first 3 documents' 5 best BM25 passages, right after the document's first passage
    first, out, placed = [], [], set()
    for i in fused:
        if units[i]["doc"] not in first:
            first.append(units[i]["doc"])
        if len(first) == 3:
            break
    for i in fused:
        if i in placed:
            continue
        out.append(i); placed.add(i)
        d = units[i]["doc"]
        if d in first[:3] and not any(units[j]["doc"] == d for j in out[:-1]):
            inner = [j for j in allidx if units[j]["doc"] == d]
            for j in sorted(inner, key=lambda j: -b[j])[:5]:
                if j not in placed:
                    out.append(j); placed.add(j)
    view, used = [], 0
    for i in out:
        body = f"{units[i]['title']}\n{units[i]['text'][:CUT]}"
        size = min(len(body), 1500) + 120
        if view and used + size > VIEW:
            break
        view.append(i); used += size
    vtexts = [(f"{units[i]['title']}\n{units[i]['text'][:CUT]}", None) for i in view]
    vtexts = [(t, _stems(t)) for t, _ in vtexts]
    view_docs = [units[i]["doc"] for i in view]
    views[q["question_id"]] = {"view": [units[i]["id"] for i in view], "chars": used}
    rank_of = {i: r for r, i in enumerate(out)}
    gold = q["expected_doc_ids"]
    for fi, f in enumerate(q["answer_facts"]):
        if f.lower().startswith("the answer must not"):
            continue
        holders = [i for i in allidx if units[i]["doc"] in gold and present_in_one(f, [(units[i]["title"] + "\n" + units[i]["text"], _stems(units[i]["title"] + "\n" + units[i]["text"]))])]
        if not holders:
            where, reached = "not checkable (worded differently from the documents)", None
        elif present_in_one(f, vtexts):
            where, reached = "reached the model", True
        else:
            reached = False
            hd = {units[i]["doc"] for i in holders}
            best = min(rank_of.get(i, 10**6) for i in holders)
            if not hd & set(view_docs):
                where = "its document never reached the model"
            elif any(i in view and units[i]["text"][CUT:] and present_in_one(f, [(units[i]["text"], _stems(units[i]["text"]))]) for i in holders):
                where = "its passage reached the model but was cut at 1,200 characters"
            else:
                where = "its document reached the model, but not the passage that holds it"
        rows.append({"fid": f"{q['question_id']}.F{fi + 1}", "question_id": q["question_id"], "question": q["question"],
                     "question_type": q["question_type"], "gold_documents": len(gold), "fact": f, "reached": reached, "where": where,
                     "holder_sources": sorted({units[i]["source"] for i in holders}),
                     "holder_rank": (min(rank_of.get(i, 10**6) for i in holders) if holders else None),
                     "has_number": bool(re.search(r"\d", f)), "words": len(re.findall(r"[A-Za-z0-9]+", f))})
json.dump({"documents": docs, "questions": [q["question_id"] for q in chosen], "passages": len(units), "views": views,
           "gold_passages": {q["question_id"]: [{"id": u["id"], "text": f"{u['title']}\n{u['text']}"} for u in units if u["doc"] in q["expected_doc_ids"]]
                             for q in chosen}}, open(HERE / "mini50_set_full.json", "w"), indent=1)
with open(HERE / "mini50_rows.jsonl", "w") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
c = Counter(r["where"] for r in rows)
print(len(rows), "facts:", dict(c))
