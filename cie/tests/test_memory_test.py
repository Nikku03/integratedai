from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cie.eval import memory_test as mt


def test_action_items_in_three_layouts_and_no_label_as_owner():
    raw = {"action_items": [
        "Olga Petrov - Provide SOC 2 report access and evidence index - Due: 2026-02-05",
        "Liam Chen | Prepare pricing worksheet with reserved vs burst | due: 2028-11-17",
        "Owner: Miguel Ramos | Item: Prepare Terraform module + IP planning worksheet | Due: 2025-09-19",
        "Samir: send benchmark spreadsheet and access instructions (due 2025-10-08)",
        "Aisha Khan (Pinecrest): Consolidate internal redlines - target 2026-11-16",  # no due date: left out
        "Owner | Item: Share CIDR worksheet | Due: 2025-09-20",  # a label, not a person
        {"owner": "x"}]}
    assert mt.action_items(raw) == [
        ("Olga Petrov", "Provide SOC 2 report access and evidence index", "2026-02-05"),
        ("Liam Chen", "Prepare pricing worksheet with reserved vs burst", "2028-11-17"),
        ("Miguel Ramos", "Prepare Terraform module + IP planning worksheet", "2025-09-19"),
        ("Samir", "send benchmark spreadsheet and access instructions", "2025-10-08")]


def test_expected_value_is_the_field_the_gold_answer_names():
    raw = {"key": "SUP-1", "assignee": "Liam Chen", "status": "Triage", "path": "users/edge-guard-keeper", "title": "Edge Guard Keeper",
           "forecast_close_month": "2026-05", "messages": "x" * 90 + " incident INC-2034-110 opened on 2026-04-08 " + "y" * 40}
    assert mt.expected_value("Who is assigned to the ticket?", "The ticket is assigned to Liam Chen.", raw) == {"value": "Liam Chen"}
    # the title wins over the path when the gold answer names both
    assert mt.expected_value("Which doc is it?", 'It is "Edge Guard Keeper" (users/edge-guard-keeper).', raw, "Edge Guard Keeper")["value"] == "Edge Guard Keeper"
    assert mt.expected_value("What month is the close forecasted for?", "The close is forecast for May 2026.", raw) == \
        {"value": "May 2026", "alts": ["2026-05"]}
    assert mt.expected_value("Which incident did the bot open?", "The bot created incident INC-2034-110.", raw)["value"] == "INC-2034-110"
    # a value the question already names is not the answer
    assert mt.expected_value("Is the ticket assigned to Liam Chen in Triage?", "Liam Chen has it in Triage.", raw) is None


def _doc(dsid, source, title, raw):
    return {"dsid": dsid, "source": source, "title": title, "raw": raw}


def test_generated_questions_are_computed_from_the_fields():
    docs = [_doc("d1", "linear", "Cap eviction", {"key": "ENG-1", "assignee": "Asha Nair", "status": "In Progress", "due_date": "2026-03-01"}),
            _doc("d2", "linear", "Rotate keys", {"key": "ENG-2", "assignee": "Asha Nair", "status": "Done", "due_date": "2026-03-05"}),
            _doc("d3", "linear", "Plants", {"key": "ENG-3", "assignee": "Ben Ortiz", "status": "Done", "due_date": "2026-03-09"}),
            _doc("d4", "linear", "Duplicate key", {"key": "ENG-3", "assignee": "Ben Ortiz", "due_date": "2026-03-09"}),  # ENG-3 twice: left out
            _doc("d5", "github", "Probe", {"pr_number": "101", "author": "Maya Chen"}),
            _doc("d6", "github", "Exporter", {"pr_number": "102", "author": "Maya Chen"}),
            _doc("d7", "fireflies", "Kickoff with Helio", {"action_items": ["Olga Petrov - Send the audit log taxonomy - Due: 2026-02-05"]})]
    qs = {q["kind"]: q for q in mt.generate_questions(docs, caps={"linear_due": 5, "action_due": 5})}
    assert qs["linear_assignee"]["question"] == "List every Linear issue assigned to Asha Nair. Give the issue keys."
    assert qs["linear_assignee"]["expected"] == {"ids": ["ENG-1", "ENG-2"], "id_kind": "key"}
    assert qs["github_author"]["expected"] == {"ids": ["101", "102"], "id_kind": "pr"} and qs["github_author"]["gold_docs"] == ["d5", "d6"]
    assert qs["action_due"]["expected"] == {"date": "2026-02-05"} and "Olga Petrov" in qs["action_due"]["question"]
    due = [q for q in mt.generate_questions(docs, caps={"linear_due": 5}) if q["kind"] == "linear_due"]
    assert {q["expected"]["date"] for q in due} == {"2026-03-01", "2026-03-05"}, "ENG-3 has a duplicate key"
    assert "linear_status" not in qs, "a one-issue status group is no list"


def test_answers_are_checked_on_the_final_line():
    date_q = {"group": "deadlines", "expected": {"date": "2026-03-05"}}
    assert mt.check(date_q, "It is due on March 5, 2026.\nAnswer: 2026-03-05")["correct"] is True
    assert mt.check(date_q, "Answer: 5 March 2026")["correct"] is True
    assert mt.check(date_q, "Answer: 2026-03-05 or 2026-03-09")["correct"] is False, "hedging between dates is wrong"
    list_q = {"group": "lists", "expected": {"ids": ["ENG-1", "ENG-2"], "id_kind": "key"}}
    c = mt.check(list_q, "ENG-9 depends on ENG-1.\nAnswer: ENG-1, ENG-7")
    assert (c["precision"], c["recall"], c["f1"], c["correct"]) == (0.5, 0.5, 0.5, False)
    assert mt.check({"group": "lists", "expected": {"ids": ["101", "24612"], "id_kind": "pr"}}, "Answer: #101, #24612")["correct"] is True
    owner = {"group": "owners", "expected": {"value": "May 2026", "alts": ["2026-05"]}}
    assert mt.check(owner, "Answer: 2026-05")["correct"] is True
    assert mt.check({"group": "owners", "expected": {"value": "Liam O'Connor"}}, "Answer: Liam OConnor")["correct"] is True
    nf = mt.check({"group": "conflicts", "expected": {}}, "Answer: not found")
    assert nf == {"not_found": True, "correct": None}


def test_plan_is_checked_against_known_fields():
    fields = {"linear": {"title", "assignee", "due_date"}, "action_items": {"owner", "due", "text", "meeting"}}
    p = mt.parse_plan('Sure:\n```json\n{"source": "linear", "where": [{"field": "assignee", "op": "=", "value": "Asha Nair"}, '
                      '{"field": "drop table", "op": "=", "value": "x"}, {"field": "due_date", "op": "~", "value": "x"}]}\n```', fields)
    assert p == {"source": "linear", "where": [{"field": "assignee", "op": "=", "value": "Asha Nair"}], "title": ""}
    assert mt.parse_plan('Lookup: {"source": "linear", "where": [], "title": "Cap eviction"} (the {title} narrows it)', fields) == \
        {"source": "linear", "where": [], "title": "Cap eviction"}, "text with braces after the JSON"
    assert mt.parse_plan('{"source": null}', fields) is None
    assert mt.parse_plan('{"source": "jira", "where": [{"field": "key", "op": "=", "value": "X"}]}', fields) is None
    assert mt.parse_plan('{"source": "linear", "where": []}', fields) is None, "nothing to look up"


def test_fusion_and_budget():
    assert mt.rrf([["a", "b", "c"], ["c", "a"]])[:2] == ["a", "c"]
    blocks, used = mt.fill([("h1", "x" * 50), ("h2", "y" * 50), ("h3", "z" * 50)], budget=130)
    assert len(blocks) == 2 and blocks[1].startswith("[2] h2") and used <= 130
    assert mt.fill([("h", "x" * 500)], budget=100)[0][0] == ("[1] h\n" + "x" * 500)[:100], "the first block is cut, not dropped"


def test_rules_need_the_thresholds_and_report_undecided_without_results():
    def diffs(lookup: dict, bank_mean: float | None, facts: dict, plain_mean: float):
        mk = lambda d: {g: ({"diff": v} if v is not None else None) for g, v in d.items()}  # noqa: E731
        return {"bank+lookup - plain": mk(lookup), "bank - plain": {"mean": {"diff": bank_mean} if bank_mean is not None else None},
                "bank+facts - bank": {**mk(facts), "mean": {"diff": sum(v for v in facts.values() if v is not None) / 4}},
                "plain - plain-words": {"mean": {"diff": plain_mean}}}

    c = mt.criteria(diffs({"owners": 0.0, "deadlines": 0.02, "lists": 0.25, "conflicts": -0.02}, 0.01,
                          {"owners": 0.1, "deadlines": 0.1, "lists": 0.1, "conflicts": -0.04}, 0.05))
    assert list(c.values()) == [True, False, False, True], "facts lose more than 0.03 on conflicts"
    c = mt.criteria(diffs({"owners": -0.05, "deadlines": 0.3, "lists": 0.3, "conflicts": None}, None,
                          {"owners": 0.1, "deadlines": 0.1, "lists": 0.1, "conflicts": None}, 0.0))
    assert c["1. structured lookup earns its place"] is False, "owners fell by more than 0.03 (no judge: the conflicts guard is skipped)"
    assert c["2. the bank's search earns its place"] is None, "no result, no decision"
    assert c["3. the Llama facts earn their place"] is True


def _write(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))


def _bench(tmp_path: Path) -> Path:
    """A tiny fictional company: four Linear issues, two pull requests, a meeting with action items, a drive document."""
    root = tmp_path / "bench"
    src = root / "generated_data" / "sources"
    ids = {k: "dsid_" + c * 32 for k, c in zip(["l1", "l2", "l3", "l4", "g1", "g2", "m1", "d1"], "abcdef01", strict=True)}
    lin = [("l1", "ENG-11", "Cap the eviction batch at 64 pages", "Asha Nair", "In Progress", "2026-03-01"),
           ("l2", "ENG-12", "Rotate the audit forwarder keys", "Asha Nair", "Done", "2026-03-05"),
           ("l3", "ENG-13", "Water the office plants", "Ben Ortiz", "Planned", "2026-04-20"),
           ("l4", "ENG-14", "Retire the legacy billing exporter", "Ben Ortiz", "Planned", "2026-04-28")]
    for k, key, title, who, status, due in lin:
        _write(src / "linear" / "eng" / f"{key}.json", {"dataset_doc_uuid": ids[k], "key": key, "title": title, "assignee": who, "status": status,
                                                         "due_date": due, "project": "Runtime", "description": f"{title}. " * 30})
    for k, n, title in (("g1", "101", "Add the sync latency probe"), ("g2", "102", "Export waterfall timelines")):
        _write(src / "github" / f"pr-{n}.json", {"dataset_doc_uuid": ids[k], "repo": "redwood", "pr_number": n, "title": title, "author": "Maya Chen",
                                                 "state": "merged", "description": f"{title} for the perf dashboards. " * 20})
    _write(src / "fireflies" / "kickoff.json", {"dataset_doc_uuid": ids["m1"], "meeting_id": "ff-1", "title": "Kickoff with Helio Finance",
                                                "redwood_owner": "Olga Petrov", "recorded_at": "2026-02-03T18:00:12Z",
                                                "action_items": ["Olga Petrov - Send the audit log event taxonomy - Due: 2026-02-05",
                                                                 "Naomi Feldman - Confirm the retention defaults in writing - Due: 2026-02-09"],
                                                "transcript": "We reviewed the security packet and the audit log exports. " * 20})
    _write(src / "google_drive" / "users" / "plan.json", {"dataset_doc_uuid": ids["d1"], "title": "Headcount ramp model", "owner": "Maya Chen",
                                                          "drive_area": "finance", "status": "draft",
                                                          "content": "Runway sensitivity to headcount and price changes. " * 30})
    (root / "questions.jsonl").write_text(json.dumps({"question_id": "qst_0001", "question_type": "conflicting_info",
                                                      "question": "What batch cap did the eviction issue settle on?", "expected_doc_ids": [ids["l1"]],
                                                      "gold_answer": "64 pages (an earlier draft said 32)."}) + "\n")
    (root / "extra_questions.jsonl").write_text(json.dumps({"question_id": "qst_0001", "question_type": "metadata",
                                                            "question": "Who owns the finance draft about headcount ramping?",
                                                            "expected_doc_ids": [ids["d1"]], "gold_answer": "It is owned by Maya Chen."}) + "\n")
    return root


@pytest.mark.db
def test_memory_test_end_to_end_with_a_stand_in_model(session, tmp_path, monkeypatch):
    from cie.core.settings import get_settings
    from cie.memory import facts as mf
    from cie.memory.embeddings import HashedEmbedding
    from cie.retrieval import bm25
    from tests.conftest import TEST_URL
    from tests.test_extract_facts import _fake_model

    session.commit()
    monkeypatch.setattr(get_settings(), "database_url", TEST_URL)
    monkeypatch.setattr(get_settings(), "lexical_index_dir", tmp_path / "lexical")
    bm25._readers.clear()
    root, work = _bench(tmp_path), tmp_path / "work"
    counts = mt.build_questions(root, work, n_docs=None, log=lambda *a: None)
    assert counts["documents"] == 8 and counts["owners_with_expected_value"] == 1
    assert counts["by_kind"] == {"metadata": 1, "conflicting_info": 1, "linear_due": 4, "action_due": 2, "linear_assignee": 2,
                                 "linear_due_window": 2, "github_author": 1}
    ld = mt.load_bank(work, workers=1, reuse="", log=lambda *a: None)
    assert mt.load_bank(work, reuse="auto", log=lambda *a: None)["tenant_id"] == ld["tenant_id"], "the same haystack is found again"
    plain = mt.build_plain(work, HashedEmbedding(384), log=lambda *a: None)
    assert plain["documents"] == 8 and plain["vector_bytes"] > 0
    # the notebook's route for the facts: the bank's passages to a file, the facts to a file, then into the bank
    from cie.eval import extract_facts as ef
    from tests.test_extract_facts import _args

    fp = mt.facts_passages(work, workers=1, log=lambda *a: None)
    ef.run_extraction(work / "facts" / "passages.jsonl", work / "facts" / "facts_fake.jsonl", _args(), generate=_fake_model, log=lambda *a: None)
    conn = mf._connect(TEST_URL)
    imp = mf.import_file(conn, mf.tenant_id_of(conn, ld["tenant_name"]), work / "facts", work / "facts" / "facts_fake.jsonl", log=lambda *a: None)
    assert imp["matched"] == imp["added"] == fp["passages"] and not imp.get("stale") and not imp.get("no_such_section"), \
        "every passage of the file is a section of the bank, with the same text"
    args = argparse.Namespace(arms=None, backend="fake", facts_signature=None, chunk=8, max_tokens=100, local=None)
    meta = mt.run(work, args, log=lambda *a: None)
    assert meta["arms"] == list(mt.ARMS)
    plans = {p["id"]: p for p in mt._jsonl(work / "plans.jsonl")}
    asha = next(q for q in mt._jsonl(work / "questions.jsonl") if q["kind"] == "linear_assignee" and "Asha" in q["question"])
    assert plans[asha["id"]]["found"] == 2 and all("Asha Nair" in b for b in plans[asha["id"]]["blocks"])
    assert len(mt._jsonl(work / "answers.jsonl")) == counts["questions"] * len(mt.ARMS)
    assert mt.run(work, args, log=lambda *a: None)["answer_seconds"] < 5, "a second run asks nothing again"
    calls = []

    def fake_judge(prompt, kind):
        calls.append(kind)
        return {"verdict": "partly", "note": "", "in": 10, "out": 2}

    j = mt.judge(work, call=fake_judge, log=lambda *a: None)
    assert j["calls"] == 2 * len(mt.ARMS) and set(calls) == {"answer"}, "the owners and conflicts answers of every arm"
    rep = mt.score(work, log=lambda *a: None)
    assert set(rep["arms"]) == set(mt.ARMS)
    look = rep["arms"]["bank+lookup"]
    assert look["by_kind"]["linear_assignee"]["score"] > 0 and look["conflicts"]["score"] == 0.5
    assert set(rep["criteria"]) == {"1. structured lookup earns its place", "2. the bank's search earns its place",
                                    "3. the Llama facts earn their place", "4. vector search earns its place in plain search"}
    assert rep["storage"]["bank_total"] > rep["storage"]["plain_words_total"] > 0
    assert "Pre-registered rules" in (work / "report.md").read_text()
