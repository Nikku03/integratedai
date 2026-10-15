"""v17 against v18 on one work folder, in process: every question's answer, route and score under both. Writes
<out>/<name>.jsonl and prints the per-family scores and the changed answers. Round 4's development script
(docs/FACTBANK_BRAIN4_PREREGISTRATION.md); round 3's, docs/benchmarks/brain3/development/compare.py, compared v16 with v17.

    PYTHONHASHSEED=0 PYTHONPATH=src python docs/benchmarks/brain4/development/compare.py WORK OUT NAME"""
import json, sys, time
from collections import defaultdict
from pathlib import Path
from cie.factbank.brain import Brain, Router
from cie.eval import brain2_questions as Q2
from cie.eval.brain_test import plain_answer

L2 = Path("docs/benchmarks/brain2/lessons")
work, out, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
mk = lambda v18: Brain(work / "factbank_v2.sqlite", L2 / "single_lessons.json", L2 / "plan_lessons.json", Router.load(L2 / "router.json"),
                       v16=True, v17=True, v18=v18)
b17, b18 = mk(False), mk(True)


def sc(q, a):
    try:
        return Q2.score(q, a)
    except Exception:
        from cie.eval import brain_questions as B
        return B.score(q, plain_answer(a["answer"]))


rows = []
t = time.time()
for line in open(work / "questions.jsonl"):
    q = json.loads(line)
    a, b = b17.ask(q["question"]), b18.ask(q["question"])
    rows.append({"id": q["id"], "family": q.get("family") or Q2.family(q), "kind": q.get("kind"), "q": q["question"][:200],
                 "expected": str(q.get("expected"))[:120], "v17": sc(q, a), "v18": sc(q, b), "r17": a["route"], "r18": b["route"],
                 "a17": a["answer"][:300], "a18": b["answer"][:300], "why18": b["reason"][:200], "ms17": a["ms"], "ms18": b["ms"]})
out.mkdir(parents=True, exist_ok=True)
(out / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
fam = defaultdict(lambda: [0, 0.0, 0.0])
for r in rows:
    f = fam[r["family"]]; f[0] += 1; f[1] += r["v17"] or 0; f[2] += r["v18"] or 0
print(f"== {name}: {len(rows)} questions, {time.time() - t:.0f} s")
for f, v in sorted(fam.items(), key=lambda x: str(x[0])):
    print(f"  {f}: {v[0]}  v17 {v[1] / v[0]:.3f}  v18 {v[2] / v[0]:.3f}")
tot = [sum(r['v17'] or 0 for r in rows), sum(r['v18'] or 0 for r in rows)]
print(f"  all: v17 {tot[0] / len(rows):.3f}  v18 {tot[1] / len(rows):.3f}")
ch = [r for r in rows if (r["v17"] or 0) != (r["v18"] or 0)]
print(f"  changed scores {len(ch)}: better {sum((r['v18'] or 0) > (r['v17'] or 0) for r in ch)}, worse {sum((r['v18'] or 0) < (r['v17'] or 0) for r in ch)}")
