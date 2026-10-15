"""Free-text quotes, v17 against v18, on every prose-family (and unanswerable) question of work folders: the same document
(the passage index's best), v16's quote against v18's; scores as brain2_questions.score; abstentions with quote_cov."""
import json, sys, time
from collections import Counter
from pathlib import Path
from cie.factbank.brain import Brain, Router
from cie.factbank.prose import ProseRoute
from cie.eval import brain2_questions as Q2
L2 = Path("docs/benchmarks/brain2/lessons")
out_rows = []
for w in sys.argv[2:]:
    work = Path(w)
    b = Brain(work / "factbank_v2.sqlite", L2 / "single_lessons.json", L2 / "plan_lessons.json", Router.load(L2 / "router.json"), v18=True)
    r18 = b.prose_route(); r17 = ProseRoute(b.bank, budget=b.budget)
    tot = Counter(); t = time.time()
    for line in open(work / "questions.jsonl"):
        q = json.loads(line)
        fam = q.get("family")
        if fam not in ("prose", "unanswerable"):
            continue
        qq = b.tidy(q["question"])
        a17 = r17.answer(qq); ans18, why18, ev18, j18 = b.prose_row(qq); a18 = {"answer": ans18, "quote_cov": j18[0]["quote_cov"]}
        s17, s18 = Q2.score(q, {"answer": a17["answer"], "route": "prose"}), Q2.score(q, {"answer": a18["answer"], "route": "prose"})
        tot[(fam, "n")] += 1; tot[(fam, "17")] += s17; tot[(fam, "18")] += s18
        tot[(fam, "len17")] += len(a17["answer"]); tot[(fam, "len18")] += len(a18["answer"])
        out_rows.append({"set": work.name, "family": fam, "q": qq[:200], "s17": s17, "s18": s18, "a17": a17["answer"][:1200], "a18": a18["answer"][:1200],
                         "facts": (q.get("expected") or {}).get("facts"), "cov17": round(a17["quote_cov"], 3), "cov18": round(a18["quote_cov"], 3)})
    for fam in ("prose", "unanswerable"):
        n = tot[(fam, "n")] or 1
        print(f"{work.parent.name}/{work.name} {fam}: {tot[(fam, 'n')]}  v17 {tot[(fam, '17')] / n:.3f}  v18 {tot[(fam, '18')] / n:.3f}  "
              f"mean length {tot[(fam, 'len17')] / n:.0f} -> {tot[(fam, 'len18')] / n:.0f}  ({time.time() - t:.0f}s)", flush=True)
Path(sys.argv[1]).write_text("".join(json.dumps(r) + "\n" for r in out_rows))
