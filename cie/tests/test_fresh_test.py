"""The fresh test's harness (``cie.eval.fresh_test``) without a model or a bank: the benchmark's questions read into
this harness's form, the ones left out, the fixed sample, an arm's rows copied to the sample, the bench score from the
judge's verdicts, and the plan's rules."""

from __future__ import annotations

import json

from cie.eval import brain50k as K
from cie.eval import fresh_test as F


def _bench(tmp_path, n=12):
    rows = []
    for i in range(n):
        kind = "info_not_found" if i % 6 == 5 else "basic" if i % 2 else "semantic"
        rows.append({"question_id": f"qst_{i:04d}", "question_type": kind, "source_types": "['github']", "question": f"Question {i}?",
                     "expected_doc_ids": "[]" if kind == "info_not_found" else f"['dsid_{i}', 'dsid_x{i}']" if i % 4 == 0 else f"['dsid_{i}']",
                     "gold_answer": f"Answer {i}.", "answer_facts": f"['Fact {i} a.', 'Fact {i} b.']"})
    (tmp_path / "questions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return F.benchmark_questions(tmp_path)


def test_the_benchmarks_questions_in_this_harness_form(tmp_path):
    qs = _bench(tmp_path)
    q = qs[1]
    assert q == {"id": "qst_0001", "group": "bench", "family": "bench", "kind": "basic", "question": "Question 1?", "systems": ["github"],
                 "expected": {"gold": "Answer 1.", "facts": ["Fact 1 a.", "Fact 1 b."]}, "gold_docs": ["dsid_1"]}
    assert qs[0]["gold_docs"] == ["dsid_0", "dsid_x0"] and qs[5]["gold_docs"] == [] and qs[5]["expected"]["unanswerable"] is True
    assert F._list("['a', 'b']") == ["a", "b"] and F._list(["a"]) == ["a"] and F._list("") == [] and F._list("not a list") == ["not a list"]
    test, tried = F.split_tried(qs, {"dsid_1", "dsid_3", "dsid_0"})
    assert [q["id"] for q in tried] == ["qst_0001", "qst_0003"], "every gold document was in the earlier haystack: left out"
    assert len(test) == 10 and "qst_0000" in {q["id"] for q in test} and "qst_0005" in {q["id"] for q in test}, \
        "one gold document outside it, or none at all: in the test"


def test_the_sample_keeps_every_kind_in_its_share(tmp_path):
    qs = _bench(tmp_path, 60)
    s = F.sample(qs, 20)
    assert len(s) == 20 and s == F.sample(qs, 20) and [q["id"] for q in s] == sorted(q["id"] for q in s), "fixed, and in the questions' order"
    count = lambda xs, k: sum(q["kind"] == k for q in xs)  # noqa: E731
    assert (count(qs, "info_not_found"), count(qs, "basic"), count(qs, "semantic")) == (10, 20, 30)
    assert (count(s, "info_not_found"), count(s, "basic"), count(s, "semantic")) in ((3, 7, 10), (4, 6, 10), (3, 6, 11), (4, 7, 9))
    assert F.sample(qs, 500) == qs and F.sample(qs, 20, seed=1) != s


def _folder(path, qs):
    path.mkdir(parents=True, exist_ok=True)
    (path / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))


def _answers(path, name, rows):
    (path / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_runs_and_the_samples_rows(tmp_path):
    assert F.names(F.CORE) == ["reasoner", "agent", "rag"] and F.names(F.EXTRA) == ["reasoner.s1", "reasoner.s2", "nobrain", "notools"]
    qs = _bench(tmp_path / "bench_src", 12) if (tmp_path / "bench_src").mkdir() is None else []
    work = tmp_path / "w_bench"
    _folder(work, qs)
    _folder(F.sub_dir(work), qs[:4])
    _answers(work, "factbank_v19", [{"id": q["id"], "answer": "brain"} for q in qs])
    _answers(work, "reasoner", [{"id": q["id"], "answer": "model"} for q in qs[:3]])  # a run stopped half way
    _answers(work, "judge_reasoner", [{"id": qs[0]["id"], "arm": "reasoner", "correct": True, "completeness": 1.0, "failed": False}])
    got = F.fill_sample(work)
    assert got == {"v19": 4, "reasoner": 3, "agent": 0, "rag": 0, "judge_v19": 0, "judge_reasoner": 1, "judge_agent": 0, "judge_rag": 0}
    sub = F.sub_dir(work)
    assert [r["answer"] for r in K._rows(sub / "factbank_v19.jsonl").values()] == ["brain"] * 4 and not (sub / "agent.jsonl").exists()
    _answers(sub, "reasoner", [{"id": qs[0]["id"], "answer": "kept"}])
    F.fill_sample(work)
    assert K._rows(sub / "reasoner.jsonl")[qs[0]["id"]]["answer"] == "kept", "a row the sample already has is not replaced"
    assert F.labels_of(work) == ["v19", "reasoner"] and F.labels_of(sub) == ["v19", "reasoner"]


def test_the_bench_score_reads_the_judge(tmp_path):
    (tmp_path / "src").mkdir()
    qs = _bench(tmp_path / "src", 12)
    work = tmp_path / "w_bench"
    _folder(work, qs)
    rows = [{"id": q["id"], "answer": "x", "steps": [{"tool": "read", "result": {"id": q["gold_docs"][0] if q["gold_docs"] and i % 2 else "other"}}],
             "prompt_tokens": 1000, "output_tokens": 200, "ms": 50.0} for i, q in enumerate(qs)]
    _answers(work, "reasoner", rows)
    verdicts = [{"id": q["id"], "arm": "reasoner", "correct": i % 3 != 0, "completeness": 0.5, "failed": False} for i, q in enumerate(qs[:10])]
    verdicts.append({"id": qs[10]["id"], "arm": "reasoner", "correct": None, "completeness": None, "failed": True})
    _answers(work, "judge_reasoner", verdicts)
    rep = F.score_bench(work, ["reasoner", "agent"])
    a = rep["arms"]["reasoner"]
    assert set(rep["arms"]) == {"reasoner"} and rep["questions"] == 12 and (a["answered"], a["judged"], a["not_judged"]) == (12, 10, 2)
    assert a["correct"] == 0.6 and a["completeness"] == 0.5, "an unreadable verdict is not counted as wrong"
    assert a["correct_by_kind"]["info_not_found"] == 1.0 and set(a["correct_by_kind"]) == {"basic", "semantic", "info_not_found"}
    assert a["reached"] == 0.4, "the gold documents named anywhere in the row (4 of 10); a question with none is not counted"
    assert F.reached(qs[0], {"reads": ["dsid_0"]}) == 0.5 and F.reached(qs[5], {"x": 1}) is None
    assert (a["prompt_tokens_per_question"], a["output_tokens_per_question"], a["ms_per_question"]) == (1000.0, 200.0, 50.0)
    items = F.to_judge(work, "reasoner")
    assert len(items) == 12 and items[0]["facts"] == ["Fact 0 a.", "Fact 0 b."] and items[0]["arm"] == "reasoner"
    calls = []

    def model(convs):
        calls.append(len(convs))
        return [{"text": '{"facts": [true, true], "correct": true}'} for _ in convs]

    out = F.judge_folder(work, ["reasoner"], model, log=lambda *_: None)
    assert out == {"reasoner": {"answers": 12, "judged_now": 2}} and calls == [2], "only what has no verdict yet is judged"
    assert F.score_bench(work, ["reasoner"])["arms"]["reasoner"]["judged"] == 12


def _report(gen, bench, sub=None, bsub=None):
    fams = ["complex", "counts", "single"]
    arm = lambda m, cx, fnf=0.0: {"mean_of_families": m, "by_family": {"complex": cx, "counts": m, "single": m}, "false_not_found": fnf}  # noqa: E731
    b = lambda c, nf=0.8: {"correct": c, "correct_by_kind": {"info_not_found": nf}}  # noqa: E731
    return {"gen": {"families": fams, "arms": {k: arm(*v) for k, v in gen.items()}}, "bench": {"arms": {k: b(*v) for k, v in bench.items()}},
            "gen_sub": {"families": fams, "arms": {k: arm(v, 0.9) for k, v in (sub or {}).items()}},
            "bench_sub": {"arms": {k: b(v) for k, v in (bsub or {}).items()}}}


def test_the_plans_rules():
    rules = F.rules()
    assert len(rules) == 8 and all(what and callable(fn) for what, fn in rules.values())
    good = _report({"v19": (0.90, 0.2), "reasoner": (0.92, 0.85, 0.02), "agent": (0.80, 0.5)},
                   {"v19": (0.3,), "reasoner": (0.70, 0.75), "agent": (0.65,), "rag": (0.60,)},
                   {"reasoner": 0.92, "reasoner.s1": 0.91, "reasoner.s2": 0.93}, {"reasoner": 0.70, "reasoner.s1": 0.66, "reasoner.s2": 0.72})
    assert {k: fn(good) for k, (_, fn) in rules.items()} == dict.fromkeys(rules, True)
    bad = _report({"v19": (0.90, 0.2), "reasoner": (0.88, 0.70, 0.08), "agent": (0.86, 0.5)},
                  {"v19": (0.3,), "reasoner": (0.60, 0.5), "agent": (0.65,), "rag": (0.58,)},
                  {"reasoner": 0.92, "reasoner.s1": 0.88, "reasoner.s2": 0.93}, {"reasoner": 0.70, "reasoner.s1": 0.66, "reasoner.s2": 0.72})
    assert {k: fn(bad) for k, (_, fn) in rules.items()} == dict.fromkeys(rules, False) | {"8 seeds agree": False}
    two = _report({"v19": (0.9, 0.2), "reasoner": (0.92, 0.85)}, {"reasoner": (0.7,)}, {"reasoner": 0.92, "reasoner.s1": 0.91}, {"reasoner": 0.7})
    assert rules["8 seeds agree"][1](two) is False, "two seeds are not three"


def test_the_report_says_what_is_not_run_yet(tmp_path):
    from cie.eval import complex_questions as C

    (tmp_path / "src").mkdir()
    bench = _bench(tmp_path / "src", 12)
    gen = [{"id": "c-1", "family": C.FAMILY, "group": "complex", "kind": "k", "steps": 2, "answer_type": "value", "question": "Q?",
            "expected": {"value": "Maya Chen"}, "gold_docs": [], "pieces": []}]
    work = tmp_path / "w"
    _folder(work, gen)
    _folder(F.bench_dir(work), bench)
    _answers(work, "factbank_v19", [{"id": "c-1", "answer": "Maya Chen", "route": "plan"}])
    _answers(F.bench_dir(work), "factbank_v19", [{"id": q["id"], "answer": "x"} for q in bench])
    rep = F.score(work)
    assert rep["rules"] == dict.fromkeys(F.rules(), None), "no model arm has answered: no rule is decided"
    assert rep["gen"]["arms"]["v19"]["by_family"]["complex"] == 1.0 and rep["bench"]["arms"]["v19"]["judged"] == 0
    text = (work / "report_fresh.md").read_text()
    assert text.count("not run yet") == 8 and "Not labelled yet" in text and "| v19 |" in text
    assert json.loads((work / "report_fresh.json").read_text())["rules"] == rep["rules"]
