"""The language-model judge (``cie.eval.judge``) with a scripted model: what it is shown, how its reply is read, an
unreadable reply asked for once more and never counted as wrong, the summary, and the comparison with people's labels."""

from __future__ import annotations

import csv
import json

from cie.eval import judge as J

ITEM = {"id": "q1", "arm": "reasoner", "question": "How long is the hiring pause?", "gold": "Three weeks, for non-critical roles.",
        "facts": ["The pause lasts three weeks.", "It applies to non-critical roles."], "answer": "It lasts three weeks."}


def test_what_the_judge_is_shown():
    conv = J.conversation(ITEM)
    assert conv[0]["role"] == "system" and '"facts": [true, false], "correct": true' in conv[0]["content"]
    user = conv[1]["content"]
    assert "Question: How long is the hiring pause?" in user and "Reference answer: Three weeks" in user
    assert "1. The pause lasts three weeks.\n2. It applies to non-critical roles." in user and user.endswith("It lasts three weeks.")
    assert "(none listed)" in J.conversation({**ITEM, "facts": []})[1]["content"]
    assert J.conversation({**ITEM, "answer": "x" * 9000})[1]["content"].count("x") == J.ANSWER_CHARS
    assert "(no answer)" in J.conversation({**ITEM, "answer": None})[1]["content"]


def test_reading_a_verdict():
    assert J.parse_verdict('{"facts": [true, false], "correct": true}', 2) == {"facts": [True, False], "correct": True}
    assert J.parse_verdict('<think>\n{"correct": false}\n</think>\nOk. {"facts": ["yes", "no"], "correct": "false"}', 2) == \
        {"facts": [True, False], "correct": False}
    assert J.parse_verdict('{"facts": [true], "correct": true}', 2) is None, "one true or false for each fact"
    assert J.parse_verdict('{"correct": true}', 0) == {"facts": [], "correct": True}
    assert J.parse_verdict("correct", 2) is None and J.parse_verdict('<think>\n{"correct": true}', 0) is None


def test_judge_asks_twice_and_never_counts_silence_as_wrong():
    calls = []

    def model(convs):
        calls.append(convs)
        if len(calls) == 1:
            return [{"text": '{"facts": [true, false], "correct": true}'}, {"text": "hmm"}, {"text": "no idea"}]
        return [{"text": '{"facts": [false, false], "correct": false}'}, {"text": "still no idea"}]

    items = [ITEM, {**ITEM, "id": "q2", "answer": "Two days."}, {**ITEM, "id": "q3"}]
    out = J.judge(items, model, log=lambda *_: None)
    assert out[0] == {"id": "q1", "arm": "reasoner", "correct": True, "facts": [True, False], "completeness": 0.5, "failed": False}
    assert out[1]["correct"] is False and out[1]["completeness"] == 0.0 and not out[1]["failed"]
    assert out[2] == {"id": "q3", "arm": "reasoner", "correct": None, "facts": None, "completeness": None, "failed": True}
    assert len(calls) == 2 and len(calls[1]) == 2 and calls[1][0][-1]["content"] == J.AGAIN
    rep = J.summarise(out, {"q1": "prose", "q2": "prose", "q3": "basic"})
    assert rep["all"] == {"answers": 3, "failed": 1, "correct": 0.5, "completeness": 0.25}
    assert rep["by_group"]["basic"] == {"answers": 1, "failed": 1, "correct": None, "completeness": None}
    assert J.judge([], model) == [] and J.judge([{**ITEM, "facts": []}], lambda c: [{"text": '{"correct": true}'}], log=lambda *_: None)[0][
        "completeness"] == 1.0


def test_items_sample_and_agreement(tmp_path):
    qs = [{"id": "a", "question": "Q a?", "expected": {"gold": "G", "facts": ["f1"]}},
          {"id": "b", "question": "Q b?", "expected": {"facts": ["f2", "f3"]}},
          {"id": "c", "question": "Q c?", "expected": {"not_found": True}},
          {"id": "d", "question": "Q d?", "expected": {"value": "x"}}]
    rows = {i: {"id": i, "answer": f"answer {i}", **({"support": "a quote"} if i == "b" else {})} for i in "abcd"}
    items = J.items_of(qs, rows, "rag")
    assert [x["id"] for x in items] == ["a", "b", "c"], "a question with no reference to judge by is left out"
    assert items[1]["answer"] == "answer b\na quote" and items[1]["gold"] == "" and items[2]["gold"].endswith("not found.")
    assert J.items_of(qs, rows, "rag", text=lambda q, r: "only this")[0]["answer"] == "only this"
    more = items + [{**x, "arm": "reasoner"} for x in items]
    picked = J.sample(more, 4, seed=1)
    assert len(picked) == 4 and {r["arm"] for r in picked} == {"rag", "reasoner"} and all(r["correct (yes/no)"] == "" for r in picked)
    assert sorted(r["arm"] for r in picked).count("rag") == 2, "drawn evenly over the arms"
    assert len(J.sample(more, 99)) == 6
    verdicts = [{"id": "a", "arm": "rag", "correct": True, "failed": False}, {"id": "b", "arm": "rag", "correct": False, "failed": False},
                {"id": "c", "arm": "rag", "correct": True, "failed": False}, {"id": "a", "arm": "reasoner", "correct": None, "failed": True}]
    labels = [{"id": "a", "arm": "rag", "correct (yes/no)": "yes"}, {"id": "b", "arm": "rag", "correct (yes/no)": "no"},
              {"id": "c", "arm": "rag", "correct (yes/no)": "No"}, {"id": "a", "arm": "reasoner", "correct (yes/no)": "yes"},
              {"id": "b", "arm": "reasoner", "correct (yes/no)": ""}]
    rep = J.agreement(labels, verdicts)
    assert rep["answers"] == 3 and rep["agree"] == 0.667 and rep["both_right"] == 1 and rep["both_wrong"] == 1
    assert rep["judge_right_person_wrong"] == 1 and rep["judge_wrong_person_right"] == 0 and rep["kappa"] == 0.4
    assert J.agreement([], verdicts) == {"answers": 0}
    (tmp_path / "q.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))
    (tmp_path / "rag.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows.values()))
    J.main(["sample", "--questions", str(tmp_path / "q.jsonl"), "--answers", str(tmp_path / "rag.jsonl"), "--n", "2", "--out", str(tmp_path / "l.csv")])
    with open(tmp_path / "l.csv", newline="") as f:
        got = list(csv.DictReader(f))
    assert len(got) == 2 and set(got[0]) == set(J.FIELDS) and got[0]["arm"] == "rag"
    (tmp_path / "v.jsonl").write_text("".join(json.dumps(v) + "\n" for v in verdicts))
    for r in got:
        r["correct (yes/no)"] = "yes"
    with open(tmp_path / "l.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=J.FIELDS)
        w.writeheader()
        w.writerows(got)
    assert J.main(["agreement", "--labels", str(tmp_path / "l.csv"), "--verdicts", str(tmp_path / "v.jsonl")])["answers"] == 2
