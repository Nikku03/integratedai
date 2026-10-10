"""The company brain's test (fact bank v15): draw the questions, build the banks, ask every arm, and score them.

- **questions:** questions of every kind the haystack's documents allow (W/haystack.json, W/index.json), drawn in a mix by
  ``brain_questions.draw_questions``, with writer-made prose questions and writer-made field questions ("descriptive") from
  files. Questions with more than one right answer are set aside: the multi-document kinds by ``factbank_5k.why_unclear``, the
  generated kinds by their generators' own rules, and a writer's question when code cannot check it, when a gold document is
  not in the haystack, or when what it names is on more than one document. With ``--small``, the control folder holds only
  the questions' gold documents (``factbank_5k.small_set``), and the questions whose expected answer is not the same there
  are recorded.
- **build:** the fact bank with text facts (factbank_v2.sqlite) and, with ``--v1``, the plain one (factbank.sqlite), each
  recorded in W/banks.json with the documents it holds.
- **ask:** one arm's answers: v1 (the untrained bank), v2 (single-document lessons), v13 (plan lessons), v15 (the brain,
  ``cie.factbank.brain.ask_brain``) and quotes, the no-model baseline for prose questions (keyword search over passages of the
  documents' text, then ``cie.retrieval.answer.quote_answer``). Each ask is recorded in W/arms.json with the questions and
  documents it answered over, so that answers to an older draw or haystack are never scored.
- **score:** every arm's answers, without quote citation markers, scored by ``brain_questions.score``, by family, group and
  kind, with the brain's routes, false "not found", prose facts reached in the evidence, time per question and the
  differences against the small folder when it holds the same questions. The rules come with the pre-registration:
  ``rules`` applies whatever rules it is given.

    python -m cie.eval.brain_test questions --work W --seed 15 [--mix JSON] [--n 40] [--prose F] [--descriptive F] [--small WS]
    python -m cie.eval.brain_test build --work W --v1
    python -m cie.eval.brain_test ask --work W --arm v13 --single LESSONS --plans PLAN_LESSONS
    python -m cie.eval.brain_test score --work W --small WS
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from cie.eval import brain_questions as B
from cie.eval import factbank_5k
from cie.eval.factbank_5k_b import _ms
from cie.eval.memory_test import EVIDENCE_CHARS, _jsonl, _norm, _write_jsonl

ARMS = ("v1", "v2", "v13", "v15", "quotes")
FILES = {"v1": "factbank", "v2": "factbank_v2", "v13": "factbank_v13", "v15": "factbank_v15", "quotes": "quotes"}
BANK = {"v1": "factbank", "v2": "factbank_v2", "v13": "factbank_v2", "v15": "factbank_v2"}  # the bank each arm reads
RESERVED = frozenset({"questions", "set_aside_questions"})  # files of the folder that no answers may replace
BUDGETS = (2_000, 6_000, 24_000)
ROUTE = {"single": "fact", "multi": "fact", "prose": "prose", "not_found": "not_found"}  # the right route for each family
QUOTE_K = 60  # passages searched for a quoted answer, as plain search takes them
REPORT = "questions_report.json"  # not draw_report.json: a brain_draw folder keeps its documents' draw report there
REGISTRY = "arms.json"
BANKS = "banks.json"
ELSEWHERE = frozenset({"no gold document", "gold document outside the haystack"})  # counted, not written: not this haystack's
CITATION = re.compile(r"\s*\[\d+\]")  # quote_answer's marker after each quote: "[2]" is no answer of 2

Rule = Callable[[dict[str, Any]], Any]


# ------------------------------------------------------------------ questions
def load_docs(work: Path) -> list[dict[str, Any]]:
    """The haystack's documents, read as factbank_5k reads them (``memory_test.haystack_docs``)."""
    from cie.eval.memory_test import haystack_docs

    hay = json.loads((work / "haystack.json").read_text())
    index = json.loads((work / "index.json").read_text())["index"]
    return haystack_docs(Path(hay["root"]) / "generated_data" / "sources", index, sorted(hay["dsids"]))


def parse_mix(text: str | None) -> dict[str, int] | None:
    """A mix of {kind, group, family or 'descriptive': number}, written as JSON or held in a JSON file."""
    if text is None:
        return None
    mix = json.loads(text if text.lstrip().startswith("{") else Path(text).read_text())
    if not isinstance(mix, dict) or not all(isinstance(v, int) and v >= 0 for v in mix.values()):
        raise ValueError(f"a mix is a JSON object of counts, not {text!r}")
    return mix


def scale(mix: dict[str, int], n: int) -> dict[str, int]:
    """The mix with its numbers scaled to ``n`` questions in all, by largest remainder (ties in name order)."""
    total = sum(mix.values())
    if total <= 0:
        return dict(mix)
    raw = {k: n * v / total for k, v in mix.items()}
    out = {k: int(x) for k, x in raw.items()}
    for k in sorted(raw, key=lambda k: (out[k] - raw[k], k))[: n - sum(out.values())]:
        out[k] += 1
    return out


def load_descriptive(path: str | Path) -> list[dict[str, Any]]:
    """Writer-made field questions from a JSONL file in ``brain_questions``' schema ({id, question, expected, gold_docs, ...};
    ``expected_doc_ids`` is read as ``gold_docs`` too). A row without a kind, group or family is read as kind and group
    'descriptive', family 'single'. The draw sets aside a row whose expected answer code cannot score (``why_malformed``)."""
    out = []
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        if not str(r.get("question") or "").strip() or not isinstance(r.get("expected"), dict):
            raise ValueError(f"{path}:{i}: a descriptive question needs a question and an expected answer")
        out.append({"kind": "descriptive", "group": "descriptive", "family": "single", "pieces": [], **r,
                    "id": str(r.get("id") or f"descriptive-{len(out) + 1:03d}"),
                    "gold_docs": list(r.get("gold_docs") or r.get("expected_doc_ids") or []), "origin": "descriptive"})
    return out


def _strings(x: Any) -> bool:
    return isinstance(x, list) and bool(x) and all(isinstance(s, str) and s.strip() for s in x)


def _iso_date(x: Any) -> bool:
    from datetime import date

    if not isinstance(x, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", x):
        return False
    try:
        date.fromisoformat(x)
    except ValueError:
        return False
    return True


def _as_answer(q: dict[str, Any]) -> str:
    """The expected answer written as an answer."""
    e = q["expected"]
    fam = B.family(q)
    if fam == "not_found":
        return "not found"
    if fam == "prose":
        return "\n".join(e["facts"])
    return str(e.get("value") or e.get("date") or ", ".join(e.get("names") or e.get("ids") or []))


def why_malformed(q: dict[str, Any]) -> str | None:
    """Why code cannot score a descriptive question, or None. Its family is one of ``brain_questions.FAMILIES``; a prose
    question expects a list of answer facts, a not-found question anything, any other exactly one of a value (a string,
    ``alts`` a list of strings), a date (YYYY-MM-DD), names (a list of strings) or ids (a list of strings, ``id_kind`` 'key'
    or 'pr'); code can check it (``brain_questions.checkable``); and ``brain_questions.score`` gives the expected answer
    itself full marks."""
    e, fam = q["expected"], B.family(q)
    if fam not in B.FAMILIES:
        return "bad family"
    if fam == "prose" and not _strings(e.get("facts")):
        return "bad expected (facts)"
    if fam in ("single", "multi"):
        given = [k for k in ("value", "date", "names", "ids") if k in e]
        if len(given) != 1:
            return "bad expected (not one of value, date, names, ids)"
        k = given[0]
        ok = {"value": lambda: isinstance(e["value"], str) and bool(e["value"].strip()) and ("alts" not in e or _strings(e["alts"])),
              "date": lambda: _iso_date(e["date"]), "names": lambda: _strings(e["names"]),
              "ids": lambda: _strings(e["ids"]) and e.get("id_kind") in ("key", "pr")}[k]()
        if not ok:
            return f"bad expected ({k})"
    if not B.checkable(q):
        return "not checkable"
    try:
        full = B.score(q, _as_answer(q))
    except (KeyError, TypeError, ValueError, AttributeError):
        return "scorer cannot read it"
    return None if full == 1.0 else "scorer cannot match"


def why_aside(q: dict[str, Any], docs: list[dict[str, Any]], dsids: set[str], titles: Counter) -> str | None:
    """Why a writer's question is set aside, or None: code cannot score it (``brain_questions.checkable``, and for a
    descriptive question ``why_malformed``), it has no gold document, a gold document is not in the haystack, a title it
    quotes names more than one document, or ``factbank_5k.why_unclear`` finds a key or number it names, or one its answer
    rests on, on more than one document."""
    if q.get("origin") == "descriptive":
        if bad := why_malformed(q):
            return bad
    elif not B.checkable(q):
        return "not checkable"
    gold = set(q.get("gold_docs") or [])
    if not gold:
        return "no gold document"
    if not gold <= dsids:
        return "gold document outside the haystack"
    if any(titles[_norm(t)] > 1 for t in re.findall(r'"([^"]+)"', q["question"])):
        return "named twice"
    return factbank_5k.why_unclear(q, docs)


def multi_aside(docs: list[dict[str, Any]], seed: int, kinds: set[str], multi_wordings: dict | None = None) -> list[dict[str, Any]]:
    """The multi-document questions ``brain_questions.generate`` sets aside, each with its reason (``unclear``): the same
    questions (``factbank_multi.questions``), the same rule (``factbank_5k.why_unclear``)."""
    from cie.eval import factbank_multi

    want = kinds & set(B.MULTI_KINDS)
    if not want:
        return []
    out = []
    for q in factbank_multi.questions(docs, {d["dsid"] for d in docs}, True, seed, wordings=multi_wordings, max_q=None):
        if q["kind"] in want and (why := factbank_5k.why_unclear(q, docs)):
            out.append({**q, "family": "multi", "unclear": why})
    return out


def _count(qs: Iterable[dict[str, Any]], key: Callable[[dict[str, Any]], Any]) -> dict[str, int]:
    return dict(sorted(Counter(key(q) for q in qs).items()))


def draw(docs: list[dict[str, Any]], seed: int = B.SEED, mix: dict[str, int] | None = None, prose: list[dict[str, Any]] | None = None,
         descriptive: list[dict[str, Any]] | None = None, multi_wordings: dict | None = None
         ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """The questions, those set aside, and a report of counts.

    The questions are ``brain_questions.draw_questions`` in ``mix`` (``DEFAULT_MIX``), the prose questions it draws from
    being the writers' that are not set aside (``why_aside``); then the descriptive questions not set aside, a seeded sample
    of ``mix['descriptive']`` of them (all when the mix does not say). A writer's question whose gold documents are not in
    the haystack is counted, but not written with the questions set aside."""
    mix = dict(B.DEFAULT_MIX if mix is None else mix)
    n_desc = mix.pop("descriptive", None)
    dsids = {d["dsid"] for d in docs}
    titles = B._names(docs)["titles"]
    aside: list[dict[str, Any]] = []
    writers: dict[str, list[dict[str, Any]]] = {}
    why_writers: dict[str, dict[str, int]] = {}
    for label, given in (("prose", prose or []), ("descriptive", descriptive or [])):
        kept, why = [], Counter()
        for q in given:
            w = why_aside(q, docs, dsids, titles)
            if w is None:
                kept.append(q)
            else:
                why[w] += 1
                if w not in ELSEWHERE:
                    aside.append({**q, "unclear": w})
        writers[label], why_writers[label] = kept, dict(sorted(why.items()))
    drawn = B.draw_questions(docs, seed, mix, prose=writers["prose"], multi_wordings=multi_wordings)
    desc = sorted(writers["descriptive"], key=lambda q: q["id"])
    if n_desc is not None and n_desc < len(desc):
        desc = sorted(random.Random(f"{seed}/descriptive").sample(desc, n_desc), key=lambda q: q["id"])
    qs = drawn + desc
    twice = sorted(i for i, c in Counter(q["id"] for q in qs).items() if c > 1)
    if twice:
        raise ValueError(f"question ids used twice: {twice}")
    wanted = set().union(*(B.resolve(k) for k in mix)) if mix else set()
    pool, gen = B.generate(docs, seed, kinds=wanted - {"prose", "metadata"}, multi_wordings=multi_wordings)
    aside += multi_aside(docs, seed, wanted, multi_wordings)
    available = Counter(q["kind"] for q in pool)
    if "prose" in wanted:
        available.update(q["kind"] for q in writers["prose"])
    available.update(q["kind"] for q in writers["descriptive"])
    given = {k: sum(1 for q in drawn if q["kind"] in B.resolve(k)) for k in mix}
    rep = {"documents": len(docs), "seed": seed, "mix": {**mix, **({"descriptive": n_desc} if n_desc is not None else {})},
           "questions": len(qs), "by_family": _count(qs, B.family), "by_group": _count(qs, lambda q: q["group"]),
           "by_kind": _count(qs, lambda q: q["kind"]), "mix_given": {**given, **({"descriptive": len(desc)} if descriptive else {})},
           "available": dict(sorted(available.items())), "set_aside": {"generated": gen["aside"], "writers": why_writers},
           "set_aside_written": _count(aside, lambda q: q["kind"]), "gold_documents": len(factbank_5k.small_set(qs))}
    return qs, aside, rep


def _ident(q: dict[str, Any]) -> tuple:
    """What a generated question is about, whatever its wording: its kind, gold documents and the name it starts from."""
    return q["kind"], tuple(sorted(q.get("gold_docs") or [])), str((q.get("pieces") or [q["question"]])[0])


def _parent_field(docs: list[dict[str, Any]], q: dict[str, Any]) -> dict[str, Any] | None:
    """The expected answer to a parent-issue question, read from the parent's own document among ``docs``."""
    parent = next((d for d in docs if d["source"] == "linear" and factbank_5k._key(d) == str(q["pieces"][0])), None)
    return B._expected(parent["raw"].get(q.get("field")), "person" if q.get("field") == "assignee" else "value")[0] if parent else None


def not_reproduced(docs: list[dict[str, Any]], small: set[str], qs: list[dict[str, Any]], seed: int = B.SEED,
                   multi_wordings: dict | None = None) -> dict[str, str]:
    """The questions whose expected answer is not the same within ``small``, each with why ('differs' or 'not asked').

    - the multi-document kinds: ``factbank_5k.not_reproduced`` (every wording and field drawn again within the set);
    - the memory test's kinds: drawn again within the set, the same question has the same expected answer;
    - the other generated kinds: drawn again within the set, the question about the same documents and name has the same
      field and expected answer (for a parent issue whose other field the draw chose there, the field read from the parent);
    - not found: the name is still written nowhere in the set;
    - the writers' questions: their gold documents are in the set."""
    inside = [d for d in docs if d["dsid"] in small]
    out: dict[str, str] = {}
    multi = [q for q in qs if q["kind"] in B.MULTI_KINDS]
    if multi:
        out.update({i: "differs or not asked" for i in factbank_5k.not_reproduced(docs, small, multi, seed, multi_wordings)})
    again = {q["kind"] for q in qs if q["kind"] in B.MEMORY_KINDS or (q["kind"] in B.GENERATORS and B.family(q) != "not_found")}
    by_text: dict[tuple, list] = defaultdict(list)
    by_ident: dict[tuple, list] = defaultdict(list)
    if again:
        for r in B.generate(inside, seed, kinds=again)[0]:
            by_text[(r["kind"], r["question"])].append(r["expected"])
            by_ident[_ident(r)].append(r)
    written = B._written(inside) if any(B.family(q) == "not_found" for q in qs) else ""
    titles = {_norm(d["title"]) for d in inside}
    for q in qs:
        k = q["kind"]
        if k in B.MULTI_KINDS:
            continue
        if k in B.MEMORY_KINDS:
            seen = by_text.get((k, q["question"]))
            why = "not asked" if not seen else None if q["expected"] in seen else "differs"
        elif B.family(q) == "not_found":
            name = str((q.get("pieces") or [""])[0])
            why = "differs" if not name or name.lower() in written or _norm(name) in titles else None
        elif k in B.GENERATORS:
            seen = by_ident.get(_ident(q)) or []
            same = any((r.get("field"), r["expected"]) == (q.get("field"), q["expected"]) for r in seen)
            if k == "parent_issue" and seen and not any(r.get("field") == q.get("field") for r in seen):
                same = _parent_field(inside, q) == q["expected"]  # the draw there chose the parent's other field
            why = "not asked" if not seen else None if same else "differs"
        else:
            why = None if set(q.get("gold_docs") or []) <= small else "gold document outside the set"
        if why:
            out[q["id"]] = why
    return dict(sorted(out.items()))


def write_questions(work: Path, seed: int = B.SEED, mix: dict[str, int] | None = None, n: int | None = None,
                    prose: Path | None = None, descriptive: Path | None = None, small: Path | None = None,
                    multi_wordings: Path | None = None) -> dict[str, Any]:
    """Draw the questions of a work folder and write W/questions.jsonl, W/set_aside_questions.jsonl and W/questions_report.json;
    with ``small``, the control folder too, checking that every expected answer reproduces there (``not_reproduced``)."""
    from cie.eval.factbank_multi import load_wordings

    if small is not None and small.resolve() == work.resolve():
        raise ValueError("the small folder must be another folder")
    mix = dict(B.DEFAULT_MIX if mix is None else mix)
    if n is not None:
        mix = scale(mix, n)
    t = time.perf_counter()
    hay = json.loads((work / "haystack.json").read_text())
    docs = load_docs(work)
    wordings = load_wordings(multi_wordings) if multi_wordings else None
    qs, aside, rep = draw(docs, seed, mix, B.load_prose(prose) if prose else None, load_descriptive(descriptive) if descriptive else None,
                          wordings)
    _write_jsonl(work / "questions.jsonl", qs)
    _write_jsonl(work / "set_aside_questions.jsonl", aside)
    rep |= {"prose_file": str(prose) if prose else None, "descriptive_file": str(descriptive) if descriptive else None,
            "multi_wordings": str(multi_wordings) if multi_wordings else None, "readable": len(docs),
            "listed": len(hay["dsids"]), "small": None}
    if small is not None:
        sm = factbank_5k.small_set(qs)
        bad = not_reproduced(docs, sm, qs, seed, wordings)
        factbank_5k._write_set(small, Path(hay["root"]), sm, qs, work / "index.json", seed)
        rep["small"] = {"folder": str(small), "documents": len(sm), "not_reproduced": bad}
        (small / REPORT).write_text(json.dumps({"control_of": str(work), **rep["small"]}, indent=1))
    rep["seconds"] = round(time.perf_counter() - t, 1)
    (work / REPORT).write_text(json.dumps(rep, indent=1))
    return rep


# ------------------------------------------------------------------ build
def haystack_sha(work: Path) -> str:
    """A fingerprint of the folder's documents: the benchmark root and the sorted document ids of W/haystack.json."""
    hay = json.loads((work / "haystack.json").read_text())
    return hashlib.sha256(json.dumps([hay["root"], sorted(hay["dsids"])]).encode()).hexdigest()


def banks(work: Path) -> dict[str, dict[str, Any]]:
    """The banks built in the folder by ``build``, by name, each with the fingerprint of the documents it holds (W/banks.json)."""
    return _read(work / BANKS) or {}


def build(work: Path, v1: bool = False) -> dict[str, Any]:
    """The fact bank with text facts (factbank_v2.sqlite) and, with ``v1``, the plain one (factbank.sqlite), each built by
    ``factbank_test.build``, which writes its build time and size to <name>_build.json. Each bank is recorded in W/banks.json
    with the fingerprint of the documents it was built from (``haystack_sha``)."""
    from cie.eval import factbank_test

    out = {}
    for name, text_facts in (("factbank_v2", True), *((("factbank", False),) if v1 else ())):
        sha = haystack_sha(work)
        rep = factbank_test.build(work, name, text_facts=text_facts)
        out[name] = {k: rep.get(k) for k in ("seconds", "bytes", "sources", "entities", "facts")} | {"check_ok": rep["check"]["ok"]}
        (work / BANKS).write_text(json.dumps({**banks(work), name: {"haystack_sha256": sha, **out[name]}}, indent=1))
    return out


# ------------------------------------------------------------------ ask
class Passages:
    """Keyword search over passages of the haystack documents' text, with no vectors: each document as plain search renders
    it (``memory_test.render_doc``), cut as plain search cuts it (``bench_enterprise.chunk``, about 1,000 characters), in an
    in-memory SQLite FTS5 index ranked by BM25, titles weighted as the bank's BM25 weights them."""

    def __init__(self, work: Path):
        from cie.eval.bench_enterprise import chunk
        from cie.eval.memory_test import render_doc
        from cie.ingest.sources import read
        from cie.retrieval.bm25 import TITLE_BOOST

        t = time.perf_counter()
        hay = json.loads((work / "haystack.json").read_text())
        index = json.loads((work / "index.json").read_text())["index"]
        sources = Path(hay["root"]) / "generated_data" / "sources"
        self.boost = float(TITLE_BOOST)
        self.rows: list[dict[str, str]] = []
        self.con = sqlite3.connect(":memory:")
        self.con.execute("CREATE VIRTUAL TABLE p USING fts5(title, body, tokenize='porter unicode61')")
        for dsid in hay["dsids"]:
            rel = index[dsid]
            try:
                d = read(sources / rel, rel)
            except Exception:  # noqa: BLE001 - as the loader: a malformed export is left out
                continue
            for i, text in enumerate(chunk(render_doc(d))):
                self.rows.append({"id": f"{dsid}#{i}", "dsid": dsid, "source": d.source, "title": d.title, "text": text})
                self.con.execute("INSERT INTO p(rowid, title, body) VALUES (?, ?, ?)", (len(self.rows), d.title, text))
        self.documents = len({r["dsid"] for r in self.rows})
        self.seconds = round(time.perf_counter() - t, 2)

    def search(self, question: str, k: int = QUOTE_K) -> list[dict[str, str]]:
        """The best ``k`` passages for the question's content words (``cie.retrieval.lexical``), any of them."""
        from cie.retrieval.lexical import _terms

        terms = list(dict.fromkeys(_terms(question)))
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        hits = self.con.execute(f"SELECT rowid FROM p WHERE p MATCH ? ORDER BY bm25(p, {self.boost}, 1.0) LIMIT ?", (match, k))
        return [self.rows[i - 1] for (i,) in hits]


def ask_quotes(work: Path, name: str = "quotes", k: int = QUOTE_K, budget: int = EVIDENCE_CHARS) -> dict[str, Any]:
    """The no-model baseline: every question answered by quoting the best passages (``quote_answer``), route 'prose'. The
    evidence is the passages in rank order, up to ``budget`` characters; an answer is empty when no sentence holds a word
    of the question."""
    from cie.eval.memory_test import fill
    from cie.retrieval.answer import quote_answer

    ps = Passages(work)
    rows = []
    for q in _jsonl(work / "questions.jsonl"):
        t = time.perf_counter()
        hits = ps.search(q["question"], k)
        items = [{"id": h["id"], "kind": "section", "summary": h["title"], "detail": h["text"], "document_id": h["dsid"]} for h in hits]
        res = quote_answer(items, q["question"])
        evidence = "\n\n".join(fill(((f"({h['source']}) {h['title']}", h["text"]) for h in hits), budget)[0])
        rows.append({"id": q["id"], "answer": res[0] if res else "", "route": "prose", "declined": res is None, "evidence": evidence,
                     "cited": list(dict.fromkeys(c["document_id"] for c in res[1])) if res else [],
                     "ms": round((time.perf_counter() - t) * 1000, 2)})
    _write_jsonl(work / f"{name}.jsonl", rows)
    return {"questions": len(rows), "written": f"{name}.jsonl", "passages": len(ps.rows), "documents": ps.documents,
            "index_seconds": ps.seconds, "declined": sum(r["declined"] for r in rows)}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def registry(work: Path) -> dict[str, dict[str, Any]]:
    """The asks recorded in the folder, by answers file name (W/arms.json)."""
    p = work / REGISTRY
    return json.loads(p.read_text()) if p.exists() else {}


def ask(work: Path, arm: str, single: Path | None = None, plans: Path | None = None, router: str | None = None,
        name: str | None = None) -> dict[str, Any]:
    """One arm's answers to W/questions.jsonl, written to W/<name>.jsonl (``FILES[arm]`` by default) and recorded in
    W/arms.json with the questions file they answer and the documents they were asked over (``haystack_sha``).

    - v1: ``factbank_test.ask`` on factbank.sqlite, the untrained bank;
    - v2: ``factbank_test.ask`` on factbank_v2.sqlite with the single-document lessons;
    - v13: ``factbank_multi.ask_plans`` with the single-document and plan lessons;
    - v15: ``cie.factbank.brain.ask_brain`` with both lessons and ``router``;
    - quotes: ``ask_quotes``.
    v1's and v2's answers are written by ``factbank_test.ask`` under the bank's name, then moved to ``name`` (the answers
    already under the bank's name are kept). An arm that reads a bank asks only one that ``build`` made from the folder's
    present documents; a name may not be another arm's answers file, nor one of the folder's question files."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}: one of {', '.join(ARMS)}")
    if arm in ("v2", "v13", "v15") and single is None:
        raise ValueError(f"arm {arm} needs the single-document lessons (--single)")
    if arm in ("v13", "v15") and plans is None:
        raise ValueError(f"arm {arm} needs the plan lessons (--plans)")
    name = name or FILES[arm]
    reg = registry(work)
    if not re.fullmatch(r"[\w.-]+", name) or name in RESERVED:
        raise ValueError(f"{name!r} cannot name an answers file")
    if other := next((a for a, f in FILES.items() if f == name and a != arm), None):
        raise ValueError(f"{name}.jsonl is arm {other}'s answers file: choose another name")
    if reg.get(name, {}).get("arm") not in (None, arm):
        raise ValueError(f"{name}.jsonl holds arm {reg[name]['arm']}'s answers: choose another name")
    label = arm if name == FILES[arm] else name
    if clash := sorted(n for n, r in reg.items() if r["label"] == label and n != name):
        raise ValueError(f"the label {label!r} already names the answers in {clash[0]}.jsonl")
    if arm == "v15":
        try:
            from cie.factbank.brain import ask_brain
        except ModuleNotFoundError as e:
            if e.name != "cie.factbank.brain":
                raise
            raise SystemExit("arm v15 needs cie.factbank.brain (ask_brain), which is not there yet") from e
    hay = haystack_sha(work)
    if arm in BANK:
        built = banks(work).get(BANK[arm])
        if built is None:
            raise ValueError(f"{BANK[arm]}.sqlite has no record of its build here: build it with `brain_test build`")
        if built.get("haystack_sha256") != hay:
            raise ValueError(f"{BANK[arm]}.sqlite was built from other documents than the folder's haystack holds: build it again")
    t = time.perf_counter()
    if arm in ("v1", "v2"):
        from cie.eval import factbank_test

        bank = FILES[arm]
        own = work / f"{bank}.jsonl"
        kept = own.read_bytes() if name != bank and own.exists() else None
        rep = factbank_test.ask(work, bank, single if arm == "v2" else None)
        if name != bank:
            own.replace(work / f"{name}.jsonl")
            if kept is not None:
                own.write_bytes(kept)
    elif arm == "v13":
        from cie.eval.factbank_multi import ask_plans

        rep = ask_plans(work, single, plans, name=name)
    elif arm == "v15":
        rep = ask_brain(work, single, plans, name=name, router=router)
    else:
        rep = ask_quotes(work, name)
    rec = {"arm": arm, "label": label, "file": f"{name}.jsonl", "single": str(single) if arm in ("v2", "v13", "v15") else None,
           "plans": str(plans) if arm in ("v13", "v15") else None, "router": router if arm == "v15" else None,
           "seconds": round(time.perf_counter() - t, 2), "answers": len(_jsonl(work / f"{name}.jsonl")),
           "questions_sha256": _sha(work / "questions.jsonl"), "haystack_sha256": hay}
    reg = registry(work)  # read again: another arm may have been asked meanwhile
    reg[name] = rec
    (work / REGISTRY).write_text(json.dumps(reg, indent=1))
    return {**rec, "result": rep}


# ------------------------------------------------------------------ score
def route_class(route: Any) -> str | None:
    """The kind of a route: 'not_found', 'prose', or 'fact' for any other (the planner's answer, v1's answer, ...)."""
    if route is None:
        return None
    r = str(route).lower().replace(" ", "_")
    return "not_found" if r.startswith("not_found") else "prose" if r.startswith("prose") else "fact"


def _mean(xs: Iterable[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def _family_mean(by_family: dict[str, float | None]) -> float | None:
    """The mean of the family means, over the families that have one."""
    return _mean(by_family.get(f) for f in B.FAMILIES)


def answered(work: Path) -> tuple[dict[str, str], dict[str, str]]:
    """The arms answered in the folder, label -> answers file name, and the asks left out, label -> why: those whose answers
    file is gone, that answered another questions file than the folder's, or that were asked over other documents than the
    folder's haystack holds (or recorded none)."""
    sha, hay = _sha(work / "questions.jsonl"), haystack_sha(work)
    ok, stale = {}, {}
    for name, rec in registry(work).items():
        if not (work / f"{name}.jsonl").exists():
            stale[rec["label"]] = "answers file missing"
        elif rec.get("questions_sha256") != sha:
            stale[rec["label"]] = "answered other questions"
        elif rec.get("haystack_sha256") != hay:
            stale[rec["label"]] = "answered with another haystack"
        else:
            ok[rec["label"]] = name
    return ok, stale


def plain_answer(answer: Any) -> str:
    """The answer without the citation markers ``quote_answer`` puts after each quote ("[2]"), which would otherwise give a
    quoted answer credit for a count or number it does not state."""
    return CITATION.sub("", str(answer or ""))


def score_rows(work: Path) -> dict[str, Any]:
    """Every arm's score on every question of the folder (None: code cannot check it), whether it said "not found", its
    route, the prose facts its evidence reaches within each budget (prose questions only) and its time. Answers are scored
    without their citation markers (``plain_answer``); their length is the answer's as given."""
    qs = _jsonl(work / "questions.jsonl")
    files, stale = answered(work)
    answers = {label: {r["id"]: r for r in _jsonl(work / f"{name}.jsonl")} for label, name in files.items()}
    rows = []
    for q in qs:
        fam = B.family(q)
        r: dict[str, Any] = {"id": q["id"], "family": fam, "group": q.get("group"), "kind": q.get("kind"), "score": {},
                             "not_found": {}, "route": {}, "reach": {}, "ms": {}, "chars": {}}
        for label, by_id in answers.items():
            row = by_id.get(q["id"])
            if row is None:
                continue
            plain = plain_answer(row.get("answer"))
            r["score"][label] = B.score(q, {**row, "answer": plain})
            r["not_found"][label] = B.says_not_found(plain, row.get("route"))
            if row.get("route") is not None:
                r["route"][label] = row["route"]
            if fam == "prose":
                r["reach"][label] = {str(b): B.prose_reach(q, str(row.get("evidence") or ""), b) for b in BUDGETS}
            r["ms"][label] = row.get("ms")
            r["chars"][label] = len(str(row.get("answer") or ""))
        rows.append(r)
    return {"labels": list(answers), "stale": stale, "rows": rows}


def routes(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    """An arm's routes by family: the routes it took, their kinds ('fact', 'prose', 'not_found'), and the share of questions
    routed to their family's kind (single and multi: fact)."""
    counts: dict[str, Counter] = defaultdict(Counter)
    kinds: dict[str, Counter] = defaultdict(Counter)
    right: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if label not in r["score"]:
            continue
        route = r["route"].get(label)
        counts[r["family"]][str(route)] += 1
        kinds[r["family"]][str(route_class(route))] += 1
        right[r["family"]].append(float(route_class(route) == ROUTE[r["family"]]))
    acc = {f: _mean(right[f]) for f in B.FAMILIES if right[f]}
    return {"counts": {f: dict(sorted(counts[f].items())) for f in B.FAMILIES if counts[f]},
            "kinds": {f: dict(sorted(kinds[f].items())) for f in B.FAMILIES if kinds[f]},
            "accuracy": acc, "accuracy_mean_over_families": _mean(acc.values())}


def summarise(rows: list[dict[str, Any]], labels: list[str]) -> dict[str, Any]:
    """Each arm's means by family, group and kind and over the families, the questions it left out (code cannot check
    them) or did not answer, false "not found" on answerable questions, prose facts in its evidence, time per question, the
    answers' length (a long answer can hold a short expected value by chance), and its routes when its answers name them."""
    out = {}
    for a in labels:
        mine = [r for r in rows if a in r["score"]]
        fam = {f: _mean(r["score"][a] for r in mine if r["family"] == f) for f in B.FAMILIES}
        groups = sorted({str(r["group"]) for r in mine})
        kinds = sorted({str(r["kind"]) for r in mine})
        nf: dict[str, float | None] = {f: _mean(float(r["not_found"][a]) for r in mine if r["family"] == f)
                                       for f in B.FAMILIES if f != "not_found"}
        nf["all"] = _mean(float(r["not_found"][a]) for r in mine if r["family"] != "not_found")
        prose = [r for r in mine if a in r["reach"]]
        out[a] = {
            "answered": len(mine), "missing": len(rows) - len(mine), "left_out": sum(1 for r in mine if r["score"][a] is None),
            "by_family": fam, "mean_of_families": _family_mean(fam), "families": [f for f in B.FAMILIES if fam[f] is not None],
            "by_group": {g: _mean(r["score"][a] for r in mine if str(r["group"]) == g) for g in groups},
            "by_kind": {k: {"mean": _mean(r["score"][a] for r in mine if str(r["kind"]) == k), "n": sum(1 for r in mine if str(r["kind"]) == k)}
                        for k in kinds},
            "false_not_found": nf,
            "prose_reach": {str(b): _mean(r["reach"][a][str(b)] for r in prose) for b in BUDGETS} if prose else None,
            "time_ms": _ms([r["ms"].get(a) for r in mine]),
            "answer_chars": _ms([r["chars"][a] for r in mine]),
            "routes": routes(rows, a) if any(a in r["route"] for r in mine) else None,
        }
    return out


def against_small(big: dict[str, Any], small: dict[str, Any], skip: set[str]) -> dict[str, Any]:
    """Each arm's family means on the big folder minus the small one, over the questions both folders answered whose
    expected answer reproduces in the small folder (``skip``: those that do not), and the questions whose score changed."""
    sm = {r["id"]: r for r in small["rows"]}
    out = {}
    for a in [x for x in big["labels"] if x in small["labels"]]:
        pairs = [(r, sm[r["id"]]) for r in big["rows"]
                 if r["id"] not in skip and r["id"] in sm and a in r["score"] and a in sm[r["id"]]["score"]]
        fb = {f: _mean(rb["score"][a] for rb, _ in pairs if rb["family"] == f) for f in B.FAMILIES}
        fs = {f: _mean(rs["score"][a] for rb, rs in pairs if rb["family"] == f) for f in B.FAMILIES}
        d = {f: round(fb[f] - fs[f], 3) if fb[f] is not None and fs[f] is not None else None for f in B.FAMILIES}
        mb, ms_ = _family_mean(fb), _family_mean(fs)
        out[a] = {"questions": len(pairs), "big": fb, "small": fs, "big_minus_small": d,
                  "mean_of_families": {"big": mb, "small": ms_, "big_minus_small": round(mb - ms_, 3) if mb is not None and ms_ is not None else None},
                  "changed": [{"id": rb["id"], "kind": rb["kind"], "family": rb["family"], "small": rs["score"][a], "big": rb["score"][a]}
                              for rb, rs in pairs if rb["score"][a] != rs["score"][a]]}
    return out


def rules(report: dict[str, Any], fns: dict[str, Rule], why: dict[str, str] | None = None) -> dict[str, bool | None]:
    """Each rule's verdict on the report: True (met), False (not met), or None when the report lacks what the rule reads (a
    missing arm, family, section or number, or a share of nothing); ``why``, when given, gets the error behind each None. No
    rule is decided here: they come with the pre-registration."""
    out: dict[str, bool | None] = {}
    for name, fn in fns.items():
        try:
            v = fn(report)
        except (KeyError, TypeError, IndexError, AttributeError, ZeroDivisionError, ValueError) as e:
            v = None
            if why is not None:
                why[name] = f"{type(e).__name__}: {e}"
        out[name] = None if v is None else bool(v)
    return out


# the rules of docs/FACTBANK_BRAIN_PREREGISTRATION.md, on the arms labelled v15, v1, v13 and quotes; rules 1 to 4 decide
EPS = 1e-9


def _fam(r: dict[str, Any], arm: str, family: str) -> float:
    return r["scores"][arm]["by_family"][family]


def preregistered() -> dict[str, Rule]:
    """The pre-registered rules (docs/FACTBANK_BRAIN_PREREGISTRATION.md). Rules 1 to 4 decide whether one brain answers every
    kind of question at least as well as the best earlier answer for that kind; 5 to 7 are reported."""
    others = lambda r: [a for a in r["scores"] if a not in ("v15", "v15_seed1")]  # noqa: E731
    return {
        "1 single-document questions: v15 >= v1 - 0.03": lambda r: _fam(r, "v15", "single") >= _fam(r, "v1", "single") - 0.03 - EPS,
        "2 multi-document questions: v15 >= v13 - 0.03": lambda r: _fam(r, "v15", "multi") >= _fam(r, "v13", "multi") - 0.03 - EPS,
        "3 free text: v15 >= plain search with quotes - 0.05": lambda r: _fam(r, "v15", "prose") >= _fam(r, "quotes", "prose") - 0.05 - EPS,
        "4 not found: v15 >= 0.80 on questions about nothing in the bank, and false 'not found' <= 0.03 on the others":
            lambda r: _fam(r, "v15", "not_found") >= 0.80 - EPS and r["scores"]["v15"]["false_not_found"]["all"] <= 0.03 + EPS,
        "5 one brain for every kind: v15's mean over families >= every other arm's + 0.20":
            lambda r: r["scores"]["v15"]["mean_of_families"] >= max(r["scores"][a]["mean_of_families"] for a in others(r)) + 0.20 - EPS,
        "6 it holds at size: v15 at 5,000 documents >= the small set - 0.05 (mean over families)":
            lambda r: r["small"]["differences"]["v15"]["mean_of_families"]["big_minus_small"] >= -0.05 - EPS,
        "7 the right route: v15's route accuracy, mean over families, >= 0.90":
            lambda r: r["scores"]["v15"]["routes"]["accuracy_mean_over_families"] >= 0.90 - EPS,
    }


def seed_check(work: Path, a: str = "v15", b: str = "v15_seed1") -> dict[str, Any] | None:
    """The same arm asked under another hash seed: the questions whose answers differ (None when either is missing)."""
    files = {rec["label"]: work / rec["file"] for rec in registry(work).values()}
    if a not in files or b not in files or not files[a].exists() or not files[b].exists():
        return None
    x = {r["id"]: r["answer"] for r in _jsonl(files[a])}
    y = {r["id"]: r["answer"] for r in _jsonl(files[b])}
    return {"questions": len(x), "different": sorted(i for i in x if x[i] != y.get(i))}


def _read(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def _asked(qs: list[dict[str, Any]]) -> list[tuple]:
    return [(q["id"], q.get("kind"), q["question"], json.dumps(q.get("expected"), sort_keys=True)) for q in qs]


def score(work: Path, small: Path | None = None, out: Path | None = None, rule_fns: dict[str, Rule] | None = None) -> dict[str, Any]:
    """Score every arm answered in ``work`` (and in ``small``, the control folder) and write report.json and report.md to
    ``out`` (``work`` by default). The big-minus-small differences are given only when the control folder holds the same
    questions (ids, kinds, wordings and expected answers), and leave out those its draw found not to reproduce there."""
    out = out or work
    big = score_rows(work)
    qs = _jsonl(work / "questions.jsonl")
    draw_rep = _read(work / REPORT) or {}
    rep: dict[str, Any] = {
        "work": str(work), "questions": len(qs), "by_family": _count(qs, B.family), "by_group": _count(qs, lambda q: str(q.get("group"))),
        "by_kind": _count(qs, lambda q: str(q.get("kind"))),
        "arms": {rec["label"]: {k: rec.get(k) for k in ("arm", "file", "single", "plans", "router", "seconds", "answers")}
                 for rec in registry(work).values() if rec["label"] in big["labels"]},
        "stale_arms": big["stale"], "scores": summarise(big["rows"], big["labels"]),
        "builds": {n: b for n in ("factbank", "factbank_v2") if (b := _read(work / f"{n}_build.json")) is not None},
        "draw": draw_rep, "small": None}
    if small is not None:
        sm = score_rows(small)
        same = _asked(qs) == _asked(_jsonl(small / "questions.jsonl"))
        skip = set(((_read(small / REPORT) or draw_rep.get("small") or {}).get("not_reproduced") or {}) if same else ())
        rep["small"] = {"work": str(small), "same_questions": same, "not_reproduced": sorted(skip), "stale_arms": sm["stale"],
                        "scores": summarise(sm["rows"], sm["labels"]), "differences": against_small(big, sm, skip) if same else None,
                        "note": None if same else "the control folder holds other questions (another draw's): no differences",
                        "builds": {n: b for n in ("factbank", "factbank_v2") if (b := _read(small / f"{n}_build.json")) is not None},
                        "rows": sm["rows"]}
    rep["seed_check"] = seed_check(work)
    why: dict[str, str] = {}
    rep["rules"] = rules(rep, rule_fns or {}, why)
    rep["rules_why"] = why
    rep["rows"] = big["rows"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    (out / "report.md").write_text(to_markdown(rep))
    return rep


def _f(x: Any, digits: int = 3) -> str:
    return "–" if x is None else f"{x:.{digits}f}" if isinstance(x, float) else str(x)


def to_markdown(rep: dict[str, Any]) -> str:
    fams = B.FAMILIES
    s = rep["scores"]
    out = ["### The company brain test", "",
           f"{rep['questions']} questions ({', '.join(f'{k} {v}' for k, v in rep['by_family'].items())}) on {rep['work']}.", "",
           "| arm | " + " | ".join(fams) + " | mean of families | left out | not answered |", "|---|" + "---|" * (len(fams) + 3)]
    for a, m in s.items():
        out.append(f"| {a} | " + " | ".join(_f(m["by_family"][f]) for f in fams) + f" | **{_f(m['mean_of_families'])}** | {m['left_out']} | {m['missing']} |")
    groups = sorted({g for m in s.values() for g in m["by_group"]})
    out += ["", "| arm | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]
    out += [f"| {a} | " + " | ".join(_f(m["by_group"].get(g)) for g in groups) + " |" for a, m in s.items()]
    out += ["", "False \"not found\" on answerable questions, prose facts in the evidence, time per question (ms), and the answers'"
            " length (characters):", "",
            "| arm | false not found | prose 2,000 | prose 6,000 | prose 24,000 | median ms | p90 ms | max ms | median chars |",
            "|---|---|---|---|---|---|---|---|---|"]
    for a, m in s.items():
        pr, t = m["prose_reach"] or {}, m["time_ms"] or {}
        out.append(f"| {a} | {_f(m['false_not_found']['all'])} | " + " | ".join(_f(pr.get(str(b))) for b in BUDGETS)
                   + " | " + " | ".join(_f(t.get(x), 1) for x in ("median", "p90", "max")) + f" | {_f((m['answer_chars'] or {}).get('median'), 0)} |")
    for a, m in s.items():
        if m["routes"]:
            r = m["routes"]
            out += ["", f"Routes of {a} (right route: single and multi fact, prose prose, not found not_found):", "",
                    "| family | routes | right route |", "|---|---|---|"]
            out += [f"| {f} | {json.dumps(r['counts'].get(f, {}))} | {_f(r['accuracy'].get(f))} |" for f in fams if f in r["counts"]]
            out.append(f"| mean over families | | **{_f(r['accuracy_mean_over_families'])}** |")
    if rep["small"] and rep["small"]["differences"] is None:
        out += ["", f"Big folder minus the small one ({rep['small']['work']}): none, {rep['small']['note']}."]
    elif rep["small"]:
        sm = rep["small"]
        out += ["", f"Big folder minus the small one ({sm['work']}; not reproduced there, left out: {len(sm['not_reproduced'])}):", "",
                "| arm | questions | " + " | ".join(fams) + " | mean of families | changed |", "|---|---|" + "---|" * (len(fams) + 2)]
        for a, d in sm["differences"].items():
            out.append(f"| {a} | {d['questions']} | " + " | ".join(_f(d["big_minus_small"][f]) for f in fams)
                       + f" | {_f(d['mean_of_families']['big_minus_small'])} | {len(d['changed'])} |")
    out += ["", "Rules:" if rep["rules"] else "Rules: none given (they come with the pre-registration)."]
    out += [f"- {k}: **{'met' if v else 'not met' if v is not None else 'n/a'}**" + (f" ({rep['rules_why'][k]})" if k in rep["rules_why"] else "")
            for k, v in rep["rules"].items()]
    out += ["", f"- hash-seed check (v15 under hash seed 1): {json.dumps(rep.get('seed_check'))}",
            f"- arms: {json.dumps(rep['arms'])}", f"- left out as stale: {json.dumps(rep['stale_arms'])}",
            f"- builds: {json.dumps(rep['builds'])}",
            f"- draw: {json.dumps({k: rep['draw'].get(k) for k in ('seed', 'mix', 'mix_given', 'set_aside_written', 'gold_documents')})}"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain_test")
    ap.add_argument("cmd", choices=["questions", "build", "ask", "score"])
    ap.add_argument("--work", required=True)
    ap.add_argument("--seed", type=int, default=B.SEED)
    ap.add_argument("--mix", default=None, help="questions: {kind, group, family or 'descriptive': number}, as JSON or a JSON file")
    ap.add_argument("--n", type=int, default=None, help="questions: scale the mix to this many questions")
    ap.add_argument("--prose", default=None, help="questions: writer-made prose questions (brain_questions.load_prose)")
    ap.add_argument("--descriptive", default=None, help="questions: writer-made field questions, JSONL in brain_questions' schema")
    ap.add_argument("--wordings", default=None, help="questions: wordings for the multi-document kinds (factbank_multi.load_wordings)")
    ap.add_argument("--small", default=None, help="questions: write the control folder here; score: compare with it")
    ap.add_argument("--v1", action="store_true", help="build: the plain bank too")
    ap.add_argument("--arm", choices=ARMS)
    ap.add_argument("--single", default=None, help="ask: the single-document lessons")
    ap.add_argument("--plans", default=None, help="ask: the plan lessons")
    ap.add_argument("--router", default=None, help="ask, v15: the router, as cie.factbank.brain names it")
    ap.add_argument("--name", default=None, help="ask: the answers file (default: the arm's)")
    ap.add_argument("--out", default=None, help="score: where to write report.json and report.md (default: --work)")
    ap.add_argument("--preregistered", action="store_true", help="score: decide the rules of docs/FACTBANK_BRAIN_PREREGISTRATION.md")
    a = ap.parse_args(argv)
    work = Path(a.work)
    path = lambda x: Path(x) if x else None  # noqa: E731
    if a.cmd == "questions":
        rep = write_questions(work, a.seed, parse_mix(a.mix), a.n, path(a.prose), path(a.descriptive), path(a.small), path(a.wordings))
    elif a.cmd == "build":
        rep = build(work, a.v1)
    elif a.cmd == "ask":
        if a.arm is None:
            ap.error("ask needs --arm")
        rep = ask(work, a.arm, path(a.single), path(a.plans), a.router, a.name)
    else:
        r = score(work, path(a.small), path(a.out), preregistered() if a.preregistered else None)
        rep = {a_: {"by_family": m["by_family"], "mean_of_families": m["mean_of_families"]} for a_, m in r["scores"].items()}
        if a.preregistered:
            rep["rules"] = r["rules"]
    print(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    main()
