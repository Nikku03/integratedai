"""The 5,000-document test, part A: the draw, the questions set aside, the selection and the small control set."""

from __future__ import annotations

import json

from cie.eval import factbank_5k as F
from cie.eval import factbank_multi as M
from cie.eval.memory_test import _write_jsonl


def _lin(dsid, key, who, due, **x):
    return {"dsid": dsid, "source": "linear", "title": f"issue {key}", "raw": {"key": key, "assignee": who, "due_date": due, "status": "Todo", **x}}


def _jira(dsid, key, who):
    return {"dsid": dsid, "source": "jira", "title": f"ticket {key}", "raw": {"key": key, "assignee": who, "status": "Open"}}


def _pr(dsid, n, links, author="Maya Chen"):
    return {"dsid": dsid, "source": "github", "title": f"PR {n}", "raw": {"pr_number": n, "author": author, "linked_linear": links}}


def test_the_draw_keeps_one_document_per_key_and_number_and_plants_pull_requests():
    docs = [_lin("l1", "ENG-11", "Omar Singh", "2026-03-20"), _lin("l2", "ENG-11", "Liam Chen", "2026-04-01"),  # a reused key
            _lin("l3", "ENG-12", "Omar Singh", "2026-04-02"), _lin("l4", "ENG-13", "Liam Chen", "2026-05-01"),
            _jira("j1", "INT-1", "Omar Singh"), _jira("j2", "INT-1", "Ava Lee"),
            _pr("g1", "4821", ["ENG-12"]), _pr("g2", "4821", ["ENG-13"]),  # a reused number
            _pr("g3", "5100", ["ENG-13"]), _pr("g4", "5200", ["ENG-13"])]  # ENG-13 has two pull requests: not plantable
    index = {d["dsid"]: f"{d['source']}/{d['dsid']}.json" for d in docs} | {f"s{i}": f"slack/s{i}.json" for i in range(10)}
    by_id = {d["dsid"]: d for d in docs}
    ids, info = F.draw(index, exclude={"s0"}, load=lambda xs: [by_id[x] for x in xs if x in by_id], n=12, seed=1, planted=1)
    chosen = [by_id[x] for x in ids if x in by_id]
    keys = [F._key(d) for d in chosen if F._key(d)]
    assert len(keys) == len(set(keys)), "one document per ticket key"
    prs = [F._pr(d) for d in chosen if F._pr(d)]
    assert len(prs) == len(set(prs)), "one document per pull request number"
    assert "s0" not in ids and len(ids) <= 12
    assert info["planted_candidates"] == 0, "4821 is reused and ENG-13 has several pull requests: nothing can be planted"
    docs2 = docs[:4] + [_pr("g5", "6100", ["ENG-12"])]
    by2 = {d["dsid"]: d for d in docs2}
    ids2, info2 = F.draw({d["dsid"]: f"{d['source']}/{d['dsid']}.json" for d in docs2}, set(), lambda xs: [by2[x] for x in xs if x in by2],
                         n=4, seed=1, planted=1)
    assert info2["planted"] == [{"pr": "g5", "issue": "l3"}] and {"g5", "l3"} <= set(ids2)
    odd = docs2 + [_lin("l9", "ENG-642317-DECISION-REFACTOR", "Ava Lee", "2026-02-01")]
    by3 = {d["dsid"]: d for d in odd}
    ids3, info3 = F.draw({d["dsid"]: f"{d['source']}/{d['dsid']}.json" for d in odd}, set(), lambda xs: [by3[x] for x in xs if x in by3],
                         n=6, seed=1, planted=1)
    assert "l9" not in ids3 and info3["skipped"].get("key not a plain ticket key") == 1


def test_questions_with_more_than_one_right_answer_are_set_aside():
    inside = [_lin("l1", "ENG-11", "Omar Singh", "2026-03-20"), _lin("l2", "ENG-12", "Omar Singh", "2026-04-02"),
              _lin("l3", "ENG-13", "Liam Chen", "2026-05-01"), _lin("l4", "ENG-14", "Liam Chen", "2026-06-01"),
              _jira("j1", "INT-1", "Omar Singh")]
    count = {"id": "c", "kind": "person_count", "question": "How many tickets are assigned to Omar Singh?", "expected": {"value": "2"},
             "gold_docs": ["l1", "l2"], "pieces": ["ENG-11", "ENG-12"]}
    assert F.ticket_reading(count, inside) == {"value": "3"} and F.why_unclear(count, inside) == "tickets"
    first = {"id": "f", "kind": "person_first", "question": "Of all the tickets assigned to Omar Singh, which one is due first?",
             "expected": {"ids": ["ENG-11"], "id_kind": "key"}, "gold_docs": ["l1", "l2"], "pieces": ["2026-03-20", "ENG-11"]}
    assert F.why_unclear(first, inside) is None, "a Jira ticket has no due date: the first one due is the same either way"
    liam = {**count, "question": "How many tickets are assigned to Liam Chen?", "gold_docs": ["l3", "l4"], "pieces": ["ENG-13", "ENG-14"]}
    assert F.why_unclear(liam, inside) is None
    dup = inside + [_lin("l5", "ENG-13", "Ava Lee", "2026-07-01")]
    link = {"id": "t", "kind": "ticket_link", "question": "ENG-13 is linked to another ticket - what status is it in?",
            "expected": {"value": "Todo"}, "gold_docs": ["l3", "l4"], "pieces": ["ENG-14", "Todo"]}
    assert F.why_unclear(link, dup) == "named"
    assert F.why_unclear({**liam, "pieces": ["ENG-13", "ENG-14"]}, dup) == "answer"
    link13 = {**link, "question": "ENG-13 is linked to another ticket - what status is it in?", "expected": {"value": "Todo"},
              "field": "status", "pieces": ["ENG-14", "Todo"]}
    back = inside + [{**_lin("l6", "ENG-16", "Ava Lee", "2026-07-01", dependencies=["ENG-13"]), "raw": {
        "key": "ENG-16", "assignee": "Ava Lee", "status": "Done", "dependencies": ["ENG-13"]}}]
    assert F.why_unclear(link13, back) == "linked", "a ticket linking to ENG-13 is a second reading, with another status"
    same = inside + [{"dsid": "l7", "source": "linear", "title": "x", "raw": {"key": "ENG-17", "status": "Todo", "dependencies": ["ENG-13"]}}]
    assert F.why_unclear(link13, same) is None, "a second reading with the same answer changes nothing"


def test_the_selection_takes_turns_and_prefers_new_things():
    inside = [_lin(f"l{i}", f"ENG-{i}", "Omar Singh", "2026-03-20") for i in range(6)]
    qs = [{"id": f"a-{i:03d}", "kind": "a", "gold_docs": ["l0"] if i < 3 else [f"l{i}"]} for i in range(6)]
    qs += [{"id": f"b-{i:03d}", "kind": "b", "gold_docs": [f"l{i}"]} for i in range(2)]
    got = F.pick(qs, inside, n=6, seed=3)
    assert [q["kind"] for q in got][:4] == ["a", "b", "a", "b"], "the kinds take turns"
    cross = [{"id": "a-001", "kind": "a", "gold_docs": ["l1"]}, {"id": "a-002", "kind": "a", "gold_docs": ["l2"]},
             {"id": "b-001", "kind": "b", "gold_docs": ["l1"]}, {"id": "b-002", "kind": "b", "gold_docs": ["l3"]}]
    first_two = F.pick(cross, inside, n=2, seed=0)
    assert not set(first_two[0]["gold_docs"]) & set(first_two[1]["gold_docs"]), "a turn prefers documents no other kind asked about"
    a = [q for q in got if q["kind"] == "a"]
    assert len({json.dumps(q["gold_docs"]) for q in a[:3]}) == 3, "questions about something new come first"
    assert F.pick(qs, inside, n=6, seed=3) == got, "seeded"


def test_the_small_set_reproduces_the_expected_answers():
    docs = [_lin("l11", "ENG-11", "Omar Singh", "2026-03-20"), _lin("l12", "ENG-12", "Omar Singh", "2026-04-02"),
            _lin("l13", "ENG-13", "Liam Chen", "2026-05-01", dependencies=["ENG-12"]), _lin("l14", "ENG-14", "Liam Chen", "2026-06-01"),
            _lin("l15", "ENG-15", "Ava Lee", "2026-02-01"), _pr("g1", "4821", ["ENG-11"])]
    w = {k: [v[1][0]] for k, v in M.T.items()}
    qs = M.questions(docs, {d["dsid"] for d in docs}, True, 5, wordings=w, max_q=None)
    small = F.small_set(qs)
    assert "l15" not in small or any("ENG-15" in q["question"] for q in qs)
    assert F.not_reproduced(docs, small, qs, 5, w) == []
    count = next(q for q in qs if q["kind"] == "person_count" and "Omar" in q["question"])
    assert F.not_reproduced(docs, small - {"l12"}, [count], 5, w) == [count["id"]], "a missing issue changes the count"


def test_the_scale_rules_compare_the_same_questions_on_both_banks(tmp_path):
    q = {"id": "person_count-001", "group": "combine", "kind": "person_count", "question": "How many tickets are assigned to Omar Singh?",
         "expected": {"value": "2"}, "gold_docs": ["l1", "l2"], "pieces": ["ENG-11", "ENG-12"]}
    for name, ans in (("big", "3"), ("small", "2")):
        w = tmp_path / name
        w.mkdir()
        _write_jsonl(w / "questions.jsonl", [q])
        for f in F.FILES.values():
            _write_jsonl(w / f"{f}.jsonl", [{"id": q["id"], "answer": ans, "ms": 5.0, "reads": {"ends": ["ENG-11", "ENG-12"]}}])
    rep = F.scale_test(tmp_path / "big", tmp_path / "small")
    assert rep["differences_5k_minus_small"]["v13"] == -1.0
    assert not rep["rules"]["1 nothing lost to size (v13 at 5,000 >= v13 on the small bank - 0.05)"]
    assert rep["changed_questions"][0]["v13"] == [1.0, 0.0] and rep["time_ms"]["v13"]["5k"]["median"] == 5
    assert (tmp_path / "big" / "scale_report.md").exists()
