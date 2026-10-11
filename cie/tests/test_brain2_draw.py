"""The company brain's fresh draw and held-out unanswerable questions (v16): the zone draw that leaves out earlier haystacks and
refuses the test zone, the held-out documents and their three checks, the writer packets, and collect with check (4)."""

from __future__ import annotations

import gzip
import hashlib
import json
import random
from collections import Counter

import pytest

from cie.eval import brain2_draw as D
from cie.eval import brain_writers as W
from cie.eval.brain_test import load_docs
from cie.ingest.sources import SourceDoc

VOCAB = [a + b for a in ("ka", "lo", "mi", "nu", "pe", "ra", "si", "to", "vu", "ze", "bo", "di", "fa", "gu")
         for b in ("rn", "lt", "mp", "sk", "nd", "rv", "lb", "xt", "ph", "qu", "st", "wn", "dr", "cl")]
FACT = "The rollback window is 45 minutes for the Brightwater pilot."


def _body(seed: str, extra: str = "") -> str:
    """A body no other document shares a run of five words with (random words of a made-up vocabulary)."""
    rng = random.Random(seed)
    return " ".join(rng.choice(VOCAB) for _ in range(120)) + (" " + extra if extra else "")


def _rec(dsid, title, body=None, **meta):
    return {"dataset_doc_uuid": dsid, "title": title, "content_field_names": ["content"], "content": body or _body(dsid), **meta}


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def _bench(tmp_path, recs, zone_of):
    """Documents on disk, a folder index, and a zone file with its summary (as brain_draw writes them)."""
    root = tmp_path / "bench"
    sources = root / "generated_data" / "sources"
    index = {}
    for src, rec in recs:
        rel = f"{src}/{rec['dataset_doc_uuid']}.json"
        _write(sources / rel, rec)
        index[rec["dataset_doc_uuid"]] = rel
    folder_idx = tmp_path / "index.json"
    folder_idx.write_text(json.dumps({"root": str(sources), "index": index}))
    zones_path = tmp_path / "zones.json.gz"
    zones_path.write_bytes(gzip.compress(json.dumps({d: zone_of(d) for d in index}, sort_keys=True).encode(), mtime=0))
    _write(tmp_path / "zones_summary.json", {"sha256": hashlib.sha256(zones_path.read_bytes()).hexdigest()})
    return root, folder_idx, zones_path, index


def _hay(folder, root, folder_idx, dsids, zone="train", **extra):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "haystack.json").write_text(json.dumps({"root": str(root), "dsids": sorted(dsids), "zone": zone, **extra}))
    (folder / "index.json").symlink_to(folder_idx)
    return folder


# ------------------------------------------------------------------ the fresh draw
def _lin(dsid, key):
    return {"dsid": dsid, "source": "linear", "title": f"issue {key}", "raw": {"key": key, "assignee": "Omar Singh"}}


def _pr(dsid, n, links):
    return {"dsid": dsid, "source": "github", "title": f"PR {n}", "raw": {"pr_number": n, "linked_linear": links}}


def _zoned():
    docs = [_lin("l1", "ENG-11"), _pr("g1", "7100", ["ENG-11"]),  # plantable only once g2, which reuses 7100, is left out
            _pr("g2", "7100", ["ENG-90"]),
            _lin("l3", "ENG-13"), _pr("g3", "7300", ["ENG-13"]),  # plantable
            _lin("t1", "ENG-14"), _pr("t2", "7400", ["ENG-14"])]  # a test-zone pair
    index = {d["dsid"]: f"{d['source']}/{d['dsid']}.json" for d in docs} | {f"s{i}": f"slack/s{i}.json" for i in range(40)}
    zone_map = {d: "train" for d in index} | {"t1": "test", "t2": "test"} | {f"s{i}": "test" for i in range(30, 40)}
    by_id = {d["dsid"]: d for d in docs}
    loaded: list[str] = []

    def load(ids):
        loaded.extend(ids)
        return [by_id[x] for x in ids if x in by_id]

    return index, zone_map, load, loaded


def test_draw2_refuses_the_test_zone_without_the_flag(tmp_path):
    index, zone_map, load, loaded = _zoned()
    with pytest.raises(PermissionError):
        D.draw2(index, zone_map, "test", load, seed=1, n=5)
    assert loaded == [], "nothing of the test zone is read before the refusal"
    ids, info = D.draw2(index, zone_map, "test", load, seed=1, n=5, preregistered=True)
    assert set(ids) <= {d for d, z in zone_map.items() if z == "test"} and info["zone"] == "test"
    root, folder_idx, zones_path, _ = _bench(tmp_path, [("slack", _rec("s0", "general"))], lambda d: "test")
    out = tmp_path / "t"
    with pytest.raises(PermissionError):
        D.write_draw2(zones_path, "test", 1, folder_idx, root, out, n=1)
    with pytest.raises(SystemExit):
        D.main(["draw", "--zone", "test", "--seed", "1", "--zones", str(zones_path), "--index", str(folder_idx), "--root", str(root),
                "--out", str(out)])
    assert not out.exists()
    with pytest.raises(ValueError):
        D.draw2(index, zone_map, "nowhere", load, seed=1, n=5)


def test_draw2_leaves_out_excluded_documents_and_plants_pairs_found_among_the_rest():
    index, zone_map, load, loaded = _zoned()
    ids, info = D.draw2(index, zone_map, "train", load, seed=3, n=20)
    assert {(p["pr"], p["issue"]) for p in info["planted"]} == {("g3", "l3")}, "7100 is on two documents of the zone"
    assert all(zone_map[d] == "train" for d in ids) and not {x for x in loaded if zone_map[x] == "test"}
    excluded = {"g2", "s0", "s1", "s2"}
    ids, info = D.draw2(index, zone_map, "train", load, seed=3, n=20, exclude=excluded)
    assert {(p["pr"], p["issue"]) for p in info["planted"]} == {("g1", "l1"), ("g3", "l3")}
    assert {"g1", "l1", "g3", "l3"} <= set(ids) and not set(ids) & excluded and all(zone_map[d] == "train" for d in ids)
    assert info["excluded_in_zone"] == 4 and info["zone_documents"] == 35 and "excluded" not in info
    one, info1 = D.draw2(index, zone_map, "train", load, seed=3, n=20, exclude=excluded, planted=1)
    assert len(info1["planted"]) == 1 and info1["planted_candidates"] == 2
    assert D.draw2(index, zone_map, "train", load, seed=3, n=20, exclude=excluded)[0] == ids, "seeded"
    with pytest.raises(ValueError, match="lacks"):
        D.draw2(index, zone_map | {"gone": "train"}, "train", load, seed=3, n=20)


def test_write_draw2_writes_a_folder_that_brain_test_reads(tmp_path):
    recs = [("linear", _rec(f"l{i}", f"Issue {i}", key=f"ENG-{10 + i}")) for i in range(3)]
    recs += [("github", _rec(f"g{i}", f"PR {i}", pr_number=f"{500 + i}", linked_linear=[f"ENG-{10 + i}"])) for i in range(3)]
    recs += [("slack", _rec(f"s{i}", "general")) for i in range(30)]
    root, folder_idx, zones_path, index = _bench(tmp_path, recs, lambda d: "dev" if d != "s29" else "test")
    old = _hay(tmp_path / "old", root, folder_idx, ["g0", "s0", "s1"], zone="dev")
    out = tmp_path / "fresh"
    rep = D.main(["draw", "--zone", "dev", "--seed", "1701", "-n", "20", "--zones", str(zones_path), "--index", str(folder_idx),
                  "--root", str(root), "--exclude", str(old), "--out", str(out)])
    hay = json.loads((out / "haystack.json").read_text())
    assert hay["zone"] == "dev" and hay["seed"] == 1701 and hay["excluded_haystacks"] == [str((old / "haystack.json").resolve())]
    assert not set(hay["dsids"]) & {"g0", "s0", "s1", "s29"} and len(hay["dsids"]) == rep["documents"]
    assert {(p["pr"], p["issue"]) for p in rep["planted"]} == {("g1", "l1"), ("g2", "l2")}, "g0 is in the earlier haystack"
    assert (out / "index.json").resolve() == folder_idx.resolve()
    assert rep["haystack_sha256"] == hashlib.sha256((out / "haystack.json").read_bytes()).hexdigest()
    assert rep["excluded_haystacks"] == {str((old / "haystack.json").resolve()): {"in_zone": 3}}
    assert sorted(d["dsid"] for d in load_docs(out)) == sorted(hay["dsids"]), "brain_test reads the folder as other draws"
    assert json.loads((out / "draw_report.json").read_text())["zones_sha256"] == hay["zones_sha256"]


# ------------------------------------------------------------------ held-out documents
def _heldout_bench(tmp_path):
    hay = [("jira", _rec("j-h1", "Edge proxy errors after a deploy", key="SUP-101", customer_company="Acme Analytics",
                         assignee="Ethan Cole")),
           ("slack", _rec("s-h1", "eng-oncall", _body("s-h1", "Blocked on ENG-77 for Novamed Health; see Quarterly pricing review "
                                                                "for Zephyr. Brightwater rollback window is 45 minutes."),
                          channel="eng-oncall")),
           ("google_drive", _rec("g-h1", "Runway model for the Q3 board deck", owner="Ava Lee")),
           ("linear", _rec("l-h1", "Rotate the KMS keys for private deployments", key="ENG-12", assignee="Maya Chen"))]
    hay += [("slack", _rec(f"s-x{i}", "general", _body(f"s-x{i}", "latency budget review"))) for i in range(12)]
    pool = [("linear", _rec("l-c1", "Gateway retries for streaming", key="ENG-77")),  # (1): its key is written in Slack
            ("gmail", {**_rec("m-c1", "", subject="Trial credits extension"), "title_field_name": "subject",
                       "related_account": "Novamed Health"}),  # (1): its account is written
            ("google_drive", _rec("g-c1", "Quarterly pricing review for Zephyr")),  # (1): its title is written
            ("google_drive", _rec("g-c2", "Runway model for the Q4 board deck")),  # (2): title Jaccard 1.0 with g-h1
            ("confluence", _rec("c-c1", "Serving fleet notes", _body("g-h1"))),  # (3): the body of g-h1
            ("linear", _rec("l-c2", "Shard the vector index by tenant", key="ENG-501", assignee="Maya Chen",
                            status="Planned", priority="P2")),  # kept unless person names are in check (1)
            ("jira", _rec("j-c1", "Brightwater ingestion latency regression", _body("j-c1", FACT), key="SUP-777",
                          customer_company="Brightwater Labs", status="Open")),
            ("github", _rec("p-c1", "add-tenant-isolation-to-the-rag-starter", pr_number="3456", repo="runtime")),
            ("fireflies", _rec("f-c1", "Pilot kickoff and success criteria review",
                               _body("f-c1", "The pilot exit criteria require three signed reference calls."),
                               customer_company="Sequoia Retail")),
            ("hubspot", {**_rec("h-c1", "", company_name="Fernfield Connect"), "title_field_name": "company_name"}),
            ("slack", _rec("s-c1", "random")),  # never held out
            ("linear", _rec("x-c1", "Excluded issue", key="ENG-900")),  # in an excluded haystack
            ("linear", _rec("t-c1", "Test-zone issue", key="ENG-901")),  # test zone
            ("linear", _rec("d-c1", "Dev-zone issue", key="ENG-902"))]  # dev zone
    zone = {"t-c1": "test", "d-c1": "dev"}
    root, folder_idx, zones_path, index = _bench(tmp_path, hay + pool, lambda d: zone.get(d, "train"))
    work = _hay(tmp_path / "work", root, folder_idx, [r["dataset_doc_uuid"] for _, r in hay])
    other = _hay(tmp_path / "other", root, folder_idx, ["x-c1"])
    return work, other, zones_path


def test_heldout_keeps_only_documents_that_pass_the_three_checks(tmp_path, monkeypatch):
    work, other, zones_path = _heldout_bench(tmp_path)
    read = []
    real = D.read_docs

    def spy(sources, index, ids):
        ids = list(ids)
        read.extend(ids)
        return real(sources, index, ids)

    monkeypatch.setattr(D, "read_docs", spy)
    held, rep = D.heldout(work, zones_path, 100, seed=5, exclude=[other])
    kept = {h["doc"]["dsid"] for h in held}
    assert kept == {"l-c2", "j-c1", "p-c1", "f-c1", "h-c1"}
    assert rep["dropped"] == {"linear": {"anchor written in the haystack": 1}, "gmail": {"anchor written in the haystack": 1},
                              "google_drive": {"anchor written in the haystack": 1, "title Jaccard >= 0.5": 1},
                              "confluence": {"shingle overlap >= 0.1": 1}}
    assert not {"t-c1", "d-c1", "x-c1", "s-c1"} & set(read), "no document of another zone, an excluded haystack or Slack is read"
    assert rep["pool"]["linear"] == 2 and "slack" not in rep["pool"] and rep["zone"] == "train"
    by = {h["doc"]["dsid"]: h for h in held}
    assert by["l-c2"]["persons_written"] == ["Maya Chen"] and by["l-c2"]["checks"]["anchors_written"] == []
    assert {"kind": "key", "text": "SUP-777"} in by["j-c1"]["anchors"] and {"kind": "customer", "text": "Brightwater Labs"} in by["j-c1"]["anchors"]
    assert [a["kind"] for a in by["h-c1"]["anchors"]] == ["title"], "a company name that is the title is one anchor"
    assert rep["kept_with_no_person_written"] == 4
    strict, srep = D.heldout(work, zones_path, 100, seed=5, exclude=[other], person_anchors=True)
    assert {h["doc"]["dsid"] for h in strict} == kept - {"l-c2"} and srep["person_anchors"]


def test_heldout_takes_equal_shares_of_the_sources_and_examines_about_1_4_times_each(tmp_path):
    recs = [(s, _rec(f"{s}-{i}", f"{s} plan {i} for {VOCAB[i]} {VOCAB[i + 30]}", key=f"ENG-{100 + i}" if s == "linear" else None))
            for s in ("linear", "confluence") for i in range(12)]
    recs.append(("slack", _rec("s-h", "general")))
    root, folder_idx, zones_path, _ = _bench(tmp_path, recs, lambda d: "dev")
    work = _hay(tmp_path / "w", root, folder_idx, ["s-h"], zone="dev")
    held, rep = D.heldout(work, zones_path, 4, seed=9)
    assert rep["quota"] == {"confluence": 2, "linear": 2} and rep["examined"] == {"confluence": 3, "linear": 3}
    assert Counter(h["doc"]["source"] for h in held) == {"confluence": 3, "linear": 3}
    assert [h["doc"]["dsid"] for h in D.heldout(work, zones_path, 4, seed=9)[0]] == [h["doc"]["dsid"] for h in held], "seeded"
    assert {h["doc"]["dsid"] for h in D.heldout(work, zones_path, 4, seed=10)[0]} != {h["doc"]["dsid"] for h in held}
    assert D.quotas(["a", "b", "c"], 7, 1) == D.quotas(["c", "b", "a"], 7, 1) and sum(D.quotas(["a", "b", "c"], 7, 1).values()) == 7


def test_heldout_refuses_a_test_zone_haystack_without_the_flag(tmp_path):
    recs = [("linear", _rec(f"l{i}", f"Issue about {VOCAB[i]} and {VOCAB[i + 40]}", key=f"ENG-{20 + i}")) for i in range(4)]
    root, folder_idx, zones_path, _ = _bench(tmp_path, recs, lambda d: "test")
    work = _hay(tmp_path / "w", root, folder_idx, ["l0"], zone="test")
    with pytest.raises(PermissionError):
        D.heldout(work, zones_path, 2, seed=1)
    nozone = tmp_path / "nz"
    nozone.mkdir()
    (nozone / "haystack.json").write_text(json.dumps({"root": str(root), "dsids": ["l0"]}))
    (nozone / "index.json").symlink_to(folder_idx)
    with pytest.raises(PermissionError):  # the zone read from the documents
        D.heldout(nozone, zones_path, 2, seed=1)
    with pytest.raises(PermissionError):
        D.load_haystack(work)
    assert len(D.heldout(work, zones_path, 2, seed=1, preregistered=True)[0]) == 3


def test_heldout_checks_the_zone_file_the_haystack_was_drawn_with(tmp_path):
    work, other, zones_path = _heldout_bench(tmp_path)
    hay = json.loads((work / "haystack.json").read_text())
    (work / "haystack.json").write_text(json.dumps({**hay, "zones_sha256": "0" * 64}))
    with pytest.raises(RuntimeError, match="zone file"):
        D.heldout(work, zones_path, 10, seed=1)


def test_written_text_undoes_json_escapes_and_matches_whole_words():
    docs = [{"title": "Notes", "raw": {"comments": "line one\nMaya Chen: ok", "n": "ref 1048576 and ENG-103456"}}]
    text = D.written_text(docs)
    assert D.is_written(text, "Maya Chen") and D.is_written(text, "ENG-103456")
    assert not D.is_written(text, "104857") and not D.is_written(text, "ENG-10345") and not D.is_written(text, "")


# ------------------------------------------------------------------ packets and collect
def test_packets_follow_the_writers_format_and_keep_the_keys_apart(tmp_path):
    work, other, zones_path = _heldout_bench(tmp_path)
    rep = D.main(["heldout", "--work", str(work), "--zones", str(zones_path), "--n", "100", "--seed", "1702", "--out",
                  str(tmp_path / "out"), "--exclude", str(other)])
    name = "work_heldout_1702"
    ps = W.read_rows(tmp_path / "out" / f"{name}.packets.jsonl")
    ks = W.read_rows(tmp_path / "out" / f"{name}.keys.jsonl")
    assert len(ps) == len(ks) == rep["kept"] == 5 and [p["packet_id"] for p in ps] == [k["packet_id"] for k in ks]
    assert [p["packet_id"] for p in ps] == [f"heldout-1702-{i:03d}" for i in range(1, 6)]
    for p, k in zip(ps, ks, strict=True):
        assert set(p) == {"packet_id", "kind", "source", "system", "title", "text", "instruction"} and p["kind"] == k["kind"] == "unanswerable"
        assert p["instruction"] == D.INSTRUCTION and "whose answer is in this document" in p["instruction"]
        assert not p["text"].startswith(p["title"]) and p["text"].startswith(f"source: {p['source']}")
        assert k["dsid"] and k["anchors"] and set(k["checks"]) == {"anchors_written", "title_jaccard", "shingle_overlap"}
    assert "c-" not in json.dumps(ps) and not any(k["dsid"] in json.dumps(ps) for k in ks), "no document id reaches a writer"
    jira = next(p for p in ps if p["source"] == "jira")
    assert "status: Open" in jira["text"] and FACT in jira["text"], "the writer sees metadata and body"
    batch = json.loads((tmp_path / "out" / "batches" / f"{name}_b00.json").read_text())
    assert batch["kind"] == "unanswerable" and [p["packet_id"] for p in batch["packets"]] == [p["packet_id"] for p in ps]
    st = W.batch_status(tmp_path / "out" / "batches", tmp_path / "answers", name)
    assert st == [{"batch": f"{name}_b00", "packets": 5, "read": "missing", "rows": 0, "packets_answered": 0, "complete": False}]
    assert [len(b["packets"]) for b in D.batches(ps * 5, "x")] == [10, 10, 5]
    assert json.loads((tmp_path / "out" / f"{name}.report.json").read_text())["packets"]["packets"] == 5


def test_collect_runs_the_prose_checks_then_check_4(tmp_path):
    work, other, zones_path = _heldout_bench(tmp_path)
    D.write_heldout(work, zones_path, 100, 1702, tmp_path / "out", [other])
    name = "work_heldout_1702"
    ps = W.read_rows(tmp_path / "out" / f"{name}.packets.jsonl")
    ks = W.read_rows(tmp_path / "out" / f"{name}.keys.jsonl")
    pid = {k["dsid"]: k["packet_id"] for k in ks}
    outputs = [
        {"packet_id": pid["j-c1"], "question": "How long is the rollback window in the ingestion regression ticket for that pilot?",
         "answer_facts": ["rollback window is 45 minutes"]},  # Slack holds "Brightwater" and the fact: check (4)
        {"packet_id": pid["l-c2"], "question": "Is the tenant sharding issue still planned?", "answer_facts": ["Planned"]},
        {"packet_id": pid["p-c1"], "question": "Which repository is the tenant isolation change for the RAG starter in?",
         "answer_facts": ["the payments monolith"]},
        {"packet_id": pid["f-c1"], "question": "What do the Sequoia Retail pilot exit criteria require before sign-off?",
         "answer_facts": ["three signed reference calls"]},
        {"packet_id": "heldout-1702-999", "question": "What is it about?", "answer_facts": ["x y"]},
        "not json at all",
    ]
    hay = D.load_haystack(work)
    qs, rejected = D.collect(ps, ks, outputs, hay)
    reasons = Counter(r["reason"] for r in rejected)
    assert reasons == {D.FOUND: 1, "yes/no question": 1, "answer fact not in the text": 1, "unknown packet id": 1,
                       "not a JSON object": 1}
    assert next(r for r in rejected if r["reason"] == D.FOUND)["holder"] == "s-h1"
    assert len(qs) == 1
    q = qs[0]
    assert q["family"] == "unanswerable" and q["kind"] == "heldout" and q["group"] == "heldout"
    assert q["expected"] == {"not_found": True} and q["gold_docs"] == [] and q["heldout_doc"] == "f-c1" and q["id"] == pid["f-c1"]
    assert D.score(q, "Not found: nothing in the documents.") == 1.0 and D.score(q, "Sequoia Retail") == 0.0
    assert D.score(q, {"answer": "Sequoia", "route": "not_found"}) == 1.0
    out = tmp_path / "q.jsonl"
    (tmp_path / "w.jsonl").write_text("\n".join(json.dumps(o) for o in outputs[:4]))
    rep = D.main(["collect", "--work", str(work), "--packets", str(tmp_path / "out" / f"{name}.packets.jsonl"), "--keys",
                  str(tmp_path / "out" / f"{name}.keys.jsonl"), "--outputs", str(tmp_path / "w.jsonl"), "--out", str(out)])
    assert rep["kept"] == 1 and rep["reasons"] == {D.FOUND: 1, "yes/no question": 1, "answer fact not in the text": 1}
    assert W.read_rows(out)[0]["heldout_doc"] == "f-c1" and (tmp_path / "q.rejected.jsonl").exists()


def _sd(dsid, title, body):
    return {"dsid": dsid, "source": "slack", "title": title, "raw": {}, "doc": SourceDoc(dsid, "slack", f"slack/{dsid}.json", title,
                                                                                     [("content", body)])}


def test_check_4_needs_an_anchor_word_few_documents_hold():
    docs = [_sd(f"x{i}", "general", f"latency budget review {i}") for i in range(11)]
    docs += [_sd("y1", "eng", "The latency budget allows p95 under 350 ms for search."),
             _sd("y2", "eng", "Kestrelpoint asked again: the cutover freeze lasts 6 days in March.")]
    hay = D.Haystack(docs)
    assert hay.anchor_words(["Latency budget for Kestrelpoint"]) == {"kestrelpoint"}, "latency and budget are on 12 documents"
    assert hay.holder(["p95 under 350 ms"], ["Latency budget for Kestrelpoint"]) is None, "a generic fact with common words"
    assert hay.holder(["cutover freeze lasts 6 days", "approved by legal"], ["Latency budget for Kestrelpoint"]) == "y2"
    assert hay.holder(["cutover freeze lasts 6 days", "approved by legal", "signed in May"], ["Kestrelpoint"]) is None, "1 of 3"
    assert hay.holder(["cutover freeze lasts 6 days"], ["Latency budget"]) is None, "no anchor word few documents hold"
