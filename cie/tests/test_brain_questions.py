"""The company brain's questions: the catalogue, the generators and what they set aside, the draw, and the scorer."""

from __future__ import annotations

import json
import random
from collections import Counter

import pytest

from cie.eval import brain_questions as B
from cie.eval import factbank_multi as M
from cie.eval.memory_test import generate_questions


def _d(dsid, source, title, **raw):
    return {"dsid": dsid, "source": source, "title": title, "raw": raw}


def _lin(dsid, key, who, due="2026-03-20", **x):
    return _d(dsid, "linear", f"Issue {key} about the gateway", key=key, assignee=who, due_date=due, status="In Progress", **x)


def _jira(dsid, key, who="Omar Singh", **x):
    return _d(dsid, "jira", f"Ticket {key} about 5xx", key=key, assignee=who, status="Resolved", priority="P2", reporter="Ava Lee", **x)


def _pr(dsid, n, author="Maya Chen", **x):
    return _d(dsid, "github", f"PR {n}: add a smoke test", pr_number=n, author=author, repo="runtime", merged_at="2026-02-20", **x)


def _gen(fn, docs, seed=1, cap=None):
    aside: Counter = Counter()
    return fn(docs, random.Random(seed), cap, aside=aside), aside


def test_the_catalogue_names_every_kind_once_with_a_family_and_a_scorer():
    cat = B.kinds()
    names = [k["name"] for k in cat]
    assert len(names) == len(set(names))
    assert {k["family"] for k in cat} == set(B.FAMILIES)
    assert all(k["group"] and k["scored"] and k["source"] for k in cat)
    assert set(B.MEMORY_KINDS) | set(B.MULTI_KINDS) | set(B.GENERATORS) | {"prose", "metadata"} == set(names)
    assert {k["name"] for k in cat if k["family"] == "multi"} == set(M.GROUP) | {"parent_issue"}
    assert B.family({"kind": "linear_due"}) == "single" and B.family({"kind": "?", "expected": {"not_found": True}}) == "not_found"


def test_field_questions_come_from_the_fields_of_uniquely_named_documents():
    docs = [_d("g1", "google_drive", "Runway model for Q3", owner="Maya Chen (Finance)", status="in_review", created_at="2026-01-05"),
            _d("g2", "google_drive", "Shared title twice", owner="Ava Lee"), _d("s1", "slack", "shared  title TWICE"),
            _d("g3", "google_drive", "Pricing notes for Acme", owner="Maya Chen, Liam Chen"),
            _d("g4", "google_drive", "Hiring plan draft", owner="TBD")]
    qs, aside = _gen(lambda *a, **k: B.field_questions("drive_owner", *a, **k), docs)
    assert [(q["question"].count("Runway model for Q3"), q["expected"], q["gold_docs"], q["pieces"]) for q in qs] == \
        [(1, {"value": "Maya Chen"}, ["g1"], ["Runway model for Q3", "Maya Chen"])]
    assert qs[0]["family"] == "single" and qs[0]["group"] == "fields" and qs[0]["field"] == "owner"
    assert qs[0]["question"] in [w.format(t="Runway model for Q3") for w in B.FIELDS["drive_owner"][3]]
    assert aside == {"named twice": 1, "several values": 1, "no value": 1}, "the title is a Slack title too; two owners; no owner"
    st, _ = _gen(lambda *a, **k: B.field_questions("drive_status", *a, **k), docs[:1])
    assert st[0]["expected"] == {"value": "in_review", "alts": ["in review"]}


def test_keys_numbers_dates_and_months_name_and_answer_field_questions():
    docs = [_jira("j1", "SUP-4127", sla_due_at="2026-03-14"), _jira("j2", "SUP-4128", sla_due_at="2026-02-30"),
            _jira("j3", "SUP-4127"), _lin("l1", "ENG-411", "Liam Chen"), _jira("j4", "SUP-4129", customer_company="Redwood Inference (internal)"),
            _pr("p1", "18544"), _pr("p2", "18545"), _pr("p3", "18545"),
            _d("h1", "hubspot", "Kitebridge Supportware", forecast_close_month="2026-05", owner="Jordan Patel"),
            _d("f1", "fireflies", "Lantana embeddings session", recorded_at="2027-03-25T15:00:00Z"),
            _d("f2", "fireflies", "Evening sync with Prism Labs", recorded_at="2026-03-01T20:00:00-08:00")]
    sla, aside = _gen(lambda *a, **k: B.field_questions("jira_sla", *a, **k), docs)
    assert sla == [] and aside == {"named twice": 2, "impossible date": 1, "no value": 1}, "SUP-4127 is on two documents"
    pri, _ = _gen(lambda *a, **k: B.field_questions("jira_priority", *a, **k), docs)
    assert any("SUP-4128" in q["question"] for q in pri) and all("SUP-4127" not in q["question"] for q in pri)
    cust, aside = _gen(lambda *a, **k: B.field_questions("jira_customer", *a, **k), docs)
    assert aside["internal"] == 1
    prs, aside = _gen(lambda *a, **k: B.field_questions("pr_author", *a, **k), docs)
    assert [q["pieces"] for q in prs] == [["18544", "Maya Chen"]] and aside["named twice"] == 2
    close, _ = _gen(lambda *a, **k: B.field_questions("hubspot_close", *a, **k), docs)
    assert close[0]["expected"] == {"value": "2026-05", "alts": ["May 2026"]}
    when, aside = _gen(lambda *a, **k: B.field_questions("meeting_date", *a, **k), docs)
    assert [q["expected"] for q in when] == [{"date": "2027-03-25"}]
    assert aside == {"several values": 1}, "8 pm on 1 March in California is 2 March in UTC: two readings"
    assert B.score(when[0], "2027-03-25T15:00:00Z") == 1.0, "a timestamp is read as its date"


def test_wordings_are_drawn_from_the_seed():
    docs = [_jira(f"j{i}", f"SUP-{100 + i}") for i in range(12)]
    a, _ = _gen(lambda *x, **k: B.field_questions("jira_status", *x, **k), docs, seed=3)
    b, _ = _gen(lambda *x, **k: B.field_questions("jira_status", *x, **k), docs, seed=3)
    assert a == b
    assert len({q["question"].split(" SUP-")[0] for q in a}) > 1, "more than one wording in use"
    capped, _ = _gen(lambda *x, **k: B.field_questions("jira_status", *x, **k), docs, seed=3, cap=4)
    assert len(capped) == 4 and [q["id"] for q in capped] == [f"jira_status-{i:03d}" for i in range(1, 5)]


def test_name_lists_and_their_scorer():
    docs = [_d("f1", "fireflies", "Lantana embeddings session", redwood_attendees=["Jordan Ellis (AE)", "Priya Nair (SE)"],
               customer_attendees=["Dr. Lina Chen (ML Engineer)", "Marco Ruiz"]),
            _d("f2", "fireflies", "Internal dry run", redwood_attendees=["Jordan Ellis (AE)"], customer_attendees=["Speaker 2 (Ops)"])]
    qs, aside = _gen(lambda *a, **k: B.name_questions("meeting_attendees", *a, **k), docs)
    assert len(qs) == 1 and qs[0]["expected"] == {"names": ["Jordan Ellis", "Priya Nair", "Dr. Lina Chen", "Marco Ruiz"]}
    assert aside == {"not a person": 1}, "a speaker label makes the list inexact"
    q = qs[0]
    assert B.score(q, "Jordan Ellis (AE), Priya Nair, Lina Chen and Marco Ruiz") == 1.0
    assert B.score(q, "The attendees were Jordan Ellis; Priya Nair") == pytest.approx(2 * 1 * 0.5 / 1.5, abs=1e-3)
    assert B.score(q, "Jordan Ellis, Priya Nair, Lina Chen, Marco Ruiz, Ava Lee") == pytest.approx(2 * 0.8 / 1.8, abs=1e-3)
    assert B.score(q, "Jordan, Priya") == 0.0, "first names alone are not the people"
    assert B.score(q, "not found") == 0.0


def test_a_project_s_people_and_a_customer_s_tickets():
    docs = [_lin("l1", "ENG-11", "Omar Singh", project="Edge Rollout"), _lin("l2", "ENG-12", "Liam Chen", project="Edge Rollout"),
            _lin("l3", "ENG-13", "Omar Singh", project="edge rollout"), _lin("l4", "ENG-14", "Ava Lee", project="Solo"),
            _lin("l5", "ENG-15", "Ava Lee", project="Gateway"), _lin("l6", "ENG-16", "Liam Chen", project="Gateway v2"),
            _lin("l7", "ENG-17", "Ava Lee", project="Gateway")]
    qs, aside = _gen(B.project_members, docs)
    assert [(q["expected"], sorted(q["gold_docs"])) for q in qs] == [({"names": ["Liam Chen", "Omar Singh"]}, ["l1", "l2", "l3"])]
    assert aside == {"named inside another": 1}, "Gateway is part of Gateway v2; Solo has one issue"
    tickets = [_jira("j1", "SUP-1001", customer_company="Acme Retail"), _jira("j2", "SUP-1002", customer_company="Acme Retail"),
               _jira("j3", "SUP-1003", customer_company="Acme"), _jira("j4", "SUP-1004", customer_company="Verity Labs"),
               _jira("j5", "SUP-1005", customer_company="Northwind"), _jira("j6", "SUP-1005", customer_company="Other Co")]
    qs, aside = _gen(B.customer_tickets, tickets)
    assert [(q["expected"], q["pieces"]) for q in qs] == [({"ids": ["SUP-1004"], "id_kind": "key"}, ["Verity Labs", "SUP-1004"])]
    assert aside == {"named inside another": 2, "named twice": 2}
    assert B.score(qs[0], "SUP-1004") == 1.0 and B.score(qs[0], "SUP-1004, SUP-1001") == pytest.approx(0.667, abs=1e-3)


def test_a_parent_issue_question_is_multi_document():
    docs = [_lin("l1", "ENG-11", "Omar Singh", parent_issue=["ENG-20"]), _lin("l2", "ENG-20", "Liam Chen"),
            _lin("l3", "ENG-12", "Ava Lee", parent_issue=["ENG-20", "ENG-21"]), _lin("l4", "ENG-21", "Ava Lee"),
            _lin("l5", "ENG-13", "Ava Lee", parent_issue=["ENG-99"])]
    qs, aside = _gen(B.parent_issue, docs)
    assert len(qs) == 1 and qs[0]["family"] == "multi" and qs[0]["group"] == "link" and "ENG-11" in qs[0]["question"]
    assert qs[0]["expected"] in ({"value": "In Progress"}, {"value": "Liam Chen"}) and qs[0]["pieces"][0] == "ENG-20"
    assert sorted(qs[0]["gold_docs"]) == ["l1", "l2"] and aside == {"several values": 1}, "ENG-99 is not in the haystack: no question"
    assert B.score(qs[0], qs[0]["expected"]["value"]) == 1.0


def test_not_found_questions_name_what_no_document_writes():
    docs = [_lin("l1", "ENG-1234", "Omar Singh", links=["ENG-1999"]), _jira("j1", "SUP-77", "Liam Chen"), _pr("p1", "4821"),
            _d("g1", "google_drive", "Runway model for the third quarter", owner="Ava Lee"),
            _d("g2", "google_drive", "Security questionnaire answers for Acme", owner="Maya Chen")]
    text = B._written(docs)
    tickets, _ = _gen(B.missing_tickets, docs, cap=10)
    assert len(tickets) == 10 and all(q["expected"] == {"not_found": True} and q["gold_docs"] == [] for q in tickets)
    for q in tickets:
        k = q["pieces"][0]
        assert k.lower() not in text and (k.startswith("ENG-") and len(k) == 8 or k.startswith("SUP-") and len(k) == 6)
    prs, _ = _gen(B.missing_prs, docs, cap=5)
    assert all(len(q["pieces"][0]) == 4 and q["pieces"][0] not in text for q in prs)
    titles, _ = _gen(B.missing_titles, docs, cap=2)
    assert titles and all(q["pieces"][0].lower() not in text and f'"{q["pieces"][0]}"' in q["question"] for q in titles)
    people, _ = _gen(B.missing_people, docs, cap=5)
    assert people and all(q["pieces"][0].lower() not in text and len(q["pieces"][0].split()) == 2 for q in people)
    q = people[0]
    assert q["family"] == "not_found"
    assert B.score(q, "not found") == 1.0 and B.score(q, "Answer: Not found.") == 1.0 and B.score(q, {"answer": "", "route": "not_found"}) == 1.0
    assert B.score(q, "ENG-1234") == 0.0 and B.score(q, "The ticket was not found") == 0.0


def test_score_dispatches_by_kind():
    due = {"id": "linear_due-001", "kind": "linear_due", "question": "When?", "expected": {"date": "2026-03-20"}}
    assert B.score(due, "2026-03-20") == 1.0 and B.score(due, {"answer": "March 20, 2026"}) == 1.0 and B.score(due, "not found") == 0.0
    assert B.score(due, "2026-03-20T10:00:00Z") == 0.0, "the memory test's kinds are scored exactly as factbank_test.direct"
    lst = {"id": "x", "kind": "linear_assignee", "question": "List", "expected": {"ids": ["ENG-11", "ENG-12"], "id_kind": "key"}}
    assert B.score(lst, "ENG-11") == pytest.approx(0.667, abs=1e-3)
    first = {"id": "y", "kind": "person_first", "question": "Which is due first?", "expected": {"ids": ["ENG-11"], "id_kind": "key"}}
    assert B.score(first, "ENG-11, ENG-12") == 0.0, "one key, exactly (factbank_multi.own_score)"
    value = {"id": "z", "kind": "drive_status", "question": "?", "expected": {"value": "in_review", "alts": ["in review"]}}
    assert B.score(value, "In review") == 1.0 and B.score(value, "draft") == 0.0
    with pytest.raises(ValueError):
        B.score({"id": "c", "kind": "conflicting_info", "question": "?", "expected": {}}, "x")


def test_prose_questions_load_and_score_by_their_facts(tmp_path):
    p = tmp_path / "prose.jsonl"
    p.write_text(json.dumps({"question": "Why was the rollout paused?", "answer_facts": ["p99 latency rose to 840 ms", "the canary failed in eu-west"],
                             "gold_docs": ["d1"]}) + "\n\n"
                 + json.dumps({"question_id": "qst_9", "question": "Who approved?", "answer_facts": ["Maya Chen approved the change"],
                               "expected_doc_ids": ["d2"]}) + "\n")
    qs = B.load_prose(p)
    assert [(q["id"], q["family"], q["gold_docs"]) for q in qs] == [("prose-001", "prose", ["d1"]), ("qst_9", "prose", ["d2"])]
    q = qs[0]
    assert B.score(q, "The rollout paused because p99 latency rose to 840 ms after the canary failed in eu-west.") == 1.0
    assert B.score(q, "p99 latency rose to 840 ms.") == 0.5 and B.score(q, "not found") == 0.0
    ev = "[1] notes\nThe canary failed in eu-west on Tuesday.\n\n[2] other\nlatency rose\n\n[3] graph\np99 latency rose to 840 ms"
    assert B.prose_reach(q, ev) == 1.0
    assert B.prose_reach(q, ev, budget=60) == 0.5, "the latency fact lies beyond the budget"
    assert B.prose_reach(q, "p99 latency\n\nrose to 840 ms") == 0.0, "one passage must hold the fact"
    (tmp_path / "bad.jsonl").write_text(json.dumps({"question": "x", "answer_facts": []}) + "\n")
    with pytest.raises(ValueError):
        B.load_prose(tmp_path / "bad.jsonl")


def _haystack():
    docs = [_lin(f"l{i}", f"ENG-{10 + i}", who, due, project=proj) for i, (who, due, proj) in enumerate([
        ("Omar Singh", "2026-03-20", "Edge"), ("Omar Singh", "2026-04-02", "Edge"), ("Liam Chen", "2026-05-01", "Core"),
        ("Liam Chen", "2026-06-01", "Core"), ("Ava Lee", "2026-03-25", "Core"), ("Ava Lee", "2026-07-01", "Edge")])]
    docs += [_jira("j1", "SUP-501", "Omar Singh", customer_company="Acme Retail"), _jira("j2", "SUP-502", "Ava Lee", customer_company="Verity")]
    docs += [_pr("p1", "4821", linked_linear=["ENG-12"]), _pr("p2", "4822", author="Liam Chen", linked_linear=["ENG-13"])]
    docs += [_d("g1", "google_drive", "Runway model for the third quarter", owner="Ava Lee", status="draft", created_at="2026-01-02"),
             _d("f1", "fireflies", "Acme kickoff call", redwood_owner="Maya Chen", redwood_attendees=["Maya Chen (AE)"],
                customer_attendees=["Tom Reed"], customer_company="Acme Retail", recorded_at="2026-02-02T10:00:00Z",
                action_items=["Liam Chen - Share the capacity sizing sheet with Acme - due 2026-03-01"])]
    return docs


def test_generate_reuses_the_existing_generators_unchanged_and_sets_aside_unclear_ones():
    docs = _haystack()
    qs, rep = B.generate(docs, seed=7)
    mem = [q for q in qs if q["kind"] in B.MEMORY_KINDS]
    ref = generate_questions(docs, 7, caps={k: B.ALL for k in B.MEMORY_KINDS})
    assert [{k: v for k, v in q.items() if k not in ("family", "pieces")} for q in mem] == ref
    assert all(q["family"] == "single" and q["pieces"] for q in mem)
    multi = [q for q in qs if q["family"] == "multi"]
    raw = M.questions(docs, {d["dsid"] for d in docs}, True, 7, max_q=None)
    assert {q["id"] for q in multi if q["kind"] in B.MULTI_KINDS} < {q["id"] for q in raw}
    assert rep["aside"]["person_count"] == {"tickets": 2}, "Omar Singh and Ava Lee have a Jira ticket too"
    assert set(rep["by_kind"]) == set(B.CATALOGUE) - {"prose", "metadata"}
    assert all(set(q) >= {"id", "group", "kind", "family", "question", "expected", "gold_docs", "pieces"} for q in qs)
    assert len({q["id"] for q in qs}) == len(qs)
    assert B.generate(docs, seed=7) == (qs, rep), "the same seed gives the same questions"


def test_draw_questions_follows_the_mix_and_prefers_documents_not_yet_asked_about():
    docs = _haystack()
    assert B.resolve("fields") >= {"drive_owner", "jira_status"} and B.resolve("not_found") == {"nf_ticket", "nf_pr", "nf_title", "nf_person"}
    with pytest.raises(ValueError):
        B.resolve("nonsense")
    avail = Counter({"nf_ticket": 5, "nf_pr": 5, "nf_title": 1, "nf_person": 5})
    for seed in range(5):
        qu = B.quotas({"not_found": 6, "nf_pr": 1}, avail, seed)
        assert sum(qu.values()) == 7 and qu["nf_title"] == 1 and all(qu[k] <= avail[k] for k in qu)
        rest = [qu["nf_ticket"], qu["nf_pr"] - 1, qu["nf_person"]]
        assert sorted(rest) == [1, 2, 2], "the group's six go round its kinds in turn; the one kind with one question gives one"
    assert len({tuple(sorted(B.quotas({"fields": 5}, Counter({k: 3 for k in B.FIELDS}), s).items())) for s in range(5)}) > 1, \
        "which kinds a small number reaches is drawn, not the first in name order"
    drawn = B.draw_questions(docs, seed=3, mix={"jira_status": 1, "jira_priority": 1, "not_found": 4, "prose": 1},
                             prose=[{"id": "prose-001", "kind": "prose", "family": "prose", "group": "prose", "question": "?",
                                     "expected": {"facts": ["x1"]}, "gold_docs": ["g1"], "pieces": ["x1"]}])
    kinds = Counter(q["kind"] for q in drawn)
    assert kinds["jira_status"] == 1 and kinds["jira_priority"] == 1 and kinds["prose"] == 1
    assert sum(v for k, v in kinds.items() if k.startswith("nf_")) == 4
    priority, status = (next(q for q in drawn if q["kind"] == k) for k in ("jira_priority", "jira_status"))
    assert priority["gold_docs"] != status["gold_docs"], "the second Jira question is about the other ticket"
    assert B.draw_questions(docs, seed=3, mix={"fields": 4}) == B.draw_questions(docs, seed=3, mix={"fields": 4})


def test_an_impossible_due_date_starts_no_window():
    bad = _haystack() + [_lin("lx", "ENG-99", "Zoe Park", "2026-02-29")]
    qs = generate_questions(bad, 7, caps={"linear_due_window": 50})
    starts = {q["question"].split("between ")[1][:10] for q in qs if q["kind"] == "linear_due_window"}
    assert starts and "2026-02-29" not in starts
