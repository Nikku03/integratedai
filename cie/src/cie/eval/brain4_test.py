"""The company brain's round-4 test (v18): do round 4's fixes answer more of the questions that name a document the company
does not have, that count, whose answer is in no document, and that ask for free text, without harming anything else?
(docs/FACTBANK_BRAIN4_PREREGISTRATION.md)

v18 is v17 with round 4's fixes (``cie.factbank.brain.Brain(..., v18=True)``). The test asks the same kinds of question as
rounds 2 and 3 (``brain2_test``: the same generators, writers, held-out documents and rewriters), with more of the four kinds
v18 changes, on 5,000 fresh test documents, and compares v18 with v17 question by question. Arms are asked with
``brain2_test ask`` (v18 is arm "v18", answers ``factbank_v18.jsonl``); this module scores them:

- ``brain2_test.score`` gives every arm's family, group and kind scores, routes, false "not found", times and the
  big-minus-small differences;
- on top of it, ``score4`` reports v18 minus v17 per family (paired over the questions, with a 95% bootstrap interval), the
  questions whose answer changed, the free-text answers' mean length, and the hash-seed check of v18 against v18_seed1;
- with ``preregistered``, the rules of ``preregistered4`` decide.

    python -m cie.eval.brain4_test score --work W --small WS [--preregistered]
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cie.eval import brain2_test as T2
from cie.eval import brain3_test as T3
from cie.eval import brain_test as H

Rule = Callable[[dict[str, Any]], bool]
NEW, OLD = "v18", "v17"
TARGETS = ("not_found", "counts", "unanswerable", "prose")  # the families v18 changes
# The thresholds of the rules, set before the freeze (docs/FACTBANK_BRAIN4_PREREGISTRATION.md)
NOT_FOUND_MIN = 0.95  # rule 1: v18 on the not-found family, and not below v17
COUNTS_MIN = 0.95  # rule 2: v18 on the counts family, and not below v17
UNANSWERABLE_LEAD = 0.03  # rule 3: v18 on the unanswerable family >= v17 + this
PROSE_LEAD = 0.04  # rule 4: v18 on free text >= v17 + this
KEEP_MARGIN = 0.03  # rule 5: v18 on each of the other four families >= v17 - this
FALSE_NOT_FOUND_MAX = 0.05  # rule 6: v18's false "not found", and at most v17's + FALSE_NOT_FOUND_RISE
FALSE_NOT_FOUND_RISE = 0.01
MEAN_LEAD = 0.02  # rule 7: v18's mean over the eight families >= v17's + this
LENGTH_SHARE = 1.05  # rule 8: v18's free-text answers are on average at most this times v17's length
SIZE_MARGIN = 0.05  # rule 9 (reported): v18 at 5,000 documents >= the small set - this, for single, multi and free text each
SIZE_FAMILIES = ("single", "multi", "prose")
EPS = 1e-9


def _fam(r: dict[str, Any], family: str, arm: str) -> float:
    return T3._fam(r, family, arm)


def preregistered4() -> dict[str, Rule]:
    """The rules of the round-4 test, each named with its threshold (the module constants, set before the freeze). They read
    the report of ``score4``: label "v18" (v18's answers) against label "v17" (v17's, asked in the same folder)."""
    others = [f for f in T2.FAMILIES2 if f not in TARGETS]
    return {
        f"1 not found: v18 >= {NOT_FOUND_MIN} and >= v17 on questions naming a document the company does not have":
            lambda r: _fam(r, "not_found", NEW) >= max(NOT_FOUND_MIN, _fam(r, "not_found", OLD)) - EPS,
        f"2 counts: v18 >= {COUNTS_MIN} and >= v17":
            lambda r: _fam(r, "counts", NEW) >= max(COUNTS_MIN, _fam(r, "counts", OLD)) - EPS,
        f"3 no answer in the haystack: v18 >= v17 + {UNANSWERABLE_LEAD} on the unanswerable questions":
            lambda r: _fam(r, "unanswerable", NEW) >= _fam(r, "unanswerable", OLD) + UNANSWERABLE_LEAD - EPS,
        f"4 free text: v18 >= v17 + {PROSE_LEAD}":
            lambda r: _fam(r, "prose", NEW) >= _fam(r, "prose", OLD) + PROSE_LEAD - EPS,
        f"5 no harm: on each of single, multi, history and email and chat, v18 >= v17 - {KEEP_MARGIN}":
            lambda r: all(_fam(r, f, NEW) >= _fam(r, f, OLD) - KEEP_MARGIN - EPS for f in others),
        f"6 false 'not found': v18 says not found to at most {FALSE_NOT_FOUND_MAX} of the answerable questions, and at most "
        f"v17's + {FALSE_NOT_FOUND_RISE}":
            lambda r: r["scores"][NEW]["false_not_found"]["all"] <= min(FALSE_NOT_FOUND_MAX, r["scores"][OLD]["false_not_found"]["all"]
                                                                     + FALSE_NOT_FOUND_RISE) + EPS,
        f"7 better overall: v18's mean over the eight families >= v17's + {MEAN_LEAD}":
            lambda r: r["scores"][NEW]["mean_of_families"] >= r["scores"][OLD]["mean_of_families"] + MEAN_LEAD - EPS,
        f"8 no longer free-text answers: v18's mean length <= {LENGTH_SHARE} x v17's":
            lambda r: r["prose_length4"][NEW] <= LENGTH_SHARE * r["prose_length4"][OLD] + EPS,
    }


def size_rule(r: dict[str, Any]) -> bool:
    """Rule 9 (reported, not part of the claim): for single, multi and free text each, v18 at 5,000 documents >= the small set
    - ``SIZE_MARGIN``."""
    return all(r["small"]["differences"][NEW]["big_minus_small"][f] >= -SIZE_MARGIN - EPS for f in SIZE_FAMILIES)


def prose_length(work: Path, rows: list[dict[str, Any]], labels: tuple[str, ...] = (NEW, OLD)) -> dict[str, float | None]:
    """Each label's mean answer length, in characters, over the free-text family's questions (its answers file in W)."""
    ids = {r["id"] for r in rows if r["family"] == "prose"}
    out: dict[str, float | None] = {}
    for lab in labels:
        f = work / f"{T2.FILES2.get(lab, lab)}.jsonl"
        if not f.exists():
            out[lab] = None
            continue
        lens = [len(str(a.get("answer") or "")) for a in map(json.loads, f.read_text().splitlines()) if a.get("id") in ids]
        out[lab] = round(sum(lens) / len(lens), 1) if lens else None
    return out


def to_markdown4(rep: dict[str, Any]) -> str:
    """Round 4's section of report.md: the rules (when applied), v18 minus v17, the length of free-text answers and the seed
    check."""
    out = ["", "### Round 4: v18 against v17", "",
           "Round 4's rules are the ones below. The round-2 sections above (their rules, \"own\" labels and best-other pairing) are",
           "not used in round 4: there v17, v18 and v18_seed1 count as other arms.", ""]
    if rep.get("rules4"):
        out += ["| rule | met |", "|---|---|", *(f"| {k} | {v} |" for k, v in rep["rules4"].items()), ""]
        out += [f"Rule 9 (reported): it holds at size, for single, multi and free text each: {rep.get('size_rule4')}", ""]
    out += ["v18 minus v17 (paired over the questions; 95% bootstrap interval; questions better and worse):", "",
            "| family | questions | v18 - v17 | 95% interval | better | worse |", "|---|---|---|---|---|---|"]
    for f, d in rep["paired4"].items():
        out.append(f"| {f} | {d['questions']} | {H._f(d['mean'])} | {d['interval_95']} | {d['better']} | {d['worse']} |")
    ln = rep["prose_length4"]
    out += ["", f"Free-text answers' mean length: v17 {ln.get(OLD)}, v18 {ln.get(NEW)} characters."]
    sc = rep.get("seed_check4")
    out += ["", f"Hash-seed check (v18 against v18_seed1): {'not run' if sc is None else str(len(sc['different'])) + ' of ' + str(sc['questions']) + ' answers differ'}."]
    return "\n".join(out) + "\n"


def score4(work: Path, small: Path | None = None, preregistered: bool = False) -> dict[str, Any]:
    """``brain2_test.score`` of the folder (and its small control), then round 4's additions written into the same
    report.json and report.md: "paired4" (v18 minus v17), "changed4", "prose_length4", "seed_check4" and, with
    ``preregistered``, "rules4" (``preregistered4``) and "size_rule4" (the report's own "rules" are round 2's, not applied)."""
    rep = T2.score(work, small)
    rep["paired4"] = T3.paired(rep["rows"], NEW, OLD)
    rep["changed4"] = T3.changed(rep["rows"], NEW, OLD)
    rep["prose_length4"] = prose_length(work, rep["rows"])
    rep["seed_check4"] = H.seed_check(work, NEW, f"{NEW}_seed1")
    if preregistered:
        why: dict[str, str] = {}
        rep["rules4"] = H.rules(rep, preregistered4(), why)
        rep["rules4_why"] = why
        try:
            rep["size_rule4"] = size_rule(rep)
        except (KeyError, TypeError) as e:
            rep["size_rule4"] = None
            rep["size_rule4_why"] = f"{type(e).__name__}: {e}"
    (work / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    md = (work / "report.md").read_text()
    (work / "report.md").write_text(md + to_markdown4(rep))
    return rep


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain4_test", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="score a folder and its small control, with round 4's comparison")
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--small", type=Path, default=None)
    s.add_argument("--preregistered", action="store_true", help="apply the pre-registered rules (preregistered4)")
    a = ap.parse_args(argv)
    rep = score4(a.work, a.small, a.preregistered)
    show = {k: {f: v["mean"] for f, v in rep["paired4"].items()} if k == "paired4" else rep.get(k) for k in ("paired4", "rules4", "size_rule4")}
    show["scores"] = {lab: {"by_family": m["by_family"], "mean_of_families": m["mean_of_families"]} for lab, m in rep["scores"].items()}
    show["prose_length4"] = rep["prose_length4"]
    show["seed_check4"] = None if rep["seed_check4"] is None else len(rep["seed_check4"]["different"])
    print(json.dumps(show, indent=1))
    return rep


if __name__ == "__main__":
    main()
