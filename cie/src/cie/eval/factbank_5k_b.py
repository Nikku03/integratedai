"""The 5,000-document test, part B (docs/FACTBANK_5K_B_PREREGISTRATION.md): the first fact-bank test, repeated on the
5,089-document haystack where search is hard. Can the fact bank's evidence still hold the answer, against the memory bank's?

- **Primary:** 50 new questions from the memory test's checkable questions that no earlier test used (``draw_questions``),
  asked on the 5,089-document haystack and on a small set holding only their gold documents.
- **Secondary:** the first test's own 50 questions (fb50), on the 5,089-document haystack, against fb50's 50-document run
  re-collected with today's code.

The evidence of the present bank and of plain search comes from ``cie.eval.memory_test`` unchanged (``collect`` wraps it to
count the searches that gave up on a time limit); the fact bank's from ``cie.eval.factbank_test``.

    python -m cie.eval.factbank_5k_b questions --src $MT5K --used $FB50 $FBTEST $MT50 --out Q.jsonl
    python -m cie.eval.factbank_5k_b assemble --work W --haystack $MT5K|--gold Q.jsonl --questions Q.jsonl --index ... --root ...
    python -m cie.eval.factbank_5k_b collect --work W        # memory_test evidence, counting give-ups
    python -m cie.eval.factbank_5k_b score --big W5K --small WSMALL --fb W5KFB --fb50 WFB50
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import statistics
from pathlib import Path
from typing import Any

from cie.eval.factbank_test import BUDGETS, GROUPS, direct, reachable
from cie.eval.memory_test import _jsonl, _write_jsonl

SEED = 61
MIX = (("owners", 26), ("linear_due", 10), ("action_due", 8), ("lists", 6))  # the first test's mix (docs/FACTBANK_RESULTS.md)
# list questions whose expected list leaves out a real item, because the item's key is reused on another document
# (docs/benchmarks/factbank_5k/understand_b.json, storage lens)
FLAWED = frozenset({"linear_assignee-002", "linear_assignee-015", "linear_status-004", "linear_status-005", "linear_due_window-003",
                    "linear_due_window-007", "linear_due_window-008", "jira_assignee-001", "jira_assignee-002", "jira_assignee-004"})
ARMS = ("plain-words", "plain", "bank", "v1", "v2")
FACT_FILES = {"v1": "factbank", "v2": "factbank_v2"}


def _pool(q: dict[str, Any]) -> str | None:
    if q["group"] == "owners":
        return "owners"
    if q["group"] == "deadlines":
        return q["kind"] if q["kind"] in ("linear_due", "action_due") else None
    return "lists" if q["group"] == "lists" else None


def draw_questions(src: list[dict[str, Any]], used: set[str], seed: int = SEED) -> list[dict[str, Any]]:
    """50 questions in the first test's mix (26 owners; 10 Linear due dates and 8 action items; 6 lists), each part a seeded
    sample of the checkable questions no earlier test used, leaving out the list questions known to be flawed."""
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for pool, n in MIX:
        cands = sorted((q for q in src if q.get("expected") and q["group"] in GROUPS and _pool(q) == pool and q["id"] not in used
                        and q["id"] not in FLAWED), key=lambda q: q["id"])
        if len(cands) < n:
            raise SystemExit(f"only {len(cands)} unused {pool} questions, {n} needed")
        rng.shuffle(cands)
        out += cands[:n]
    return out


def assemble(work: Path, root: str, dsids: list[str], qs: list[dict[str, Any]], index_path: Path, seed: int = SEED) -> dict[str, Any]:
    """A work folder: the documents, the index and the questions."""
    work.mkdir(parents=True, exist_ok=True)
    ids = sorted(set(dsids))
    (work / "haystack.json").write_text(json.dumps({"root": root, "n_docs": len(ids), "seed": seed, "base_questions": 0, "documents": len(ids),
                                                    "dsids": ids}))
    if not (work / "index.json").exists():
        (work / "index.json").symlink_to(index_path.resolve())
    _write_jsonl(work / "questions.jsonl", qs)
    return {"documents": len(ids), "questions": len(qs)}


class _GiveUps(logging.Handler):
    """Counts the bank's bounded queries that gave up on a time limit (cie.retrieval.bounded logs them at DEBUG only)."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.n = 0
        self.names: dict[str, int] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if "gave up" in record.getMessage():
            self.n += 1
            name = str(record.args[0]) if record.args else "?"
            self.names[name] = self.names.get(name, 0) + 1


def collect(work: Path, arms: tuple[str, ...] = ("plain-words", "plain", "bank")) -> dict[str, Any]:
    """memory_test's evidence for ``arms``, unchanged, with the give-ups counted (saved to giveups.json)."""
    from cie.eval.memory_test import collect_evidence

    h = _GiveUps()
    lg = logging.getLogger("cie.retrieval.bounded")
    lg.setLevel(logging.DEBUG)
    lg.addHandler(h)
    try:
        info = collect_evidence(work, list(arms))
    finally:
        lg.removeHandler(h)
    (work / "giveups.json").write_text(json.dumps({"gave_up": h.n, "by_query": h.names}, indent=1))
    return {"gave_up": h.n, **{k: v for k, v in info.items() if k == "storage"}}


def _ms(xs: list[float]) -> dict[str, float] | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return {"median": round(statistics.median(xs), 1), "p90": round(xs[min(len(xs) - 1, int(0.9 * len(xs)))], 1), "max": round(xs[-1], 1)}


def measure_b(work: Path) -> dict[str, Any]:
    """Each arm's answer within its evidence at 2,000 / 6,000 / 24,000 characters, by group and mean; the fact banks' own
    answers; time per question; storage; and the integrity checks."""
    qs = _jsonl(work / "questions.jsonl")
    ev = {r["id"]: r for r in _jsonl(work / "evidence.jsonl")} if (work / "evidence.jsonl").exists() else {}
    fb = {a: {r["id"]: r for r in _jsonl(work / f"{n}.jsonl")} for a, n in FACT_FILES.items() if (work / f"{n}.jsonl").exists()}
    rows = []
    for q in qs:
        r: dict[str, Any] = {"id": q["id"], "group": q["group"], "kind": q["kind"], "reach": {}, "direct": {}, "ms": {}}
        texts = {a: ev.get(q["id"], {}).get(a) for a in ("plain-words", "plain", "bank")}
        texts.update({a: d.get(q["id"], {}).get("evidence") for a, d in fb.items()})
        for a, t in texts.items():
            if t is not None:
                r["reach"][a] = {str(b): reachable(q, t[:b]) for b in BUDGETS}
        for a in ("plain-words", "plain", "bank"):
            r["ms"][a] = (ev.get(q["id"], {}).get("ms") or {}).get(a)
        for a, d in fb.items():
            if q["id"] in d:
                r["direct"][a] = direct(q, d[q["id"]]["answer"])
                r["ms"][a] = d[q["id"]].get("ms")
        rows.append(r)

    def gm(fn) -> dict[str, float | None]:
        out = {}
        for g in GROUPS:
            vals = [v for v in (fn(r) for r in rows if r["group"] == g) if v is not None]
            out[g] = round(sum(vals) / len(vals), 3) if vals else None
        have = [v for v in out.values() if v is not None]
        out["mean"] = round(sum(have) / len(have), 3) if have else None
        return out

    info = json.loads((work / "evidence_info.json").read_text()) if (work / "evidence_info.json").exists() else {}
    st = info.get("storage") or {}
    fbb = {a: json.loads((work / f"{n}_build.json").read_text()) for a, n in FACT_FILES.items() if (work / f"{n}_build.json").exists()}
    giveups = json.loads((work / "giveups.json").read_text()) if (work / "giveups.json").exists() else None
    return {
        "questions": len(rows), "by_group": {g: sum(1 for r in rows if r["group"] == g) for g in GROUPS},
        "reach": {a: {str(b): gm(lambda r, a=a, b=b: (r["reach"].get(a) or {}).get(str(b))) for b in BUDGETS} for a in ARMS},
        "direct": {a: gm(lambda r, a=a: r["direct"].get(a)) for a in fb},
        "ms": {a: _ms([r["ms"].get(a) for r in rows]) for a in ARMS},
        "storage": {"bank_total": st.get("bank_total"), "bank_bytes": st.get("bank_bytes"), "plain_total": st.get("plain_total"),
                    **{f"{a}_bytes": b.get("bytes") for a, b in fbb.items()}},
        "checks": {"bank_errors": sum(1 for r in ev.values() if r.get("bank_error")),
                   "evidence_missing": sum(1 for q in qs if q["id"] not in ev or not all(a in ev[q["id"]] for a in ("plain-words", "plain", "bank"))),
                   "gave_up": giveups, "fact_bank_documents": {a: b.get("documents") for a, b in fbb.items()}},
        "rows": rows}


def rules_b(m: dict[str, Any], control: dict[str, Any] | None, arm: str = "v1") -> dict[str, bool | None]:
    """The first test's rules on ``arm`` (docs/FACTBANK_PREREGISTRATION.md), and rule 5: its own answers hold at size."""
    d = lambda a, b: round(a - b, 3) if a is not None and b is not None else None  # noqa: E731
    f24, b24 = m["reach"][arm]["24000"], m["reach"]["bank"]["24000"]
    f2, b2 = m["reach"][arm]["2000"], m["reach"]["bank"]["2000"]
    own = (m["direct"].get(arm) or {}).get("mean")
    st = m["storage"]
    return {
        "1 not worse at the evidence budget (fact bank - bank >= -0.03 in every group, 24,000 chars)":
            all((x := d(f24.get(g), b24.get(g))) is not None and x >= -0.03 for g in GROUPS if f24.get(g) is not None),
        "2 better near the top (fact bank - bank >= +0.10 on the mean, first 2,000 chars)": (x := d(f2.get("mean"), b2.get("mean"))) is not None and x >= 0.10,
        "3 answers without a model (own answers >= 0.70 on the mean)": own is not None and own >= 0.70,
        "4 smaller (fact bank <= 1/3 of the bank's storage)": bool(st.get("bank_total")) and st.get(f"{arm}_bytes") is not None
                                                             and st[f"{arm}_bytes"] * 3 <= st["bank_total"],
        "5 own answers hold at size (5,089 documents >= control - 0.05)": None if control is None else (
            (x := d(own, (control["direct"].get(arm) or {}).get("mean"))) is not None and x >= -0.05),
    }


def same_bank_evidence(work: Path) -> dict[str, Any] | None:
    """The bank's evidence collected twice (evidence_pass1.jsonl, then evidence.jsonl): the questions whose text differs."""
    p1 = work / "evidence_pass1.jsonl"
    if not p1.exists():
        return None
    a = {r["id"]: r.get("bank") for r in _jsonl(p1)}
    b = {r["id"]: r.get("bank") for r in _jsonl(work / "evidence.jsonl")}
    return {"questions": len(a), "different": sorted(q for q in a if a[q] != b.get(q))}


def same_as_original(work: Path) -> dict[str, Any] | None:
    """The control's evidence re-collected with today's code against the original run's (evidence_original.jsonl): for each arm,
    the questions whose text differs."""
    p0 = work / "evidence_original.jsonl"
    if not p0.exists():
        return None
    a = {r["id"]: r for r in _jsonl(p0)}
    b = {r["id"]: r for r in _jsonl(work / "evidence.jsonl")}
    return {arm: sorted(q for q in a if a[q].get(arm) != b.get(q, {}).get(arm)) for arm in ("plain-words", "plain", "bank")}


def chance(work: Path) -> dict[str, int]:
    """For each question, how many documents of the haystack other than its gold documents carry the expected answer's text:
    a hit in the evidence may come from one of them."""
    from cie.eval.memory_test import _norm, haystack_docs

    hay = json.loads((work / "haystack.json").read_text())
    index = json.loads((work / "index.json").read_text())["index"]
    docs = haystack_docs(Path(hay["root"]) / "generated_data" / "sources", index, hay["dsids"])
    texts = {d["dsid"]: _norm(json.dumps(d["raw"], ensure_ascii=False)) for d in docs}
    out = {}
    for q in _jsonl(work / "questions.jsonl"):
        e = q["expected"]
        vals = [e["date"]] if "date" in e else (e["ids"] if "ids" in e else [e["value"], *e.get("alts", [])])
        pats = [re.compile(r"(?<!\w)" + re.escape(_norm(v)) + r"(?!\w)") for v in vals if v]
        gold = set(q.get("gold_docs") or [])
        out[q["id"]] = sum(1 for dsid, t in texts.items() if dsid not in gold and any(p.search(t) for p in pats))
    return out


def b_test(big: Path, small: Path, fb: Path, fb50: Path) -> dict[str, Any]:
    """Part B's rules and what is reported with them."""
    mb, ms_, mf, mf50 = measure_b(big), measure_b(small), measure_b(fb), measure_b(fb50)
    d = lambda a, b: round(a - b, 3) if a is not None and b is not None else None  # noqa: E731

    def change(m, c):
        return {a: {b: {g: d(m["reach"][a][b].get(g), c["reach"][a][b].get(g)) for g in (*GROUPS, "mean")} for b in m["reach"][a]} for a in ARMS}

    rules = rules_b(mb, ms_, "v1")
    rep = {
        "primary_5k": {k: v for k, v in mb.items() if k != "rows"}, "primary_small": {k: v for k, v in ms_.items() if k != "rows"},
        "fb50_5k": {k: v for k, v in mf.items() if k != "rows"}, "fb50_50": {k: v for k, v in mf50.items() if k != "rows"},
        "rules": rules, "replace": bool(list(rules.values())[0] and list(rules.values())[1] and list(rules.values())[3]),
        "rules_v2_primary": rules_b(mb, ms_, "v2"), "rules_fb50_5k": rules_b(mf, mf50, "v1"),
        "change_primary_5k_minus_small": change(mb, ms_), "change_fb50_5k_minus_50": change(mf, mf50),
        "fact_bank_minus_plain_words": {b: d(mb["reach"]["v1"][b]["mean"], mb["reach"]["plain-words"][b]["mean"]) for b in mb["reach"]["v1"]},
        "bank_evidence_twice": {w.name: same_bank_evidence(w) for w in (big, small, fb, fb50)},
        "control_against_original_run": same_as_original(fb50),
        "rows": {"primary_5k": mb["rows"], "primary_small": ms_["rows"], "fb50_5k": mf["rows"], "fb50_50": mf50["rows"]},
    }
    for w in (big, small):
        p = w / "chance.json"
        if p.exists():
            rep[f"chance_{w.name}"] = json.loads(p.read_text())
    (big / "b_report.json").write_text(json.dumps(rep, indent=1, default=str))
    (big / "b_report.md").write_text(to_markdown(rep))
    return rep


def to_markdown(rep: dict[str, Any]) -> str:
    g = (*GROUPS, "mean")
    out = ["### Part B: the fact bank against the memory bank at 5,089 documents", ""]
    for name, label in (("primary_small", "primary questions, small set"), ("primary_5k", "primary questions, 5,089 documents"),
                        ("fb50_50", "the first test's questions, 50 documents"), ("fb50_5k", "the first test's questions, 5,089 documents")):
        m = rep[name]
        out += [f"**{label}** ({m['questions']} questions: {', '.join(f'{k} {v}' for k, v in m['by_group'].items())})", "",
                "| arm | budget | " + " | ".join(g) + " |", "|---|---|" + "---|" * len(g)]
        for a in ARMS:
            for b, r in m["reach"][a].items():
                out.append(f"| {a} | {int(b):,} | " + " | ".join("–" if r.get(x) is None else f"{r[x]:.3f}" for x in g) + " |")
        for a, r in m["direct"].items():
            out.append(f"| own answers, {a} | | " + " | ".join("–" if r.get(x) is None else f"{r[x]:.3f}" for x in g) + " |")
        out += ["", f"time per question (ms): {json.dumps(m['ms'])}", f"storage: {json.dumps(m['storage'])}", f"checks: {json.dumps(m['checks'])}", ""]
    out += ["Rules (fact bank v1, primary questions, 5,089 documents):"] + [f"- {k}: **{'met' if v else ('not met' if v is not None else 'n/a')}**"
                                                                          for k, v in rep["rules"].items()]
    out += [f"- replace (rules 1, 2 and 4): **{'met' if rep['replace'] else 'not met'}**", "",
            f"- v2 on the same rules: {json.dumps(rep['rules_v2_primary'])}", f"- the first test's questions at 5,089: {json.dumps(rep['rules_fb50_5k'])}",
            f"- fact bank minus plain-words: {json.dumps(rep['fact_bank_minus_plain_words'])}",
            f"- bank evidence collected twice: {json.dumps(rep['bank_evidence_twice'])}",
            f"- the control against the original run: {json.dumps(rep['control_against_original_run'])}"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.factbank_5k_b")
    ap.add_argument("cmd", choices=["questions", "assemble", "collect", "chance", "score"])
    ap.add_argument("--src")
    ap.add_argument("--used", nargs="*", default=[])
    ap.add_argument("--out")
    ap.add_argument("--work")
    ap.add_argument("--haystack", help="assemble: a folder whose documents to take")
    ap.add_argument("--gold", help="assemble: take only the gold documents of this questions file")
    ap.add_argument("--questions")
    ap.add_argument("--index")
    ap.add_argument("--root")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--big")
    ap.add_argument("--small")
    ap.add_argument("--fb")
    ap.add_argument("--fb50")
    a = ap.parse_args(argv)
    if a.cmd == "questions":
        used = {q["id"] for d in a.used for q in _jsonl(Path(d) / "questions.jsonl")}
        qs = draw_questions(_jsonl(Path(a.src) / "questions.jsonl"), used, a.seed)
        _write_jsonl(Path(a.out), qs)
        rep: Any = {"questions": len(qs), "by_pool": {p: sum(1 for q in qs if _pool(q) == p) for p, _ in MIX}}
    elif a.cmd == "assemble":
        qs = _jsonl(Path(a.questions))
        ids = json.loads((Path(a.haystack) / "haystack.json").read_text())["dsids"] if a.haystack else sorted(
            {x for q in _jsonl(Path(a.gold)) for x in q["gold_docs"]})
        rep = assemble(Path(a.work), a.root, ids, qs, Path(a.index), a.seed)
    elif a.cmd == "collect":
        rep = collect(Path(a.work))
    elif a.cmd == "chance":
        c = chance(Path(a.work))
        (Path(a.work) / "chance.json").write_text(json.dumps(c, indent=1))
        rep = {"questions": len(c), "median_other_documents_with_the_answer": statistics.median(c.values()) if c else None}
    else:
        r = b_test(Path(a.big), Path(a.small), Path(a.fb), Path(a.fb50))
        rep = {"rules": r["rules"], "replace": r["replace"]}
    print(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    main()
