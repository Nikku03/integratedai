"""Ask v11 and v13 (and optionally v12/v14 with a fixed simulated form) each question of a jsonl; write results."""
import json, sys
from pathlib import Path
from multiprocessing import Pool
from cie.factbank import plans
from cie.factbank.learn import Lessons
from cie.factbank.trained import TrainedBank
from cie.eval.factbank_multi import own_score
S = Path("/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad")
L11 = plans.PlanLessons.load(S / "mdtrain/plan_lessons_v11.json")
L13 = plans.PlanLessons.load(S / "mdtrain/plan_lessons_v13.json")

def run(args):
    work, qs, form = args
    tb = TrainedBank(S / work / "factbank_v2.sqlite", Lessons.load(S / "fb50/lessons.json"))
    p11, p13 = L11.planner(tb), L13.planner(tb)
    out = []
    for q in qs:
        r = {"id": q["id"], "work": work, "kind": q["kind"], "question": q["question"],
             "several": plans.Planner.asks_several(q["question"]), "acts": plans.Planner.wants_several(q["question"])}
        for les, pl, name in ((L11, p11, "v11"), (L13, p13, "v13")):
            ans, best, _j, _t = plans.answer(tb, les, q["question"], pl, form)
            sc = own_score(q, ans)
            ok = sc >= 0.999 and best is not None and plans.rests_on(q.get("pieces") or [], pl.reads(best))
            r[name] = round(sc, 3); r[name + "_reason"] = float(ok); r[name + "_ans"] = ans
            r[name + "_plan"] = best.describe(tb.names) if best else ""
        out.append(r)
    return out

if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    form = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    qs = [json.loads(l) for l in open(src)]
    by = {}
    for q in qs:
        by.setdefault(q["work"], []).append(q)
    # split each work's list into chunks for parallelism
    jobs = []
    for w, lst in by.items():
        for i in range(0, len(lst), 25):
            jobs.append((w, lst[i:i + 25], form))
    with Pool(3) as p:
        res = [r for chunk in p.map(run, jobs) for r in chunk]
    Path(dst).write_text("\n".join(json.dumps(r) for r in res) + "\n")
    from collections import Counter
    c = Counter((r["kind"], "worse" if r["v13"] < r["v11"] else "better" if r["v13"] > r["v11"] else "same") for r in res)
    print(dict(c))
