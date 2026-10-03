"""Per-question split of the related-documents arms against today (single- vs multi-document questions)."""
import runpy, sys, io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    g = runpy.run_path("docs/benchmarks/related_docs/related50.py")
order, view, units, chosen, by_q, nb = g["order"], g["view"], g["units"], g["chosen"], g["by_q"], g["neighbours"]
from cie.eval.evidence_audit import _stems, present_in_one
CUT = g["CUT"]
def reached(q, kw, budget):
    out, _ = order(q, **kw); sel, _ = view(out, budget)
    ids = {units[i]["id"] for i in sel}
    texts = [(f"{units[i]['title']}\n{units[i]['text'][:CUT]}",) for i in sel]
    texts = [(t[0], _stems(t[0])) for t in texts]
    got = set()
    for f in by_q[q["question_id"]]:
        ok = present_in_one(f["fact"], texts) if f["reached"] is not None else set(f["judge"]["passages"]) <= ids
        if ok: got.add(f["fid"])
    return got, sel
for budget in (12000, 24000):
    for arm, kw in (("related: both", {"related": nb["both"]}), ("related: names", {"related": nb["names"]})):
        tot = {"single": [0, 0, 0], "multi": [0, 0, 0]}
        for q in chosen:
            a, _ = reached(q, {}, budget); b, sel = reached(q, kw, budget)
            k = "multi" if len(q["expected_doc_ids"]) > 1 else "single"
            tot[k][0] += len(by_q[q["question_id"]]); tot[k][1] += len(a); tot[k][2] += len(b)
        print(budget, arm, {k: f"today {v[1]} -> {v[2]} of {v[0]}" for k, v in tot.items()})
# what the related passages displace, one example
q = [q for q in chosen if len(q["expected_doc_ids"]) == 1][0]
out0, _ = order(q); out1, _ = order(q, related=nb["both"])
s0, _ = view(out0, 12000); s1, _ = view(out1, 12000)
gold = set(q["expected_doc_ids"])
print("single-doc example", q["question_id"], "gold passages in view: today", sum(units[i]["doc"] in gold for i in s0), "of", len(s0),
      "| related", sum(units[i]["doc"] in gold for i in s1), "of", len(s1))
