from __future__ import annotations

from cie.eval.showcase import MEASURED_5K, to_html


def test_showcase_page_shows_answers_sources_and_the_change_and_escapes_text():
    rep = {"tenant": "t", "documents": 5000, "answers": "quoted from the evidence (no model)", "at": "now", "measured": MEASURED_5K,
           "ask": [{"question_id": "q1", "question": "What is <the> limit?", "type": "basic", "answer": "10 MiB [1].", "status": "answered",
                    "mode": "strict", "model": None, "citations": [{"n": 1, "source": "slack", "title": "uploads", "quote": "x"}],
                    "expected": "10 MiB", "facts": 1, "facts_found": 1, "seconds": 0.5, "evidence_items": 40, "documents_in_evidence": 12}],
           "change": {"label": "FICTIONAL, GENERATED project data", "seed": 1, "projects": 12, "project": "P", "task": "Can P deliver?",
                      "first_answers_seconds": 3.0, "before": {"summary": "P can deliver", "claims": [], "matches_expected": True},
                      "change": {"kind": "supplier delay", "notice": "S delays part X", "supplier": "S", "product": "X", "new_date": "2026-12-27",
                                 "orders": ["PO-1"]},
                      "after": {"summary": "P cannot deliver", "claims": ["M1 is at risk: X short"], "matches_expected": True},
                      "tasks_reopened": 1, "projects_affected": 1, "projects_missed": 0, "change_to_refreshed_answer_seconds": 2.0,
                      "without_routing": "P can deliver"}}
    page = to_html(rep)
    assert "What is &lt;the&gt; limit?" in page and "<the>" not in page
    assert "1 of 1 expected facts" in page and "slack" in page and "uploads" in page
    assert "FICTIONAL, GENERATED" in page and "P cannot deliver" in page and "M1 is at risk" in page
    assert "The published answer would still say" in page and "PO-1" in page
