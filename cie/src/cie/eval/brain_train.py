"""Training the company brain (v15): one set of lessons for single- and multi-document questions, and the router.

Three steps, each from questions with known answers over a training bank (``cie.eval.brain_test`` writes them):

1. **Single-fact lessons** (``cie.factbank.learn.train``) on the single-document questions: which entity a question is
   about, which field answers it, which relation a list means.
2. **Plan lessons** (the procedure of ``cie.factbank.plans.learn_plans``, over several banks at once) on the single- and
   multi-document questions together, with v13's rules (v9, proper, tickets, orders, the glossary) and the brain flag on.
   Earlier training sets can join on their own banks, so that what v13 learned is learned again.
3. **The router** (``cie.factbank.brain.Router``) on every fact and prose question: fact or prose.

**v16** (round 2, ``--v16``; v15's training is unchanged without it): the router is fitted on the signals of the v16 brain
(``Brain(..., v16=True)``: a question word after a verb of knowing or telling asks plainly, so its signals change), over
v15's questions and a sample of round 2's new kinds (``--kinds``: the questions ``cie.eval.brain2_questions`` drew on the
same bank). The sample (``sample_kinds``) takes up to ``PER_FAMILY`` questions of each new family (counts, history,
email_chat, the two-document multi kinds, the embedded single kinds and the empty-field unanswerable kind), shared out over
the family's kinds in turn, so that they do not swamp v15's questions; every one of them is labelled fact, as the brain
should route it. Held-out writers' questions (kind "heldout") are never learned from. With ``--kinds``, the plan lessons
(``train`` or ``plans``) also learn from the two-document questions of the new kinds (``kinds_multi``: all of them, or only
the kinds named by ``--plan-kinds``). Each run writes
what it fitted with the sha256 of its inputs and outputs (``train_report.json``, ``router_report.json``,
``plans_report.json``).

Why ``--plan-kinds``: on train5k, plan lessons learned from all six new two-document kinds made 9 answers of v15's own
questions worse (Linear issue assignees behind pull requests read as issue keys, HubSpot owners, a customer's Jira tickets),
the lessons learned from only the kinds v15's lessons answered below 0.9 on train (owner_accounts, pr_issue_creator,
pr_issue_team) none. Plan lessons are reproducible in content but not byte for byte: the order of their associations and
the last bits of their weights follow Python's string hashing (``PYTHONHASHSEED``).

    python -m cie.eval.brain_train train --work TRAIN --out DIR [--extra WORK ...] [--glossary G] [--workers N]
        [--v16 --kinds KINDS [--per-family N] [--seed S]]
    python -m cie.eval.brain_train router --work TRAIN --out DIR [--workers N]   (the router alone, on lessons in DIR)
        [--lessons DIR2] [--v16 --kinds KINDS [--per-family N] [--seed S]]   (lessons read from DIR2)
    python -m cie.eval.brain_train plans --work TRAIN --out DIR --kinds KINDS [--extra WORK ...] [--extra-single L]
        [--glossary G] [--lessons DIR2] [--plan-kinds KIND ...]   (the plan lessons alone, on the single-fact lessons in DIR2
        or DIR)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cie.eval.memory_test import _jsonl

SINGLE_ANSWERS = ("value", "date", "ids")  # what the single-fact lessons can learn from; lists of names are left out
ROUTED = ("single", "multi", "prose")  # the families the router learns from (v15)
# v16: round 2's new families join, every question of them labelled fact (``Router.label``: only prose is prose)
ROUTED16 = (*ROUTED, "counts", "history", "email_chat", "unanswerable")
PER_FAMILY = 30  # v16: the new kinds' questions the router learns from, at most this many per family
KINDS_SEED = 16  # v16: the seed of that sample (round 2's question seed)
HELDOUT = "heldout"  # the held-out writers' questions: never learned from


def single_questions(qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The single-document questions the single-fact lessons learn from: an answer that is a value, a date or a list of keys."""
    return [q for q in qs if q.get("family") == "single" and any(k in q.get("expected", {}) for k in SINGLE_ANSWERS)]


def fact_questions(qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The questions the plan lessons learn from: single- and multi-document questions with a value, a date or keys."""
    return [q for q in qs if q.get("family") in ("single", "multi") and any(k in q.get("expected", {}) for k in SINGLE_ANSWERS)]


def sha256(path: str | Path) -> str:
    """A file's sha256, in hex."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sample_kinds(qs: list[dict[str, Any]], per_family: int = PER_FAMILY, seed: int = KINDS_SEED) -> list[dict[str, Any]]:
    """v16: up to ``per_family`` of round 2's new questions per family, shared out over the family's kinds in turn (each
    kind's questions, and the order of the kinds, shuffled with ``seed``), so that a kind with thousands of questions (Slack
    channels) does not crowd out one with ten. Held-out writers' questions are left out. The same ``qs`` and seed give the
    same sample."""
    rng = random.Random(seed)
    by: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for q in qs:
        if q.get("kind") != HELDOUT and q.get("family") != "prose":
            by[q.get("family") or ""][q.get("kind") or ""].append(q)
    out = []
    for fam in sorted(by):
        kinds = sorted(by[fam])
        rng.shuffle(kinds)
        pools = []
        for k in kinds:
            pool = list(by[fam][k])
            rng.shuffle(pool)
            pools.append(pool[::-1])  # taken from the end
        taken: list[dict[str, Any]] = []
        while len(taken) < per_family and any(pools):
            for pool in pools:
                if pool and len(taken) < per_family:
                    taken.append(pool.pop())
        out += taken
    return out


def kinds_multi(qs: list[dict[str, Any]], kinds: list[str] | None = None) -> list[dict[str, Any]]:
    """v16: the two-document questions of round 2's new kinds that the plan lessons learn from (family multi, with a value,
    a date or keys), only those of ``kinds`` when given."""
    return [q for q in fact_questions(qs) if q.get("family") == "multi" and q.get("kind") != HELDOUT
            and (not kinds or q.get("kind") in kinds)]


def routed_questions(qs: list[dict[str, Any]], v16: bool = False) -> list[dict[str, Any]]:
    """The questions the router learns from: v15's fact and prose families, and with ``v16`` round 2's new families too
    (held-out writers' questions never)."""
    fams = ROUTED16 if v16 else ROUTED
    return [q for q in qs if q.get("family") in fams and q.get("kind") != HELDOUT]


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


def _signals(args: tuple[str, str, str, list[str], bool]) -> list[dict[str, float]]:
    from cie.factbank.brain import Brain

    bank, single, plans, questions, v16 = args
    brain = Brain(bank, single, plans, v16=v16)
    return [brain.signals(q) for q in questions]


class _Signals:
    """Signals worked out beforehand, read back by question, so that ``Router.train`` need not run the planner again."""

    def __init__(self, by_question: dict[str, dict[str, float]]):
        self.by_question = by_question

    def signals(self, question: str) -> dict[str, float]:
        return self.by_question[question]


def router_signals(work: Path, single: Path, plans: Path, texts: list[str], workers: int = 1, v16: bool = False
                   ) -> dict[str, dict[str, float]]:
    """``Brain.signals`` of each question text on ``work``'s bank (the v16 brain's with ``v16``), worked out in ``workers``
    processes: they run the planner, about a second a question at 5,000 documents."""
    from concurrent.futures import ProcessPoolExecutor

    chunks = [texts[i::max(1, workers)] for i in range(max(1, workers))]
    args = [(str(work / "factbank_v2.sqlite"), str(single), str(plans), c, v16) for c in chunks if c]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            got = list(ex.map(_signals, args))
    else:
        got = [_signals(a) for a in args]
    return {t: s for (_, _, _, c, _), sigs in zip(args, got, strict=True) for t, s in zip(c, sigs, strict=True)}


def fit_router(work: Path, single: Path, plans: Path, qs: list[dict[str, Any]], workers: int = 1, v16: bool = False):
    """The router, trained on the fact and prose questions of ``qs`` (``routed_questions``); their signals (which run the
    planner, a few seconds a question at 5,000 documents) are worked out in ``workers`` processes. With ``v16``, the signals
    are the v16 brain's and round 2's new families are learned from too (each labelled fact); the router's ``trained_on``
    then also counts its questions by family."""
    from cie.factbank.brain import Router

    routed = routed_questions(qs, v16)
    by_question = router_signals(work, single, plans, sorted({q["question"] for q in routed}), workers, v16)
    router = Router.train(routed, _Signals(by_question))
    if v16:
        router.trained_on.update({"v16": True, "by_family": dict(sorted(Counter(q["family"] for q in routed).items()))})
    return router


def fit_router16(work: Path, single: Path, plans: Path, kinds: Path, workers: int = 1, per_family: int = PER_FAMILY,
                 seed: int = KINDS_SEED, log=print) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    """v16: the router on the v16 brain's signals over ``work``'s questions (v15's families) and ``sample_kinds`` of the new
    kinds in ``kinds``; with a report of what it learned from and the sha256 of every input, and each question's signals
    ({id, family, kind, label, question, signals}, as ``router_signals.jsonl`` keeps them)."""
    from cie.factbank.brain import Router

    qs = _jsonl(work / "questions.jsonl")
    sample = sample_kinds(_jsonl(kinds), per_family, seed)
    routed = routed_questions(qs + sample, v16=True)
    log(f"router (v16): {len(routed) - len(sample)} questions of v15's families and {len(sample)} of the new kinds")
    by_question = router_signals(work, single, plans, sorted({q["question"] for q in routed}), workers, v16=True)
    router = Router.train(routed, _Signals(by_question))
    router.trained_on.update({"v16": True, "by_family": dict(sorted(Counter(q["family"] for q in routed).items())),
                              "kinds": {"per_family": per_family, "seed": seed, "questions": len(sample),
                                        "by_kind": dict(sorted(Counter(q["kind"] for q in sample).items()))}})
    rep = {"work": str(work), "questions_sha256": sha256(work / "questions.jsonl"), "kinds": str(kinds), "kinds_sha256": sha256(kinds),
           "single": str(single), "single_sha256": sha256(single), "plans": str(plans), "plans_sha256": sha256(plans),
           "sample_ids": [q["id"] for q in sample], "trained_on": router.trained_on}
    rows = [{"id": q.get("id"), "family": q["family"], "kind": q.get("kind"), "label": Router.label(q), "question": q["question"],
             "signals": by_question[q["question"]]} for q in routed]
    return router, rep, rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def plan_pairs(work: Path, lessons: Any, qs: list[dict[str, Any]], extra: list[Path] = (), extra_single: Path | None = None,
               kinds: Path | None = None, plan_kinds: list[str] | None = None) -> list[tuple[Any, list[dict[str, Any]]]]:
    """The (bank, questions) pairs the plan lessons learn from: ``work``'s fact questions over its bank (with round 2's
    two-document kinds from ``kinds`` after them, v16, only those of ``plan_kinds`` when given), then each ``extra`` folder's
    questions over its own bank (read with ``extra_single``, the single-fact lessons those questions were asked with, else
    ``lessons``)."""
    from cie.factbank.learn import Lessons
    from cie.factbank.trained import TrainedBank

    new = kinds_multi(_jsonl(kinds), plan_kinds) if kinds else []
    pairs = [(TrainedBank(work / "factbank_v2.sqlite", lessons), fact_questions(qs) + new)]
    for w in extra:
        pairs.append((TrainedBank(w / "factbank_v2.sqlite", Lessons.load(extra_single) if extra_single else lessons),
                      [{**q, "family": q.get("family", "multi")} for q in _jsonl(w / "questions.jsonl")]))
    return pairs


def train(work: Path, out: Path, extra: list[Path] = (), glossary: Path | None = None, extra_single: Path | None = None,
          workers: int = 1, log=print, v16: bool = False, kinds: Path | None = None, per_family: int = PER_FAMILY,
          seed: int = KINDS_SEED, plan_kinds: list[str] | None = None) -> dict[str, Any]:
    """Train the three parts on ``work`` (questions.jsonl over its v2 bank), the plan lessons also on each ``extra`` folder's
    questions over its own bank (read with ``extra_single``, the single-fact lessons those questions were asked with). Writes
    ``single_lessons.json``, ``plan_lessons.json`` and ``router.json`` to ``out``, and ``train_report.json`` with the sha256
    of each.

    With ``kinds`` (round 2's new questions over ``work``'s bank), the plan lessons also learn from its two-document kinds
    (those of ``plan_kinds`` when given); with ``v16`` (which needs ``kinds``), the router is fitted as ``fit_router16`` fits
    it."""
    import time

    from cie.factbank.learn import train as fit_single
    from cie.factbank.trained import TrainedBank

    if v16 and kinds is None:
        raise ValueError("v16 training needs the new kinds' questions (kinds)")
    out.mkdir(parents=True, exist_ok=True)
    qs = _jsonl(work / "questions.jsonl")
    t = time.perf_counter()
    single = single_questions(qs)
    lessons = fit_single(TrainedBank(work / "factbank_v2.sqlite"), single)
    lessons.save(out / "single_lessons.json")
    times = {"single": round(time.perf_counter() - t, 1)}
    t = time.perf_counter()
    plan = learn_plans_many(plan_pairs(work, lessons, qs, extra, extra_single, kinds, plan_kinds), str(glossary.resolve()) if glossary else "",
                            log=log)
    plan.save(out / "plan_lessons.json")
    times["plans"] = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    if v16:
        router, router_rep, sig_rows = fit_router16(work, out / "single_lessons.json", out / "plan_lessons.json", kinds, workers, per_family,
                                                    seed, log)
        write_jsonl(out / "router_signals.jsonl", sig_rows)
    else:
        router = fit_router(work, out / "single_lessons.json", out / "plan_lessons.json", qs, workers)
    router.save(out / "router.json")
    times["router"] = round(time.perf_counter() - t, 1)
    rep = {"work": str(work), "extra": [str(w) for w in extra], "glossary": str(glossary) if glossary else "",
           "single": {"questions": len(single), "trained_on": lessons.trained_on},
           "plans": plan.trained_on, "router": router.trained_on, "seconds": times}
    if kinds is not None:
        rep.update({"v16": v16, "kinds": str(kinds), "kinds_sha256": sha256(kinds), "plan_kinds": len(kinds_multi(_jsonl(kinds), plan_kinds)),
                    "plan_kinds_named": list(plan_kinds or [])})
        if v16:
            rep["router_sample_ids"] = router_rep["sample_ids"]
        rep["sha256"] = {f: sha256(out / f) for f in ("single_lessons.json", "plan_lessons.json", "router.json")}
    (out / "train_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def train_plans(work: Path, out: Path, kinds: Path, lessons_dir: Path | None = None, extra: list[Path] = (),
                glossary: Path | None = None, extra_single: Path | None = None, log=print, plan_kinds: list[str] | None = None
                ) -> dict[str, Any]:
    """v16: the plan lessons alone, as ``train`` fits them with ``kinds`` (and ``plan_kinds``), on the single-fact lessons in
    ``lessons_dir`` (else ``out``). Writes ``plan_lessons.json`` and ``plans_report.json`` (what they learned from, the
    sha256 of every input and of the lessons) to ``out``."""
    import time

    from cie.factbank.learn import Lessons

    single = (lessons_dir or out) / "single_lessons.json"
    out.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    pairs = plan_pairs(work, Lessons.load(single), _jsonl(work / "questions.jsonl"), extra, extra_single, kinds, plan_kinds)
    plan = learn_plans_many(pairs, str(glossary.resolve()) if glossary else "", log=log)
    plan.save(out / "plan_lessons.json")
    new = kinds_multi(_jsonl(kinds), plan_kinds)
    rep = {"work": str(work), "questions_sha256": sha256(work / "questions.jsonl"), "kinds": str(kinds), "kinds_sha256": sha256(kinds),
           "plan_kinds_named": list(plan_kinds or []), "plan_kinds": len(new),
           "plan_kinds_by_kind": dict(sorted(Counter(q["kind"] for q in new).items())),
           "extra": [{"work": str(w), "questions_sha256": sha256(w / "questions.jsonl")} for w in extra],
           "extra_single": str(extra_single) if extra_single else "", "extra_single_sha256": sha256(extra_single) if extra_single else "",
           "glossary": str(glossary) if glossary else "", "glossary_sha256": sha256(glossary) if glossary else "",
           "single": str(single), "single_sha256": sha256(single), "trained_on": plan.trained_on,
           "seconds": round(time.perf_counter() - t, 1), "sha256": {"plan_lessons.json": sha256(out / "plan_lessons.json")}}
    (out / "plans_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain_train")
    ap.add_argument("cmd", choices=["train", "router", "plans"])
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--extra", nargs="*", default=[], type=Path, help="earlier training folders whose questions join the plan lessons")
    ap.add_argument("--extra-single", type=Path, help="the single-fact lessons the extra folders' questions were asked with")
    ap.add_argument("--glossary", type=Path)
    ap.add_argument("--workers", type=int, default=1, help="processes for the router's signals")
    ap.add_argument("--v16", action="store_true", help="fit the router on the v16 brain's signals, with a sample of --kinds (round 2)")
    ap.add_argument("--kinds", type=Path, help="round 2's new questions over --work's bank (cie.eval.brain2_questions)")
    ap.add_argument("--per-family", type=int, default=PER_FAMILY, help=f"v16: new questions per family for the router (default {PER_FAMILY})")
    ap.add_argument("--seed", type=int, default=KINDS_SEED, help=f"v16: the seed of that sample (default {KINDS_SEED})")
    ap.add_argument("--lessons", type=Path, help="router, plans: read the lessons from this folder instead of --out")
    ap.add_argument("--plan-kinds", nargs="*", default=None, help="train, plans: only these two-document kinds of --kinds (default: all)")
    a = ap.parse_args(argv)
    if a.v16 and a.kinds is None:
        ap.error("--v16 needs --kinds")
    if a.cmd == "plans":
        if a.kinds is None:
            ap.error("plans needs --kinds")
        rep = train_plans(a.work, a.out, a.kinds, a.lessons, a.extra, a.glossary, a.extra_single, plan_kinds=a.plan_kinds)
        print(json.dumps(rep, indent=1))
        return rep
    if a.cmd == "router":  # the router alone, on lessons already in --out (or --lessons)
        src = a.lessons or a.out
        single, plans = src / "single_lessons.json", src / "plan_lessons.json"
        if not a.v16:
            router = fit_router(a.work, single, plans, _jsonl(a.work / "questions.jsonl"), a.workers)
            router.save(a.out / "router.json")
            print(json.dumps(router.trained_on))
            return router.trained_on
        a.out.mkdir(parents=True, exist_ok=True)
        router, rep, sig_rows = fit_router16(a.work, single, plans, a.kinds, a.workers, a.per_family, a.seed)
        router.save(a.out / "router.json")
        write_jsonl(a.out / "router_signals.jsonl", sig_rows)
        rep["sha256"] = {"router.json": sha256(a.out / "router.json")}
        (a.out / "router_report.json").write_text(json.dumps(rep, indent=1))
        print(json.dumps(router.trained_on))
        return router.trained_on
    rep = train(a.work, a.out, a.extra, a.glossary, a.extra_single, a.workers, v16=a.v16, kinds=a.kinds, per_family=a.per_family,
                seed=a.seed, plan_kinds=a.plan_kinds)
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
