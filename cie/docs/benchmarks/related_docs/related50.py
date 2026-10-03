"""Related documents on the 50-document set (plan: README.md in this folder).

Same documents, questions and passages as ../missing_facts/ (built in memory, no database). Writes results.json here.
    CIE_ERB_ROOT=<EnterpriseRAG-Bench> ERB_INDEX=<index.json> python related50.py
"""
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from cie.eval.evidence_audit import _stems, present_in_one
from cie.ingest.builder import build
from cie.ingest.sources import read
from cie.retrieval.bm25 import analyze, query_terms

HERE = Path(__file__).parent
ROOT = Path(os.environ.get("CIE_ERB_ROOT", "EnterpriseRAG-Bench"))
INDEX = os.environ.get("ERB_INDEX")
N_DOCS, CUT, BUDGETS = 50, 1200, (6000, 12000, 24000)
K_NEIGHBOURS, SEEDS, PER_SEED, PER_NEIGHBOUR, NEXT_FOR = 3, 3, 2, 3, 8
MAX_DF_SHARE = 0.2

# ------------------------------------------------------------------ the set (as ../missing_facts/mini50.py)
qs = [json.loads(l) for l in open(ROOT / "questions.jsonl") if l.strip()]
dev = [q for q in qs if q["expected_doc_ids"] and int(q["question_id"][4:]) % 2 == 1]
docs, chosen = [], []
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
ref = json.load(open(HERE.parent / "missing_facts" / "set.json"))
assert docs == ref["documents"] and [q["question_id"] for q in chosen] == ref["questions"], "not the missing_facts set"
index = json.load(open(INDEX))["index"]
mem = {d: build(read(ROOT / "generated_data" / "sources" / index[d], index[d])) for d in docs}
units, of_doc = [], defaultdict(list)
for d in docs:
    for k, (title, stored, _e) in enumerate(mem[d].sections):
        of_doc[d].append(len(units))
        units.append({"id": f"{d}#{k}", "doc": d, "k": k, "title": title or "", "text": stored or ""})
uid = {u["id"]: i for i, u in enumerate(units)}

from cie.core.settings import get_settings
from cie.memory.embeddings import get_embedding_provider

emb = get_embedding_provider(get_settings())
V = np.array([np.asarray(v, dtype=float) for v in emb.embed([f"{u['title']}\n{u['text']}"[:2000] for u in units])])
V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-9
toks = [analyze(f"{u['title']} {u['text']}") for u in units]
df = Counter(t for tk in toks for t in set(tk))
avg = sum(len(t) for t in toks) / len(toks)


def bm25(q, idx):
    qt = [t for t in query_terms(q) if len(t) > 1]
    n = len(units)
    return {i: sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * Counter(toks[i])[t] * 2.2
                   / (Counter(toks[i])[t] + 1.2 * (0.25 + 0.75 * len(toks[i]) / avg)) for t in qt if t in toks[i]) for i in idx}


def rrf(*rankings):
    s = defaultdict(float)
    for r in rankings:
        for pos, i in enumerate(r):
            s[i] += 1 / (60 + pos)
    return sorted(s, key=lambda i: -s[i])


# ------------------------------------------------------------------ load time: neighbours
t0 = time.perf_counter()
D = np.array([V[of_doc[d]].mean(axis=0) for d in docs])
D /= np.linalg.norm(D, axis=1, keepdims=True) + 1e-9
cos = D @ D.T
IDENT = [re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b"), re.compile(r"\b[a-z][a-z0-9]*(?:[_.][a-z0-9]+)+\b"),
         re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b"), re.compile(r"https?://\S+")]


def keys_of(d):
    m = mem[d]
    out = {("person", n.lower()) for n, _ in m.people} | {("org", o.lower()) for o in m.orgs}
    if m.project:
        out.add(("project", m.project.lower()))
    body = " ".join(units[i]["text"] for i in of_doc[d])
    for rx in IDENT:
        out |= {("id", x.lower().rstrip(".,)")) for x in rx.findall(body) if len(x) >= 6}
    return out


keys = {d: keys_of(d) for d in docs}
kdf = Counter(k for d in docs for k in keys[d])
usable = {k for k, c in kdf.items() if 2 <= c <= MAX_DF_SHARE * len(docs)}
name_score = {(a, b): sum(math.log(len(docs) / kdf[k]) for k in (keys[a] & keys[b]) & usable) for a in docs for b in docs if a != b}
neighbours = {"content": {}, "names": {}, "both": {}}
for i, a in enumerate(docs):
    by_cos = [docs[j] for j in np.argsort(-cos[i]) if docs[j] != a]
    by_names = [b for b in sorted((b for b in docs if b != a), key=lambda b: -name_score[(a, b)]) if name_score[(a, b)] > 0]
    neighbours["content"][a] = by_cos[:K_NEIGHBOURS]
    neighbours["names"][a] = by_names[:K_NEIGHBOURS]
    neighbours["both"][a] = rrf(by_cos[:20], by_names[:20])[:K_NEIGHBOURS]
load_ms = (time.perf_counter() - t0) * 1000

# neighbour quality: links that join two gold documents of one question
pairs = {frozenset((a, b)) for q in chosen for a in q["expected_doc_ids"] for b in q["expected_doc_ids"] if a != b}
quality = {}
for sig, nb in neighbours.items():
    links = [(a, b) for a in docs for b in nb[a]]
    quality[sig] = {"links": len(links), "join_two_gold_documents_of_a_question": sum(frozenset(l) in pairs for l in links),
                    "gold_pairs": len(pairs), "gold_pairs_linked": sum(1 for p in pairs if any(frozenset((a, b)) == p for a, b in links))}


# ------------------------------------------------------------------ question time
def best_in_doc(d, b, qv, n):
    idx = of_doc[d]
    return rrf(sorted(idx, key=lambda i: -b[i]), sorted(idx, key=lambda i: -float(V[i] @ qv)))[:n]


def order(q, related=None, next_passage=False):
    allidx = list(range(len(units)))
    b = bm25(q["question"], allidx)
    qv = np.asarray(emb.embed([q["question"]])[0], dtype=float)
    qv /= np.linalg.norm(qv) + 1e-9
    v = V @ qv
    fused = rrf(sorted(allidx, key=lambda i: -b[i])[:80], sorted(allidx, key=lambda i: -v[i])[:80])
    first = []
    for i in fused:
        if units[i]["doc"] not in first:
            first.append(units[i]["doc"])
        if len(first) == SEEDS:
            break
    out, placed = [], set()

    def add(j):
        if j not in placed:
            out.append(j)
            placed.add(j)

    t = time.perf_counter()
    for i in fused:
        if i in placed:
            continue
        d = units[i]["doc"]
        is_first = not any(units[j]["doc"] == d for j in out)
        add(i)
        if d in first and is_first:
            for j in sorted(of_doc[d], key=lambda j: -b[j])[:5]:  # document expansion (today)
                add(j)
            if related:
                for nb in related[d][:PER_SEED]:
                    for j in best_in_doc(nb, b, qv, PER_NEIGHBOUR):
                        add(j)
    if next_passage:
        new, seen = [], set()
        for pos, i in enumerate(out):
            if i in seen:
                continue
            new.append(i); seen.add(i)
            nxt = uid.get(f"{units[i]['doc']}#{units[i]['k'] + 1}")
            if pos < NEXT_FOR and nxt is not None and nxt not in seen:
                new.append(nxt); seen.add(nxt)
        out = new
    return out, (time.perf_counter() - t) * 1000


def view(out, budget):
    sel, used = [], 0
    for i in out:
        size = min(len(units[i]["title"]) + 1 + len(units[i]["text"][:CUT]), 1500) + 120
        if sel and used + size > budget:
            break
        sel.append(i); used += size
    return sel, used


facts = json.load(open(HERE.parent / "missing_facts" / "facts.json"))
findable = [f for f in facts if f["reached"] is not None or (f["judge"] or {}).get("status") in ("one_passage", "several_passages")]
by_q = defaultdict(list)
for f in findable:
    by_q[f["question_id"]].append(f)
ARMS = {"today": {}, "related: similar content": {"related": neighbours["content"]},
        "related: shared names and identifiers": {"related": neighbours["names"]}, "related: both": {"related": neighbours["both"]},
        "today + next passage": {"next_passage": True}, "related: both + next passage": {"related": neighbours["both"], "next_passage": True}}
res = {}
for arm, kw in ARMS.items():
    for budget in BUDGETS:
        r = res[f"{arm} @ {budget}"] = {"facts": 0, "reached": 0, "questions_every_fact": 0, "gold_recall": [], "gold_recall_multi": [],
                                        "chars": 0, "extra_ms": []}
        for q in chosen:
            out, ms = order(q, **kw)
            sel, used = view(out, budget)
            ids = {units[i]["id"] for i in sel}
            texts = [(f"{units[i]['title']}\n{units[i]['text'][:CUT]}", None) for i in sel]
            texts = [(t, _stems(t)) for t, _ in texts]
            n = 0
            for f in by_q[q["question_id"]]:
                if f["reached"] is not None:
                    n += present_in_one(f["fact"], texts)
                else:
                    n += set(f["judge"]["passages"]) <= ids
            r["facts"] += len(by_q[q["question_id"]]); r["reached"] += n
            r["questions_every_fact"] += int(n == len(by_q[q["question_id"]]))
            g = q["expected_doc_ids"]
            rec = len({units[i]["doc"] for i in sel} & set(g)) / len(g)
            r["gold_recall"].append(rec)
            if len(g) > 1:
                r["gold_recall_multi"].append(rec)
            r["chars"] += used; r["extra_ms"].append(ms)
        r["gold_recall"] = round(sum(r["gold_recall"]) / len(r["gold_recall"]), 3)
        r["gold_recall_multi"] = round(sum(r["gold_recall_multi"]) / len(r["gold_recall_multi"]), 3)
        r["chars"] = round(r["chars"] / len(chosen))
        r["extra_ms"] = round(sorted(r["extra_ms"])[len(chosen) // 2], 1)
json.dump({"questions": len(chosen), "multi_document_questions": sum(len(q["expected_doc_ids"]) > 1 for q in chosen),
           "findable_facts": len(findable), "neighbour_build_ms": round(load_ms), "neighbour_quality": quality,
           "neighbours": {s: {a: v for a, v in nb.items()} for s, nb in neighbours.items()}, "arms": res},
          open(HERE / "results.json", "w"), indent=1)
print(f"{len(chosen)} questions, {len(findable)} findable facts; neighbours built in {load_ms:.0f} ms")
for s, qq in quality.items():
    print(f"  neighbours by {s:8s}: {qq['join_two_gold_documents_of_a_question']} of {qq['links']} links join two gold documents of a question; "
          f"{qq['gold_pairs_linked']} of {qq['gold_pairs']} gold pairs linked")
for k, r in res.items():
    print(f"{k:48s} facts {r['reached']:3d}/{r['facts']}  every fact {r['questions_every_fact']:2d}/26  gold recall {r['gold_recall']:.2f} "
          f"(multi-doc {r['gold_recall_multi']:.2f})  chars {r['chars']:,}  ordering ms p50 {r['extra_ms']}")
