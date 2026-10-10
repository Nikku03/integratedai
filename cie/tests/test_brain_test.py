"""The company brain's test harness: the draw and what it sets aside, the small control folder, the banks, every arm's
answers (the brain stubbed) and the scores."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from cie.eval import brain_questions as B
from cie.eval import brain_test as H
from cie.eval.memory_test import _jsonl, _write_jsonl

DOCS = {
    "linear/ENG-11.json": {"key": "ENG-11", "title": "Gateway timeout retries for streaming", "assignee": "Omar Singh", "creator": "Ava Lee",
                           "status": "In Progress", "priority": "P1", "project": "gateway-hardening", "due_date": "2026-03-20",
                           "description": "Retry the gateway on timeouts. The retry budget is three attempts with a 250 ms backoff."},
    "linear/ENG-12.json": {"key": "ENG-12", "title": "Keycard reader firmware update", "assignee": "Omar Singh", "creator": "Ava Lee",
                           "status": "Todo", "priority": "P2", "project": "gateway-hardening", "due_date": "2026-04-02",
                           "parent_issue": "ENG-11", "dependencies": ["ENG-13"]},
    "linear/ENG-13.json": {"key": "ENG-13", "title": "Rate limiter for the billing API", "assignee": "Liam Chen", "creator": "Maya Chen",
                           "status": "Done", "priority": "P1", "project": "billing", "due_date": "2026-05-01"},
    "linear/ENG-14.json": {"key": "ENG-14", "title": "Billing export to the warehouse", "assignee": "Liam Chen", "creator": "Maya Chen",
                           "status": "Todo", "priority": "P3", "project": "billing", "due_date": "2026-05-09"},
    "jira/SUP-41.json": {"key": "SUP-41", "title": "Customer sees 5xx on upload", "assignee": "Priya Desai", "reporter": "Jordan Patel",
                         "status": "Open", "priority": "High", "customer_company": "Kitebridge", "sla_due_at": "2026-03-14"},
    "jira/SUP-42.json": {"key": "SUP-42", "title": "Export job stalls overnight", "assignee": "Priya Desai", "reporter": "Jordan Patel",
                         "status": "Resolved", "priority": "Low", "customer_company": "Kitebridge", "sla_due_at": "2026-03-18"},
    "github/pr-4821.json": {"pr_number": 4821, "title": "Add gateway retry with backoff", "author": "Maya Chen", "repo": "gateway",
                            "merged_at": "2026-02-20", "reviewers": ["Liam Chen", "Ava Lee"], "linked_linear": ["ENG-11"]},
    "fireflies/sync.json": {"title": "Weekly gateway sync with Kitebridge", "recorded_at": "2026-02-10", "redwood_owner": "Ava Lee",
                            "customer_company": "Kitebridge", "redwood_attendees": ["Ava Lee", "Omar Singh"], "customer_attendees": ["Dana Fox"],
                            "action_items": ["Omar Singh - ship the keycard reader firmware update - Due: 2026-03-01"]},
    "google_drive/runway.json": {"title": "Runway model for Q3 planning", "owner": "Maya Chen", "status": "in_review", "created_at": "2026-01-05"},
    "confluence/oncall.json": {"title": "On-call handbook for the gateway", "author": "Liam Chen", "space": "ENG", "last_updated": "2026-01-20",
                               "body": "Escalate gateway incidents to the platform lead within 15 minutes. Pages go to the gateway rotation first."},
}
PROSE = [{"question_id": "p1", "question": "How many retry attempts does the gateway make on timeouts?", "expected_doc_ids": ["d0"],
          "answer_facts": ["three attempts", "250 ms backoff"]},
         {"question_id": "p2", "question": "What does the deleted page say?", "expected_doc_ids": ["d99"], "answer_facts": ["nothing here"]},
         {"question_id": "p3", "question": "Is anything not in the documents?", "expected_doc_ids": [], "answer_facts": ["no information"]}]
MIX = {"deadlines": 2, "lists": 2, "fields": 4, "names": 2, "link": 2, "combine": 2, "compare": 1, "not_found": 2, "prose": 2}


def _bench(tmp_path: Path) -> Path:
    """A tiny benchmark folder in the raw export format and a work folder over all of its documents."""
    src = tmp_path / "bench" / "generated_data" / "sources"
    index = {}
    for i, (rel, d) in enumerate(DOCS.items()):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(json.dumps(d))
        index[f"d{i}"] = rel
    work = tmp_path / "w"
    work.mkdir()
    (work / "haystack.json").write_text(json.dumps({"root": str(tmp_path / "bench"), "dsids": sorted(index)}))
    (work / "index.json").write_text(json.dumps({"root": str(src), "index": index}))
    _write_jsonl(tmp_path / "prose.jsonl", PROSE)
    return work


def _lessons(tmp_path: Path) -> tuple[Path, Path]:
    from cie.factbank import learn as L
    from cie.factbank import plans as P

    single, plans = tmp_path / "lessons.json", tmp_path / "plan_lessons.json"
    L.Lessons([0.0] * len(L.ENTITY_FEATURES), [0.0] * len(L.ANSWER_FEATURES), [0.0] * len(L.LIST_FEATURES),
              [0.0] * len(L.RELATION_FEATURES), {}, {}, {}).save(single)
    P.PlanLessons([0.0] * len(P.FEATURES_V4), {}, {}, {}, list(P.FEATURES_V4), rules="v9", tickets=True, orders=True).save(plans)
    return single, plans


def _brain_stub(monkeypatch, calls: list) -> None:
    """``cie.factbank.brain`` as its builder describes it: ask_brain(work, single, plans, name, router) writes rows {id, answer,
    route, reason, evidence, ms, reads, journal}. The stub says "not found" to questions about pull requests and quotes the
    gateway's retry budget otherwise."""

    def ask_brain(work, single, plans, name="factbank_v15", router=None):
        calls.append({"single": single, "plans": plans, "name": name, "router": router})
        rows = []
        for q in _jsonl(Path(work) / "questions.jsonl"):
            nf = "pull request" in q["question"].lower() or "PR #" in q["question"]
            rows.append({"id": q["id"], "answer": "not found" if nf else "Three attempts with a 250 ms backoff.",
                         "route": "not_found" if nf else "prose", "reason": "", "ms": 1.5, "reads": [], "journal": [],
                         "evidence": "The retry budget is three attempts with a 250 ms backoff.\n\nOther text."})
        _write_jsonl(Path(work) / f"{name}.jsonl", rows)
        return {"questions": len(rows)}

    stub = types.ModuleType("cie.factbank.brain")
    stub.ask_brain = ask_brain
    monkeypatch.setitem(sys.modules, "cie.factbank.brain", stub)


def test_the_mix_scales_and_parses():
    assert H.scale(B.DEFAULT_MIX, 40) == {"deadlines": 4, "lists": 4, "fields": 8, "names": 4, "link": 5, "combine": 5, "compare": 2,
                                          "not_found": 4, "prose": 4}
    assert sum(H.scale({"a": 1, "b": 1, "c": 1}, 10).values()) == 10 and H.scale({}, 5) == {}
    assert H.parse_mix('{"fields": 3, "descriptive": 2}') == {"fields": 3, "descriptive": 2} and H.parse_mix(None) is None
    with pytest.raises(ValueError):
        H.parse_mix('{"fields": -1}')


def test_routes_are_read_as_fact_prose_or_not_found():
    assert [H.route_class(r) for r in ("not_found", "not found", "prose", "prose:quotes", "fact", "v1", None)] == \
        ["not_found", "not_found", "prose", "prose", "fact", "fact", None]


def test_rules_are_applied_but_not_decided_here():
    rep = {"scores": {"v15": {"mean_of_families": 0.9}}}
    got = H.rules(rep, {"high": lambda r: r["scores"]["v15"]["mean_of_families"] >= 0.8, "missing arm": lambda r: r["scores"]["v99"],
                        "undecided": lambda r: None})
    assert got == {"high": True, "missing arm": None, "undecided": None}
    assert H.rules(rep, {}) == {}
    why: dict = {}
    got = H.rules({"small": None, "scores": {}}, {"drift": lambda r: r["small"].get("differences"), "share": lambda r: 1 / len(r["scores"])}, why)
    assert got == {"drift": None, "share": None}, "a section the report lacks, read with .get, or a share of nothing"
    assert why["drift"].startswith("AttributeError") and why["share"].startswith("ZeroDivisionError")


def test_the_draw_is_brain_questions_own_and_sets_aside_what_has_two_answers(tmp_path):
    work = _bench(tmp_path)
    docs = H.load_docs(work)
    prose = B.load_prose(tmp_path / "prose.jsonl")
    qs, aside, rep = H.draw(docs, 3, MIX, prose)
    kept_prose = [q for q in prose if q["id"] == "p1"]
    assert qs == B.draw_questions(docs, 3, MIX, prose=kept_prose), "the draw is brain_questions.draw_questions"
    assert rep["questions"] == len(qs) and sum(rep["by_family"].values()) == len(qs)
    assert set(rep["by_family"]) <= set(B.FAMILIES) and "prose" in rep["by_family"] and "not_found" in rep["by_family"]
    assert rep["set_aside"]["writers"]["prose"] == {"gold document outside the haystack": 1, "no gold document": 1}
    assert not [q for q in aside if q["kind"] == "prose"], "questions about other documents are counted, not written"
    multi_aside = sum(n for k, why in rep["set_aside"]["generated"].items() if k in B.MULTI_KINDS for n in why.values())
    assert multi_aside == sum(1 for q in aside if q["kind"] in B.MULTI_KINDS), "every multi question generate sets aside is written"
    assert rep["mix_given"]["prose"] == 1 and rep["available"]["prose"] == 1
    twin = [*docs, {**docs[0], "dsid": "x"}]  # ENG-11 on two documents
    _, aside2, rep2 = H.draw(twin, 3, {"prose": 1}, [{**prose[0], "question": "How often does ENG-11 retry?"}])
    assert [(q["id"], q["unclear"]) for q in aside2] == [("p1", "named")] and rep2["questions"] == 0


def test_descriptive_questions_join_the_draw_unless_they_name_two_things(tmp_path):
    work = _bench(tmp_path)
    docs = H.load_docs(work)
    rows = [{"id": "w1", "question": "Which space is the on-call handbook kept in?", "expected": {"value": "ENG"}, "gold_docs": ["d9"]},
            {"id": "w2", "question": "Who has ENG-11 and ENG-11?", "expected": {"value": "Omar Singh"}, "gold_docs": ["d0"]},
            {"id": "w3", "question": "What is it?", "expected": {"facts": []}, "gold_docs": ["d0"]},
            {"id": "w4", "question": "What is it about?", "expected": {"facts": ["the of"]}, "family": "prose", "gold_docs": ["d0"]}]
    _write_jsonl(tmp_path / "desc.jsonl", rows)
    desc = H.load_descriptive(tmp_path / "desc.jsonl")
    assert desc[0]["family"] == "single" and desc[0]["kind"] == "descriptive" and desc[0]["origin"] == "descriptive"
    twin = [*docs, {**docs[0], "dsid": "x"}]  # ENG-11 on two documents
    qs, aside, rep = H.draw(twin, 3, {"fields": 2, "descriptive": 5}, descriptive=desc)
    assert [q["id"] for q in qs if q["kind"] == "descriptive"] == ["w1"]
    assert {q["id"]: q["unclear"] for q in aside if q.get("origin")} == \
        {"w2": "named", "w3": "bad expected (not one of value, date, names, ids)", "w4": "not checkable"}
    one, _, _ = H.draw(docs, 3, {"descriptive": 0}, descriptive=desc)
    assert one == [], "the mix says how many descriptive questions"
    taken = H.draw(docs, 3, {"fields": 1})[0][0]["id"]
    with pytest.raises(ValueError, match="twice"):
        H.draw(docs, 3, {"fields": 1}, descriptive=[{**desc[0], "id": taken}])


def test_descriptive_answers_code_cannot_score_are_set_aside_and_scoring_runs(tmp_path):
    work = _bench(tmp_path)
    ask = {"blocks": "Which tickets block the keycard reader firmware update?", "who": "Who is assigned the keycard reader firmware update?",
           "due": "When is the keycard reader firmware update due?"}
    rows = [{"id": "m1", "question": ask["blocks"], "expected": {"ids": ["ENG-13"]}},
            {"id": "m2", "question": ask["who"], "expected": {"names": "Omar Singh"}},
            {"id": "m3", "question": ask["due"], "expected": {"date": "2 April 2026"}},
            {"id": "m4", "question": ask["due"], "expected": {"value": "Todo", "date": "2026-04-02"}},
            {"id": "m5", "question": ask["blocks"], "expected": {"ids": ["eng-13"], "id_kind": "key"}},
            {"id": "m6", "question": ask["who"], "expected": {"value": "Omar Singh", "alts": "Omar"}},
            {"id": "m7", "question": ask["who"], "expected": {"value": "Omar Singh"}, "family": "singel"},
            {"id": "k1", "question": ask["blocks"], "expected": {"ids": ["ENG-13"], "id_kind": "key"}},
            {"id": "k2", "question": ask["who"], "expected": {"names": ["Omar Singh"]}},
            {"id": "k3", "question": ask["due"], "expected": {"date": "2026-04-02"}}]
    _write_jsonl(tmp_path / "desc.jsonl", [{**r, "gold_docs": ["d1"]} for r in rows])
    H.write_questions(work, 3, {"fields": 2}, descriptive=tmp_path / "desc.jsonl")
    assert [q["id"] for q in _jsonl(work / "questions.jsonl") if q["kind"] == "descriptive"] == ["k1", "k2", "k3"]
    assert {q["id"]: q["unclear"] for q in _jsonl(work / "set_aside_questions.jsonl")} == {
        "m1": "bad expected (ids)", "m2": "bad expected (names)", "m3": "bad expected (date)",
        "m4": "bad expected (not one of value, date, names, ids)", "m5": "scorer cannot match", "m6": "bad expected (value)", "m7": "bad family"}
    H.ask(work, "quotes")
    rows = {r["id"]: r for r in H.score(work)["rows"]}
    assert all(rows[k]["score"]["quotes"] is not None for k in ("k1", "k2", "k3"))
    q2 = next(q for q in _jsonl(work / "questions.jsonl") if q["id"] == "k2")
    assert B.score(q2, "Omar Singh") == 1.0


def test_quote_citation_markers_are_not_answers(tmp_path):
    work = _bench(tmp_path)
    q = {"id": "c1", "group": "combine", "kind": "person_count", "family": "multi", "field": "", "expected": {"value": "2"},
         "question": "How many Linear tickets does Omar Singh have on their plate?", "gold_docs": ["d0", "d1"], "pieces": ["ENG-11", "ENG-12"]}
    _write_jsonl(work / "questions.jsonl", [q])
    H.ask(work, "quotes")
    quoted = 'Gateway timeout retries: "Omar Singh owns the retry work." [1]. Keycard reader: "Omar Singh ships the firmware." [2].'
    _write_jsonl(work / "quotes.jsonl", [{"id": "c1", "answer": quoted, "route": "prose"}])
    assert B.score(q, quoted) == 1.0, "the marker [2] alone would hold the count"
    assert H.plain_answer(quoted) == 'Gateway timeout retries: "Omar Singh owns the retry work.". Keycard reader: "Omar Singh ships the firmware.".'
    row = H.score_rows(work)["rows"][0]
    assert row["score"]["quotes"] == 0.0 and row["chars"]["quotes"] == len(quoted)
    stated = quoted.replace("the firmware.", "the firmware; 2 tickets in all.")
    _write_jsonl(work / "quotes.jsonl", [{"id": "c1", "answer": stated, "route": "prose"}])
    assert H.score_rows(work)["rows"][0]["score"]["quotes"] == 1.0, "a count the quote states still counts"


def test_the_small_folder_of_another_draw_gives_no_differences(tmp_path):
    work, small = _bench(tmp_path), tmp_path / "small"
    H.write_questions(work, 3, MIX, small=small)
    H.ask(small, "quotes")
    H.write_questions(work, 5, MIX)  # another draw, the control folder left as it was
    H.ask(work, "quotes")
    rep = H.score(work, small, rule_fns={"drift": lambda r: r["small"]["differences"].get("quotes")})
    sm = rep["small"]
    assert sm["same_questions"] is False and sm["differences"] is None and sm["scores"]["quotes"]["answered"] > 0
    assert rep["rules"] == {"drift": None} and rep["rules_why"]["drift"].startswith("AttributeError")
    md = (work / "report.md").read_text()
    assert "another draw's): no differences" in md and "| arm | questions |" not in md and "AttributeError" in md
    H.write_questions(work, 3, MIX)  # the control folder's draw again, without --small
    H.ask(work, "quotes")
    rep = H.score(work, small)
    assert rep["small"]["same_questions"] and rep["small"]["differences"]["quotes"]["questions"] == rep["questions"]


def test_answers_over_other_documents_are_refused_or_left_out(tmp_path):
    from cie.eval import factbank_test

    work, small = _bench(tmp_path), tmp_path / "small"
    H.write_questions(work, 3, {"fields": 1}, small=small)
    H.build(small, v1=True)
    H.ask(small, "v1")
    assert H.answered(small) == ({"v1": "factbank"}, {}) and set(H.banks(small)) == {"factbank", "factbank_v2"}
    H.write_questions(work, 3, MIX, small=small)  # the control folder now holds more documents, its banks the old ones
    assert len(json.loads((small / "haystack.json").read_text())["dsids"]) > 2
    with pytest.raises(ValueError, match="other documents"):
        H.ask(small, "v1")
    assert H.answered(small)[1] == {"v1": "answered other questions"}
    H.build(small, v1=True)
    H.ask(small, "v1")
    H.ask(small, "quotes")
    assert set(H.answered(small)[0]) == {"v1", "quotes"}
    hay = json.loads((small / "haystack.json").read_text())
    (small / "haystack.json").write_text(json.dumps({**hay, "dsids": hay["dsids"][:-1]}))  # the same questions, fewer documents
    assert H.answered(small) == ({}, {"v1": "answered with another haystack", "quotes": "answered with another haystack"})
    factbank_test.build(work, "factbank", text_facts=False)  # built outside the harness: nothing says which documents it holds
    with pytest.raises(ValueError, match="no record"):
        H.ask(work, "v1")


def test_a_name_cannot_take_another_arms_answers_or_a_question_file(tmp_path):
    work = _bench(tmp_path)
    H.write_questions(work, 3, {"fields": 2})
    H.ask(work, "quotes")
    H.ask(work, "quotes", name="mine")
    lessons = (tmp_path / "l.json", tmp_path / "p.json")
    for arm, name, why in (("v1", "quotes", "arm quotes's answers file"), ("v2", "factbank", "arm v1's answers file"),
                           ("v1", "mine", "holds arm quotes's answers"), ("quotes", "questions", "cannot name"),
                           ("quotes", "../elsewhere", "cannot name")):
        with pytest.raises(ValueError, match=why):
            H.ask(work, arm, *lessons, name=name)
    assert {n: r["arm"] for n, r in H.registry(work).items()} == {"quotes": "quotes", "mine": "quotes"}
    assert len(_jsonl(work / "questions.jsonl")) == 2


def test_questions_write_the_set_the_set_aside_and_the_small_control(tmp_path):
    work = _bench(tmp_path)
    rep = H.write_questions(work, 3, MIX, prose=tmp_path / "prose.jsonl", small=tmp_path / "small")
    qs = _jsonl(work / "questions.jsonl")
    assert len(qs) == rep["questions"] > 10 and (work / "set_aside_questions.jsonl").exists()
    assert json.loads((work / H.REPORT).read_text())["questions"] == len(qs)
    small = tmp_path / "small"
    gold = sorted({x for q in qs for x in q["gold_docs"]})
    assert json.loads((small / "haystack.json").read_text())["dsids"] == gold
    assert _jsonl(small / "questions.jsonl") == qs and (small / "index.json").exists()
    assert rep["small"]["not_reproduced"] == {}, "every expected answer rests on gold documents only"
    with pytest.raises(ValueError):
        H.write_questions(work, 3, MIX, small=work)


def test_answers_that_do_not_reproduce_in_the_small_set_are_recorded(tmp_path):
    work = _bench(tmp_path)
    docs = H.load_docs(work)
    qs, _, _ = H.draw(docs, 3, MIX)
    lists = next(q for q in qs if q["kind"] in B.MEMORY_KINDS and "ids" in q["expected"])
    field = next(q for q in qs if q["kind"] in B.FIELDS)
    nf = next(q for q in qs if q["family"] == "not_found")
    wrong = [{**lists, "expected": {**lists["expected"], "ids": ["ENG-99"]}}, {**field, "expected": {"value": "nobody"}},
             {**nf, "pieces": ["ENG-11"]}, {**field, "id": "gone", "kind": "descriptive", "gold_docs": ["d0"]}]
    small = {x for q in qs for x in q["gold_docs"]} - {"d0"}
    got = H.not_reproduced(docs, small | {x for q in wrong[:2] for x in q["gold_docs"]}, wrong, 3)
    assert got[lists["id"]] == "differs" and got[field["id"]] == "differs" and got[nf["id"]] == "differs"
    assert got["gone"] == "gold document outside the set"


def test_generated_lists_and_a_parents_other_field_reproduce_on_their_gold_documents(tmp_path):
    work = _bench(tmp_path)
    docs = H.load_docs(work)
    qs = B.generate(docs, 3, kinds={"parent_issue", "linear_project_members", "customer_tickets", "linear_assignee"})[0]
    assert {q["kind"] for q in qs} == {"parent_issue", "linear_project_members", "customer_tickets", "linear_assignee"}
    small = {x for q in qs for x in q["gold_docs"]}
    assert small < {d["dsid"] for d in docs} and H.not_reproduced(docs, small, qs, 3) == {}
    parent = next(q for q in qs if q["kind"] == "parent_issue")
    other = {"status": ("assignee", {"value": "Omar Singh"}), "assignee": ("status", {"value": "In Progress"})}
    field, expected = other[parent["field"]]
    assert H.not_reproduced(docs, small, [{**parent, "field": field, "expected": expected}], 3) == {}, "the same parent, the other field"
    wrong = {**parent, "field": field, "expected": {"value": "Done"}}
    assert H.not_reproduced(docs, small, [wrong], 3) == {parent["id"]: "differs"}
    assert H.not_reproduced(docs, small, [{**parent, "pieces": ["ENG-14", *parent["pieces"][1:]]}], 3) == {parent["id"]: "not asked"}


def test_build_ask_every_arm_and_score(tmp_path, monkeypatch):
    work = _bench(tmp_path)
    H.write_questions(work, 3, MIX, prose=tmp_path / "prose.jsonl", small=tmp_path / "small")
    single, plans = _lessons(tmp_path)
    calls: list = []
    _brain_stub(monkeypatch, calls)
    for w in (work, tmp_path / "small"):
        built = H.build(w, v1=True)
        assert set(built) == {"factbank_v2", "factbank"} and all(b["bytes"] > 0 and b["seconds"] >= 0 for b in built.values())
        assert (w / "factbank_v2.sqlite").exists() and (w / "factbank_build.json").exists()
        H.ask(w, "v1")
        H.ask(w, "v2", single)
        H.ask(w, "v13", single, plans)
        H.ask(w, "v15", single, plans, router="v1-fallback")
        H.ask(w, "quotes")
    assert calls[0]["router"] == "v1-fallback" and calls[0]["name"] == "factbank_v15"
    with pytest.raises(ValueError, match="single"):
        H.ask(work, "v2")
    with pytest.raises(ValueError, match="plan"):
        H.ask(work, "v13", single)
    H.ask(work, "v1", name="factbank_again")
    assert (work / "factbank_again.jsonl").exists() and H.registry(work)["factbank_again"]["label"] == "factbank_again"
    with pytest.raises(ValueError, match="label"):
        H.ask(work, "quotes", name="v1")
    reg = H.registry(work)
    assert reg["factbank"]["single"] is None and reg["factbank_v2"]["plans"] is None and reg["factbank_v15"]["router"] == "v1-fallback"
    quotes = {r["id"]: r for r in _jsonl(work / "quotes.jsonl")}
    assert all(r["route"] == "prose" for r in quotes.values())
    p1 = quotes["p1"]
    assert "three attempts" in p1["answer"].lower() and p1["cited"][0] == "d0" and "250 ms backoff" in p1["evidence"]

    rep = H.score(work, tmp_path / "small", rule_fns={"brain is fine": lambda r: r["scores"]["v15"]["mean_of_families"] >= 0.0})
    s = rep["scores"]
    assert set(s) == {"v1", "v2", "v13", "v15", "quotes", "factbank_again"} and rep["stale_arms"] == {}
    assert {**s["v1"], "time_ms": None} == {**s["factbank_again"], "time_ms": None}, "the same arm under another name scores the same"
    for m in s.values():
        assert m["missing"] == 0 and set(m["families"]) <= set(B.FAMILIES)
        assert m["mean_of_families"] == round(sum(m["by_family"][f] for f in m["families"]) / len(m["families"]), 3)
    v15 = s["v15"]
    assert v15["by_family"]["prose"] == 1.0 and v15["prose_reach"] == {"2000": 1.0, "6000": 1.0, "24000": 1.0}
    assert v15["routes"]["accuracy"]["prose"] == 1.0 and v15["routes"]["kinds"]["single"].get("fact", 0) == 0
    assert 0 < v15["false_not_found"]["all"] < 1, "the stub says not found to every question about a pull request"
    assert s["quotes"]["routes"]["counts"]["prose"] == {"prose": 1} and s["quotes"]["by_family"]["not_found"] == 0.0
    assert s["v1"]["routes"] is None and s["v1"]["time_ms"]["max"] >= s["v1"]["time_ms"]["median"]
    sm = rep["small"]
    assert sm["same_questions"] and sm["not_reproduced"] == []
    assert set(sm["differences"]) == {"v1", "v2", "v13", "v15", "quotes"}, "the small folder has no factbank_again"
    assert all(d["questions"] == rep["questions"] for d in sm["differences"].values())
    assert rep["rules"] == {"brain is fine": True}
    md = (work / "report.md").read_text()
    assert "| v15 |" in md and "Routes of v15" in md and "Big folder minus the small one" in md and "brain is fine" in md
    assert json.loads((work / "report.json").read_text())["questions"] == rep["questions"]

    H.write_questions(work, 4, MIX)  # a new draw: the old answers are not scored against it
    again = H.score(work, out=tmp_path / "r")
    assert again["scores"] == {} and set(again["stale_arms"]) == set(s) and (tmp_path / "r" / "report.md").exists()


def test_v15_without_the_brain_module_says_so(tmp_path, monkeypatch):
    work = _bench(tmp_path)
    H.write_questions(work, 3, {"fields": 2})
    monkeypatch.setitem(sys.modules, "cie.factbank.brain", None)  # as if the module were not there
    with pytest.raises(SystemExit, match="brain"):
        H.ask(work, "v15", tmp_path / "l.json", tmp_path / "p.json")


def test_the_command_line_runs_each_step(tmp_path, capsys):
    work = _bench(tmp_path)
    H.main(["questions", "--work", str(work), "--seed", "3", "--mix", json.dumps(MIX), "--n", "8"])
    assert len(_jsonl(work / "questions.jsonl")) <= 8
    H.main(["build", "--work", str(work)])
    assert (work / "factbank_v2.sqlite").exists() and not (work / "factbank.sqlite").exists()
    H.main(["ask", "--work", str(work), "--arm", "quotes"])
    out = H.main(["score", "--work", str(work)])
    assert set(out) == {"quotes"} and "mean_of_families" in out["quotes"]


def test_the_preregistered_rules_read_the_report():
    def arm(single, multi, prose, nf, false_nf=0.0, routes=1.0):
        fam = {"single": single, "multi": multi, "prose": prose, "not_found": nf}
        return {"by_family": fam, "mean_of_families": sum(fam.values()) / 4, "false_not_found": {"all": false_nf},
                "routes": {"accuracy_mean_over_families": routes}}
    rep = {"scores": {"v1": arm(0.80, 0.05, 0.0, 0.25), "v13": arm(0.25, 0.94, 0.0, 0.0), "quotes": arm(0.1, 0.05, 0.65, 0.0),
                      "v15": arm(0.78, 0.92, 0.61, 0.85, 0.02, 0.95), "v15_seed1": arm(0.78, 0.92, 0.61, 0.85)},
           "small": {"differences": {"v15": {"mean_of_families": {"big_minus_small": -0.04}}}}}
    got = H.rules(rep, H.preregistered())
    assert all(got.values()), got
    rep["scores"]["v15"]["by_family"]["single"] = 0.76
    rep["scores"]["v15"]["false_not_found"]["all"] = 0.04
    got = H.rules(rep, H.preregistered())
    assert not got["1 single-document questions: v15 >= v1 - 0.03"]
    assert not got["4 not found: v15 >= 0.80 on questions about nothing in the bank, and false 'not found' <= 0.03 on the others"]
    assert got["2 multi-document questions: v15 >= v13 - 0.03"] and got["3 free text: v15 >= plain search with quotes - 0.05"]
    del rep["small"]
    assert H.rules(rep, H.preregistered())["6 it holds at size: v15 at 5,000 documents >= the small set - 0.05 (mean over families)"] is None
