from __future__ import annotations

import argparse
import json
from pathlib import Path

from cie.eval import extract_facts as ef


def _doc(dsid: str, key: str, title: str, description: str, root_cause: str) -> dict:
    return {"key": key, "team": "engineering", "title": title, "status": "Done", "priority": "P1", "created_at": "2026-02-01",
            "creator": "Maya Chen", "assignee": "Asha Nair", "description": description, "root_cause": root_cause,
            "title_field_name": "title", "content_field_names": ["description", "root_cause"], "dataset_doc_uuid": dsid}


def _bench(tmp_path: Path) -> Path:
    root = tmp_path / "bench"
    src = root / "generated_data" / "sources" / "linear" / "eng"
    src.mkdir(parents=True)
    docs = [_doc("dsid_" + "a" * 32, "ENG-1", "Cap the eviction batch", "We decided to cap the eviction batch at 64 pages. "
                 "Rollout must complete by 2026-03-01.", "Eviction ran in the request path above 90% occupancy."),
            _doc("dsid_" + "b" * 32, "ENG-2", "Rotate the audit keys", "Key rotation pauses for 30 minutes during the backfill.",
                 "The forwarder dropped events on a 403 from KMS."),
            _doc("dsid_" + "c" * 32, "ENG-3", "Unrelated ticket", "The office plants are watered on Fridays.", "None.")]
    for i, d in enumerate(docs):
        (src / f"eng-{i}.json").write_text(json.dumps(d))
    qs = [{"question_id": "qst_0001", "question": "What cap was decided for eviction?", "question_type": "basic",
           "expected_doc_ids": ["dsid_" + "a" * 32],
           "answer_facts": ["The eviction batch is capped at 64 pages.", "Rollout must complete by 2026-03-01.",
                            "The answer must not mention the office plants."]},
          {"question_id": "qst_0002", "question": "Why were audit events dropped?", "question_type": "semantic",
           "expected_doc_ids": ["dsid_" + "b" * 32], "answer_facts": ["The forwarder dropped events on a 403 from KMS."]}]
    (root / "questions.jsonl").write_text("\n".join(json.dumps(q) for q in qs) + "\n")
    return root


def test_parse_facts_drops_preamble_none_and_repeats():
    text = ("Here are the facts stated in the passage:\n- The batch is capped at 64 pages.\n2. Rollout ends by 2026-03-01.\n"
            "* The batch is capped at 64 pages.\n- none\n\nFacts:\n• Asha Nair is the assignee.\n- - From: Tessa Morgan\n- - none")
    facts, counts = ef.parse_facts(text)
    assert facts == ["The batch is capped at 64 pages.", "Rollout ends by 2026-03-01.", "Asha Nair is the assignee.", "From: Tessa Morgan"]
    assert counts == {"preamble": 2, "duplicates": 1, "none": 2}
    assert "Asha" not in ef.INSTRUCTIONS, "no real-looking name in the instructions: small models copy it into their facts"


def test_prompt_puts_the_shared_instructions_before_the_passage():
    msgs = ef.conversation({"doc_title": "ENG-1", "source": "linear", "title": "Description", "text": "Cap at 64 pages."})
    user = msgs[1]["content"]
    assert msgs[0]["role"] == "system" and user.startswith(ef.INSTRUCTIONS)
    assert user.index("Cap at 64 pages.") > user.index("Document: ENG-1") > len(ef.INSTRUCTIONS) - 1


def test_numbers_must_come_from_the_passage():
    src = "The p99 target is 250 ms and the cap is 1,024 pages, due 2026-03-01."
    assert ef.grounded_numbers("The cap is 1024 pages.", src) is True
    assert ef.grounded_numbers("The p99 target is 250 ms.", src) is True
    assert ef.grounded_numbers("The cap is 2048 pages.", src) is False
    assert ef.grounded_numbers("Asha Nair owns it.", src) is None
    assert ef.wilson(0, 0) == (0.0, 0.0) and ef.wilson(5, 100)[0] < 0.05 < ef.wilson(5, 100)[1]


def _args(**kw) -> argparse.Namespace:
    base = {"limit": 0, "chunk": 2, "backend": "fake", "model": "fake", "max_tokens": 64, "gpu_mem": 0.9, "max_model_len": 4096,
            "max_num_seqs": None, "max_num_batched_tokens": None, "quantization": "none"}
    return argparse.Namespace(**{**base, **kw})


def _fake_model(convs):
    import time

    time.sleep(0.01)
    out = []
    for msgs in convs:
        passage = msgs[1]["content"].split("Passage:\n", 1)[1]
        lines = [s.strip() for s in passage.replace("\n", " ").split(". ") if len(s.strip()) > 8]
        out.append({"text": "Here are the facts:\n" + "\n".join(f"- {s.rstrip('.')}." for s in lines), "prompt_tokens": 100,
                    "output_tokens": 20 * len(lines), "finish_reason": "stop"})
    return out


def test_build_extract_score_and_judge_end_to_end(tmp_path):
    root = _bench(tmp_path)
    work = tmp_path / "work"
    info = ef.build_set(root, work, n_docs=None, seed=5, workers=1, log=lambda *a: None)
    assert info["documents"] == 3 and info["passages"] >= 3 and info["records"] >= 3
    passages = ef.load_jsonl(work / "passages.jsonl")
    assert {p["doc"] for p in passages} == {"dsid_" + c * 32 for c in "abc"} and all(p["doc_title"] for p in passages)

    out = work / "facts_fake.jsonl"
    calls = []
    meta = ef.run_extraction(work / "passages.jsonl", out, _args(limit=3), generate=lambda c: calls.append(len(c)) or _fake_model(c),
                             log=lambda *a: None)
    assert calls == [2, 1] and meta["summary"]["passages"] == 3
    meta = ef.run_extraction(work / "passages.jsonl", out, _args(), generate=lambda c: calls.append(len(c)) or _fake_model(c), log=lambda *a: None)
    rows = ef.load_jsonl(out)
    assert len(rows) == len(passages) == len({r["id"] for r in rows}), "a resumed run extracts only what is missing"
    assert sum(calls) == len(passages) and meta["summary"]["passages"] == len(passages)
    assert all(r["preamble"] == 1 for r in rows if r["facts"])

    rep = ef.score(work, root, [out], log=lambda *a: None)
    assert rep["answer_facts"] == 3, "the 'must not' fact is not an answer fact to look for"
    assert rep["checkable_in_passages"] == 3
    assert rep["kept"]["fake"]["in_a_passage_list"] == 3
    m = rep["methods"]["fake"]
    assert m["lines_with_a_number_not_in_the_passage"] == 0 and m["speed"]["passages"] == len(passages)
    assert m["hours_on_this_gpu"] is not None and (work / "report.md").exists()

    seen = []

    def fake_judge(prompt, kind):
        seen.append(prompt)
        assert kind == ("retention" if prompt.startswith("You check whether") else "correctness")
        if kind == "retention":
            return {"verdict": "covered", "note": "", "in": 10, "out": 2}
        return {"verdict": "wrong" if "2026-03-01" in prompt.split("Extracted fact:")[1] else "correct", "note": "", "in": 10, "out": 2}

    s = ef.judge(work, root, [out], model="gpt-5.4-mini", n_retention=3, n_lines=50, call=fake_judge, log=lambda *a: None)
    assert s["retention"]["fake"]["n"] == 3 and s["retention"]["fake"]["good_share"] == 1.0
    assert set(s["retention"]) == {"fake", ef.BASELINE, ef.CARD_FREE}
    assert s["calls"] > 0 and s["failed_share"] == 0.0
    c = s["correctness"]["fake"]
    assert c["counts"].get("wrong", 0) >= 1 and c["n"] == sum(len(r["facts"]) for r in rows)
    assert s["tokens"]["cost_usd"] is not None and s["judge_failed"] == 0


def test_a_failed_passage_is_asked_again_and_counted_once(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    ps = [{"id": f"d#{k}", "doc": "d", "k": k, "doc_title": "D", "source": "linear", "title": "", "text": f"Fact number {k} holds."} for k in range(3)]
    (work / "passages.jsonl").write_text("\n".join(json.dumps(p) for p in ps) + "\n")
    out = work / "facts_m.jsonl"

    def flaky(convs):
        return [{"text": "", "prompt_tokens": 0, "output_tokens": 0, "finish_reason": "error: HTTPError: 500"} if "number 1" in c[1]["content"]
                else {"text": "- " + c[1]["content"].rsplit("\n", 1)[1], "prompt_tokens": 5, "output_tokens": 5, "finish_reason": "stop"}
                for c in convs]

    ef.run_extraction(work / "passages.jsonl", out, _args(chunk=10), generate=flaky, log=lambda *a: None)
    asked = []
    ef.run_extraction(work / "passages.jsonl", out, _args(chunk=10), generate=lambda c: asked.extend(c) or _fake_model(c), log=lambda *a: None)
    assert len(asked) == 1 and "number 1" in asked[0][1]["content"], "only the failed passage is asked again"
    rows = ef.load_facts(out)
    assert len(rows) == 3 and not any(ef.failed(r) for r in rows)


def test_card_copy_numbers_one_by_one_and_resume_settings(tmp_path):
    card = {"type": "document", "text": "linear: ENG-1 — Cap the batch\nSummary: Cap it\nTags: cache\n\nsource: linear\nWe cap at 64 pages."}
    assert ef.card_without_passages(card) == "linear: ENG-1 — Cap the batch\nSummary: Cap it\nTags: cache"
    assert ef.card_without_passages({"type": "risk", "text": "a\n\nb"}) == "a\n\nb"
    src = "Silences of 15–30 seconds; due 2026-03-13."
    assert ef.grounded_numbers("Silences last 15-30 seconds.", src) is False, "the registered check compares the range as written"
    assert ef.grounded_numbers_each("Silences last 15-30 seconds.", src) is True
    assert ef.grounded_numbers_each("Due 2026-03-14.", src) is False

    work = tmp_path / "w"
    work.mkdir()
    (work / "passages.jsonl").write_text(json.dumps({"id": "d#0", "doc": "d", "k": 0, "doc_title": "D", "source": "x", "title": "",
                                                     "text": "Fact zero holds."}) + "\n")
    out = work / "facts_m.jsonl"
    ef.run_extraction(work / "passages.jsonl", out, _args(), generate=_fake_model, log=lambda *a: None)
    import pytest

    with pytest.raises(SystemExit):  # other settings must not resume into (and mix with) these facts
        ef.run_extraction(work / "passages.jsonl", out, _args(max_tokens=999, limit=0), generate=_fake_model, log=lambda *a: None)
    out.write_text(out.read_text() + '{"id": "d#1", "doc"')  # a write cut off by a disconnect
    assert [r["id"] for r in ef.load_facts(out)] == ["d#0"]


def test_a_judge_whose_calls_all_fail_reports_instead_of_crashing(tmp_path):
    root = _bench(tmp_path)
    work = tmp_path / "work"
    ef.build_set(root, work, n_docs=None, seed=5, workers=1, log=lambda *a: None)
    out = work / "facts_fake.jsonl"
    ef.run_extraction(work / "passages.jsonl", out, _args(), generate=_fake_model, log=lambda *a: None)
    (work / "judge.json").write_text("{}")
    ef.score(work, root, [out], log=lambda *a: None)
    assert not (work / "judge.json").exists(), "a judge of earlier facts never decides for new ones"

    def broken(prompt, kind):
        raise RuntimeError("insufficient_quota")

    s = ef.judge(work, root, [out], n_retention=3, n_lines=5, call=broken, log=lambda *a: None)
    assert s["failed_share"] == 1.0 and s["correctness"]["fake"]["good_share"] is None
    assert "–" in ef.judge_markdown(s)
