"""The 5,000-document test, part B: drawing the questions, the measure and the rules."""

from __future__ import annotations

import json

from cie.eval import factbank_5k_b as F
from cie.eval.memory_test import _write_jsonl


def _q(i, group, kind, expected):
    return {"id": f"{kind}-{i:03d}", "group": group, "kind": kind, "question": f"q {kind} {i}", "expected": expected, "gold_docs": [f"d{kind}{i}"]}


def test_the_questions_keep_the_first_tests_mix_and_leave_out_used_and_flawed_ones():
    src = ([_q(i, "owners", "metadata", {"value": "Maya Chen"}) for i in range(40)]
           + [_q(i, "deadlines", "linear_due", {"date": "2026-03-01"}) for i in range(15)]
           + [_q(i, "deadlines", "action_due", {"date": "2026-03-02"}) for i in range(12)]
           + [_q(i, "lists", "linear_assignee", {"ids": ["ENG-1"], "id_kind": "key"}) for i in range(1, 9)])
    used_qs = [q for q in src if q["id"] in ("metadata-000", "linear_due-001")]
    used = {F.content(q) for q in used_qs}
    clash = {**src[5], "id": "linear_due-099"}  # another set numbers its questions anew: the id differs, the question is the same
    used.add(F.content(clash))
    qs = F.draw_questions(src, used, seed=3)
    assert len(qs) == 50
    assert [F._pool(q) for q in qs].count("owners") == 26 and [q["kind"] for q in qs].count("linear_due") == 10
    assert [q["kind"] for q in qs].count("action_due") == 8 and [q["group"] for q in qs].count("lists") == 6
    ids = {q["id"] for q in qs}
    assert not ids & {"metadata-000", "linear_due-001", src[5]["id"]} and not ids & F.FLAWED, "used (by content) and flawed questions are left out"
    assert F.draw_questions(src, used, seed=3) == qs


def test_the_measure_and_rules_compare_the_fact_bank_with_the_bank(tmp_path):
    qs = [{"id": "o1", "group": "owners", "kind": "metadata", "question": "who owns it?", "expected": {"value": "Maya Chen"}},
          {"id": "d1", "group": "deadlines", "kind": "linear_due", "question": "when is it due?", "expected": {"date": "2026-03-01"}},
          {"id": "l1", "group": "lists", "kind": "linear_assignee", "question": "list them", "expected": {"ids": ["ENG-11", "ENG-12"], "id_kind": "key"}}]
    w = tmp_path / "w"
    w.mkdir()
    _write_jsonl(w / "questions.jsonl", qs)
    far = "x" * 3000
    _write_jsonl(w / "evidence.jsonl", [{"id": "o1", "ms": {"bank": 400.0}, "plain-words": "Maya Chen", "plain": "Maya Chen", "bank": far + "Maya Chen"},
                                        {"id": "d1", "ms": {"bank": 300.0}, "plain-words": "", "plain": "", "bank": "due 2026-03-01"},
                                        {"id": "l1", "ms": {"bank": 200.0}, "plain-words": "", "plain": "", "bank": "ENG-11", "bank_error": "Timeout"}])
    _write_jsonl(w / "factbank.jsonl", [{"id": "o1", "answer": "Maya Chen", "evidence": "owner: Maya Chen", "ms": 700.0},
                                        {"id": "d1", "answer": "2026-03-01", "evidence": "due: 2026-03-01", "ms": 800.0},
                                        {"id": "l1", "answer": "ENG-11, ENG-12", "evidence": "ENG-11 ENG-12", "ms": 900.0}])
    (w / "evidence_info.json").write_text(json.dumps({"storage": {"bank_total": 900}}))
    (w / "factbank_build.json").write_text(json.dumps({"bytes": 600}))
    m = F.measure_b(w)
    assert m["reach"]["v1"]["2000"]["mean"] == 1.0 and m["reach"]["bank"]["2000"]["owners"] == 0.0, "the bank's answer is past 2,000 chars"
    assert m["reach"]["bank"]["24000"]["lists"] == 0.5 and m["checks"]["bank_errors"] == 1
    r = F.rules_b(m, None)
    assert r["1 not worse at the evidence budget (fact bank - bank >= -0.03 in every group, 24,000 chars)"]
    assert r["2 better near the top (fact bank - bank >= +0.10 on the mean, first 2,000 chars)"]
    assert not r["4 smaller (fact bank <= 1/3 of the bank's storage)"], "600 bytes is more than a third of 900"
    assert r["5 own answers hold at size (5,089 documents >= control - 0.05)"] is None
    assert m["ms"]["v1"]["median"] == 800.0 and m["checks"]["fact_bank_sources"] == {"v1": None}
    assert F.measure_b(w, exclude={"l1"})["questions"] == 2


def test_the_bank_evidence_collected_twice_is_compared(tmp_path):
    _write_jsonl(tmp_path / "evidence_pass1.jsonl", [{"id": "a", "bank": "x"}, {"id": "b", "bank": "y"}])
    _write_jsonl(tmp_path / "evidence.jsonl", [{"id": "a", "bank": "x"}, {"id": "b", "bank": "z"}])
    assert F.same_bank_evidence(tmp_path) == {"questions": 2, "different": ["b"]}
