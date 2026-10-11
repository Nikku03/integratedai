"""The company brain's fresh draw and held-out unanswerable questions (v16).

- **The fresh draw** (``draw2``) is ``factbank_5k.draw`` over one zone of ``brain_draw``'s zone file, leaving out the
  documents of earlier haystacks (the test draw leaves out test5k's). Its planted pull request -> Linear issue pairs are found
  by draw's own planting rule among the zone's remaining documents (up to ``PLANTED``), not dealt from the zone summary as
  ``brain_draw.draw`` deals them. The test zone is drawn only after the pre-registration (``--i-have-preregistered``). The
  folder is written as ``brain_draw.write_draw`` writes one (haystack.json, the folder index linked as index.json,
  draw_report.json), so that ``brain_test``'s build and ask read it, and haystack.json names the haystacks it left out.
- **Held-out documents** (``heldout``) are documents of the haystack's zone that are neither in it nor in a haystack it left
  out, for natural questions with no answer in the haystack. The sources of ``HELD_SOURCES`` (no Slack: a thread's only name
  is its channel) take equal shares of the target; about ``OVERSAMPLE`` times each share is examined in a seeded order, and a
  document is kept only if (1) none of its anchors (``anchors``: title or subject, ticket key, pull request number, customer
  or account names) is written in the haystack (``brain_questions._written``, between word boundaries); (2) no haystack
  document of its source has a title whose words overlap its title's by a Jaccard of ``TITLE_JACCARD`` or more; and (3) no
  haystack document holds ``SHINGLE_MAX`` or more of its body's 5-word shingles.
- **Packets** (``packets``) follow ``brain_writers``' format with the instruction kind "unanswerable": the writer sees the
  whole document (metadata and body) and writes the question a colleague would naturally ask whose answer is in it, with 1 to
  3 answer facts copied from it. The keys (document, anchors, check values) stay in a separate file, and the packets are also
  cut into batch files of ``BATCH`` for writers (``brain_writers status`` reads them).
- **Collect** (``collect``) runs ``brain_writers.collect``'s prose checks on the writers' outputs (one question, not yes/no,
  not "this document", 1 to 3 facts copied verbatim from the packet's text, none of them in the question), then check (4): no
  single haystack document holds an anchor content word and ``FACT_SHARE`` or more of the answer facts
  (``evidence_audit.present``). The questions kept get family "unanswerable", kind "heldout", expected {"not_found": true}
  and no gold documents.

Two readings were fixed by measurement, since the plain ones keep almost nothing in this benchmark:

- Full person names are anchors, but check (1) leaves them out unless ``person_anchors`` is set. The benchmark reuses a small
  pool of names: with them, 6 of 640 sampled dev-zone documents pass check (1) against dev5k, against 562 without them
  (S/brain2/E_draw/anchors_probe.py). Each run reports how many kept documents would pass with them too.
- An anchor content word, in check (4), is a content word of an anchor (person names included) that at most ``RARE_DF``
  haystack documents hold. With every content word, a generic fact ("p95 under 350ms") and a common word reject 87% of the
  train5k writers' prose questions asked without their gold document (dev5k 98%); with words held by at most 10 documents,
  11% (dev 10%), while 77% (dev 83%) of them are still caught with the gold document in the haystack
  (S/brain2/E_draw/check4_fit.py; chosen on train as the most caught at about 10% rejected, with one word as the design
  says: two words held by at most 50 documents do as well).

    python -m cie.eval.brain2_draw draw --zone dev --seed 1701 --zones $S/brain/zones.json.gz --index $S/mt5k/index.json \\
        --root $BENCH --exclude $S/brain/dev5k --out W
    python -m cie.eval.brain2_draw heldout --work W --zones $S/brain/zones.json.gz --n 60 --seed 1702 --out DIR
    python -m cie.eval.brain2_draw collect --work W --packets P --keys K --outputs O1.jsonl O2.jsonl --out Q.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from cie.eval import brain_draw, factbank_5k
from cie.eval import brain_questions as B
from cie.eval import brain_writers as W
from cie.eval.memory_test import _write_jsonl, render_doc

N_DOCS = 5000
PLANTED = 10
HELD_SOURCES = ("jira", "linear", "hubspot", "google_drive", "confluence", "fireflies", "github", "gmail")
OVERSAMPLE = 1.4
TITLE_JACCARD = 0.5
SHINGLE = 5
SHINGLE_MAX = 0.1
FACT_SHARE = 0.5
RARE_DF = 10  # check (4): an anchor word held by at most this many haystack documents (fixed on train5k, check4_fit.py)
MIN_TEXT = 300  # characters of text (metadata and body) a writer needs
KIND = "unanswerable"
PREFIX = "heldout"
BATCH = 10
TEXT_CHARS = 6_000
TITLE_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "by", "from", "at", "is", "are", "be", "as",
              "into", "via"}
INSTRUCTION = W.INTRO + (
    "Write the question a colleague would naturally ask whose answer is in this document (a fact or a short passage), with "
    "answer_facts copied from it: 1 to 3 short phrases of 2 to 8 words, each copied EXACTLY from the text, that a correct answer "
    "must contain (numbers, names, settings, dates, decisions). Ask it the way someone who has not seen the document would: name "
    'what it is about (the system, customer, project, incident or person), never "this document". The question must not '
    "contain the answer facts and must not be answerable by yes/no. One question. Reply with JSON only: "
    '{"packet_id": "<the packet id>", "question": "<your question>", "answer_facts": ["<fact>", ...]}')
FOUND = "a haystack document holds an anchor word and half the answer facts"


# ------------------------------------------------------------------ the fresh draw
def draw2(index: dict[str, str], zone_map: dict[str, str], zone: str, load: brain_draw.Loader, *, seed: int,
          exclude: Iterable[str] = (), n: int = N_DOCS, planted: int = PLANTED, preregistered: bool = False
          ) -> tuple[list[str], dict[str, Any]]:
    """``n`` documents of one zone that are not in ``exclude``, drawn by ``factbank_5k.draw`` (every source in its share, one
    document per ticket key and pull request number), planting up to ``planted`` pull request -> Linear issue pairs that meet
    draw's rule among the zone's remaining documents. The test zone is drawn only after the pre-registration."""
    if zone == "test" and not preregistered:
        raise PermissionError("the test zone is drawn only after the pre-registration")
    if zone not in brain_draw.ZONES:
        raise ValueError(f"unknown zone {zone!r}")
    exclude = set(exclude)
    zone_docs = {d for d, z in zone_map.items() if z == zone}
    inside = zone_docs - exclude
    if missing := len(inside - set(index)):
        raise ValueError(f"the index lacks {missing} documents of the {zone} zone")
    ids, info = factbank_5k.draw(index, set(index) - inside, load, n=n, seed=seed, planted=planted)
    if stray := len(set(ids) - inside):
        raise RuntimeError(f"draw took {stray} documents from outside the zone or from an excluded haystack")
    pairs = [(p["pr"], p["issue"]) for p in info["planted"]]
    if any(x not in ids for pair in pairs for x in pair):
        raise RuntimeError("a planted pair is not in the draw")
    info = {k: v for k, v in info.items() if k != "excluded"}  # the documents of other zones are not counted
    return ids, {**info, "zone": zone, "seed": seed, "zone_documents": len(zone_docs), "excluded_in_zone": len(zone_docs & exclude)}


def haystack_ids(folder: Path) -> set[str]:
    """The document ids of a haystack folder (its haystack.json's ``dsids``; nothing else is read from it)."""
    return set(json.loads((folder / "haystack.json").read_text()).get("dsids") or [])


def write_draw2(zones_path: Path, zone: str, seed: int, index_path: Path, root: Path, out: Path, exclude: Iterable[Path] = (),
                n: int = N_DOCS, planted: int = PLANTED, preregistered: bool = False, load: brain_draw.Loader | None = None
                ) -> dict[str, Any]:
    """Draw ``n`` documents from one zone, leaving out the documents of the haystack folders in ``exclude``, and write
    ``out``/haystack.json (with the folder index linked as index.json) and ``out``/draw_report.json, as
    ``brain_draw.write_draw`` does."""
    if zone == "test" and not preregistered:
        raise PermissionError("the test zone is drawn only after the pre-registration")
    index = brain_draw.load_folder_index(index_path, root)
    link = out / "index.json"
    if (link.exists() or link.is_symlink()) and link.resolve() != index_path.resolve():
        raise ValueError(f"{link} already names another index ({link.resolve()})")
    rep_z = json.loads(brain_draw.summary_path(zones_path).read_text())
    if brain_draw._sha256(zones_path) != rep_z["sha256"]:
        raise RuntimeError(f"{zones_path} differs from the file its summary describes")
    zone_map = brain_draw.read_zones(zones_path)
    excluded = {str((Path(f) / "haystack.json").resolve()): haystack_ids(Path(f)) for f in exclude}
    ids, info = draw2(index, zone_map, zone, load or brain_draw._loader(root, index), seed=seed,
                      exclude=set().union(*excluded.values()), n=n, planted=planted, preregistered=preregistered)
    out.mkdir(parents=True, exist_ok=True)
    hay = out / "haystack.json"
    hay.write_text(json.dumps({"root": str(root), "n_docs": len(ids), "seed": seed, "base_questions": 0, "documents": len(ids),
                               "zone": zone, "index": str(index_path), "zones_sha256": rep_z["sha256"],
                               "excluded_haystacks": sorted(excluded), "dsids": ids}))
    if not (link.exists() or link.is_symlink()):
        link.symlink_to(index_path.resolve())
    rep = {**info, "n": n, "by_source": brain_draw._by_source(index, ids),
           "excluded_haystacks": {f: {"in_zone": sum(1 for d in v if zone_map.get(d) == zone)} for f, v in sorted(excluded.items())},
           "zones_file": str(zones_path), "zones_sha256": rep_z["sha256"], "index": str(index_path),
           "index_sha256": brain_draw._sha256(index_path), "haystack": str(hay), "haystack_sha256": brain_draw._sha256(hay)}
    (out / "draw_report.json").write_text(json.dumps(rep, indent=1))
    return rep


# ------------------------------------------------------------------ documents and anchors
def read_docs(sources: Path, index: dict[str, str], ids: Iterable[str]) -> list[dict[str, Any]]:
    """Documents read as ``brain_writers.documents`` reads them (id, source, title, raw record, and the ``SourceDoc`` under
    "doc"); a malformed export is left out."""
    from cie.eval.memory_test import _raw
    from cie.ingest.sources import read

    out = []
    for dsid in ids:
        rel = index[dsid]
        try:
            d = read(sources / rel, rel)
        except Exception:  # noqa: BLE001 - a malformed export is left out, as haystack_docs leaves it out
            continue
        out.append({"dsid": dsid, "source": d.source, "title": d.title, "raw": _raw(sources, rel), "doc": d})
    return out


def anchors(d: dict[str, Any]) -> list[dict[str, str]]:
    """The strings a question could name the document by, each {"kind", "text"}: its title or subject, its ticket key or pull
    request number, its customer or account names (``SourceDoc.orgs``) and the full names of its people (``SourceDoc.people``
    that ``brain_questions._person`` takes for a person), without repeats."""
    sd = d["doc"]
    cands = [("title", str(d["title"] or "").strip()), ("key", factbank_5k._key(d) or ""), ("pr", factbank_5k._pr(d) or ""),
             *(("customer", str(o).strip()) for o in sd.orgs),
             *(("person", p) for name, _ in sd.people if (p := B._person(name)))]
    out, seen = [], set()
    for kind, text in cands:
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append({"kind": kind, "text": text})
    return out


def written_text(docs: list[dict[str, Any]]) -> str:
    """The haystack's written text (``brain_questions._written``: titles and every field, in lower case), with JSON's escapes
    of line breaks, tabs and quotes undone, so that a name after a line break stands between word boundaries."""
    return B._written(docs).replace("\\n", " ").replace("\\t", " ").replace('\\"', '"')


def is_written(text: str, s: str) -> bool:
    """Whether ``s`` stands in the written text (lower case), not inside a longer word or number."""
    a = s.lower().strip()
    return bool(a) and a in text and W._holds(text, a)


def title_words(title: Any) -> set[str]:
    """A title's words for the Jaccard check: lower-case letter and digit runs of three or more characters, without a few
    function words."""
    return {w for w in re.findall(r"[a-z0-9]+", str(title or "").lower()) if len(w) > 2 and w not in TITLE_STOP}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def shingles(text: str, k: int = SHINGLE) -> set[str]:
    """The ``k``-word shingles of a text (lower-case letter and digit runs)."""
    w = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return {" ".join(w[i:i + k]) for i in range(len(w) - k + 1)}


def shingle_overlap(held: list[set[str]], texts: Iterable[str]) -> list[float]:
    """For each held-out shingle set, the largest share of it that one of ``texts`` holds."""
    owners: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(held):
        for g in s:
            owners[g].append(i)
    best = [0.0] * len(held)
    for t in texts:
        hits: Counter = Counter()
        for g in shingles(t):
            for i in owners.get(g, ()):
                hits[i] += 1
        for i, c in hits.items():
            best[i] = max(best[i], c / len(held[i]))
    return best


def _text(d: dict[str, Any]) -> str:
    """The document as a writer sees it: every metadata line and body field (``memory_test.render_doc``), without the title."""
    return render_doc(replace(d["doc"], title="")).lstrip("\n")


# ------------------------------------------------------------------ held-out documents
def _hay_zone(hay: dict[str, Any], zone_map: dict[str, str]) -> str:
    """The zone a haystack was drawn from: its own "zone", or the one zone of all its documents."""
    if hay.get("zone"):
        return str(hay["zone"])
    zs = {zone_map.get(d) for d in hay.get("dsids") or []}
    if len(zs) != 1 or None in zs:
        raise ValueError("the haystack names no zone and its documents are not all of one zone")
    return str(zs.pop())


def quotas(sources: list[str], n: int, seed: int) -> dict[str, int]:
    """``n`` split evenly over ``sources``, the remainder going to sources in a seeded order."""
    if not sources:
        return {}
    order = sorted(sources)
    random.Random(f"{seed}/quotas").shuffle(order)
    base, extra = divmod(n, len(order))
    return {s: base + (i < extra) for i, s in enumerate(order)}


def heldout(work: Path, zones_path: Path, n: int, seed: int, *, exclude: Iterable[Path] = (), person_anchors: bool = False,
            oversample: float = OVERSAMPLE, preregistered: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Held-out documents for about ``n`` natural unanswerable questions about the haystack in ``work``, and a report.

    The pool is the haystack's zone less its documents and those of every haystack it left out (haystack.json's
    "excluded_haystacks", and the folders in ``exclude``), in the sources of ``HELD_SOURCES``. Each source gets an equal share
    of ``n`` (``quotas``); ``oversample`` times its share of readable documents with a title and ``MIN_TEXT`` characters of
    text are examined in a seeded order, and those that pass checks (1) to (3) are kept (see the module notes). Each kept
    document comes with its anchors and check values. A haystack drawn from the test zone is read only after the
    pre-registration."""
    hay = json.loads((work / "haystack.json").read_text())
    if hay.get("zone") == "test" and not preregistered:
        raise PermissionError("the test zone is read only after the pre-registration")
    if hay.get("zones_sha256") and brain_draw._sha256(zones_path) != hay["zones_sha256"]:
        raise RuntimeError(f"{zones_path} is not the zone file the haystack was drawn with")
    zone_map = brain_draw.read_zones(zones_path)
    zone = _hay_zone(hay, zone_map)
    if zone == "test" and not preregistered:
        raise PermissionError("the test zone is read only after the pre-registration")
    index = json.loads((work / "index.json").read_text())["index"]
    sources = Path(hay["root"]) / "generated_data" / "sources"
    inside = set(hay["dsids"])
    left_out = [Path(f) for f in hay.get("excluded_haystacks") or []] + [Path(f) / "haystack.json" for f in exclude]
    excluded: set[str] = set()
    for f in left_out:
        excluded |= haystack_ids(f.parent)
    pool: dict[str, list[str]] = defaultdict(list)
    for dsid, z in sorted(zone_map.items()):
        if z == zone and dsid not in inside and dsid not in excluded and dsid in index:
            src = index[dsid].split("/")[0]
            if src in HELD_SOURCES:
                pool[src].append(dsid)
    share = quotas(sorted(pool), n, seed)
    cands: list[dict[str, Any]] = []
    aside: Counter = Counter()
    examined: Counter = Counter()
    for src in sorted(share):
        want = round(oversample * share[src])
        order = list(pool[src])
        random.Random(f"{seed}/{src}").shuffle(order)
        for dsid in order:
            if examined[src] >= want:
                break
            got = read_docs(sources, index, [dsid])
            if not got:
                aside["unreadable"] += 1
                continue
            d = got[0]
            if not str(d["title"] or "").strip():
                aside["no title"] += 1
                continue
            if len(_text(d)) < MIN_TEXT:
                aside["short text"] += 1
                continue
            examined[src] += 1
            cands.append(d)
    docs = read_docs(sources, index, sorted(inside))
    text = written_text(docs)
    titles: dict[str, list[set[str]]] = defaultdict(list)
    for x in docs:
        titles[x["source"]].append(title_words(x["title"]))
    overlap = shingle_overlap([shingles(d["doc"].body) for d in cands], (x["doc"].body for x in docs))
    kept: list[dict[str, Any]] = []
    why_dropped: dict[str, Counter] = defaultdict(Counter)
    written_kinds: Counter = Counter()
    strict_pass = 0
    for d, ov in zip(cands, overlap, strict=True):
        anc = anchors(d)
        written = [a for a in anc if is_written(text, a["text"])]
        written_kinds.update(a["kind"] for a in written)
        in_check1 = [a for a in written if person_anchors or a["kind"] != "person"]
        tw = title_words(d["title"])
        jac = max((jaccard(tw, t) for t in titles[d["source"]]), default=0.0)
        checks = {"anchors_written": [a["text"] for a in in_check1], "title_jaccard": round(jac, 3), "shingle_overlap": round(ov, 4)}
        why = ("anchor written in the haystack" if in_check1 else f"title Jaccard >= {TITLE_JACCARD}" if jac >= TITLE_JACCARD
               else f"shingle overlap >= {SHINGLE_MAX}" if ov >= SHINGLE_MAX else None)
        if why:
            why_dropped[d["source"]][why] += 1
            continue
        strict_pass += not written
        kept.append({"doc": d, "anchors": anc, "checks": checks,
                     "persons_written": [a["text"] for a in written if a["kind"] == "person"]})
    ovs = [k["checks"]["shingle_overlap"] for k in kept]
    rep = {"work": str(work), "zone": zone, "n": n, "seed": seed, "oversample": oversample, "person_anchors": person_anchors,
           "haystack_documents": len(inside), "haystack_readable": len(docs), "excluded_haystacks": [str(f) for f in left_out],
           "pool": {s: len(v) for s, v in sorted(pool.items())}, "quota": dict(sorted(share.items())),
           "examined": dict(sorted(examined.items())), "kept": len(kept),
           "kept_by_source": dict(sorted(Counter(k["doc"]["source"] for k in kept).items())),
           "skipped": dict(sorted(aside.items())), "dropped": {s: dict(c) for s, c in sorted(why_dropped.items())},
           "anchors_written_by_kind": dict(sorted(written_kinds.items())),
           "kept_with_no_person_written": strict_pass,
           "kept_shingle_overlap": {"median": round(statistics.median(ovs), 4) if ovs else None, "max": max(ovs, default=None)},
           "kept_title_jaccard_max": max((k["checks"]["title_jaccard"] for k in kept), default=None)}
    return kept, rep


# ------------------------------------------------------------------ packets
def packets(held: list[dict[str, Any]], seed: int, work: Path | str | None = None
            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """One packet per held-out document in ``brain_writers``' format (instruction kind "unanswerable"; the sources take turns
    in a seeded order, ``brain_writers.spread``), their keys (document, anchors, check values) and a report."""
    pools = {}
    for h in held:
        pools.setdefault(h["doc"]["source"], {"": []})[""].append(h)
    picked = W.spread(pools, len(held), f"{seed}/{KIND}")
    ps, ks = [], []
    for i, h in enumerate(picked, 1):
        d, pid = h["doc"], f"{PREFIX}-{seed}-{i:03d}"
        ps.append({"packet_id": pid, "kind": KIND, "source": d["source"], "system": W.SYSTEMS.get(d["source"], d["source"]),
                   "title": d["title"], "text": W._cut(_text(d), TEXT_CHARS), "instruction": INSTRUCTION})
        ks.append({"packet_id": pid, "kind": KIND, "dsid": d["dsid"], "source": d["source"], "title": d["title"],
                   "anchors": h["anchors"], "checks": h["checks"], "persons_written": h.get("persons_written", []),
                   **({"work": str(work)} if work is not None else {})})
    sizes = [len(p["text"]) for p in ps]
    rep = {"packets": len(ps), "seed": seed, "by_source": dict(sorted(Counter(k["source"] for k in ks).items())),
           "text_chars": {"median": int(statistics.median(sizes)) if sizes else 0, "cut": sum(p["text"].endswith("[...]") for p in ps)}}
    return ps, ks, rep


def batches(ps: list[dict[str, Any]], name: str, size: int = BATCH) -> list[dict[str, Any]]:
    """The packets in batch files of ``size`` for writers, {"batch": "<name>_bNN", "kind", "packets"}, as
    ``brain_writers.batch_status`` reads them."""
    return [{"batch": f"{name}_b{j // size:02d}", "kind": KIND, "packets": ps[j:j + size]} for j in range(0, len(ps), size)]


def write_heldout(work: Path, zones_path: Path, n: int, seed: int, out: Path, exclude: Iterable[Path] = (),
                  person_anchors: bool = False, preregistered: bool = False) -> dict[str, Any]:
    """Choose the held-out documents and write ``out``/<name>.packets.jsonl (for the writers), <name>.keys.jsonl (never for the
    writers), <name>.report.json and batches/<name>_bNN.json, where name is "<work folder>_heldout_<seed>"."""
    held, rep = heldout(work, zones_path, n, seed, exclude=exclude, person_anchors=person_anchors, preregistered=preregistered)
    ps, ks, prep = packets(held, seed, work)
    name = f"{work.name}_{PREFIX}_{seed}"
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / f"{name}.packets.jsonl", ps)
    _write_jsonl(out / f"{name}.keys.jsonl", ks)
    for b in batches(ps, name):
        (out / "batches").mkdir(exist_ok=True)
        (out / "batches" / f"{b['batch']}.json").write_text(json.dumps(b, indent=1))
    rep = {**rep, "packets": prep, "out": str(out / f"{name}.packets.jsonl"), "keys": str(out / f"{name}.keys.jsonl"),
           "batches": str(out / "batches")}
    (out / f"{name}.report.json").write_text(json.dumps(rep, indent=1))
    return rep


# ------------------------------------------------------------------ collect and check (4)
def anchor_stems(anchor_texts: Iterable[str]) -> set[str]:
    """The stemmed content words of the anchors, as ``evidence_audit.fact_terms`` takes a fact's words."""
    from cie.eval.evidence_audit import fact_terms

    return {s for a in anchor_texts for s in fact_terms(str(a))[1]}


class Haystack:
    """The haystack's documents as check (4) reads them: each one's text (``memory_test.render_doc``: title, metadata and
    body), lower-cased, with its stems (``evidence_audit._stems``), and how many documents hold each stem."""

    def __init__(self, docs: list[dict[str, Any]]):
        from cie.eval.evidence_audit import _stems

        self.rows = []
        for d in docs:
            t = render_doc(d["doc"])
            self.rows.append((d["dsid"], t.lower(), _stems(t)))
        self.df = Counter(s for _, _, stems in self.rows for s in stems)

    def anchor_words(self, anchor_texts: Iterable[str], rare: int = RARE_DF) -> set[str]:
        """The anchors' content words (``anchor_stems``) that at most ``rare`` haystack documents hold: the words that tie a
        document to what the held-out one is about."""
        return {w for w in anchor_stems(anchor_texts) if self.df[w] <= rare}

    def holder(self, facts: list[str], anchor_texts: Iterable[str], share: float = FACT_SHARE, rare: int = RARE_DF) -> str | None:
        """The first document that holds an anchor content word (``anchor_words``) and at least ``share`` of the facts (those
        with a number or a content word, each present as ``evidence_audit.present`` finds it), or None."""
        from cie.eval.evidence_audit import present

        facts = B._checkable(facts)
        words = self.anchor_words(anchor_texts, rare)
        if not facts or not words:
            return None
        for dsid, low, stems in self.rows:
            if words & stems and sum(present(f, low, stems) for f in facts) >= share * len(facts):
                return dsid
        return None


def collect(packets: list[dict[str, Any]], keys: list[dict[str, Any]], outputs: Iterable[Any], hay: Haystack
            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The writers' questions that pass ``brain_writers.collect``'s prose checks against the packet's text and check (4)
    against ``hay``, as held-out unanswerable questions (family "unanswerable", kind "heldout", expected {"not_found": true},
    no gold documents; the held-out document, its anchors and the answer facts kept beside them); and the outputs rejected,
    each with its reason."""
    ps = [{**p, "kind": "prose"} for p in packets if p.get("kind") == KIND]
    ks = [{**k, "kind": "prose"} for k in keys if k.get("kind") == KIND]
    by_key = {k["packet_id"]: k for k in ks}
    passed, rejected = W.collect("prose", ps, ks, outputs)
    out = []
    for q in passed:
        key = by_key[q["packet_id"]]
        names = [a["text"] if isinstance(a, dict) else str(a) for a in key.get("anchors") or []]
        if (at := hay.holder(q["answer_facts"], names)) is not None:
            rejected.append({"packet_id": q["packet_id"], "question": q["question"], "answer_facts": q["answer_facts"],
                             "reason": FOUND, "holder": at})
            continue
        out.append({"id": q["id"], "group": PREFIX, "kind": PREFIX, "family": KIND, "question": q["question"],
                    "expected": {"not_found": True}, "gold_docs": [], "pieces": q["answer_facts"], "answer_facts": q["answer_facts"],
                    "heldout_doc": key["dsid"], "anchors": names, "source": key["source"], "packet_id": q["packet_id"]})
    return out, rejected


def load_haystack(work: Path, preregistered: bool = False) -> Haystack:
    """The work folder's haystack for check (4); a folder drawn from the test zone is read only after the pre-registration."""
    hay = json.loads((work / "haystack.json").read_text())
    if hay.get("zone") == "test" and not preregistered:
        raise PermissionError("the test zone is read only after the pre-registration")
    index = json.loads((work / "index.json").read_text())["index"]
    return Haystack(read_docs(Path(hay["root"]) / "generated_data" / "sources", index, sorted(hay["dsids"])))


def score(q: dict[str, Any], row: dict[str, Any] | str) -> float:
    """A held-out question's score: 1 if the answer says not found (``brain_questions.says_not_found``), else 0."""
    answer, route = (row, None) if isinstance(row, str) else (str(row.get("answer") or ""), row.get("route"))
    return float(B.says_not_found(answer, route))


# ------------------------------------------------------------------ the command line
def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain2_draw")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw", help="a fresh draw from one zone, leaving out earlier haystacks")
    d.add_argument("--zone", required=True, choices=brain_draw.ZONES)
    d.add_argument("--seed", type=int, required=True)
    d.add_argument("--zones", required=True, help="the zone file (zones.json.gz, with its _summary.json beside it)")
    d.add_argument("--index", required=True, help='a folder index {"root": <root>/generated_data/sources, "index": {...}}')
    d.add_argument("--root", required=True, help="the benchmark folder (holding generated_data/sources)")
    d.add_argument("--exclude", nargs="*", default=[], help="haystack folders whose documents are left out")
    d.add_argument("--out", required=True)
    d.add_argument("-n", type=int, default=N_DOCS)
    d.add_argument("--planted", type=int, default=PLANTED, help="pull request -> Linear issue pairs to plant, at most")
    d.add_argument("--i-have-preregistered", dest="preregistered", action="store_true", help="allow the test zone")
    h = sub.add_parser("heldout", help="held-out documents and writer packets for natural unanswerable questions")
    h.add_argument("--work", required=True, help="the haystack folder (haystack.json, index.json)")
    h.add_argument("--zones", required=True)
    h.add_argument("--n", type=int, required=True, help="the target number of questions (about 1.4 times as many documents are examined)")
    h.add_argument("--seed", type=int, required=True)
    h.add_argument("--out", required=True, help="the folder for packets, keys, report and batches")
    h.add_argument("--exclude", nargs="*", default=[], help="more haystack folders whose documents are not held out")
    h.add_argument("--person-anchors", action="store_true", help="check (1) covers full person names too")
    h.add_argument("--i-have-preregistered", dest="preregistered", action="store_true", help="allow a test-zone haystack")
    c = sub.add_parser("collect", help="check the writers' outputs and write the held-out questions")
    c.add_argument("--work", required=True)
    c.add_argument("--packets", required=True)
    c.add_argument("--keys", required=True)
    c.add_argument("--outputs", required=True, nargs="+", help="the writers' files, each read on its own (brain_writers.read_batch)")
    c.add_argument("--out", required=True, help="the questions, JSONL")
    c.add_argument("--rejected", default=None, help="the rejected outputs, JSONL (default: <out>.rejected.jsonl)")
    c.add_argument("--i-have-preregistered", dest="preregistered", action="store_true", help="allow a test-zone haystack")
    a = ap.parse_args(argv)
    if a.cmd == "draw":
        if a.zone == "test" and not a.preregistered:
            ap.error("the test zone is drawn only after the pre-registration: pass --i-have-preregistered once it is filed")
        rep = write_draw2(Path(a.zones), a.zone, a.seed, Path(a.index), Path(a.root), Path(a.out), [Path(x) for x in a.exclude],
                          a.n, a.planted, a.preregistered)
    elif a.cmd == "heldout":
        rep = write_heldout(Path(a.work), Path(a.zones), a.n, a.seed, Path(a.out), [Path(x) for x in a.exclude], a.person_anchors,
                            a.preregistered)
    else:
        hay = load_haystack(Path(a.work), a.preregistered)
        outputs = [r for f in a.outputs for r in W.read_batch(Path(f))[0]]
        qs, rejected = collect(W.read_rows(Path(a.packets)), W.read_rows(Path(a.keys)), outputs, hay)
        out = Path(a.out)
        rej = Path(a.rejected) if a.rejected else out.with_name(out.name.removesuffix(".jsonl") + ".rejected.jsonl")
        _write_jsonl(out, qs)
        _write_jsonl(rej, rejected)
        rep = {**W.collect_report(qs, rejected), "out": str(out), "rejected_file": str(rej)}
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
