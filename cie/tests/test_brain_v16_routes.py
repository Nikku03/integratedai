"""The company brain's v16 routes (``Brain(..., v16=True)``, ``cie.factbank.brain``): derived, table, v16's prose with its
abstention, and absent, each on a tiny bank built here; the order the routes are tried in; one ``Records`` and one passage
index per brain, built on first use; the row every route gives; ``ask_brain`` and the CLI with ``--min-held``. With v16 off,
none of the new routes runs and nothing of them is built."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cie.eval.brain2_test import route_class
from cie.factbank import bank as B
from cie.factbank import brain as BR
from cie.factbank import plans as P
from cie.factbank import prose as PR
from cie.factbank import records as R
from cie.factbank.learn import Lessons
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)
RUNBOOK = ("Overview of the service. " * 40 + "To verify the telemetry mode, query the status endpoint on port 9100. "
           "The mode should then read local-only. " + "Unrelated closing notes follow here. " * 30)
COMMENTS = ("- 2026-03-10 Diego Martinez: Initial sketch complete.\n"
            "- 2026-03-11 09:20 - Ava Chen (Eng): We need the timeline to tie into the rollout history.\n"
            "- 2026-03-12 Diego Martinez: Consolidated feedback; moving ticket to In Review.\n"
            "- 2026-03-14 Priya Nair: Scheduled the staging canary.")


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)] if body else [],
                     meta=meta, updated=WHEN, keys=list(keys))


DOCS = [
    (_doc("j1", "jira", "Soft 429s during batch import", {"key": "SUP-101", "status": "In Progress", "priority": "P1", "assignee": "Marco Nguyen"},
          keys=["SUP-101"]), {}),
    (_doc("j2", "jira", "Negative invoice after consolidation", {"key": "SUP-102", "status": "Resolved", "priority": "P1",
                                                                 "assignee": "Marco Nguyen"}, keys=["SUP-102"]), {}),
    (_doc("j3", "jira", "Webhook retries stall", {"key": "SUP-103", "status": "Triage", "priority": "P2", "assignee": "Liam Chen"},
          keys=["SUP-103"]), {}),
    (_doc("l1", "linear", "Traffic Inspector prototype", {"key": "DES-1", "status": "In Review", "priority": "P1", "project": "Badge Revamp",
                                                          "assignee": "Priya Nair", "creator": "Ava Chen", "customer_impact": "high",
                                                          "created_at": "2026-03-09", "updated_at": "2026-03-15", "due_date": "2026-04-02"},
          COMMENTS, ["DES-1"]), {}),
    (_doc("l2", "linear", "Rotate office wifi keys", {"key": "ENG-12", "status": "Done", "priority": "P2", "project": "Badge Revamp",
                                                      "assignee": "Omar Singh", "creator": "Ava Chen", "customer_impact": "low",
                                                      "due_date": "2026-04-03"}, keys=["ENG-12"]), {}),
    (_doc("l3", "linear", "Replace the badge printer", {"key": "ENG-13", "status": "In Progress", "priority": "P2", "project": "Lobby Refresh",
                                                        "assignee": "Omar Singh", "creator": "Liam Chen", "customer_impact": "TBD"},
          keys=["ENG-13"]), {}),
    (_doc("c1", "confluence", "Telemetry Runbook: local-only mode", {"author": "Maya Chen", "space": "eng-private"}, RUNBOOK), {}),
]
W = dict.fromkeys(P.FEATURES_V4, 0.0) | {"start_named": 2.0, "path_len": -1.0, "path_overlap": 1.0, "field_overlap": 2.0, "label_field": 1.0,
                                          "answer_named_clue": -3.0, "system_fits": 1.0}
ROW = {"answer", "route", "reason", "evidence", "reads", "journal", "family_scores", "ms"}

FIRST_COMMENT = "Who left the first comment on the Linear issue DES-1?"
UPDATED = "When was DES-1 last updated?"
COUNT = "How many Jira tickets have priority P1?"
KEYS = "Which Jira tickets have priority P1? Give the keys."
PROSE = "How do we verify the telemetry mode?"
PRIVATE = "How do we verify the telemetry mode on a private deployment?"  # the runbook says nothing of private deployments
ABSENT = "What is the customer impact of the Linear issue ENG-13?"
FIELD = "What is the status of ENG-12?"
MISSING = "When was the Linear issue ENG-99 created?"


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    path = tmp_path_factory.mktemp("v16routes")
    B.build(path / "factbank_v2.sqlite", DOCS, text_facts=True)
    Lessons([0.0, 1.0, 1.0, 0.5, 1.0, 0.0], [0.0, 1.0, -0.5, 2.0, 0.0, 0.0, 1.0, -1.0, -2.0, -1.0, 1.0, -1.0, 0.0], [-2.0, 1.0, 2.0, 1.0, 0.0],
            [0.0, 2.0, 0.0, 0.0, 1.0], {}, {}, {}).save(path / "lessons.json")
    P.PlanLessons([W[f] for f in P.FEATURES_V4], {}, {}, {}, list(P.FEATURES_V4), rules="v9", tickets=True,
                  orders=True).save(path / "plans.json")
    return path


def _brain(paths, v16: bool = True, **kw) -> BR.Brain:
    return BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", v16=v16, **kw)


@pytest.fixture
def v16(paths):
    return _brain(paths)


@pytest.fixture
def v15(paths):
    return _brain(paths, v16=False)


def _row_ok(brain: BR.Brain, r: dict, route: str) -> None:
    """The row every route gives: the same keys, the evidence within the budget, a journal that starts with the route."""
    assert set(r) == ROW and r["route"] == route
    assert r["journal"][0]["op"] == "route" and r["journal"][0]["route"] == route and r["journal"][0]["reason"] == r["reason"]
    assert r["evidence"] and len(r["evidence"]) <= brain.budget and r["ms"] >= 0


# ------------------------------------------------------------------ each route
def test_derived(v16, v15):
    r = v16.ask(FIRST_COMMENT)
    _row_ok(v16, r, "derived")
    assert r["answer"] == "Diego Martinez" and r["reason"] == "first_commenter of DES-1: the first dated comment"
    assert r["evidence"].startswith("Answer: Diego Martinez\n[linear] DES-1: Traffic Inspector prototype\n2026-03-10")
    assert r["family_scores"] == {} and "family_scores" not in r["journal"][0], "derived comes before the router"
    assert r["journal"][1] == {"op": "start", "doc": "doc:l1", "label": "DES-1"}
    assert r["journal"][2] == {"op": "derived", "kind": "first_commenter", "doc": "doc:l1", "values": ["Diego Martinez"]}
    assert r["reads"] == {"ends": ["des-1"], "values": ["diego martinez"], "people": ["diego martinez"]}
    assert v15.ask(FIRST_COMMENT)["route"] in ("plan", "fact"), "v15 has no derived route"
    u = v16.ask(UPDATED)
    assert (u["answer"], u["route"]) == ("2026-03-15", "derived") and "updated at: 2026-03-15" in u["evidence"]


def test_table(v16):
    r = v16.ask(COUNT)
    _row_ok(v16, r, "table")
    assert r["answer"] == "2" and r["reason"] == "2 Jira tickets where priority = P1"
    assert r["evidence"].startswith("Answer: 2\n2 Jira tickets where priority = P1:\n- SUP-101: ")
    assert r["family_scores"] == {}, "table comes before the router"
    step = r["journal"][1]
    assert step["op"] == "table" and (step["kind"], step["system"], step["count"]) == ("count", "jira", 2)
    assert step["filters"] == ["priority = P1"] and step["docs"] == ["doc:j1", "doc:j2"]
    assert r["reads"] == {"ends": ["sup-101", "sup-102"], "values": ["2"], "people": []}
    k = v16.ask(KEYS)
    assert (k["answer"], k["route"]) == ("SUP-101, SUP-102", "table") and k["reads"]["values"] == ["sup-101", "sup-102"]


def test_table_takes_a_filtered_list_from_the_planner(v16, v15):
    q = "List every Linear issue assigned to Omar Singh. Give the issue keys."
    a, b = v16.ask(q), v15.ask(q)
    assert (a["answer"], a["route"]) == ("ENG-12, ENG-13", "table") and (b["answer"], b["route"]) == ("ENG-12, ENG-13", "plan")
    assert a["reason"] == "2 Linear issues where assignee = Omar Singh"


def test_prose_quotes_one_document(v16):
    r = v16.ask(PROSE)
    _row_ok(v16, r, "prose")
    assert "port 9100" in r["answer"] and "doc:c1" in r["reason"] and "(quote_cov " in r["reason"]
    assert r["evidence"].startswith("[passage] Telemetry Runbook: local-only mode\n")
    step = r["journal"][1]
    assert step["op"] == "prose" and step["doc"] == "doc:c1" and not step["abstained"] and step["threshold"] == PR.ABSTAIN_BELOW
    assert step["quote_cov"] >= PR.ABSTAIN_BELOW and set(r["family_scores"]) == {"fact", "prose"} and r["reads"] == []


def test_prose_abstains_below_the_threshold(v16):
    r = v16.ask(PRIVATE)
    _row_ok(v16, r, "prose")
    assert r["answer"] == "not found" and r["reason"].startswith("the quote from doc:c1 holds 0.462 of the question's words")
    assert r["reason"].endswith("below 0.47 (quote_cov 0.462)") and r["evidence"].startswith("[passage] Telemetry Runbook")
    assert r["journal"][1] == {"op": "prose", "doc": "doc:c1", "quote_cov": 0.4621, "threshold": 0.47, "abstained": True}
    route = v16.prose_route()
    assert route.threshold == PR.ABSTAIN_BELOW == 0.47, "ProseRoute's default threshold"
    route.threshold = 0.999
    r = v16.ask(PROSE)
    _row_ok(v16, r, "prose")
    assert r["answer"] == "not found" and "below 0.999" in r["reason"] and "(quote_cov " in r["reason"]
    assert r["journal"][1]["abstained"] and r["journal"][1]["quote_cov"] < 0.999 and route_class(r["route"]) == "prose"


def test_v15_prose_without_v16(v15):
    r = v15.ask(PROSE)
    assert r["route"] == "prose" and "passage(s) of 1 document(s): doc:c1" in r["reason"] and "quote_cov" not in r["reason"]
    assert r["journal"] == r["journal"][:1], "v15's prose journal holds the route alone"


def test_absent(v16, v15):
    r = v16.ask(ABSENT)
    _row_ok(v16, r, "absent")
    why = 'the Linear issue ENG-13 has no customer impact (the field says "TBD")'
    assert (r["answer"], r["reason"]) == ("not found", why)
    assert r["evidence"].startswith(f"Not found: {why}.\n[linear] ENG-13: Replace the badge printer\n")
    assert "- customer impact: TBD" in r["evidence"] and "- assignee: Omar Singh" in r["evidence"]
    assert set(r["family_scores"]) == {"fact", "prose"}, "absent comes after the router"
    assert r["journal"][1:] == [{"op": "start", "doc": "doc:l3", "label": "ENG-13"}, {"op": "absent", "doc": "doc:l3", "reason": why}]
    assert r["reads"] == {"ends": ["eng-13"], "values": [], "people": []}
    assert v15.ask(ABSENT)["route"] in ("plan", "fact")


def test_absent_reads_min_held(paths):
    """Two Linear issues in three hold a customer impact: a usual field at ``MIN_HELD`` (0.3), not at 0.9."""
    assert BR.MIN_HELD == 0.3
    assert _brain(paths).records().min_held == BR.MIN_HELD
    strict = _brain(paths, min_held=0.9)
    assert strict.records().min_held == 0.9 and strict.ask(ABSENT)["route"] in ("plan", "fact")


def test_v15_routes_stay(v16, v15):
    a, b = v16.ask(FIELD), v15.ask(FIELD)
    assert (a["answer"], a["route"]) == (b["answer"], b["route"]) == ("Done", "plan"), "a field of a named document: the planner"
    m = v16.ask(MISSING)
    _row_ok(v16, m, "not_found")
    assert m["answer"] == "not found" and m["reason"] == "the bank holds no ticket ENG-99"


def test_route_classes():
    assert [route_class(r) for r in ("derived", "table", "absent", "prose", "plan", "fact", "not_found")] == \
        ["fact", "fact", "not_found", "prose", "fact", "fact", "not_found"]


# ------------------------------------------------------------------ the order
class Spy:
    """Records' four functions, answering as told and counting their calls."""

    def __init__(self, rec: R.Records, monkeypatch, start=None, derived=None, table=None, absent=None):
        self.calls: list[str] = []
        for name, value in (("start", start), ("derived", derived), ("table", table), ("absent", absent)):
            monkeypatch.setattr(rec, name, self.wrap(name, value))

    def wrap(self, name, value):
        def f(*args):
            self.calls.append(name)
            return value
        return f


DERIVED = {"answer": "2026-01-01", "kind": "created_on", "doc": "doc:l1", "reason": "the created at field", "evidence": "[linear] DES-1"}
TABLE = {"answer": "7", "kind": "count", "system": "jira", "filters": ["priority = P9"], "docs": ["doc:j1"], "reason": "7 Jira tickets",
         "evidence": "7 Jira tickets where priority = P9:"}


def test_not_found_comes_first(v16, monkeypatch):
    spy = Spy(v16.records(), monkeypatch, start="doc:l1", derived=DERIVED, table=TABLE, absent="no field")
    assert v16.ask(MISSING)["route"] == "not_found" and spy.calls == []


def test_derived_comes_before_table(v16, monkeypatch):
    spy = Spy(v16.records(), monkeypatch, start="doc:l1", derived=DERIVED, table=TABLE)
    r = v16.ask("When was DES-1 created?")
    assert (r["answer"], r["route"]) == ("2026-01-01", "derived") and spy.calls == ["start", "derived"]


def test_derived_needs_a_start(v16, monkeypatch):
    spy = Spy(v16.records(), monkeypatch, start=None, derived=DERIVED, table=TABLE)
    assert v16.ask("When was DES-1 created?")["route"] == "table" and spy.calls == ["start", "table"]


def test_table_comes_before_the_router(paths, monkeypatch):
    b = BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", BR.Router(["bias"], [5.0]), v16=True)
    spy = Spy(b.records(), monkeypatch, start="doc:l1", table=TABLE, absent="no field")
    monkeypatch.setattr(b, "plan", lambda q: pytest.fail("the router ran"))
    r = b.ask(PROSE)
    assert (r["answer"], r["route"]) == ("7", "table") and spy.calls == ["start", "derived", "table"]


def test_prose_comes_before_absent(paths, monkeypatch):
    always_prose = BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", BR.Router(["bias"], [5.0]), v16=True)
    spy = Spy(always_prose.records(), monkeypatch, start="doc:l3", absent="the Linear issue ENG-13 has no customer impact")
    r = always_prose.ask(ABSENT)
    assert r["route"] == "prose" and "absent" not in spy.calls


def test_absent_comes_before_the_planner_and_needs_a_start(v16, monkeypatch):
    spy = Spy(v16.records(), monkeypatch, start="doc:l2", absent="the Linear issue ENG-12 has no status")
    monkeypatch.setattr(v16, "engine", lambda q: pytest.fail("the engine ran"))
    r = v16.ask(FIELD)
    assert (r["answer"], r["route"], r["reason"]) == ("not found", "absent", "the Linear issue ENG-12 has no status")
    assert spy.calls == ["start", "derived", "table", "absent"]
    monkeypatch.undo()
    spy = Spy(v16.records(), monkeypatch, start=None, absent="never asked")
    assert v16.ask(FIELD)["route"] == "plan" and spy.calls == ["start", "table"]


# ------------------------------------------------------------------ built once, on first use
def test_records_and_the_passage_index_are_built_once(v16, monkeypatch):
    assert v16._records is None and v16._prose_route is None, "nothing built before the first question"
    builds = []
    real = PR.PassageIndex.build

    def build(self):
        if not self.built:
            builds.append(self)
        return real(self)

    monkeypatch.setattr(PR.PassageIndex, "build", build)
    v16.ask(FIELD)
    rec = v16.records()
    assert isinstance(rec, R.Records) and rec.b is v16.bank and v16._prose_route is None, "no prose question yet: no index"
    v16.ask(PROSE)
    route = v16.prose_route()
    assert isinstance(route, PR.ProseRoute) and route.bank is v16.bank and route.budget == v16.budget and route.index.built
    v16.ask(PROSE.replace("verify", "check"))
    v16.ask(COUNT)
    assert len(builds) == 1 and v16.prose_route() is route and v16.records() is rec, "one index and one Records per brain"


def test_v15_builds_nothing_new(v15):
    for q in (FIRST_COMMENT, COUNT, PROSE, ABSENT, FIELD, MISSING):
        assert v15.ask(q)["route"] in ("not_found", "plan", "fact", "prose"), q
    assert v15._records is None and v15._prose_route is None


def test_evidence_within_a_small_budget(paths):
    b = _brain(paths, budget=60)
    for q, route in ((COUNT, "table"), (FIRST_COMMENT, "derived"), (ABSENT, "absent")):
        r = b.ask(q)
        assert r["route"] == route and 0 < len(r["evidence"]) <= 60, q
    b = _brain(paths, budget=1200)
    r = b.ask(PROSE)
    assert r["route"] == "prose" and r["evidence"].startswith("[passage] ") and len(r["evidence"]) <= 1200
    assert b.prose_route().budget == 1200


# ------------------------------------------------------------------ ask_brain and the CLI
QUESTIONS = [("a", FIRST_COMMENT), ("b", COUNT), ("c", PROSE), ("d", ABSENT), ("e", FIELD), ("f", MISSING)]


def _write_questions(path) -> None:
    (path / "questions.jsonl").write_text("".join(json.dumps({"id": i, "question": q}) + "\n" for i, q in QUESTIONS))


def test_ask_brain_v16(paths):
    _write_questions(paths)
    rep = BR.ask_brain(paths, paths / "lessons.json", paths / "plans.json", v16=True)
    assert rep["written"] == "factbank_v16.jsonl"
    assert rep["routes"] == {"derived": 1, "table": 1, "prose": 1, "absent": 1, "plan": 1, "not_found": 1}
    rows = [json.loads(x) for x in (paths / "factbank_v16.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == [i for i, _ in QUESTIONS]
    assert all(set(r) == {"id", *ROW} and r["journal"][0]["route"] == r["route"] for r in rows)
    rep = BR.ask_brain(paths, paths / "lessons.json", paths / "plans.json", name="strict", v16=True, min_held=0.9)
    assert "absent" not in rep["routes"]
    rep = BR.ask_brain(paths, paths / "lessons.json", paths / "plans.json", name="off")
    assert set(rep["routes"]) <= {"not_found", "plan", "fact", "prose"}


def test_main_min_held(paths, capsys):
    _write_questions(paths)
    base = ["ask", "--work", str(paths), "--single", str(paths / "lessons.json"), "--plans", str(paths / "plans.json"), "--v16"]
    assert BR.main([*base, "--name", "v16cli"])["routes"]["absent"] == 1
    rep = BR.main([*base, "--name", "v16strict", "--min-held", "0.9"])
    assert "absent" not in rep["routes"] and '"written": "v16strict.jsonl"' in capsys.readouterr().out
