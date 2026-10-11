"""Messy wordings for the company brain's round-2 test (v16): the test's generated questions, reworded the way people type.

The question generators (``brain_questions``, ``brain2_questions``) write tidy templates ("How many Jira tickets have priority
P1?"). People type "hey how many p1 tickets do we have in jira rn?". This module turns the test's generated questions into
blind rewriters' packets and collects the rewrites back:

- **packets:** every generated question (not the writers' own questions: free text, descriptive and held-out, which the
  writers already wrote in a casual style) goes to a rewriter as its text alone, with no document and no answer, in batches.
- **collect:** a rewrite is kept only when it still names everything the question needs to be answered (``anchors``):
  - every ticket key, pull request number and other token holding a digit (dates, cycles, "P1");
  - every capitalised word that does not open a sentence (people, systems, field values such as "Done");
  - at least ``TITLE_SHARE`` of the content words of each quoted title or quote.

  Case and punctuation may change. A rewrite also has to stay one question, ending in one question mark, without new
  quotes of its own. Kept rewrites replace the question's wording; the expected answer is unchanged. A question whose rewrite
  is rejected is left out of the messy set, with its reason.
- **folders:** the messy set gets its own work folder next to the tidy one, sharing its banks (symlinks), so every arm answers
  the same questions in both wordings.

    python -m cie.eval.brain2_messy packets --work W --out DIR --per 40 [--i-have-preregistered]
    python -m cie.eval.brain2_messy collect --work W --batches DIR --outputs DIR --out W_MESSY [--small WS --small-out WS_MESSY]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from cie.eval.brain_writers import read_batch
from cie.factbank.brain import PR_NUMBER, TICKET
from cie.factbank.engine import STOP
from cie.factbank.plans import QUOTED

PER_BATCH = 40
TITLE_SHARE = 0.6
WRITERS_KINDS = frozenset(("prose", "descriptive", "heldout"))  # written by the writers, in a casual style already
SHARED = ("haystack.json", "index.json", "banks.json", "factbank.sqlite", "factbank_v2.sqlite", "factbank_build.json",
          "factbank_v2_build.json", "draw_report.json")
DIGIT_TOKEN = re.compile(r"[A-Za-z0-9][\w./:-]*\d[\w./:-]*|\d[\w./:-]*")
CAP_WORD = re.compile(r"(?<![\w'])([A-Z][\w'&.-]*)")
WORD = re.compile(r"[a-z0-9]+")
POSSESSIVE = re.compile(r"['\u2019]s$")
REASONS = ("no rewrite", "not one question", "new quotes", "drops a quoted title")
INSTRUCTION = ("Rewrite each question the way a busy colleague would actually type it into a work chat or a search box. Make it "
               "messy and human: often lower case, short, casual, maybe a greeting or a bit of context first ('hey', 'quick q', "
               "'for the board deck'), abbreviations people use (pls, asap, w/, rn, fyi), an indirect ask ('do you know', 'can "
               "someone remind me', 'need'), words in a different order, an occasional typo in an ordinary word. Keep the meaning "
               "exactly: ask for the same thing about the same thing. Keep every ticket key, pull request number, date, number, "
               "person's name, system name (Jira, Linear, HubSpot, Slack, Gmail...), status or other value, and the words of any "
               "quoted title or quote, spelled exactly as given (you may change their case and drop the quote marks). One "
               "question, ending with one question mark.")


def is_generated(q: dict[str, Any]) -> bool:
    """A question made by a generator, not written by a writer."""
    return q.get("kind") not in WRITERS_KINDS and q.get("family") != "prose"


def _words(s: str) -> list[str]:
    return [w for w in WORD.findall(s.lower()) if w not in STOP and len(w) >= 2]


def anchors(question: str) -> dict[str, list]:
    """What a rewrite must keep: tokens (keys, pull request numbers, tokens holding a digit, capitalised words that do not open
    a sentence) and the content words of each quote."""
    quotes = [m.group(0)[1:-1] for m in QUOTED.finditer(question)]
    rest = QUOTED.sub(" ", question)
    tokens = [m.group(0) for m in TICKET.finditer(rest)] + [m.group(1) for m in PR_NUMBER.finditer(rest)]
    tokens += [m.group(0).strip(".-/:") for m in DIGIT_TOKEN.finditer(rest)]
    for m in CAP_WORD.finditer(rest):
        before = rest[:m.start()].rstrip()
        if before and before[-1] not in ".?!:":
            tokens.append(POSSESSIVE.sub("", m.group(1)).rstrip(".'"))
    return {"tokens": list(dict.fromkeys(t for t in tokens if t)), "quotes": [w for w in (_words(q) for q in quotes) if w]}


def why_rejected(original: str, rewrite: Any) -> str | None:
    """Why a rewrite cannot stand for the question, or None."""
    if not isinstance(rewrite, str) or not rewrite.strip():
        return "no rewrite"
    r = " ".join(rewrite.split())
    if not r.endswith("?") or r.count("?") != 1:
        return "not one question"
    if len(QUOTED.findall(r)) > len(QUOTED.findall(original)):
        return "new quotes"
    low = r.lower()
    flat = re.sub(r"[^a-z0-9]+", " ", low)
    a = anchors(original)
    for t in a["tokens"]:
        tl = t.lower()
        if tl not in low and " ".join(WORD.findall(tl)) not in flat:
            return f"drops {t!r}"
    have = set(WORD.findall(low))
    for qw in a["quotes"]:
        if sum(1 for w in qw if w in have) < TITLE_SHARE * len(qw):
            return "drops a quoted title"
    return None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_packets(work: Path, out: Path, per: int = PER_BATCH) -> dict[str, Any]:
    """The rewriters' batches: ``<out>/<name>_messy_bNN.json``, each {batch, instruction, packets: [{packet_id, question}]},
    holding only the questions' text."""
    qs = [q for q in _jsonl(work / "questions.jsonl") if is_generated(q)]
    out.mkdir(parents=True, exist_ok=True)
    name = f"{work.name}_messy"
    batches = []
    for i in range(0, len(qs), per):
        b = f"{name}_b{i // per:02d}"
        (out / f"{b}.json").write_text(json.dumps({"batch": b, "instruction": INSTRUCTION,
                                                   "packets": [{"packet_id": q["id"], "question": q["question"]} for q in qs[i:i + per]]},
                                                  indent=1))
        batches.append(b)
    return {"questions": len(qs), "batches": batches}


def collect(work: Path, batches: Path, outputs: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The messy question set: every writer's question as it is, and every generated question whose rewrite is kept, with
    its rewrite as the question and the tidy wording under "clean_question". The report counts what was kept (in all and by
    batch) and, by category alone, why the rest was not."""
    written: dict[str, Any] = {}
    reading: dict[str, str] = {}
    batch_of: dict[str, str] = {}
    kept: Counter = Counter()
    for f in sorted(batches.glob("*.json")):
        batch = json.loads(f.read_text())
        b = batch["batch"]
        batch_of.update({str(pk["packet_id"]): b for pk in batch["packets"]})
        path = outputs / f"{b}.jsonl"
        if not path.exists():
            reading[b] = "missing"
            continue
        rows, how = read_batch(path)
        reading[b] = how
        for r in rows:
            if isinstance(r, dict) and r.get("packet_id") is not None:
                written.setdefault(str(r["packet_id"]), r.get("question"))
    out, why = [], Counter()
    for q in _jsonl(work / "questions.jsonl"):
        if not is_generated(q):
            out.append(q)
            continue
        if q["id"] not in written:
            why["not rewritten"] += 1
            continue
        reason = why_rejected(q["question"], written[q["id"]])
        if reason:
            why[reason if reason in REASONS else "drops a token"] += 1  # the reason's category: never the question's words
            continue
        out.append({**q, "question": " ".join(written[q["id"]].split()), "clean_question": q["question"], "messy": True})
        kept[batch_of[q["id"]]] += 1
    gen = sum(1 for q in _jsonl(work / "questions.jsonl") if is_generated(q))
    return out, {"generated": gen, "kept": sum(1 for q in out if q.get("messy")), "rejected": dict(why), "batches": reading,
                 "kept_by_batch": {b: kept[b] for b in reading}}


def messy_folder(work: Path, out: Path, questions: list[dict[str, Any]]) -> None:
    """A work folder for the messy set: the tidy folder's banks and documents linked, the messy questions written."""
    out.mkdir(parents=True, exist_ok=False)
    for n in SHARED:
        if (work / n).exists():
            os.symlink((work / n).resolve(), out / n)
    (out / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in questions))
    if (work / "questions_report.json").exists():
        rep = json.loads((work / "questions_report.json").read_text())
        (out / "questions_report.json").write_text(json.dumps({**rep, "messy_of": str(work)}, indent=1))


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain2_messy", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("packets", help="the rewriters' batches of a work folder's generated questions")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--per", type=int, default=PER_BATCH)
    c = sub.add_parser("collect", help="check the rewrites and write the messy work folder(s)")
    c.add_argument("--work", type=Path, required=True)
    c.add_argument("--batches", type=Path, required=True)
    c.add_argument("--outputs", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True, help="the messy work folder (new)")
    c.add_argument("--small", type=Path, default=None, help="the tidy small control folder")
    c.add_argument("--small-out", type=Path, default=None, help="the messy small control folder (new)")
    a = ap.parse_args(argv)
    if a.cmd == "packets":
        rep = write_packets(a.work, a.out, a.per)
        print(json.dumps(rep))
        return rep
    qs, rep = collect(a.work, a.batches, a.outputs)
    messy_folder(a.work, a.out, qs)
    if a.small and a.small_out:
        ids = {q["id"] for q in _jsonl(a.small / "questions.jsonl")}
        messy_folder(a.small, a.small_out, [q for q in qs if q["id"] in ids])
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
