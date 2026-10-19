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


def test_glossary_found_in_the_repository(tmp_path):
    from cie.factbank.plans import GLOSSARY_COPY, glossary_path

    gone = tmp_path / "scratch" / "glossary.json"  # where the frozen lessons name it: not on a fresh machine
    assert glossary_path(gone) == GLOSSARY_COPY
    here = tmp_path / "glossary.json"
    here.write_text("[]")
    assert glossary_path(here) == here  # a file that is there is used as named
    other = tmp_path / "x" / "lexicon.json"
    assert glossary_path(other) == other  # only v8's glossary is looked for elsewhere


def test_a_brain_that_fails_to_load_stops_the_run(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(T, "_load_brain", lambda *a: (_ for _ in ()).throw(FileNotFoundError("no lessons")))
    T._init_brain("bank", "s", "p", "r")
    assert T._BRAIN is None and "no lessons" in T._BRAIN_ERROR
    with pytest.raises(RuntimeError, match="did not load"):
        T._ask_one({"id": "q", "question": "?"})


def test_a_row_cut_off_half_way_is_asked_again(tmp_path):
    f = tmp_path / "factbank_v18.jsonl"
    f.write_text('{"id": "a", "answer": "x"}\n{"id": "b", "answ')
    assert list(T._rows(f)) == ["a"] and f.read_text() == '{"id": "a", "answer": "x"}\n'


def test_finish_keeps_answers_past_a_limit(tmp_path):
    _write(tmp_path / "questions.jsonl", [{"id": i} for i in "abc"])
    _write(tmp_path / "rag.jsonl", [{"id": "c", "answer": "3"}, {"id": "a", "answer": "1"}, {"id": "a", "answer": "1b"}])
    have = T._finish(tmp_path, "rag")
    assert [json.loads(x)["id"] for x in (tmp_path / "rag.jsonl").read_text().splitlines()] == ["a", "c"] and have["a"]["answer"] == "1b"


def test_settings_must_match(tmp_path):
    import pytest

    _write(tmp_path / "questions.jsonl", [{"id": "a"}])
    s = {"model_name": "qwen3.8-27b", "effort": "medium", "thinking": True, "max_tokens": 6144}
    T.record(tmp_path, "rag", {"arm": "rag", "file": "rag.jsonl", "seconds": 10, **s})
    T.check_settings([tmp_path], "reasoner", {**s, "model_name": "qwen3.8-27b-fp8"})  # no rag answers yet: nothing to match
    _write(tmp_path / "rag.jsonl", [{"id": "a", "answer": "x"}])
    T.check_settings([tmp_path], "reasoner", s)
    with pytest.raises(SystemExit, match="model_name"):
        T.check_settings([tmp_path], "reasoner", {**s, "model_name": "qwen3.8-27b-fp8"})
    with pytest.raises(SystemExit, match="effort"):
        T.check_settings([tmp_path], "rag", {**s, "effort": "low"})
    T.record(tmp_path, "rag", {"arm": "rag", "file": "rag.jsonl", "seconds": 5, **s}, add=True)
    assert json.loads((tmp_path / "arms50k.json").read_text())["rag"]["seconds"] == 15  # a resumed run adds its time


def test_rules_7_and_8_need_the_same_model(tmp_path):
    test_score_folder_and_rules(tmp_path)
    s = {"effort": "medium", "thinking": True, "max_tokens": 6144}
    T.record(tmp_path, "rag", {"file": "rag.jsonl", "model_name": "qwen3.8-27b", **s})
    T.record(tmp_path, "reasoner", {"file": "reasoner.jsonl", "model_name": "qwen3.8-27b-fp8", **s})
    rep = T.score(tmp_path, None, None)
    said = {k[0]: v for k, v in rep["rules"].items()}
    assert said["7"] is None and said["8"] is None and said["2"] and "rules 7 and 8 are undecided" in rep["warnings"][0]
    md = (tmp_path / "report50k.md").read_text()
    assert "**Warning:**" in md and "How the model arms ran" in md


def _die(q):  # a brain process killed (out of memory) while it answers
    import os
    import signal

    os.kill(os.getpid(), signal.SIGKILL)


def test_a_brain_process_that_dies_stops_the_step(tmp_path, monkeypatch):
    import pytest

    _write(tmp_path / "questions.jsonl", [{"id": i, "question": "?"} for i in "abcd"])
    monkeypatch.setattr(T, "_load_brain", lambda *a: None)
    monkeypatch.setattr(T, "_ask_one", _die)
    with pytest.raises(RuntimeError, match="a brain process died"):
        T.ask_v18(tmp_path, workers=2, log=lambda *_: None)


def test_reasoner_rows_written_as_they_end(tmp_path):
    from test_brain_v16_routes import DOCS

    from cie.factbank import bank as BK
    from cie.factbank import reasoner as R

    BK.build(tmp_path / "factbank_v2.sqlite", DOCS, text_facts=True)
    box = R.Toolbox(tmp_path / "factbank_v2.sqlite")
    _write(tmp_path / "questions.jsonl", [{"id": "a", "question": "When is DES-1 due?"}, {"id": "b", "question": "Who?"}])
    _write(tmp_path / "factbank_v18.jsonl", [{"id": "a", "answer": "2026-04-02", "route": "fact"}, {"id": "b", "answer": "x", "route": "fact"}])
    _write(tmp_path / "reasoner.jsonl", [{"id": "b", "answer": "kept", "route": "reasoner", "steps": []}])

    class Model:
        repo = "scripted"

        def __call__(self, convs):
            return [{"text": '{"answer": "2026-04-02"}', "finish_reason": "stop", "output_tokens": 4} for _ in convs]

    s = {"model_name": "m", "effort": "medium", "thinking": True, "max_tokens": 6144}
    rep = T.ask_llm([tmp_path], "reasoner", Model(), R.LocalTools(box), settings=s, log=lambda *_: None)
    rows = [json.loads(x) for x in (tmp_path / "reasoner.jsonl").read_text().splitlines()]
    assert [(r["id"], r["answer"]) for r in rows] == [("a", "2026-04-02"), ("b", "kept")] and rep[str(tmp_path)]["asked"] == 1
    reg = json.loads((tmp_path / "arms50k.json").read_text())["reasoner"]
    assert reg["model"] == "scripted" and reg["model_name"] == "m" and reg["asked"] == 1
    # nothing left to ask: the step ends before it loads a model (none could load here)
    assert T.main(["ask", "--arm", "reasoner", "--work", str(tmp_path), "--model", "no-such-model"])[str(tmp_path)]["asked"] == 0
