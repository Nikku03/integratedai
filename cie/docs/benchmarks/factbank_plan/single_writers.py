"""The same questions as a set, each asked in one writer's wording only (writers 1, 2 and 3), in folders <set>_w1..w3 that
share the set's bank. Fails if the questions or answers differ from the set's own."""
import json, sys
from pathlib import Path
from cie.eval.memory_test import haystack_docs, _jsonl, _write_jsonl
from cie.eval import factbank_multi as fm
S = Path(sys.argv[1]); name = sys.argv[2]; qseed = int(sys.argv[3])
h = json.loads((S / name / "haystack.json").read_text()); idx = json.loads((S / name / "index.json").read_text())["index"]
docs = haystack_docs(Path(h["root"]) / "generated_data" / "sources", idx, h["dsids"])
test = _jsonl(S / name / "questions.jsonl")
assert fm.questions(docs, set(h["dsids"]), True, qseed, wordings=fm.load_wordings(S / "plan9/blind3/wordings.json")) == test
for i in (1, 2, 3):
    w = {tuple(x["key"].split("/")): [x["wording"]] for x in json.loads((S / f"plan9/blind3/writer{i}.json").read_text())["wordings"]}
    qs = fm.questions(docs, set(h["dsids"]), True, qseed, wordings=w)
    assert len(qs) == len(test) and all(a["id"] == b["id"] and a["expected"] == b["expected"] and a["pieces"] == b["pieces"] for a, b in zip(qs, test))
    d = S / f"{name}_w{i}"; d.mkdir(exist_ok=True)
    for f in ("factbank_v2.sqlite", "haystack.json", "index.json"):
        if not (d / f).exists():
            (d / f).symlink_to((S / name / f).resolve())
    _write_jsonl(d / "questions.jsonl", qs)
    print(f"writer {i}: same {len(qs)} questions; wording differs from the drawn one on {sum(a['question'] != b['question'] for a, b in zip(qs, test))}")
