"""Training the company brain (v15): one set of lessons for single- and multi-document questions, and the router.

Three steps, each from questions with known answers over a training bank (``cie.eval.brain_test`` writes them):

1. **Single-fact lessons** (``cie.factbank.learn.train``) on the single-document questions: which entity a question is
   about, which field answers it, which relation a list means.
2. **Plan lessons** (the procedure of ``cie.factbank.plans.learn_plans``, over several banks at once) on the single- and
   multi-document questions together, with v13's rules (v9, proper, tickets, orders, the glossary) and the brain flag on.
   Earlier training sets can join on their own banks, so that what v13 learned is learned again.
3. **The router** (``cie.factbank.brain.Router``) on every fact and prose question: fact or prose.

    python -m cie.eval.brain_train train --work TRAIN --out DIR [--extra WORK ...] [--glossary G]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cie.eval.memory_test import _jsonl

SINGLE_ANSWERS = ("value", "date", "ids")  # what the single-fact lessons can learn from; lists of names are left out


def single_questions(qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The single-document questions the single-fact lessons learn from: an answer that is a value, a date or a list of keys."""
    return [q for q in qs if q.get("family") == "single" and any(k in q.get("expected", {}) for k in SINGLE_ANSWERS)]


def fact_questions(qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The questions the plan lessons learn from: single- and multi-document questions with a value, a date or keys."""
    return [q for q in qs if q.get("family") in ("single", "multi") and any(k in q.get("expected", {}) for k in SINGLE_ANSWERS)]


def learn_plans_many(pairs: list[tuple[Any, list[dict[str, Any]]]], glossary_path: str = "", log=print):
    """``plans.learn_plans`` with v13's settings (rules v9, proper, tickets, orders) over several (bank, questions) pairs, the
    associations shared and each question's own share left out, as there. The brain flag is recorded in the lessons."""
    import numpy as np

    from cie.factbank.engine import words
    from cie.factbank.learn import Assoc, fit
    from cie.factbank.plans import (
        FEATURES_V4,
        AskedKind,
        Lift,
        PlanLessons,
        Planner,
        proper_right,
        question_words,
        tokens_of,
    )

    glossary = None
    if glossary_path:
        from cie.factbank.reader import Glossary

        glossary = Glossary.load(glossary_path)
    per_q = []
    rel_total, agg_total, kind_total = Assoc(), Assoc(), Lift()
    asked = AskedKind()
    for bank, questions in pairs:
        pl = Planner(bank, "v9", None, None, None, "company", 0.5)
        pl.tickets = True
        pl.glossary = glossary
        for q in questions:
            cands = pl.candidates(q["question"])
            right = [proper_right(pl, q, p, m) for p, m in cands]
            good = [(p, m) for (p, m), ok in zip(cands, right, strict=True) if ok]
            qw, kw = set(words(q["question"])), question_words(q["question"])
            if glossary is not None:
                gq, gk = pl.glossary_words(q["question"])
                qw, kw = qw | gq, kw | gk
            rt = set().union(*[set().union(*[tokens_of(r) for r in p.path], tokens_of(p.field) if p.field != "label" else set())
                               for p, _ in good]) if good else set()
            at = {p.aggregate for p, _ in good}
            kt = {pl.out_kind(p, m["answer"]) for p, m in good}
            rel_total.add(qw, rt)
            agg_total.add(qw, at)
            kind_total.add(kw, kt)
            asked.add(question_words(q["question"]), {pl.kind9(p, m["answer"]) for p, m in good})
            per_q.append((pl, q, cands, right, qw, kw, rt, at, kt))
        log(f"plan candidates: {len(per_q)} questions so far")
    xs, ys = [], []
    for pl, q, cands, right, qw, kw, rt, at, kt in per_q:
        rel_total.add(qw, rt, -1.0)
        agg_total.add(qw, at, -1.0)
        kind_total.add(kw, kt, -1.0)
        for (p, m), ok in zip(cands, right, strict=True):
            xs.append(pl.x(q["question"], p, m, rel_total, agg_total, kind_total, FEATURES_V4))
            ys.append(int(ok))
        rel_total.add(qw, rt)
        agg_total.add(qw, at)
        kind_total.add(kw, kt)
    w = fit(np.array(xs, float), np.array(ys))
    trained_on = {"questions": len(per_q), "plans": len(ys), "right_plans": int(sum(ys)),
                  "questions_with_a_right_plan": sum(1 for x in per_q if any(x[3])), "proper": True,
                  "by_family": {f: sum(1 for x in per_q if x[1].get("family", "multi") == f) for f in ("single", "multi")}}
    les = PlanLessons(w, rel_total.to_json(), agg_total.to_json(), trained_on, list(FEATURES_V4), kind_total.to_json(), "v9", "", [], "",
                      "company", 0.5, glossary_path, asked.to_json(), 0.9, True, True, True)
    log("\n".join(les.describe()))
    return les


def train(work: Path, out: Path, extra: list[Path] = (), glossary: Path | None = None, extra_single: Path | None = None,
          log=print) -> dict[str, Any]:
    """Train the three parts on ``work`` (questions.jsonl over its v2 bank), the plan lessons also on each ``extra`` folder's
    questions over its own bank (read with ``extra_single``, the single-fact lessons those questions were asked with). Writes
    ``single_lessons.json``, ``plan_lessons.json`` and ``router.json`` to ``out``."""
    import time

    from cie.factbank.brain import Brain, Router
    from cie.factbank.learn import Lessons
    from cie.factbank.learn import train as fit_single
    from cie.factbank.trained import TrainedBank

    out.mkdir(parents=True, exist_ok=True)
    qs = _jsonl(work / "questions.jsonl")
    t = time.perf_counter()
    single = single_questions(qs)
    lessons = fit_single(TrainedBank(work / "factbank_v2.sqlite"), single)
    lessons.save(out / "single_lessons.json")
    times = {"single": round(time.perf_counter() - t, 1)}
    t = time.perf_counter()
    pairs = [(TrainedBank(work / "factbank_v2.sqlite", lessons), fact_questions(qs))]
    for w in extra:
        pairs.append((TrainedBank(w / "factbank_v2.sqlite", Lessons.load(extra_single) if extra_single else lessons),
                      [{**q, "family": q.get("family", "multi")} for q in _jsonl(w / "questions.jsonl")]))
    plan = learn_plans_many(pairs, str(glossary.resolve()) if glossary else "", log=log)
    plan.save(out / "plan_lessons.json")
    times["plans"] = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    brain = Brain(work / "factbank_v2.sqlite", out / "single_lessons.json", out / "plan_lessons.json")
    routed = [q for q in qs if q.get("family") in ("single", "multi", "prose")]
    router = Router.train(routed, brain)
    router.save(out / "router.json")
    times["router"] = round(time.perf_counter() - t, 1)
    rep = {"work": str(work), "extra": [str(w) for w in extra], "glossary": str(glossary) if glossary else "",
           "single": {"questions": len(single), "trained_on": lessons.trained_on},
           "plans": plan.trained_on, "router": router.trained_on, "seconds": times}
    (out / "train_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain_train")
    ap.add_argument("cmd", choices=["train"])
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--extra", nargs="*", default=[], type=Path, help="earlier training folders whose questions join the plan lessons")
    ap.add_argument("--extra-single", type=Path, help="the single-fact lessons the extra folders' questions were asked with")
    ap.add_argument("--glossary", type=Path)
    a = ap.parse_args(argv)
    rep = train(a.work, a.out, a.extra, a.glossary, a.extra_single)
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
