"""The company brain's round-3 test (v17): does BM25's document fix the questions that describe a document instead of naming
it, without harming anything else? (docs/FACTBANK_BRAIN3_PREREGISTRATION.md)

v17 is v16 with one more route (``cie.factbank.brain.Brain.described``). The test asks the same kinds of question as round 2
(``brain2_test``: the same generators, writers, held-out documents and rewriters), with more descriptive questions, on 5,000
fresh test documents, and compares v17 with v16 question by question. Arms are asked with ``brain2_test ask`` (v17 is arm
"v17", answers ``factbank_v17.jsonl``); this module scores them:

- ``brain2_test.score`` gives every arm's family, group and kind scores, routes, false "not found", times and the
  big-minus-small differences;
- on top of it, ``score3`` reports v17 minus v16 per family and for the descriptive questions (paired over the questions,
  with a 95% bootstrap interval), the questions whose answer changed, and the hash-seed check of v17 against v17_seed1;
- with ``preregistered``, the rules of ``preregistered3`` decide.

    python -m cie.eval.brain3_test score --work W --small WS [--preregistered]
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cie.eval import brain2_test as T2
from cie.eval import brain_test as H

Rule = Callable[[dict[str, Any]], bool]
NEW, OLD = "v17", "v16"
DESCRIPTIVE = "descriptive"  # the writers' descriptive questions (group and kind "descriptive")
# The thresholds of the rules, set before the freeze (docs/FACTBANK_BRAIN3_PREREGISTRATION.md)
DESC_LEAD = 0.10  # rule 1: v17 on the descriptive questions >= v16 + this
SINGLE_LEAD = 0.03  # rule 2: v17 on the single-document family >= v16 + this
KEEP_MARGIN = 0.03  # rule 3: v17 on every other family >= v16 - this
UNANSWERABLE_MIN = 0.70  # rule 4
FALSE_NOT_FOUND_MAX = 0.05  # rule 5
MEAN_LEAD = 0.01  # rule 6: v17's mean over the eight families >= v16's + this
SIZE_MARGIN = 0.05  # rule 7: v17 at 5,000 documents >= the small set - this, for single, multi and free text each
SIZE_FAMILIES = ("single", "multi", "prose")
EPS = 1e-9


def _fam(r: dict[str, Any], family: str, arm: str) -> float:
    v = r["scores"][arm]["by_family"][family]
    if v is None:
        raise ValueError(f"{arm} has no {family} score")
    return v


def _group(r: dict[str, Any], group: str, arm: str) -> float:
    v = r["scores"][arm]["by_group"][group]
    if v is None:
        raise ValueError(f"{arm} has no {group} score")
    return v


def preregistered3() -> dict[str, Rule]:
    """The rules of the round-3 test, each named with its threshold (the module constants, set before the freeze). They read
    the report of ``brain2_test.score``: label "v17" (v17's answers) against label "v16" (v16's, asked in the same folder)."""
    others = [f for f in T2.FAMILIES2 if f != "single"]
    return {
        f"1 descriptive questions: v17 >= v16 + {DESC_LEAD}":
            lambda r: _group(r, DESCRIPTIVE, NEW) >= _group(r, DESCRIPTIVE, OLD) + DESC_LEAD - EPS,
        f"2 single-document questions: v17 >= v16 + {SINGLE_LEAD}":
            lambda r: _fam(r, "single", NEW) >= _fam(r, "single", OLD) + SINGLE_LEAD - EPS,
        f"3 no harm: on each of the other seven families, v17 >= v16 - {KEEP_MARGIN}":
            lambda r: all(_fam(r, f, NEW) >= _fam(r, f, OLD) - KEEP_MARGIN - EPS for f in others),
        f"4 no answer in the haystack: v17 >= {UNANSWERABLE_MIN} on the unanswerable questions":
            lambda r: _fam(r, "unanswerable", NEW) >= UNANSWERABLE_MIN - EPS,
        f"5 false 'not found': v17 says not found to at most {FALSE_NOT_FOUND_MAX} of the answerable questions":
            lambda r: r["scores"][NEW]["false_not_found"]["all"] <= FALSE_NOT_FOUND_MAX + EPS,
        f"6 better overall: v17's mean over the eight families >= v16's + {MEAN_LEAD}":
            lambda r: r["scores"][NEW]["mean_of_families"] >= r["scores"][OLD]["mean_of_families"] + MEAN_LEAD - EPS,
        f"7 it holds at size: for each of single, multi and free text, v17 at 5,000 documents >= the small set - {SIZE_MARGIN}":
            lambda r: all(r["small"]["differences"][NEW]["big_minus_small"][f] >= -SIZE_MARGIN - EPS for f in SIZE_FAMILIES),
    }


def paired(rows: list[dict[str, Any]], a: str = NEW, b: str = OLD) -> dict[str, Any]:
    """``a`` minus ``b`` per family and on the descriptive questions: the mean paired difference over the questions both
    scored, its 95% bootstrap interval (``memory_test.paired_ci``), and how many questions each got better and worse on."""
    from cie.eval.memory_test import paired_ci

    def one(sel: list[dict[str, Any]]) -> dict[str, Any]:
        pairs = [(r["score"][a], r["score"][b]) for r in sel if r["score"].get(a) is not None and r["score"].get(b) is not None]
        x, y = [p for p, _ in pairs], [q for _, q in pairs]
        return {"questions": len(pairs), "mean": round(sum(x) / len(x) - sum(y) / len(y), 3) if pairs else None,
                "interval_95": paired_ci(x, y) if pairs else None, "better": sum(p > q for p, q in pairs), "worse": sum(p < q for p, q in pairs)}

    out = {f: one([r for r in rows if r["family"] == f]) for f in T2.FAMILIES2}
    out[DESCRIPTIVE] = one([r for r in rows if r.get("group") == DESCRIPTIVE])
    out["all"] = one(rows)
    return out


def changed(rows: list[dict[str, Any]], a: str = NEW, b: str = OLD) -> list[dict[str, Any]]:
    """The questions whose score differs between ``a`` and ``b``: id, family, group, kind, both scores and both routes."""
    return [{"id": r["id"], "family": r["family"], "group": r.get("group"), "kind": r.get("kind"), b: r["score"][b], a: r["score"][a],
             "routes": {b: (r.get("route") or {}).get(b), a: (r.get("route") or {}).get(a)}}
            for r in rows if r["score"].get(a) is not None and r["score"].get(b) is not None and r["score"][a] != r["score"][b]]


def to_markdown3(rep: dict[str, Any]) -> str:
    """Round 3's section of report.md: the rules (when applied), v17 minus v16, the seed check and the described route's use."""
    out = ["", "### Round 3: v17 against v16", ""]
    if rep.get("rules3"):
        out += ["| rule | met |", "|---|---|", *(f"| {k} | {v} |" for k, v in rep["rules3"].items()), ""]
    out += ["v17 minus v16 (paired over the questions; 95% bootstrap interval; questions better and worse):", "",
            "| family | questions | v17 - v16 | 95% interval | better | worse |", "|---|---|---|---|---|---|"]
    for f, d in rep["paired3"].items():
        out.append(f"| {f} | {d['questions']} | {H._f(d['mean'])} | {d['interval_95']} | {d['better']} | {d['worse']} |")
    sc = rep.get("seed_check3")
    out += ["", f"Hash-seed check (v17 against v17_seed1): {'not run' if sc is None else str(len(sc['different'])) + ' of ' + str(sc['questions']) + ' answers differ'}."]
    return "\n".join(out) + "\n"


def score3(work: Path, small: Path | None = None, preregistered: bool = False) -> dict[str, Any]:
    """``brain2_test.score`` of the folder (and its small control), then round 3's additions written into the same
    report.json and report.md: "paired3" (v17 minus v16), "changed3", "seed_check3" and, with ``preregistered``, "rules3"
    (``preregistered3``; the report's own "rules" are round 2's, not applied)."""
    rep = T2.score(work, small)
    rep["paired3"] = paired(rep["rows"])
    rep["changed3"] = changed(rep["rows"])
    rep["seed_check3"] = H.seed_check(work, NEW, f"{NEW}_seed1")
    if preregistered:
        why: dict[str, str] = {}
        rep["rules3"] = H.rules(rep, preregistered3(), why)
        rep["rules3_why"] = why
    (work / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    md = (work / "report.md").read_text()
    (work / "report.md").write_text(md + to_markdown3(rep))
    return rep


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain3_test", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="score a folder and its small control, with round 3's comparison")
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--small", type=Path, default=None)
    s.add_argument("--preregistered", action="store_true", help="apply the pre-registered rules (preregistered3)")
    a = ap.parse_args(argv)
    rep = score3(a.work, a.small, a.preregistered)
    show = {k: {f: v["mean"] for f, v in rep["paired3"].items()} if k == "paired3" else rep.get(k) for k in ("paired3", "rules3")}
    show["scores"] = {lab: {"by_family": m["by_family"], "descriptive": m["by_group"].get(DESCRIPTIVE), "mean_of_families": m["mean_of_families"]}
                      for lab, m in rep["scores"].items()}
    show["seed_check3"] = None if rep["seed_check3"] is None else len(rep["seed_check3"]["different"])
    print(json.dumps(show, indent=1))
    return rep


if __name__ == "__main__":
    main()
