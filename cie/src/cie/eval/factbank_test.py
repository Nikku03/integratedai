"""Can the fact bank replace the memory bank? 50 documents, 50 questions (docs/FACTBANK_PREREGISTRATION.md).

The questions are the memory test's, whose answers code can check: owners and other document fields, deadlines, and
lists. Conflicts are left out because only the judge model can score them. The present bank's evidence comes from
``cie.eval.memory_test evidence`` on the same work folder; the fact bank's from ``cie.factbank``.

    W=eval_out/factbank50
    python -m cie.eval.factbank_test select --from <memory test work with questions.jsonl, index.json> --work $W
    python -m cie.eval.memory_test load --work $W && python -m cie.eval.memory_test plain --work $W
    python -m cie.eval.memory_test evidence --work $W --arms plain-words,plain,bank
    python -m cie.eval.factbank_test build --work $W
    python -m cie.eval.factbank_test ask --work $W
    python -m cie.eval.factbank_test score --work $W
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import time
from pathlib import Path
from typing import Any

from cie.eval.memory_test import _jsonl, _norm, _raw, _write_jsonl, check, dates_in, ids_in

GROUPS = ("owners", "deadlines", "lists")
ARMS = ("plain-words", "plain", "bank", "factbank")
BUDGETS = (2_000, 6_000, 24_000)
N_DOCS, N_QUESTIONS, SEED = 50, 50, 7
LIST_QUESTIONS, LIST_DOCS = 6, 20


def select(src: Path, work: Path, seed: int = SEED) -> dict[str, Any]:
    """Questions whose gold documents fit in 50: a few list questions first, then questions whose gold document is already
    in, then owners and deadlines questions in a seeded order until there are 50 questions or 50 documents."""
    qs = [q for q in _jsonl(src / "questions.jsonl") if q["group"] in GROUPS and q.get("expected")]
    rng = random.Random(seed)
    rng.shuffle(qs)
    docs: set[str] = set()
    chosen: list[dict[str, Any]] = []
    for q in sorted((q for q in qs if q["group"] == "lists"), key=lambda q: (len(q["gold_docs"]), q["id"])):
        if len([c for c in chosen if c["group"] == "lists"]) >= LIST_QUESTIONS:
            break
        if len(docs | set(q["gold_docs"])) <= LIST_DOCS:
            docs |= set(q["gold_docs"])
            chosen.append(q)
    single = [q for q in qs if q["group"] != "lists"]
    for q in single:
        if set(q["gold_docs"]) <= docs and q not in chosen:
            chosen.append(q)
    for q in single:
        if len(chosen) >= N_QUESTIONS:
            break
        if q in chosen or len(docs | set(q["gold_docs"])) > N_DOCS:
            continue
        docs |= set(q["gold_docs"])
        chosen.append(q)
    hay = json.loads((src / "haystack.json").read_text())
    pool = [d for d in hay["dsids"] if d not in docs]
    rng.shuffle(pool)
    dsids = sorted(docs | set(pool[: max(0, N_DOCS - len(docs))]))
    work.mkdir(parents=True, exist_ok=True)
    (work / "haystack.json").write_text(json.dumps({"root": hay["root"], "n_docs": N_DOCS, "seed": seed, "base_questions": 0,
                                                    "documents": len(dsids), "dsids": dsids}))
    idx = work / "index.json"
    if not idx.exists():
        idx.symlink_to((src / "index.json").resolve())
    _write_jsonl(work / "questions.jsonl", chosen)
    counts = {g: sum(1 for q in chosen if q["group"] == g) for g in GROUPS}
    return {"questions": len(chosen), "documents": len(dsids), "by_group": counts}


def _docs(work: Path):
    from cie.ingest.sources import read

    hay = json.loads((work / "haystack.json").read_text())
    index = json.loads((work / "index.json").read_text())["index"]
    sources = Path(hay["root"]) / "generated_data" / "sources"
    for dsid in hay["dsids"]:
        rel = index[dsid]
        try:
            sd = read(sources / rel, rel)
        except Exception:  # noqa: BLE001 - as the loader: a malformed export is left out
            continue
        sd.dsid = sd.dsid or dsid
        yield sd, _raw(sources, rel)


def build(work: Path) -> dict[str, Any]:
    from cie.factbank import bank

    t = time.perf_counter()
    rep = bank.build(work / "factbank.sqlite", list(_docs(work)))
    rep["seconds"] = round(time.perf_counter() - t, 2)
    (work / "factbank_build.json").write_text(json.dumps(rep, indent=1))
    return rep


def ask(work: Path) -> dict[str, Any]:
    from cie.factbank.engine import FactBank, replay, state_of

    fb = FactBank(work / "factbank.sqlite")
    rows = []
    replays_ok = 0
    for q in _jsonl(work / "questions.jsonl"):
        r = fb.ask(q["question"])
        ok = replay(r.journal) == state_of(r.written)
        replays_ok += ok
        rows.append({"id": q["id"], "answer": r.answer, "reason": r.reason, "evidence": r.evidence, "ms": round(r.ms, 2),
                     "journal": len(r.journal), "contradictions": sum(1 for j in r.journal if j["op"] == "contradiction"),
                     "replay_ok": ok, "seeds": [e for e, _ in r.seeds[:5]]})
    _write_jsonl(work / "factbank.jsonl", rows)
    return {"questions": len(rows), "replay_ok": replays_ok}


def reachable(q: dict[str, Any], text: str) -> float:
    """Whether the expected answer is in the text: the value, the date, or the share of the list's keys."""
    e = q["expected"]
    if "date" in e:
        return float(e["date"] in dates_in(text))
    if "ids" in e:
        want = set(e["ids"])
        return len(ids_in(text, e["id_kind"]) & want) / len(want)
    vals = [e["value"], *e.get("alts", [])]
    t = _norm(text)
    return float(any(re.search(r"(?<!\w)" + re.escape(_norm(v)) + r"(?!\w)", t) for v in vals))


def direct(q: dict[str, Any], answer: str) -> float:
    c = check(q, "Answer: " + answer)
    return float(c["f1"]) if "f1" in c else float(bool(c.get("correct")))


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def score(work: Path) -> dict[str, Any]:
    qs = {q["id"]: q for q in _jsonl(work / "questions.jsonl")}
    ev = {r["id"]: r for r in _jsonl(work / "evidence.jsonl")}
    fb = {r["id"]: r for r in _jsonl(work / "factbank.jsonl")}
    per: list[dict[str, Any]] = []
    for qid, q in qs.items():
        row: dict[str, Any] = {"id": qid, "group": q["group"], "kind": q["kind"], "reach": {}, "ms": {}}
        texts = {a: ev.get(qid, {}).get(a) for a in ("plain-words", "plain", "bank")}
        texts["factbank"] = fb.get(qid, {}).get("evidence")
        for a, t in texts.items():
            if t is None:
                continue
            row["reach"][a] = {str(b): reachable(q, t[:b]) for b in BUDGETS}
            row["ms"][a] = (ev.get(qid, {}).get("ms") or {}).get(a) if a != "factbank" else fb[qid]["ms"]
        if qid in fb:
            row["direct"] = direct(q, fb[qid]["answer"])
            row["answer"] = fb[qid]["answer"]
            row["expected"] = q["expected"]
        per.append(row)

    def group_means(fn) -> dict[str, float | None]:
        out = {g: _mean([fn(r) for r in per if r["group"] == g and fn(r) is not None]) for g in GROUPS}
        vals = [v for v in out.values() if v is not None]
        out["mean"] = round(sum(vals) / len(vals), 3) if vals else None
        return out

    reach = {a: {str(b): group_means(lambda r, a=a, b=b: (r["reach"].get(a) or {}).get(str(b))) for b in BUDGETS} for a in ARMS}
    direct_m = group_means(lambda r: r.get("direct"))
    ms = {a: (statistics.median([r["ms"][a] for r in per if r["ms"].get(a) is not None]) if any(r["ms"].get(a) is not None for r in per)
              else None) for a in ARMS}
    info = json.loads((work / "evidence_info.json").read_text()) if (work / "evidence_info.json").exists() else {}
    build_rep = json.loads((work / "factbank_build.json").read_text())
    st = info.get("storage") or {}
    storage = {"bank_bytes": st.get("bank_total"), "plain_bytes": st.get("plain_total"), "factbank_bytes": build_rep["bytes"]}
    d = lambda a, b, key: (round(a[key] - b[key], 3) if a.get(key) is not None and b.get(key) is not None else None)  # noqa: E731
    fb24, bk24 = reach["factbank"]["24000"], reach["bank"]["24000"]
    fb2, bk2 = reach["factbank"]["2000"], reach["bank"]["2000"]
    rules = {
        "1 not worse at the evidence budget (factbank - bank >= -0.03 in every group, 24,000 chars)":
            all((d(fb24, bk24, g) or 0) >= -0.03 for g in GROUPS if fb24.get(g) is not None),
        "2 better near the top (factbank - bank >= +0.10 on the mean, first 2,000 chars)": (d(fb2, bk2, "mean") or 0) >= 0.10,
        "3 answers without a model (direct >= 0.70 on the mean)": (direct_m["mean"] or 0) >= 0.70,
        "4 smaller (factbank <= 1/3 of the bank's storage)": bool(storage["bank_bytes"]) and storage["factbank_bytes"] * 3 <= storage["bank_bytes"],
    }
    rep = {"questions": len(per), "by_group": {g: sum(1 for r in per if r["group"] == g) for g in GROUPS}, "reachable": reach,
           "direct": direct_m, "search_ms_p50": ms, "storage": storage, "build": build_rep,
           "differences": {"24000": {g: d(fb24, bk24, g) for g in (*GROUPS, "mean")}, "2000": {g: d(fb2, bk2, g) for g in (*GROUPS, "mean")}},
           "rules": rules, "replace": rules[next(iter(rules))] and list(rules.values())[1] and list(rules.values())[3], "per_question": per}
    (work / "factbank_report.json").write_text(json.dumps(rep, indent=1, default=str))
    (work / "factbank_report.md").write_text(to_markdown(rep))
    return rep


def to_markdown(rep: dict[str, Any]) -> str:
    g = ("owners", "deadlines", "lists", "mean")
    out = [f"### Fact bank vs memory bank: {rep['questions']} questions ({', '.join(f'{k} {v}' for k, v in rep['by_group'].items())}), 50 documents",
           "", "Answer within the evidence (owners, deadlines: share; lists: share of the keys):", "",
           "| arm | budget | " + " | ".join(g) + " |", "|---|---|" + "---|" * len(g)]
    for a in ARMS:
        for b in BUDGETS:
            r = rep["reachable"][a][str(b)]
            out.append(f"| {a} | {b:,} | " + " | ".join("–" if r.get(x) is None else f"{r[x]:.3f}" for x in g) + " |")
    out += ["", "Answers from the fact bank alone, no model (owners, deadlines: share correct; lists: mean F1): "
            + ", ".join(f"{x} {rep['direct'][x]}" for x in g), "",
            f"Search time p50 (ms): {rep['search_ms_p50']}", f"Storage (bytes): {rep['storage']}",
            f"Fact bank: {rep['build']['facts']} facts, {rep['build']['entities']} entities, built in {rep['build']['seconds']} s; checker ok: "
            f"{rep['build']['check']['ok']}, contradictions {rep['build']['check']['contradictions']}, stale {rep['build']['check']['stale']}",
            "", "Rules:"] + [f"- {k}: **{'met' if v else 'not met'}**" for k, v in rep["rules"].items()]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.factbank_test")
    ap.add_argument("cmd", choices=["select", "build", "ask", "score"])
    ap.add_argument("--work", required=True)
    ap.add_argument("--from", dest="src")
    a = ap.parse_args(argv)
    work = Path(a.work)
    if a.cmd == "select":
        out = select(Path(a.src), work)
    elif a.cmd == "build":
        out = build(work)
    elif a.cmd == "ask":
        out = ask(work)
    else:
        out = score(work)
        print(to_markdown(out))
        return out
    print(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    main()
