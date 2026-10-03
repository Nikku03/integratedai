"""Development half only (odd question numbers). Take the first D documents of today's evidence packet, split every
section of those documents into sentences, score each sentence with BM25 against the question (statistics over the
sentences of those D documents), and keep the best sentences (plus the next one) up to E characters. Does putting
those extracts in what the model reads bring more answer facts to the model?

Scoring:
  forward: the question is the query, each sentence a document (BM25, k1 1.2, b 0.75; length-normalised)
  reverse: each sentence is the query, the question the document: the sum of the IDF of the question terms the
           sentence holds (no length penalty)
"""
import json
import os
import math
import re
import sys
import time
from collections import Counter, defaultdict

from sqlalchemy import select, text

from cie.core.db import session_scope
from cie.core.models import Document, Principal, Section, Tenant
from cie.core.settings import get_settings
from cie.eval.evidence_audit import _stems, model_view, present_in_one
from cie.memory.embeddings import get_embedding_provider
from cie.retrieval.bm25 import analyze, query_terms
from cie.retrieval.pipeline import Retriever

ROOT = os.environ.get("CIE_ERB_ROOT", "EnterpriseRAG-Bench")
HALF = sys.argv[1] if len(sys.argv) > 1 else "odd"
OUT = sys.argv[2] if len(sys.argv) > 2 else f"eval_out/inside_bm25_{HALF}.json"
qs = [json.loads(l) for l in open(f"{ROOT}/questions.jsonl") if l.strip()]
qs = [q for q in qs if q["expected_doc_ids"] and (int(q["question_id"][4:]) % 2 == 1) == (HALF == "odd")]
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+")
VIEW = 24000


def sentences(sec_text):
    return [x.strip() for x in SENT.split(re.sub(r"[ \t]+", " ", sec_text or "")) if len(x.strip()) >= 3]


def score_sentences(sents, qterms, how):
    toks = [analyze(x) for x in sents]
    n = len(sents)
    df = Counter(t for tk in toks for t in set(tk))
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in qterms}
    avg = (sum(len(tk) for tk in toks) / n) if n else 1
    out = []
    for tk in toks:
        tf = Counter(tk)
        if how == "forward":
            sc = sum(idf[t] * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(tk) / avg)) for t in qterms if tf[t])
        else:
            sc = sum(idf[t] for t in qterms if tf[t])
        out.append(sc)
    return out


def extracts(docs, secs_of, title_of, qterms, how, budget, after=1, before=0):
    """Passages of at most 1,500 characters, built from each document's best sentences in document order."""
    flat = []  # (doc, section index, sentence index, text)
    for d in docs:
        for si, st in enumerate(secs_of[d]):
            for j, x in enumerate(sentences(st)):
                flat.append((d, si, j, x))
    if not flat:
        return []
    sc = score_sentences([f[3] for f in flat], qterms, how)
    pos = {(f[0], f[1], f[2]): k for k, f in enumerate(flat)}
    chosen, used = set(), 0
    for k in sorted(range(len(flat)), key=lambda k: -sc[k]):
        if sc[k] <= 0:
            break
        d, si, j, _ = flat[k]
        for jj in range(j - before, j + after + 1):
            kk = pos.get((d, si, jj))
            if kk is None or kk in chosen:
                continue
            cost = len(flat[kk][3]) + 1
            if used + cost > budget:
                continue
            chosen.add(kk)
            used += cost
        if used >= budget * 0.97:
            break
    out = []
    for d in docs:
        ks = sorted(k for k in chosen if flat[k][0] == d)
        if not ks:
            continue
        # contiguous runs within a section are one span; spans are joined in document order, cut into passages
        spans, cur, prev = [], [], None
        for k in ks:
            if prev is not None and (flat[k][1] != flat[prev][1] or k != prev + 1):
                spans.append(" ".join(flat[i][3] for i in cur)); cur = []
            cur.append(k); prev = k
        spans.append(" ".join(flat[i][3] for i in cur))
        buf = ""
        for sp in spans:
            while len(sp) > 1500:
                if buf:
                    out.append({"summary": title_of[d], "detail": buf}); buf = ""
                out.append({"summary": title_of[d], "detail": sp[:1500]}); sp = sp[1500:]
            if buf and len(buf) + len(sp) + 3 > 1500:
                out.append({"summary": title_of[d], "detail": buf}); buf = ""
            buf = f"{buf} … {sp}" if buf else sp
        if buf:
            out.append({"summary": title_of[d], "detail": buf})
    return out


def view_chars(items, budget):
    used, n = 0, 0
    for it in items:
        body = f"{it.get('summary', '')}\n{it.get('detail', '')}"
        size = min(len(body), 1500) + 120
        if budget and n and used + size > budget:
            break
        used += size; n += 1
    return used


st = get_settings()
arms = defaultdict(lambda: {"reached": 0, "facts": 0, "chars": 0})
upper = defaultdict(lambda: {"reached": 0, "facts": 0})
judged = checkable = 0
gold_rank = Counter()
times = []
with session_scope() as s:
    t = s.scalar(select(Tenant).where(Tenant.name == "erbfull-5000-9688c2"))
    admin = s.scalar(select(Principal).where(Principal.tenant_id == t.id, Principal.name == "admin"))
    company = s.scalar(select(text("id")).select_from(text("scopes")).where(text("tenant_id = :t AND parent_id IS NULL")).params(t=t.id))
    doc_of, dsid_of, title_of = {}, {}, {}
    for i, e, ti in s.execute(select(Document.id, Document.extra, Document.title).where(Document.tenant_id == t.id)):
        doc_of[e.get("dsid")] = i; dsid_of[str(i)] = e.get("dsid"); title_of[str(i)] = ti or ""
    r = Retriever(s, st, embedder=get_embedding_provider(st))
    for qi, q in enumerate(qs):
        gold_ids = [doc_of[g] for g in q["expected_doc_ids"] if g in doc_of]
        gold = [(x or "", _stems(x or "")) for x in s.scalars(select(Section.text).where(Section.document_id.in_(gold_ids)))] if gold_ids else []
        facts = [f for f in q["answer_facts"] if present_in_one(f, gold)]
        if not facts:
            continue
        judged += 1; checkable += len(facts)
        qterms = [x for x in query_terms(q["question"]) if len(x) > 2]
        items = r.retrieve(q["question"], admin, company).packet.items
        s.rollback()
        docs = []
        for it in items:
            d = it.get("document_id")
            if d and d not in docs:
                docs.append(d)
        gset = {str(g) for g in gold_ids}
        first = next((k for k, d in enumerate(docs) if d in gset), None)
        gold_rank[first if first is None or first < 10 else "10+"] += 1
        t0 = time.perf_counter()
        top = docs[:5]
        secs_of = defaultdict(list)
        for d, x in s.execute(select(Section.document_id, Section.text).where(Section.document_id.in_(top)).order_by(Section.document_id, Section.order_index)):
            secs_of[str(d)].append(x or "")
        fetch_ms = (time.perf_counter() - t0) * 1000
        # upper bound: facts anywhere in the first D documents (one section at a time)
        for D in (3, 5):
            pool = [(x, _stems(x)) for d in docs[:D] for x in secs_of[d]]
            n = sum(1 for f in facts if present_in_one(f, pool))
            upper[f"facts anywhere in the first {D} documents"]["facts"] += n
            upper[f"facts anywhere in the first {D} documents"]["reached"] += int(n == len(facts))

        def score(name, passages_items, budget):
            v = model_view(passages_items, budget)
            vv = [(p, _stems(p)) for p in v]
            n = sum(1 for f in facts if present_in_one(f, vv))
            a = arms[name]; a["facts"] += n; a["reached"] += int(n == len(facts)); a["chars"] += view_chars(passages_items, budget)

        score("today (24k)", items, VIEW)
        for D in (3, 5):
            for how in ("forward", "reverse"):
                for E in (3000, 6000, 12000):
                    t1 = time.perf_counter()
                    ex = extracts(docs[:D], secs_of, title_of, qterms, how, E)
                    if D == 5 and how == "reverse" and E == 6000:
                        times.append(fetch_ms + (time.perf_counter() - t1) * 1000)
                    score(f"{D} docs, {how}, extracts only ({E // 1000}k)", ex, None)
                    score(f"{D} docs, {how}, {E // 1000}k extracts then today's items (24k)", ex + items, VIEW)
        if (qi + 1) % 50 == 0:
            print(f"  {qi + 1}/{len(qs)}", flush=True)

report = {"half": HALF, "judged": judged, "checkable_facts": checkable, "view_chars": VIEW,
          "first_gold_document_position": {str(k): v for k, v in sorted(gold_rank.items(), key=lambda kv: (kv[0] is None, str(kv[0])))},
          "extraction_ms_p50": sorted(times)[len(times) // 2] if times else None,
          "extraction_ms_p95": sorted(times)[int(len(times) * 0.95)] if times else None,
          "upper_bounds": dict(upper),
          "arms": {k: {**v, "chars_mean": round(v["chars"] / judged)} for k, v in arms.items()}}
json.dump(report, open(OUT, "w"), indent=1)
print(f"{HALF} half: {judged} judged questions, {checkable} checkable facts")
for k, v in upper.items():
    print(f"  {k:62s} every fact {v['reached']:3d} ({v['reached'] / judged:.0%})  facts {v['facts']}")
for k, v in arms.items():
    print(f"  {k:62s} every fact {v['reached']:3d} ({v['reached'] / judged:.0%})  facts {v['facts']:3d}  chars read {v['chars'] / judged:,.0f}")
print("first gold document position:", report["first_gold_document_position"])
print("extraction ms p50/p95:", report["extraction_ms_p50"], report["extraction_ms_p95"])
