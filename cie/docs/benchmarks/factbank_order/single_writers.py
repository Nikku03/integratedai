"""The same questions as a set, each asked in one writer's wording only (writers 1, 2 and 3), in folders <set>_w1..w3 that
share the set's bank. Fails if the questions or answers differ from the set's own. A writer's wording that the selection rule
rejects (each placeholder not used exactly once, other braces, or over 200 characters) is replaced by writer 3's, the stand-in,
or by the drawn pair's first wording if writer 3's is rejected too; only the number replaced is printed."""
import json, re, sys
from pathlib import Path
from cie.eval.memory_test import haystack_docs, _jsonl, _write_jsonl
from cie.eval import factbank_multi as fm
S = Path(sys.argv[1]); name = sys.argv[2]; qseed = int(sys.argv[3])
h = json.loads((S / name / "haystack.json").read_text()); idx = json.loads((S / name / "index.json").read_text())["index"]
docs = haystack_docs(Path(h["root"]) / "generated_data" / "sources", idx, h["dsids"])
test = _jsonl(S / name / "questions.jsonl")
assert fm.questions(docs, set(h["dsids"]), True, qseed, wordings=fm.load_wordings(S / "ord/blind5/wordings.json")) == test
pairs = json.loads((S / "ord/blind5/wordings.json").read_text())
raw = {i: {x["key"]: x["wording"] for x in json.loads((S / f"ord/blind5/writer{i}.json").read_text())["wordings"]} for i in (1, 2, 3)}


def valid(key: str, w: str | None) -> bool:
    want = sorted(re.findall(r"\{(\w+)\}", pairs[key][0]))
    return bool(w) and sorted(re.findall(r"\{(\w+)\}", w)) == want and w.count("{") == w.count("}") == len(want) and len(w) <= 200


for i in (1, 2, 3):
    chosen = {k: raw[i].get(k) if valid(k, raw[i].get(k)) else raw[3].get(k) if valid(k, raw[3].get(k)) else pairs[k][0] for k in pairs}
    print(f"writer {i}: {sum(not valid(k, raw[i].get(k)) for k in pairs)} wording(s) replaced by the stand-in")
    w = {tuple(k.split("/")): [v] for k, v in chosen.items()}
    qs = fm.questions(docs, set(h["dsids"]), True, qseed, wordings=w)
    assert len(qs) == len(test) and all(a["id"] == b["id"] and a["expected"] == b["expected"] and a["pieces"] == b["pieces"] for a, b in zip(qs, test))
    d = S / f"{name}_w{i}"; d.mkdir(exist_ok=True)
    for f in ("factbank_v2.sqlite", "haystack.json", "index.json"):
        if not (d / f).exists():
            (d / f).symlink_to((S / name / f).resolve())
    _write_jsonl(d / "questions.jsonl", qs)
    print(f"writer {i}: same {len(qs)} questions; wording differs from the drawn one on {sum(a['question'] != b['question'] for a, b in zip(qs, test))}")
