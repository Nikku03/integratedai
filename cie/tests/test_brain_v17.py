"""The company brain's v17 (``Brain(..., v17=True)``): v16 with the described route (``Brain.described``), on the tiny bank of the
v16 route tests. A question that names no document is answered from the document BM25 ranks first when that document holds
enough of the question's words by rarity; lists, counts and questions about documents the bank lacks are left to v16."""

from __future__ import annotations

import json
import re

import pytest

from cie.eval.brain2_test import route_class
from cie.factbank import bank as B
from cie.factbank import brain as BR
from cie.factbank import plans as P
from cie.factbank.learn import Lessons
from test_brain_v16_routes import DOCS, ROW, W

DESCRIBED = "Who wrote the runbook on the local-only telemetry mode?"  # names no document; BM25 ranks the runbook first
ELSEWHERE = "Who wrote the runbook on quantum routing for satellites?"  # no such runbook: BM25's first document covers too little
LIST = "Which tickets does Marco Nguyen have?"


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    path = tmp_path_factory.mktemp("v17")
    B.build(path / "factbank_v2.sqlite", DOCS, text_facts=True)
    Lessons([0.0, 1.0, 1.0, 0.5, 1.0, 0.0], [0.0, 1.0, -0.5, 2.0, 0.0, 0.0, 1.0, -1.0, -2.0, -1.0, 1.0, -1.0, 0.0], [-2.0, 1.0, 2.0, 1.0, 0.0],
            [0.0, 2.0, 0.0, 0.0, 1.0], {}, {}, {}).save(path / "lessons.json")
    P.PlanLessons([W[f] for f in P.FEATURES_V4], {}, {}, {}, list(P.FEATURES_V4), rules="v9", tickets=True,
                  orders=True).save(path / "plans.json")
    return path


def _brain(paths, **kw) -> BR.Brain:
    return BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", **kw)


def test_described_route(paths):
    brain = _brain(paths, v17=True)
    assert brain.v16 and brain.v17, "v17 is v16 with the described route"
    r = brain.ask(DESCRIBED)
    assert set(r) == ROW and (r["route"], r["answer"]) == (BR.ROUTE_DESCRIBED, "Maya Chen")
    assert r["journal"][0]["route"] == BR.ROUTE_DESCRIBED and r["evidence"].startswith("Answer: Maya Chen")
    step = r["journal"][1]
    assert step["op"] == "described" and step["doc"] == "doc:c1" and step["coverage"] >= BR.DESCRIBED_BELOW == step["threshold"]
    assert r["reason"].startswith("Telemetry Runbook: local-only mode is the document BM25 ranks first")
    assert route_class(r["route"]) == "fact"


def test_v16_has_no_described_route(paths):
    r = _brain(paths, v16=True).ask(DESCRIBED)
    assert r["route"] != BR.ROUTE_DESCRIBED and r["answer"] == "Maya Chen"


def test_too_little_covered_is_left_to_v16(paths):
    v17, v16 = _brain(paths, v17=True), _brain(paths, v16=True)
    assert v17.described(ELSEWHERE) is None
    assert v17.ask(ELSEWHERE)["answer"] == v16.ask(ELSEWHERE)["answer"] == "not found"
    strict = _brain(paths, v17=True, described_below=0.99)
    assert strict.described(DESCRIBED) is None and strict.ask(DESCRIBED)["route"] != BR.ROUTE_DESCRIBED


def test_lists_and_counts_are_left_to_v16(paths):
    v17 = _brain(paths, v17=True)
    for q in (LIST, "List every ticket about batch imports", "How many runbooks cover the telemetry mode?",
              "Give the keys of the tickets about webhook retries"):
        assert BR.DESCRIBED_SKIP.search(q.lower()) or BR.LIST_RE.search(q), q
        assert v17.described(q) is None, q
    assert v17.ask(LIST)["answer"] == "SUP-101, SUP-102"


def test_who_is_not_answered_with_a_date(paths):
    hit = _brain(paths, v17=True).described("Who created the runbook on the local-only telemetry mode?")
    assert hit is None or not re.match(r"\d{4}-\d{2}-\d{2}", hit["answer"])


def test_ask_brain_and_cli(paths, tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    (work / "factbank_v2.sqlite").symlink_to(paths / "factbank_v2.sqlite")
    (work / "questions.jsonl").write_text(json.dumps({"id": "q1", "question": DESCRIBED}) + "\n")
    rep = BR.ask_brain(work, paths / "lessons.json", paths / "plans.json", v17=True)
    assert rep["written"] == "factbank_v17.jsonl" and rep["routes"] == {BR.ROUTE_DESCRIBED: 1}
    rep = BR.main(["ask", "--work", str(work), "--single", str(paths / "lessons.json"), "--plans", str(paths / "plans.json"), "--v17",
                   "--described-below", "0.99", "--name", "strict"])
    assert rep["written"] == "strict.jsonl" and BR.ROUTE_DESCRIBED not in rep["routes"]


def test_what_reads_the_field_the_question_names(paths):
    r = _brain(paths, v17=True).ask("Which space holds the runbook on the local-only telemetry mode?")
    assert (r["route"], r["answer"]) == (BR.ROUTE_DESCRIBED, "eng-private")
    assert r["journal"][2] == {"op": "field", "doc": "doc:c1", "field": "space", "weight": r["journal"][2]["weight"], "values": ["eng-private"]}
    assert r["reason"].endswith("the question asks for its space") and r["evidence"].startswith("Answer: eng-private")
    assert r["reads"]["values"] == ["eng-private"]
