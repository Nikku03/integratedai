"""The company brain's fresh-document zones and draws: seen sets, hash zones, planted pairs dealt to zones, and zone draws."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter

import pytest

from cie.eval import brain_draw as B
from cie.eval import factbank_5k as F


def _lin(dsid, key):
    return {"dsid": dsid, "source": "linear", "title": f"issue {key}", "raw": {"key": key, "assignee": "Omar Singh", "status": "Todo"}}


def _jira(dsid, key):
    return {"dsid": dsid, "source": "jira", "title": f"ticket {key}", "raw": {"key": key, "assignee": "Ava Lee", "status": "Open"}}


def _pr(dsid, n, links, **x):
    return {"dsid": dsid, "source": "github", "title": f"PR {n}", "raw": {"pr_number": n, "author": "Maya Chen", "linked_linear": links, **x}}


def _setup(docs, n_slack=20):
    index = {d["dsid"]: f"{d['source']}/{d['dsid']}.json" for d in docs} | {f"s{i}": f"slack/s{i}.json" for i in range(n_slack)}
    by_id = {d["dsid"]: d for d in docs}
    return index, by_id, lambda xs: [by_id[x] for x in xs if x in by_id]


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def test_seen_documents_reads_every_haystack_but_the_benchmark_brain_and_hidden_folders(tmp_path):
    _write(tmp_path / "a" / "haystack.json", {"dsids": ["d1", "d2"]})
    _write(tmp_path / "b" / "review" / "c" / "haystack.json", {"dsids": ["d3"]})
    _write(tmp_path / "brain" / "train5k" / "haystack.json", {"dsids": ["x1"]})
    _write(tmp_path / "EnterpriseRAG-Bench" / "haystack.json", {"dsids": ["x2"]})
    _write(tmp_path / ".cache" / "haystack.json", {"dsids": ["x3"]})
    _write(tmp_path / "lexsample" / "haystack.json", {"dsids": ["d4"]})
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "haystack.json").write_text("{not json")
    _write(tmp_path / "nodsids" / "haystack.json", {"root": "r"})
    (tmp_path / "t5k_dsids.txt").write_text("d5\n\nd6\n")
    _write(tmp_path / "hay5k_docs.json", [{"dsid": "d7"}, {"dsid": "d1"}])
    (tmp_path / "linked").symlink_to(tmp_path / "a")
    assert B.seen_documents(tmp_path) == {"d1", "d2", "d3", "d4", "d5", "d6", "d7"}
    sets = B.seen_sets(tmp_path)
    assert sets["b/review/c/haystack.json"] == {"d3"} and "linked/haystack.json" in sets and "bad/haystack.json" not in sets
    assert not any(k.startswith(("brain", "EnterpriseRAG-Bench", ".cache")) for k in sets)


def test_zones_hash_the_salted_id_and_skip_seen_documents():
    ids = [f"dsid_{i:05d}" for i in range(5000)]
    z = B.zones(ids, seen={"dsid_00000", "dsid_00001"})
    assert "dsid_00000" not in z and len(z) == 4998
    for d in ids[2:50]:
        h = int(hashlib.sha256(("brain-zones-v1" + d).encode()).hexdigest(), 16) % 10
        assert z[d] == ("test" if h < 2 else "dev" if h < 4 else "train")
    share = Counter(z.values())
    assert 0.17 < share["test"] / len(z) < 0.23 and 0.17 < share["dev"] / len(z) < 0.23 and 0.56 < share["train"] / len(z) < 0.64
    assert B.zones(ids, set(), salt="other") != B.zones(ids, set()), "the salt changes the partition"
    assert B.zones(reversed(ids), set()) == B.zones(ids, set())


def test_deal_planted_is_seeded_and_keeps_counts():
    pairs = [(f"g{i:02d}", f"l{i:02d}") for i in range(27)]
    dealt = B.deal_planted(pairs)
    assert {z: len(v) for z, v in dealt.items()} == {"test": 10, "dev": 8, "train": 9}
    assert sorted(p for v in dealt.values() for p in v) == pairs
    assert B.deal_planted(list(reversed(pairs))) == dealt, "the input order does not matter"
    assert B.deal_planted(pairs, seed=901) != dealt
    with pytest.raises(ValueError):
        B.deal_planted(pairs[:26])
    zone_map = {x: "train" for p in pairs for x in p}
    moved = B.plant(zone_map, dealt)
    assert moved == 2 * 18 and all(zone_map[a] == zone_map[b] == z for z, v in dealt.items() for a, b in v)
    with pytest.raises(ValueError):
        B.plant({}, dealt)


def test_planted_pairs_use_the_draw_rule_among_fresh_documents_only():
    docs = [_lin("l1", "ENG-11"), _lin("l2", "ENG-12"), _lin("l3", "ENG-13"), _lin("l4", "ENG-14"),
            _pr("g1", "4821", ["ENG-11"]), _pr("g2", "4821", ["ENG-12"]),  # a reused number: neither plantable
            _pr("g3", "5100", ["ENG-13"]), _pr("g4", "5200", ["ENG-13"]),  # two pull requests for ENG-13
            _pr("g5", "6100", ["ENG-14"])]
    index, _, load = _setup(docs)
    fresh = set(index)
    assert B.planted_pairs(index, fresh, load) == [("g5", "l4")]
    assert B.planted_pairs(index, fresh - {"g2"}, load) == [("g1", "l1"), ("g5", "l4")], "a seen document no longer counts"


def _zoned():
    docs = [_lin("l1", "ENG-11"), _pr("g1", "7100", ["ENG-11", "INT-55"]),  # the pair dealt to train; INT-55 must stay out
            _jira("j5", "INT-55"),
            _lin("l2", "ENG-12"), _pr("g2", "7200", ["ENG-12"]),  # meets the rule only inside train: 7200 is reused in dev
            _pr("g9", "7200", ["ENG-90"]),
            _lin("l3", "ENG-13"), _pr("g3", "7300", ["ENG-13"])]  # a pair dealt to test
    index, by_id, load = _setup(docs, n_slack=30)
    zone_map = {d: "train" for d in index} | {"g9": "dev", "l3": "test", "g3": "test"} | {f"s{i}": "dev" for i in range(20, 30)}
    return index, by_id, load, zone_map


def test_a_zone_draw_plants_exactly_its_pairs_and_stays_inside_the_zone():
    index, _, load, zone_map = _zoned()
    _, plain = F.draw(index, {d for d in index if zone_map[d] != "train"}, load, n=12, seed=3, planted=1)
    assert plain["planted_candidates"] == 2, "a plain zone draw would also plant the pair that meets the rule only in the zone"
    ids, info = B.draw(index, zone_map, "train", load, seed=3, n=12, planted=[("g1", "l1")])
    assert info["planted"] == [{"pr": "g1", "issue": "l1"}] and info["planted_candidates"] == 1 and info["zone"] == "train"
    assert {"g1", "l1"} <= set(ids) and all(zone_map[d] == "train" for d in ids)
    assert B.draw(index, zone_map, "train", load, seed=3, n=12, planted=[("g1", "l1")])[0] == ids
    inside = [d for d in index if zone_map[d] == "train"]
    every, info = B.draw(index, zone_map, "train", load, seed=3, n=len(inside), planted=[("g1", "l1")])
    assert set(every) == set(inside) - {"j5"} and info["skipped"] == {"ticket linked by a planted pull request": 1}


def test_a_zone_draw_refuses_the_test_zone_and_pairs_from_other_zones():
    index, _, load, zone_map = _zoned()
    with pytest.raises(PermissionError):
        B.draw(index, zone_map, "test", load, seed=1, n=3, planted=[("g3", "l3")])
    ids, info = B.draw(index, zone_map, "test", load, seed=1, n=3, planted=[("g3", "l3")], preregistered=True)
    assert set(ids) == {"g3", "l3"} and info["planted"] == [{"pr": "g3", "issue": "l3"}]
    with pytest.raises(ValueError):
        B.draw(index, zone_map, "train", load, seed=1, n=5, planted=[("g3", "l3")])
    with pytest.raises(RuntimeError):  # g2 is not a pair the rule allows once its reused number is in the zone
        B.draw(index, zone_map | {"g9": "train"}, "train", load, seed=1, n=5, planted=[("g2", "l2")])


def test_a_zone_draw_checks_each_pair_against_the_rule_among_the_zone_documents():
    docs = [_lin("l1", "ENG-11"), _pr("g1", "7100", ["ENG-11"]), _pr("g4", "7400", ["ENG-11"])]  # two pull requests for ENG-11
    index, _, load = _setup(docs)
    zone_map = {d: "train" for d in index}
    assert F.draw(index, set(), load, n=13, seed=1, planted=1)[1]["planted_candidates"] == 0
    with pytest.raises(RuntimeError, match="rule"):  # hiding g4's link from draw must not let the pair through
        B.draw(index, zone_map, "train", load, seed=1, n=13, planted=[("g1", "l1")])
    zone_map["g4"] = "dev"
    ids, info = B.draw(index, zone_map, "train", load, seed=1, n=12, planted=[("g1", "l1")])
    assert info["planted"] == [{"pr": "g1", "issue": "l1"}] and {"g1", "l1"} <= set(ids) and "g4" not in ids
    with pytest.raises(ValueError, match="lacks 1 documents"):
        B.draw(index, zone_map | {"gone": "train"}, "train", load, seed=1, n=12, planted=[("g1", "l1")])


def _bench(tmp_path):
    """A small benchmark on disk: 4 plantable pairs, other tracker documents and Slack messages."""
    root = tmp_path / "bench"
    src = root / "generated_data" / "sources"
    index = {}
    for i in range(4):
        _write(src / "linear" / f"l{i}.json", {"title": f"issue {i}", "key": f"ENG-{10 + i}", "assignee": "Omar Singh"})
        _write(src / "github" / f"g{i}.json", {"title": f"PR {i}", "pr_number": f"{500 + i}", "linked_linear": [f"ENG-{10 + i}"]})
        index |= {f"l{i}": f"linear/l{i}.json", f"g{i}": f"github/g{i}.json"}
    for i in range(60):
        _write(src / "slack" / f"s{i}.json", {"title": f"message {i}", "text": "hello"})
        index[f"s{i}"] = f"slack/s{i}.json"
    for i in range(8):
        _write(src / "jira" / f"j{i}.json", {"title": f"ticket {i}", "key": f"INT-{20 + i}"})
        index[f"j{i}"] = f"jira/j{i}.json"
    idx = root / "generated_data" / "uuid_index.json"
    idx.write_text(json.dumps(index))
    folder_idx = tmp_path / "index.json"
    folder_idx.write_text(json.dumps({"root": str(src), "index": index}))
    scratch = tmp_path / "scratch"
    _write(scratch / "old" / "haystack.json", {"dsids": [f"s{i}" for i in range(10)]})
    return root, idx, folder_idx, scratch


def test_the_cli_writes_reproducible_zones_and_draws_only_from_allowed_zones(tmp_path, monkeypatch):
    root, idx, folder_idx, scratch = _bench(tmp_path)
    counts = {"test": 1, "dev": 1, "train": 2}
    monkeypatch.setattr(B, "PLANT_COUNTS", counts)
    rep = B.main(["zones", "--scratch", str(scratch), "--index", str(idx), "--root", str(root)])
    zones_path = scratch / "brain" / "zones.json.gz"
    zone_map = json.loads(gzip.decompress(zones_path.read_bytes()))
    assert rep["seen"] == 10 and rep["fresh"] == len(zone_map) == 66 and rep["documents"] == 76
    assert rep["sha256"] == hashlib.sha256(zones_path.read_bytes()).hexdigest()
    assert rep["planted"]["count"] == counts and "test" not in rep["planted"]["pairs"]
    assert sum(v["documents"] for v in rep["zones"].values()) == 66
    first = zones_path.read_bytes()
    B.main(["zones", "--scratch", str(scratch), "--index", str(idx), "--root", str(root)])
    assert zones_path.read_bytes() == first, "the zone file is byte-for-byte reproducible"
    with pytest.raises(SystemExit):
        B.main(["draw", "--zone", "test", "--seed", "1", "--scratch", str(scratch), "--index", str(folder_idx), "--root", str(root),
                "--out", str(tmp_path / "t")])
    assert not (tmp_path / "t").exists()
    out = tmp_path / "train"
    n = min(10, rep["zones"]["train"]["documents"])
    dr = B.main(["draw", "--zone", "train", "--seed", "601", "-n", str(n), "--scratch", str(scratch), "--index", str(folder_idx),
                 "--root", str(root), "--out", str(out)])
    hay = json.loads((out / "haystack.json").read_text())
    assert hay["zone"] == "train" and hay["seed"] == 601 and hay["index"] == str(folder_idx)
    assert len(hay["dsids"]) == hay["n_docs"] == dr["documents"] >= n
    assert all(zone_map[d] == "train" for d in hay["dsids"]) and (out / "index.json").resolve() == folder_idx.resolve()
    assert json.loads((out / "index.json").read_text())["index"].keys() >= set(hay["dsids"]), "the folder reads as other draws do"
    want = sorted((p["pr"], p["issue"]) for p in rep["planted"]["pairs"]["train"])
    assert sorted((p["pr"], p["issue"]) for p in dr["planted"]) == want and all(x in hay["dsids"] for p in want for x in p)
    assert dr["haystack_sha256"] == hashlib.sha256((out / "haystack.json").read_bytes()).hexdigest()
    test = B.write_draw(zones_path, "test", 7, folder_idx, root, tmp_path / "test", n=3, preregistered=True)
    assert len(test["planted"]) == 1 and all(zone_map[d] == "test" for d in json.loads((tmp_path / "test" / "haystack.json").read_text())["dsids"])


def test_a_draw_needs_a_folder_index_of_the_same_benchmark(tmp_path, monkeypatch):
    root, idx, folder_idx, scratch = _bench(tmp_path)
    monkeypatch.setattr(B, "PLANT_COUNTS", {"test": 1, "dev": 1, "train": 2})
    B.main(["zones", "--scratch", str(scratch), "--index", str(idx), "--root", str(root)])
    zones_path = scratch / "brain" / "zones.json.gz"

    def run(index, out):
        return B.main(["draw", "--zone", "train", "--seed", "601", "-n", "8", "--zones", str(zones_path), "--index", str(index),
                       "--root", str(root), "--out", str(out)])

    with pytest.raises(ValueError, match="not a folder index"):  # the flat index used for the zones
        run(idx, tmp_path / "flat")
    assert not (tmp_path / "flat").exists()
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps({"root": str(tmp_path / "other"), "index": json.loads(idx.read_text())}))
    with pytest.raises(ValueError, match="reads documents from"):
        run(elsewhere, tmp_path / "elsewhere")
    out = tmp_path / "train"
    first = run(folder_idx, out)
    assert first["index_sha256"] == hashlib.sha256(folder_idx.read_bytes()).hexdigest()
    assert run(folder_idx, out)["haystack_sha256"] == first["haystack_sha256"], "drawing again into the folder is allowed"
    copy = tmp_path / "copy.json"
    copy.write_bytes(folder_idx.read_bytes())
    with pytest.raises(ValueError, match="another index"):
        run(copy, out)
