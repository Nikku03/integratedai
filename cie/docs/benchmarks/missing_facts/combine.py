"""Combine the word check, the judge and the kind of each fact into one outcome per fact, and tabulate."""
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
rows = [json.loads(l) for l in open(HERE / "mini50_rows.jsonl")]  # written by mini50.py
st = json.load(open(HERE / "set.json"))
kinds = json.load(open(HERE / "kinds.json"))
judge = json.load(open(HERE / "judge.json"))

OUT = {"reached": "reached the model",
       "reworded_reached": "reached the model (worded differently)",
       "lost": "in one or more passages, did not reach the model",
       "several": "spread over several passages, not all reached the model",
       "inferred": "not written anywhere: must be worked out",
       "partly": "only partly in the documents",
       "absent": "not in the documents"}
for r in rows:
    view = set(st["views"][r["question_id"]]["view"])
    j = judge.get(r["fid"])
    if r["reached"] is True:
        r["outcome"] = "reached"
    elif j is None:
        r["outcome"] = "lost"
    elif j["status"] in ("one_passage", "several_passages"):
        inside = set(j.get("passages") or []) <= view
        r["outcome"] = "reworded_reached" if inside else ("several" if j["status"] == "several_passages" else "lost")
    else:
        r["outcome"] = j["status"]
    r["judge"] = j
    k = kinds.get(r["fid"], {})
    r.update({"kind": k.get("kind", "?"), "list_item": k.get("list_item"), "combines": k.get("combines"), "negative": k.get("negative")})

n = len(rows)
print(f"{n} facts, {len({r['question_id'] for r in rows})} questions")
for o, c in Counter(r["outcome"] for r in rows).most_common():
    print(f"  {OUT[o]:58s} {c:3d} ({c / n:.0%})")
missing = lambda r: r["outcome"] not in ("reached", "reworded_reached")


def table(key, label):
    g = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    print(f"\nby {label}: facts, missing, (lost on the way | must be worked out | partly | not in documents)")
    for k_, rs in sorted(g.items(), key=lambda kv: -sum(missing(r) for r in kv[1])):
        m = [r for r in rs if missing(r)]
        c = Counter(r["outcome"] for r in m)
        print(f"  {str(k_):26s} {len(rs):3d}  missing {len(m):3d} ({len(m) / len(rs):4.0%})  "
              f"({c['lost'] + c['several']} | {c['inferred']} | {c['partly']} | {c['absent']})")


table("kind", "kind of fact")
table("question_type", "question type")
for flag in ("list_item", "combines", "negative", "has_number"):
    table(flag, flag)
print("\nwhy the words differ (facts the word check could not follow):")
print(Counter((r["judge"] or {}).get("why_words_differ", "?").split("/")[0].split(",")[0].strip().lower() for r in rows if r["reached"] is None).most_common(12))
json.dump(rows, open(HERE / "facts.json", "w"), indent=1)
