"""The company brain's v16 fact-route abstention (``Brain(..., v16=True)`` with ``cover_below``, ``cie.factbank.brain``): the
question's rare words (``Brain.cover_weights``), the share the documents an answer rests on hold (``Brain.cover``), which
answers are checked (``Brain.cover_step``: those chosen by the question's content), the "not found" of route absent_doc and
the row it gives, ``BrainBank.answered``, and the plumbing (``ask_brain``, the CLI's ``--cover-below``). With v16 off, or
``cover_below`` None, nothing is checked and the answers are v15's and v16's as before."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cie.eval.brain2_test import route_class
from cie.factbank import bank as B
from cie.factbank import brain as BR
from cie.factbank import plans as P
from cie.factbank.engine import Result
from cie.factbank.learn import Lessons
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)] if body else [],
                     meta=meta, updated=WHEN, keys=list(keys))


DOCS = [
    (_doc("j1", "jira", "Soft 429s during batch import", {"key": "SUP-101", "status": "In Progress", "priority": "P1",
                                                          "assignee": "Marco Nguyen"},
          "Batch imports hit soft 429s after the proxy rotation; the refill window drifts.", ["SUP-101"]), {}),
    (_doc("j2", "jira", "Webhook retries stall after a deploy", {"key": "SUP-103", "status": "Triage", "priority": "P2",
                                                                 "assignee": "Liam Chen"},
          "Webhook deliveries stall when the retry queue fills up during a deploy.", ["SUP-103"]), {}),
    (_doc("l1", "linear", "Rotate office wifi keys", {"key": "ENG-12", "status": "Done", "priority": "P2", "assignee": "Omar Singh"},
          "Rotate the office wifi keys every quarter.", ["ENG-12"]), {}),
    (_doc("c1", "confluence", "Telemetry runbook for private deployments", {"author": "Maya Chen", "space": "eng-private"},
          "How to switch telemetry to local-only mode on a private deployment and verify it on the status endpoint."), {}),
    (_doc("g1", "github", "Add canary rollback adapter", {"pr_number": "4821", "author": "Ava Chen", "repo": "redwood-deploy",
                                                          "merged_at": "2026-02-20"}, "Adds a rollback adapter for canary deploys."), {}),
]
W = dict.fromkeys(P.FEATURES_V4, 0.0) | {"start_named": 2.0, "path_len": -1.0, "path_overlap": 1.0, "field_overlap": 2.0, "label_field": 1.0,
                                          "answer_named_clue": -3.0, "system_fits": 1.0}
ROW = {"answer", "route", "reason", "evidence", "reads", "journal", "family_scores", "ms"}

MISSING = "Who is assigned to the ticket about webhook signature mismatches in the billing gateway?"  # no such ticket
HELD = "Who is assigned to the ticket about webhook deliveries that stall when the retry queue fills up?"  # SUP-103
KEYED = "Who is assigned to SUP-103?"
TITLED = 'Who wrote "Telemetry runbook for private deployments"?'
NOTHING = "Who wrote the PR that added the shadow traffic mirroring sidecar for staging clusters?"  # v1 finds no fact


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    path = tmp_path_factory.mktemp("v16abstain")
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


def _cover(row: dict) -> dict | None:
    return next((j for j in row["journal"] if j.get("op") == "cover"), None)


# ------------------------------------------------------------------ constants
def test_the_check_is_on_with_v16_at_the_train_fit_and_its_route_declines():
    assert BR.COVER_BELOW == 0.57
    assert route_class(BR.ROUTE_UNCOVERED) == "not_found"
    assert {"between", "many", "people", "know", "remind", "first", "list", "keys", "linked", "who", "please"} <= BR.COVER_STOP
    assert not {"webhook", "gateway", "telemetry"} & BR.COVER_STOP


# ------------------------------------------------------------------ the words
def test_cover_weights_leave_out_quoted_titles_cue_words_words_of_asking_and_numbers(v16):
    q = 'Could you tell me who is assigned to the "Webhook retries stall" ticket for the gateway since 2026, or which webhook?'
    w = v16.cover_weights(q)
    assert "retri" not in w and "stall" not in w, "words only inside a quoted title"
    assert "webhook" in w, "a quoted word the question also writes outside the title stays"
    assert "assign" not in w, "a cue word of the field asked for (v1's CUES)"
    assert not {"could", "tell", "who", "which", "since"} & set(w) and "2026" not in w
    assert {"ticket", "gateway"} <= set(w)


def test_cover_weights_weigh_rare_words_more(v16):
    w = v16.cover_weights(MISSING)
    assert w["signature"] > w["webhook"] > 0, "a word no entity holds weighs more than one a document holds"
    status = v16.cover_weights("What is the status of the ticket about the gateway?")
    assert "status" not in status, "a word of the field asked for (BrainBank.wanted)"


def test_cover_is_the_share_of_the_weight_the_documents_hold(v16):
    w = v16.cover_weights(MISSING)
    share, total, missing = v16.cover(MISSING, ["doc:j2"])
    assert total == pytest.approx(sum(w.values())) and total > BR.COVER_MIN_WEIGHT
    assert share == pytest.approx(w["webhook"] / total)
    assert missing == sorted(set(w) - {"webhook"})
    assert v16.cover(MISSING, [])[0] == 0.0
    assert v16.cover(MISSING, ["doc:j2", "doc:j1"])[0] >= share, "the documents' words together"


def test_a_question_saying_little_beyond_what_it_names_is_not_checked(v16):
    q = "Who reviewed the gateway change?"
    share, total, missing = v16.cover(q, [])
    assert total <= BR.COVER_MIN_WEIGHT and (share, missing) == (1.0, [])


# ------------------------------------------------------------------ asking
def test_a_question_about_a_document_the_bank_lacks_is_not_found(v16):
    r = v16.ask(MISSING)
    assert set(r) == ROW
    assert (r["answer"], r["route"]) == ("not found", BR.ROUTE_UNCOVERED)
    assert "rare words" in r["reason"] and "below 0.57" in r["reason"] and "signature" in r["reason"]
    assert r["evidence"].startswith("Not found: ") and "would have answered: Liam Chen" in r["evidence"]
    step = _cover(r)
    assert step["abstained"] and step["docs"] == ["doc:j2"] and step["cover"] < BR.COVER_BELOW and step["threshold"] == BR.COVER_BELOW
    assert r["journal"][0] == {"op": "route", "route": BR.ROUTE_UNCOVERED, "reason": r["reason"], "family_scores": r["family_scores"]}
    assert r["reads"] == []


def test_a_question_about_a_document_the_bank_holds_is_answered(v16):
    r = v16.ask(HELD)
    assert (r["answer"], r["route"]) == ("Liam Chen", "fact")
    step = _cover(r)
    assert step is not None and not step["abstained"] and step["cover"] >= BR.COVER_BELOW


def test_answers_from_what_the_question_names_and_found_nothing_are_not_checked(v16):
    for q, route in ((KEYED, "plan"), (TITLED, "plan"), (NOTHING, "fact")):
        r = v16.ask(q)
        assert r["route"] == route and _cover(r) is None, q
    assert v16.ask(NOTHING)["answer"] == "not found"


def test_cover_step_skips_a_named_document_and_a_plan_from_a_named_start(v16):
    seeds = [("doc:j2", 1.0)]
    v16.bank.answered = ["doc:j2"]
    res = Result("Liam Chen", "", [], {}, seeds, 0.0)
    assert v16.cover_step("Who is assigned to SUP-103, the gateway signature ticket?", None, result=res) is None
    assert v16.cover_step(MISSING, None, result=res)["abstained"]
    plan = {"best": P.Plan(("doc:g1",), (), "author", "single")}
    assert v16.cover_step('Who wrote "Add canary rollback adapter" for the shadow mirroring sidecar?', None, plan=plan) is None
    step = v16.cover_step("Who wrote the PR for the shadow traffic mirroring sidecar in staging clusters?", None, plan=plan)
    assert step["docs"] == ["doc:g1"] and step["abstained"]
    assert v16.cover_step("Who wrote the PR for the shadow traffic mirroring sidecar in staging clusters?", "doc:g1", plan=plan) is None, \
        "a start Records.start names"


def test_bank_answered_keeps_what_v1_read(paths, v16):
    v16.engine(HELD)
    assert v16.bank.answered == ["doc:j2"]
    v16.engine("List every Jira ticket assigned to Marco Nguyen.")
    assert v16.bank.answered == ["doc:j1"], "the items of a list, by their keys"
    v16.engine(NOTHING)
    assert v16.bank.answered == []
    off = _brain(paths, v16=False)
    off.engine(HELD)
    assert off.bank.answered == [] and "answered" not in vars(off.bank), "v15's engine leaves it alone"


# ------------------------------------------------------------------ off
def test_with_the_check_off_or_v16_off_nothing_is_checked(paths):
    on = _brain(paths)
    none = _brain(paths, cover_below=None)
    r = none.ask(MISSING)
    assert (r["answer"], r["route"]) == ("Liam Chen", "fact") and _cover(r) is None
    v15 = _brain(paths, v16=False)
    v15c = _brain(paths, v16=False, cover_below=0.99)
    for q in (MISSING, HELD, KEYED, TITLED, NOTHING):
        a, b = v15.ask(q), v15c.ask(q)
        assert {k: a[k] for k in ROW - {"ms"}} == {k: b[k] for k in ROW - {"ms"}}, q
        assert _cover(a) is None and a["route"] != BR.ROUTE_UNCOVERED
        x, y = none.ask(q), on.ask(q)
        if y["route"] != BR.ROUTE_UNCOVERED:
            assert (x["answer"], x["route"]) == (y["answer"], y["route"]), "the check only withdraws answers"


# ------------------------------------------------------------------ plumbing
def _work(paths, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "factbank_v2.sqlite").symlink_to(paths / "factbank_v2.sqlite")
    qs = [{"id": "q1", "question": MISSING}, {"id": "q2", "question": HELD}]
    (work / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))
    return work


def test_ask_brain_and_the_cli_pass_the_threshold(paths, tmp_path):
    work = _work(paths, tmp_path)
    rep = BR.ask_brain(work, paths / "lessons.json", paths / "plans.json", v16=True)
    assert rep["routes"] == {BR.ROUTE_UNCOVERED: 1, "fact": 1}
    rows = [json.loads(x) for x in (work / "factbank_v16.jsonl").read_text().splitlines()]
    assert rows[0]["answer"] == "not found" and rows[1]["answer"] == "Liam Chen"
    rep = BR.main(["ask", "--work", str(work), "--single", str(paths / "lessons.json"), "--plans", str(paths / "plans.json"), "--v16",
                   "--cover-below", "0", "--name", "off"])
    assert rep["routes"] == {"fact": 2}, "0 turns the check off"
    rep = BR.ask_brain(work, paths / "lessons.json", paths / "plans.json", name="v15")
    assert rep["routes"] == {"fact": 2}, "v16 off: no check"
