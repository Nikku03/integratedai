"""The company brain's round 2 fault fixes (``Brain(..., v16=True)``, ``cie.factbank.brain`` and ``cie.factbank.plans``): each
of the five faults on a small example, the per-question memo of ``FactBank.named``, and the flag's plumbing. With v16 off,
every one of them gives v15's answer."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cie.factbank import bank as B
from cie.factbank import brain as BR
from cie.factbank import plans as P
from cie.factbank.engine import FactBank
from cie.factbank.learn import Lessons
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)], meta=meta, updated=WHEN,
                     keys=list(keys))


DOCS = [
    (_doc("d1", "linear", "Fix keycard reader timeouts",
          {"key": "ENG-11", "status": "In Progress", "assignee": "Omar Singh", "creator": "Priya Desai", "created_at": "2025-02-10",
           "due_date": "2026-03-20", "project": "Badge Revamp"}, "Badge readers time out at night.", ["ENG-11"]), {}),
    (_doc("d2", "linear", "Rotate office wifi keys", {"key": "ENG-12", "status": "Done", "assignee": "Maya Lopez", "due_date": "2026-04-02",
                                                      "stakeholders": ["Maya Chen", "Okta SSO", "Zed Corp"]}, "", ["ENG-12"]), {}),
    (_doc("d3", "linear", "Replace the badge printer", {"key": "ENG-13", "assignee": "Omar Singh", "stakeholders": ["Zed Corp"]}, "",
          ["ENG-13"]), {}),
    (_doc("d4", "confluence", "Printer vendor notes", {"author": "Lena Ford", "stakeholders": ["Zed Corp"]}, "Notes."), {}),
    (_doc("d5", "fireflies", "Badge rollout sync", {"meeting_id": "ff-20280712-8b4f", "recorded_at": "2028-07-12T10:00:00Z",
                                                    "redwood_attendees": ["Omar Singh", "Lena Ford"],
                                                    "customer_attendees": ["Ana Ruiz", "Bo Chen"]}, "We talked about badges."), {}),
]
W = dict.fromkeys(P.FEATURES_V4, 0.0) | {"start_named": 2.0, "path_len": -1.0, "path_overlap": 1.0, "field_overlap": 2.0, "label_field": 1.0,
                                          "answer_named_clue": -3.0, "system_fits": 1.0}


@pytest.fixture
def paths(tmp_path):
    B.build(tmp_path / "factbank_v2.sqlite", DOCS, text_facts=True)
    Lessons([0.0, 1.0, 1.0, 0.5, 1.0, 0.0], [0.0, 1.0, -0.5, 2.0, 0.0, 0.0, 1.0, -1.0, -2.0, -1.0, 1.0, -1.0, 0.0], [-2.0, 1.0, 2.0, 1.0, 0.0],
            [0.0, 2.0, 0.0, 0.0, 1.0], {}, {}, {}).save(tmp_path / "lessons.json")
    P.PlanLessons([W[f] for f in P.FEATURES_V4], {}, {}, {}, list(P.FEATURES_V4), rules="v9", tickets=True,
                  orders=True).save(tmp_path / "plans.json")
    return tmp_path


def _brain(paths, v16: bool) -> BR.Brain:
    return BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", v16=v16)


@pytest.fixture
def v15(paths):
    return _brain(paths, False)


@pytest.fixture
def v16(paths):
    return _brain(paths, True)


def _bank(paths, v16: bool) -> BR.BrainBank:
    bank = BR.BrainBank(paths / "factbank_v2.sqlite")
    bank.v16 = v16
    return bank


# ------------------------------------------------------------------ the flag
def test_the_flag_is_off_by_default_and_brain_sets_it(paths, v15, v16):
    assert BR.BrainBank.v16 is False and P.Planner.v16 is False
    assert not v15.v16 and not v15.bank.v16 and not v15.planner.v16
    assert v16.v16 and v16.bank.v16 and v16.planner.v16
    assert v16.bank.brain and v16.planner.brain, "v16 adds to the v15 modes"


def test_ask_brain_and_the_cli_name_the_rows_after_the_version(paths, capsys):
    (paths / "questions.jsonl").write_text(json.dumps({"id": "a", "question": "When is ENG-11 due?"}) + "\n")
    rep = BR.ask_brain(paths, paths / "lessons.json", paths / "plans.json", v16=True)
    assert rep["written"] == "factbank_v16.jsonl" and (paths / "factbank_v16.jsonl").exists()
    assert BR.ask_brain(paths, paths / "lessons.json", paths / "plans.json")["written"] == "factbank_v15.jsonl"
    assert BR.ask_brain(paths, paths / "lessons.json", paths / "plans.json", name="x", v16=True)["written"] == "x.jsonl"
    args = ["ask", "--work", str(paths), "--single", str(paths / "lessons.json"), "--plans", str(paths / "plans.json")]
    assert BR.main([*args, "--v16"])["written"] == "factbank_v16.jsonl"
    assert BR.main(args)["written"] == "factbank_v15.jsonl"
    rows = [json.loads(x) for x in (paths / "factbank_v16.jsonl").read_text().splitlines()]
    assert rows[0]["answer"] == "2026-03-20"
    capsys.readouterr()


# ------------------------------------------------------------------ fault 1: a question word after a verb of knowing or telling
@pytest.mark.parametrize(("question", "kind"), [
    ("Do you know when ENG-11 is due?", "date"),
    ("Can you remind me who is assigned to ENG-11?", "person"),
    ("Could you tell me exactly who owns the runbook?", "person"),  # past "me" and "exactly"
    ("I wonder whom the ticket went to.", "person"),
    ("Any idea how many tickets Omar Singh has?", "count"),
    ("Do you know by when the printer must be replaced?", "date"),  # a preposition after the verb
    ("Not sure when it shipped, can you check?", "date"),
])
def test_an_embedded_question_word_asks_plainly(question, kind):
    assert P.Planner.interrogative_kind(question) is None, "v15 reads only a question word that opens a clause"
    assert P.Planner.interrogative_kind(question, embedded=True) == kind


@pytest.mark.parametrize("question", [
    "Find who owns the runbook, then list their tickets.",  # finding is not knowing or telling: two steps
    "Could you check for me when it ships?",  # "check" is not on the list, and "for" stands between
    "Show me who is on call.",
    "The person who took it is out.",  # a relative "who" after a noun
])
def test_only_verbs_of_knowing_or_telling_embed_a_question(question):
    assert P.Planner.interrogative_kind(question, embedded=True) is None


def test_follows_embedding_verb():
    toks = ["can", "you", "remind", "me", "again", "who", "owns", "it"]
    assert P.follows_embedding_verb(toks, 5) and not P.follows_embedding_verb(toks, 6)
    assert not P.follows_embedding_verb(["who"], 0)


def test_asks_field_after_a_verb_of_telling():
    q = "Could you tell me which project ENG-11 is in?"
    assert not BR.asks_field(q) and BR.asks_field(q, embedded=True)
    assert BR.asks_field("Which project is ENG-11 in?", embedded=True), "a clause-opening which still counts"
    assert not BR.asks_field("Could you tell me which way to go?", embedded=True), "no field or item after it"


def test_the_brain_signals_and_the_planner_read_embedded_question_words(v15, v16):
    q = "Can you remind me who is assigned to ENG-11?"
    assert v15.signals(q)["who"] == 0.0 and v16.signals(q)["who"] == 1.0
    f = "Could you tell me which project ENG-11 is in?"
    assert v15.signals(f)["field_word"] == 0.0 and v16.signals(f)["field_word"] == 1.0
    when = "Do you know when ENG-11 is due?"
    assert v15.planner.asked_kind(when, None) is None and v16.planner.asked_kind(when, None) == "date"
    assert v16.planner.asked_kind(when, "other") == "date", "a plain question word replaces the learned kind"


# ------------------------------------------------------------------ fault 2: products stored as people
def test_not_people(v16):
    bank = v16.bank
    assert "person:okta sso" in bank.kinds, "the stakeholders field names it as if it were a person"
    assert bank.not_people() == {"person:okta sso"}
    # Maya Chen: her first name starts two people's names; Zed Corp: named in three documents; Omar Singh, Lena Ford, Ana Ruiz,
    # Bo Chen, Priya Desai: they hold a person field (assignee, author, attendees, creator)
    assert bank.not_people() is bank.not_people(), "kept on the bank"
    assert "assignee" in BR.PERSON_FIELDS and "stakeholders" not in BR.PERSON_FIELDS


def test_named_fully_drops_what_is_not_a_person(v15, v16):
    q = "What does Okta SSO need for the wifi rotation?"
    assert v15.planner.named_fully(q) == ["person:okta sso"]
    assert v16.planner.named_fully(q) == [] and v16.planner.about(q) == set()
    assert v16.planner.named_fully("What did Zed Corp ask for?") == ["person:zed corp"]
    assert v16.planner.named_fully("What is Maya Chen working on?") == ["person:maya chen"]


# ------------------------------------------------------------------ fault 3: the kind asked for
def test_the_engine_reads_a_date_when_asked_when(paths, v16):
    q = 'When was the meeting "Badge rollout sync" recorded?'
    old, new = FactBank.ask(_bank(paths, False), q), FactBank.ask(_bank(paths, True), q)
    assert old.answer == "ff-20280712-8b4f", "meeting_id ties with recorded_at and is written first"
    assert (new.answer, new.reason) == ("2028-07-12", "recorded_at of Badge rollout sync")
    assert v16.engine(q).evidence.startswith("Answer: 2028-07-12\n- recorded at of Badge rollout sync: 2028-07-12")


def test_the_engine_reads_a_person_when_asked_who(paths):
    q = "Who created the keycard reader timeouts ticket?"
    assert FactBank.ask(_bank(paths, False), q).answer == "2025-02-10", "created_at outweighs the creator"
    assert FactBank.ask(_bank(paths, True), q).answer == "Priya Desai"


def test_the_kind_filter_keeps_v1s_choice_when_nothing_fits(paths):
    q = "When is the status of the keycard reader timeouts ticket?"  # no written value of a date's kind is weighted
    old, new = FactBank.ask(_bank(paths, False), q), FactBank.ask(_bank(paths, True), q)
    assert new.answer == old.answer == "In Progress"


def test_value_fits(v16):
    b = v16.bank
    assert b.value_fits("2028-07-12T10:00:00Z", None, "date") and not b.value_fits("ff-20280712-8b4f", None, "date")
    assert b.value_fits("Priya Desai", None, "person") and b.value_fits("PD", "person:priya desai", "person")
    assert not b.value_fits("Badge Revamp", None, "person") and b.value_fits("Badge Revamp", None, None)


def test_the_field_check_weighs_the_fields_of_the_asked_kind(v15, v16):
    q = "Who is the project assignee for ENG-11?"
    plan = {"answer": "Badge Revamp", "best": P.Plan(("doc:d1",), (), "project", "single"), "journal": [], "top": [], "score": 0.9,
            "start_named": True}
    assert v15.reads_asked_field(q, plan), "v15: the project has a positive weight, so the plan stands"
    assert not v16.reads_asked_field(q, plan), "v16: the assignee, a person, weighs more"
    right = {**plan, "answer": "Omar Singh", "best": P.Plan(("doc:d1",), (), "assignee", "single")}
    assert v16.reads_asked_field(q, right)
    for best in (P.Plan(("doc:d1",), ("assignee",), "status", "single"), P.Plan(("doc:d1",), (), "label", "single"),
                 P.Plan(("person:omar singh",), ("assignee_of",), "label", "count")):
        assert v16.reads_asked_field(q, {**plan, "best": best}), "links, items and counts are the planner's own"


def test_the_field_check_on_a_tie_prefers_the_field_that_fits(v16, monkeypatch):
    q = "Who is the owner of ENG-11?"
    plan = {"answer": "x", "best": P.Plan(("doc:d1",), (), "project", "single"), "journal": [], "top": [], "score": 0.9, "start_named": True}
    monkeypatch.setattr(v16.bank, "wanted", lambda question: {"project": 1.0, "assignee": 1.0})
    assert not v16.reads_asked_field(q, plan), "as heavy, and the plan's field holds no person"
    monkeypatch.setattr(v16.bank, "wanted", lambda question: {"project": 1.0, "assignee": 0.5})
    assert v16.reads_asked_field(q, plan), "lighter: the plan stands"


# ------------------------------------------------------------------ fault 4: attendees
def test_the_attendee_lists_join(paths, v16):
    q = 'List the attendees of the meeting "Badge rollout sync".'
    old, new = FactBank.ask(_bank(paths, False), q), FactBank.ask(_bank(paths, True), q)
    assert old.answer == "Lena Ford, Omar Singh"
    assert new.answer == "Lena Ford, Omar Singh, Ana Ruiz, Bo Chen"
    assert new.reason == "redwood_attendees of Badge rollout sync + customer_attendees"
    assert "\n- customer attendees of Badge rollout sync: Ana Ruiz\n" in v16.engine(q).evidence, "each list's facts are cited"


def test_a_named_part_keeps_its_own_list(paths):
    bank = _bank(paths, True)
    q = 'Who were the customer attendees of the meeting "Badge rollout sync"?'
    assert FactBank.ask(bank, q).answer == "Ana Ruiz, Bo Chen"
    written = FactBank.run(bank, q)[0]
    redwood, customer = written[("doc:d5", "redwood_attendees")], written[("doc:d5", "customer_attendees")]
    assert bank.siblings(q, redwood, written) == [], "the question names a part the best field does not have"
    assert bank.siblings(q, customer, written) == []
    assert bank.siblings('Who attended "the customer call"?', redwood, written) == [customer], "words in a quoted title do not count"
    assert bank.siblings(q, written[("doc:d5", "recorded_at")], written) == [], "a single-valued field has no siblings"


def test_attendees_ask_for_people(v15, v16):
    q = 'List the attendees of the meeting "Badge rollout sync".'
    assert v15.planner.asked_kind(q, None) is None and v16.planner.asked_kind(q, None) == "person"
    assert v16.planner.asked_kind(q, "key") == "person"
    assert v16.planner.asked_kind('When did the attendees of "Badge rollout sync" meet?', None) == "date", "a question word decides"
    assert v16.planner.asked_kind('What is the status of "Badge rollout sync"?', "other") == "other"


# ------------------------------------------------------------------ fault 5: "filed under"
def test_filed_under_asks_for_the_project(paths):
    old, new = _bank(paths, False), _bank(paths, True)
    q = "What project is the Linear ticket filed under for the keycard reader timeouts?"
    assert old.wanted(q)["creator"] == pytest.approx(1.9) and old.wanted(q)["project"] == pytest.approx(1.0)
    w = new.wanted(q)
    assert "reporter" not in w and "creator" not in w
    assert w["project"] == pytest.approx(3.0) and w["space"] == pytest.approx(1.9)
    assert FactBank.ask(old, q).answer == "Priya Desai" and FactBank.ask(new, q).answer == "Badge Revamp"


def test_filed_under_leaves_other_questions_alone(paths):
    old, new = _bank(paths, False), _bank(paths, True)
    for q in ("Who filed the keycard reader ticket?", 'Who filed "the ticket filed under badges"?'):
        assert new.wanted(q) == old.wanted(q), q
    q = "Which file was filed under the badge project?"
    w = new.wanted(q)
    assert w["reporter"] == pytest.approx(old.wanted(q)["reporter"]), "another word brought the cue: it stays"
    assert w["project"] == pytest.approx(old.wanted(q)["project"] + 2.0)


# ------------------------------------------------------------------ the memo of FactBank.named
def test_named_is_kept_per_question_with_v16(paths, monkeypatch):
    calls = []
    orig = FactBank.named

    def counting(self, question):
        calls.append(question)
        return orig(self, question)

    monkeypatch.setattr(FactBank, "named", counting)
    new, old = _bank(paths, True), _bank(paths, False)
    q = "Who is assigned to ENG-11?"
    first = new.named(q)
    first.append("mutated")
    assert new.named(q) == ["doc:d1"] and new.named(q) == old.named(q) and calls.count(q) == 2, "one scan for v16, one for v15"
    old.named(q)
    assert calls.count(q) == 3, "v15 scans every time"
    monkeypatch.setattr(BR, "NAMED_MEMO", 2)
    for x in ("ENG-12", "ENG-13", "ENG-11"):
        new.named(x)
    assert len(new._named_memo) <= 2


def test_v16_answers_through_the_brain(v15, v16):
    q = 'When was the meeting "Badge rollout sync" recorded?'
    assert v16.ask(q)["answer"] == "2028-07-12"
    for brain in (v15, v16):
        r = brain.ask("When is ENG-11 due?")
        assert (r["answer"], r["route"]) == ("2026-03-20", "plan")
