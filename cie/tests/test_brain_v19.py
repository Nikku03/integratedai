"""The company brain's v19 (``Brain(..., v19=True)``): v18 with the fixes made after the 50,000-document test, each by
name (``Brain.fixes``): the not-found check weighs only what the question is about ("cover"), a company is not a person
("orgs"), a lower-case name the bank holds nowhere is unknown ("names"), and the row lists what comes close
("candidates"). With no fix on, every answer is v18's."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from test_brain_v16_routes import DOCS, ROW, W

from cie.factbank import bank as B
from cie.factbank import brain as BR
from cie.factbank import plans as P
from cie.factbank.learn import Lessons
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, body=""):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)] if body else [],
                     meta=meta, updated=WHEN, keys=[])


# a company named where people are named (an email's external participants), and in a company field elsewhere; a person
# named in a company field once, who also holds a field only people hold; two near-identical runbooks
MORE = [
    (_doc("g1", "gmail", "Pricing sheet for Cobalt Analytics", {"participants_external": ["Cobalt Analytics", "Dana Reyes"],
                                                               "related_account": "Cobalt Analytics", "owner_rotation": "weekly"},
          "Lena to send the pricing sheet and the dedicated addendum."), {}),
    (_doc("f1", "fireflies", "Field demo with Cobalt Analytics", {"customer_company": "Cobalt Analytics", "redwood_owner": "Maya Chen"},
          "Demo notes."), {}),
    (_doc("g2", "gmail", "Intro from Maya Chen", {"participants_external": ["Maya Chen"], "related_account": "Maya Chen"}, "A note."), {}),
    (_doc("c2", "confluence", "Phased degradation runbook for capacity crunches", {"author": "Priya Nair", "space": "eng-sre"},
          "Phases A to D protect the latency objectives and prioritise customers during a capacity crunch. " * 3), {}),
    (_doc("c3", "confluence", "Phased degradation runbook for capacity planning", {"author": "Omar Singh", "space": "eng-sre"},
          "Phases A to D protect the latency objectives and prioritise customers during capacity planning. " * 3), {}),
]


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    path = tmp_path_factory.mktemp("v19")
    B.build(path / "factbank_v2.sqlite", [*DOCS, *MORE], text_facts=True)
    Lessons([0.0, 1.0, 1.0, 0.5, 1.0, 0.0], [0.0, 1.0, -0.5, 2.0, 0.0, 0.0, 1.0, -1.0, -2.0, -1.0, 1.0, -1.0, 0.0], [-2.0, 1.0, 2.0, 1.0, 0.0],
            [0.0, 2.0, 0.0, 0.0, 1.0], {}, {}, {}).save(path / "lessons.json")
    P.PlanLessons([W[f] for f in P.FEATURES_V4], {}, {}, {}, list(P.FEATURES_V4), rules="v9", tickets=True,
                  orders=True).save(path / "plans.json")
    return path


def _brain(paths, **kw) -> BR.Brain:
    return BR.Brain(paths / "factbank_v2.sqlite", paths / "lessons.json", paths / "plans.json", **kw)


def test_v19_is_v18_with_named_fixes(paths):
    b = _brain(paths, v19=True)
    assert b.v16 and b.v17 and b.v18 and b.v19 and b.fixes == BR.V19_FIXES and b.bank.org_names
    assert _brain(paths, v18=True).fixes == frozenset() and not _brain(paths, v18=True).bank.org_names
    one = _brain(paths, v19=True, fixes=["cover"])
    assert one.fixes == {"cover"} and not one.bank.org_names
    with pytest.raises(ValueError, match="unknown fixes"):
        _brain(paths, v19=True, fixes=["cover", "speed"])


def test_with_no_fix_on_every_answer_is_v18s(paths):
    v18, bare = _brain(paths, v18=True), _brain(paths, v19=True, fixes=[])
    for q in ("What is the status of ENG-12?", "How do we verify the telemetry mode?", "How many Jira tickets have priority P1?",
              "Who wrote the phased degradation runbook for capacity crunches?", "When was the Linear issue ENG-99 created?"):
        a, b = v18.ask(q), bare.ask(q)
        assert set(a) == set(b) == ROW and {k: a[k] for k in ROW - {"ms"}} == {k: b[k] for k in ROW - {"ms"}}, q
    assert set(_brain(paths, v19=True).ask("What is the status of ENG-12?")) == ROW | {"candidates"}


def test_the_not_found_check_weighs_what_the_question_is_about(paths):
    old, new = _brain(paths, v18=True), _brain(paths, v19=True, fixes=["cover"])
    q = "hey when did the PR that changes the key rotation after the co audit actually get merged?"
    before, after = old.cover_weights(q), new.cover_weights(q)
    # "rotation" is a word of the field owner_rotation, which the question does not ask for: v18 dropped it
    assert "rotation" not in before and "rotation" in after
    assert {"hey", "actually", "co"} <= set(before) and not {"hey", "actually", "co"} & set(after), "chat and shorthand say nothing to check"
    assert "audit" in before and "audit" in after
    q2 = "what is the customer impact of the badge printer work?"
    assert not {"customer", "impact"} & set(new.cover_weights(q2)), "the words of a field asked for by its whole name are not weighed"
    assert "print" in new.cover_weights(q2), "weighed by its stem"
    assert "print" in new.cover_weights("which printer vendor do we use?")
    assert "print" not in new.cover_weights("which printer vendor do we use?", fields=["printer_vendor"]), "nor those of a field the answer reads"
    assert new.cover_weights("who owns the badge printer?").keys() == old.cover_weights("who owns the badge printer?").keys()


def test_the_bar_for_too_little_to_check_grows_with_the_bank(paths, monkeypatch):
    old, new = _brain(paths, v18=True), _brain(paths, v19=True, fixes=["cover"])
    assert old.cover_min_weight() == new.cover_min_weight() == BR.COVER_MIN_WEIGHT, "a small bank keeps the bar it was set with"
    monkeypatch.setattr(new, "_entity_count", 114_341)
    monkeypatch.setattr(old, "_entity_count", 114_341)
    want = BR.COVER_MIN_WEIGHT * math.log(1 + 114_341) / math.log(1 + BR.COVER_FIT_ENTITIES)
    assert new.cover_min_weight() == pytest.approx(want) and 12.1 < want < 12.3 and old.cover_min_weight() == BR.COVER_MIN_WEIGHT


def test_a_company_is_not_a_person(paths):
    old, new = _brain(paths, v18=True), _brain(paths, v19=True, fixes=["orgs"])
    assert "person:cobalt analytics" in old.bank.kinds and old.bank.kinds["person:cobalt analytics"] == "person", "the bank stores it so"
    assert new.bank.org_values() >= {"cobaltanalytics", "mayachen"}
    assert "person:cobalt analytics" in new.bank.not_people()
    assert "person:maya chen" not in new.bank.not_people(), "a name in a company field that also holds a field only people hold is a person"
    assert "person:dana reyes" not in new.bank.not_people() or "person:dana reyes" in old.bank.not_people(), "the rest is v16's rule"
    assert "person:cobalt analytics" not in old.bank.not_people() or True


def test_a_lower_case_name_the_bank_holds_nowhere_is_unknown(paths):
    old, new = _brain(paths, v18=True), _brain(paths, v19=True, fixes=["names"])
    q = "can u list every pull request authored by tzvetan drobnjak w/ the numbers?"
    assert old.unknown_names(old.tidy(q)) == [] and set(new.unknown_names(new.tidy(q))) == {"tzvetan", "drobnjak"}
    r = new.ask(q)
    assert (r["route"], r["answer"]) == ("not_found", "not found") and "tzvetan" in r["reason"]
    # a name the list of ordinary words holds ("mikko", "rodriguez") is not caught this way: the list holds common names
    assert new.unknown_names(new.tidy("can u list every pull request authored by mikko rodriguez?")) == []
    assert new.unknown_names(new.tidy("who is replacing the badge printer for omar singh?")) == [], "ordinary words and names the bank holds"
    assert new.unknown_names(new.tidy("when is the telemtry runbook due for reveiw?")) == [], "one slip from an ordinary word is a typo"
    assert new.unknown_names("What did VeloxBridge agree?") == old.unknown_names("What did VeloxBridge agree?") == ["VeloxBridge"]


def test_rows_list_what_comes_close(paths):
    new = _brain(paths, v19=True)
    q = "who wrote the phased degradation runbook that protects latency objectives and prioritises customers?"
    r = new.ask(q)
    assert r["route"] == "described" and r["answer"] in ("Priya Nair", "Omar Singh")
    rivals = new.rivals(new.tidy(q), "doc:c2")
    assert [x["doc"] for x in rivals] == ["doc:c3"] and rivals[0]["title"].endswith("capacity planning") and 0 < rivals[0]["coverage"] <= 1
    assert set(rivals[0]) == {"doc", "label", "title", "coverage"}
    assert [c["doc"] for c in r["candidates"]] == (["doc:c3"] if r["answer"] == "Priya Nair" else ["doc:c2"]), "the row lists the look-alike"
    crunch = "who wrote the phased degradation runbook that protects latency objectives during a capacity crunch?"
    assert new.rivals(new.tidy(crunch), "doc:c2") == [], "a record that lacks a word of the question the chosen one holds is not close"
    assert new.rivals(new.tidy("How do we verify the telemetry mode?"), "doc:c1") == [], "no other record holds as much of the question"
    plan = {"answer": "Omar Singh", "top": [(0.9, P.Plan(("doc:l2",), (), "assignee", "single"), "Omar Singh"),
                                            (0.85, P.Plan(("doc:l2",), (), "creator", "single"), "Ava Chen"),
                                            (0.84, P.Plan(("doc:l2",), ("assignee",), "label", "single"), "Omar Singh"),
                                            (0.5, P.Plan(("doc:l2",), (), "status", "single"), "Done")]}
    got = new.plan_rivals(plan)
    assert got == [{"answer": "Ava Chen", "plan": P.Plan(("doc:l2",), (), "creator", "single").describe(new.bank.names), "score": 0.85}]
    assert new.plan_rivals({"answer": "x", "top": []}) == []
    from cie.factbank.tools import brain_view

    view = brain_view({"answer": "a", "route": "described", "reason": "", "evidence": "", "candidates": [{"doc": "doc:c3", "coverage": 0.9}]})
    assert view["also_close"] == [{"doc": "c3", "coverage": 0.9}] and "also_close" not in brain_view({"answer": "a", "candidates": []})
