import json, sys
from collections import defaultdict
FAM = ("single", "multi", "prose", "not_found", "counts", "history", "email_chat", "unanswerable")
ANS = ("single", "multi", "prose", "counts", "history", "email_chat")
for n in sys.argv[2:]:
    rows = [json.loads(l) for l in open(f"{sys.argv[1]}/{n}.jsonl")]
    fam = defaultdict(lambda: [0, 0.0, 0.0])
    for r in rows:
        f = fam[r["family"]]; f[0] += 1; f[1] += r["v17"] or 0; f[2] += r["v18"] or 0
    m = {a: sum(fam[f][k] / fam[f][0] for f in FAM) / 8 for a, k in (("v17", 1), ("v18", 2))} if all(f in fam for f in FAM) else None
    ans = [r for r in rows if r["family"] in ANS]
    nf = {a: sum(1 for r in ans if str(r["a" + a[1:]]).lower().startswith("not found")) for a in ("v17", "v18")}
    allq = {a: sum(r[a] or 0 for r in rows) / len(rows) for a in ("v17", "v18")}
    print(n, len(rows), "| mean of 8:", None if m is None else f"{m['v17']:.3f} -> {m['v18']:.3f}", "| all questions:", f"{allq['v17']:.3f} -> {allq['v18']:.3f}",
          "| false nf:", f"{nf['v17']} -> {nf['v18']} of {len(ans)}", "|", {f: f"{v[1]/v[0]:.3f}->{v[2]/v[0]:.3f} ({v[0]})" for f, v in sorted(fam.items())})
