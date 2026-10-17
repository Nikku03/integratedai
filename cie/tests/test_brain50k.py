"""The 50,000-document test's harness (``cie.eval.brain50k``): the draw keeps the base set and its one-answer names, a count
is counted again among the bigger haystack, and the report's scores and rules."""

from __future__ import annotations

import json

from cie.eval import brain50k as T


def _d(dsid, source, **raw):
    return {"dsid": dsid, "source": source, "title": raw.pop("title", dsid), "raw": raw}


def test_grow_keeps_the_base_and_one_document_per_name():
    base_docs = [_d("b1", "linear", key="ENG-11"), _d("b2", "github", pr_number="101", linked_linear=["ENG-11"]), _d("b3", "slack")]
    more = [_d("x1", "linear", key="ENG-11"),  # the same key as a base issue
            _d("x2", "linear", key="ENG-21", parent_issue="ENG-11"),  # links a base ticket
            _d("x3", "github", pr_number="101"),  # the same pull request number
            _d("x4", "linear", key="ENG-31"), _d("x5", "github", pr_number="202", linked_linear=["ENG-31"]),
            *(_d(f"s{i}", "slack") for i in range(10))]
    docs = {d["dsid"]: d for d in base_docs + more}
    index = {d: f"{docs[d]['source']}/{d}.json" for d in docs}
    index["held"] = "linear/held.json"
    reasons = set()
    for seed in range(8):
        ids, info = T.grow(index, ["b1", "b2", "b3"], {"held"}, lambda xs: [docs[x] for x in xs if x in docs], n=10, seed=seed)
        assert {"b1", "b2", "b3"} <= set(ids) and "held" not in ids and not {"x1", "x2", "x3"} & set(ids)
        assert len(ids) == 10 - sum(info["short"].values())
        reasons |= set(info["skipped"])
    assert reasons == {"ticket key already drawn", "links a ticket of the base set", "pull request number already drawn"}


def test_recount():
    docs = [_d("a", "jira", priority="P1", status="Open"), _d("b", "jira", priority="P1", status="Closed"), _d("c", "jira", priority="P2")]
    q = {"id": "q", "kind": "count1_jira", "filters": [["priority", "P1"]], "expected": {"value": "1"}, "gold_docs": ["a"]}
    new, why = T.recount(q, docs)
    assert why == "" and new["expected"]["value"] == "2" and new["gold_docs"] == ["a", "b"] and new["recounted"]
    assert T.recount({**q, "filters": [["priority", "P9"]]}, docs) == (None, "no documents hold the filters")
    assert T.recount({"id": "x", "kind": "linear_due", "expected": {"date": "2026-01-01"}}, docs) == (None, "not a count")


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_score_folder_and_rules(tmp_path):
    fams = ["single", "multi", "prose", "not_found", "counts", "history", "email_chat", "unanswerable"]
    qs = []
    for f in fams:
        if f == "not_found":
            qs.append({"id": f, "family": f, "kind": "nf_title", "group": "not_found", "question": "?", "expected": {"not_found": True}})
        elif f == "unanswerable":
            qs.append({"id": f, "family": f, "kind": "heldout", "group": "heldout", "question": "?", "expected": {"not_found": True}})
        else:
            qs.append({"id": f, "family": f, "kind": "count1_jira", "group": "count", "question": "?", "expected": {"value": "2"}})
    qs.append({"id": "cx", "family": "complex", "kind": "owner_meetings", "steps": 3, "answer_type": "count", "question": "?",
               "expected": {"value": "4"}})
    _write(tmp_path / "questions.jsonl", qs)
    nf = {"not_found", "unanswerable"}
    _write(tmp_path / "factbank_v18.jsonl", [{"id": q["id"], "answer": "not found" if q["id"] in nf else "2" if q["id"] != "prose" else "x",
                                              "route": "fact"} for q in qs])
    _write(tmp_path / "reasoner.jsonl", [{"id": q["id"], "answer": "not found" if q["id"] in nf else "4" if q["id"] == "cx" else "2",
                                          "route": "reasoner", "output_tokens": 100} for q in qs])
    _write(tmp_path / "rag.jsonl", [{"id": q["id"], "answer": "not found", "route": "rag"} for q in qs])
    rep = T.score_folder(tmp_path)
    a = rep["arms"]
    assert a["v18"]["by_family"]["prose"] == 0.0 and a["reasoner"]["by_family"]["complex"] == 1.0 and a["v18"]["by_family"]["complex"] == 0.0
    assert a["reasoner"]["mean_of_eight"] == 1.0 and a["v18"]["mean_of_eight"] == 0.875
    assert a["rag"]["false_not_found"] == 1.0 and a["reasoner"]["false_not_found"] == 0.0
    assert rep["paired"]["reasoner - v18"]["complex"]["mean"] == 1.0 and list(rep["arms"]) == ["reasoner", "rag", "v18"]
    verdicts = {k[0]: T._try(fn, {"messy": rep}) for k, fn in T.rules().items()}
    assert verdicts["1"] is None  # no answers at 5,000 documents: undecided
    assert verdicts["2"] and verdicts["3"] and verdicts["4"] and verdicts["5"] and verdicts["6"] and verdicts["7"] and verdicts["8"]
    md = T.to_markdown({"messy": rep, "rules": {k: True for k in T.rules()}})
    assert "| reasoner |" in md and "owner_meetings" in md and "| met |" in md
