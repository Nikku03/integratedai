"""How often v18's new not-found checks fire, per family, on a work folder's questions (no full ask)."""
import json, sys, time
from collections import Counter
from pathlib import Path
from cie.factbank.brain import Brain, Router
L2 = Path("docs/benchmarks/brain2/lessons")
work = Path(sys.argv[1])
b = Brain(work / "factbank_v2.sqlite", L2 / "single_lessons.json", L2 / "plan_lessons.json", Router.load(L2 / "router.json"), v18=True)
fire, tot = Counter(), Counter()
t = time.time()
for line in open(work / "questions.jsonl"):
    q = json.loads(line)
    qq = b.tidy(q["question"])
    fam = q.get("family") or ("not_found" if (q.get("expected") or {}).get("not_found") else "?")
    tot[fam] += 1
    if b.missing(qq) or b.unknown_names(qq):
        continue
    sp = b.spliced(qq)
    if sp:
        fire[fam] += 1
        if fam != "not_found":
            print(f"  FIRE {fam}: {qq[:150]} | span {sp!r}")
print(work.name, {f: f"{fire[f]}/{tot[f]}" for f in tot}, f"{time.time() - t:.0f}s")
