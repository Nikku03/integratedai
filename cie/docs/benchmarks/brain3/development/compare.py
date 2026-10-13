"""v16 against v17 on one work folder, in process: every question's answer, route and score under both. Writes
<out>/<name>.jsonl and prints the per-family scores and the changed answers."""
import json, sys, time
from collections import defaultdict
from pathlib import Path
from cie.factbank.brain import Brain, Router
from cie.eval import brain2_questions as Q2
from cie.eval.brain_test import plain_answer

L2 = Path("docs/benchmarks/brain2/lessons")
work, out, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
thr = float(sys.argv[4]) if len(sys.argv) > 4 else None
mk = lambda v17: Brain(work / "factbank_v2.sqlite", L2 / "single_lessons.json", L2 / "plan_lessons.json", Router.load(L2 / "router.json"),
                       v16=True, v17=v17, **({"described_below": thr} if thr is not None and v17 else {}))
b16, b17 = mk(False), mk(True)
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
    a, b = b16.ask(q["question"]), b17.ask(q["question"])
    rows.append({"id": q["id"], "family": q.get("family"), "kind": q.get("kind"), "q": q["question"][:160], "expected": str(q.get("expected"))[:80],
                 "v16": sc(q, a), "v17": sc(q, b), "r16": a["route"], "r17": b["route"], "a16": a["answer"][:80], "a17": b["answer"][:80],
                 "cov": next((j.get("coverage") for j in b["journal"] if j.get("op") == "described"), None)})
out.mkdir(parents=True, exist_ok=True)
(out / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
fam = defaultdict(lambda: [0, 0.0, 0.0])
for r in rows:
    f = fam[r["family"]]; f[0] += 1; f[1] += r["v16"] or 0; f[2] += r["v17"] or 0
print(f"== {name}: {len(rows)} questions, {time.time() - t:.0f} s; described route {sum(r['r17'] == 'described' for r in rows)}")
for f, v in sorted(fam.items(), key=lambda x: str(x[0])):
    print(f"  {f}: {v[0]}  v16 {v[1] / v[0]:.3f}  v17 {v[2] / v[0]:.3f}")
tot = [sum(r['v16'] or 0 for r in rows), sum(r['v17'] or 0 for r in rows)]
print(f"  all: v16 {tot[0] / len(rows):.3f}  v17 {tot[1] / len(rows):.3f}")
ch = [r for r in rows if (r["v16"] or 0) != (r["v17"] or 0)]
print(f"  changed scores {len(ch)}: better {sum((r['v17'] or 0) > (r['v16'] or 0) for r in ch)}, worse {sum((r['v17'] or 0) < (r['v16'] or 0) for r in ch)}")
