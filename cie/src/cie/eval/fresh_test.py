"""The fresh test of the company brain (docs/FACTBANK_FRESH_PLAN.md): questions the brain has never answered, on
documents the last test did not use.

The 635 questions of the 50,000-document test are development data now: the brain's v19 and the model's new loop were
made after reading their answers. This test has two question sets on one new haystack:

- **bench:** the benchmark's own questions (EnterpriseRAG-Bench ``questions.jsonl``: written by its authors, with a
  reference answer, the facts a right answer states and the documents it rests on). No brain arm has answered them. A
  free-text answer has no exact check, so a model judges it (``cie.eval.judge``), and people label a sample of the
  judge's verdicts.
- **gen:** generated questions with checkable answers, drawn with new seeds from the new documents by the generators of
  the earlier tests (``brain2_test.draw2``, ``complex_questions.draw``).

Steps:
- **draw:** the haystack is the documents the benchmark's questions rest on and fresh documents up to 50,000, every
  source in its share; no document of the 50,000-document test's haystack is drawn (``brain50k.grow``).
- **questions:** ``W/questions.jsonl`` (gen) and ``W_bench/questions.jsonl`` (bench), and a fixed sample of each
  (``W_sub``, ``W_bench_sub``); the folders share one bank.
- **run:** with one load of the model (``brain50k.ask_llm``): the core arms on every question (the model on the brain,
  the model with search alone, plain search); then, on the samples, two more seeds of the model on the brain and the
  two ablations (without the brain; without the tools); then the judge.
- **judge:** each arm's answers to the bench questions judged (``cie.eval.judge``).
- **score:** gen by its exact checks, per family; bench by the judge (correct, completeness), per question type, with
  how often the documents an answer rests on were reached; the samples the same way; the plan's rules.

    python -m cie.eval.fresh_test draw --index INDEX --root BENCH --old OLD_HAYSTACK.json --out W
    python -m cie.eval.fresh_test questions --work W --root BENCH
    python -m cie.eval.brain50k ask --arm v19 --work W W_bench --workers 10
    python -m cie.eval.fresh_test run --work W W_bench --model qwen3.8-27b --workers 10
    python -m cie.eval.fresh_test score --work W --bench W_bench
"""

from __future__ import annotations

import argparse
import ast
import gzip
import json
import os
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from cie.eval import brain50k as K
from cie.eval import judge as J

N_DOCS = 50_000
SEED = 6060  # the draw
QSEED = 6061  # the generated questions
CSEED = 6062  # the complex questions
PLAN = Path("docs/benchmarks/fresh/plan")
BRAIN = "v19"
CORE = (("reasoner", 0), ("agent", 0), ("rag", 0))  # (arm, seed) asked on every question, in this order
EXTRA = (("reasoner", 1), ("reasoner", 2), ("nobrain", 0), ("notools", 0))  # asked on the samples only
SUB = 100  # questions of each sample
SUBSEED = 6063
JUDGED_FAMILIES = ("prose",)  # generated families with free-text answers: judged as well as scored
# the generated kinds of the earlier tests (``brain2_test.MIX15`` and ``MIX16``) without the writers' questions (free
# text, descriptions and held-out ones were written by hand for other documents; the benchmark's own questions take
# their place)
MIX15 = {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20}
MIX16 = {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3,
         "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}
PER_KIND = 12  # complex questions of each kind


def _list(v: Any) -> list[Any]:
    """A list the benchmark writes as text ("['a', 'b']")."""
    if isinstance(v, list):
        return v
    if not v:
        return []
    try:
        out = ast.literal_eval(str(v))
    except (ValueError, SyntaxError):
        return [str(v)]
    return list(out) if isinstance(out, list | tuple) else [out]


def benchmark_questions(root: Path, name: str = "questions.jsonl") -> list[dict[str, Any]]:
    """The benchmark's own questions in this harness's form: the reference answer and its facts as what is expected,
    the documents it rests on as the gold documents. A question of the type "info_not_found" has none: the right answer
    says the documents do not hold it."""
    out = []
    for line in (Path(root) / name).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        kind = str(r["question_type"])
        expected: dict[str, Any] = {"gold": str(r.get("gold_answer") or ""), "facts": [str(f) for f in _list(r.get("answer_facts"))]}
        if kind == "info_not_found":
            expected["unanswerable"] = True
        out.append({"id": str(r["question_id"]), "group": "bench", "family": "bench", "kind": kind, "question": str(r["question"]),
                    "expected": expected, "gold_docs": [str(d) for d in _list(r.get("expected_doc_ids"))],
                    "systems": [str(s) for s in _list(r.get("source_types"))]})
    return out


def split_tried(qs: list[dict[str, Any]], old: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The questions of the test, and those left out of it: a question every gold document of which was in the earlier
    haystack could be asked there, so it is kept for trying the harness and never counted."""
    tried = [q for q in qs if q["gold_docs"] and set(q["gold_docs"]) <= old]
    ids = {q["id"] for q in tried}
    return [q for q in qs if q["id"] not in ids], tried


def write_draw(root: Path, index_path: Path, old_haystack: Path, out: Path, n: int = N_DOCS, seed: int = SEED,
               load: Callable[[list[str]], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """The fresh haystack: the gold documents of the benchmark's questions that are in the test (``split_tried``) and
    fresh documents up to ``n``; none of the earlier haystack's other documents."""
    from cie.eval import brain_draw

    index = brain_draw.load_folder_index(index_path, root)
    old = set(json.loads(_read(old_haystack))["dsids"])
    qs, tried = split_tried(benchmark_questions(root), old)
    gold = sorted({d for q in qs for d in q["gold_docs"]})
    if missing := [d for d in gold if d not in index]:
        raise ValueError(f"the index lacks {len(missing)} gold documents of the benchmark's questions")
    ids, info = K.grow(index, gold, old - set(gold), load or brain_draw._loader(root, index), n=n, seed=seed)
    out.mkdir(parents=True, exist_ok=True)
    hay = out / "haystack.json"
    hay.write_text(json.dumps({"root": str(root), "n_docs": len(ids), "seed": seed, "base_questions": len(qs), "documents": len(ids),
                               "index": str(index_path), "dsids": ids}))
    link = out / "index.json"
    if not (link.exists() or link.is_symlink()):
        link.symlink_to(index_path.resolve())
    rep = {**info, "n": n, "dsids_sha256": K.dsids_sha(ids), "old_haystack_sha256": K.dsids_sha(old), "from_old_haystack": len(set(ids) & old),
           "gold_documents": len(gold), "bench_questions": len(qs), "bench_left_out": len(tried),
           "by_source": brain_draw._by_source(index, ids), "index": str(index_path)}
    (out / "draw_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def _read(path: Path) -> str:
    return gzip.open(path, "rt").read() if str(path).endswith(".gz") else Path(path).read_text()


def bench_dir(work: Path) -> Path:
    return work.parent / f"{work.name}_bench"


def sub_dir(work: Path) -> Path:
    return work.parent / f"{work.name}_sub"


def sample(qs: list[dict[str, Any]], n: int = SUB, seed: int = SUBSEED) -> list[dict[str, Any]]:
    """``n`` of the questions, every kind in its share (largest remainders), drawn by ``seed``; in the questions' order."""
    import random

    by: dict[str, list[dict[str, Any]]] = {}
    for q in qs:
        by.setdefault(f"{q['family']}/{q['kind']}", []).append(q)
    n = min(n, len(qs))
    raw = {k: n * len(v) / len(qs) for k, v in by.items()}
    take = {k: int(x) for k, x in raw.items()}
    for k in sorted(raw, key=lambda k: (take[k] - raw[k], k))[:n - sum(take.values())]:
        take[k] += 1
    picked = {q["id"] for k, v in sorted(by.items()) for q in random.Random(f"{seed}/{k}").sample(v, take[k])}
    return [q for q in qs if q["id"] in picked]


def write_questions(work: Path, root: Path, old_haystack: Path, seed: int = QSEED, cseed: int = CSEED, per_kind: int | None = None,
                    mix15: dict[str, int] | None = None, mix16: dict[str, int] | None = None,
                    log: Callable[[str], None] = print) -> dict[str, Any]:
    """``work``/questions.jsonl: generated questions on the fresh haystack (``brain2_test.draw2`` in ``MIX15`` and
    ``MIX16``, and the complex ones). ``work``_bench/questions.jsonl: the benchmark's own questions of the test. The
    bench folder links ``work``'s haystack, index and bank."""
    from cie.eval import brain2_questions as Q2
    from cie.eval import brain2_test as T2
    from cie.eval import brain_test as H
    from cie.eval import complex_questions as C

    hay = json.loads((work / "haystack.json").read_text())
    have = set(hay["dsids"])
    old = set(json.loads(_read(old_haystack))["dsids"])
    bench, tried = split_tried(benchmark_questions(root), old)
    if outside := [q["id"] for q in bench if not set(q["gold_docs"]) <= have]:
        raise ValueError(f"{len(outside)} of the benchmark's questions rest on documents outside the haystack")
    log(f"  reading {len(have):,} documents")
    docs = H.load_docs(work)
    gen, aside, rep = T2.draw2(docs, seed, dict(MIX15 if mix15 is None else mix15), dict(MIX16 if mix16 is None else mix16))
    cq, crep = C.draw(docs, per_kind or PER_KIND, cseed)
    gen = [{**q, "family": Q2.family(q)} for q in gen]
    b = bench_dir(work)
    folders = ((work, gen + cq, {"generated": rep, "complex": crep, "set_aside": len(aside)}),
               (b, bench, {"left_out_tried_on_the_old_haystack": [q["id"] for q in tried]}),
               (sub_dir(work), sample(gen + cq), {"sample_of": work.name}), (sub_dir(b), sample(bench), {"sample_of": b.name}))
    for folder, _, _ in folders[1:]:
        folder.mkdir(exist_ok=True)
        link_bank(work, folder)
    out = {}
    for folder, qs, extra in folders:
        text = "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in qs)
        (folder / "questions.jsonl").write_text(text)
        out[folder.name] = {"questions": len(qs), "by_family": dict(Counter(q["family"] for q in qs)),
                            "by_kind": dict(sorted(Counter(q["kind"] for q in qs).items())),
                            "questions_sha256": K.hashlib.sha256(text.encode()).hexdigest(), "dsids_sha256": K.dsids_sha(have), **extra}
        (folder / "questions_report.json").write_text(json.dumps(out[folder.name], indent=1))
    return out


def link_bank(work: Path, folder: Path) -> None:
    """The folder shares ``work``'s haystack, index and bank."""
    for n in ("haystack.json", "index.json", "factbank_v2.sqlite", "banks.json", "draw_report.json"):
        if (work / n).exists() and not (folder / n).exists():
            os.symlink((work / n).resolve(), folder / n)


# ------------------------------------------------------------------ asking: every arm with one load of the model
def names(pairs: Iterable[tuple[str, int]]) -> list[str]:
    """The answer file of each (arm, seed)."""
    return [K.arm_file(arm, seed) for arm, seed in pairs]


def fill_sample(work: Path, labels: Iterable[str] = (BRAIN, *names(CORE))) -> dict[str, int]:
    """The sample folder's answers (and the judge's verdicts) of the arms asked on every question, copied from
    ``work``: the sample's questions are ``work``'s, so its rows are not asked or judged twice. Rows already there are
    kept, except a verdict the judge could not give when the full folder has one."""
    sub = sub_dir(work)
    ids = [q["id"] for q in K._questions(sub)]
    out = {}
    labels = list(labels)
    for lab in [*labels, *(judge_file(x)[:-len(".jsonl")] for x in labels)]:
        src, dst = work / f"{K.FILES.get(lab, lab)}.jsonl", sub / f"{K.FILES.get(lab, lab)}.jsonl"
        have, full = K._rows(dst), K._rows(src)
        rows = [(have.get(i) if have.get(i) and not have[i].get("failed") else None) or full.get(i) or have.get(i) for i in ids]
        if any(r is not None for r in rows):
            K._write(dst, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if r is not None))
        out[lab] = sum(r is not None for r in rows)
    return out


def run(works: list[Path], generate: Any, tools: Any, settings: dict[str, Any], core: Iterable[tuple[str, int]] = CORE,
        extra: Iterable[tuple[str, int]] = EXTRA, limit: int | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """The core arms over the folders, then the extra ones over the folders' samples, with the model already loaded:
    the seed is set on the backend before each run (it is a sampling setting, not part of the loaded model). A run
    already complete is not asked again."""
    out = {}
    for stage, pairs, folders in (("core", core, works), ("extra", extra, [])):
        if stage == "extra":
            folders = [sub_dir(w) for w in works if (sub_dir(w) / "questions.jsonl").exists()]
            if missing := [w.name for w in works if not (sub_dir(w) / "questions.jsonl").exists()]:
                log(f"no sample folder for {', '.join(missing)}: its seeds and ablations are not asked")
            for w in works:
                if (sub_dir(w) / "questions.jsonl").exists() and list(extra):
                    log(f"sample of {w.name}: {fill_sample(w)}")
        for arm, seed in pairs:
            name, st = K.arm_file(arm, seed), {**settings, "seed": seed}
            if not any(K.left(folders, arm, name, limit).values()):
                log(f"{arm} seed {seed} ({stage}): every question already answered")
                continue
            K.check_settings(folders, arm if name == K.FILES[arm] else name, st)
            if hasattr(generate, "seed"):
                generate.seed = seed
            log(f"{arm} seed {seed} ({stage})")
            out[f"{stage}/{name}"] = K.ask_llm(folders, arm, generate, None if arm == "rag" else tools, name, None, limit, st, log)
    return out


# ------------------------------------------------------------------ judging
def judge_file(label: str) -> str:
    return f"judge_{label}.jsonl"


def to_judge(work: Path, label: str) -> list[dict[str, Any]]:
    """The answers of one arm that a judge reads: every bench question's, and the generated free-text questions'."""
    qs = [q for q in K._questions(work) if q["family"] == "bench" or q["family"] in JUDGED_FAMILIES]
    rows = K._rows(work / f"{K.FILES.get(label, label)}.jsonl")
    return J.items_of(qs, rows, label)  # the answer with the quotes that go with it


def judge_folder(work: Path, labels: Iterable[str], generate: Any, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Each arm's answers judged, appended to ``work``/judge_<label>.jsonl: a verdict already there is not asked again."""
    out = {}
    for label in labels:
        items = to_judge(work, label)
        path = work / judge_file(label)
        done = {(v["id"]): v for v in K._rows(path).values() if not v.get("failed")}
        todo = [x for x in items if x["id"] not in done]
        if todo:
            log(f"judging {label}: {len(todo)} answers ({work.name})")
            verdicts = J.judge(todo, generate, log=log)
            with path.open("a") as f:
                for v in verdicts:
                    f.write(json.dumps(v) + "\n")
        out[label] = {"answers": len(items), "judged_now": len(todo)}
    return out


# ------------------------------------------------------------------ scoring
def reached(q: dict[str, Any], row: dict[str, Any]) -> float | None:
    """The share of the question's gold documents that the answer's row names anywhere (what the brain read, what a tool
    returned, the passages a search gave); None when the question has no gold document."""
    gold = q.get("gold_docs") or []
    if not gold:
        return None
    text = json.dumps(row, ensure_ascii=False)
    return sum(d in text for d in gold) / len(gold)


def _mean(xs: Iterable[float | None]) -> float | None:
    xs = [float(x) for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def score_bench(work: Path, labels: Iterable[str]) -> dict[str, Any]:
    """The bench folder: each arm's judged correctness and completeness, over all questions and by question type, how
    many verdicts are missing, and the share of gold documents reached."""
    qs = K._questions(work)
    by_id = {q["id"]: q for q in qs}
    out: dict[str, Any] = {"folder": str(work), "questions": len(qs), "by_kind_count": dict(sorted(Counter(q["kind"] for q in qs).items())),
                           "arms": {}}
    for label in labels:
        rows = K._rows(work / f"{K.FILES.get(label, label)}.jsonl")
        if not rows:
            continue
        verdicts = {v["id"]: v for v in K._rows(work / judge_file(label)).values()}
        ok = {i: v for i, v in verdicts.items() if not v.get("failed") and i in by_id}
        kinds = sorted({q["kind"] for q in qs})
        out["arms"][label] = {
            "answered": sum(q["id"] in rows for q in qs), "judged": len(ok), "not_judged": sum(q["id"] in rows and q["id"] not in ok for q in qs),
            "correct": _mean(float(v["correct"]) for v in ok.values()),
            "completeness": _mean(v.get("completeness") for v in ok.values()),
            "correct_by_kind": {k: _mean(float(v["correct"]) for i, v in ok.items() if by_id[i]["kind"] == k) for k in kinds},
            "reached": _mean(reached(q, rows[q["id"]]) for q in qs if q["id"] in rows),
            "output_tokens_per_question": _mean(r.get("output_tokens") for r in rows.values() if r.get("output_tokens") is not None),
            "prompt_tokens_per_question": _mean(r.get("prompt_tokens") for r in rows.values() if r.get("prompt_tokens") is not None),
            "ms_per_question": _mean(r.get("ms") for r in rows.values() if r.get("ms") is not None)}
    return out


def score_gen(work: Path, labels: Iterable[str]) -> dict[str, Any]:
    """The generated folder by its exact checks (``brain50k.score_folder``), with the mean over the families it has."""
    rep = K.score_folder(work, labels)
    fams = sorted(rep["by_family_count"])
    for _lab, a in rep["arms"].items():
        got = [a["by_family"].get(f) for f in fams if f != "complex"]
        a["mean_of_families"] = round(sum(got) / len(got), 4) if got and all(x is not None for x in got) else None
    rep["families"] = fams
    return rep


def seeds_of(rep_arms: dict[str, Any], arm: str, key: Callable[[dict[str, Any]], float | None]) -> list[float]:
    """One number of each seed's run of an arm (the file of seed 0 is the arm's own name)."""
    return [x for lab, a in rep_arms.items() if K.arm_of(lab) == arm and (x := key(a)) is not None]


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def rules() -> dict[str, tuple[str, Callable[[dict[str, Any]], bool]]]:
    """The plan's rules (docs/FACTBANK_FRESH_PLAN.md), each with what it says. Rules 1 to 7 read the arms asked on
    every question (seed 0); rule 8 reads the three seeds on the samples."""
    def gen(rep: dict[str, Any], arm: str) -> float:
        return _avg(seeds_of(rep["gen"]["arms"], arm, lambda a: a["mean_of_families"]))  # type: ignore[return-value]

    def fam(rep: dict[str, Any], arm: str, f: str) -> float:
        return _avg(seeds_of(rep["gen"]["arms"], arm, lambda a: a["by_family"].get(f)))  # type: ignore[return-value]

    def bench(rep: dict[str, Any], arm: str, k: str = "correct") -> float:
        return _avg(seeds_of(rep["bench"]["arms"], arm, lambda a: a[k]))  # type: ignore[return-value]

    def no_harm(rep: dict[str, Any]) -> bool:
        fams = [f for f in rep["gen"]["families"] if f != "complex"]
        return gen(rep, "reasoner") >= gen(rep, BRAIN) - 0.01 and all(fam(rep, "reasoner", f) >= fam(rep, BRAIN, f) - 0.03 for f in fams)

    def seeds_agree(rep: dict[str, Any]) -> bool:
        xs = seeds_of(rep["gen_sub"]["arms"], "reasoner", lambda a: a["mean_of_families"])
        ys = seeds_of(rep["bench_sub"]["arms"], "reasoner", lambda a: a["correct"])
        return len(xs) >= 3 and len(ys) >= 3 and max(xs) - min(xs) <= 0.03 and max(ys) - min(ys) <= 0.06

    return {
        "1 no harm": ("generated: the model on the brain is within 0.01 of the brain alone on the mean, and within 0.03 on every family", no_harm),
        "2 complex": ("generated: the model on the brain scores 0.80 or more on the complex questions", lambda r: fam(r, "reasoner", "complex") >= 0.80),
        "3 the bank helps": ("generated: the model on the brain beats the model with search alone by 0.05 or more",
                             lambda r: gen(r, "reasoner") >= gen(r, "agent") + 0.05),
        "4 natural questions": ("bench: the model on the brain is judged right at least as often as the model with search alone",
                                lambda r: bench(r, "reasoner") >= bench(r, "agent")),
        "5 beats plain search": ("bench: the model on the brain is judged right more often than plain search by 0.05 or more",
                                 lambda r: bench(r, "reasoner") >= bench(r, "rag") + 0.05),
        "6 says when it does not know": ("bench: on the questions the documents cannot answer, the model on the brain is judged right on 0.70 or more",
                                         lambda r: _avg(seeds_of(r["bench"]["arms"], "reasoner", lambda a: a["correct_by_kind"].get("info_not_found"))) >= 0.70),
        "7 false not found": ("generated: the model on the brain says \"not found\" on at most 0.05 of the answerable questions",
                              lambda r: _avg(seeds_of(r["gen"]["arms"], "reasoner", lambda a: a["false_not_found"])) <= 0.05),
        "8 seeds agree": ("on the samples, three seeds of the model on the brain differ by at most 0.03 (generated mean) and 0.06 (bench, judged right)",
                          seeds_agree),
    }


AGREEMENT = 0.85  # the judge's agreement with people below which rules 4 to 6 are not decided by it
JUDGED_RULES = ("4 natural questions", "5 beats plain search", "6 says when it does not know")


def margins() -> dict[str, tuple[str, Callable[[dict[str, Any]], float]]]:
    """How far each of rules 1 to 7 is from its line (met when 0 or more), and the set its numbers come from ("gen" or
    "bench"): a rule decided by less than the seeds' spread on that set is undecided when rule 8 fails."""
    def mean(rep: dict[str, Any], part: str, arm: str, key: Callable[[dict[str, Any]], Any]) -> float:
        return _avg(seeds_of(rep[part]["arms"], arm, key))  # type: ignore[return-value]

    def g(r: dict[str, Any], arm: str) -> float:
        return mean(r, "gen", arm, lambda a: a["mean_of_families"])

    def f(r: dict[str, Any], arm: str, fam: str) -> float:
        return mean(r, "gen", arm, lambda a: a["by_family"].get(fam))

    def b(r: dict[str, Any], arm: str) -> float:
        return mean(r, "bench", arm, lambda a: a["correct"])

    def no_harm(r: dict[str, Any]) -> float:
        fams = [x for x in r["gen"]["families"] if x != "complex"]
        return min([g(r, "reasoner") - g(r, BRAIN) + 0.01, *(f(r, "reasoner", x) - f(r, BRAIN, x) + 0.03 for x in fams)])

    return {
        "1 no harm": ("gen", no_harm),
        "2 complex": ("gen", lambda r: f(r, "reasoner", "complex") - 0.80),
        "3 the bank helps": ("gen", lambda r: g(r, "reasoner") - g(r, "agent") - 0.05),
        "4 natural questions": ("bench", lambda r: b(r, "reasoner") - b(r, "agent")),
        "5 beats plain search": ("bench", lambda r: b(r, "reasoner") - b(r, "rag") - 0.05),
        "6 says when it does not know": ("bench", lambda r: mean(r, "bench", "reasoner", lambda a: a["correct_by_kind"].get("info_not_found")) - 0.70),
        "7 false not found": ("gen", lambda r: 0.05 - mean(r, "gen", "reasoner", lambda a: a["false_not_found"])),
    }


def spreads(rep: dict[str, Any]) -> dict[str, float | None]:
    """The spread of the three seeds of the model on the brain on the samples: generated mean, bench judged right."""
    out: dict[str, float | None] = {}
    for part, sub, key in (("gen", "gen_sub", "mean_of_families"), ("bench", "bench_sub", "correct")):
        xs = seeds_of(rep.get(sub, {}).get("arms", {}), "reasoner", lambda a, key=key: a[key])
        out[part] = round(max(xs) - min(xs), 4) if len(xs) >= 3 else None
    return out


def decide(rep: dict[str, Any], agreement: dict[str, Any] | None) -> tuple[dict[str, bool | None], dict[str, str]]:
    """The rules as the plan decides them: each met or not by its numbers; then rules 4 to 6 undecided until the
    judge agrees with people on ``AGREEMENT`` of their labels; then, when rule 8 fails, every rule decided by less than
    the seeds' spread undecided. Returns the rules and why each undecided one is."""
    met: dict[str, bool | None] = {}
    why: dict[str, str] = {}
    for name, (_what, fn) in rules().items():
        try:
            met[name] = bool(fn(rep))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            met[name], why[name] = None, "an arm it needs has not answered"
    agree = (agreement or {}).get("agree")
    for name in JUDGED_RULES:
        if met.get(name) is not None and (agree is None or agree < AGREEMENT):
            met[name] = None
            why[name] = (f"the judge agrees with people on {agree:.2f} of their labels, below {AGREEMENT}" if agree is not None
                         else "the judge has not been checked against people's labels yet")
    if met.get("8 seeds agree") is False:
        spread = spreads(rep)
        for name, (part, fn) in margins().items():
            try:
                m = fn(rep)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            if met.get(name) is not None and spread[part] is not None and abs(m) < spread[part]:
                met[name] = None
                why[name] = f"decided by {abs(m):.3f}, less than the seeds' spread ({spread[part]:.3f})"
    return met, why


def labels_of(work: Path) -> list[str]:
    """The arms that answered in a folder: the brain alone and every run of the model's arms that left a file."""
    return [lab for lab in dict.fromkeys(("v18", BRAIN, *names(CORE), *names(EXTRA))) if (work / f"{K.FILES.get(lab, lab)}.jsonl").exists()]


def score(work: Path, bench: Path | None = None, agreement: dict[str, Any] | None = None) -> dict[str, Any]:
    bench = bench or bench_dir(work)
    rep: dict[str, Any] = {"gen": score_gen(work, labels_of(work)), "bench": score_bench(bench, labels_of(bench))}
    for key, full in (("gen_sub", work), ("bench_sub", bench)):
        sub = sub_dir(full)
        if (sub / "questions.jsonl").exists():
            fill_sample(full)
            rep[key] = score_gen(sub, labels_of(sub)) if key == "gen_sub" else score_bench(sub, labels_of(sub))
    rep["rules"], rep["undecided"] = decide(rep, agreement)
    rep["spreads"] = spreads(rep)
    rep["judge_agreement"] = agreement
    (work / "report_fresh.json").write_text(json.dumps(rep))
    (work / "report_fresh.md").write_text(to_markdown(rep))
    return rep


def _f(x: Any) -> str:
    return "n/a" if x is None else f"{x:.3f}" if isinstance(x, float) else str(x)


def _gen_table(g: dict[str, Any]) -> list[str]:
    fams = g["families"]
    out = ["| arm | mean | " + " | ".join(fams) + " | false not found |", "|---|---|" + "---|" * (len(fams) + 1)]
    for lab, a in g["arms"].items():
        out.append(f"| {lab} | {_f(a['mean_of_families'])} | " + " | ".join(_f(a["by_family"].get(f)) for f in fams) + f" | {_f(a['false_not_found'])} |")
    return out


def _bench_table(b: dict[str, Any]) -> list[str]:
    kinds = sorted(b["by_kind_count"])
    out = ["| arm | judged right | completeness | gold documents reached | not judged | " + " | ".join(kinds) + " |",
           "|---|---|---|---|---|" + "---|" * len(kinds)]
    for lab, a in b["arms"].items():
        out.append(f"| {lab} | {_f(a['correct'])} | {_f(a['completeness'])} | {_f(a['reached'])} | {a['not_judged']} | "
                   + " | ".join(_f(a["correct_by_kind"].get(k)) for k in kinds) + " |")
    return out


def to_markdown(rep: dict[str, Any]) -> str:
    g, b = rep["gen"], rep["bench"]
    out = ["# The fresh test: results", "", "## Rules", "", "| rule | what it says | met |", "|---|---|---|"]
    for name, (what, _fn) in rules().items():
        met = rep["rules"].get(name)
        why = rep.get("undecided", {}).get(name, "not run yet")
        out.append(f"| {name} | {what} | {f'undecided: {why}' if met is None else 'yes' if met else 'NO'} |")
    out += ["", f"## Generated questions ({g['questions']}), by exact check", "", *_gen_table(g)]
    out += ["", f"## The benchmark's own questions ({b['questions']}), by the judge", "", *_bench_table(b)]
    out += ["", "## Cost on the benchmark's questions", "", "| arm | prompt tokens a question | output tokens a question | ms a question |", "|---|---|---|---|"]
    for lab, a in b["arms"].items():
        out.append(f"| {lab} | {_f(a['prompt_tokens_per_question'])} | {_f(a['output_tokens_per_question'])} | {_f(a['ms_per_question'])} |")
    if "gen_sub" in rep:
        out += ["", f"## The samples: three seeds, and the model without the brain and without the tools ({rep['gen_sub']['questions']} generated)", "",
                *_gen_table(rep["gen_sub"])]
    if "bench_sub" in rep:
        out += ["", f"### The benchmark's questions of the sample ({rep['bench_sub']['questions']})", "", *_bench_table(rep["bench_sub"])]
    ag = rep.get("judge_agreement")
    out += ["", "## The judge against people's labels", ""]
    if ag and ag.get("answers"):
        out += [f"{ag['answers']} answers labelled; the judge and the person agree on {_f(ag.get('agree'))} (kappa {_f(ag.get('kappa'))}); "
                f"the judge says right where the person says wrong on {ag.get('judge_right_person_wrong')}, the other way on "
                f"{ag.get('judge_wrong_person_right')}."]
    else:
        out += ["Not labelled yet: `python -m cie.eval.judge sample` writes the sheet to label; the score step reads it with `--labels`."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.fresh_test", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw", help="the fresh haystack")
    d.add_argument("--index", type=Path, required=True)
    d.add_argument("--root", type=Path, required=True, help="the benchmark checkout")
    d.add_argument("--old", type=Path, required=True, help="the 50,000-document test's haystack.json (or its ids, gzipped)")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--n", type=int, default=N_DOCS)
    d.add_argument("--seed", type=int, default=SEED)
    q = sub.add_parser("questions", help="the generated questions, the benchmark's own, and a sample of each")
    q.add_argument("--work", type=Path, required=True)
    q.add_argument("--root", type=Path, required=True)
    q.add_argument("--old", type=Path, required=True)
    q.add_argument("--per-kind", type=int, default=None)
    r = sub.add_parser("run", help="the core arms, the extra ones on the samples, then the judge, with one load of the model")
    r.add_argument("--work", type=Path, nargs="+", required=True, help="the generated folder, then the bench folder")
    r.add_argument("--no-core", action="store_true", help="skip the arms asked on every question")
    r.add_argument("--no-extra", action="store_true", help="skip the seeds and ablations on the samples")
    r.add_argument("--no-judge", action="store_true")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--model", default="qwen3.8-27b")
    r.add_argument("--base-url", default=None)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--max-model-len", type=int, default=32768)
    r.add_argument("--gpu-mem", type=float, default=0.90)
    r.add_argument("--max-tokens", type=int, default=6144)
    r.add_argument("--max-num-seqs", type=int, default=None)
    r.add_argument("--effort", default="medium")
    r.add_argument("--no-thinking", action="store_true")
    s = sub.add_parser("score", help="the report and the plan's rules")
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--bench", type=Path, default=None)
    s.add_argument("--labels", type=Path, default=None, help="the sheet people labelled (judge sample), to compare the judge with")
    a = ap.parse_args(argv)
    if a.cmd == "draw":
        rep = write_draw(a.root, a.index, a.old, a.out, a.n, a.seed)
        print(json.dumps({k: rep[k] for k in ("documents", "base", "added", "short", "skipped", "from_old_haystack", "gold_documents",
                                              "bench_questions", "bench_left_out", "dsids_sha256")}, indent=1))
        return rep
    if a.cmd == "questions":
        rep = write_questions(a.work, a.root, a.old, per_kind=a.per_kind)
        print(json.dumps({f: {k: v[k] for k in ("questions", "by_family", "questions_sha256")} for f, v in rep.items()}, indent=1))
        return rep
    if a.cmd == "run":
        from cie.factbank import reasoner as R
        from cie.factbank import store

        settings = {"model_name": a.model, "effort": a.effort, "thinking": not a.no_thinking, "max_tokens": a.max_tokens,
                    "max_model_len": a.max_model_len, "seed": 0, "loop": K.LOOP, "brain": BRAIN}
        store.ensure(a.work[0] / "factbank_v2.sqlite", log=print)
        lessons = (K.LESSONS / "single_lessons.json", K.LESSONS / "plan_lessons.json", K.LESSONS / "router.json")
        tools = R.ToolPool(a.work[0] / "factbank_v2.sqlite", *lessons, workers=a.workers, v19=True)  # forked before the model
        gen = K.backend(a.model, a.base_url, max_model_len=a.max_model_len, gpu_mem=a.gpu_mem, max_tokens=a.max_tokens,
                        max_num_seqs=a.max_num_seqs, effort=a.effort, thinking=False if a.no_thinking else None, seed=0)
        rep: dict[str, Any] = {"runs": run(a.work, gen, tools, settings, () if a.no_core else CORE, () if a.no_extra else EXTRA, a.limit)}
        if not a.no_judge:
            if hasattr(gen, "seed"):
                gen.seed = 0
            rep["judge"] = {}
            for w in a.work:
                rep["judge"][w.name] = judge_folder(w, labels_of(w), gen)
                if (sub_dir(w) / "questions.jsonl").exists():
                    fill_sample(w)  # the verdicts just made are the sample's too
                    rep["judge"][sub_dir(w).name] = judge_folder(sub_dir(w), labels_of(sub_dir(w)), gen)
        print(json.dumps(rep, indent=1, default=str))
        return rep
    agreement = None
    bench = a.bench or bench_dir(a.work)
    if a.labels:
        verdicts = [v for lab in labels_of(bench) for v in K._rows(bench / judge_file(lab)).values()]
        with a.labels.open(newline="") as f:
            agreement = J.agreement(list(J.csv.DictReader(f)), verdicts)
    rep = score(a.work, bench, agreement)
    print(json.dumps({"rules": rep["rules"], "gen": {lab: v["mean_of_families"] for lab, v in rep["gen"]["arms"].items()},
                      "bench": {lab: v["correct"] for lab, v in rep["bench"]["arms"].items()}}, indent=1))
    return rep


if __name__ == "__main__":
    main()
