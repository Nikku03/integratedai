"""The company brain's fresh documents (v15): the documents no earlier set has used, split once into test, development and
training zones, and 5,000-document draws from one zone.

- **Seen** documents are those of every haystack under the scratch folder (``seen_documents``); they get no zone.
- **Zones** come from a salted hash of the document id: 2 in 10 test, 2 in 10 development, 6 in 10 training (``zones``).
- **Planted pull requests:** the pull request -> Linear issue pairs that meet ``factbank_5k.draw``'s planting rule among the
  fresh documents are dealt to the zones by a seeded shuffle, both documents of a pair to one zone (``deal_planted``).
- **Draws** are ``factbank_5k.draw`` over one zone, planting exactly that zone's pairs (``draw``). The test zone is drawn only
  after the pre-registration (``--i-have-preregistered``); until then only its counts are written.

``zones`` takes the flat dsid -> path index (uuid_index.json). ``draw`` takes a folder index, ``{"root": <benchmark>/
generated_data/sources, "index": {dsid: path}}`` (mt5k/index.json), because it links the index into the draw folder as
index.json and the readers of a draw folder expect that format.

    python -m cie.eval.brain_draw zones --scratch $S --index $BENCH/generated_data/uuid_index.json --root $BENCH
    python -m cie.eval.brain_draw draw --zone train --seed 601 --zones $S/brain/zones.json.gz --index $S/mt5k/index.json \\
        --root $BENCH --out $S/brain/train5k
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from cie.eval import factbank_5k

SALT = "brain-zones-v1"
ZONES = ("test", "dev", "train")
PLANT_SEED = 900
PLANT_COUNTS = {"test": 10, "dev": 8, "train": 9}
N_DOCS = 5000
SKIP = {"EnterpriseRAG-Bench", "brain"}

Pair = tuple[str, str]
Loader = Callable[[list[str]], list[dict[str, Any]]]


def seen_sets(scratch: Path) -> dict[str, set[str]]:
    """Every seen set under ``scratch`` by its relative path: each haystack.json outside the benchmark and ``brain/`` (hidden
    folders skipped and linked folders followed, as a recursive ``glob`` does), and the two older lists at the top,
    t5k_dsids.txt and hay5k_docs.json. An unreadable haystack.json is left out."""
    out: dict[str, set[str]] = {}
    for dirpath, dirnames, filenames in os.walk(scratch, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP)
        if "haystack.json" in filenames:
            f = Path(dirpath) / "haystack.json"
            try:
                out[str(f.relative_to(scratch))] = set(json.loads(f.read_text()).get("dsids") or [])
            except (OSError, ValueError, AttributeError):
                continue
    t5k, hay5k = scratch / "t5k_dsids.txt", scratch / "hay5k_docs.json"
    if t5k.exists():
        out["t5k_dsids.txt"] = {x.strip() for x in t5k.read_text().splitlines() if x.strip()}
    if hay5k.exists():
        out["hay5k_docs.json"] = {d["dsid"] for d in json.loads(hay5k.read_text())}
    return out


def seen_documents(scratch: Path) -> set[str]:
    """Every document an earlier set under ``scratch`` has used (``seen_sets``)."""
    return set().union(*seen_sets(scratch).values())


def zone_of(dsid: str, salt: str = SALT) -> str:
    """The hash zone of one document: sha256 of salt and id, modulo 10; 0-1 test, 2-3 dev, 4-9 train."""
    h = int(hashlib.sha256((salt + dsid).encode()).hexdigest(), 16) % 10
    return "test" if h < 2 else "dev" if h < 4 else "train"


def zones(all_dsids: Iterable[str], seen: set[str], salt: str = SALT) -> dict[str, str]:
    """The hash zone of every document not in ``seen``."""
    return {d: zone_of(d, salt) for d in sorted(all_dsids) if d not in seen}


def planted_pairs(index: dict[str, str], fresh: set[str], load: Loader) -> list[Pair]:
    """Every (pull request, Linear issue) pair that meets ``factbank_5k.draw``'s planting rule among the ``fresh`` documents,
    sorted. Draw is asked for no documents and every candidate, so the rule is draw's own."""
    _, info = factbank_5k.draw(index, set(index) - fresh, load, n=0, planted=len(index))
    return sorted((p["pr"], p["issue"]) for p in info["planted"])


def deal_planted(pairs: list[Pair], seed: int = PLANT_SEED, counts: dict[str, int] | None = None) -> dict[str, list[Pair]]:
    """The pairs dealt to the zones: shuffled with ``seed``, then the first ``counts['test']`` to test, the next to dev, the
    rest to train."""
    counts = counts or PLANT_COUNTS
    if sum(counts.values()) != len(pairs):
        raise ValueError(f"{len(pairs)} planted pairs to deal, but the counts {counts} add up to {sum(counts.values())}")
    order = sorted(pairs)
    random.Random(seed).shuffle(order)
    out: dict[str, list[Pair]] = {}
    i = 0
    for z in ZONES:
        out[z] = sorted(order[i:i + counts.get(z, 0)])
        i += counts.get(z, 0)
    return out


def plant(zone_map: dict[str, str], dealt: dict[str, list[Pair]]) -> int:
    """Put both documents of each dealt pair in its zone, over their hash zone; the number of documents moved."""
    moved = 0
    for z, pairs in dealt.items():
        for pair in pairs:
            for dsid in pair:
                if dsid not in zone_map:
                    raise ValueError(f"planted document {dsid} has no zone (seen, or not in the index)")
                moved += zone_map[dsid] != z
                zone_map[dsid] = z
    return moved


def build_zones(index: dict[str, str], seen: set[str], load: Loader, salt: str = SALT, seed: int = PLANT_SEED,
                counts: dict[str, int] | None = None) -> tuple[dict[str, str], dict[str, list[Pair]], int]:
    """The zone of every fresh document with the planted pairs dealt and placed, the dealt pairs, and the documents moved."""
    zone_map = zones(index, seen, salt)
    dealt = deal_planted(planted_pairs(index, set(zone_map), load), seed, counts)
    return zone_map, dealt, plant(zone_map, dealt)


def draw(index: dict[str, str], zone_map: dict[str, str], zone: str, load: Loader, *, seed: int, n: int = N_DOCS,
         planted: Iterable[Pair] = (), preregistered: bool = False) -> tuple[list[str], dict[str, Any]]:
    """``factbank_5k.draw`` over the documents of one zone, planting exactly ``planted``.

    Each planted pair must first meet draw's rule among the zone's own documents (no second pull request linking the issue, no
    reused number or key). Draw plants pull requests that meet its rule inside its pool, and a zone holds pairs that meet it
    only there (the other document with that pull request number is in another zone, say). The loader handed to draw therefore
    hides the Linear links of every other pull request. Nothing else in draw reads them, so the sample is draw's own, with
    ``planted`` as its only candidates; draw still keeps out the other tickets a planted pull request links."""
    if zone == "test" and not preregistered:
        raise PermissionError("the test zone is drawn only after the pre-registration")
    if zone not in ZONES:
        raise ValueError(f"unknown zone {zone!r}")
    planted = sorted(planted)
    inside = {d for d, z in zone_map.items() if z == zone}
    if missing := len(inside - set(index)):
        raise ValueError(f"the index lacks {missing} documents of the {zone} zone")
    outside = sorted(x for pair in planted for x in pair if x not in inside)
    if outside:
        raise ValueError(f"{len(outside)} planted documents are not in the {zone} zone")
    stale = sorted(set(planted) - set(planted_pairs(index, inside, load)))
    if stale:
        raise RuntimeError(f"{len(stale)} planted pairs do not meet draw's rule among the {zone} zone's documents")
    prs = {pr for pr, _ in planted}

    def view(ids: list[str]) -> list[dict[str, Any]]:
        return [d if d["source"] != "github" or d["dsid"] in prs else
                {**d, "raw": {k: v for k, v in d["raw"].items() if k != "linked_linear"}} for d in load(ids)]

    ids, info = factbank_5k.draw(index, set(index) - inside, view, n=n, seed=seed, planted=len(planted))
    got = sorted((p["pr"], p["issue"]) for p in info["planted"])
    if got != planted:
        raise RuntimeError(f"draw planted {len(got)} pairs, not the zone's {len(planted)}")
    return ids, {**info, "zone": zone, "seed": seed}


def _by_source(index: dict[str, str], ids: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(index[d].split("/")[0] for d in ids).items()))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_index(path: Path) -> dict[str, str]:
    """A dsid -> relative path index, flat (uuid_index.json) or under ``index`` (a haystack folder's index.json)."""
    d = json.loads(path.read_text())
    return d["index"] if isinstance(d.get("index"), dict) else d


def load_folder_index(path: Path, root: Path) -> dict[str, str]:
    """The dsid -> relative path index of a folder index, ``{"root": <root>/generated_data/sources, "index": {...}}``
    (mt5k/index.json), the format the readers of a draw folder expect in its index.json."""
    d = json.loads(path.read_text())
    if not (isinstance(d, dict) and isinstance(d.get("root"), str) and isinstance(d.get("index"), dict)):
        raise ValueError(f"{path} is not a folder index: draw links it as index.json, whose readers need "
                         '{"root": <benchmark>/generated_data/sources, "index": {dsid: path}} (mt5k/index.json, say), '
                         "not a flat dsid -> path map such as uuid_index.json")
    if Path(d["root"]).resolve() != (root / "generated_data" / "sources").resolve():
        raise ValueError(f"{path} reads documents from {d['root']}, not from {root / 'generated_data' / 'sources'}")
    return d["index"]


def _loader(root: Path, index: dict[str, str]) -> Loader:
    from cie.eval.memory_test import haystack_docs

    sources = root / "generated_data" / "sources"
    return lambda ids: haystack_docs(sources, index, ids)


def summary_path(zones_path: Path) -> Path:
    return zones_path.with_name(zones_path.name.split(".")[0] + "_summary.json")


def write_zones(scratch: Path, index_path: Path, root: Path, out: Path, load: Loader | None = None) -> dict[str, Any]:
    """Build the zones and write ``out`` (gzip JSON, dsid -> zone, fresh documents only, byte-for-byte reproducible) and its
    summary: counts per zone and source, the file's sha256, the seen sets, and the planted pairs of the training and development
    zones (only their number for the test zone)."""
    index = load_index(index_path)
    sets = seen_sets(scratch)
    seen = set().union(*sets.values())
    zone_map, dealt, moved = build_zones(index, seen, load or _loader(root, index))
    body = json.dumps(zone_map, sort_keys=True, separators=(",", ":")).encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
    members: dict[str, list[str]] = defaultdict(list)
    for d, z in zone_map.items():
        members[z].append(d)
    rep = {"file": str(out), "sha256": _sha256(out), "sha256_json": hashlib.sha256(body).hexdigest(), "salt": SALT,
           "index": str(index_path), "documents": len(index), "seen": len(seen), "fresh": len(zone_map),
           "not_in_index": len(seen - set(index)), "by_source_all": _by_source(index, index),
           "zones": {z: {"documents": len(members[z]), "by_source": _by_source(index, members[z])} for z in ZONES},
           "planted": {"seed": PLANT_SEED, "candidates": sum(len(v) for v in dealt.values()),
                       "count": {z: len(dealt[z]) for z in ZONES}, "moved_from_hash_zone": moved,
                       "pairs": {z: [{"pr": a, "issue": b} for a, b in dealt[z]] for z in ZONES if z != "test"}},
           "seen_sets": {k: len(v) for k, v in sorted(sets.items())}}
    summary_path(out).write_text(json.dumps(rep, indent=1))
    return rep


def read_zones(path: Path) -> dict[str, str]:
    return json.loads(gzip.decompress(path.read_bytes()))


def zone_pairs(zones_path: Path, zone: str, index: dict[str, str], load: Loader) -> list[Pair]:
    """The zone's planted pairs: from the summary for training and development; for the test zone, dealt again from the
    frozen fresh documents (the summary holds only their number), and checked against the zone file."""
    rep = json.loads(summary_path(zones_path).read_text())
    if zone != "test":
        return sorted((p["pr"], p["issue"]) for p in rep["planted"]["pairs"][zone])
    zone_map = read_zones(zones_path)
    pairs = deal_planted(planted_pairs(index, set(zone_map), load))["test"]
    if len(pairs) != rep["planted"]["count"]["test"] or any(zone_map.get(x) != "test" for p in pairs for x in p):
        raise RuntimeError("the test zone's planted pairs no longer match the zone file")
    return pairs


def write_draw(zones_path: Path, zone: str, seed: int, index_path: Path, root: Path, out: Path, n: int = N_DOCS,
               preregistered: bool = False, load: Loader | None = None) -> dict[str, Any]:
    """Draw ``n`` documents from one zone and write ``out``/haystack.json (with the folder index linked as index.json, as the
    other draws do) and ``out``/draw_report.json."""
    if zone == "test" and not preregistered:
        raise PermissionError("the test zone is drawn only after the pre-registration")
    index = load_folder_index(index_path, root)
    link = out / "index.json"
    if (link.exists() or link.is_symlink()) and link.resolve() != index_path.resolve():
        raise ValueError(f"{link} already names another index ({link.resolve()})")
    rep_z = json.loads(summary_path(zones_path).read_text())
    if _sha256(zones_path) != rep_z["sha256"]:
        raise RuntimeError(f"{zones_path} differs from the file its summary describes")
    load = load or _loader(root, index)
    zone_map = read_zones(zones_path)
    planted = zone_pairs(zones_path, zone, index, load)
    ids, info = draw(index, zone_map, zone, load, seed=seed, n=n, planted=planted, preregistered=preregistered)
    out.mkdir(parents=True, exist_ok=True)
    hay = out / "haystack.json"
    hay.write_text(json.dumps({"root": str(root), "n_docs": len(ids), "seed": seed, "base_questions": 0, "documents": len(ids),
                               "zone": zone, "index": str(index_path), "zones_sha256": rep_z["sha256"], "dsids": ids}))
    if not (link.exists() or link.is_symlink()):
        link.symlink_to(index_path.resolve())
    rep = {**info, "n": n, "zone_documents": sum(1 for z in zone_map.values() if z == zone), "by_source": _by_source(index, ids),
           "zones_file": str(zones_path), "zones_sha256": rep_z["sha256"], "index": str(index_path),
           "index_sha256": _sha256(index_path), "haystack": str(hay), "haystack_sha256": _sha256(hay)}
    (out / "draw_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain_draw")
    ap.add_argument("cmd", choices=["zones", "draw"])
    ap.add_argument("--scratch", help="zones: the folder whose haystacks are the seen documents")
    ap.add_argument("--index", required=True, help="zones: the flat dsid -> path index (uuid_index.json); draw: a folder index "
                    '{"root": <root>/generated_data/sources, "index": {...}} (mt5k/index.json), linked into the folder as index.json')
    ap.add_argument("--root", required=True, help="the benchmark folder (holding generated_data/sources)")
    ap.add_argument("--zones", default=None, help="the zone file (default: <scratch>/brain/zones.json.gz)")
    ap.add_argument("--zone", choices=ZONES)
    ap.add_argument("--seed", type=int)
    ap.add_argument("-n", type=int, default=N_DOCS)
    ap.add_argument("--out")
    ap.add_argument("--i-have-preregistered", dest="preregistered", action="store_true",
                    help="draw: allow the test zone (only after the pre-registration)")
    a = ap.parse_args(argv)
    if a.zones is None and a.scratch is None:
        ap.error("--zones or --scratch is needed")
    zones_path = Path(a.zones) if a.zones else Path(a.scratch) / "brain" / "zones.json.gz"
    if a.cmd == "zones":
        if a.scratch is None:
            ap.error("zones needs --scratch")
        rep = write_zones(Path(a.scratch), Path(a.index), Path(a.root), zones_path)
        rep = {k: v for k, v in rep.items() if k != "seen_sets"} | {"seen_sets": len(rep["seen_sets"])}
    else:
        if a.zone is None or a.seed is None or a.out is None:
            ap.error("draw needs --zone, --seed and --out")
        if a.zone == "test" and not a.preregistered:
            ap.error("the test zone is drawn only after the pre-registration: pass --i-have-preregistered once it is filed")
        rep = write_draw(zones_path, a.zone, a.seed, Path(a.index), Path(a.root), Path(a.out), a.n, a.preregistered)
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
