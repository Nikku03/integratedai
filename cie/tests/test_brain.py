"""The company brain (fact bank v15, ``cie.factbank.brain``): the not-found route, the router, the fact, plan and prose routes,
``ask_brain``, and the planner's brain-only additions (whole-word system names, check 7)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cie.factbank import bank as B
from cie.factbank import brain as BR
from cie.factbank import plans as P
from cie.factbank.engine import FactBank, Result
from cie.factbank.learn import Lessons
from cie.factbank.trained import TrainedBank
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)
RUNBOOK = ("Overview of the service. " * 40 + "To verify the telemetry mode, query the status endpoint on port 9100. "
           "The mode should then read local-only. " + "Unrelated closing notes follow here. " * 30)


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)], meta=meta, updated=WHEN,
                     keys=list(keys))


DOCS = [
    (_doc("d1", "linear", "Fix keycard reader timeouts",
          {"key": "ENG-11", "status": "In Progress", "assignee": "Omar Singh", "due_date": "2026-03-20", "project": "Badge Revamp"},
          "Badge readers time out at night.", ["ENG-11"]), {}),
    (_doc("d2", "linear", "Rotate office wifi keys", {"key": "ENG-12", "status": "Done", "assignee": "Omar Singh", "due_date": "2026-04-02"},
          "Quarterly rotation. See also ENG-404 in the old tracker.", ["ENG-12"]), {}),
    (_doc("d3", "linear", "Replace the badge printer",
          {"key": "ENG-13", "status": "Todo", "assignee": "Liam Chen", "due_date": "2026-05-01", "dependencies": ["ENG-12"]}, "", ["ENG-13"]), {}),
    (_doc("d4", "github", "Add retry to badge sync", {"pr_number": "4821", "author": "Maya Chen", "linked_linear": ["ENG-11", "ENG-77"]}), {}),
    (_doc("d5", "confluence", "Telemetry Runbook: local-only mode", {"author": "Maya Chen", "space": "eng-private"}, RUNBOOK), {}),
    (_doc("d6", "fireflies", "Badge rollout sync", {"redwood_attendees": ["Omar Singh", "Lena M\u00fcller"]}, "We talked about badges."),
     {"action_items": ["Priya | send the badge rollout checklist to facilities | Due: 2026-03-25"]}),
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


@pytest.fixture
def brain(paths):
    return BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json")


# ------------------------------------------------------------------ the brain's modes
def test_the_brain_opens_one_bank_in_its_modes(brain, paths):
    assert brain.bank.brain and brain.bank.whole_system_words and brain.bank.answer_first is False
    assert brain.planner.brain and brain.lessons.brain, "the planner fixes are on whatever the lessons file says"
    assert not P.PlanLessons.load(paths / "plans.json").brain, "the file itself is not changed"
    assert brain.planner.whole_words()


# ------------------------------------------------------------------ not found
@pytest.mark.parametrize(("question", "what"), [
    ("What is the status of the Linear issue ENG-99?", "ticket ENG-99"),
    ("Who authored pull request #9999?", "pull request #9999"),
    ("When was PR 5150 merged?", "pull request #5150"),
    ('Who owns the Google Drive document "Badge budget plan for facilities"?', 'title "Badge budget plan for facilities"'),
    ('When was the meeting "Printer rollout sync" recorded?', 'title "Printer rollout sync"'),
    ("List every Linear issue assigned to Omar Chen. Give the issue keys.", "person Omar Chen"),
    ("Which Jira tickets are assigned to Maya Singh's team?", "person Maya Singh"),
    ("Which Jira tickets are assigned to Omar M\u00fcller? Give the ticket keys.", "person Omar M\u00fcller"),
])
def test_names_the_bank_does_not_hold(brain, question, what):
    assert brain.missing(question) == what
    r = brain.ask(question)
    assert (r["answer"], r["route"]) == ("not found", "not_found")
    assert what in r["reason"] and what in r["evidence"] and r["family_scores"] == {} and r["reads"] == []


@pytest.mark.parametrize("question", [
    "What is the status of ENG-11?",
    "Who is assigned to eng-12?",
    "Which pull request links ENG-77?",  # cited by a pull request, though no document of its own
    "What does ENG-404 say?",  # written in a document's text
    "Is GPT-4 faster than SOC-2?",  # not a prefix the bank's tickets use
    "Who authored PR #4821?",
    "Who authored pull request 4821?",
    'Who wrote the Confluence page "telemetry runbook - local only mode"?',  # case and punctuation differ from the title
    'Who wrote the page titled "Telemetry Runbook: local-only mode"?',
    'In the meeting "Badge rollout sync", Priya took this action item: "send the checklist". When is it due?',  # an item, not a title
    'Which Linear issues assigned to Omar Singh have the status "Done"?',
    'Who has issues in the Linear project "Badge Revamp"?',  # a field value the documents write
    'What does the runbook "query the status endpoint" say about ports?',  # the document's own words
    "When is Omar Singh's ticket ENG-11 due?",
    "Will Omar Singh finish ENG-11?",  # a person's alias inside a longer run of capitalised words
    "How does Smart Routing pick a fallback?",  # capitalised words that are not a person's name
    "What did Lena M\u00fcller attend?",
])
def test_names_the_bank_holds(brain, question):
    assert brain.missing(question) is None


def test_holds_text_reads_the_index(brain):
    assert brain.holds_text("query the status endpoint on port 9100") and brain.holds_text("Telemetry runbook")
    assert not brain.holds_text("zebra crossing policy")
    assert brain.holds_text('""') and brain.holds_text("--"), "nothing to search: held"
    assert brain.holds_text("lena muller") and brain.holds_text("LENA MÜLLER"), "case and accents do not matter"
    assert brain.ticket_prefixes() == {"ENG"}


OTHER = [
    (_doc("g1", "github", "Speed up the batch queue", {"pr_number": "193", "author": "Lucas Chen"}), {}),
    (_doc("o1", "linear", "POC batching and queueing tune-up", {"key": "ENG-21", "assignee": "Luca Rossi", "related_github_prs": ["PR-489"]},
          "We cut costs & latency here.", ["ENG-21"]), {}),
    (_doc("o2", "confluence", "Q3 R&D + Ops plan", {"author": "Lucas Chen"}), {}),
]


@pytest.fixture
def other(paths):
    B.build(paths / "other.sqlite", OTHER, text_facts=True)
    return BR.Brain(paths / "other.sqlite", paths / "lessons.json", paths / "plans.json")


def test_a_pull_request_written_with_a_dash(other):
    assert "PR" in other.ticket_prefixes(), "a document cites the key PR-489"
    for q in ("Who reviewed PR-193?", "Who reviewed PR #193?", "Who reviewed pr-193?", "Which Linear issue cites PR-489?"):
        assert other.missing(q) is None, q
    assert other.ask("Who reviewed PR-193?")["route"] != "not_found"
    assert other.missing("Who reviewed PR-9999?") == "pull request #9999"
    assert other.missing("What is the status of ENG-99?") == "ticket ENG-99"


def test_titles_with_and_or_an_ampersand(other):
    assert BR.squash("POC batching & queueing tune-up") == BR.squash("POC batching and queueing tune-up") == "poc batching and queueing tune up"
    assert BR.squash("Q3 R&D + Ops") == "q3 r and d plus ops" and BR.squash("Lena Müller") == "lena muller"
    for q in ('Who owns the document "POC batching & queueing tune-up"?', 'Who wrote the page "Q3 R and D plus Ops plan"?',
              'What does the page "cut costs and latency" say?', 'Who wrote the page "batching & queueing"?'):
        assert other.missing(q) is None, q


def test_word_forms_count(other, brain):
    assert other.holds_text("Lucas Chen") and not other.holds_text("Luca Chen"), "the stemmed index matches both"
    assert other.missing("List every Linear issue assigned to Luca Chen. Give the issue keys.") == "person Luca Chen"
    assert other.missing("List every Linear issue assigned to Luca Rossi. Give the issue keys.") is None
    assert brain.missing('Who owns the document "Rotate office wifi key"?') == 'title "Rotate office wifi key"'
    assert brain.missing('Who owns the document "Rotate office wifi keys"?') is None


# ------------------------------------------------------------------ the router
@pytest.mark.parametrize(("question", "family"), [
    ("Who is assigned to ENG-11?", "fact"),
    ("When is the Linear issue \"Fix keycard reader timeouts\" due?", "fact"),
    ("In the eng space, what is the current ticket status of the keycard reader work?", "fact"),
    ("For the badge printer work, which draft doc covers the rollout?", "fact"),
    ("How many tickets does Omar Singh have?", "fact"),
    ("Which ticket keys mention badges?", "fact"),
    ('List the attendees of the meeting "Badge rollout sync".', "fact"),  # names a document: no prose
    ("What is the operator procedure to verify the telemetry mode afterwards?", "prose"),
    ("Why do badge readers time out at night?", "prose"),
    ("What success targets were suggested for the pilot?", "prose"),
    ("Who owns the runbook, and what is the best channel to ask in?", "prose"),  # two question words that disagree
])
def test_the_rule(brain, question, family):
    scores = brain.family_scores(question, brain.plan(question))
    assert max(scores, key=scores.get) == family and sum(scores.values()) == 1.0


def test_signals(brain):
    q = "When is ENG-11 due?"
    s = brain.signals(q)
    assert s["bias"] == 1.0 and s["start_named"] == 1.0 and s["when"] == 1.0 and s["has_id"] == 1.0 and s["plan_score"] > 0
    assert "w:when" in s and "w:due" in s and not any(k.startswith("w:eng") or k.startswith("w:11") for k in s), "no keys or numbers"
    p = brain.signals("Why do badge readers time out, and how do we verify it?")
    assert p["why"] == 1.0 and p["how_do"] == 1.0 and p["start_named"] == 0.0 and p["who"] == 0.0
    assert brain.signals("What caused the outage?")["what_caused"] == 1.0
    assert set(BR.SIGNALS) <= set(s)


def test_asks_field():
    assert BR.asks_field("In the eng-sre space, what is the last updated date of the runbook?")
    assert BR.asks_field("In which month is the account forecast to close?")
    assert BR.asks_field("Which published runbook by Maya Chen covers rotation?")
    assert not BR.asks_field("What timing did Redwood agree to for an incident summary?")
    assert not BR.asks_field("the page which status we discussed")  # not a clause-opening "which"
    assert not BR.asks_field("What was proposed, and why? The status quo stays.")  # punctuation ends the window


def test_router_train_save_load(brain, tmp_path):
    qs = [{"question": q, "family": f} for q, f in [
        ("Who is assigned to ENG-11?", "single"), ("When is ENG-12 due?", "single"), ("Who authored PR #4821?", "single"),
        ("What is the status of ENG-13?", "single"), ("Who is assigned to the ticket linked to PR #4821?", "multi"),
        ("How do we verify the telemetry mode?", "prose"), ("Why do badge readers time out at night?", "prose"),
        ("How do we rotate the office wifi keys?", "prose"), ("What should the telemetry mode read after the change?", "prose")]]
    r = BR.Router.train(qs, brain, min_count=1)
    assert r.features[0] == "bias" and r.trained_on == {"questions": 9, "prose": 4, "min_count": 1, "l2": 1.0}
    assert "w:how" in r.features and len(r.weights) == len(r.features)
    s_fact, s_prose = (r.scores(brain.signals(q)) for q in ("Who is assigned to ENG-12?", "How do we verify the badge readers?"))
    assert s_fact["fact"] > 0.5 > s_prose["fact"] and abs(s_fact["fact"] + s_fact["prose"] - 1) < 1e-3
    r.save(tmp_path / "router.json")
    again = BR.Router.load(tmp_path / "router.json")
    assert again.features == r.features and again.scores(brain.signals("Who is assigned to ENG-12?")) == s_fact
    assert BR.Router().scores({"start_named": 1.0}) == {"fact": 1.0, "prose": 0.0}, "no weights: the rule"
    assert BR.Router.label({"family": "prose"}) == 1 and BR.Router.label({"family": "not_found"}) == 0
    assert BR.Router.label({"route": "prose", "family": "single"}) == 1


def test_a_trained_router_decides(paths, brain):
    always_prose = BR.Router(["bias"], [5.0])
    b = BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", always_prose)
    r = b.ask("Who is assigned to ENG-11?")
    assert r["route"] == "prose" and r["family_scores"]["prose"] > 0.99
    assert b.ask("Who is assigned to ENG-99?")["route"] == "not_found", "not found comes first"


# ------------------------------------------------------------------ the fact and plan routes
def test_plan_route(brain):
    r = brain.ask("When is ENG-11 due?")
    assert (r["answer"], r["route"]) == ("2026-03-20", "plan")
    assert r["evidence"].startswith("Answer: 2026-03-20\nPlan: ") and len(r["evidence"]) <= brain.budget
    assert r["evidence"].count("Answer:") == 1, "the bank's evidence under the planner prints no second answer"
    assert r["reads"]["values"] == ["2026-03-20"] and r["journal"][0]["op"] == "route" and r["journal"][0]["route"] == "plan"
    assert any(j.get("op") == "plan" for j in r["journal"]) and r["family_scores"] == {"fact": 1.0, "prose": 0.0}
    assert r["ms"] >= 0 and brain.bank.answer_first is False


def test_fact_route_uses_v1s_engine_with_the_brain_evidence(brain):
    q = "When are the keycard reader timeouts due?"
    assert not brain.plan(q)["start_named"]
    r = brain.ask(q)
    assert (r["answer"], r["route"]) == ("2026-03-20", "fact") and r["reason"] == "due_date of Fix keycard reader timeouts"
    assert r["evidence"].startswith("Answer: 2026-03-20\n- due date of ENG-11 (Fix keycard reader timeouts): 2026-03-20")
    assert r["reads"] == [] and any(j.get("op") == "seed" for j in r["journal"])
    full = brain.engine(q).journal
    assert r["journal"][-1] == {"op": "steps", "count": len(full)} and len(r["journal"]) < len(full) + 2
    assert any(j.get("op") == "set" and j["values"] == ["2026-03-20"] and j["parameter"] == "due_date" for j in r["journal"])
    assert brain.bank.answer_first is False, "set back after the engine ran"


def test_v1s_engine_reads_fields_not_sentence_dates(tmp_path):
    body = "Spikes began on 2026-03-10. They came back on 2026-03-10 at noon. A third wave hit on 2026-03-10."
    docs = [(_doc("j1", "jira", "Rate limit spike on bulk embeddings", {"key": "SUP-1", "sla_due_at": "2026-03-13"}, body, ["SUP-1"]), {})]
    B.build(tmp_path / "fb.sqlite", docs, text_facts=True)
    q = "For the rate limit spike on bulk embeddings, what is the SLA due date?"
    plain, brain = TrainedBank(tmp_path / "fb.sqlite"), BR.BrainBank(tmp_path / "fb.sqlite")
    assert FactBank.ask(plain, q).answer == "2026-03-10", "the sentence dates outvote the field"
    r = FactBank.ask(brain, q)
    assert (r.answer, r.reason) == ("2026-03-13", "sla_due_at of Rate limit spike on bulk embeddings")
    assert "text_date" in plain.wanted(q) and "text_date" not in brain.wanted(q)


def test_rests_on():
    j = [{"op": "seed", "entity": "doc:a"}, {"op": "set", "entity": "doc:a", "parameter": "status", "values": ["Done"]},
         {"op": "set", "entity": "doc:a", "parameter": "key", "values": ["ENG-1"]},
         {"op": "contradiction", "entity": "doc:b", "parameter": "key", "values": ["ENG-2", "ENG-9"]}]
    assert BR.rests_on(j, "ENG-1, ENG-2") == [j[0], j[2], j[3], {"op": "steps", "count": 4}]
    assert BR.rests_on(j, "not found") == [j[0], {"op": "steps", "count": 4}]
    assert BR.rests_on(j, "Done", limit=1) == [j[0], {"op": "steps", "count": 4}]


def test_the_planner_answer_stays_when_the_engine_finds_nothing(brain, monkeypatch):
    q = "When are the keycard reader timeouts due?"
    monkeypatch.setattr(brain, "engine", lambda question: Result("not found", "", [], {}, [], 0.0, "nothing"))
    r = brain.ask(q)
    assert r["route"] == "plan" and r["answer"] == brain.plan(q)["answer"] != "not found" and "engine found nothing" in r["reason"]


def test_a_plain_read_of_a_field_not_asked_for_goes_to_the_engine(paths, brain, monkeypatch):
    q = "Which project is ENG-11 part of?"
    wrong = {"answer": "In Progress", "best": P.Plan(("doc:d1",), (), "status", "single"), "journal": [], "top": [], "score": 0.9,
             "start_named": True}
    monkeypatch.setattr(brain, "plan", lambda question: wrong)
    r = brain.ask(q)
    assert (r["answer"], r["route"]) == ("Badge Revamp", "fact") and r["reason"] == "project of Fix keycard reader timeouts"
    off = BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", field_check=False)
    monkeypatch.setattr(off, "plan", lambda question: wrong)
    assert (off.ask(q)["answer"], off.ask(q)["route"]) == ("In Progress", "plan"), "without the check: the planner, as specified first"
    right = {**wrong, "answer": "Badge Revamp", "best": P.Plan(("doc:d1",), (), "project", "single")}
    assert brain.reads_asked_field(q, right) and not brain.reads_asked_field(q, wrong)
    who = "Who is the owner of ENG-11?"  # no owner field: nothing of a person's kind the engine would read instead
    assert brain.reads_asked_field(who, {**wrong, "answer": "Omar Singh", "best": P.Plan(("doc:d1",), (), "assignee", "single")})
    assert not brain.reads_asked_field("Who is the assignee of ENG-11?", {**wrong, "best": P.Plan(("doc:d1",), (), "project", "single")})
    assert (brain.kind_of("Omar Singh"), brain.kind_of("2026-03-20"), brain.kind_of("12"), brain.kind_of("Done")) == \
        ("person", "date", "count", "other")
    for best in (P.Plan(("doc:d1",), ("assignee",), "status", "single"), P.Plan(("doc:d1",), (), "label", "single"),
                 P.Plan(("person:omar singh",), ("assignee_of",), "label", "count")):
        assert brain.reads_asked_field(q, {**wrong, "best": best}), "links, items and counts are the planner's own"


def test_list_question_goes_to_the_plan(brain):
    r = brain.ask("List every Linear issue assigned to Omar Singh. Give the issue keys.")
    assert (r["answer"], r["route"]) == ("ENG-11, ENG-12", "plan")


# ------------------------------------------------------------------ the prose route
def test_prose_route(brain):
    r = brain.ask("How do we verify the telemetry mode on a private deployment?")
    assert r["route"] == "prose" and "port 9100" in r["answer"] and "Telemetry Runbook" in r["answer"]
    assert r["evidence"].startswith("[passage] Telemetry Runbook: local-only mode\n") and len(r["evidence"]) <= brain.budget
    assert "doc:d5" in r["reason"] and r["reads"] == [] and set(r["family_scores"]) == {"fact", "prose"}
    blocks = r["evidence"].split("\n\n")
    assert all(b.startswith("[passage] ") for b in blocks), "one passage per block, no blank lines inside"


def test_prose_within_a_small_budget(paths):
    b = BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", budget=1200)
    r = b.ask("How do we verify the telemetry mode on a private deployment?")
    assert r["route"] == "prose" and r["evidence"].startswith("[passage] ") and len(r["evidence"]) <= 1200


def test_prose_says_not_found_without_a_quote(brain, monkeypatch):
    import cie.retrieval.answer as A

    monkeypatch.setattr(A, "quote_answer", lambda items, question: None)
    r = brain.ask("How do we verify the telemetry mode on a private deployment?")
    assert (r["answer"], r["route"]) == ("not found", "prose") and r["evidence"]


# ------------------------------------------------------------------ ask_brain
def test_ask_brain_writes_rows(paths):
    qs = [{"id": "a", "question": "When is ENG-11 due?"}, {"id": "b", "question": "Who authored pull request #9999?"},
          {"id": "c", "question": "How do we verify the telemetry mode on a private deployment?"}]
    (paths / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))
    rep = BR.ask_brain(paths, paths / "lessons.json", paths / "plans.json", name="v15")
    assert rep["questions"] == 3 and rep["written"] == "v15.jsonl" and rep["routes"] == {"plan": 1, "not_found": 1, "prose": 1}
    rows = [json.loads(x) for x in (paths / "v15.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ["a", "b", "c"]
    assert all(set(r) >= {"id", "answer", "route", "reason", "evidence", "ms", "reads", "journal"} for r in rows)
    always_prose = paths / "router.json"
    BR.Router(["bias"], [5.0]).save(always_prose)
    rep = BR.ask_brain(paths, paths / "lessons.json", paths / "plans.json", name="v15r", router=always_prose)
    assert rep["routes"] == {"prose": 2, "not_found": 1}


def test_main(paths, capsys):
    (paths / "questions.jsonl").write_text(json.dumps({"id": "a", "question": "When is ENG-11 due?"}) + "\n")
    rep = BR.main(["ask", "--work", str(paths), "--single", str(paths / "lessons.json"), "--plans", str(paths / "plans.json")])
    assert rep["routes"] == {"plan": 1} and (paths / "factbank_v15.jsonl").exists() and '"plan": 1' in capsys.readouterr().out
    rep = BR.main(["ask", "--work", str(paths), "--single", str(paths / "lessons.json"), "--plans", str(paths / "plans.json"),
                   "--no-field-check", "--name", "nocheck"])
    assert rep["written"] == "nocheck.jsonl"


# ------------------------------------------------------------------ the planner's brain-only additions
def test_whole_word_systems_in_the_planner(paths):
    tb = TrainedBank(paths / "factbank_v2.sqlite")
    q = "Who wrote the Echo harness for CI-driven regressions?"
    v13, brain = P.Planner(tb, "v9"), P.Planner(tb, "v9", brain=True)
    assert v13.systems_named(q) == ["google_drive"] and brain.systems_named(q) == ["google_drive"], "off until the bank reads whole words"
    tb.whole_system_words = True
    assert brain.systems_named(q) == [] and v13.systems_named(q) == ["google_drive"], "v13 reads system words as before"
    assert brain.systems_named("Who opened the PRs for ENG-11?") == ["github"]
    brain.tickets = True
    assert brain.systems_named("Which Linear tickets are open?") == ["linear", "ticket"]


@pytest.mark.parametrize(("question", "link"), [
    ("When is ENG-13 due?", False),
    ('When is the Linear issue "Replace the badge printer" due?', False),
    ("When is the ticket that ENG-13 depends on due?", True),
    ("ENG-13 is tied to another ticket. Where does that one stand?", True),
    ("Who is assigned to the ticket linked to PR #4821?", True),
    ("Who is the owner of the action item?", True),
    ("Whoever took it: when is it due?", True),
    ("Who is its assignee?", True),
    ('When is "the linked dashboard" due?', False),  # words inside a quoted title do not count
])
def test_asks_link(question, link):
    assert P.Planner.asks_link(question) is link


def test_check7_reads_the_named_start_itself(paths):
    tb = TrainedBank(paths / "factbank_v2.sqlite")
    q = 'When is the Linear issue "Replace the badge printer" due?'
    v13, brain = P.Planner(tb, "v9"), P.Planner(tb, "v9", brain=True)
    for pl in (v13, brain):
        pl.tickets = pl.orders = True
    cands = v13.candidates(q)
    assert any(p.path == ("dependencies",) for p, _ in v13.check(q, cands, "date")), "v13 keeps the hop to the dependency"
    kept = brain.check(q, cands, "date")
    assert kept and all(not p.path for p, _ in kept) and {m["answer"] for _, m in kept} == {"2026-05-01"}
    linked = "When is the ticket that ENG-13 depends on due?"
    lc = brain.candidates(linked)
    assert any(p.path == ("dependencies",) for p, _ in brain.check(linked, lc, "date")), "a link word keeps the hop"
    content = "When is the badge printer replacement due?"  # names nothing: check 7 does not apply
    cc = brain.candidates(content)
    assert brain.check(content, cc, "date") == v13.check(content, cc, "date")
