"""The fair retest of the fact bank: a held-out set with the training set's kinds of questions, other documents, other
wording, and a copy with the information changed (docs/FACTBANK_LEARNING_PREREGISTRATION.md).

* ``testset``: 50 documents and 50 questions that share no document and no question with the training set (the
  50 of docs/FACTBANK_RESULTS.md). The kinds are kept as in training: owners/metadata 26, Linear due dates 10, meeting
  action items 8, pull requests by author 5, Jira tickets by assignee 1.
* **Other wording, other tone.** Each generated question is rewritten with one of a fixed set of alternative wordings
  (seed 8). Each benchmark-written question gets a different register: a casual opener and/or its context clause moved
  to the end. The original wording is kept in ``original``.
* ``changed``: the same documents and questions with the information changed. Every person is renamed to a new name
  that the corpus does not contain, and every ISO date is moved 23 days later, in the documents, the questions and the
  expected answers. The documents are written to a new folder.

    python -m cie.eval.factbank_split testset --from <memory test work> --train <training work> --work $T
    python -m cie.eval.factbank_split changed --work $T --out $C
"""

from __future__ import annotations

import argparse
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from cie.eval.memory_test import _jsonl, _write_jsonl

QUOTAS = {"metadata": 26, "linear_due": 10, "action_due": 8, "github_author": 5, "jira_assignee": 1}
N_DOCS = 50
SEED = 8
SHIFT_DAYS = 23

# alternative wordings, written before any learned model existed; {} fields come from the original question
REWORD = {
    "linear_due": (re.compile(r'^When is the Linear issue "(?P<t>.+)" due\?$'), [
        'What\'s the deadline for the Linear ticket "{t}"?',
        'By what date does "{t}" (Linear) need to be done?',
        'quick one: "{t}" in Linear, when\'s that due?']),
    "action_due": (re.compile(r'^In the meeting "(?P<m>.+)", (?P<o>.+?) took this action item: "(?P<a>.+)"\. When is it due\?$'), [
        '{o} picked up "{a}" in the "{m}" meeting. What\'s the deadline on that?',
        'From "{m}": by when does {o} have to finish "{a}"?']),
    "github_author": (re.compile(r"^List every GitHub pull request authored by (?P<p>.+)\. Give the pull request numbers\.$"), [
        "What PRs has {p} opened on GitHub? Just the numbers.",
        "Which pull requests did {p} write? PR numbers please."]),
    "jira_assignee": (re.compile(r"^List every Jira ticket assigned to (?P<p>.+)\. Give the ticket keys\.$"), [
        "Which Jira tickets are on {p}'s plate? Keys only, please.",
        "{p} has which Jira tickets assigned? I need the keys."]),
}
OPENERS = ["Quick question: ", "Hey, can you check: ", "Do you know ", "I need to find out: "]

FIRST = ["Odalys", "Tiberius", "Wrenna", "Caspian", "Marisol", "Leifur", "Anouk", "Basilio", "Cosima", "Dashiell", "Ilse", "Joaquim",
         "Katrien", "Lisandro", "Mireille", "Nils", "Ottoline", "Pascoe", "Quilla", "Rasmus", "Saoirse", "Thaddeus", "Ulrika", "Valdis",
         "Wilhelmina", "Xanthe", "Yorick", "Zenaida"]
LAST = ["Quennell", "Abernathy", "Lindqvist", "Okonkwo", "Varga", "Haldane", "Ferreira", "Strand", "Moreau", "Brennan", "Iqbal",
        "Kowalczyk", "Ashdown", "Bellweather", "Castellanos", "Dunmore", "Eriksen", "Fairweather", "Galloway", "Hargreave"]


def retone(q: str, rng: random.Random) -> str:
    """A different register for a benchmark-written question, without changing what it asks."""
    m = re.match(r"^(In|On|For) ([^,?]{8,160}), (.+)$", q)
    if m and rng.random() < 0.6:  # the context clause moves to the end
        rest = m.group(3).rstrip("?")
        q = f"{rest[0].upper()}{rest[1:]}, {m.group(1).lower()} {m.group(2)}?"
    if rng.random() < 0.6:
        q = rng.choice(OPENERS) + q[0].lower() + q[1:]
    return q


def reword(q: dict[str, Any], rng: random.Random) -> str:
    if q["kind"] in REWORD:
        rx, alts = REWORD[q["kind"]]
        m = rx.match(q["question"])
        if m:
            return rng.choice(alts).format(**m.groupdict())
    return retone(q["question"], rng)


def testset(src: Path, train: Path, work: Path, seed: int = SEED) -> dict[str, Any]:
    used_docs = set(json.loads((train / "haystack.json").read_text())["dsids"])
    used_q = {q["id"] for q in _jsonl(train / "questions.jsonl")}
    pool = [q for q in _jsonl(src / "questions.jsonl") if q["kind"] in QUOTAS and q.get("expected") and q["id"] not in used_q
            and not set(q["gold_docs"]) & used_docs]
    rng = random.Random(seed)
    rng.shuffle(pool)
    docs: set[str] = set()
    chosen: list[dict[str, Any]] = []
    need = dict(QUOTAS)
    for kind in ("github_author", "jira_assignee"):  # the list questions first: they bring several documents each
        for q in sorted((q for q in pool if q["kind"] == kind), key=lambda q: (len(q["gold_docs"]), q["id"])):
            if need[kind] and len(docs | set(q["gold_docs"])) <= N_DOCS - 30:
                docs |= set(q["gold_docs"])
                chosen.append(q)
                need[kind] -= 1
    for q in pool:
        if need.get(q["kind"]) and q not in chosen and len(docs | set(q["gold_docs"])) <= N_DOCS:
            docs |= set(q["gold_docs"])
            chosen.append(q)
            need[q["kind"]] -= 1
    for q in pool:  # then questions about documents already in, of the same kinds, up to 50 questions
        if len(chosen) >= 50:
            break
        if q not in chosen and set(q["gold_docs"]) <= docs:
            chosen.append(q)
    hay = json.loads((src / "haystack.json").read_text())
    rest = [d for d in hay["dsids"] if d not in docs and d not in used_docs]
    rng.shuffle(rest)
    dsids = sorted(docs | set(rest[: max(0, N_DOCS - len(docs))]))
    for q in chosen:
        q["original"] = q["question"]
        q["question"] = reword(q, rng)
    work.mkdir(parents=True, exist_ok=True)
    (work / "haystack.json").write_text(json.dumps({"root": hay["root"], "n_docs": N_DOCS, "seed": seed, "base_questions": 0,
                                                    "documents": len(dsids), "dsids": dsids}))
    if not (work / "index.json").exists():
        (work / "index.json").symlink_to((src / "index.json").resolve())
    _write_jsonl(work / "questions.jsonl", chosen)
    return {"questions": len(chosen), "documents": len(dsids), "missing_quota": {k: v for k, v in need.items() if v},
            "overlap_with_training_docs": len(set(dsids) & used_docs)}


# ------------------------------------------------------------------ changed information
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def shift_dates(s: str, days: int = SHIFT_DAYS) -> str:
    def f(m):
        try:
            return (date(int(m.group(1)), int(m.group(2)), int(m.group(3))) + timedelta(days=days)).isoformat()
        except ValueError:
            return m.group(0)
    return _ISO.sub(f, s)


def rename(s: str, names: dict[str, str]) -> str:
    for old, new in names.items():
        s = s.replace(old, new)
        s = s.replace(old.lower().replace(" ", "_"), new.lower().replace(" ", "_"))
        s = s.replace(old.lower().replace(" ", "."), new.lower().replace(" ", "."))
    return s


def _walk(v: Any, fn) -> Any:
    if isinstance(v, str):
        return fn(v)
    if isinstance(v, list):
        return [_walk(x, fn) for x in v]
    if isinstance(v, dict):
        return {k: _walk(x, fn) for k, x in v.items()}
    return v


def changed(work: Path, out: Path, seed: int = SEED) -> dict[str, Any]:
    from cie.ingest.sources import PEOPLE_FIELDS, as_list, person_name

    hay = json.loads((work / "haystack.json").read_text())
    index = json.loads((work / "index.json").read_text())["index"]
    root = Path(hay["root"])
    src = root / "generated_data" / "sources"
    raws = {d: json.loads((src / index[d]).read_text(errors="replace")) for d in hay["dsids"] if index[d].endswith(".json")}
    people: set[str] = set()
    for raw in raws.values():
        for f in PEOPLE_FIELDS:
            for item in as_list(raw.get(f)):
                n = person_name(item)
                if n:
                    people.add(n)
    qs = _jsonl(work / "questions.jsonl")
    for q in qs:
        v = (q.get("expected") or {}).get("value")
        if v and person_name(v):
            people.add(person_name(v))
    rng = random.Random(seed)
    fresh = [f"{a} {b}" for a in FIRST for b in LAST]
    rng.shuffle(fresh)
    corpus = "\n".join(json.dumps(r) for r in raws.values())
    fresh = [n for n in fresh if n not in corpus]
    names = {p: fresh[i] for i, p in enumerate(sorted(people, key=lambda p: (-len(p), p)))}  # longest first: no partial overlap

    def fn(s: str) -> str:
        return shift_dates(rename(s, names))

    new_root = out / "erb_changed"
    for d, raw in raws.items():
        p = new_root / "generated_data" / "sources" / index[d]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_walk(raw, fn), ensure_ascii=False))
    out.mkdir(parents=True, exist_ok=True)
    (out / "haystack.json").write_text(json.dumps({**hay, "root": str(new_root.resolve())}))
    if not (out / "index.json").exists():
        (out / "index.json").symlink_to((work / "index.json").resolve())
    for q in qs:
        q["question"] = fn(q["question"])
        q["original"] = fn(q.get("original", q["question"]))
        q["expected"] = _walk(q["expected"], fn)
        if q.get("pieces"):
            q["pieces"] = _walk(q["pieces"], fn)
    _write_jsonl(out / "questions.jsonl", qs)
    (out / "renamed.json").write_text(json.dumps(names, indent=1))
    return {"documents": len(raws), "people_renamed": len(names), "date_shift_days": SHIFT_DAYS}


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.factbank_split")
    ap.add_argument("cmd", choices=["testset", "changed"])
    ap.add_argument("--work", required=True)
    ap.add_argument("--from", dest="src")
    ap.add_argument("--train")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = testset(Path(a.src), Path(a.train), Path(a.work)) if a.cmd == "testset" else changed(Path(a.work), Path(a.out))
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
