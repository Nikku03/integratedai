"""Training the company brain: plan lessons over several banks, and which questions each part learns from; v16: the router
on the v16 brain's signals with a sample of round 2's new kinds, and plan lessons with its two-document kinds."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime

import pytest

from cie.eval import brain_train as T
from cie.factbank import bank as B
from cie.factbank import plans as P
from cie.factbank.learn import Lessons
from cie.factbank.trained import TrainedBank
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", "")], meta=meta, updated=WHEN,
                     keys=list(keys))


def _bank(path, docs):
    B.build(path, [(d, {}) for d in docs], text_facts=True)
    return TrainedBank(path)


ONE = [_doc("d1", "linear", "Fix keycard reader timeouts", {"key": "ENG-11", "status": "In Progress", "assignee": "Omar Singh",
                                                              "due_date": "2026-03-20", "priority": "High"}, ["ENG-11"]),
       _doc("d2", "linear", "Rotate office wifi keys", {"key": "ENG-12", "status": "Done", "assignee": "Omar Singh",
                                                         "due_date": "2026-04-02", "priority": "Low"}, ["ENG-12"]),
       _doc("d4", "github", "Add retry to badge sync", {"pr_number": "4821", "author": "Maya Chen", "linked_linear": ["ENG-11"]})]
TWO = [_doc("e1", "linear", "Replace the badge printer", {"key": "OPS-3", "status": "Todo", "assignee": "Liam Chen",
                                                           "due_date": "2026-05-01", "dependencies": ["OPS-4"]}, ["OPS-3"]),
       _doc("e2", "linear", "Order spare keycards", {"key": "OPS-4", "status": "Done", "assignee": "Ava Lee", "due_date": "2026-04-10"},
            ["OPS-4"])]


def test_each_part_learns_from_the_questions_it_can_use():
    qs = [{"family": "single", "expected": {"value": "Omar Singh"}}, {"family": "single", "expected": {"names": ["A B"]}},
          {"family": "multi", "expected": {"ids": ["ENG-1"], "id_kind": "key"}}, {"family": "prose", "expected": {"facts": ["x y"]}},
          {"family": "not_found", "expected": {"not_found": True}}, {"family": "single", "expected": {"date": "2026-01-02"}}]
    assert [q["expected"] for q in T.single_questions(qs)] == [{"value": "Omar Singh"}, {"date": "2026-01-02"}]
    assert len(T.fact_questions(qs)) == 3, "single and multi questions with a value, a date or keys"


def test_plan_lessons_learn_over_several_banks_and_match_one_bank_training(tmp_path):
    one, two = _bank(tmp_path / "one.sqlite", ONE), _bank(tmp_path / "two.sqlite", TWO)
    q1 = [{"family": "multi", "question": "Who is assigned to the Linear issue that pull request #4821 is linked to?",
           "expected": {"value": "Omar Singh"}, "pieces": ["ENG-11", "Omar Singh"]},
          {"family": "single", "question": "What is the priority of ENG-12?", "expected": {"value": "Low"}, "pieces": ["ENG-12", "Low"]}]
    q2 = [{"family": "multi", "question": "Who is assigned to the ticket that OPS-3 is linked to?", "expected": {"value": "Ava Lee"},
           "pieces": ["OPS-4", "Ava Lee"]}]
    les = T.learn_plans_many([(one, q1), (two, q2)], log=lambda *_: None)
    assert les.brain and les.rules == "v9" and les.tickets and les.orders and les.trained_on["proper"]
    assert les.trained_on["questions"] == 3 and les.trained_on["by_family"] == {"single": 1, "multi": 2}
    les.save(tmp_path / "plans.json")
    assert P.PlanLessons.load(tmp_path / "plans.json").brain
    alone = T.learn_plans_many([(one, q1)], log=lambda *_: None)
    ref = P.learn_plans(one, q1, log=lambda *_: None, rules="v9", proper=True, tickets=True, orders=True, brain=True)
    assert alone.weights == ref.weights and alone.asked_kind == ref.asked_kind, "one bank: the same fit as plans.learn_plans"


# ------------------------------------------------------------------ v16: the router on the v16 brain's signals, the new kinds
def _q(qid, family, kind, question="Q?", expected=None, **kw):
    return {"id": qid, "family": family, "kind": kind, "question": question, "expected": expected or {"value": "x"}, **kw}


def test_the_new_kinds_sample_caps_each_family_and_shares_it_over_its_kinds():
    qs = ([_q(f"s{i}", "email_chat", "slack_channel") for i in range(50)] + [_q(f"c{i}", "email_chat", "email_cc") for i in range(3)]
          + [_q(f"h{i}", "history", "created_on") for i in range(4)] + [_q(f"u{i}", "unanswerable", "heldout") for i in range(9)]
          + [_q(f"p{i}", "prose", "prose") for i in range(5)])
    got = T.sample_kinds(qs, per_family=6, seed=3)
    kinds = Counter(q["kind"] for q in got)
    assert kinds == {"slack_channel": 3, "email_cc": 3, "created_on": 4}, "three of each email and chat kind; all four history"
    assert T.sample_kinds(qs, per_family=6, seed=3) == got, "the same seed, the same sample"
    assert {q["id"] for q in T.sample_kinds(qs, per_family=6, seed=4)} != {q["id"] for q in got}
    assert not any(q["kind"] == "heldout" or q["family"] == "prose" for q in T.sample_kinds(qs, per_family=100))


def test_v16_routes_the_new_families_and_learns_plans_from_the_new_two_document_kinds():
    qs = [_q("a", "single", "linear_due"), _q("b", "prose", "prose"), _q("c", "counts", "count1_jira"),
          _q("d", "unanswerable", "field_absent", expected={"not_found": True}), _q("e", "unanswerable", "heldout", expected={"not_found": True}),
          _q("f", "not_found", "nf_key", expected={"not_found": True}), _q("g", "multi", "pr_issue_team"),
          _q("h", "multi", "owner_accounts", expected={"names": ["A B"]})]
    assert [q["id"] for q in T.routed_questions(qs)] == ["a", "b", "g", "h"], "v15: single, multi and prose"
    assert [q["id"] for q in T.routed_questions(qs, v16=True)] == ["a", "b", "c", "d", "g", "h"], "never not_found or held-out"
    assert [q["id"] for q in T.kinds_multi(qs)] == ["g"], "two-document questions with a value, a date or keys"
    assert T.kinds_multi(qs, ["owner_accounts"]) == [] and [q["id"] for q in T.kinds_multi(qs, ["pr_issue_team"])] == ["g"]


@pytest.fixture
def work(tmp_path):
    """A training folder over ONE with v15-style lessons, its questions (single, multi, prose) and round 2's kinds."""
    w = tmp_path / "work"
    w.mkdir()
    B.build(w / "factbank_v2.sqlite", [(d, {}) for d in ONE], text_facts=True)
    Lessons([0.0, 1.0, 1.0, 0.5, 1.0, 0.0], [0.0, 1.0, -0.5, 2.0, 0.0, 0.0, 1.0, -1.0, -2.0, -1.0, 1.0, -1.0, 0.0], [-2.0, 1.0, 2.0, 1.0, 0.0],
            [0.0, 2.0, 0.0, 0.0, 1.0], {}, {}, {}).save(tmp_path / "single_lessons.json")
    weights = dict.fromkeys(P.FEATURES_V4, 0.0) | {"start_named": 2.0, "path_len": -1.0, "field_overlap": 2.0, "label_field": 1.0}
    P.PlanLessons([weights[f] for f in P.FEATURES_V4], {}, {}, {}, list(P.FEATURES_V4), rules="v9", tickets=True,
                  orders=True).save(tmp_path / "plan_lessons.json")
    qs = [_q("s1", "single", "linear_due", "When is ENG-11 due?", {"date": "2026-03-20"}, pieces=["ENG-11", "2026-03-20"]),
          _q("s2", "single", "linear_priority", "What is the priority of ENG-12?", {"value": "Low"}, pieces=["ENG-12", "Low"]),
          _q("m1", "multi", "pr_assignee", "Who is assigned to the Linear issue that pull request #4821 is linked to?",
             {"value": "Omar Singh"}, pieces=["ENG-11", "Omar Singh"]),
          _q("p1", "prose", "prose", "Why do the keycard readers time out at night?", {"facts": ["readers time out"]}),
          _q("p2", "prose", "prose", "How should the office wifi keys be rotated each quarter?", {"facts": ["quarterly rotation"]})]
    (w / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))
    kinds = [_q("k1", "single", "embedded_linear_due", "Do you know when ENG-12 is due?", {"date": "2026-04-02"}),
             _q("k2", "counts", "count1_linear", "How many Linear issues are assigned to Omar Singh?", {"value": "2"}),
             _q("k3", "multi", "pr_issue_project", "Which status does the Linear issue linked from PR #4821 have?",
                {"value": "In Progress"}, pieces=["ENG-11", "In Progress"]),
             _q("k4", "unanswerable", "heldout", "What did the wifi vendor say about the outage?", {"not_found": True})]
    (tmp_path / "kinds.jsonl").write_text("".join(json.dumps(q) + "\n" for q in kinds))
    return tmp_path


def test_v16_signals_read_a_question_word_after_a_verb_of_knowing(work):
    texts = ["Do you know when ENG-12 is due?"]
    args = (work / "work", work / "single_lessons.json", work / "plan_lessons.json", texts)
    assert T.router_signals(*args)[texts[0]]["when"] == 0.0, "v15 reads no plain question word"
    assert T.router_signals(*args, v16=True)[texts[0]]["when"] == 1.0


def test_the_v16_router_learns_from_v15s_questions_and_the_sampled_kinds_all_labelled_fact(work):
    router, rep, rows = T.fit_router16(work / "work", work / "single_lessons.json", work / "plan_lessons.json", work / "kinds.jsonl",
                                       per_family=5, log=lambda *_: None)
    assert router.trained_on["questions"] == 8 and router.trained_on["prose"] == 2, "five of v15's and three new; held-out left out"
    assert router.trained_on["v16"] and router.trained_on["by_family"] == {"counts": 1, "multi": 2, "prose": 2, "single": 3}
    assert rep["sample_ids"] == ["k2", "k3", "k1"] and rep["kinds_sha256"] == T.sha256(work / "kinds.jsonl")
    assert {r["id"]: r["label"] for r in rows} == {"s1": 0, "s2": 0, "m1": 0, "p1": 1, "p2": 1, "k2": 0, "k3": 0, "k1": 0}
    assert next(r for r in rows if r["id"] == "k1")["signals"]["when"] == 1.0, "the v16 brain's signals"


def test_the_router_command_keeps_v15_by_default_and_writes_its_inputs_with_v16(work, capsys):
    out = work / "out"
    out.mkdir()
    base = ["router", "--work", str(work / "work"), "--out", str(out), "--lessons", str(work)]
    v15 = T.main(base)
    assert "v16" not in v15 and v15["questions"] == 5 and sorted(p.name for p in out.iterdir()) == ["router.json"]
    v16 = T.main([*base, "--v16", "--kinds", str(work / "kinds.jsonl"), "--per-family", "5"])
    assert v16["v16"] and v16["questions"] == 8
    rep = json.loads((out / "router_report.json").read_text())
    assert rep["sha256"]["router.json"] == T.sha256(out / "router.json")
    assert rep["plans_sha256"] == T.sha256(work / "plan_lessons.json") and rep["single_sha256"] == T.sha256(work / "single_lessons.json")
    assert len((out / "router_signals.jsonl").read_text().splitlines()) == 8
    with pytest.raises(SystemExit):
        T.main([*base, "--v16"])  # --v16 needs --kinds
    capsys.readouterr()


def test_the_plans_command_learns_v15s_questions_and_the_new_two_document_kinds(work, capsys):
    out = work / "plans"
    rep = T.main(["plans", "--work", str(work / "work"), "--out", str(out), "--lessons", str(work), "--kinds", str(work / "kinds.jsonl")])
    assert rep["plan_kinds"] == 1 and rep["plan_kinds_by_kind"] == {"pr_issue_project": 1}
    assert rep["trained_on"]["questions"] == 4 and rep["trained_on"]["by_family"] == {"single": 2, "multi": 2}
    assert rep["sha256"]["plan_lessons.json"] == T.sha256(out / "plan_lessons.json") and P.PlanLessons.load(out / "plan_lessons.json").brain
    ref = T.learn_plans_many(T.plan_pairs(work / "work", Lessons.load(work / "single_lessons.json"), T._jsonl(work / "work/questions.jsonl"),
                                          kinds=work / "kinds.jsonl"), log=lambda *_: None)
    assert P.PlanLessons.load(out / "plan_lessons.json").weights == ref.weights
    only = T.main(["plans", "--work", str(work / "work"), "--out", str(work / "plans2"), "--lessons", str(work), "--kinds",
                   str(work / "kinds.jsonl"), "--plan-kinds", "pr_issue_creator"])
    assert only["plan_kinds"] == 0 and only["plan_kinds_named"] == ["pr_issue_creator"] and only["trained_on"]["questions"] == 3
    capsys.readouterr()
