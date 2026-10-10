"""The company brain's planner fixes (v15, ``Planner(brain=True)``): question words over the learned kind of answer, no count
for a question asking for several things, no one-word person aliases in check 1, and ``start_named`` for the router."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cie.factbank import bank as B
from cie.factbank import plans as P
from cie.factbank.trained import TrainedBank
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)
OMAR = "person:omar singh"


def _doc(dsid, source, title, meta, keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", "")], meta=meta, updated=WHEN,
                     keys=list(keys))


DOCS = [
    (_doc("d1", "linear", "Fix keycard reader timeouts",
          {"key": "ENG-11", "status": "In Progress", "assignee": "Omar Singh", "due_date": "2026-03-20"}, ["ENG-11"]), {}),
    (_doc("d2", "linear", "Rotate office wifi keys",
          {"key": "ENG-12", "status": "Done", "assignee": "Omar Singh", "due_date": "2026-04-02"}, ["ENG-12"]), {}),
    (_doc("d3", "linear", "Replace the badge printer",
          {"key": "ENG-13", "status": "Todo", "assignee": "Liam Chen", "due_date": "2026-05-01", "dependencies": ["ENG-12"]}, ["ENG-13"]), {}),
    (_doc("d4", "github", "Add retry to badge sync", {"pr_number": "4821", "author": "Maya Chen", "linked_linear": ["ENG-11"]}), {}),
    # action items give people by a first name only ("Priya"), as meetings write them
    (_doc("d6", "fireflies", "Badge rollout sync", {"redwood_attendees": ["Omar Singh"]}),
     {"action_items": ["Priya | send the badge rollout checklist to facilities | Due: 2026-03-25",
                       "Priya Nair | order spare keycards for the lobby | Due: 2026-03-27"]}),
]


@pytest.fixture
def tb(tmp_path):
    B.build(tmp_path / "fb.sqlite", DOCS, text_facts=True)
    return TrainedBank(tmp_path / "fb.sqlite")


def _v13(tb, brain=False):
    pl = P.Planner(tb, "v9", brain=brain)
    pl.tickets = pl.orders = True
    return pl


@pytest.mark.parametrize(("question", "kind"), [
    ("When is ENG-11 due?", "date"),
    ('In the meeting "Badge rollout sync", Priya took this action item: "send the checklist". When is it due?', "date"),
    ("ticket linked to #4821 - when's it due? need the deadline date", "date"),
    ("What is the due date of ENG-11?", "date"),
    ("Priya picked up an action item in the meeting. What's the deadline on that?", "date"),
    ("Who is assigned to ENG-11?", "person"),
    ("ENG-11 has a pull request attached to it. Whose PR is it?", "person"),
    ("Quick question: the ticket that goes with PR #4821, who is that assigned to?", "person"),
    ("ENG-11 has a linked ticket, and I need to know who owns it. Who is that other ticket assigned to?", "person"),
    ('Who took "When is the launch due" in the meeting?', "person"),
    ("How many Linear issues does Omar Singh have?", "count"),
    ("How many tickets does the person who opened PR #4821 have?", "count"),
    ("What's the total number of Linear tickets on Omar Singh's list?", "count"),
])
def test_question_words_that_ask_plainly(question, kind):
    assert P.Planner.interrogative_kind(question) == kind


@pytest.mark.parametrize("question", [
    "Which ticket key is assigned to Omar Singh?",
    "What is the status of ENG-11?",
    "Which deadline is sooner, the one for ENG-11 or the one for ENG-13?",
    "ENG-11 and ENG-13: whose due date is earlier?",
    "What is the deadline of the next ticket Omar Singh has?",
    "What was Priya asked to prepare as an action item and when was it due?",
    "Which Linear issues are assigned to the person who took the action item? Give the keys.",
    "What is the PR number of the pull request linked to ENG-11?",
    "List every GitHub pull request authored by Maya Chen.",
    "Where does the ticket linked to PR #4821 stand right now?",
])
def test_question_words_that_leave_the_kind_open(question):
    assert P.Planner.interrogative_kind(question) is None


def test_the_question_word_overrides_the_learned_kind_only_with_brain(tb):
    q = "When is ENG-11 due?"
    assert _v13(tb).asked_kind(q, "key") == "key" and _v13(tb).asked_kind(q, None) is None, "off: the learned kind as it was"
    brain = _v13(tb, brain=True)
    assert brain.asked_kind(q, "key") == "date", "a learned kind that differs is replaced"
    assert brain.asked_kind(q, None) == "date", "an unsure lesson is filled in"
    assert brain.asked_kind("What is the status of ENG-11?", "other") == "other", "an open question word leaves the lesson's kind"
    assert brain.asked_kind("What is the status of ENG-11?", None) is None


def test_answer_uses_the_question_word_with_brain(tb):
    ak = P.AskedKind()
    for _ in range(5):  # lessons sure that this wording asks for a key ("action item" read as asking for one)
        ak.add(P.question_words("When is the action item ENG-11 due?"), {"key"})
        ak.add(P.question_words("Who is assigned to ENG-12?"), {"person"})
    q = "When is the action item ENG-11 due?"
    assert ak.asked(q) == "key"
    w = [0.0] * len(P.FEATURES_V4)
    w[P.FEATURES_V4.index("path_len")] = -1.0
    les = P.PlanLessons(w, {}, {}, {}, list(P.FEATURES_V4), rules="v9", asked_kind=ak.to_json(), tickets=True, orders=True)
    off, _, _, _ = P.answer(tb, les, q, les.planner(tb))
    assert off == "#4821", "v13: only plans giving a key pass check 4"
    on, best, _, _ = P.answer(tb, les, q, P.Planner(tb, "v9", brain=True))
    assert on == "2026-03-20" and best == P.Plan(("doc:d1",), (), "due_date", "single")


def test_several_things_get_no_count_with_brain(tb):
    q = "List every Linear issue assigned to Omar Singh."
    v13, brain = _v13(tb), _v13(tb, brain=True)
    cands = v13.candidates(q)
    assert any(p.aggregate == "count" for p, _ in v13.check(q, cands)), "v13 keeps counts"
    kept = brain.check(q, cands)
    assert kept and not any(p.aggregate == "count" for p, _ in kept)
    assert "ENG-11, ENG-12" in {m["answer"] for p, m in kept if p.aggregate == "list"}
    for q2 in ("Count every Linear issue assigned to Omar Singh.", "How many Linear issues does Omar Singh have? List them all.",
               "Give the number of tickets on every list Omar Singh has."):
        assert any(p.aggregate == "count" for p, _ in brain.check(q2, brain.candidates(q2))), "it asks for a count too"
    q3 = "Which of Omar Singh's tickets is due first?"
    assert brain.check(q3, brain.candidates(q3)) == v13.check(q3, v13.candidates(q3)), "one thing asked for: nothing changes"


def test_a_one_word_alias_does_not_say_who_the_question_is_about(tb):
    q = "When is Priya's action item due?"
    v13, brain = _v13(tb), _v13(tb, brain=True)
    assert tb.named(q) == ["person:priya"] and brain.named_fully(q) == [] and brain.about(q) == set()
    cands = v13.candidates(q)
    assert {p.starts for p, _ in v13.check(q, cands)} == {("person:priya",)}, "v13: the first name decides the start"
    assert {p.starts for p, _ in brain.check(q, cands)} > {("person:priya",)}, "brain: check 1 does not narrow to it"
    full = "When is Priya Nair's action item due?"
    assert set(tb.named(full)) == {"person:priya", "person:priya nair"}, "the one-word alias matches inside the full name"
    assert brain.named_fully(full) == ["person:priya nair"], "a full name still counts"
    assert {p.starts for p, _ in brain.check(full, brain.candidates(full))} == {("person:priya nair",)}


def test_start_named(tb):
    pl = _v13(tb)
    by_first = P.Plan(("person:priya",), ("action_owner_of",), "due_date", "single")
    by_full = P.Plan(("person:priya nair",), ("action_owner_of",), "due_date", "single")
    assert not pl.start_named(by_first, "When is Priya's action item due?"), "a first name only: the router answers with v1"
    assert pl.start_named(by_full, "When is Priya Nair's action item due?")
    assert not pl.start_named(by_first, "When is Priya Nair's action item due?")
    quoted = 'When is "send the badge rollout checklist to facilities" due?'
    assert pl.start_named(P.Plan(("action:d6:0",), (), "due_date", "single"), quoted), "a quoted title names its start"
    assert not pl.start_named(P.Plan(("action:d6:1",), (), "due_date", "single"), quoted)
    assert pl.start_named(P.Plan(("doc:d1",), (), "due_date", "single"), "When is ENG-11 due?"), "a key names its start"
    assert not pl.start_named(P.Plan(("doc:d1",), (), "due_date", "single"), "When are the keycard reader timeouts fixed?"), \
        "found by content only"
    assert _v13(tb, brain=True).start_named(by_full, "When is Priya Nair's action item due?")


def test_brain_is_saved_with_the_lessons(tb, tmp_path):
    qs = [{"question": "How many tickets are assigned to Omar Singh?", "expected": {"value": "2"}, "pieces": ["ENG-11", "ENG-12"]}]
    les = P.learn_plans(tb, qs, log=lambda *_: None, rules="v9", proper=True, tickets=True, orders=True, brain=True)
    les.save(tmp_path / "v15.json")
    again = P.PlanLessons.load(tmp_path / "v15.json")
    assert again.brain and again.planner(tb).brain
    old = {k: v for k, v in json.loads((tmp_path / "v15.json").read_text()).items() if k != "brain"}
    (tmp_path / "v13.json").write_text(json.dumps(old))
    v13 = P.PlanLessons.load(tmp_path / "v13.json")
    assert not v13.brain and not v13.planner(tb).brain, "lessons saved before v15 load without the brain fixes"
    assert not P.learn_plans(tb, qs, log=lambda *_: None, rules="v9").brain and not P.Planner(tb, "v9").brain
