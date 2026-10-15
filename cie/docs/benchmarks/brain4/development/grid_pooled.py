"""The quote's title weighting, pooled over the four development sets: free text with title words weighed down (TITLE_DOWN
True) and not, at DESC_WEIGHT 0.3 and KIND_BONUS 0.3, v16's abstention kept. Prints each set and the pool."""
import json, sys
from pathlib import Path
from cie.factbank.brain import Brain, Router
from cie.factbank import prose as P
from cie.eval import brain2_questions as Q2
L2 = Path("docs/benchmarks/brain2/lessons")
pool = {True: [0.0, 0], False: [0.0, 0]}
for w in sys.argv[1:]:
    work = Path(w)
    b = Brain(work / "factbank_v2.sqlite", L2 / "single_lessons.json", L2 / "plan_lessons.json", Router.load(L2 / "router.json"), v18=True)
    tq = [(q, b.tidy(q["question"])) for q in map(json.loads, open(work / "questions.jsonl")) if q.get("family") == "prose"]
    for td in (True, False):
        P.TITLE_DOWN = td
        tot = sum(Q2.score(q, {"answer": b.prose_row(qq)[0], "route": "prose"}) for q, qq in tq)
        pool[td][0] += tot; pool[td][1] += len(tq)
        print(f"{work.parent.name}/{work.name}: {len(tq)} free-text questions, title_down {td}: {tot / len(tq):.3f}", flush=True)
for td, (t, n) in pool.items():
    print(f"pooled, title_down {td}: {t / n:.3f} over {n}")
