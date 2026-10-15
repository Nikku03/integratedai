"""Fit v18's quote weights on training documents only: free-text score on train5k's 111 prose questions for each
(DESC_WEIGHT, KIND_BONUS); the abstention is v16's, unchanged."""
import json, sys, itertools
from pathlib import Path
from cie.factbank.brain import Brain, Router
from cie.factbank import prose as P
from cie.eval import brain2_questions as Q2
L2 = Path("docs/benchmarks/brain2/lessons")
work = Path(sys.argv[1])
b = Brain(work / "factbank_v2.sqlite", L2 / "single_lessons.json", L2 / "plan_lessons.json", Router.load(L2 / "router.json"), v18=True)
qs = [q for q in map(json.loads, open(work / "questions.jsonl")) if q.get("family") == "prose"]
tq = [(q, b.tidy(q["question"])) for q in qs]
for dw, kb, td in itertools.product((0.15, 0.3, 0.5, 1.0), (0.0, 0.15, 0.3, 0.5), (True, False)):
    P.DESC_WEIGHT, P.KIND_BONUS, P.TITLE_DOWN = dw, kb, td
    tot = sum(Q2.score(q, {"answer": b.prose_row(qq)[0], "route": "prose"}) for q, qq in tq)
    print(f"desc {dw} kind {kb} title_down {td}: {tot / len(tq):.3f}", flush=True)
