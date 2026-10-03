"""Entity-and-link pilot on 5 documents: graph lines against ~1,000-character passages.

    prepare  build the passage units and the graph lines (no question is read)
    tasks    write one judge task per question (questions are read from here on)
    score    coverage per arm and budget from the judge's attributions
"""
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CIE_ERB_ROOT", os.path.join(HERE, "..", "EnterpriseRAG-Bench"))
BUDGETS = (3000, 6000, 12000, None)


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def analyze(s):
    from cie.retrieval.bm25 import analyze as a
    return a(s or "")


# ------------------------------------------------------------------ prepare
def prepare():
    meta = json.load(open(f"{HERE}/meta.json"))
    from sqlalchemy import select
    from cie.core.db import session_scope
    from cie.core.models import Section
    import uuid
    chunks = []
    with session_scope() as s:
        for m in meta:
            for k, x in enumerate(s.scalars(select(Section).where(Section.document_id == uuid.UUID(m["document_id"])).order_by(Section.order_index))):
                chunks.append({"id": f"C{m['n']}.{k}", "doc": m["n"], "text": f"{x.title or ''}\n{x.text}".strip()})
    # merge entities across documents by normalised name or alias (union-find)
    graphs = {m["n"]: json.load(open(f"{HERE}/graph/doc{m['n']}.json")) for m in meta}
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    key_of = {}
    for n, g in graphs.items():
        for e in g.get("entities", []):
            node = (n, e["id"])
            names = [e.get("name")] + list(e.get("aliases") or [])
            for nm in names:
                k = norm(nm)
                if len(k) < 3:
                    continue
                if k in key_of:
                    union(node, key_of[k])
                else:
                    key_of[k] = node
                    find(node)
            find(node)
    ent = {}
    for n, g in graphs.items():
        for e in g.get("entities", []):
            ent[(n, e["id"])] = e
    groups = defaultdict(list)
    for node in ent:
        groups[find(node)].append(node)
    cross = [g for g in groups.values() if len({n for n, _ in g}) > 1]
    lines = []
    for n, g in graphs.items():
        name = {e["id"]: e.get("name") or e["id"] for e in g.get("entities", [])}
        for i, l in enumerate(g.get("links", [])):
            parts = [f"{name.get(l.get('from'), l.get('from'))} — {l.get('relation')} → {name.get(l.get('to'), l.get('to'))}: {l.get('description') or ''}".strip()]
            if l.get("time"):
                parts.append(f"When: {l['time']}.")
            if l.get("figures"):
                parts.append("Figures: " + "; ".join(str(f) for f in l["figures"]) + ".")
            if l.get("conditions"):
                parts.append(f"Conditions: {l['conditions']}.")
            if l.get("status") and l["status"] != "unknown":
                parts.append(f"Status: {l['status']}.")
            lines.append({"id": f"G{n}.L{i}", "doc": n, "kind": "link", "text": " ".join(parts),
                          "nodes": [find((n, l.get("from"))), find((n, l.get("to")))]})
        for e in g.get("entities", []):
            attrs = {k: v for k, v in (e.get("attributes") or {}).items() if v not in (None, "")}
            if not attrs and not e.get("aliases"):
                continue
            txt = f"{e.get('name')} ({e.get('type')})"
            if e.get("aliases"):
                txt += " also: " + ", ".join(e["aliases"])
            if attrs:
                txt += ": " + "; ".join(f"{k}: {v}" for k, v in attrs.items())
            lines.append({"id": f"G{n}.{e['id']}", "doc": n, "kind": "entity", "text": txt, "nodes": [find((n, e["id"]))]})
    names_of = defaultdict(set)
    for node, e in ent.items():
        for nm in [e.get("name")] + list(e.get("aliases") or []):
            if len(norm(nm)) >= 3:
                names_of[str(find(node))].add(norm(nm))
    for l in lines:
        l["nodes"] = [str(x) for x in l["nodes"]]
    stats = {"documents": len(graphs), "document_chars": sum(len(c["text"]) for c in chunks), "passages": len(chunks),
             "entities": len(ent), "entities_after_merge": len(groups), "entities_in_two_or_more_documents": len(cross),
             "cross_document_entities": sorted({ent[g[0]].get("name") for g in cross}),
             "links": sum(1 for l in lines if l["kind"] == "link"), "entity_lines": sum(1 for l in lines if l["kind"] == "entity"),
             "graph_chars": sum(len(l["text"]) for l in lines),
             "graph_json_chars": sum(len(json.dumps(g)) for g in graphs.values()),
             "links_with_time": sum(1 for g in graphs.values() for l in g.get("links", []) if l.get("time")),
             "links_with_figures": sum(1 for g in graphs.values() for l in g.get("links", []) if l.get("figures")),
             "links_with_conditions": sum(1 for g in graphs.values() for l in g.get("links", []) if l.get("conditions")),
             "per_document": {n: {"entities": len(g.get("entities", [])), "links": len(g.get("links", [])),
                                  "json_chars": len(json.dumps(g))} for n, g in graphs.items()}}
    json.dump({"chunks": chunks, "lines": lines, "names_of": {k: sorted(v) for k, v in names_of.items()}, "stats": stats},
              open(f"{HERE}/units.json", "w"), indent=1)
    with open(f"{HERE}/judge/passages.txt", "w") as f:
        for c in chunks:
            f.write(f"=== {c['id']} (document {c['doc']})\n{c['text']}\n\n")
    with open(f"{HERE}/judge/graph_lines.txt", "w") as f:
        for l in lines:
            f.write(f"{l['id']}\t{l['text']}\n")
    print(json.dumps(stats, indent=1))


# ------------------------------------------------------------------ tasks
def covered_questions():
    meta = json.load(open(f"{HERE}/meta.json"))
    ds = {m["dsid"] for m in meta}
    qs = [json.loads(l) for l in open(f"{ROOT}/questions.jsonl") if l.strip()]
    return [q for q in qs if q["expected_doc_ids"] and int(q["question_id"][4:]) % 2 == 1 and set(q["expected_doc_ids"]) <= ds]


def positive(q):
    """Answer facts to look for; "The answer must not ..." facts are constraints on the answer, not evidence."""
    return {f"F{i + 1}": f for i, f in enumerate(q["answer_facts"]) if not f.lower().startswith("the answer must not")}


def tasks():
    for q in covered_questions():
        t = {"question_id": q["question_id"], "question": q["question"], "question_type": q["question_type"],
             "facts": positive(q)}
        json.dump(t, open(f"{HERE}/judge/task_{q['question_id']}.json", "w"), indent=1)
        print(q["question_id"], q["question_type"], len(t["facts"]), "facts to look for")


# ------------------------------------------------------------------ score
def bm25_rank(units, question):
    from cie.retrieval.bm25 import query_terms
    qt = [t for t in query_terms(question) if len(t) > 2]
    toks = [analyze(u["text"]) for u in units]
    n = len(units)
    df = Counter(t for tk in toks for t in set(tk))
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in qt}
    avg = sum(len(t) for t in toks) / n
    sc = []
    for tk in toks:
        tf = Counter(tk)
        sc.append(sum(idf[t] * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(tk) / avg)) for t in qt if tf[t]))
    order = sorted(range(n), key=lambda i: (-sc[i], i))
    return [units[i] for i in order], {units[i]["id"]: sc[i] for i in range(n)}


def entity_route(lines, names_of, question):
    qn = f" {norm(question)} "
    hit = {node for node, names in names_of.items() if any(len(nm) >= 4 and f" {nm} " in qn for nm in names)}
    ranked, _ = bm25_rank(lines, question)
    first = [l for l in ranked if hit & set(l["nodes"])]
    rest = [l for l in ranked if not (hit & set(l["nodes"]))]
    return first + rest, hit


def take(units, budget):
    out, used = [], 0
    for u in units:
        size = len(u["text"]) + 1
        if budget and out and used + size > budget:
            break
        out.append(u)
        used += size
    return out, used


def score():
    from cie.eval.evidence_audit import _stems, present_in_one
    U = json.load(open(f"{HERE}/units.json"))
    chunks, lines = U["chunks"], U["lines"]
    rows = []
    for q in covered_questions():
        j = json.load(open(f"{HERE}/judge/verdict_{q['question_id']}.json"))
        facts = positive(q)
        c_rank, _ = bm25_rank(chunks, q["question"])
        g_rank, _ = bm25_rank(lines, q["question"])
        e_rank, hit = entity_route(lines, U["names_of"], q["question"])
        arms = {"passages": c_rank, "graph lines": g_rank, "graph by entity": e_rank}
        for arm, ranked in arms.items():
            for b in BUDGETS:
                sel, used = take(ranked, b)
                ids = {u["id"] for u in sel}
                texts = [(u["text"], _stems(u["text"])) for u in sel]
                key = "passage_sets" if arm == "passages" else "graph_sets"
                judged = lexical = 0
                for fid, fact in facts.items():
                    v = j["facts"].get(fid, {})
                    sets = [set(s) for s in v.get(key, []) if s]
                    judged += any(s <= ids for s in sets)
                    lexical += present_in_one(fact, texts)
                rows.append({"question_id": q["question_id"], "type": q["question_type"], "arm": arm, "budget": b or "all",
                             "chars": used, "facts": len(facts), "judge": judged, "lexical": lexical,
                             "entities_matched": len(hit) if arm == "graph by entity" else None})
    summary = defaultdict(lambda: {"facts": 0, "judge": 0, "lexical": 0, "chars": 0, "questions_all_facts": 0})
    for r in rows:
        k = f"{r['arm']} @ {r['budget']}"
        s = summary[k]
        s["facts"] += r["facts"]; s["judge"] += r["judge"]; s["lexical"] += r["lexical"]; s["chars"] += r["chars"]
        s["questions_all_facts"] += int(r["judge"] == r["facts"])
    # what the graph never holds, with the judge's reason
    lost = []
    for q in covered_questions():
        j = json.load(open(f"{HERE}/judge/verdict_{q['question_id']}.json"))
        for fid, f in positive(q).items():
            v = j["facts"].get(fid, {})
            if v.get("passage_sets") and not v.get("graph_sets"):
                lost.append({"question_id": q["question_id"], "fact": f, "why": v.get("graph_missing")})
    out = {"stats": U["stats"], "summary": dict(summary), "rows": rows, "graph_lost": lost}
    json.dump(out, open(f"{HERE}/results.json", "w"), indent=1)
    for k, s in summary.items():
        print(f"{k:28s} facts (judge) {s['judge']:3d}/{s['facts']}  lexical {s['lexical']:3d}  every fact {s['questions_all_facts']}  chars {s['chars'] / 4:,.0f} per question")
    print(f"facts the graph never holds (but a passage does): {len(lost)}")


if __name__ == "__main__":
    {"prepare": prepare, "tasks": tasks, "score": score}[sys.argv[1]]()
