"""Training the company brain: plan lessons over several banks, and which questions each part learns from."""

from __future__ import annotations

from datetime import UTC, datetime

from cie.eval import brain_train as T
from cie.factbank import bank as B
from cie.factbank import plans as P
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
