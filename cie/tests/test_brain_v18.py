"""The company brain's v18 (``Brain(..., v18=True)``): v17 with round 4's fixes, on the tiny bank of the v16 route tests: a title
that joins the start of one real title to the end of another is "not found" (``Brain.spliced``); counts asked the way people
type ("# of…", a lead-in clause, "by" a person: ``Records.v18``); an empty field read whatever the router says, and "can
someone remind me" is not a link; a free-text answer whose document does not write the question's own terms is "not found"
(``Brain.unheld_terms``); and the free-text quote answers each part of the question (``prose.quote_v18``)."""

from __future__ import annotations

import pytest

from cie.factbank import bank as B
from cie.factbank import brain as BR
from cie.factbank import plans as P
from cie.factbank import prose as PR
from cie.factbank import records as R
from cie.factbank.learn import Lessons
from test_brain_v16_routes import DOCS, ROW, W


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    path = tmp_path_factory.mktemp("v18")
    B.build(path / "factbank_v2.sqlite", DOCS, text_facts=True)
    Lessons([0.0, 1.0, 1.0, 0.5, 1.0, 0.0], [0.0, 1.0, -0.5, 2.0, 0.0, 0.0, 1.0, -1.0, -2.0, -1.0, 1.0, -1.0, 0.0], [-2.0, 1.0, 2.0, 1.0, 0.0],
            [0.0, 2.0, 0.0, 0.0, 1.0], {}, {}, {}).save(path / "lessons.json")
    P.PlanLessons([W[f] for f in P.FEATURES_V4], {}, {}, {}, list(P.FEATURES_V4), rules="v9", tickets=True,
                  orders=True).save(path / "plans.json")
    return path


def _brain(paths, **kw) -> BR.Brain:
    return BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", **kw)


def test_v18_is_v17_with_the_fixes(paths):
    b = _brain(paths, v18=True)
    assert b.v16 and b.v17 and b.v18 and b.records().v18
    assert not _brain(paths, v17=True).records().v18


# ------------------------------------------------------------------ not found: spliced titles
SPLICED = "When is the Linear issue Traffic Inspector office wifi keys due?"  # "Traffic Inspector …" + "… office wifi keys"


def test_a_spliced_title_is_not_found(paths):
    b = _brain(paths, v18=True)
    assert b.spliced(b.tidy(SPLICED)) == "traffic inspector office wifi keys"
    r = b.ask(SPLICED)
    assert set(r) == ROW and (r["route"], r["answer"]) == ("not_found", "not found")
    assert "joins the start of one title to the end of another" in r["reason"]
    assert _brain(paths, v17=True).ask(SPLICED)["route"] != "not_found"


def test_real_and_shortened_titles_are_not_spliced(paths):
    b = _brain(paths, v18=True)
    for q in ("When is the Linear issue Traffic Inspector prototype due?", "When is the Rotate office wifi keys issue due?",
              "Who is on the traffic inspector issue?", "When is the Linear issue Rotate wifi keys due?"):
        assert b.spliced(b.tidy(q)) is None, q


def test_holds_words_reads_and_for_an_ampersand(paths):
    b = _brain(paths, v18=True)
    assert b.holds_words("telemetry runbook local only mode")
    assert not b.holds_words("telemetry runbook remote only mode")


# ------------------------------------------------------------------ counts
def test_counts_asked_the_way_people_type(paths):
    rec18, rec17 = _brain(paths, v18=True).records(), _brain(paths, v17=True).records()
    for q in ("for the board deck, how many Jira tickets have priority P1?", "# of jira tickets at priority P1?",
              "quick one - count the jira tickets with priority P1", "fyi prepping for a review - how many jira tickets have priority P1?"):
        t = rec18.table(q)
        assert t is not None and (t["kind"], t["answer"]) == ("count", "2"), q
    assert rec17.table("for the board deck, how many Jira tickets have priority P1?") is None
    assert rec17.table("# of jira tickets at priority P1?") is None


def test_an_aside_must_say_nothing_table_reads(paths):
    rec = _brain(paths, v18=True).records()
    # a clause after the ask is a condition, and one table cannot read leaves the question to the other routes
    assert rec.table("how many jira tickets have priority P1, created after the march offsite?") is None
    assert rec.table("how many jira tickets have priority P1, fyi prepping for a review") is None
    # a lead-in with a value, a "not" or a number is not an aside
    assert rec.table("not the old ones, how many jira tickets have priority P1?") is None
    assert rec.table("for the q3 review, how many jira tickets have priority P1?") is None


def test_by_a_person_names_the_author_role(paths):
    rec = _brain(paths, v18=True).records()
    assert R.BY_ROLES[0] == "author" and "by" in R.FILLER


# ------------------------------------------------------------------ unanswerable
def test_someone_is_not_a_link(paths):
    q = "can someone remind me the due date of ENG-13?"
    rec18, rec17 = _brain(paths, v18=True).records(), _brain(paths, v17=True).records()
    start = rec18.start(q)
    assert start == "doc:l3"
    assert rec18.absent(q, start) == "the Linear issue ENG-13 has no due date"
    assert rec17.absent(q, start) is None  # "someone" is a link word to v16
    assert R.ASK_SOMEONE.sub(" ", "does anyone know who owns it").split() == ["who", "owns", "it"]
    assert R.ASK_SOMEONE.sub(" ", "can someone remind me who owns it").split() == ["me", "who", "owns", "it"]


def test_own_terms(paths):
    b = _brain(paths, v18=True)
    assert b.own_terms("What did the Zorblax pilot agree on the sample-and-hold probe for Argentum Health?") == \
        ["argentum", "health", "zorblax"] or set(b.own_terms("What did the Zorblax pilot agree on the sample-and-hold probe for Argentum "
                                                               "Health?")) == {"argentum", "health", "zorblax"}
    assert b.own_terms("what p95 TTFT did we promise for the 6wk pilot, tmrw?") == ["ttft"]
    assert b.ordinary("happened") and b.ordinary("gettting") and not b.ordinary("zorblax")


def test_a_free_text_answer_needs_the_questions_own_terms(paths):
    b = _brain(paths, v18=True)
    assert b.unheld_terms("How do we verify the telemetry mode on the status endpoint?", "doc:c1") == []
    assert b.unheld_terms("How do we verify the Zorblax telemetry mode?", "doc:c1") == ["zorblax"]
    ans, why, evidence, journal = b.prose_row("How do we verify the Zorblax telemetry mode?")
    assert ans == "not found" and "zorblax" in why and journal[0]["unheld"] == ["zorblax"] and journal[0]["abstained"]


# ------------------------------------------------------------------ free text: the quote
def test_question_parts_and_kinds():
    parts, desc = PR.question_parts("re the vault rewrap incident where pods failed — what was the hotfix and how much jitter will the fix allow?")
    assert parts == ["what was the hotfix", "how much jitter will the fix allow?"]
    assert "incident where pods failed" in desc
    assert [PR.part_kind(p) for p in parts] == [None, "number"]
    assert PR.part_kind("who merged that PR") == "person" and PR.part_kind("when is it due") == "date"
    assert PR.part_kind("what's the docs ticket for it") == "key" and PR.part_kind("what flag gates it") == "code"
    assert PR.question_parts("for the OOM ticket in linear, what default split did they pick?")[0] == ["what default split did they pick?"]


def test_quote_v18_answers_each_part():
    items = [{"id": "d:0", "kind": "passage", "summary": "Claim window race", "document_id": "d",
              "detail": "During the rewrap the pods failed to claim tokens and stayed pending for an hour. "
                        "Diego bumped the controller acceptance window to 100ms and rolled a hotfix to the group. "
                        "The pods recovered after the restart of the leader in the region. "
                        "The permanent fix will tolerate up to 2s jitter with backoff on failures. "
                        "Nobody else was paged during the window that night."}]
    q = "re the rewrap incident where pods failed to claim tokens - what was the hotfix and how much jitter will the permanent fix allow?"
    text, cites = PR.quote_v18(items, q, stop=BR.COVER_STOP)
    assert "100ms" in text and "2s jitter" in text and len(text) <= PR.QUOTE_CAP and cites


def test_v18_keeps_v16s_abstention(paths):
    b17, b18 = _brain(paths, v17=True), _brain(paths, v18=True)
    for q in ("How do we verify the telemetry mode?", "What do the closing notes say about quantum routing?"):
        a17, a18 = b17.prose_route().answer(q), b18.prose_route().answer(q)
        assert a17["abstained"] == a18["abstained"] and a17["quote_cov"] == a18["quote_cov"], q
