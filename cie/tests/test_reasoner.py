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
    assert R.parse_action("Reasoning...\nAnswer: Omar Singh") == {"answer": "Omar Singh", "join": True}
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


def test_cut_off_thinking_is_no_reply():
    cut = '<think>\nThe brain said 3, so {"answer": "3"} might be right, but wait'  # what the vLLM backend returns, opener put back
    assert R.visible(cut) == "" and R.parse_action(cut) is None
    assert R.rag_answer(cut, "length") == "(no reply: cut off)" and R.rag_answer("<think>\n</think>\n\n", "stop") == "(no reply)"
    assert R.rag_answer('<think>\nok</think>\n\nAnswer: Ava Chen') == "Ava Chen"


def test_parse_action_more_forms():
    assert R.parse_action('{"answer": "The team decided:\n1. Raise Pro by 12%.\n2. Keep Starter."}') == \
        {"answer": "The team decided: Raise Pro by 12%.; Keep Starter."}  # a raw line break inside the string
    assert R.parse_action('{"answer": null}') == {"answer": R.NOT_FOUND}
    assert R.parse_action('{"answer": 3}') == {"answer": "3"}
    assert R.parse_action('{"name": "find", "arguments": {"system": "jira"}}') == {"tool": "find", "args": {"system": "jira"}}
    assert R.parse_action('{"name": "find", "arguments": "{\\"system\\": \\"jira\\"}"}') == {"tool": "find", "args": {"system": "jira"}}
    assert R.parse_action("<tool_call>\n<function=find>\n<parameter=system>\nlinear\n</parameter>\n<parameter=where>\n"
                          '{"status": "Todo"}\n</parameter>\n</function>\n</tool_call>') == \
        {"tool": "find", "args": {"system": "linear", "where": {"status": "Todo"}}}
    assert R.parse_action('{"answer": "He wrote \\"{x}\\" and \\"}\\" there"}') == {"answer": 'He wrote "{x}" and "}" there'}
    assert R.parse_action('{"name": "Ava Chen"}') is None  # a name is not a tool call
    assert R.parse_action('{"name": "answer", "arguments": {"answer": "ENG-12"}}') == {"answer": "ENG-12"}  # an answer written as a call
    assert R.parse_action("<tool_call>\n<function=answer>\n<parameter=answer>\nENG-12\n</parameter>\n</function>\n</tool_call>") == {"answer": "ENG-12"}
    assert R.parse_action('{"name": "find", "parameters": {"system": "jira"}}') == {"tool": "find", "args": {"system": "jira"}}


def test_answer_lines_and_lists():
    assert R.answer_line("Reviewers:\nAnswer:\n- Maya Patel\n- Liam Ortiz\n- Ava Chen\n\n(Sources: [2])") == "Maya Patel; Liam Ortiz; Ava Chen"
    assert R.answer_line("Answer: In the review the team decided three things:\n1. Raise Pro\n2. Keep Starter\n3. Pilot in Q3") == \
        "In the review the team decided three things: Raise Pro; Keep Starter; Pilot in Q3"
    assert R.answer_line("Answer: Marco Rivera\n- DES-1 is due first (Marco Rivera)\n- DES-2 (Ana Lopez)") == "Marco Rivera"
    assert R.answer_line("Answer: Maya Patel, Liam Ortiz\n(Sources: [2], [5])") == "Maya Patel, Liam Ortiz"
    assert R.answer_line("ENG-12 is due on 2026-03-15 per [2].\n\nFinal answer: 2026-03-15") == "2026-03-15"
    assert R.answer_line("**Final Answer:** 3") == "3"
    # below a bare label: every line (stored joined, as before); a list there is read as a list, its note left out
    assert R.rag_answer("Answer:\nThe pilot starts in March.\n\nIt runs three weeks.") == "The pilot starts in March. It runs three weeks."
    assert R.answer_line("**Answer:**\n\nThe escalation intake template requires:\n\n- UTC timestamps, region,\n  tier (Hosted/Dedicated)\n"
                         "- streaming yes/no\n\n(Sources: [3])") == \
        "The escalation intake template requires: UTC timestamps, region, tier (Hosted/Dedicated); streaming yes/no"
    assert R.one_line("3. ENG-1, ENG-2\nThose are the matching issues.") == "3. ENG-1, ENG-2\nThose are the matching issues."  # not a list
    assert R.parse_action('{"answer": "2028-01-24\nIt was moved from 2028-01-10."}') == {"answer": "2028-01-24\nIt was moved from 2028-01-10."}


def test_final_reads_refusals():
    for a in ("There is no such ticket.", "The passages do not contain this information.", "I could not find this in the passages.",
              "Not in the passages.", "None", "null", "No Jira tickets are assigned to Riley Silva.", "No CSM is listed for Wrenfield.",
              "Not specified"):
        assert R.final(a) == R.NOT_FOUND, a
    for a in ("There is no rollback plan; it moves to Q3", "No. 3 is the one: ENG-12", "Ava Chen",
              "There is no fixed date. The team planned a pilot in March.", "Maya Patel; Liam Ortiz",
              "Not stated directly, but it is 2028-01-24", "There is no exact field for it, the record gives 2028-01-24",
              "Not mentioned in the notes (the tracker says 2028-01-24)", "No due date is listed in the meeting\nThe tracker gives 2028-01-24"):
        assert R.final(a) == a, a
    assert R.final("There is no such ticket.", refusals=False) == "There is no such ticket."
    assert R.final("There is no ticket ENG-99999 in the records.") == R.NOT_FOUND
    assert R.rag_answer("Answer: The passages do not state a due date directly, but the action item lists 2028-01-24.") != R.NOT_FOUND


def test_find_keeps_what_fits(box, monkeypatch):
    monkeypatch.setattr(R, "RESULT_CHARS", 300)
    r = box.find("linear", {}, ["key", "status", "assignee"])
    assert 0 < len(r["records"]) < r["count"] and r["note"].startswith(f"{r['count']} records match; the first {len(r['records'])}")
    assert "narrow" in r["note"]
    assert R._cut("x" * 400) == "x" * R.FIELD_CHARS + " [...]"
    assert {"key", "status"} <= set(box.find("linear", {"assignee": "Omar Singh"}, "key, status")["records"][0])  # "show" as one string


def test_reason_out_of_room_and_long_conversations(box, monkeypatch):
    seen = []

    def model(convs):
        out = []
        for c in convs:
            q = c[1]["content"].split("\n", 1)[0]
            if "ZZ-1" in q:
                out.append({"text": "", "finish_reason": "too_long"})
            else:
                out.append({"text": '{"answer": "done"}' if any(m["content"].endswith(R.LAST) for m in c) else
                            '{"tool": "search", "args": {"query": "badge"}}', "finish_reason": "stop"})
        return out

    monkeypatch.setattr(R, "CONV_CHARS", 1)  # every conversation is long at once: it must answer next
    brain = {"a": {"answer": "There is no such ticket."}, "b": {"answer": "x"}}
    rows = R.reason([{"id": "a", "question": "Who owns ZZ-1?"}, {"id": "b", "question": "Badge printer?"}], brain, model,
                    R.LocalTools(box), log=lambda *_: None, on_done=seen.append)
    by = {r["id"]: r for r in rows}
    assert by["a"]["answer"] == "There is no such ticket." and by["a"]["steps"] == [
        {"gave_up": True, "finish": "too_long", "answer": "There is no such ticket.", "raw": ""}]  # the brain's answer, as it gave it
    assert by["b"]["answer"] == "done" and [s.get("tool") for s in by["b"]["steps"]] == ["search", None]
    assert [r["id"] for r in seen] == ["a", "b"]  # each row handed on as its conversation ends


def test_rag_turns_remind_once():
    calls = []

    def model(convs):
        calls.append(len(convs))
        return [{"text": "<think>\nhmm" if len(c) == 2 and "cut" in c[1]["content"] else
                 "Answer: Ava" if len(c) > 2 else "The owner is Ava.", "finish_reason": "length" if "cut" in c[1]["content"] and len(c) == 2 else "stop",
                 "prompt_tokens": 5, "output_tokens": 7} for c in convs]

    convs = [R.rag_conversation(q, [{"source": "jira", "title": "T", "text": "Owner: Ava"}]) for q in ("who? cut", "who?")]
    outs = R.rag_turns(convs, model)
    assert calls == [2, 2] and [R.rag_answer(o["text"], o["finish_reason"]) for o in outs] == ["Ava", "Ava"]
    assert outs[0]["retried"] == "length" and outs[0]["output_tokens"] == 14
    assert len(R.rag_blocks([{"source": "s", "title": "t", "text": "x" * 1000}] * 12)) == 12  # all 12 passages fit


class _Out:
    def __init__(self, text, n):
        self.outputs = [type("C", (), {"text": text, "token_ids": [0] * 3, "finish_reason": "stop"})()]
        self.prompt_token_ids = [0] * n


def _vllm(monkeypatch, fail_over=None):
    """A VLLMBackend over a stand-in engine: a prompt's tokens are its characters, and the engine fails a batch holding a
    prompt over ``fail_over`` characters as vLLM does."""
    import sys
    import types

    fake = types.ModuleType("vllm")
    fake.SamplingParams = lambda **kw: kw
    monkeypatch.setitem(sys.modules, "vllm", fake)
    b = R.VLLMBackend.__new__(R.VLLMBackend)
    b.max_model_len, b.max_tokens, b.thinks, b.kwargs, b.log, b._count_failed = 3000, 6144, True, {}, lambda *_: None, False
    b.tok = type("T", (), {"apply_chat_template": lambda self, conv, **kw: [0] * R._chars(conv)})()
    b.batches = []

    def chat(convs, sps, **kw):
        b.batches.append((len(convs), [sp["max_tokens"] for sp in sps]))
        if fail_over and any(R._chars(c) > fail_over for c in convs):
            raise ValueError("The decoder prompt (length 9) is longer than the maximum model length of 8.")
        return [_Out("ok\n</think>\n\n{}", R._chars(c)) for c in convs]

    b.llm = type("L", (), {"chat": staticmethod(chat)})()
    return b


def test_vllm_backend_guards_the_window(monkeypatch):
    b = _vllm(monkeypatch)
    convs = [[{"role": "user", "content": "x" * n}] for n in (100, 2000, 900)]
    outs = b(convs)
    assert [o["finish_reason"] for o in outs] == ["stop", "too_long", "stop"]  # 2000 leaves 984 tokens: under MIN_ROOM
    assert b.batches == [(2, [2884, 2084])]  # each request gets at most the room it has
    assert outs[0]["text"].startswith("<think>\n") and R.visible(outs[0]["text"]) == "{}"
    b = _vllm(monkeypatch, fail_over=500)  # the engine counts more than the template: find the prompt by halves
    outs = b([[{"role": "user", "content": "x" * n}] for n in (100, 600, 200, 300)])
    assert [o["finish_reason"] for o in outs] == ["stop", "too_long", "stop", "stop"]
