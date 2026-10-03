"""Added after the planned arms were scored: the graph as a pointer. Graph lines are ranked (BM25, or the entity
route), each line is mapped to the passage it was extracted from, and the model reads those passages."""
import json, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import kg_eval as k

U = json.load(open(k.HERE + "/units.json"))
graphs = {n: json.load(open(f"{k.HERE}/graph/doc{n}.json")) for n in range(1, 6)}
src = {}
for n, g in graphs.items():
    for i, l in enumerate(g.get("links", [])):
        src[f"G{n}.L{i}"] = f"C{n}.{l.get('source_section')}"
    for e in g.get("entities", []):
        ss = e.get("source_sections") or []
        if ss:
            src[f"G{n}.{e['id']}"] = f"C{n}.{ss[0]}"
chunk = {c["id"]: c for c in U["chunks"]}
tot = {}
for q in k.covered_questions():
    j = json.load(open(f"{k.HERE}/judge/verdict_{q['question_id']}.json"))
    facts = k.positive(q)
    g_rank, _ = k.bm25_rank(U["lines"], q["question"])
    e_rank, _ = k.entity_route(U["lines"], U["names_of"], q["question"])
    for arm, ranked in (("graph lines -> their passages", g_rank), ("graph by entity -> their passages", e_rank)):
        order = []
        for l in ranked:
            cid = src.get(l["id"])
            if cid in chunk and cid not in order:
                order.append(cid)
        for b in (3000, 6000, 12000):
            sel, used = k.take([chunk[c] for c in order], b)
            ids = {u["id"] for u in sel}
            n = sum(1 for fid in facts if any(set(s) <= ids for s in j["facts"][fid].get("passage_sets", []) if s))
            t = tot.setdefault(f"{arm} @ {b}", [0, 0, 0]); t[0] += n; t[1] += len(facts); t[2] += used
for kk, (n, f, c) in tot.items():
    print(f"{kk:42s} facts (judge) {n:3d}/{f}  chars {c / 4:,.0f} per question")
json.dump(tot, open(k.HERE + "/results_pointer.json", "w"), indent=1)
