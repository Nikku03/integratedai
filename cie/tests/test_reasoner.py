"""The reasoning engine (``cie.factbank.reasoner``): its tools over a tiny bank, how it reads a model's replies, and the
lockstep loop with a scripted model in place of a language model: an answer kept from the brain, a chain of tool calls, a
reply it cannot read, the step limit, and the plain-search arm's one turn."""

from __future__ import annotations

import json

import pytest
from test_brain_v16_routes import DOCS

from cie.factbank import bank as BK
from cie.factbank import reasoner as R


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    path = tmp_path_factory.mktemp("reasoner") / "factbank_v2.sqlite"
    BK.build(path, DOCS, text_facts=True)
    return R.Toolbox(path, brain=lambda q: {"answer": "2026-04-02", "route": "fact", "reason": "due_date of DES-1",
                                            "evidence": "Answer: 2026-04-02\n- due date of DES-1: 2026-04-02"})


def test_find_counts_and_lists_by_exact_field_values(box):
    r = box.find("linear", {"assignee": "omar singh"}, ["key", "status"])
    assert r["count"] == 2 and {x["key"] for x in r["records"]} == {"ENG-12", "ENG-13"}
    assert {x["status"] for x in r["records"]} == {"Done", "In Progress"}
    assert box.find("linear", {"assignee": "Omar Singh", "status": "done"})["count"] == 1
    assert box.find("jira", {"priority": ["P1", "P2"]})["count"] == 3  # a list is any of its values
    assert box.find("jira", {"priority": "P9"})["count"] == 0
    assert "error" in box.find("tickets", {"priority": "P1"})


def test_values_search_and_read(box):
    v = box.values("jira", "priority")
    assert v["values"][0] == {"value": "P1", "records": 2} and v["distinct"] == 2
    assert "error" in box.values("jira", "colour") and "priority" in box.values("jira", "colour")["fields"]
    hits = box.search("badge printer replacement")["results"]
    assert hits and hits[0]["title"] == "Replace the badge printer" and hits[0]["key"] == "ENG-13"
    assert all(h["system"] == "jira" for h in box.search("webhook retries", system="jira")["results"])
    doc = box.read(hits[0]["doc"])
    assert doc["title"] == "Replace the badge printer" and "Omar Singh" in doc["text"]
    long = box.read([h for h in box.search("telemetry runbook")["results"] if h["system"] == "confluence"][0]["doc"], query="verify telemetry",
                    chars=400)
    assert "status endpoint" in long["text"] and long["text"].endswith("left out]")
    assert "error" in box.read("doc:nothing")


def test_run_never_raises(box):
    assert "missing argument" in box.run("find", {"where": {}})["error"]
    assert "no tool" in box.run("delete", {})["error"]
    assert box.run("brain", {"question": "When is DES-1 due?"})["answer"] == "2026-04-02"


def test_parse_action():
    assert R.parse_action('<think>\nplan {"tool": "x"}\n</think>\n\n{"tool": "find", "args": {"system": "jira"}}') == \
        {"tool": "find", "args": {"system": "jira"}}
    assert R.parse_action('{"answer": ["ENG-12", "ENG-13"]}') == {"answer": "ENG-12, ENG-13"}
    assert R.parse_action('I will search. {"tool": "search", "query": "badge"}') == {"tool": "search", "args": {"query": "badge"}}
    assert R.parse_action("Reasoning...\nAnswer: Omar Singh") == {"answer": "Omar Singh"}
    assert R.parse_action("<think>\nstill thinking, cut off") is None
    assert R.parse_action('{"answer": "a {brace} inside"}') == {"answer": "a {brace} inside"}
    assert R.final("Not found in the records.") == R.NOT_FOUND and R.final("") == R.NOT_FOUND
    assert len(R.final("x" * 5000)) == R.ANSWER_CAP


class Script:
    """A scripted model: for each conversation, the reply chosen by the question and the turn."""

    def __init__(self, plays: dict[str, list[str]]):
        self.plays, self.calls = plays, 0

    def __call__(self, convs):
        self.calls += 1
        out = []
        for c in convs:
            q = c[1]["content"].split("\n", 1)[0].removeprefix("Question: ")
            turn = sum(1 for m in c if m["role"] == "assistant")
            out.append({"text": self.plays[q][min(turn, len(self.plays[q]) - 1)], "prompt_tokens": 10, "output_tokens": 5,
                        "finish_reason": "stop"})
        return out


def test_reason_in_lockstep(box):
    qs = [{"id": "a", "question": "When is DES-1 due?"}, {"id": "b", "question": "How many issues does Omar Singh have?"},
          {"id": "c", "question": "garbled"}, {"id": "d", "question": "loops"}]
    brain = {"a": {"answer": "2026-04-02", "route": "fact"}, "b": {"answer": "1", "route": "table"},
             "c": {"answer": "Liam Chen", "route": "fact"}, "d": {"answer": "x", "route": "fact"}}
    model = Script({
        "When is DES-1 due?": ['{"answer": "2026-04-02"}'],
        "How many issues does Omar Singh have?": ['{"tool": "values", "args": {"system": "linear", "field": "assignee"}}',
                                                  '{"tool": "find", "args": {"system": "linear", "where": {"assignee": "Omar Singh"}}}',
                                                  '{"answer": "2"}'],
        "garbled": ["hmm", "still nothing", "no"],
        "loops": ['{"tool": "search", "args": {"query": "badge"}}'],
    })
    rows = {r["id"]: r for r in R.reason(qs, brain, model, R.LocalTools(box), max_steps=3, log=lambda *_: None)}
    assert rows["a"]["answer"] == "2026-04-02" and rows["a"]["reason"] == "0 tool call(s): none"
    assert rows["b"]["answer"] == "2" and [s.get("tool") for s in rows["b"]["steps"]] == ["values", "find", None]
    assert rows["c"]["answer"] == "Liam Chen" and rows["c"]["steps"][-1]["gave_up"]  # no answer of its own: the brain's stands
    assert sum(1 for s in rows["d"]["steps"] if "tool" in s) == 3 and rows["d"]["steps"][-1].get("gave_up")
    assert all(r["route"] == "reasoner" and r["output_tokens"] > 0 for r in rows.values())
    assert model.calls <= 6  # one batched call per turn for every open conversation


def test_first_message_shows_the_brain(box):
    seen = []

    def model(convs):
        seen.extend(convs)
        return [{"text": '{"answer": "not found"}'} for _ in convs]

    rows = R.reason([{"id": "a", "question": "Who owns ZZ-1?"}], {"a": {"answer": "not found", "route": "not_found", "evidence": ""}},
                    model, R.LocalTools(box), log=lambda *_: None)
    assert rows[0]["answer"] == R.NOT_FOUND
    first = seen[0][1]["content"]
    assert first.startswith("Question: Who owns ZZ-1?") and json.loads(first.split("first answer:\n")[1].split("\n\n")[0])["route"] == "not_found"
    assert seen[0][0]["content"] == R.SYSTEM


def test_rag_turn():
    conv = R.rag_conversation("Who owns it?", [{"source": "jira", "title": "T", "text": "Owner: Ava"}] * 3, chars=40)
    assert conv[0]["content"] == R.RAG_SYSTEM and conv[1]["content"].count("[") == 1  # one passage fits in 40 characters
    assert R.rag_answer("<think>x</think>\nThe owner is Ava.\nAnswer: Ava Chen") == "Ava Chen"
    assert R.rag_answer("Answer: not found") == R.NOT_FOUND


def test_template_kwargs():
    assert R.template_kwargs("qwen3.8-27b", "medium", None) == {"enable_thinking": True, "preserve_thinking": False,
                                                                "reasoning_effort": "medium"}
    assert R.template_kwargs("qwen3.8-27b", "medium", False) == {"enable_thinking": False, "preserve_thinking": False}
    assert "date_string" in R.template_kwargs("llama-3.1-8b", None, None)


def test_answer_line():
    assert R.answer_line("**Answer:** Ava Chen") == "Ava Chen"
    assert R.answer_line("The list:\nAnswer:\nErin Cole, Diego Ramos") == "Erin Cole, Diego Ramos"
    assert R.answer_line("no line here") is None
    assert R.final("<final answer>.") == R.NOT_FOUND
