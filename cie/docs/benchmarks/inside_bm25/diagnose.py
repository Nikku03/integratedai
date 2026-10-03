"""Development half. For every answer fact today's model view misses: where is it, and how does in-document BM25 rank
the sentence that holds it?"""
import json
import math
import os
import re
from collections import Counter, defaultdict

from sqlalchemy import select, text

from cie.core.db import session_scope
from cie.core.models import Document, Principal, Section, Tenant
from cie.core.settings import get_settings
from cie.eval.evidence_audit import _stems, model_view, present, present_in_one
from cie.memory.embeddings import get_embedding_provider
from cie.retrieval.bm25 import analyze, query_terms
from cie.retrieval.pipeline import Retriever

ROOT = os.environ.get("CIE_ERB_ROOT", "EnterpriseRAG-Bench")
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+")


def sentences(t):
    return [x.strip() for x in SENT.split(re.sub(r"[ \t]+", " ", t or "")) if len(x.strip()) >= 3]


qs = [json.loads(l) for l in open(f"{ROOT}/questions.jsonl") if l.strip()]
qs = [q for q in qs if q["expected_doc_ids"] and int(q["question_id"][4:]) % 2 == 1]
st = get_settings()
where = Counter()
sent_rank = Counter()
shares = Counter()
cats = Counter()
out_types = Counter()
out_ngold = Counter()
qs_gold = Counter()
examples = []
in_view = in5 = both = only_view = only5 = 0
with session_scope() as s:
    t = s.scalar(select(Tenant).where(Tenant.name == "erbfull-5000-9688c2"))
    admin = s.scalar(select(Principal).where(Principal.tenant_id == t.id, Principal.name == "admin"))
    company = s.scalar(select(text("id")).select_from(text("scopes")).where(text("tenant_id = :t AND parent_id IS NULL")).params(t=t.id))
    doc_of = {e.get("dsid"): i for i, e in s.execute(select(Document.id, Document.extra).where(Document.tenant_id == t.id))}
    r = Retriever(s, st, embedder=get_embedding_provider(st))
    for q in qs:
        gold_ids = [doc_of[g] for g in q["expected_doc_ids"] if g in doc_of]
        gold = [(x or "", _stems(x or "")) for x in s.scalars(select(Section.text).where(Section.document_id.in_(gold_ids)))] if gold_ids else []
        facts = [f for f in q["answer_facts"] if present_in_one(f, gold)]
        if not facts:
            continue
        items = r.retrieve(q["question"], admin, company).packet.items
        s.rollback()
        docs = []
        for it in items:
            d = it.get("document_id")
            if d and d not in docs:
                docs.append(d)
        view = [(p, _stems(p)) for p in model_view(items, 24000)]
        secs = defaultdict(list)
        for d, x in s.execute(select(Section.document_id, Section.text).where(Section.document_id.in_(docs[:5])).order_by(Section.document_id, Section.order_index)):
            secs[str(d)].append(x or "")
        pool5 = [(x, _stems(x)) for d in docs[:5] for x in secs[d]]
        gset = {str(g) for g in gold_ids}
        # sentence pool for BM25 ranks
        flat = [x for d in docs[:5] for sec in secs[d] for x in sentences(sec)]
        toks = [analyze(x) for x in flat]
        qterms = [x for x in query_terms(q["question"]) if len(x) > 2]
        n = len(flat)
        df = Counter(tt for tk in toks for tt in set(tk))
        idf = {tt: math.log(1 + (n - df[tt] + 0.5) / (df[tt] + 0.5)) for tt in qterms}
        sc = [sum(idf[tt] for tt in qterms if tt in set(tk)) for tk in toks]
        order = sorted(range(n), key=lambda k: -sc[k])
        rank_of = {k: i for i, k in enumerate(order)}
        for f in facts:
            a = present_in_one(f, view)
            b = present_in_one(f, pool5)
            in_view += a; in5 += b; both += a and b; only_view += a and not b; only5 += b and not a
            if a:
                continue
            if b:
                where["in the first 5 documents, missed by today's view"] += 1
                # the best-ranked sentence (with its next one) holding the fact
                best = None
                for k in range(n):
                    win = flat[k] + " " + (flat[k + 1] if k + 1 < n else "")
                    if present(f, win):
                        rr = min(rank_of[k], rank_of.get(k + 1, 10**9) if k + 1 < n else 10**9)
                        best = rr if best is None else min(best, rr)
                if best is None:
                    sent_rank["fact spans more than two sentences"] += 1
                else:
                    sent_rank["top 10" if best < 10 else "11-30" if best < 30 else "31-100" if best < 100 else "over 100"] += 1
                    if best >= 30 and len(examples) < 6:
                        examples.append({"q": q["question"], "fact": f, "sentence_rank": best, "pool_sentences": n})
                cats[q["question_type"]] += 1
            else:
                g_pos = [k for k, d in enumerate(docs) if d in gset]
                if not g_pos:
                    where["gold document not in the packet"] += 1
                elif min(g_pos) >= 5 or not any(present_in_one(f, [(x, _stems(x)) for x in secs.get(docs[k], [])]) for k in g_pos if k < 5):
                    where["in a gold document ranked 6th or lower"] += 1
                    out_types[q["question_type"]] += 1
                    out_ngold[len(q["expected_doc_ids"]) if len(q["expected_doc_ids"]) < 5 else "5+"] += 1
                else:
                    where["other"] += 1
print("facts: in today's view", in_view, "| anywhere in first 5 docs", in5, "| both", both, "| only today's view", only_view, "| only the 5 docs", only5)
print("missed facts by where they are:", dict(where))
print("rank of the best sentence holding a missed fact (in-document BM25, of the 5 documents' sentences):", dict(sent_rank))
print("question types of missed-but-present facts:", dict(cats))
print("facts outside the first 5 documents, by question type:", dict(out_types))
print("... by number of gold documents of the question:", dict(out_ngold))
for e in examples:
    print(json.dumps(e)[:400])
