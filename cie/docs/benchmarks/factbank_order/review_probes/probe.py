"""Ask v11 and v13 a list of (set, question, expected) and show answers, scores and plans."""
import json, sys
from pathlib import Path
from cie.factbank import plans
from cie.factbank.learn import Lessons
from cie.factbank.trained import TrainedBank
from cie.eval.memory_test import _jsonl
from cie.eval.factbank_multi import own_score
S = Path("/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad")
L11 = plans.PlanLessons.load(S / "mdtrain/plan_lessons_v11.json")
L13 = plans.PlanLessons.load(S / "mdtrain/plan_lessons_v13.json")
_banks = {}
def bank(work):
    if work not in _banks:
        tb = TrainedBank(S / work / "factbank_v2.sqlite", Lessons.load(S / "fb50/lessons.json"))
        _banks[work] = (tb, L11.planner(tb), L13.planner(tb))
    return _banks[work]
def ask(work, q, expected, kind="", pieces=()):
    tb, p11, p13 = bank(work)
    out = []
    for les, pl, name in ((L11, p11, "v11"), (L13, p13, "v13")):
        ans, best, _j, _t = plans.answer(tb, les, q, pl)
        sc = own_score({"expected": expected, "kind": kind, "question": q, "pieces": list(pieces)}, ans)
        out.append((name, round(sc, 3), ans, best.describe(tb.names) if best else ""))
    return out
if __name__ == "__main__":
    cases = json.load(open(sys.argv[1]))
    for c in cases:
        res = ask(c["work"], c["question"], c["expected"], c.get("kind", ""), c.get("pieces", ()))
        flag = "  <-- WORSE" if res[1][1] < res[0][1] else ("  (better)" if res[1][1] > res[0][1] else "")
        print(f"[{c['work']}] {c['question']}  several={plans.Planner.asks_several(c["question"])} rank={plans.Planner.asks_rank(c["question"])}{flag}")
        for name, sc, ans, plan in res:
            print(f"   {name} {sc} {ans!r}  :: {plan[:140]}")
