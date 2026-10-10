"""Packets for blind question writers, and the checks on what they write (the company brain, fact bank v15).

Writers who know nothing about the brain write two kinds of questions about one document each:

* **descriptive:** a question for one field of a document (its owner, status, due date...) that names the document by what
  it is about, not by its title. The packet holds the document as text without that field's line and without any other
  metadata line or list item that gives the answer; the expected answer, in the form ``brain_questions`` gives that field
  (``_expected``), stays in a separate key file.
* **prose:** a question whose answer is written in a document's body, with 1 to 3 answer facts copied from it. The packet
  holds the title and the body, without the metadata fields.

``packets`` deals one packet per document of a work folder (haystack.json, index.json): the sources take turns in a seeded
order, and for descriptive packets each source's fields take turns too; a document that a question of the folder's
questions.jsonl uses is dealt only when no other is left. ``collect`` checks each writer's output against its packet and
key and turns those that pass into questions in ``brain_questions``' schema, as ``brain_test.load_descriptive`` and
``brain_questions.load_prose`` read them.

    python -m cie.eval.brain_writers packets --work W --kind descriptive --n 120 --seed 611 --out P.jsonl --keys K.jsonl
    python -m cie.eval.brain_writers collect --kind descriptive --packets P.jsonl --keys K.jsonl --outputs O.jsonl --out Q.jsonl
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

from cie.eval import brain_questions as B
from cie.eval.memory_test import MONTH_NAMES, _jsonl, _norm, _write_jsonl, dates_in, render_doc

KINDS = ("descriptive", "prose")
PREFIX = {"descriptive": "desc", "prose": "prose"}
TEXT_CHARS = {"descriptive": 5_000, "prose": 6_000}
MIN_BODY = 800  # characters of body text a prose packet needs
FACT_WORDS = (2, 10)
MAX_FACTS = 3
TITLE_RUN = 5  # this many title words in a row give the title away
SYSTEMS = {"google_drive": "Google Drive", "confluence": "Confluence", "hubspot": "HubSpot", "jira": "Jira", "linear": "Linear",
           "github": "GitHub", "fireflies": "Fireflies (meeting recordings)", "slack": "Slack", "gmail": "Gmail"}
_ASKED = [(s, f, t) for s, f, t, _ in B.FIELDS.values()] + [("linear", "due_date", "date")]
FIELDS: dict[str, dict[str, str]] = {s: {f: t for s2, f, t in _ASKED if s2 == s} for s in dict.fromkeys(s for s, _, _ in _ASKED)}
FIELD_WORDS = {"owner": "the owner", "status": "the status", "created_at": "the creation date", "author": "the author",
               "space": "the Confluence space", "last_updated": "the last-updated date", "stage": "the deal stage",
               "forecast_close_month": "the forecast close month", "se_assigned": "the assigned solutions engineer",
               "priority": "the priority", "sla_due_at": "the SLA due date", "reporter": "the reporter", "assignee": "the assignee",
               "customer_company": "the customer company", "project": "the project", "creator": "the creator",
               "repo": "the repository", "merged_at": "the merge date", "redwood_owner": "the Redwood owner",
               "recorded_at": "the recording date", "due_date": "the due date"}
INTRO = ("You are given one document from the internal tools of a company (its chat, email, shared documents, wiki, tickets, CRM, "
         "code reviews or meeting recordings). ")
INSTRUCTIONS = {
    "descriptive": INTRO + (
        "Write one question a colleague might ask to find out <field> of this document, describing the document by what it is "
        "about (its topic, purpose, who it is for, where it lives) the way people do when they do not remember its exact title. "
        'Do not quote the title, do not include the answer, do not use the words "this document". One sentence. Ask for <field> '
        "directly, not as a yes/no question. Do not use its ticket key or pull request number either. The text leaves out "
        "<field>: you do not need it, and if the text gives it "
        'away, still keep it out of the question. Reply with JSON only: {"packet_id": "<the packet id>", "question": "<your '
        'question>"}'),
    "prose": INTRO + (
        "Write one question that a colleague might ask whose answer is stated in this document's text (not in its title or "
        "metadata fields), plus 1 to 3 answer facts: each a short phrase of 2 to 8 words copied EXACTLY from the text that a "
        "correct answer must contain (numbers, names, settings, thresholds, dates, decisions). The question must not contain the "
        "answer facts, must make sense without seeing the document (name the system, customer, incident or project it is about), "
        'and must not be answerable by yes/no. Reply with JSON only: {"packet_id": "<the packet id>", "question": "<your '
        'question>", "answer_facts": ["<fact>", ...]}'),
}
SELF_RE = re.compile(r"\b(?:this|the above|the attached|the given|the provided|the following)\s+(?:document|doc|page|text|file|"
                     r"packet|excerpt|passage|thread|e-?mail|ticket|issue|transcript|record|notes?|message|conversation|chat|pr|"
                     r"pull request|account|meeting)\b", re.I)
_OPEN = r"(?:^|[,;:]\s*|\b(?:and|or)\s+)\W*"  # where a clause of the question starts
_WH = r"(what|which|who|whom|whose|when|where|why|how)"
YES_NO_RE = re.compile(_OPEN + r"(?:is|are|was|were|am|do|does|did|can|could|will|would|should|shall|has|have|had|may|might|must)"
                       r"(?:n['’]?t)?\b", re.I)
WH_OPEN_RE = re.compile(_OPEN + r"(?:(?:in|on|at|by|for|to|from|under|with|of|during|until|since|within|after|before)\s+)?" + _WH
                        + r"\b", re.I)
WH_ASKED_RE = re.compile(r"\b(?:know|tell(?:\s+(?:me|us))?|say|remember|recall|confirm|check|find(?:\s+out)?|see|wonder(?:ing)?|ask|"
                         r"of|about)\s+" + _WH + r"\b", re.I)
FITS = {"person": {"who", "whom", "whose", "which", "what"}, "customer": {"who", "whom", "whose", "which", "what"},
        "value": {"what", "which", "where", "how"}, "date": {"when", "what", "which"}, "month": {"when", "what", "which"}}
QUOTED_RE = re.compile(r'"([^"]+)"|“([^”]+)”|‘([^’]+)’|(?:^|\s)\'([^\']+)\'(?=[\s?.,!:;]|$)')
DASHES = str.maketrans({"–": "-", "—": "-", "‑": "-", " ": " "})
Pools = dict[str, dict[str, list[dict[str, Any]]]]


# ------------------------------------------------------------------ documents
def documents(work: Path, preregistered: bool = False) -> list[dict[str, Any]]:
    """The work folder's documents, read as ``memory_test.haystack_docs`` reads them (id, source, title, raw record), each with
    its ``SourceDoc`` under "doc". A folder drawn from the test zone is read only after the pre-registration."""
    from cie.eval.memory_test import _raw
    from cie.ingest.sources import read

    hay = json.loads((work / "haystack.json").read_text())
    if hay.get("zone") == "test" and not preregistered:
        raise PermissionError("the test zone is read only after the pre-registration")
    index = json.loads((work / "index.json").read_text())["index"]
    sources = Path(hay["root"]) / "generated_data" / "sources"
    out = []
    for dsid in sorted(hay["dsids"]):
        rel = index[dsid]
        try:
            d = read(sources / rel, rel)
        except Exception:  # noqa: BLE001 - a malformed export is left out, as haystack_docs leaves it out
            continue
        out.append({"dsid": dsid, "source": d.source, "title": d.title, "raw": _raw(sources, rel), "doc": d})
    return out


def used_documents(work: Path) -> set[str]:
    """The gold documents of the questions in the folder's questions.jsonl (none when there is no such file)."""
    return {g for q in _jsonl(work / "questions.jsonl") for g in q.get("gold_docs") or q.get("expected_doc_ids") or []}


def body_text(doc: Any) -> str:
    """A document's body as ``memory_test.render_doc`` writes it (each content field under its label), without the title and
    the metadata fields."""
    return "\n".join(f"{f}:\n{t}" for f, t in doc.fields if t)


def _cut(text: str, limit: int) -> str:
    """The text up to about ``limit`` characters, cut at a line or word break, with "[...]" where it was cut."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    i = max(head.rfind("\n"), head.rfind(" "))
    return (head[:i] if i > 0.8 * limit else head).rstrip() + "\n[...]"


def _run(needle: list[str], hay: list[str]) -> bool:
    """Whether the words of ``needle`` stand in ``hay`` as a run."""
    m = len(needle)
    return m > 0 and any(hay[i:i + m] == needle for i in range(len(hay) - m + 1))


def _longest_run(a: list[str], b: list[str]) -> int:
    """The length of the longest run of words that ``a`` and ``b`` share."""
    best, prev = 0, [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


# ------------------------------------------------------------------ candidates and the deal
def descriptive_candidates(docs: list[dict[str, Any]]) -> tuple[Pools, Counter]:
    """For each source and field of ``FIELDS``, the documents a descriptive question can ask that field of, with the expected
    answer (``brain_questions._expected``); and what was left out, by reason. A document qualifies when its title is on no
    other document and ``brain_questions`` can name it (``_address``: a unique title, key or pull request number), the field
    holds one value, the value is not written inside another value of the field (``field_questions``' rule), the title does
    not give it (``_gives_value``), and ``brain_questions.score`` gives full marks both to the expected answer and to the value
    as the document stores it (a timestamp such as "2026-05-14T16:00:00Z" for a date)."""
    names = B._names(docs)
    pools: Pools = {}
    aside: Counter = Counter()
    for src, fields in FIELDS.items():
        mine = B._of(docs, src)
        for field, typ in fields.items():
            exps = [B._expected(d["raw"].get(field), typ) for d in mine]
            inner = B._nested({e["value"] for e, _ in exps if e and "value" in e}, outer=False)
            pool = []
            for d, (exp, why) in zip(mine, exps, strict=True):
                fmt, name = B._address(d, names)
                probe = {"kind": "descriptive", "family": "single", "expected": exp}
                if fmt is None:
                    exp, why = None, name
                elif names["titles"][_norm(d["title"])] != 1:
                    exp, why = None, "named twice"
                elif exp is not None and "value" in exp and B._squash(exp["value"]) in inner:
                    exp, why = None, "named inside another"
                elif exp is not None and _gives_value(d["title"], exp, typ):
                    exp, why = None, "value in the title"
                elif exp is not None and B.score(probe, str(exp.get("date") or exp.get("value"))) != 1.0:
                    exp, why = None, "scorer cannot match"
                elif exp is not None and B.score(probe, str(d["raw"].get(field))) != 1.0:
                    exp, why = None, "scorer cannot read the stored value"
                if exp is None:
                    aside[why] += 1
                    continue
                pool.append({"doc": d, "field": field, "type": typ, "expected": exp, "name": name})
            pools.setdefault(src, {})[field] = pool
    return pools, aside


def prose_candidates(docs: list[dict[str, Any]]) -> tuple[Pools, Counter]:
    """The documents of every source with at least ``MIN_BODY`` characters of body text, by source; and how many fell short."""
    pools: Pools = defaultdict(lambda: {"": []})
    aside: Counter = Counter()
    for d in sorted(docs, key=lambda d: d["dsid"]):
        if len(d["doc"].body) >= MIN_BODY:
            pools[d["source"]][""].append({"doc": d})
        else:
            aside["short body"] += 1
    return dict(pools), aside


def spread(pools: Pools, n: int, seed: int | str, later: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Up to ``n`` candidates, at most one per document (``_deal``). Documents in ``later`` are dealt only when the others have
    run out, in a second deal of their own."""
    first = _deal({s: {f: [c for c in cs if c["doc"]["dsid"] not in later] for f, cs in fs.items()} for s, fs in pools.items()},
                  n, seed)
    if len(first) >= n or not later:
        return first
    rest = {s: {f: [c for c in cs if c["doc"]["dsid"] in later] for f, cs in fs.items()} for s, fs in pools.items()}
    return first + _deal(rest, n - len(first), f"{seed}/later")


def _deal(pools: Pools, n: int, seed: int | str) -> list[dict[str, Any]]:
    """Up to ``n`` candidates, at most one per document: the sources take turns in a seeded order, and at its turn a source
    gives its next field in a seeded rotation that still has a document left. Each field's documents come in a seeded order."""
    rng = random.Random(seed)
    order = sorted(s for s, fs in pools.items() if any(fs.values()))
    rng.shuffle(order)
    turns: dict[str, list[str]] = {}
    queues: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in order:
        turns[s] = sorted(pools[s])
        rng.shuffle(turns[s])
        for f in turns[s]:
            queues[s, f] = list(pools[s][f])
            rng.shuffle(queues[s, f])
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    at = dict.fromkeys(order, 0)
    moved = True
    while len(out) < n and moved:
        moved = False
        for s in order:
            if len(out) >= n:
                break
            fs = turns[s]
            for j in range(len(fs)):
                q = queues[s, fs[(at[s] + j) % len(fs)]]
                while q and q[0]["doc"]["dsid"] in used:
                    q.pop(0)
                if q:
                    c = q.pop(0)
                    used.add(c["doc"]["dsid"])
                    out.append(c)
                    at[s] = (at[s] + j + 1) % len(fs)
                    moved = True
                    break
    return out


def instruction(kind: str, field: str | None = None) -> str:
    """The writer's instruction for a kind, with the field in plain words for a descriptive packet."""
    return INSTRUCTIONS[kind].replace("<field>", field) if field else INSTRUCTIONS[kind]


def shown_meta(meta: dict[str, Any], field: str, exp: dict[str, Any], typ: str) -> tuple[dict[str, Any], int]:
    """A descriptive packet's metadata: without the asked field, without any other line whose value gives the expected answer
    (``_gives_value``: an updated_at equal to merged_at, a meeting id holding the date), and without each list item that gives
    it (an attendee who is the owner, a page path holding the space); and how many lines and items were left out."""
    from cie.ingest.sources import text_of

    out: dict[str, Any] = {}
    dropped = 0
    for k, v in meta.items():
        if k == field:
            continue
        if isinstance(v, list):
            kept = [x for x in v if not _gives_value(text_of(x), exp, typ)]
            dropped += len(v) - len(kept)
            if kept or not v:
                out[k] = kept
        elif v is not None and _gives_value(json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v), exp, typ):
            dropped += 1
        else:
            out[k] = v
    return out, dropped


def _packet(kind: str, pid: str, c: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], int]:
    d, src = c["doc"], c["doc"]["source"]
    base = {"packet_id": pid, "kind": kind, "source": src, "system": SYSTEMS.get(src, src)}
    key = {"packet_id": pid, "kind": kind, "dsid": d["dsid"], "source": src, "title": d["title"]}
    if kind == "prose":
        return ({**base, "title": d["title"], "text": _cut(body_text(d["doc"]), TEXT_CHARS[kind]), "instruction": instruction(kind)},
                key, 0)
    words = FIELD_WORDS[c["field"]]
    meta, dropped = shown_meta(d["doc"].meta, c["field"], c["expected"], c["type"])
    return ({**base, "field": words, "text": _cut(render_doc(replace(d["doc"], meta=meta)), TEXT_CHARS[kind]),
             "instruction": instruction(kind, words)},
            {**key, "name": c["name"], "field": c["field"], "type": c["type"], "field_words": words, "expected": c["expected"]}, dropped)


def packets(work: Path, kind: str, n: int, seed: int, avoid: Iterable[str] = (), preregistered: bool = False
            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """``n`` packets of a kind for the work folder, one per document (``spread``; none for a document in ``avoid``), their keys
    and a report: packets by source and field, the candidates left after ``avoid``, what was left out and why, and for
    descriptive packets the metadata lines and list items left out because they gave the answer (``shown_meta``) and how many
    texts still give it (in the body: the writers are told to keep it out, and ``collect`` rejects a question that holds it)."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}: one of {KINDS}")
    docs = documents(work, preregistered)
    pools, aside = descriptive_candidates(docs) if kind == "descriptive" else prose_candidates(docs)
    avoid = set(avoid)
    pools = {s: {f: [c for c in cs if c["doc"]["dsid"] not in avoid] for f, cs in fs.items()} for s, fs in pools.items()}
    later = used_documents(work)
    picked = spread(pools, n, f"{seed}/{kind}", later)
    made = [_packet(kind, f"{PREFIX[kind]}-{seed}-{i:03d}", c) for i, c in enumerate(picked, 1)]
    ps, ks = [p for p, _, _ in made], [k for _, k, _ in made]
    sizes = [len(p["text"]) for p in ps]
    shown = ({"answer_lines_dropped": sum(x for _, _, x in made),
              "answer_in_text": sum(_gives_value(p["text"].split("\n", 1)[-1], k["expected"], k["type"]) for p, k in zip(ps, ks, strict=True))}
             if kind == "descriptive" else {})
    rep = {"work": str(work), "kind": kind, "n": n, "seed": seed, "documents": len(docs), "packets": len(ps),
           "by_source": dict(sorted(Counter(k["source"] for k in ks).items())),
           **({"by_field": dict(sorted(Counter(f"{k['source']}.{k['field']}" for k in ks).items()))} if kind == "descriptive" else {}),
           "candidates": {s: ({f: len(cs) for f, cs in sorted(fs.items())} if kind == "descriptive" else len(fs[""]))
                          for s, fs in sorted(pools.items())},
           "left_out": dict(sorted(aside.items())), "avoided": len(avoid & {d["dsid"] for d in docs}),
           "used_by_questions": sum(c["doc"]["dsid"] in later for c in picked), **shown,
           "text_chars": {"median": int(statistics.median(sizes)) if sizes else 0, "cut": sum(p["text"].endswith("[...]") for p in ps)}}
    return ps, ks, rep


# ------------------------------------------------------------------ the checks
def _flat(s: Any) -> str:
    """Text for a verbatim match: dashes and spaces unified, quotes and markdown marks dropped, whitespace collapsed, lower case
    (``memory_test._norm``)."""
    return _norm(str(s).translate(DASHES))


def _holds(hay: str, needle: str) -> bool:
    """Whether ``needle`` stands in ``hay``, not inside a longer word or number."""
    if not needle:
        return False
    left = r"(?<!\w)" if needle[0].isalnum() else ""
    right = r"(?!\w)" if needle[-1].isalnum() else ""
    return re.search(left + re.escape(needle) + right, hay) is not None


def _gives_value(q: str, exp: dict[str, Any], typ: str | None) -> bool:
    """Whether the question holds the expected answer: the value or one of its alternatives (as ``memory_test.check`` finds
    it, or as a run of words), any part of a person's name, or the date in any written form."""
    if "date" in exp:
        d = exp["date"]
        month, day = MONTH_NAMES[int(d[5:7]) - 1][:3], int(d[8:10])
        return d in q or d in dates_in(q) or bool(re.search(rf"\b{month}[a-z]*\.?\s+0?{day}(?!\d)", q, re.I)) \
            or bool(re.search(rf"(?<!\d)0?{day}(?:st|nd|rd|th)?\s+(?:of\s+)?{month}", q, re.I))
    for v in [exp["value"], *exp.get("alts", [])]:
        if _holds(_norm(q), _norm(v)) or _run(B._words(v), B._words(q)):
            return True
    return typ == "person" and any(len(t) >= 3 and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", q) for t in exp["value"].split())


def _why_title(q: str, title: str) -> str | None:
    """Why the question gives the title away, or None: it holds the whole title, puts a run of it in quotes, or holds
    ``TITLE_RUN`` of its words in a row."""
    tw, qw = B._words(title), B._words(q)
    if _run(tw, qw):
        return "quotes the title"
    for m in QUOTED_RE.finditer(q):
        sw = B._words(next(g for g in m.groups() if g))
        if len(sw) >= min(3, len(tw)) and _run(sw, tw):
            return "quotes the title"
    return "long run of the title" if _longest_run(tw, qw) >= TITLE_RUN else None


def question_words(q: str) -> list[str]:
    """The question words that open a clause of the question ("For the March burst, how much...", "In which space...") or
    follow a verb of asking ("Do you know who..."), in lower case."""
    return [m.group(1).lower() for r in (WH_OPEN_RE, WH_ASKED_RE) for m in r.finditer(q)]


def yes_no(q: str) -> bool:
    """Whether the question asks for yes or no: a clause opens with an auxiliary verb ("Has the pull request ... been
    merged?", "For the March incident, did latency rise?") and no question word asks for something else."""
    return YES_NO_RE.search(q) is not None and not question_words(q)


def _why_question(q: str, kind: str) -> str | None:
    if not q:
        return "no question"
    if not q.endswith("?") or len(q.split()) < 4:
        return "not a question"
    if q.count("?") > 1:
        return "more than one question"
    if SELF_RE.search(q):
        return "refers to the document itself"
    if yes_no(q):
        return "yes/no question"
    return None


def _why_descriptive(q: str, key: dict[str, Any]) -> str | None:
    if _gives_value(q, key["expected"], key.get("type")):
        return "contains the answer"
    if why := _why_title(q, key["title"]):
        return why
    name = str(key.get("name") or "")
    if (key["source"] in ("jira", "linear") and _run(B._words(name), B._words(q))) or \
            (key["source"] == "github" and re.search(rf"(?<!\d){re.escape(name)}(?!\d)", q)):
        return "names the key or number"
    asks = set(question_words(q))
    if asks and not asks & FITS.get(str(key.get("type")), asks):
        return "question word does not fit the field"
    return None


def _trim(fact: str) -> str:
    return " ".join(fact.split()).strip("\"'“”‘’").strip().rstrip(".,;:").strip()


def clean_facts(raw: Any) -> list[str] | None:
    """The answer facts trimmed (runs of spaces, surrounding quotes, closing punctuation) and without repeats; None when they
    are not a list of text."""
    if not isinstance(raw, list) or not all(isinstance(f, str) for f in raw):
        return None
    return list(dict.fromkeys(t for f in raw if (t := _trim(f))))


def _why_prose(q: str, facts: list[str] | None, text: str) -> str | None:
    from cie.eval.evidence_audit import fact_terms

    if facts is None:
        return "answer facts are not a list of text"
    if not facts:
        return "no answer facts"
    if len(facts) > MAX_FACTS:
        return f"more than {MAX_FACTS} answer facts"
    body = _flat(text)
    for f in facts:
        n = len(f.split())
        if n < FACT_WORDS[0]:
            return f"answer fact shorter than {FACT_WORDS[0]} words"
        if n > FACT_WORDS[1]:
            return f"answer fact longer than {FACT_WORDS[1]} words"
        if not _holds(body, _flat(f)):
            return "answer fact not in the text"
        if not any(fact_terms(f)):
            return "answer fact without a number or content word"
        if B.fact_share([f], f) < 1:
            return "answer fact the scorer cannot match"
        if _holds(_flat(q), _flat(f)) or _run(B._words(f), B._words(q)) or B.fact_share([f], q) >= 1:
            return "question contains an answer fact"
    return None


def _parse(raw: Any) -> dict[str, Any] | None:
    """A writer's output as a dict: the row itself, or the JSON object in its text."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and "{" in raw and "}" in raw:
        try:
            out = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        except ValueError:
            return None
        return out if isinstance(out, dict) else None
    return None


def _question(kind: str, q: str, facts: list[str] | None, key: dict[str, Any]) -> dict[str, Any]:
    pid = key["packet_id"]
    if kind == "prose":
        return {"id": pid, "group": "prose", "kind": "prose", "family": "prose", "question": q, "answer_facts": facts,
                "expected": {"facts": facts}, "gold_docs": [key["dsid"]], "pieces": facts, "source": key["source"], "packet_id": pid}
    e = key["expected"]
    return {"id": pid, "group": "descriptive", "kind": "descriptive", "family": "single", "field": key["field"], "question": q,
            "expected": e, "gold_docs": [key["dsid"]], "pieces": [key["name"], e.get("date") or e["value"]], "source": key["source"],
            "packet_id": pid}


def collect(kind: str, packets: list[dict[str, Any]], keys: list[dict[str, Any]], outputs: Iterable[Any]
            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The writers' questions that pass the checks, in ``brain_questions``' schema (family 'single' kind 'descriptive', or
    family 'prose' kind 'prose'), and the outputs rejected, each with its reason. An output is rejected when it is not a JSON
    object, its packet id is unknown, it is not one question, it asks for yes or no (``yes_no``), it refers to "this
    document", or a question for its packet or the same question came earlier; a descriptive question when it holds the
    expected answer, gives the title away (``_why_title``), names the ticket key or pull request number, or asks with question
    words that do not fit the field ("who" for a date); a prose question when it holds an answer fact (verbatim, as a run of
    words, or as ``brain_questions.fact_share`` would find it, so that an answer repeating the question earns nothing), or
    when its facts are not 1 to ``MAX_FACTS`` phrases of ``FACT_WORDS`` words, each standing verbatim in the packet's text
    (``_flat``), with a number or content word, that ``brain_questions.fact_share`` finds in the fact itself."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}: one of {KINDS}")
    by_packet = {p["packet_id"]: p for p in packets if p.get("kind") == kind}
    by_key = {k["packet_id"]: k for k in keys if k.get("kind") == kind}
    questions: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    answered: set[str] = set()
    asked: set[str] = set()
    for raw in outputs:
        out = _parse(raw)
        if out is None:
            rejected.append({"output": raw, "reason": "not a JSON object"})
            continue
        pid = str(out.get("packet_id") or "")
        q = " ".join(str(out.get("question") or "").split()).strip("\"'“”‘’ ")
        facts = clean_facts(out.get("answer_facts")) if kind == "prose" else None
        if pid not in by_packet or pid not in by_key:
            why = "unknown packet id"
        else:
            why = _why_question(q, kind) or (_why_descriptive(q, by_key[pid]) if kind == "descriptive"
                                             else _why_prose(q, facts, by_packet[pid]["text"]))
        sig = " ".join(B._words(q))
        if why is None and pid in answered:
            why = "packet answered already"
        if why is None and sig in asked:
            why = "duplicate question"
        if why:
            rejected.append({**out, "reason": why})
            continue
        answered.add(pid)
        asked.add(sig)
        questions.append(_question(kind, q, facts, by_key[pid]))
    return questions, rejected


def collect_report(questions: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, Any]:
    """Questions kept by source (and field), and the outputs rejected by reason."""
    return {"kept": len(questions), "rejected": len(rejected), "reasons": dict(Counter(r["reason"] for r in rejected).most_common()),
            "by_source": dict(sorted(Counter(q["source"] for q in questions).items())),
            **({"by_field": dict(sorted(Counter(f"{q['source']}.{q['field']}" for q in questions if "field" in q).items()))}
               if any("field" in q for q in questions) else {})}


# ------------------------------------------------------------------ files and the command line
def read_rows(path: Path) -> list[Any]:
    """The rows of a JSONL file or of a JSON list; a line that is not JSON is kept as its text."""
    text = path.read_text()
    if text.lstrip().startswith("["):
        return json.loads(text)
    out: list[Any] = []
    for line in text.splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append(line)
    return out


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain_writers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("packets", help="write packets for writers and, separately, their keys")
    p.add_argument("--work", required=True, help="a folder with haystack.json and index.json")
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True, help="the packets, JSONL (for the writers)")
    p.add_argument("--keys", required=True, help="the keys, JSONL (never for the writers)")
    p.add_argument("--avoid", nargs="*", default=[], help="key files whose documents get no packet")
    p.add_argument("--i-have-preregistered", dest="preregistered", action="store_true", help="allow a test-zone folder")
    c = sub.add_parser("collect", help="check the writers' outputs and write the questions")
    c.add_argument("--kind", required=True, choices=KINDS)
    c.add_argument("--packets", required=True)
    c.add_argument("--keys", required=True)
    c.add_argument("--outputs", required=True, help="the writers' outputs: JSONL or a JSON list of {packet_id, question, ...}")
    c.add_argument("--out", required=True, help="the questions, JSONL")
    c.add_argument("--rejected", default=None, help="the rejected outputs, JSONL (default: <out>.rejected.jsonl)")
    a = ap.parse_args(argv)
    if a.cmd == "packets":
        out, keys = Path(a.out), Path(a.keys)
        if out.resolve() == keys.resolve():
            ap.error("the packets and the keys go to separate files")
        avoid = {r["dsid"] for f in a.avoid for r in read_rows(Path(f)) if isinstance(r, dict) and r.get("dsid")}
        ps, ks, rep = packets(Path(a.work), a.kind, a.n, a.seed, avoid, a.preregistered)
        _write_jsonl(out, ps)
        _write_jsonl(keys, ks)
        rep |= {"out": str(out), "keys": str(keys)}
    else:
        qs, rejected = collect(a.kind, read_rows(Path(a.packets)), read_rows(Path(a.keys)), read_rows(Path(a.outputs)))
        out = Path(a.out)
        rej = Path(a.rejected) if a.rejected else out.with_name(out.name.removesuffix(".jsonl") + ".rejected.jsonl")
        _write_jsonl(out, qs)
        _write_jsonl(rej, rejected)
        rep = {**collect_report(qs, rejected), "out": str(out), "rejected_file": str(rej)}
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
