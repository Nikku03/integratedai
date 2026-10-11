"""The company brain v16's test harness: the three-part draw and what it sets aside, the small control folder and what does not
reproduce there, every arm's answers (the brain stubbed) with the lessons' hashes, the hash seed and the quoted documents,
and the scores over eight families with the rules."""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

from cie.eval import brain2_questions as Q2
from cie.eval import brain2_test as T
from cie.eval import brain_questions as B
from cie.eval import brain_test as H
from cie.eval.memory_test import _jsonl, _write_jsonl

DOCS = {
    "linear/ENG-11.json": {"key": "ENG-11", "title": "Gateway timeout retries for streaming", "assignee": "Omar Singh", "creator": "Ava Lee",
                           "status": "In Progress", "priority": "P1", "project": "gateway-hardening", "due_date": "2026-03-20",
                           "team": "Platform", "created_at": "2026-01-02", "updated_at": "2026-02-01",
                           "description": "Retry the gateway on timeouts. The retry budget is three attempts with a 250 ms backoff."},
    "linear/ENG-12.json": {"key": "ENG-12", "title": "Keycard reader firmware update", "assignee": "Omar Singh", "creator": "Ava Lee",
                           "status": "Todo", "priority": "P2", "project": "gateway-hardening", "due_date": "2026-04-02", "team": "Platform",
                           "parent_issue": "ENG-11", "dependencies": ["ENG-13"], "created_at": "2026-01-05", "updated_at": "2026-02-03"},
    "linear/ENG-13.json": {"key": "ENG-13", "title": "Rate limiter for the billing API", "assignee": "Liam Chen", "creator": "Maya Chen",
                           "status": "Done", "priority": "P1", "project": "billing", "due_date": "2026-05-01", "team": "Billing"},
    "linear/ENG-14.json": {"key": "ENG-14", "title": "Billing export to the warehouse", "assignee": "Liam Chen", "creator": "Maya Chen",
                           "status": "Todo", "priority": "P3", "project": "billing", "due_date": "2026-05-09", "team": "Billing"},
    "linear/ENG-15.json": {"key": "ENG-15", "title": "Webhook signature checks", "assignee": "Maya Chen", "creator": "Liam Chen",
                           "status": "In Review", "priority": "P2", "project": "security", "due_date": "2026-06-01", "team": "Security"},
    "jira/SUP-41.json": {"key": "SUP-41", "title": "Customer sees 5xx on upload", "assignee": "Priya Desai", "reporter": "Jordan Patel",
                         "status": "Open", "priority": "High", "customer_company": "Kitebridge", "sla_due_at": "2026-03-14",
                         "created_at": "2026-03-01"},
    "jira/SUP-42.json": {"key": "SUP-42", "title": "Export job stalls overnight", "assignee": "Priya Desai", "reporter": "Jordan Patel",
                         "status": "Resolved", "priority": "Low", "customer_company": "Kitebridge", "sla_due_at": "2026-03-18",
                         "created_at": "2026-03-02"},
    "jira/SUP-43.json": {"key": "SUP-43", "title": "Invoice totals off by a cent", "assignee": "Noah Kim", "reporter": "Dana Fox",
                         "status": "Open", "priority": "High", "customer_company": "Lumen Retail", "sla_due_at": "2026-03-20",
                         "created_at": "2026-03-03"},
    "jira/SUP-44.json": {"key": "SUP-44", "title": "Password reset email delayed", "assignee": "Noah Kim", "reporter": "Dana Fox",
                         "status": "Resolved", "priority": "Low", "customer_company": "Lumen Retail", "created_at": "2026-03-04"},
    "github/pr-4821.json": {"pr_number": 4821, "title": "Add gateway retry with backoff", "author": "Maya Chen", "repo": "gateway",
                            "state": "merged", "created_at": "2026-02-16", "merged_at": "2026-02-20", "reviewers": ["Liam Chen", "Ava Lee"],
                            "linked_linear": ["ENG-11"]},
    "fireflies/sync.json": {"title": "Weekly gateway sync with Kitebridge", "recorded_at": "2026-02-10", "redwood_owner": "Ava Lee",
                            "customer_company": "Kitebridge", "redwood_attendees": ["Ava Lee", "Omar Singh"], "customer_attendees": ["Dana Fox"],
                            "action_items": ["Omar Singh - ship the keycard reader firmware update - Due: 2026-03-01"]},
    "hubspot/northwind.json": {"title": "Northwind Health", "owner": "Ava Lee", "stage": "negotiation", "csm_assigned": "Dana Fox",
                               "created_at": "2025-11-02", "updated_at": "2026-01-10"},
    "hubspot/fjord.json": {"title": "Fjord Bank", "owner": "Ava Lee", "stage": "negotiation", "csm_assigned": "Omar Singh",
                           "created_at": "2025-10-02", "updated_at": "2026-01-12"},
    "hubspot/helios.json": {"title": "Helios Labs", "owner": "Liam Chen", "stage": "closed won", "csm_assigned": "",
                            "created_at": "2025-09-02", "updated_at": "2026-01-14"},
    "google_drive/runway.json": {"title": "Runway model for Q3 planning", "owner": "Maya Chen", "status": "in_review", "created_at": "2026-01-05"},
    "confluence/oncall.json": {"title": "On-call handbook for the gateway", "author": "Liam Chen", "space": "ENG", "last_updated": "2026-01-20",
                               "body": "Escalate gateway incidents to the platform lead within 15 minutes. Pages go to the gateway rotation first."},
}
PROSE = [{"question_id": "p1", "question": "How many retry attempts does the gateway make on timeouts?", "expected_doc_ids": ["d0"],
          "answer_facts": ["three attempts", "250 ms backoff"]},
         {"question_id": "p2", "question": "What does the deleted page say?", "expected_doc_ids": ["d99"], "answer_facts": ["nothing here"]}]
HELD = [{"id": "heldout-9-001", "question": "What discount did Orbit Freight negotiate for the renewal?", "expected": {"not_found": True},
         "gold_docs": [], "heldout_doc": "x1", "answer_facts": ["12% discount"]},
        {"id": "heldout-9-002", "question": "What is the retry budget of the gateway?", "expected": {"not_found": True}, "gold_docs": [],
         "heldout_doc": "d0"},
        {"id": "heldout-9-003", "question": "Who owns the Orbit Freight renewal?", "expected": {"value": "Ava Lee"}, "gold_docs": [],
         "heldout_doc": "x2"},
        {"id": "heldout-9-004", "question": "When does the Orbit Freight pilot end?", "expected": {"not_found": True}, "gold_docs": ["x3"],
         "heldout_doc": "x3"},
        {"id": "heldout-9-005", "question": "What discount did Orbit Freight negotiate for the renewal?", "expected": {"not_found": True},
         "gold_docs": [], "heldout_doc": "x4"},
        {"id": "7", "question": "Which carrier does the Orbit Freight pilot use?", "expected": {"not_found": True}, "gold_docs": []},
        {"id": "8", "question": "How long is the Orbit Freight onboarding?", "expected": {"not_found": True}, "gold_docs": [], "heldout_doc": "x5"}]
MIX15 = {"fields": 4, "names": 1, "link": 1, "not_found": 2, "prose": 2}
MIX16 = {"counts": 3, "history": 3, "pr_issue_project": 1, "author_issues": 1, "owner_accounts": 1, "field_absent": 2, "embedded": 2}


def _bench(tmp_path: Path) -> Path:
    """A tiny benchmark folder in the raw export format, a work folder over all of its documents, and the writers' files."""
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
    _write_jsonl(tmp_path / "heldout.jsonl", HELD)
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
    """``cie.factbank.brain.ask_brain`` as it writes its rows. v15 quotes the gateway's retry budget from two documents (the
    reason names both); v16 answers counts by its table route ("2"), declines the empty-field questions by its absent route,
    quotes free text from one document (d0) and reads any other question by its plan route ("Omar Singh")."""

    def ask_brain(work, single, plans, name=None, router=None, budget=24_000, field_check=True, v16=False):
        name = name or ("factbank_v16" if v16 else "factbank_v15")
        calls.append({"single": single, "plans": plans, "name": name, "router": router, "v16": v16})
        rows = []
        for q in _jsonl(Path(work) / "questions.jsonl"):
            quote = 'Gateway timeout retries: "The retry budget is three attempts with a 250 ms backoff." [1].'
            if not v16:
                row = {"answer": quote, "route": "prose", "reason": "quoted from 2 passage(s) of 2 document(s): doc:d0, doc:d5"}
            elif Q2.family(q) == "prose":
                row = {"answer": quote, "route": "prose", "reason": "quoted from 1 passage(s) of doc:d0; it holds 0.900 of the question's words"}
            elif q["question"].startswith(("How many", "Count", "Can you count", "What is the number")):
                row = {"answer": "2", "route": "table", "reason": "counted"}
            elif q.get("kind") == "field_absent":
                row = {"answer": "not found", "route": "absent", "reason": "the field is empty"}
            else:
                row = {"answer": "Omar Singh", "route": "plan", "reason": "read"}
            rows.append({"id": q["id"], **row, "evidence": "The retry budget is three attempts with a 250 ms backoff.", "ms": 1.5,
                         "reads": [], "journal": [], "family_scores": {}})
        _write_jsonl(Path(work) / f"{name}.jsonl", rows)
        return {"questions": len(rows)}

    stub = types.ModuleType("cie.factbank.brain")
    stub.ask_brain = ask_brain
    monkeypatch.setitem(sys.modules, "cie.factbank.brain", stub)


# ------------------------------------------------------------------ the mixes and the routes
def test_the_new_kinds_mix_spreads_over_the_new_families_and_names_none_of_v15s_kinds():
    fam = lambda key: {Q2.CATALOGUE[k].family for k in Q2.resolve(key)}  # noqa: E731
    per: dict[str, int] = {}
    for key, n in T.MIX16.items():
        (f,) = fam(key)
        per[f] = per.get(f, 0) + n
        assert Q2.resolve(key) <= set(Q2.CATALOGUE), key
    assert per == {"counts": 40, "history": 40, "email_chat": 40, "multi": 20, "unanswerable": 20, "single": 20}
    assert {k for k in T.MIX16 if fam(k) == {"multi"}} == {k for k, v in Q2.CATALOGUE.items() if v.family == "multi"}
    assert T.MIX15 == {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20,
                       "prose": 50, "descriptive": 40}, "v15's test mix, descriptive questions up to 40"
    T.check_mix16(T.MIX16)
    for bad in ({"multi": 5}, {"link": 2}, {"fields": 3}):
        with pytest.raises(ValueError, match="mix15"):
            T.check_mix16(bad)
    assert T.FAMILIES2[:4] == B.FAMILIES and len(set(T.FAMILIES2)) == 8


def test_routes_are_read_as_fact_prose_or_not_found():
    got = [T.route_class(r) for r in ("plan", "fact", "table", "derived", "prose", "not_found", "not found", "absent", "absent:field", None)]
    assert got == ["fact", "fact", "fact", "fact", "prose", "not_found", "not_found", "not_found", "not_found", None]
    assert set(T.ROUTE2) == set(T.FAMILIES2) - {"unanswerable"} and T.ANSWERABLE == ("single", "multi", "prose", "counts", "history", "email_chat")


# ------------------------------------------------------------------ questions
def test_the_draw_is_v15s_draw_then_the_new_kinds_then_the_held_out_questions(tmp_path):
    work = _bench(tmp_path)
    docs = H.load_docs(work)
    prose = B.load_prose(tmp_path / "prose.jsonl")
    held = T.load_heldout(tmp_path / "heldout.jsonl")
    assert [q["id"] for q in held][-2:] == ["heldout-7", "heldout-8"], "an id that is not a held-out one is made one"
    assert all(q["family"] == "unanswerable" and q["kind"] == q["group"] == "heldout" for q in held)
    qs, aside, rep = T.draw2(docs, 3, MIX15, MIX16, prose, None, held)
    q15, a15, r15 = H.draw(docs, 3, MIX15, prose)
    n15, n16 = len(q15), rep["by_part"]["v16"]
    assert qs[:n15] == q15, "v15's part is brain_test.draw's, unchanged"
    asked15 = Q2.Asked(q15)
    assert qs[n15:n15 + n16] == Q2.draw_questions(docs, 3, MIX16, avoid=q15), \
        "the new kinds are brain2_questions.draw_questions', none re-asking a question of v15's part"
    assert not any(asked15(q) for q in qs[n15:n15 + n16])
    assert [q["id"] for q in qs[n15 + n16:]] == ["heldout-9-001", "heldout-8"]
    assert len({q["id"] for q in qs}) == len(qs) == rep["questions"] and sum(rep["by_family"].values()) == len(qs)
    assert {q["kind"] for q in qs[n15:n15 + n16]} >= {"count1_jira", "pr_issue_project", "author_issues", "owner_accounts", "field_absent"}
    assert rep["mix16"] == {"asked": MIX16, "given": MIX16}, "the tiny bench has every kind asked for"
    assert rep["mix15"]["asked"] == MIX15 and rep["mix15"]["given"] == r15["mix_given"] and rep["v15"] == r15
    gen = Q2.generate(docs, 3, kinds=set().union(*map(Q2.resolve, MIX16)))[1]
    assert rep["v16"]["available"] == gen["by_kind"] and rep["v16"]["set_aside"] == gen["aside"] and gen["by_kind"]["count1_jira"] == 2
    assert rep["heldout"] == {"read": 7, "kept": 2, "set_aside": {"asked twice": 1, "expects an answer": 1, "has gold documents": 1,
                                                                   "held-out document in the haystack": 1, "no held-out document": 1}}
    assert aside[:len(a15)] == a15 and {q["id"]: q["unclear"] for q in aside[len(a15):] if T.part(q) == "heldout"} == {
        "heldout-9-002": "held-out document in the haystack", "heldout-9-003": "expects an answer", "heldout-9-004": "has gold documents",
        "heldout-9-005": "asked twice", "heldout-7": "no held-out document"}
    rows16 = [q for q in aside[len(a15):] if T.part(q) == "v16"]
    reask = [q for q in rows16 if q["unclear"].startswith(T.REASK)]
    by_id15 = {q["id"]: q for q in q15}
    assert reask and all(q["unclear"] == f"re-asks {asked15(q)}: the same field of the same document, the same answer" for q in reask)
    assert {(q["kind"], by_id15[asked15(q)]["kind"]) for q in reask} == {
        ("embedded_hubspot_stage", "hubspot_stage"), ("embedded_linear_issue_priority", "linear_issue_priority"),
        ("embedded_pr_author", "pr_author"), ("embedded_pr_repo", "pr_repo"), ("embedded_linear_issue_status", "pr_issue")}, \
        "the embedded wordings of v15's field questions, and the status of the issue a v15 link question asks through a pull request"
    assert rep["v16"]["reasked"] == {q["kind"]: 1 for q in reask} and all(q["unclear"] and q.get("expected") for q in rows16)
    gen_rows: list = []
    Q2.generate(docs, 3, kinds=set().union(*map(Q2.resolve, MIX16)), aside_rows=gen_rows)
    assert [q for q in rows16 if q not in reask] == gen_rows, "the new kinds' set-aside questions with their reasons"
    assert rep["by_part"] == {"heldout": 2, "v15": n15, "v16": n16} and rep["set_aside_written"]["heldout"] == 5
    with pytest.raises(ValueError, match="twice"):
        T.draw2(docs, 3, MIX15, MIX16, prose, None, [{**held[0], "id": q15[0]["id"]}])
    with pytest.raises(ValueError, match="mix15"):
        T.draw2(docs, 3, MIX15, {"multi": 2})


def test_questions_write_the_set_and_the_small_control_where_every_answer_reproduces(tmp_path):
    work, small = _bench(tmp_path), tmp_path / "small"
    rep = T.write_questions(work, 3, MIX15, MIX16, prose=tmp_path / "prose.jsonl", heldout=tmp_path / "heldout.jsonl", small=small)
    qs = _jsonl(work / "questions.jsonl")
    assert len(qs) == rep["questions"] and json.loads((work / H.REPORT).read_text())["by_part"] == rep["by_part"]
    sha = {"prose": H._sha(tmp_path / "prose.jsonl"), "descriptive": None, "heldout": H._sha(tmp_path / "heldout.jsonl"), "wordings": None}
    assert rep["inputs_sha256"] == sha and json.loads((work / H.REPORT).read_text())["inputs_sha256"] == sha
    assert any(q["unclear"].startswith(T.REASK) for q in _jsonl(work / "set_aside_questions.jsonl") if T.part(q) == "v16")
    assert {q["id"]: q["unclear"] for q in _jsonl(work / "set_aside_questions.jsonl") if q.get("origin") == "heldout"}["heldout-7"] \
        == "no held-out document"
    gold = sorted({x for q in qs for x in q["gold_docs"]})
    assert json.loads((small / "haystack.json").read_text())["dsids"] == gold and _jsonl(small / "questions.jsonl") == qs
    assert len(gold) < len(DOCS) and rep["small"]["not_reproduced"] == {}, "every expected answer rests on the gold documents"
    assert json.loads((small / H.REPORT).read_text())["not_reproduced"] == {}
    with pytest.raises(ValueError):
        T.write_questions(work, 3, MIX15, MIX16, small=work)


def test_new_answers_that_do_not_reproduce_in_the_small_set_are_found(tmp_path):
    work = _bench(tmp_path)
    docs = H.load_docs(work)
    qs = Q2.generate(docs, 3, kinds={"count1_jira", "created_on", "owner_accounts", "field_absent", "filter_list"})[0]
    one = lambda kind, **kw: next(q for q in qs if q["kind"] == kind and all(q.get(k) == v for k, v in kw.items()))  # noqa: E731
    count, made, owner, absent = one("count1_jira"), one("created_on", gold_docs=["d5"]), one("owner_accounts"), one("field_absent")
    small = {x for q in qs for x in q["gold_docs"]}
    assert T.not_reproduced2(docs, small, qs, 3) == {}
    wrong = [{**count, "id": "c", "expected": {"value": "3"}}, {**made, "id": "m", "expected": {"date": "2020-01-01"}},
             {**count, "id": "r", "pieces": ["some other name", *count["pieces"][1:]]},
             {**count, "id": "r3", "pieces": ["some other name"], "expected": {"value": "3"}},
             {**owner, "id": "o", "field": "name", "expected": {"value": "Fjord Bank"}},
             {**absent, "id": "a", "gold_docs": ["d0"]}, {"id": "h", "kind": "heldout", "family": "unanswerable", "gold_docs": []},
             {**made, "id": "n", "pieces": ["ENG-99"]}]
    got = T.not_reproduced2(docs, small - {"d0"}, wrong, 3)
    assert got == {"c": "differs", "m": "differs", "r3": "differs", "o": "differs", "a": "gold document outside the set", "n": "not asked"}, \
        "a count drawn under another name is counted again (r), and a held-out question always reproduces (h)"
    keys = one("filter_list", gold_docs=["d5", "d7"])
    assert T._recount({**keys, "expected": {"ids": ["SUP-41", "SUP-43"], "id_kind": "key"}}, docs, {d["dsid"]: d for d in docs})
    assert T._recount({**keys, "expected": {"ids": ["SUP-41"], "id_kind": "key"}}, docs, {d["dsid"]: d for d in docs}) is False
    assert T._recount(made, docs, {}) is None
    assert T._owner_accounts_again({**owner, "field": "count", "expected": {"value": "2"}}, docs)


# ------------------------------------------------------------------ scoring pieces
def test_held_out_questions_score_a_not_found_and_the_new_kinds_their_own_scorer():
    held = {"id": "h", "kind": "heldout", "family": "unanswerable", "expected": {"not_found": True}, "question": "?", "gold_docs": []}
    assert T.score_one(held, "Not found: nothing in the documents") == 1.0 and T.score_one(held, "It is 12%.") == 0.0
    assert T.score_one(held, {"answer": "12%", "route": "not_found"}) == 1.0
    count = {"id": "c", "kind": "count1_jira", "expected": {"value": "2"}, "question": "How many?"}
    assert T.score_one(count, "2 tickets: SUP-41 and SUP-43") == 1.0 and T.score_one(count, "SUP-41") == 0.0
    absent = {"id": "a", "kind": "field_absent", "expected": {"not_found": True}}
    assert T.score_one(absent, {"answer": "not found", "route": "absent"}) == 1.0
    field = {"id": "f", "kind": "jira_priority", "family": "single", "expected": {"value": "High"}}
    assert T.score_one(field, "High") == B.score(field, "High") == 1.0


def test_the_documents_of_a_quoted_answer_and_the_strict_free_text_score():
    q = {"id": "p", "kind": "prose", "family": "prose", "expected": {"facts": ["three attempts", "250 ms backoff"]}, "gold_docs": ["d0"]}
    two = 'Retries: "The retry budget is three attempts." [1]. Billing: "It waits a 250 ms backoff." [2].'
    assert T.quoted_parts(two) == ['Retries: "The retry budget is three attempts."', '. Billing: "It waits a 250 ms backoff."']
    assert T.quoted_parts('A: "see note [2] here" [1].') == ['A: "see note [2] here"'], "a marker out of turn is text"
    assert T.provenance({"quote_docs": ["d0", "d5"]}) == (["d0", "d5"], True)
    assert T.provenance({"reason": "quoted from 2 passage(s) of doc:d0; it holds 0.6"}) == (["d0"], False)
    assert T.provenance({"reason": "quoted from 3 passage(s) of 2 document(s): doc:d0, doc:d5"}) is None
    assert T.provenance({"doc": "doc:d5", "reason": "anything"}) == (["d5"], False) and T.provenance({"reason": "read"}) is None
    assert B.score(q, H.plain_answer(two)) == 1.0
    assert T.strict_prose(q, {"answer": two, "quote_docs": ["d0", "d5"]}) == 0.5, "the backoff is quoted from another document"
    assert T.strict_prose(q, {"answer": two, "quote_docs": ["d5", "d0"]}) == 0.5
    assert T.strict_prose(q, {"answer": two, "quote_docs": ["d0", "d0"]}) == 1.0
    assert T.strict_prose(q, {"answer": two, "quote_docs": ["d0"]}) is None, "markers and documents must pair up"
    assert T.strict_prose(q, {"answer": two, "reason": "quoted from 2 passage(s) of doc:d5; ..."}) == 0.0
    assert T.strict_prose(q, {"answer": two, "doc": "doc:d0"}) == 1.0
    assert T.strict_prose(q, {"answer": "not found", "route": "prose"}) == 0.0
    assert T.strict_prose(q, {"answer": two, "reason": "quoted from 2 passage(s) of 2 document(s): doc:d0, doc:d5"}) is None


# ------------------------------------------------------------------ ask and score
def test_every_arm_is_asked_recorded_with_its_lessons_and_hash_seed_and_scored(tmp_path, monkeypatch):
    work, small = _bench(tmp_path), tmp_path / "small"
    T.write_questions(work, 3, MIX15, MIX16, prose=tmp_path / "prose.jsonl", heldout=tmp_path / "heldout.jsonl", small=small)
    single, plans = _lessons(tmp_path)
    calls: list = []
    _brain_stub(monkeypatch, calls)
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    for w in (work, small):
        H.build(w, v1=True)
        T.ask(w, "v1")
        T.ask(w, "v15", single, plans, router="rule")
        T.ask(w, "v16", single, plans, router=str(single))
        T.ask(w, "quotes")
    monkeypatch.setenv("PYTHONHASHSEED", "1")
    T.ask(work, "v16", single, plans, name="v16_seed1")
    T.ask(work, "v16", single, plans, router=str(single), name="v16b")  # v16 again under another name: still v16's own answers
    assert [(c["name"], c["v16"]) for c in calls[:3]] == [("factbank_v15", False), ("factbank_v16", True), ("factbank_v15", False)]
    reg = H.registry(work)
    assert reg["factbank_v16"]["label"] == "v16" and reg["factbank_v16"]["arm"] == "v16" and reg["v16_seed1"]["label"] == "v16_seed1"
    assert reg["factbank_v16"]["single_sha256"] == H._sha(single) == reg["factbank_v15"]["single_sha256"]
    assert reg["factbank_v16"]["plans_sha256"] == H._sha(plans) and reg["factbank_v16"]["router_sha256"] == H._sha(single)
    assert reg["factbank_v15"]["router_sha256"] is None, "a router named, not given as a file"
    assert reg["factbank"]["single_sha256"] is None and reg["quotes"]["plans_sha256"] is None
    assert reg["factbank_v16"]["pythonhashseed"] == "0" and reg["v16_seed1"]["pythonhashseed"] == "1"
    quotes = _jsonl(work / "quotes.jsonl")
    H.ask(work, "quotes", name="plain_quotes")
    plain = _jsonl(work / "plain_quotes.jsonl")
    assert [r["answer"] for r in quotes] == [r["answer"] for r in plain], "recording the quoted documents changes no answer"
    assert all(len(r["quote_docs"]) == len(T.quoted_parts(r["answer"])) for r in quotes)
    p1 = next(r for r in quotes if r["id"] == "p1")
    assert p1["quote_docs"][0] == "d0" and set(p1["quote_docs"]) <= set(p1["cited"])
    (work / "plain_quotes.jsonl").unlink()  # left out as stale

    rep = T.score(work, small, rule_fns=T.preregistered2())
    s = rep["scores"]
    assert set(s) == {"v1", "v15", "v16", "v16_seed1", "v16b", "quotes"} and rep["stale_arms"] == {"plain_quotes": "answers file missing"}
    assert rep["own"] == ["v16", "v16_seed1", "v16b"] and rep["arms"]["v16b"]["arm"] == "v16"
    for m in s.values():
        assert set(m["by_family"]) == set(T.FAMILIES2) and m["missing"] == 0
        assert m["mean_of_families"] == H._mean(m["by_family"][f] for f in T.FAMILIES2)
        assert m["mean_of_v15_families"] == H._mean(m["by_family"][f] for f in B.FAMILIES)
    v16 = s["v16"]
    assert v16["by_family"]["prose"] == 1.0 and v16["by_family"]["unanswerable"] == 0.5, \
        "the absent route declines the empty fields, the plan route answers the held-out questions"
    assert v16["by_kind"]["field_absent"] == {"mean": 1.0, "n": 2} and v16["by_kind"]["heldout"] == {"mean": 0.0, "n": 2}
    r = v16["routes"]
    assert r["kinds"]["counts"] == {"fact": 3} and r["accuracy"]["prose"] == 1.0 and r["accuracy"]["not_found"] == 0.0
    assert "unanswerable" not in r["accuracy"] and r["kinds"]["unanswerable"] == {"fact": 2, "not_found": 2}
    assert v16["false_not_found"]["all"] == 0.0 and set(v16["false_not_found"]) == {*T.ANSWERABLE, "all"}
    assert v16["strict_prose"] == {"mean": 1.0, "questions": 1, "quoted": 1, "documents_unknown": 0}
    assert s["v15"]["strict_prose"]["mean"] is None and s["v15"]["strict_prose"]["documents_unknown"] == 1, "two documents named"
    assert s["v1"]["strict_prose"]["mean"] is None and s["v1"]["strict_prose"]["quoted"] == 0 and s["v1"]["routes"] is None
    assert s["quotes"]["strict_prose"]["mean"] is not None and s["quotes"]["strict_prose"]["quoted"] == 1
    assert rep["best_other"]["prose"]["arm"] in ("v15", "quotes") and not {b["arm"] for b in rep["best_other"].values()} & set(rep["own"])
    assert set(rep["paired"]) == set(T.FAMILIES2) - {"email_chat"} and rep["paired"]["counts"]["other"] == rep["best_other"]["counts"]["arm"]
    assert not {p["other"] for p in rep["paired"].values()} & set(rep["own"]), "v16 is never paired with its own answers"
    assert rep["seed_check"] == {"questions": rep["questions"], "different": []}
    sm = rep["small"]
    assert sm["same_questions"] and set(sm["differences"]) == {"v1", "v15", "v16", "quotes"}
    assert sm["differences"]["v16"]["big_minus_small"]["single"] == 0.0
    rules = rep["rules"]
    assert len(rules) == 12 and all(v in (True, False, None) for v in rules.values())
    assert rules[next(k for k in rules if k.startswith("12 "))] is True and rules[next(k for k in rules if k.startswith("3 "))] is True
    assert rules[next(k for k in rules if k.startswith("4 "))] is False, "the stub's plan route answers questions about nothing"
    md = (work / "report.md").read_text()
    for part in ("| v16 |", "Routes of v16", "v16 minus the best other arm", "Big folder minus the small one", "By kind:", "strict prose",
                 "own answers, never another arm"):
        assert part in md, part
    assert json.loads((work / "report.json").read_text())["questions"] == rep["questions"]


def test_the_lessons_hashes_and_the_hash_seed_are_taken_when_the_arm_starts(tmp_path, monkeypatch):
    work = _bench(tmp_path)
    T.write_questions(work, 3, {"fields": 2}, {"counts": 1})
    H.build(work)
    single, plans = _lessons(tmp_path)
    calls: list = []
    _brain_stub(monkeypatch, calls)
    stub = sys.modules["cie.factbank.brain"]
    real = stub.ask_brain

    def changing(work, single, plans, **kw):  # the lessons and the hash seed change while the arm runs
        Path(single).write_text(Path(single).read_text() + " ")
        os.environ["PYTHONHASHSEED"] = "9"
        return real(work, single, plans, **kw)

    stub.ask_brain = changing
    for arm in ("v16", "v15"):
        monkeypatch.setenv("PYTHONHASHSEED", "0")
        before = H._sha(single), H._sha(plans)
        rec = T.ask(work, arm, single, plans, router=str(plans))
        reg = H.registry(work)[T.FILES2[arm]]
        assert (reg["single_sha256"], reg["plans_sha256"], reg["router_sha256"]) == (*before, before[1]), arm
        assert reg["pythonhashseed"] == rec["pythonhashseed"] == "0" and os.environ["PYTHONHASHSEED"] == "9", arm
        assert H._sha(single) != before[0], "the file changed after the arm started"
    assert [c["v16"] for c in calls] == [True, False]


def test_v15s_part_takes_at_most_40_descriptive_questions(tmp_path):
    work = _bench(tmp_path)
    docs = H.load_docs(work)
    rows = [{"id": f"desc-9-{i:03d}", "group": "descriptive", "kind": "descriptive", "family": "single", "field": "owner",
             "question": "Who owns the planning sheet for the next quarter's runway?", "expected": {"value": "Maya Chen"},
             "gold_docs": ["d14"], "pieces": ["Runway model for Q3 planning", "Maya Chen"]} for i in range(45)]
    _write_jsonl(tmp_path / "descriptive.jsonl", rows)
    desc = H.load_descriptive(tmp_path / "descriptive.jsonl")
    qs, _, rep = T.draw2(docs, 3, None, {"counts": 1}, None, desc)
    assert sum(q["kind"] == "descriptive" for q in qs) == 40 == rep["mix15"]["given"]["descriptive"] == rep["mix15"]["asked"]["descriptive"]
    qs, _, rep = T.draw2(docs, 3, None, {"counts": 1}, None, desc[:12])
    assert sum(q["kind"] == "descriptive" for q in qs) == 12, "all of them when fewer pass"


def test_a_name_cannot_take_another_arms_file_or_label_and_v16_checks_what_it_reads(tmp_path, monkeypatch):
    work = _bench(tmp_path)
    T.write_questions(work, 3, {"fields": 2}, {"counts": 1})
    single, plans = _lessons(tmp_path)
    calls: list = []
    _brain_stub(monkeypatch, calls)
    for arm, name, why in (("v15", "factbank_v16", "arm v16's answers file"), ("v16", "factbank_v15", "arm v15's answers file"),
                           ("quotes", "v16", "arm v16's label"), ("v15", "v16_seed1", "v16 brain's answers"),
                           ("v16", "v15", "arm v15's label"), ("v16", "questions", "cannot name"), ("v16", "../x", "cannot name")):
        with pytest.raises(ValueError, match=why):
            T.ask(work, arm, single, plans, name=name)
    with pytest.raises(ValueError, match="single"):
        T.ask(work, "v16")
    with pytest.raises(ValueError, match="plan"):
        T.ask(work, "v16", single)
    with pytest.raises(ValueError, match="no record"):
        T.ask(work, "v16", single, plans)
    with pytest.raises(ValueError, match="unknown arm"):
        T.ask(work, "v17")
    H.build(work)
    T.ask(work, "quotes", name="mine")
    with pytest.raises(ValueError, match="holds arm quotes's answers"):
        T.ask(work, "v16", single, plans, name="mine")
    monkeypatch.setitem(sys.modules, "cie.factbank.brain", None)  # as if the module were not there
    with pytest.raises(SystemExit, match="brain"):
        T.ask(work, "v16", single, plans)
    assert calls == [] and set(H.registry(work)) == {"mine"}


def test_the_rules_read_the_report():
    def arm(single=0.8, multi=0.9, prose=0.7, nf=0.9, counts=0.8, history=0.8, email=0.8, unans=0.7, false_nf=0.02, routes=0.95):
        fam = {"single": single, "multi": multi, "prose": prose, "not_found": nf, "counts": counts, "history": history, "email_chat": email,
               "unanswerable": unans}
        return {"by_family": fam, "mean_of_families": sum(fam.values()) / 8, "false_not_found": {"all": false_nf},
                "routes": {"accuracy_mean_over_families": routes}}
    rep = {"scores": {"v16": arm(), "v16_seed1": arm(single=0.0), "v1": arm(0.82, 0.05, 0.0, 0.25, 0.1, 0.1, 0.1, 0.1),
                      "v13": arm(0.3, 0.92, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0), "quotes": arm(0.1, 0.05, 0.74, 0.0, 0.3, 0.2, 0.3, 0.0)},
           "small": {"differences": {"v16": {"big_minus_small": {"single": -0.05, "multi": 0.0, "prose": -0.01, "not_found": 0.3}}}}}
    fns = T.preregistered2()
    assert len(fns) == 12 and all(str(T.SINGLE_MARGIN) in k for k in fns if k.startswith("1 "))
    got = H.rules(rep, fns)
    assert all(got.values()), got
    rep["scores"]["v16"]["by_family"]["counts"] = 0.35  # >= 0.60 fails though above the best other arm + 0.10
    rep["scores"]["v16"]["by_family"]["prose"] = 0.68  # quotes 0.74: below by more than 0.05
    rep["scores"]["v16"]["false_not_found"]["all"] = 0.06
    rep["small"]["differences"]["v16"]["big_minus_small"]["prose"] = -0.06
    got = H.rules(rep, fns)
    failed = sorted(k.split()[0] for k, v in got.items() if v is False)
    assert failed == ["12", "3", "6", "7"], got
    rep["small"]["differences"]["v16"]["big_minus_small"] |= {"single": -0.06, "multi": 0.06, "prose": 0.0}
    got = {k.split()[0]: v for k, v in H.rules(rep, fns).items()}
    assert got["12"] is False, "the size rule holds for each of single, multi and prose, not for their mean (0.0 here)"
    assert T.SIZE_FAMILIES2 == ("single", "multi", "prose") and "for each of single, multi and free text" in next(k for k in fns if k.startswith("12 "))
    assert "for each of single, multi and prose" in T.preregistered2.__doc__
    del rep["small"]
    rep["scores"] = {"v16": rep["scores"]["v16"]}
    why: dict = {}
    got = H.rules(rep, fns, why)
    assert got[next(k for k in got if k.startswith("12 "))] is None and got[next(k for k in got if k.startswith("1 "))] is None
    assert got[next(k for k in got if k.startswith("4 "))] is True, "a rule with no other arm in it still reads v16"
    assert why[next(k for k in got if k.startswith("10 "))].startswith("ValueError"), "no other arm's mean to beat"


def test_no_label_asked_as_v16_is_another_arm():
    def arm(counts, mean):
        fam = {f: 0.9 for f in T.FAMILIES2} | {"counts": counts}
        return {"by_family": fam, "mean_of_families": mean, "false_not_found": {"all": 0.0}, "routes": {"accuracy_mean_over_families": 0.95}}
    rep = {"scores": {"v16": arm(0.70, 0.70), "v16b": arm(0.72, 0.71), "v15": arm(0.15, 0.50)},
           "arms": {"v16": {"arm": "v16"}, "v16b": {"arm": "v16"}, "v15": {"arm": "v15"}}}
    assert T.own_labels(rep["arms"]) == ["v16", "v16_seed1", "v16b"] and T.own_labels(None) == sorted(T.OWN)
    assert T.best_other(rep["scores"], "counts", T.own_labels(rep["arms"])) == ("v15", 0.15)
    assert T.best_other(rep["scores"], "counts") == ("v16b", 0.72), "with no records, only OWN is left out"
    rows = [{"family": "counts", "score": {"v16": 1.0, "v16b": 1.0, "v15": 0.0}}]
    assert T.paired2(rows, rep["scores"], own=T.own_labels(rep["arms"]))["counts"]["other"] == "v15"
    got = {k.split()[0]: v for k, v in H.rules(rep, T.preregistered2()).items()}
    assert got["7"] is True and got["10"] is True, "v16 is not measured against itself asked under another name"
    rep["arms"]["v16b"]["arm"] = "v15"  # the same label asked as another arm is another arm
    got = {k.split()[0]: v for k, v in H.rules(rep, T.preregistered2()).items()}
    assert got["7"] is False and got["10"] is False


def test_the_command_line_runs_each_step(tmp_path):
    work = _bench(tmp_path)
    out = T.main(["questions", "--work", str(work), "--seed", "3", "--mix15", json.dumps({"fields": 2, "not_found": 1}), "--mix16",
                  json.dumps({"counts": 2, "field_absent": 1}), "--heldout", str(tmp_path / "heldout.jsonl")])
    assert out["by_part"] == {"heldout": 2, "v15": 3, "v16": 3} and len(_jsonl(work / "questions.jsonl")) == 8
    H.main(["build", "--work", str(work)])
    T.main(["ask", "--work", str(work), "--arm", "quotes"])
    assert all("quote_docs" in r for r in _jsonl(work / "quotes.jsonl"))
    out = T.main(["score", "--work", str(work), "--preregistered"])
    assert set(out) == {"quotes", "rules"} and set(out["quotes"]["by_family"]) == set(T.FAMILIES2)
    assert all(v is None for v in out["rules"].values()), "no v16 answers: every rule lacks what it reads"
