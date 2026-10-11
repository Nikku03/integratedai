"""Messy wordings of the round-2 test's generated questions (``cie.eval.brain2_messy``): what a rewrite must keep, the
rewriters' batches, and the messy work folder."""

from __future__ import annotations

import json

import pytest

from cie.eval import brain2_messy as M


def test_anchors():
    a = M.anchors('Who owns the Google Drive document "Q3 Roadmap Draft"?')
    assert a["tokens"] == ["Google", "Drive"] and a["quotes"] == [["q3", "roadmap", "draft"]]
    a = M.anchors("Of ENG-9053 and ENG-71234, which deadline comes first?")
    assert a["tokens"] == ["ENG-9053", "ENG-71234"]
    assert M.anchors("When was PR #4821 merged?")["tokens"] == ["4821", "PR"]
    assert "Rae" in M.anchors("Which Jira tickets are assigned to Rae Ruiz? Give the ticket keys.")["tokens"]


@pytest.mark.parametrize("original, rewrite, why", [
    ("How many Jira tickets have priority P1?", "hey how many p1 tickets do we have in jira rn?", None),
    ('Who owns the Google Drive document "Q3 Roadmap Draft"?', "who owns the q3 roadmap doc in google drive?", None),
    ("When was PR #4821 merged?", "pr 4821 - when did that merge?", None),
    ("Of ENG-9053 and ENG-71234, which deadline comes first?", "eng 9053 vs eng 71234, which one's due sooner?", None),
    ("When was PR #4821 merged?", "when did that pr merge?", "drops '4821'"),
    ('Who owns the Google Drive document "Q3 Roadmap Draft"?', "who owns the roadmap doc in google drive?", "drops a quoted title"),
    ("How many Jira tickets have priority P1?", "how many p1 tickets in jira", "not one question"),
    ("How many Jira tickets have priority P1?", "how many p1 tickets in jira? and p2?", "not one question"),
    ("How many Jira tickets have priority P1?", "", "no rewrite"),
])
def test_why_rejected(original, rewrite, why):
    assert M.why_rejected(original, rewrite) == why


def test_packets_collect_and_folder(tmp_path):
    w = tmp_path / "t5k"
    w.mkdir()
    qs = [{"id": "jira_priority-1", "kind": "jira_priority", "family": "single", "question": "What priority does Jira ticket SUP-1 have?",
           "expected": {"value": "P1"}},
          {"id": "count1_jira-2", "kind": "count1_jira", "family": "counts", "question": "How many Jira tickets have priority P2?",
           "expected": {"value": "3"}},
          {"id": "prose-912-001", "kind": "prose", "family": "prose", "question": "hey whats the retry limit on webhooks?",
           "expected": {"facts": ["5 retries"]}}]
    (w / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))
    (w / "haystack.json").write_text("{}")
    rep = M.write_packets(w, tmp_path / "b", per=40)
    assert rep == {"questions": 2, "batches": ["t5k_messy_b00"]}
    batch = json.loads((tmp_path / "b" / "t5k_messy_b00.json").read_text())
    assert [p["packet_id"] for p in batch["packets"]] == ["jira_priority-1", "count1_jira-2"]
    assert all(set(p) == {"packet_id", "question"} for p in batch["packets"]), "the rewriters see the question text alone"
    (tmp_path / "o").mkdir()
    (tmp_path / "o" / "t5k_messy_b00.jsonl").write_text(
        json.dumps({"packet_id": "jira_priority-1", "question": "quick q - whats the priority on SUP-1 in jira?"}) + "\n"
        + json.dumps({"packet_id": "count1_jira-2", "question": "how many tickets are p2?"}) + "\n")
    out, rep = M.collect(w, tmp_path / "b", tmp_path / "o")
    assert [q["id"] for q in out] == ["jira_priority-1", "prose-912-001"]
    assert out[0]["question"].startswith("quick q") and out[0]["clean_question"] == qs[0]["question"] and out[0]["expected"] == {"value": "P1"}
    assert rep["kept"] == 1 and rep["rejected"] == {"drops": 1}
    M.messy_folder(w, tmp_path / "t5k_messy", out)
    assert (tmp_path / "t5k_messy" / "haystack.json").is_symlink()
    assert len((tmp_path / "t5k_messy" / "questions.jsonl").read_text().splitlines()) == 2
