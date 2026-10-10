"""Packets for blind question writers and the checks on what they write: the deal, the keys kept apart, and collect."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from cie.eval import brain_questions as B
from cie.eval import brain_writers as W
from cie.eval.brain_test import load_descriptive

LONG = ("The rollout uses a canary of 5 percent for two days before the fleet upgrade. The decision was to cap max_batch_size "
        "at 48 on the A100 pool, and the alert threshold for p99 latency is 850 ms. Owners review the dashboard every Monday. ")


def _rec(dsid, title, body="Short note.", **meta):
    return {"dataset_doc_uuid": dsid, "title": title, "content_field_names": ["content"], "content": body, **meta}


def _docs():
    return [
        ("google_drive", _rec("g1", "Runway model for the Q3 board deck", LONG * 4, owner="Maya Chen", status="draft",
                              created_at="2026-01-05")),
        ("confluence", _rec("c1", "Incident review process for the serving fleet", LONG * 4, author="Ava Lee", space="OPS",
                            last_updated="2026-02-11")),
        ("hubspot", _rec("h1", "Fernfield Connect", LONG, owner="Omar Singh", stage="procurement", forecast_close_month="2026-05",
                         se_assigned="Priya Nair")),
        ("jira", _rec("j1", "Intermittent 5xx on the edge proxy after a deploy", LONG * 4, key="SUP-101", status="In Progress",
                      priority="P1", reporter="Liam Chen", assignee="Ethan Cole", customer_company="Acme Analytics",
                      sla_due_at="2026-03-12")),
        ("linear", _rec("l1", "Rotate the KMS keys for private deployments", LONG * 4, key="ENG-12", status="Planned",
                        priority="P2", assignee="Diego Alvarez", creator="Asha Menon", project="Private Deploy Hardening",
                        due_date="2026-04-01")),
        ("github", _rec("p1", "add-tenant-isolation-to-the-rag-starter", LONG * 4, pr_number=345, author="Claire Huang",
                        repo="runtime", merged_at="2026-03-03")),
        ("fireflies", _rec("f1", "Pilot kickoff and success criteria review", LONG * 4, redwood_owner="Nina Patel",
                           customer_company="Sequoia Retail", recorded_at="2026-02-20")),
        ("slack", _rec("s1", "people-ops", LONG * 4, channel="people-ops")),
        ("gmail", _rec("m1", "Re: trial credits for Novamed", LONG * 4, mailbox_owner="alex_martinez")),
    ]


def _work(tmp_path, docs=None, zone="train", questions=None):
    root = tmp_path / "bench"
    sources = root / "generated_data" / "sources"
    index = {}
    for src, rec in docs or _docs():
        rel = f"{src}/{rec['dataset_doc_uuid']}.json"
        (sources / src).mkdir(parents=True, exist_ok=True)
        (sources / rel).write_text(json.dumps(rec))
        index[rec["dataset_doc_uuid"]] = rel
    work = tmp_path / "work"
    work.mkdir()
    (work / "index.json").write_text(json.dumps({"root": str(sources), "index": index}))
    (work / "haystack.json").write_text(json.dumps({"root": str(root), "dsids": sorted(index), "zone": zone}))
    if questions is not None:
        (work / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in questions))
    return work


def test_descriptive_packets_ask_one_field_per_document_and_keep_the_answer_in_the_key(tmp_path):
    ps, ks, rep = W.packets(_work(tmp_path), "descriptive", 20, seed=3)
    assert len(ps) == len(ks) == 7 and rep["packets"] == 7, "one packet per document; no Slack or Gmail packet"
    assert {p["source"] for p in ps} == set(W.FIELDS) and {k["dsid"] for k in ks} == {"g1", "c1", "h1", "j1", "l1", "p1", "f1"}
    for p, k in zip(ps, ks, strict=True):
        assert p["packet_id"] == k["packet_id"] and set(p) == {"packet_id", "kind", "source", "system", "field", "text", "instruction"}
        assert k["field"] in W.FIELDS[k["source"]] and p["field"] == W.FIELD_WORDS[k["field"]] == k["field_words"]
        assert not any(line.startswith(k["field"] + ":") for line in p["text"].splitlines()), "the asked field's line is left out"
        assert p["text"].startswith(k["title"]) and p["field"] in p["instruction"] and "<field>" not in p["instruction"]
        assert k["expected"] == B._expected(json.loads((tmp_path / "bench/generated_data/sources" / f"{k['source']}/{k['dsid']}.json")
                                                       .read_text())[k["field"]], W.FIELDS[k["source"]][k["field"]])[0]
    assert "dsid" not in json.dumps(ps)
    again, _, _ = W.packets(_work(tmp_path / "b"), "descriptive", 20, seed=3)
    assert [(p["source"], p["field"]) for p in again] == [(p["source"], p["field"]) for p in ps], "seeded"


def test_descriptive_packets_spread_over_sources_and_fields_and_prefer_unused_documents(tmp_path):
    drive = [("google_drive", _rec(f"g{i}", f"Drive plan number {i} for the platform team", owner="Maya Chen",
                                   status="draft", created_at="2026-01-05")) for i in range(6)]
    linear = [("linear", _rec(f"l{i}", f"Linear issue number {i} about rate limits", key=f"ENG-{20 + i}", status="Planned",
                              priority="P2", assignee="Diego Alvarez", creator="Asha Menon", project="Gateway",
                              due_date="2026-04-01")) for i in range(6)]
    ps, ks, _ = W.packets(_work(tmp_path, drive + linear), "descriptive", 4, seed=1)
    assert Counter(k["source"] for k in ks) == {"google_drive": 2, "linear": 2}
    assert all(len({k["field"] for k in ks if k["source"] == s}) == 2 for s in ("google_drive", "linear")), "fields take turns"
    used = [{"id": "q1", "gold_docs": [f"g{i}" for i in range(5)]}]
    _, ks2, rep = W.packets(_work(tmp_path / "u", drive + linear, questions=used), "descriptive", 4, seed=1)
    assert [k["dsid"] for k in ks2 if k["source"] == "google_drive"] == ["g5"] and rep["used_by_questions"] == 0, \
        "a used document is dealt only when no unused one is left in any source or field"
    _, ks4, rep4 = W.packets(_work(tmp_path / "v", drive + linear, questions=used), "descriptive", 9, seed=1)
    assert len(ks4) == 9 and rep4["used_by_questions"] == 2 and {k["dsid"] for k in ks4} >= {"g5"} | {f"l{i}" for i in range(6)}
    assert len({k["dsid"] for k in ks4}) == 9
    _, ks3, rep3 = W.packets(_work(tmp_path / "a", drive + linear), "descriptive", 20, seed=1, avoid={"g0", "l0"})
    assert len(ks3) == 10 and not {"g0", "l0"} & {k["dsid"] for k in ks3} and rep3["avoided"] == 2


def test_descriptive_candidates_leave_out_shared_titles_values_inside_others_and_values_in_the_title(tmp_path):
    docs = [("google_drive", _rec("g1", "Shared title for two docs", owner="Maya Chen", status="draft")),
            ("google_drive", _rec("g2", "Shared title for two docs", owner="Ava Lee", status="final")),
            ("google_drive", _rec("g3", "Draft hiring plan for support", owner="Ava Lee", status="draft")),
            ("google_drive", _rec("g4", "Runway notes from the March 5 offsite", owner="Ava Lee", created_at="2026-03-05")),
            ("linear", _rec("l1", "Linear issue about the gateway", key="ENG-11", project="gateway")),
            ("linear", _rec("l2", "Linear issue about rate limits", key="ENG-12", project="gateway-v2"))]
    pools, aside = W.descriptive_candidates(W.documents(_work(tmp_path, docs)))
    assert [c["doc"]["dsid"] for c in pools["google_drive"]["owner"]] == ["g3", "g4"]
    assert pools["google_drive"]["status"] == [] and [c["doc"]["dsid"] for c in pools["linear"]["project"]] == ["l2"]
    assert pools["google_drive"]["created_at"] == [], "a date written out in the title gives the answer away"
    assert aside["named twice"] == 6 and aside["value in the title"] == 2 and aside["named inside another"] == 1


def test_a_value_the_scorer_cannot_read_as_the_document_stores_it_is_not_asked(tmp_path):
    docs = [("fireflies", _rec("f1", "Pilot kickoff with Sequoia Retail", redwood_owner="Nina Patel", recorded_at="2026-02-20T16:00:00-07:00")),
            ("fireflies", _rec("f2", "Quarterly review with Acme", redwood_owner="Omar Reyes", recorded_at="2026-02-21")),
            ("jira", _rec("j1", "Edge proxy errors after a deploy", key="SUP-301", sla_due_at="2026-03-11T14:00:00Z")),
            ("jira", _rec("j2", "Slow token streaming in eu-west", key="SUP-302", sla_due_at="2026-03-12"))]
    pools, aside = W.descriptive_candidates(W.documents(_work(tmp_path, docs)))
    readable = {raw: B.score({"kind": "descriptive", "family": "single", "expected": {"date": raw[:10]}}, raw) == 1.0
                for raw in ("2026-02-20T16:00:00-07:00", "2026-03-11T14:00:00Z")}
    assert [c["doc"]["dsid"] for c in pools["fireflies"]["recorded_at"]] == ["f1"] * readable["2026-02-20T16:00:00-07:00"] + ["f2"]
    assert [c["doc"]["dsid"] for c in pools["jira"]["sla_due_at"]] == ["j1"] * readable["2026-03-11T14:00:00Z"] + ["j2"]
    assert aside["scorer cannot read the stored value"] == sum(not ok for ok in readable.values())
    for c in (c for fs in pools.values() for cs in fs.values() for c in cs):
        probe = {"kind": "descriptive", "family": "single", "expected": c["expected"]}
        assert B.score(probe, str(c["doc"]["raw"][c["field"]])) == 1.0


def test_no_metadata_line_of_a_descriptive_packet_gives_the_answer(tmp_path):
    twins = {"p1": {"updated_at": "2026-03-03", "merge_outcome": "Merged by squash on 2026-03-03 by Claire Huang", "state": "merged"},
             "f1": {"meeting_id": "ff-2026-02-20-sequoia-001", "redwood_attendees": ["Nina Patel (AE)", "Omar Reyes (SE)"]},
             "c1": {"related_pages": ["/confluence/OPS/runbooks/rollback", "/confluence/ENG/design"]},
             "j1": {"first_response_due_at": "2026-03-12", "audit_trail": "created_by=Liam Chen; updated_by=Ethan Cole"}}
    docs = [(s, {**r, **twins.get(r["dataset_doc_uuid"], {})}) for s, r in _docs()]
    pools, _ = W.descriptive_candidates(W.documents(_work(tmp_path, docs)))
    texts = {}
    for c in (c for fs in pools.values() for cs in fs.values() for c in cs):
        p, k, dropped = W._packet("descriptive", "desc-0-001", c)
        meta = [ln.split(": ", 1) for ln in p["text"].splitlines()[2:] if ln.split(":", 1)[0] in c["doc"]["doc"].meta]
        assert meta and not any(W._gives_value(v, k["expected"], k["type"]) for _, v in meta), (k["dsid"], k["field"])
        texts[k["dsid"], k["field"]] = (dict(meta), dropped)
    merged, dropped = texts["p1", "merged_at"]
    assert "updated_at" not in merged and "merge_outcome" not in merged and merged["state"] == "merged" and dropped == 2
    assert texts["p1", "author"][0]["updated_at"] == "2026-03-03" and "merge_outcome" not in texts["p1", "author"][0]
    assert texts["f1", "redwood_owner"][0]["redwood_attendees"] == "Omar Reyes (SE)" and "meeting_id" not in texts["f1", "recorded_at"][0]
    assert texts["c1", "space"][0]["related_pages"] == "/confluence/ENG/design"
    assert "first_response_due_at" not in texts["j1", "sla_due_at"][0] and "audit_trail" not in texts["j1", "reporter"][0]
    assert texts["j1", "status"][1] == 0
    ps, ks, rep = W.packets(_work(tmp_path / "b", docs), "descriptive", 20, seed=3)
    assert rep["answer_lines_dropped"] == sum(texts[k["dsid"], k["field"]][1] for k in ks)


def test_prose_packets_take_long_bodies_from_any_source_without_the_metadata(tmp_path):
    docs = _docs() + [("google_drive", _rec("g9", "A short note on lunch", "Lunch is at noon.", owner="Ava Lee")),
                      ("confluence", _rec("c9", "Very long handbook page", LONG * 80, author="Ava Lee", space="HR"))]
    ps, ks, rep = W.packets(_work(tmp_path, docs), "prose", 50, seed=2)
    assert {k["dsid"] for k in ks} == {"g1", "c1", "j1", "l1", "p1", "f1", "s1", "m1", "c9"} and rep["left_out"] == {"short body": 2}
    assert {p["source"] for p in ps} >= {"slack", "gmail"} and all(set(p) == {"packet_id", "kind", "source", "system", "title", "text",
                                                                               "instruction"} for p in ps)
    long = next(p for p, k in zip(ps, ks, strict=True) if k["dsid"] == "c9")
    assert len(long["text"]) <= W.TEXT_CHARS["prose"] + 10 and long["text"].endswith("[...]")
    assert all(p["text"].startswith("content:\n") and "owner:" not in p["text"] and "author:" not in p["text"] for p in ps)
    assert all("expected" not in k for k in ks) and rep["by_source"]["slack"] == 1


def test_a_test_zone_folder_is_read_only_after_the_preregistration(tmp_path):
    work = _work(tmp_path, zone="test")
    with pytest.raises(PermissionError):
        W.packets(work, "prose", 3, seed=1)
    assert len(W.packets(work, "prose", 3, seed=1, preregistered=True)[0]) == 3
    with pytest.raises(ValueError):
        W.packets(work, "other", 3, seed=1, preregistered=True)


def _by_source(ps, ks, src):
    return next((p, k) for p, k in zip(ps, ks, strict=True) if k["source"] == src)


def test_collect_descriptive_keeps_good_questions_and_rejects_with_reasons(tmp_path):
    ps, ks, _ = W.packets(_work(tmp_path), "descriptive", 20, seed=3)
    keyed = {k["source"]: k for k in ks}
    drive, jira, gh = keyed["google_drive"], keyed["jira"], keyed["github"]
    ask = {"owner": "Who owns the spreadsheet that projects our cash runway for the board?",
           "status": "What state is the spreadsheet that projects our cash runway for the board in?",
           "created_at": "When was the spreadsheet that projects our cash runway for the board created?"}
    jira_q = f"What is {jira['field_words']} of the support ticket about the edge proxy errors after a deploy?"
    gh_q = f"What is {gh['field_words']} of the pull request that isolates tenants in the retrieval starter?"
    misfit = ("Who" if jira["type"] in ("date", "month") else "When") + " got the support ticket about edge proxy errors its setting?"
    outs = [{"packet_id": drive["packet_id"], "question": f"“{ask[drive['field']]}”"},
            {"packet_id": jira["packet_id"], "question": jira_q},
            {"packet_id": gh["packet_id"], "question": gh_q},
            {"packet_id": drive["packet_id"], "question": "Who wrote the cash runway projection for the board?"},
            {"packet_id": jira["packet_id"], "question": jira_q},
            {"packet_id": "desc-999-001", "question": "Who owns the cash runway projection?"},
            '{"packet_id": "' + keyed["confluence"]["packet_id"] + '", "question": "What is the Incident review process for the serving fleet?"}',
            {"packet_id": keyed["confluence"]["packet_id"], "question": "Who wrote the page on reviewing incidents for the serving fleet"},
            {"packet_id": keyed["linear"]["packet_id"], "question": "What is the status of ENG-12, the key rotation work?"},
            {"packet_id": keyed["fireflies"]["packet_id"], "question": "Who owned the call in this document about the pilot?"},
            {"packet_id": keyed["hubspot"]["packet_id"], "question": "Who handles the Fernfield Connect account in the CRM?"},
            {"packet_id": gh["packet_id"], "question": "Has the pull request that isolates tenants in the retrieval starter been merged yet?"},
            {"packet_id": jira["packet_id"], "question": misfit},
            "not json at all"]
    qs, rej = W.collect("descriptive", ps, ks, outs)
    reasons = [r["reason"] for r in rej]
    assert [q["packet_id"] for q in qs] == [drive["packet_id"], jira["packet_id"], gh["packet_id"]]
    assert reasons == ["packet answered already", "packet answered already", "unknown packet id", "quotes the title", "not a question",
                       "names the key or number", "refers to the document itself", "quotes the title", "yes/no question",
                       "question word does not fit the field", "not a JSON object"]
    q = qs[0]
    assert q["kind"] == q["group"] == "descriptive" and q["family"] == "single" and q["gold_docs"] == ["g1"]
    assert q["expected"] == drive["expected"] and q["field"] == drive["field"] and q["id"] == drive["packet_id"]
    assert q["question"] == ask[drive["field"]], "the quote marks around the question are dropped"
    path = tmp_path / "desc.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in qs))
    loaded = load_descriptive(path)
    assert [x["expected"] for x in loaded] == [x["expected"] for x in qs] and all(B.checkable(x) for x in loaded)
    e = drive["expected"]
    assert B.score(loaded[0], f"Answer: {e.get('value') or e.get('date')}") == 1.0 and B.score(loaded[0], "Answer: not found") == 0.0


@pytest.mark.parametrize("question,expected,typ,gives", [
    ("Who owns the doc Maya wrote about runway?", {"value": "Maya Chen"}, "person", True),
    ("Who owns the doc about may launch plans?", {"value": "Maya Chen"}, "person", False),
    ("What priority does the high-traffic gateway ticket have?", {"value": "High"}, "value", True),
    ("What state is the in-progress gateway migration in?", {"value": "In Progress"}, "value", True),
    ("When was the review held on March 5, 2026 recorded?", {"date": "2026-03-05"}, "date", True),
    ("When was the March 5 review recorded?", {"date": "2026-03-05"}, "date", True),
    ("When was the 2026-03-05 review recorded?", {"date": "2026-03-05"}, "date", True),
    ("When was the review of March 15 recorded?", {"date": "2026-03-05"}, "date", False),
    ("Which month will the deal expected in May 2026 close?", {"value": "2026-05", "alts": ["May 2026"]}, "month", True),
    ("Which space holds the page on GPU quotas?", {"value": "OPS"}, "value", False),
])
def test_a_question_that_holds_the_answer_is_found_in_any_written_form(question, expected, typ, gives):
    assert W._gives_value(question, expected, typ) is gives


@pytest.mark.parametrize("question,asks_yes_no", [
    ("Has the pull request that adds tenant isolation to the retrieval starter been merged yet?", True),
    ("Was the quickstart pull request merged before the end of Q1?", True),
    ("For QuantaThera's dedicated pool incident on 2026-03-10, did customer P99 latency increase?", True),
    ("The fix shipped in March, didn't it?", True),
    ("Did the incident where P99 rose get resolved?", True),
    ("Do you know who owns the runway spreadsheet for the board?", False),
    ("Can you tell me when the tenant isolation pull request was merged?", False),
    ("For the March burst, how much did throughput drop?", False),
    ("In which space does the page on GPU quotas live?", False),
    ("Who is handling the support ticket about edge proxy errors?", False),
])
def test_a_yes_no_question_is_found_after_a_leading_clause_too(question, asks_yes_no):
    assert W.yes_no(question) is asks_yes_no


@pytest.mark.parametrize("question,typ,fits", [
    ("Who merged the pull request that isolates tenants?", "date", False),
    ("When was the support ticket about edge proxy errors assigned?", "person", False),
    ("When did the gateway ticket get its priority?", "value", False),
    ("Why is the gateway ticket at that priority?", "value", False),
    ("By when is the SLA on the edge proxy ticket due?", "date", True),
    ("What day was the tenant isolation pull request merged?", "date", True),
    ("When the gateway ticket was filed, who was it given to?", "person", True),
    ("Where does the page on GPU quotas live?", "value", True),
    ("How urgent is the support ticket about edge proxy errors?", "value", True),
    ("Which customer raised the edge proxy errors ticket?", "customer", True),
    ("Who raised the edge proxy errors ticket?", "customer", True),
])
def test_a_descriptive_question_word_must_fit_the_field(question, typ, fits):
    exp = {"date": "2026-03-12"} if typ == "date" else {"value": "Zed Quill"}
    key = {"expected": exp, "type": typ, "title": "Some other title entirely", "source": "jira", "name": "SUP-101"}
    assert (W._why_descriptive(question, key) is None) is fits


def test_the_title_is_given_away_whole_quoted_or_by_a_long_run():
    title = "Incident review process for the serving fleet"
    assert W._why_title("Who wrote the incident review process for the serving fleet page?", title) == "quotes the title"
    assert W._why_title('Who wrote the "incident review process" page?', title) == "quotes the title"
    assert W._why_title("Who wrote up the review process for the serving fleet?", title) == "long run of the title"
    assert W._why_title("Who wrote the page on how we review outages of our inference servers?", title) is None
    assert W._why_title("Who owns the Fernfield Connect account?", "Fernfield Connect") == "quotes the title"


def test_collect_prose_checks_the_facts_against_the_text_and_converts_for_load_prose(tmp_path):
    ps, ks, _ = W.packets(_work(tmp_path), "prose", 3, seed=2)
    pid = [p["packet_id"] for p in ps]
    q = "During the A100 pool rollout, what batch size cap and p99 alert threshold were decided?"
    outs = [{"packet_id": pid[0], "question": q, "answer_facts": ["cap  max_batch_size at 48", "“850 ms.”"]},
            {"packet_id": pid[1], "question": q, "answer_facts": ["cap max_batch_size at 64"]},
            {"packet_id": pid[1], "question": "What canary size precedes the fleet upgrade for the platform?", "answer_facts": ["5"]},
            {"packet_id": pid[1], "question": "What canary precedes the fleet upgrade for the platform?",
             "answer_facts": ["The rollout uses a canary of 5 percent for two days before"]},
            {"packet_id": pid[1], "question": "How long does the 5 percent canary run before the fleet upgrade?",
             "answer_facts": ["5 percent"]},
            {"packet_id": pid[1], "question": "Is the canary for the fleet upgrade 5 percent?", "answer_facts": ["two days"]},
            {"packet_id": pid[1], "question": "How long does the canary run before the fleet upgrade?", "answer_facts": []},
            {"packet_id": pid[1], "question": "How long does the canary run before the fleet upgrade?",
             "answer_facts": ["for two days", "5 percent", "every Monday", "850 ms"]},
            {"packet_id": pid[1], "question": "How long does the canary run before the fleet upgrade?", "answer_facts": "two days"},
            {"packet_id": pid[1], "question": "How long does the canary run before the fleet upgrade?", "answer_facts": ["before the"]},
            {"packet_id": pid[2], "question": "  " + q.lower(), "answer_facts": ["850 ms"]},
            {"packet_id": pid[2], "question": "Why was max_batch_size capped at 48 on the A100 pool?", "answer_facts": ["cap max_batch_size at 48"]},
            {"packet_id": pid[2], "question": "On the A100 pool, what happens when p99 latency passes the 850 ms alert threshold?",
             "answer_facts": ["alert threshold for p99 latency is 850 ms"]},
            {"packet_id": pid[2], "question": "For the A100 pool rollout, did the team settle on a batch size cap?",
             "answer_facts": ["cap max_batch_size at 48"]},
            {"packet_id": pid[1], "question": "How long does the canary run before the fleet upgrade?", "answer_facts": ["for two days"]}]
    qs, rej = W.collect("prose", ps, ks, outs)
    assert [r["reason"] for r in rej] == ["answer fact not in the text", "answer fact shorter than 2 words", "answer fact longer than 10 words",
                                          "question contains an answer fact", "yes/no question", "no answer facts",
                                          "more than 3 answer facts", "answer facts are not a list of text",
                                          "answer fact without a number or content word", "duplicate question",
                                          "question contains an answer fact", "question contains an answer fact", "yes/no question"]
    echo = {"kind": "prose", "family": "prose", "expected": {"facts": ["cap max_batch_size at 48"]}}
    assert B.score(echo, "Why was max_batch_size capped at 48 on the A100 pool?") == 1.0, "why the reworded question is rejected"
    assert [x["packet_id"] for x in qs] == [pid[0], pid[1]]
    assert qs[0]["answer_facts"] == ["cap max_batch_size at 48", "850 ms"] and qs[0]["family"] == qs[0]["kind"] == "prose"
    path = tmp_path / "prose.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in qs))
    loaded = B.load_prose(path)
    assert [(x["id"], x["expected"], x["gold_docs"]) for x in loaded] == [(x["id"], {"facts": x["answer_facts"]}, x["gold_docs"]) for x in qs]
    assert loaded[0]["gold_docs"] == [ks[0]["dsid"]] and all(B.checkable(x) for x in loaded)
    assert B.score(loaded[1], "Answer: the canary runs for two days") == 1.0


def test_the_command_line_writes_packets_and_keys_apart_and_collects(tmp_path, capsys):
    work = _work(tmp_path)
    p, k, o, q = (tmp_path / n for n in ("p.jsonl", "k.jsonl", "o.jsonl", "q.jsonl"))
    rep = W.main(["packets", "--work", str(work), "--kind", "descriptive", "--n", "4", "--seed", "5", "--out", str(p), "--keys", str(k)])
    assert rep["packets"] == 4 and len(p.read_text().splitlines()) == len(k.read_text().splitlines()) == 4
    assert '"dsid"' not in p.read_text() and '"expected"' not in p.read_text() and '"dsid"' in k.read_text()
    rep2 = W.main(["packets", "--work", str(work), "--kind", "prose", "--n", "20", "--seed", "6", "--out", str(tmp_path / "pp.jsonl"),
                   "--keys", str(tmp_path / "pk.jsonl"), "--avoid", str(k)])
    prose_keys = [json.loads(x) for x in (tmp_path / "pk.jsonl").read_text().splitlines()]
    assert rep2["avoided"] == 4 and rep2["packets"] == len(prose_keys) >= 4
    assert not {r["dsid"] for r in prose_keys} & {json.loads(x)["dsid"] for x in k.read_text().splitlines()}
    first = json.loads(p.read_text().splitlines()[0])
    o.write_text(json.dumps({"packet_id": first["packet_id"], "question": "Which colleague is responsible for it, roughly?"}) + "\n")
    rep3 = W.main(["collect", "--kind", "descriptive", "--packets", str(p), "--keys", str(k), "--outputs", str(o), "--out", str(q)])
    assert rep3["kept"] + rep3["rejected"] == 1 and (tmp_path / "q.rejected.jsonl").exists()
    with pytest.raises(SystemExit):
        W.main(["packets", "--work", str(work), "--kind", "prose", "--n", "1", "--seed", "1", "--out", str(p), "--keys", str(p)])
    capsys.readouterr()
