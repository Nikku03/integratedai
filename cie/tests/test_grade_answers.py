from __future__ import annotations

import pytest

from cie.eval import grade_answers as g


def _q(qid, correct, reasoning="ok", completeness=50.0, qtype="basic"):
    return {"question_id": qid, "answer_correct": correct, "correctness_reasoning": reasoning, "completeness_pct": completeness,
            "question_type": qtype}


def test_summary_counts_failed_judge_calls_and_splits_declined_and_audit_stages():
    results = {"questions": [_q("q1", True), _q("q2", False), _q("q3", False, reasoning=""), _q("q4", False, reasoning="", qtype="semantic"),
                             _q("q5", True, qtype="semantic")]}
    answers = [{"question_id": "q1", "answer": "a", "status": "answered"}, {"question_id": "q2", "answer": "b", "status": "answered"},
               {"question_id": "q3", "answer": "c", "status": "answered"},
               {"question_id": "q4", "answer": "", "status": "error"},  # no answer: wrong, but not a failed judge call
               {"question_id": "q5", "answer": "Insufficient evidence (model).", "status": "insufficient_evidence"}]
    audit = [{"question_id": "q1", "stage": "everything_reached_model"}, {"question_id": "q2", "stage": "everything_reached_model"},
             {"question_id": "q3", "stage": "right_document_wrong_part"}]
    s = g.summarise(results, answers, audit)
    assert s["overall"] == {"n": 5, "correct_pct": 40.0, "completeness_pct": 50.0}
    assert s["judge_failed"] == 1 and s["usable"] is False, "1 of 4 answered questions had no judgement: over 5%"
    assert s["declined"]["n"] == 1 and s["not_declined"]["n"] == 4
    assert s["by_question_type"]["semantic"]["n"] == 2
    assert s["by_audit_stage"]["everything_reached_model"] == {"n": 2, "correct_pct": 50.0, "completeness_pct": 50.0}
    assert s["by_audit_stage"]["not judged by the audit"]["n"] == 2


def test_judge_env_takes_the_claude_key_and_hides_this_package():
    env = g.judge_env("claude-sonnet-4-6", base={"ANTHROPIC_API_KEY": "k", "PYTHONPATH": "src", "PATH": "/bin"})
    assert env["LLM_API_KEY"] == "k" and env["LLM_PROVIDER"] == "anthropic" and env["LLM_MODEL_NAME"] == "claude-sonnet-4-6"
    assert "PYTHONPATH" not in env and env["PATH"] == "/bin"
    with pytest.raises(SystemExit):
        g.judge_env("claude-sonnet-4-6", base={"PATH": "/bin"})


def test_detail_file_sits_beside_the_answers_file(tmp_path):
    assert g.detail_file(tmp_path / "answers_x.jsonl") == tmp_path / "answers_x_detail.jsonl"
