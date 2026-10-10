"""Generate real questions (with expected answers computed from the set's documents) in given templates, for a set.
usage: gen.py SET templates.json out.jsonl   (templates: {"kind/field": [template, ...]})"""
import json, sys
from pathlib import Path
from cie.eval.memory_test import haystack_docs
from cie.eval import factbank_multi as fm
S = Path("/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad")
name, tpl, out = sys.argv[1], sys.argv[2], sys.argv[3]
h = json.loads((S / name / "haystack.json").read_text()); idx = json.loads((S / name / "index.json").read_text())["index"]
docs = haystack_docs(Path(h["root"]) / "generated_data" / "sources", idx, h["dsids"])
T = {tuple(k.split("/")): v for k, v in json.loads(Path(tpl).read_text()).items()}
# every kind needs a wording; use a dummy for kinds not asked about, then drop them
base = {k: ["DUMMY"] for k in fm.T}
base.update(T)
qs = fm.questions(docs, set(h["dsids"]), True, 1, wordings=base, all_wordings=True, max_q=None)
qs = [dict(q, work=name) for q in qs if q["question"] != "DUMMY"]
with open(out, "a") as f:
    for q in qs:
        f.write(json.dumps(q) + "\n")
print(name, len(qs))
