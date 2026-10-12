"""Post-hoc probe (not a result): where does plain BM25 rank the gold document?"""
import json, sys
from pathlib import Path
from cie.eval.brain_test import Passages

def run(work, label):
    work = Path(work)
    qs = [json.loads(l) for l in open(work / "questions.jsonl")]
    rep = json.load(open(work / "report.json"))
    v16 = {r["id"]: r["score"]["v16"] for r in rep["rows"]}
    ps = Passages(work)
    for fam_kind in ("descriptive", "prose"):
        sel = [q for q in qs if q["kind"] == fam_kind]
        top1 = top5 = 0
        lost_top1 = lost = 0
        for q in sel:
            gold = set(q.get("gold_docs") or [])
            docs = list(dict.fromkeys(h["dsid"] for h in ps.search(q["question"], 60)))
            t1 = bool(docs[:1]) and docs[0] in gold
            top1 += t1
            top5 += bool(gold & set(docs[:5]))
            if v16[q["id"]] < 0.5:
                lost += 1
                lost_top1 += t1
        print(f"{label} {fam_kind}: n={len(sel)} BM25 top-1 gold {top1} ({top1/len(sel):.2f}), top-5 {top5} ({top5/len(sel):.2f}); "
              f"v16 misses {lost}, of which BM25 top-1 is gold {lost_top1}")

for w, l in zip(sys.argv[1::2], sys.argv[2::2]):
    run(w, l)
