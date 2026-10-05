"""Does the memory bank beat plain search on the questions it is built for? A test run on Colab.

The decision rules are fixed in ``docs/MEMORY_TEST_PREREGISTRATION.md``; the results go in ``docs/MEMORY_TEST.md``.

**Questions.** They come from EnterpriseRAG-Bench's fictional company "Redwood Inference": every name, ticket and date
is made up.

| group | where the questions come from | how an answer is checked |
|---|---|---|
| owners | the benchmark's 100 metadata questions (``extra_questions.jsonl``): who owns, who is assigned, which status | the gold document's field value that the gold answer names must be in the answer (code); the judge too |
| deadlines | due dates of Linear issues, and meeting action items that name an owner and a due date | the date (code) |
| lists | every Linear issue assigned to a person, with a status, or due in a two-week window; every Jira ticket assigned to a person; every pull request by an author | the keys or numbers listed: precision, recall, F1 (code) |
| conflicts | the benchmark's 20 conflicting_info questions: an earlier figure and the one that replaced it | the judge |

The deadlines and lists are computed from the documents' own fields over the haystack, so every expected answer is
exact.

**Arms.** Each arm gives the same model the same prompt with at most ``EVIDENCE_CHARS`` characters of evidence:

* ``plain-words``: BM25 over the raw documents, with every field written as "name: value", cut into passages;
* ``plain``: the same passages, with BM25 and vector search fused by reciprocal rank;
* ``bank``: the memory bank's own search, with its defaults;
* ``bank+facts``: the fact lines a language model extracted from the bank's passages (``section_facts``). The lines
  that match the question come first, then the bank's search;
* ``bank+lookup``: the model first turns the question into a lookup on the documents' fields and the action items'
  owners and due dates. The matching records come first, then the bank's search. When the lookup cannot be read or
  finds nothing, the evidence is the bank's search alone.

**Steps.** Each step writes its files into ``--work`` and can be run again:
1. ``questions``: the haystack and the questions;
2. ``load``: the haystack as a memory bank;
3. ``plain``: plain search's passages, BM25 index and vectors;
4. ``facts-passages``: the bank's passages in the layout of ``cie.eval.extract_facts``, whose ``run`` makes their facts
   into a file (which survives a disconnect), and ``cie.memory.facts import`` stores them in the bank;
5. ``evidence``: each question's evidence for every arm that needs no model;
6. ``answer``: the model plans the lookups and answers every question in every arm. ``run`` is ``evidence`` then
   ``answer``, in one process;
7. ``judge``, then ``score``.

``--local`` names a directory on the machine's own disk for the plain index and the embedding cache when ``--work`` is
on a network drive.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

GROUPS = ("owners", "deadlines", "lists", "conflicts")
ARMS = ("plain-words", "plain", "bank", "bank+facts", "bank+lookup")
EVIDENCE_CHARS = 24_000  # what the evidence audit's small model reads
FACT_CHARS = 6_000  # bank+facts: matching fact lines, at most this much; the bank's search fills the rest
LOOKUP_CHARS = 12_000  # bank+lookup: matching records, at most this much; the bank's search fills the rest
ITEM_CHARS = 1_500
K = 60  # candidates per search
LIST_MIN, LIST_MAX = 2, 10
CAPS = {"linear_due": 40, "action_due": 30, "linear_assignee": 15, "linear_status": 10, "linear_due_window": 10,
        "jira_assignee": 10, "github_author": 10}
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}(?:-\d{1,7})+\b")  # ENG-11, INC-2034-110
PR_RE = re.compile(r"(?<![\w.\-/])#?(\d{2,7})\b")
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
TEXT_DATE_RES = (re.compile(_MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I),  # March 5, 2025
                 re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH + r",?\s+(\d{4})", re.I))  # 5 March 2025
SKIP_FIELDS = {"dsid", "summary", "tags", "source"}


# ------------------------------------------------------------------ files
def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]], mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`\"“”‘’']", "", str(s))).strip().lower()


def _iso(v: Any) -> str | None:
    m = ISO_RE.search(str(v or ""))
    return m.group(0) if m else None


def _person(v: Any) -> str | None:
    s = str(v or "").strip()
    return s if 2 < len(s) < 60 and "," not in s and not s.startswith("[") else None


# ------------------------------------------------------------------ questions
_OWNER = re.compile(r"^\s*([A-Z][\w.'’\-]+(?:\s[A-Z][\w.'’\-]+){0,3})\s*(?:\([^)]{1,40}\))?\s*(?:[-–—]|:)\s+(.+)$")
_DUE = re.compile(r"[\s,;|(\[–—-]*\bdue\b(?:\s*date)?\s*(?:by|on)?\s*:?\s*(\d{4}-\d{2}-\d{2})\)?\.?\s*$", re.I)
_LABELED = re.compile(r"^\s*owner\s*:\s*([^|;]+?)\s*[|;]\s*(?:item|task|action)\s*:\s*(.+?)\s*[|;]\s*due(?:\s*date)?\s*:?\s*(\d{4}-\d{2}-\d{2})\b", re.I)
_LABELS = {"owner", "owners", "action", "item", "task", "next", "follow", "due", "assignee", "todo", "ai"}


def action_items(raw: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(owner, task, due date) of a meeting's action items that name both an owner and a due date. Three layouts:
    "Name - task - Due: date", "Name | task | due: date" and "Owner: Name | Item: task | Due: date"."""
    out = []
    for it in raw.get("action_items") or []:
        if not isinstance(it, str):
            continue
        m = _LABELED.match(it)
        if m:
            owner, task, when = m.groups()
        else:
            d = _DUE.search(it)
            if not d:
                continue
            when, head = d.group(1), _DUE.sub("", it)
            parts = [p.strip() for p in head.split("|") if p.strip()]
            if len(parts) >= 2:
                owner, task = parts[0], " | ".join(parts[1:])
            else:
                m2 = _OWNER.match(head)
                if not m2:
                    continue
                owner, task = m2.group(1), m2.group(2)
        owner = re.sub(r"\s*\([^)]*\)\s*$", "", owner).strip()
        task = task.strip(" -–—;,.|")
        if _person(owner) and owner[0].isupper() and owner.split()[0].lower().strip(":") not in _LABELS and len(task) > 10:
            out.append((owner, task, when))
    return out


def _values(v: Any, out: list[str]) -> None:
    if isinstance(v, dict):
        for x in v.values():
            _values(x, out)
    elif isinstance(v, list):
        for x in v:
            _values(x, out)
    elif v not in (None, ""):
        out.append(str(v))


MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def expected_value(question: str, gold_answer: str, raw: dict[str, Any], title: str | None = None) -> dict[str, Any] | None:
    """The gold document's field value that the gold answer names and the question does not.
    "Who is assigned to the incident about ...?" / "The incident is assigned to Liam Chen." -> the assignee field.

    Candidates are the fields' values up to 80 characters, and the dates and ticket keys inside longer ones; a month
    field (2026-05) also counts written out (May 2026). The document's title wins when the gold answer names it (the
    question asked which document); otherwise the longest candidate that is not a path or a link."""
    from cie.ingest.sources import ARTEFACT_FIELDS

    vals: list[str] = []
    for k, v in raw.items():
        if k not in ARTEFACT_FIELDS:
            _values(v, vals)
    pool: dict[str, set[str]] = {}
    for s in (x.strip() for x in vals):
        if len(s) <= 80:
            pool.setdefault(s, set())
        else:
            for x in (m.group(0) for m in ISO_RE.finditer(s)):
                pool.setdefault(x, set())
            for x in KEY_RE.findall(s):
                pool.setdefault(x, set())
        m = re.fullmatch(r"(\d{4})-(\d{2})", s)
        if m and 1 <= int(m.group(2)) <= 12:
            pool.setdefault(f"{MONTH_NAMES[int(m.group(2)) - 1]} {m.group(1)}", set()).add(s)
    gold, ques = _norm(gold_answer), _norm(question)
    cands = [c for c in pool if len(_norm(c)) > 2 and _norm(c) not in ques
             and re.search(r"(?<!\w)" + re.escape(_norm(c)) + r"(?!\w)", gold)]
    if not cands:
        return None
    if title and title.strip() in cands:
        best = title.strip()
    else:
        best = max(sorted([c for c in cands if "/" not in c and not c.lower().startswith("http")] or cands), key=len)
    return {"value": best, **({"alts": sorted(pool[best])} if pool[best] else {})}


def _raw(sources: Path, rel: str) -> dict[str, Any]:
    if not rel.endswith(".json"):
        return {}
    try:
        d = json.loads((sources / rel).read_text(errors="replace"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def haystack_docs(sources: Path, index: dict[str, str], dsids: list[str]) -> list[dict[str, Any]]:
    """The haystack's documents: id, source, title and the raw export record."""
    from cie.ingest.sources import read

    out = []
    for dsid in dsids:
        rel = index[dsid]
        try:
            d = read(sources / rel, rel)
        except Exception:  # noqa: BLE001 - a malformed export is left out of the question set, as the loader leaves it out
            continue
        out.append({"dsid": dsid, "source": d.source, "title": d.title, "raw": _raw(sources, rel)})
    return out


def generate_questions(docs: list[dict[str, Any]], seed: int = 7, caps: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Deadline and list questions whose answers are computed from the haystack documents' fields."""
    caps = {**CAPS, **(caps or {})}
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    n_kind: Counter = Counter()

    def add(kind: str, group: str, question: str, expected: dict[str, Any], gold: list[str]) -> None:
        n_kind[kind] += 1
        out.append({"id": f"{kind}-{n_kind[kind]:03d}", "group": group, "kind": kind, "question": question, "expected": expected,
                    "gold_docs": sorted(set(gold)), "generated": True})

    def unique(rows: list[dict], key: Callable[[dict], Any]) -> list[dict]:
        c = Counter(key(d) for d in rows)
        return [d for d in rows if key(d) is not None and c[key(d)] == 1]

    titles = Counter(_norm(d["title"]) for d in docs)
    linear = unique([d for d in docs if d["source"] == "linear" and d["raw"].get("key")], lambda d: d["raw"]["key"])
    jira = unique([d for d in docs if d["source"] == "jira" and d["raw"].get("key")], lambda d: d["raw"]["key"])
    github = unique([d for d in docs if d["source"] == "github" and str(d["raw"].get("pr_number") or "").isdigit()],
                    lambda d: str(d["raw"]["pr_number"]))
    dsid_of_id = {**{d["raw"]["key"]: d["dsid"] for d in linear + jira}, **{str(d["raw"]["pr_number"]): d["dsid"] for d in github}}

    # deadlines
    due = [d for d in linear if _iso(d["raw"].get("due_date")) and titles[_norm(d["title"])] == 1]
    for d in rng.sample(due, min(caps["linear_due"], len(due))):
        add("linear_due", "deadlines", f'When is the Linear issue "{d["title"]}" due?', {"date": _iso(d["raw"]["due_date"])}, [d["dsid"]])
    items = []
    for d in docs:
        if d["source"] == "fireflies" and titles[_norm(d["title"])] == 1:
            its = action_items(d["raw"])
            once = Counter((o, t) for o, t, _ in its)
            items += [(d, o, t, when) for o, t, when in its if once[(o, t)] == 1]
    for d, o, t, when in rng.sample(items, min(caps["action_due"], len(items))):
        add("action_due", "deadlines", f'In the meeting "{d["title"]}", {o} took this action item: "{t}". When is it due?',
            {"date": when}, [d["dsid"]])

    # lists
    def groups(rows: list[dict], key: Callable[[dict], Any], ident: Callable[[dict], str]) -> dict[Any, set[str]]:
        g: dict[Any, set[str]] = defaultdict(set)
        for d in rows:
            k = key(d)
            if k:
                g[k].add(ident(d))
        return dict(g)

    def pick(kind: str, g: dict[Any, set[str]], make: Callable[[Any], str], id_kind: str, keep: Callable[[Any], bool] = lambda k: True) -> None:
        ok = sorted(k for k, v in g.items() if LIST_MIN <= len(v) <= LIST_MAX and keep(k))
        for k in rng.sample(ok, min(caps[kind], len(ok))):
            ids = sorted(g[k])
            add(kind, "lists", make(k), {"ids": ids, "id_kind": id_kind}, [dsid_of_id[i] for i in ids])

    key = lambda d: d["raw"]["key"]  # noqa: E731
    by_assignee = groups(linear, lambda d: _person(d["raw"].get("assignee")), key)
    pick("linear_assignee", by_assignee, lambda n: f"List every Linear issue assigned to {n}. Give the issue keys.", "key")
    by_status = groups(linear, lambda d: (_person(d["raw"].get("assignee")), str(d["raw"].get("status") or "").strip() or None)
                       if _person(d["raw"].get("assignee")) and d["raw"].get("status") else None, key)
    pick("linear_status", by_status, lambda k: f'Which Linear issues assigned to {k[0]} have the status "{k[1]}"? Give the issue keys.', "key",
         keep=lambda k: len(by_status[k]) < len(by_assignee.get(k[0], ())))  # the status must narrow the person's issues
    dated = sorted((_iso(d["raw"].get("due_date")), d["raw"]["key"]) for d in linear if _iso(d["raw"].get("due_date")))
    windows: dict[tuple[str, str], set[str]] = {}
    for when, _ in rng.sample(dated, min(len(dated), 8 * caps["linear_due_window"])):
        d1 = date.fromisoformat(when)
        w = (d1.isoformat(), (d1 + timedelta(days=13)).isoformat())
        windows.setdefault(w, {k for x, k in dated if w[0] <= x <= w[1]})
    pick("linear_due_window", windows, lambda w: f"Which Linear issues are due between {w[0]} and {w[1]}, inclusive? Give the issue keys.", "key")
    pick("jira_assignee", groups(jira, lambda d: _person(d["raw"].get("assignee")), key),
         lambda n: f"List every Jira ticket assigned to {n}. Give the ticket keys.", "key")
    pick("github_author", groups(github, lambda d: _person(d["raw"].get("author")), lambda d: str(d["raw"]["pr_number"])),
         lambda n: f"List every GitHub pull request authored by {n}. Give the pull request numbers.", "pr")
    return out


def benchmark_questions(root: Path, sources: Path, index: dict[str, str], n_metadata: int | None = None,
                        n_conflicting: int | None = None) -> list[dict[str, Any]]:
    """The benchmark's metadata questions (owners) and conflicting_info questions (conflicts), with their gold answers."""
    extra = [q for q in _jsonl(root / "extra_questions.jsonl") if q.get("question_type") == "metadata"][: n_metadata or None]
    conflicting = [q for q in _jsonl(root / "questions.jsonl") if q.get("question_type") == "conflicting_info"][: n_conflicting or None]
    out = []
    for q in extra:
        gold = q["expected_doc_ids"]
        doc = haystack_docs(sources, index, gold[:1]) if gold and gold[0] in index else []
        exp = expected_value(q["question"], q["gold_answer"], doc[0]["raw"], doc[0]["title"]) if doc else None
        out.append({"id": f"metadata-{q['question_id']}", "group": "owners", "kind": "metadata", "question": q["question"],
                    "expected": exp or {}, "gold_answer": q["gold_answer"], "gold_docs": gold})
    for q in conflicting:
        out.append({"id": f"conflicting-{q['question_id']}", "group": "conflicts", "kind": "conflicting_info", "question": q["question"],
                    "expected": {}, "gold_answer": q["gold_answer"], "gold_docs": q["expected_doc_ids"]})
    return out


def build_questions(root: Path, work: Path, n_docs: int | None = 5000, seed: int = 5, n_questions: int | None = None,
                    n_metadata: int | None = None, n_conflicting: int | None = None, caps: dict[str, int] | None = None,
                    log=print) -> dict[str, Any]:
    """The haystack and the questions. The haystack is the 5,000-document one of the earlier runs (every gold document of
    the benchmark's questions plus a stratified sample, seed 5), plus the gold documents of the metadata questions."""
    from cie.eval.bench_enterprise import build_index, select_docs

    sources = root / "generated_data" / "sources"
    base = _jsonl(root / "questions.jsonl")[: n_questions or None]
    extra = [q for q in _jsonl(root / "extra_questions.jsonl") if q.get("question_type") == "metadata"][: n_metadata or None]
    conflicting = [q for q in _jsonl(root / "questions.jsonl") if q.get("question_type") == "conflicting_info"][: n_conflicting or None]
    gold = {d for q in base + extra + conflicting for d in q["expected_doc_ids"]}
    index = build_index(sources, cache=work / "index.json", must_contain=gold, log=log)
    missing = gold - set(index)
    if not index or missing:
        raise SystemExit(f"corpus not found or incomplete under {sources}: {len(index):,} documents indexed, {len(missing)} gold documents missing")
    dsids = sorted(set(select_docs(index, base, n_docs, seed)) | {d for q in extra + conflicting for d in q["expected_doc_ids"]})
    docs = haystack_docs(sources, index, dsids)
    qs = benchmark_questions(root, sources, index, n_metadata, n_conflicting) + generate_questions(docs, caps=caps)
    work.mkdir(parents=True, exist_ok=True)
    (work / "haystack.json").write_text(json.dumps({"root": str(root.resolve()), "n_docs": n_docs, "seed": seed, "base_questions": len(base),
                                                    "documents": len(dsids), "dsids": dsids}))
    _write_jsonl(work / "questions.jsonl", qs)
    counts = {"documents": len(dsids), "questions": len(qs), "by_group": dict(Counter(q["group"] for q in qs)),
              "by_kind": dict(Counter(q["kind"] for q in qs)),
              "owners_with_expected_value": sum(1 for q in qs if q["group"] == "owners" and q["expected"])}
    log(json.dumps(counts, indent=1))
    return counts


# ------------------------------------------------------------------ the memory bank
def load_bank(work: Path, batch: int = 64, workers: int | None = None, reuse: str | None = "auto", local: Path | None = None,
              log=print) -> dict[str, Any]:
    """The haystack loaded as a full memory bank (``cie.eval.bench_enterprise.load_full``), or the one already loaded."""
    import psycopg
    from sqlalchemy import select, text

    from cie.core.db import session_scope
    from cie.core.models import Tenant
    from cie.core.settings import get_settings
    from cie.eval.bench_enterprise import find_loaded_tenant, load_full
    from cie.eval.bench_scale import ensure_indexes
    from cie.memory.embeddings import get_embedding_provider

    hay = json.loads((work / "haystack.json").read_text())
    root = Path(hay["root"])
    index = json.loads((work / "index.json").read_text())["index"]
    settings = get_settings()
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        ensure_indexes(conn)
    name = find_loaded_tenant(hay["dsids"], "full", log=log) if reuse == "auto" else (reuse or None)
    if name:
        with session_scope() as s:
            t = s.scalar(select(Tenant).where(Tenant.name == name))
            if t is None:
                raise SystemExit(f"no tenant named {name!r}")
            company = s.scalar(text("SELECT id FROM scopes WHERE tenant_id = :t AND parent_id IS NULL"), {"t": t.id})
            rep: dict[str, Any] = {"tenant_name": name, "tenant_id": str(t.id), "company_id": str(company), "reused": True}
    else:
        rep = load_full(url, root / "generated_data" / "sources", index, hay["dsids"], get_embedding_provider(settings),
                        tenant_name=f"erbfull-{len(hay['dsids'])}-{uuid.uuid4().hex[:6]}", batch=batch, workers=workers,
                        cache=(local or work) / "emb_cache.sqlite", log=log)
    (work / "load.json").write_text(json.dumps(rep, indent=1, default=str))
    log(f"memory bank: {rep['tenant_name']}")
    return rep


# ------------------------------------------------------------------ plain search over the raw documents
def render_doc(d) -> str:
    """A raw document as text: title, source, then every field (``SourceDoc``: metadata, then body fields)."""
    from cie.ingest.sources import text_of

    lines = [d.title, f"source: {d.source}"]
    for k, v in d.meta.items():
        if isinstance(v, list):
            v = ", ".join(text_of(x) for x in v)
        elif isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        if v not in (None, ""):
            lines.append(f"{k}: {v}")
    for f, t in d.fields:
        lines.append(f"{f}:\n{t}")
    return "\n".join(lines)


def _plain_schema():
    import tantivy

    sb = tantivy.SchemaBuilder()
    sb.add_text_field("id", stored=True, tokenizer_name="raw", index_option="basic")
    sb.add_text_field("title", tokenizer_name="en_stem", index_option="freq")
    sb.add_text_field("body", tokenizer_name="en_stem", index_option="freq")
    return sb.build()


def _dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def build_plain(work: Path, embedder=None, local: Path | None = None, log=print) -> dict[str, Any]:
    """Passages of the raw documents (1,000 characters, as the memory bank cuts them), a BM25 index and their vectors."""
    import shutil

    import numpy as np
    import tantivy

    from cie.eval.bench_enterprise import chunk
    from cie.ingest.sources import read

    t0 = time.perf_counter()
    hay = json.loads((work / "haystack.json").read_text())
    sources = Path(hay["root"]) / "generated_data" / "sources"
    index = json.loads((work / "index.json").read_text())["index"]
    d_out = (local or work) / "plain"
    if d_out.exists():
        shutil.rmtree(d_out)
    d_out.mkdir(parents=True)
    chunks = []
    for dsid in hay["dsids"]:
        rel = index[dsid]
        try:
            d = read(sources / rel, rel)
        except Exception:  # noqa: BLE001 - left out, as the loader leaves it out
            continue
        for i, c in enumerate(chunk(render_doc(d))):
            chunks.append({"id": f"{dsid}#{i}", "dsid": dsid, "source": d.source, "title": d.title, "text": c})
    _write_jsonl(d_out / "chunks.jsonl", chunks)
    (d_out / "bm25").mkdir()
    idx = tantivy.Index(_plain_schema(), path=str(d_out / "bm25"))
    w = idx.writer(heap_size=256_000_000)
    for c in chunks:
        w.add_document(tantivy.Document(id=c["id"], title=c["title"], body=c["text"]))
    w.commit()
    w.wait_merging_threads()
    t_bm25 = time.perf_counter() - t0
    out = {"documents": len(hay["dsids"]), "passages": len(chunks), "text_bytes": sum(len(c["text"].encode()) for c in chunks),
           "bm25_bytes": _dir_bytes(d_out / "bm25"), "bm25_seconds": round(t_bm25, 1)}
    if embedder is not None:
        t = time.perf_counter()
        vecs = []
        for i in range(0, len(chunks), 256):
            vecs += embedder.embed([f"{c['title']}\n{c['text']}" for c in chunks[i:i + 256]])
        a = np.asarray(vecs, dtype=np.float32)
        a /= np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)
        np.save(d_out / "vectors.npy", a.astype(np.float16))  # 16-bit, as the memory bank stores them
        out.update({"vector_bytes": (d_out / "vectors.npy").stat().st_size, "embed_seconds": round(time.perf_counter() - t, 1)})
    (d_out / "meta.json").write_text(json.dumps(out, indent=1))
    (work / "plain_meta.json").write_text(json.dumps(out, indent=1))  # the sizes, kept with the results
    log(f"plain search: {out}")
    return out


class Plain:
    """Search over the raw documents' passages: BM25, vectors, and the two fused by reciprocal rank."""

    def __init__(self, d: Path, embedder=None):
        import numpy as np
        import tantivy

        self.chunks = _jsonl(d / "chunks.jsonl")
        self.pos = {c["id"]: i for i, c in enumerate(self.chunks)}
        self.index = tantivy.Index.open(str(d / "bm25"))
        self.searcher = self.index.searcher()
        self.vecs = np.load(d / "vectors.npy").astype(np.float32) if (d / "vectors.npy").exists() else None
        self.embedder = embedder

    def words(self, q: str, k: int = K) -> list[int]:
        import tantivy

        from cie.retrieval.bm25 import TITLE_BOOST, query_terms

        terms = query_terms(q)
        if not terms:
            return []
        sch = self.index.schema
        query = tantivy.Query.boolean_query(
            [(tantivy.Occur.Should, tantivy.Query.boost_query(tantivy.Query.term_query(sch, "title", t), TITLE_BOOST)) for t in terms]
            + [(tantivy.Occur.Should, tantivy.Query.term_query(sch, "body", t)) for t in terms])
        res = self.searcher.search(query, k)
        return [self.pos[self.searcher.doc(a)["id"][0]] for _, a in res.hits]

    def vector(self, q: str, k: int = K) -> list[int]:
        import numpy as np

        if self.vecs is None or self.embedder is None or not len(self.vecs):
            return []
        v = np.asarray(self.embedder.embed([q])[0], dtype=np.float32)
        v /= max(float(np.linalg.norm(v)), 1e-9)
        sims = self.vecs @ v
        top = np.argpartition(-sims, min(k, len(sims) - 1))[:k]
        return [int(i) for i in top[np.argsort(-sims[top])]]

    def hybrid(self, q: str, k: int = K) -> list[int]:
        return rrf([self.words(q, k), self.vector(q, k)])[:k]

    def blocks(self, ids: list[int]) -> list[tuple[str, str]]:
        return [(f"({self.chunks[i]['source']}) {self.chunks[i]['title']}", self.chunks[i]["text"]) for i in ids]


def rrf(lists: list[list[Any]], c: int = 60) -> list[Any]:
    """Reciprocal rank fusion: each list adds 1 / (c + rank) to its items."""
    score: dict[Any, float] = defaultdict(float)
    for lst in lists:
        for r, x in enumerate(lst):
            score[x] += 1.0 / (c + r + 1)
    return sorted(score, key=lambda x: -score[x])


def fill(blocks: Iterable[tuple[str, str]], budget: int = EVIDENCE_CHARS, start: int = 1) -> tuple[list[str], int]:
    """Numbered evidence blocks in rank order, up to ``budget`` characters (the first one is cut to fit if it must be)."""
    out: list[str] = []
    used = 0
    for head, body in blocks:
        b = f"[{start + len(out)}] {head}\n{body}"
        if used + len(b) + 2 > budget:
            if not out:
                out.append(b[:budget])
                used = budget
            break
        out.append(b)
        used += len(b) + 2
    return out, used


# ------------------------------------------------------------------ facts and lookups in the memory bank
class Facts:
    """The tenant's stored fact lines (``section_facts``) of one extractor, searched by BM25 in memory."""

    def __init__(self, conn, tenant_id: uuid.UUID, signature: str | None = None):
        import tantivy

        if signature is None:
            row = conn.execute("SELECT signature FROM section_facts WHERE tenant_id = %s GROUP BY 1 ORDER BY count(*) DESC LIMIT 1",
                               (tenant_id,)).fetchone()
            signature = row[0] if row else None
        self.signature = signature
        self.lines: list[tuple[str, str, str]] = []  # (line, source, document title)
        self.sections = 0
        if signature:
            for facts, src, title in conn.execute(
                    "SELECT f.facts, d.extra->>'source', d.title FROM section_facts f JOIN documents d ON d.id = f.document_id "
                    "WHERE f.tenant_id = %s AND f.signature = %s AND f.status IN ('done', 'capped')", (tenant_id, signature)):
                self.sections += 1
                for x in facts or []:
                    if isinstance(x, dict) and x.get("text") and not x.get("tag"):
                        self.lines.append((x["text"], src or "?", title or ""))
        self.index = tantivy.Index(_plain_schema())
        w = self.index.writer(heap_size=256_000_000)
        for i, (line, _src, title) in enumerate(self.lines):
            w.add_document(tantivy.Document(id=str(i), title=title, body=line))
        w.commit()
        w.wait_merging_threads()
        self.index.reload()
        self.searcher = self.index.searcher()

    def search(self, q: str, k: int = 40) -> list[int]:
        import tantivy

        from cie.retrieval.bm25 import query_terms

        terms = query_terms(q)
        if not terms or not self.lines:
            return []
        sch = self.index.schema
        query = tantivy.Query.boolean_query([(tantivy.Occur.Should, tantivy.Query.term_query(sch, f, t)) for t in terms for f in ("title", "body")])
        return [int(self.searcher.doc(a)["id"][0]) for _, a in self.searcher.search(query, k).hits]

    def block(self, q: str, budget: int = FACT_CHARS) -> str | None:
        lines, used = [], 0
        for i in self.search(q):
            line, src, title = self.lines[i]
            s = f"- {line} ({src}: {title[:120]})"
            if used + len(s) + 1 > budget:
                break
            lines.append(s)
            used += len(s) + 1
        return "\n".join(lines) if lines else None


LOOKUP_SYSTEM = "You turn a question about a company's records into a lookup on their fields. You reply with JSON only."
OPS = ("=", "contains", ">=", "<=")


def lookup_schema(conn, tenant_id: uuid.UUID, max_fields: int = 22) -> tuple[str, dict[str, set[str]]]:
    """The fields of the tenant's documents per source, with a few example values, and the action items' fields."""
    rows = conn.execute(
        "SELECT d.extra->>'source', e.key, count(*), (array_agg(DISTINCT left(e.value, 40)))[1:3] "
        "FROM documents d, jsonb_each_text(d.extra) e WHERE d.tenant_id = %s GROUP BY 1, 2 ORDER BY 1, 3 DESC", (tenant_id,)).fetchall()
    n_src = dict(conn.execute("SELECT extra->>'source', count(*) FROM documents WHERE tenant_id = %s GROUP BY 1", (tenant_id,)).fetchall())
    fields: dict[str, set[str]] = defaultdict(lambda: {"title"})
    parts: dict[str, list[str]] = defaultdict(list)
    for src, key, n, examples in rows:
        if not src or key in SKIP_FIELDS or n < 0.1 * n_src.get(src, 1) or len(parts[src]) >= max_fields:
            continue
        fields[src].add(key)
        ex = [x for x in (examples or []) if x and len(x) <= 30][:2]
        parts[src].append(f"{key}" + (f" (e.g. {'; '.join(ex)})" if ex else ""))
    lines = [f"- {src} ({n_src.get(src, 0)} records): title, " + ", ".join(p) for src, p in sorted(parts.items())]
    lines.append("- action_items (action items from meetings and other documents): owner, due (YYYY-MM-DD), text, meeting (the meeting's title)")
    fields["action_items"] = {"owner", "due", "text", "meeting"}
    return "Sources and their fields:\n" + "\n".join(lines), dict(fields)


def plan_conversation(schema: str, question: str) -> list[dict[str, str]]:
    user = (f"{schema}\n\nQuestion: {question}\n\n"
            "Write a lookup that finds the records that answer the question, as JSON:\n"
            '{"source": "<one source above>", "where": [{"field": "<one of its fields>", "op": "=", "value": "<value>"}], '
            '"title": "<words of the record\'s title if the question names it, else empty>"}\n'
            'op is "=" for an exact value such as a name or a status, ">=" or "<=" for a date range (dates as YYYY-MM-DD), '
            '"contains" for part of a value. If no lookup on these fields can answer the question, reply {"source": null}.\n'
            f"Question: {question}")
    return [{"role": "system", "content": LOOKUP_SYSTEM}, {"role": "user", "content": user}]


def parse_plan(text: str, fields: dict[str, set[str]]) -> dict[str, Any] | None:
    """The model's lookup, checked against the known sources, fields and operators; None when there is none to run."""
    text = text or ""
    p = None
    for i in [m.start() for m in re.finditer(r"\{", text)][:5]:  # the first JSON object, whatever the model wrote around it
        try:
            p = json.JSONDecoder().raw_decode(text[i:])[0]
            break
        except ValueError:
            continue
    if not isinstance(p, dict):
        return None
    src = p.get("source")
    if not isinstance(src, str) or src not in fields:
        return None
    where = []
    for c in p.get("where") or []:
        if isinstance(c, dict) and c.get("field") in fields[src] and c.get("op") in OPS and isinstance(c.get("value"), str | int | float):
            where.append({"field": c["field"], "op": c["op"], "value": str(c["value"]).strip()})
    title = p.get("title") if isinstance(p.get("title"), str) else ""
    if not where and not title.strip():
        return None
    return {"source": src, "where": where, "title": title.strip()}


def _cond(expr: str, op: str, value: str) -> tuple[str, list[Any]]:
    if op == "=":
        return f"lower({expr}) = lower(%s)", [value]
    if op == "contains":
        return f"{expr} ILIKE %s", [f"%{value}%"]
    target = f"left({expr}, 10)" if ISO_RE.fullmatch(value) else expr
    return f"{target} {op} %s", [value]


def run_lookup(conn, tenant_id: uuid.UUID, plan: dict[str, Any], limit: int = 60) -> tuple[list[tuple[str, str]], int]:
    """The records the lookup finds, as evidence blocks, best title match first; and how many it found."""
    words = [w for w in re.findall(r"[a-z0-9]+", plan["title"].lower()) if len(w) > 2]
    if plan["source"] == "action_items":
        cols = {"owner": "r.content->>'owner'", "due": "r.content->>'due'", "text": "r.summary", "meeting": "d.title"}
        sql = ("SELECT r.summary, r.content->>'owner', left(r.content->>'due', 10), d.title, coalesce(d.extra->>'recorded_at', ''), "
               "d.extra->>'source' FROM memory_records r JOIN documents d ON d.id = r.source_document_id "
               "WHERE r.tenant_id = %s AND r.type = 'task' AND r.superseded_by_id IS NULL AND r.deleted_at IS NULL")
    else:
        cols = {}
        sql = "SELECT d.title, d.extra FROM documents d WHERE d.tenant_id = %s AND d.extra->>'source' = %s AND d.deleted_at IS NULL"
    params: list[Any] = [tenant_id] + ([] if plan["source"] == "action_items" else [plan["source"]])
    for c in plan["where"]:
        if plan["source"] == "action_items":
            expr = cols[c["field"]]
        elif c["field"] == "title":
            expr = "d.title"
        else:
            expr, params = "(d.extra->>%s)", params + [c["field"]]
        s, p = _cond(expr, c["op"], c["value"])
        sql += " AND " + s
        params += p
    if not plan["where"]:  # a title alone: records whose title holds one of its words
        if not words:
            return [], 0
        sql += " AND (" + " OR ".join("d.title ILIKE %s" for _ in words) + ")"
        params += [f"%{w}%" for w in words]
    order = " ORDER BY d.title, r.summary" if plan["source"] == "action_items" else " ORDER BY d.title"
    rows = conn.execute(sql + order + " LIMIT 2000", params).fetchall()

    def overlap(title: str) -> int:
        t = title.lower()
        return sum(1 for w in words if w in t)

    blocks = []
    if plan["source"] == "action_items":
        rows.sort(key=lambda r: -overlap(f"{r[3]} {r[0]}"))
        for summ, owner, due, meeting, rec, src in rows[:limit]:
            blocks.append((f"(action item, {src}) {meeting}", f"Action item: {summ} | owner: {owner or '?'} | due: {due or '?'} | "
                                                              f"meeting: {meeting} ({rec[:10]})"))
    else:
        rows.sort(key=lambda r: -overlap(r[0]))
        for title, extra in rows[:limit]:
            fields = " | ".join(f"{k}: {v}" for k, v in (extra or {}).items() if k not in SKIP_FIELDS and v not in (None, ""))
            blocks.append((f"({plan['source']} record) {title}", fields[:600]))
    return blocks, len(rows)


def bank_blocks(items: list[dict[str, Any]], source_of: dict[str, str]) -> list[tuple[str, str]]:
    return [(f"({source_of.get(str(it.get('document_id')), '?')}, {it.get('type')}) {str(it.get('summary') or '')[:300]}",
             str(it.get("detail") or "")[:ITEM_CHARS]) for it in items]


# ------------------------------------------------------------------ the model
ANSWER_SYSTEM = "You answer questions about a company's internal documents, using only the evidence you are given."


def answer_conversation(question: str, evidence: str) -> list[dict[str, str]]:
    user = (f"Evidence:\n{evidence}\n\nQuestion: {question}\n\n"
            "Use only the evidence above, and keep the answer short. End with one line that starts with \"Answer:\" and gives "
            "only the answer: a name, a date as YYYY-MM-DD, a status, or a comma-separated list of issue keys or pull request "
            "numbers. If the evidence does not contain the answer, end with \"Answer: not found\".\n"
            f"Question: {question}")  # restated last: small models attend to the end
    return [{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": user}]


def _fake_plan(q: str) -> dict[str, Any] | None:
    src = next((s for w, s in (("Linear", "linear"), ("Jira", "jira"), ("pull request", "github"), ("meeting", "action_items")) if w in q), None)
    if src is None:
        return None
    m = re.search(r"(?:assigned to|authored by) ([A-Z][\w'’\-]+(?: [A-Z][\w'’\-]+)*)", q)
    where = [{"field": {"github": "author"}.get(src, "assignee"), "op": "=", "value": m.group(1)}] if m and src != "action_items" else []
    dates = [x.group(0) for x in ISO_RE.finditer(q)]
    if src == "linear" and len(dates) == 2:
        where += [{"field": "due_date", "op": ">=", "value": dates[0]}, {"field": "due_date", "op": "<=", "value": dates[1]}]
    t = re.search(r'"([^"]+)"', q)
    return {"source": src, "where": where, "title": t.group(1) if t else ""}


def fake_generate(convs: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
    """A stand-in for a model, for tests of the plumbing: it writes a lookup from patterns in the question, and answers
    with the first keys or the first date in its evidence. Its scores mean nothing."""
    out = []
    for msgs in convs:
        user = msgs[-1]["content"]
        if msgs[0]["content"] == LOOKUP_SYSTEM:
            text = json.dumps(_fake_plan(user.rsplit("Question: ", 1)[-1]) or {"source": None})
        else:
            q = user.rsplit("Question: ", 1)[-1]
            ev = user.split("Question: ", 1)[0]
            ids = list(dict.fromkeys(KEY_RE.findall(ev)))[:3]
            if "keys" in q:
                text = "Answer: " + (", ".join(ids) if ids else "not found")
            elif "due" in q:
                text = "Answer: " + (_iso(ev) or "not found")
            else:
                text = "Answer: not found"
        out.append({"text": text, "prompt_tokens": len(user) // 4, "output_tokens": len(text) // 4, "finish_reason": "stop"})
    return out


def make_generate(a: argparse.Namespace, log=print) -> tuple[Callable[[list, int], list[dict[str, Any]]], str]:
    """``generate(conversations, max_tokens)`` for the chosen backend, and a name for the report."""
    if a.backend == "fake":
        return (lambda convs, max_tokens: fake_generate(convs)), "fake (plumbing only)"
    from cie.eval import extract_facts as ef

    if a.backend == "vllm":
        repo, rev = ef.resolve_model(a.model, log=log)
        engine = ef._vllm_engine(repo, rev, a, log=log)
        return (lambda convs, max_tokens: ef._vllm_generate(engine, convs, argparse.Namespace(max_tokens=max_tokens))), \
            f"{repo}@{rev}" if rev else repo

    def gen(convs, max_tokens):
        return ef._openai_generate(convs, argparse.Namespace(**{**vars(a), "max_tokens": max_tokens}))

    return gen, f"{a.model} at {a.base_url}"


# ------------------------------------------------------------------ run
def _context(work: Path):
    from sqlalchemy import select

    from cie.core.models import Principal

    ld = json.loads((work / "load.json").read_text())
    return ld, uuid.UUID(ld["tenant_id"]), uuid.UUID(ld["company_id"]), select(Principal).where(
        Principal.tenant_id == uuid.UUID(ld["tenant_id"]), Principal.name == "admin")


def collect_evidence(work: Path, arms: list[str], facts_signature: str | None = None, local: Path | None = None, log=print) -> dict[str, Any]:
    """Each question's evidence for the arms that need no model: plain-words, plain, bank, bank+facts; and the bank's
    blocks, which bank+lookup fills its remaining budget with. Saved to evidence.jsonl, one line per question."""
    from sqlalchemy import select

    from cie.core.db import session_scope
    from cie.core.models import Document
    from cie.core.settings import get_settings
    from cie.memory.embeddings import get_embedding_provider
    from cie.memory.facts import _connect
    from cie.retrieval.pipeline import Retriever

    questions = _jsonl(work / "questions.jsonl")
    path = work / "evidence.jsonl"
    need = [x for x in arms if x != "bank+lookup"]
    have = {r["id"]: r for r in _jsonl(path)}  # a later line of a question replaces an earlier one
    done = {qid for qid, r in have.items() if all(x in r for x in need)}
    todo = [q for q in questions if q["id"] not in done]
    settings = get_settings()
    embedder = get_embedding_provider(settings)
    _ld, tenant_id, company_id, admin_q = _context(work)
    conn = _connect(settings.database_url)
    prev = json.loads((work / "evidence_info.json").read_text()) if (work / "evidence_info.json").exists() else {}
    info: dict[str, Any] = {"facts": prev.get("facts")} if prev.get("facts") else {}
    facts = plain = None
    if todo and "bank+facts" in arms:  # nothing to do: no index is built (a new runtime may have lost the plain index)
        facts = Facts(conn, tenant_id, facts_signature)
        info["facts"] = {"signature": facts.signature, "sections": facts.sections, "lines": len(facts.lines)}
        log(f"facts: {info['facts']}")
    if todo and {"plain", "plain-words"} & set(arms):
        plain = Plain((local or work) / "plain", embedder)
    with session_scope() as s:
        admin = s.scalar(admin_q)
        source_of = {str(i): (e or {}).get("source", "?") for i, e in s.execute(select(Document.id, Document.extra).where(Document.tenant_id == tenant_id))}
        retriever = Retriever(s, settings, embedder=embedder)
        rows = []
        for i, q in enumerate(todo):
            row: dict[str, Any] = {"id": q["id"], "ms": {}}
            if plain is not None:
                t = time.perf_counter()
                row["plain-words"] = "\n\n".join(fill(plain.blocks(plain.words(q["question"])))[0])
                row["ms"]["plain-words"] = round((time.perf_counter() - t) * 1000, 1)
                t = time.perf_counter()
                row["plain"] = "\n\n".join(fill(plain.blocks(plain.hybrid(q["question"])))[0])
                row["ms"]["plain"] = round((time.perf_counter() - t) * 1000, 1)
            t = time.perf_counter()
            try:
                res = retriever.retrieve(q["question"], admin, company_id)
                items = res.packet.items
            except Exception as e:  # noqa: BLE001 - a failed search is an empty packet, recorded
                s.rollback()
                items = []
                row["bank_error"] = f"{type(e).__name__}: {e}"[:300]
            s.rollback()  # nothing the search wrote stays
            row["ms"]["bank"] = round((time.perf_counter() - t) * 1000, 1)
            blocks = bank_blocks(items, source_of)
            shown, _ = fill(blocks)
            row["bank"] = "\n\n".join(shown)
            row["bank_blocks"] = [list(b) for b in blocks[:len(shown)]]  # bank+lookup fills what its records leave with these
            if facts is not None:
                t = time.perf_counter()
                fb = facts.block(q["question"])
                row["ms"]["bank+facts"] = row["ms"]["bank"] + round((time.perf_counter() - t) * 1000, 1)
                head = [f"Facts that match the question (extracted from the documents by a language model):\n{fb}"] if fb else []
                rest, _ = fill(blocks, EVIDENCE_CHARS - sum(len(x) + 2 for x in head))
                row["bank+facts"] = "\n\n".join(head + rest)
            rows.append(row)
            if len(rows) >= 25 or i == len(todo) - 1:
                _write_jsonl(path, rows, "a")
                rows = []
                log(f"  evidence: {len(done) + i + 1}/{len(questions)} questions")
    info["storage"] = storage(conn, tenant_id, work, settings)
    (work / "evidence_info.json").write_text(json.dumps(info, indent=1, default=str))
    return info


def storage(conn, tenant_id: uuid.UUID, work: Path, settings) -> dict[str, Any]:
    """Bytes each kind of search keeps for this haystack. The bank: its rows (indexes are shared by every tenant in the
    database and left out) and its BM25 index. Plain search: its passages' text, BM25 index and vectors."""
    from cie.retrieval import bm25

    bank = {}
    for t in ("documents", "sections", "memory_records", "record_links", "section_facts"):
        bank[t] = int(conn.execute(f"SELECT coalesce(sum(pg_column_size(x.*)), 0) FROM {t} x WHERE x.tenant_id = %s", (tenant_id,)).fetchone()[0])
    bank["bm25"] = _dir_bytes(bm25.tenant_dir(tenant_id, settings))
    meta = work / "plain_meta.json"
    plain = json.loads(meta.read_text()) if meta.exists() else {}
    return {"bank_bytes": bank, "bank_total": sum(bank.values()),
            "plain_bytes": {k: plain.get(k) for k in ("text_bytes", "bm25_bytes", "vector_bytes")},
            "plain_words_total": (plain.get("text_bytes") or 0) + (plain.get("bm25_bytes") or 0),
            "plain_total": (plain.get("text_bytes") or 0) + (plain.get("bm25_bytes") or 0) + (plain.get("vector_bytes") or 0)}


def _arms(spec: str | None) -> list[str]:
    arms = [x.strip() for x in spec.split(",") if x.strip()] if spec else list(ARMS)
    unknown = set(arms) - set(ARMS)
    if unknown:
        raise SystemExit(f"unknown arm(s) {sorted(unknown)}; choose from {', '.join(ARMS)}")
    return arms


def answer(work: Path, a: argparse.Namespace, log=print) -> dict[str, Any]:
    """The lookups planned by the model, then every question's answer in every arm, in chunks that are saved; the model
    is loaded only when something is left to ask."""
    from cie.core.settings import get_settings
    from cie.memory.facts import _connect

    arms = _arms(a.arms)
    info = json.loads((work / "evidence_info.json").read_text()) if (work / "evidence_info.json").exists() else {}
    if "bank+facts" in arms and not (info.get("facts") or {}).get("lines"):
        log("bank+facts: this memory bank holds no facts (cie.memory.facts import or extract): the arm is left out")
        arms.remove("bank+facts")
    questions = {q["id"]: q for q in _jsonl(work / "questions.jsonl")}
    evidence = {r["id"]: r for r in _jsonl(work / "evidence.jsonl")}
    missing = [qid for qid in questions if qid not in evidence]
    if missing:
        raise SystemExit(f"{len(missing)} questions have no evidence yet: run the evidence step first")
    prev = json.loads((work / "run.json").read_text()) if (work / "run.json").exists() else {}
    model: dict[str, Any] = {}

    def generate(convs: list, max_tokens: int) -> list[dict[str, Any]]:
        if "generate" not in model:
            model["generate"], model["name"] = make_generate(a, log=log)
        return model["generate"](convs, max_tokens)

    meta: dict[str, Any] = {"backend": a.backend, "arms": arms, "evidence_chars": EVIDENCE_CHARS}
    if "bank+lookup" in arms:
        settings = get_settings()
        conn = _connect(settings.database_url)
        _ld, tenant_id, _c, _a = _context(work)
        schema, fields = lookup_schema(conn, tenant_id)
        (work / "lookup_schema.txt").write_text(schema)
        ppath = work / "plans.jsonl"
        have = {r["id"] for r in _jsonl(ppath)}
        todo = [qid for qid in questions if qid not in have]
        t = time.perf_counter()
        for i in range(0, len(todo), a.chunk):
            ids = todo[i:i + a.chunk]
            outs = generate([plan_conversation(schema, questions[qid]["question"]) for qid in ids], 300)
            rows = []
            for qid, o in zip(ids, outs, strict=True):
                plan = parse_plan(o["text"], fields)
                blocks, found = run_lookup(conn, tenant_id, plan) if plan else ([], 0)
                rows.append({"id": qid, "raw": o["text"][:2000], "plan": plan, "found": found, "blocks": [f"{h}\n{b}" for h, b in blocks],
                             "prompt_tokens": o.get("prompt_tokens", 0), "output_tokens": o.get("output_tokens", 0)})
            _write_jsonl(ppath, rows, "a")
            log(f"  lookups: {len(have) + i + len(ids)}/{len(questions)}")
        if todo:
            meta["plan_seconds"] = round(time.perf_counter() - t, 1)
        for p in _jsonl(ppath):
            ev = evidence.get(p["id"])
            if ev is None:
                continue
            if p["found"]:
                lines, used = [], 0
                for b in p["blocks"]:
                    if used + len(b) + 1 > LOOKUP_CHARS:
                        break
                    lines.append(b)
                    used += len(b) + 1
                head = f"Records that match a lookup on the documents' fields ({p['found']} found, {len(lines)} shown):\n" + "\n".join(lines)
                rest, _ = fill([tuple(b) for b in ev["bank_blocks"]], EVIDENCE_CHARS - len(head) - 2)
                ev["bank+lookup"] = "\n\n".join([head] + rest)
            else:
                ev["bank+lookup"] = ev["bank"]
            ev["lookup_fallback"] = not p["found"]

    apath = work / "answers.jsonl"
    have = {(r["id"], r["arm"]) for r in _jsonl(apath)}
    todo = [(qid, arm) for qid in questions for arm in arms if (qid, arm) not in have and arm in evidence[qid]]
    t = time.perf_counter()
    for i in range(0, len(todo), a.chunk):
        part = todo[i:i + a.chunk]
        outs = generate([answer_conversation(questions[qid]["question"], evidence[qid][arm]) for qid, arm in part], a.max_tokens)
        _write_jsonl(apath, [{"id": qid, "arm": arm, "answer": o["text"], "prompt_tokens": o.get("prompt_tokens", 0),
                              "output_tokens": o.get("output_tokens", 0), "finish_reason": o.get("finish_reason"),
                              "evidence_chars": len(evidence[qid][arm]),
                              "lookup_fallback": evidence[qid].get("lookup_fallback") if arm == "bank+lookup" else None,
                              "ms": evidence[qid]["ms"].get(arm, evidence[qid]["ms"].get("bank"))}
                             for (qid, arm), o in zip(part, outs, strict=True)], "a")
        log(f"  answers: {len(have) + i + len(part)}/{len(have) + len(todo)}")
    meta["answer_seconds"] = round(time.perf_counter() - t, 1)
    meta["model"] = model.get("name") or prev.get("model")
    (work / "run.json").write_text(json.dumps({**prev, **meta, **info}, indent=1, default=str))
    return meta


def run(work: Path, a: argparse.Namespace, log=print) -> dict[str, Any]:
    """The evidence step, then the answer step, in this process."""
    collect_evidence(work, _arms(a.arms), a.facts_signature, Path(a.local) if getattr(a, "local", None) else None, log=log)
    return answer(work, a, log=log)


def facts_passages(work: Path, workers: int | None = None, log=print) -> dict[str, Any]:
    """The bank's passages in the layout of ``cie.eval.extract_facts`` (the same builder over the same documents, so their
    text and positions are the bank's sections'), in ``<work>/facts/passages.jsonl``. ``extract_facts run --work
    <work>/facts`` then makes their facts into a file that survives a disconnect, and ``cie.memory.facts import`` stores
    them in the bank."""
    import os
    from multiprocessing import Pool

    from cie.eval.extract_facts import _build_one

    hay = json.loads((work / "haystack.json").read_text())
    sources = Path(hay["root"]) / "generated_data" / "sources"
    index = json.loads((work / "index.json").read_text())["index"]
    out = work / "facts"
    out.mkdir(parents=True, exist_ok=True)
    with Pool(workers or max(1, (os.cpu_count() or 2) - 1)) as pool:
        built = [b for b in pool.imap(_build_one, [(str(sources), d, index[d]) for d in hay["dsids"]], chunksize=16) if b]
    n = 0
    with open(out / "passages.jsonl", "w") as fp:
        for b in built:
            for p in b["passages"]:
                fp.write(json.dumps(p) + "\n")
                n += 1
    info = {"documents": len(built), "failed": len(hay["dsids"]) - len(built), "passages": n}
    (out / "set.json").write_text(json.dumps(info, indent=1))
    log(f"facts passages: {info}")
    return info


# ------------------------------------------------------------------ scoring
def final_answer(text: str) -> str:
    """The text after the last "Answer:", or the whole answer when the model wrote no such line."""
    hits = list(re.finditer(r"(?im)^\W*answer\s*:\s*(.*)$", text or ""))
    return hits[-1].group(1).strip() if hits else (text or "").strip()


def dates_in(s: str) -> set[str]:
    out = {m.group(0) for m in ISO_RE.finditer(s)}
    for rx in TEXT_DATE_RES:
        for m in rx.finditer(s):
            g = m.groups()
            mon, day, yr = (g[0], g[1], g[2]) if not g[0].isdigit() else (g[1], g[0], g[2])
            try:
                out.add(date(int(yr), MONTHS[mon[:3].lower()], int(day)).isoformat())
            except ValueError:
                pass
    return out


def ids_in(s: str, kind: str) -> set[str]:
    return set(KEY_RE.findall(s)) if kind == "key" else set(PR_RE.findall(s))


def check(q: dict[str, Any], text: str) -> dict[str, Any]:
    """The code check of one answer: correct (True/False, None when the question has no expected value), and for lists
    precision, recall and F1."""
    line = final_answer(text)
    out: dict[str, Any] = {"not_found": bool(re.search(r"\bnot found\b", line, re.I))}
    e = q.get("expected") or {}
    if "date" in e:
        found = dates_in(line)
        out["correct"] = found == {e["date"]}
    elif "ids" in e:
        found, want = ids_in(line, e["id_kind"]), set(e["ids"])
        hit = len(found & want)
        p = hit / len(found) if found else 0.0
        r = hit / len(want)
        out.update({"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if hit else 0.0,
                    "correct": found == want})
    elif "value" in e:
        out["correct"] = any(re.search(r"(?<!\w)" + re.escape(_norm(v)) + r"(?!\w)", _norm(line)) for v in [e["value"], *e.get("alts", [])])
    else:
        out["correct"] = None
    return out


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    return (round(max(0.0, (c - r) / d), 3), round(min(1.0, (c + r) / d), 3))


def paired_ci(a: list[float], b: list[float], n_boot: int = 2000, seed: int = 11) -> tuple[float, float]:
    """95% bootstrap interval of mean(a) - mean(b) over the same questions."""
    if not a:
        return (0.0, 0.0)
    rng = random.Random(seed)
    d = [x - y for x, y in zip(a, b, strict=True)]
    means = sorted(statistics.fmean(rng.choices(d, k=len(d))) for _ in range(n_boot))
    return (round(means[int(0.025 * n_boot)], 3), round(means[int(0.975 * n_boot) - 1], 3))


def stratified_ci(groups: dict[str, tuple[list[float], list[float]]], n_boot: int = 2000, seed: int = 11) -> tuple[float, float]:
    """95% bootstrap interval of the mean over groups of each group's paired difference, resampling within each group."""
    diffs = [[x - y for x, y in zip(a, b, strict=True)] for a, b in groups.values() if a]
    if not diffs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(statistics.fmean(rng.choices(d, k=len(d))) for d in diffs) for _ in range(n_boot))
    return (round(means[int(0.025 * n_boot)], 3), round(means[int(0.975 * n_boot) - 1], 3))


JUDGE_PROMPT = """You grade an answer to a question about a company's documents against the reference answer.

Question: {question}
Reference answer: {reference}
Answer to grade: {answer}

Verdicts:
- correct: it states the reference answer's key information (the wording may differ; extra detail is fine unless it contradicts the reference).
- partly: it states some of the key information, or hedges between the right answer and a wrong one.
- wrong: the key information is wrong or missing, or it says the answer was not found.

Reply as JSON: {{"verdict": "correct" | "partly" | "wrong", "note": "<one short reason>"}}"""
JUDGE_SCORE = {"correct": 1.0, "partly": 0.5, "wrong": 0.0}


def judge(work: Path, model: str = "gpt-5.4-mini", groups: Iterable[str] = ("owners", "conflicts"), concurrency: int = 16,
          call: Callable[..., dict[str, Any]] | None = None, log=print) -> dict[str, Any]:
    """An OpenAI model grades the answers of these groups against the benchmark's gold answers."""
    from concurrent.futures import ThreadPoolExecutor

    questions = {q["id"]: q for q in _jsonl(work / "questions.jsonl")}
    path = work / "judge.jsonl"
    have = {(r["id"], r["arm"]) for r in _jsonl(path) if r.get("verdict") in JUDGE_SCORE}
    groups = set(groups)
    todo = [r for r in _jsonl(work / "answers.jsonl") if questions[r["id"]]["group"] in groups and (r["id"], r["arm"]) not in have
            and questions[r["id"]].get("gold_answer")]
    if call is None:
        from cie.eval.extract_facts import openai_judge

        call = openai_judge(model)

    def one(r):
        q = questions[r["id"]]
        try:
            v = call(JUDGE_PROMPT.format(question=q["question"], reference=q["gold_answer"], answer=r["answer"][:4000]), "answer")
        except Exception as e:  # noqa: BLE001 - one failed call is recorded, never the end of the run
            v = {"verdict": "judge_failed", "note": f"{type(e).__name__}: {e}"[:200], "in": 0, "out": 0}
        return {"id": r["id"], "arm": r["arm"], **v}

    out = []
    with ThreadPoolExecutor(concurrency) as ex:
        for i, row in enumerate(ex.map(one, todo), start=1):
            out.append(row)
            if len(out) >= 50 or i == len(todo):
                _write_jsonl(path, out, "a")
                out = []
                log(f"  judged {i}/{len(todo)}")
    rows = _jsonl(path)
    res = {"model": model, "served_by": getattr(call, "state", {}).get("served_by"), "calls": len(rows),
           "failed": sum(1 for r in rows if r.get("verdict") not in JUDGE_SCORE),
           "tokens_in": sum(r.get("in", 0) for r in rows), "tokens_out": sum(r.get("out", 0) for r in rows)}
    (work / "judge.json").write_text(json.dumps(res, indent=1))
    return res


def score(work: Path, log=print) -> dict[str, Any]:
    """Every arm's score per group, per kind of question, the decision rules and the storage, into report.json and
    report.md."""
    questions = {q["id"]: q for q in _jsonl(work / "questions.jsonl")}
    answers = _jsonl(work / "answers.jsonl")
    judged = {(r["id"], r["arm"]): r for r in _jsonl(work / "judge.jsonl") if r.get("verdict") in JUDGE_SCORE}
    run_meta = json.loads((work / "run.json").read_text()) if (work / "run.json").exists() else {}
    arms = [x for x in ARMS if any(r["arm"] == x for r in answers)]
    per: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)  # arm -> question id -> scores
    rows_by_arm: dict[str, list[dict]] = defaultdict(list)
    for r in answers:
        q = questions.get(r["id"])
        if q is None:
            continue
        c = check(q, r["answer"])
        j = judged.get((r["id"], r["arm"]))
        sc: dict[str, float] = {}
        if q["group"] == "owners" and c["correct"] is not None:
            sc["code"] = float(c["correct"])
        if q["group"] == "deadlines":
            sc["code"] = float(c["correct"])
        if q["group"] == "lists":
            sc["code"] = c["f1"]
            sc["exact"] = float(c["correct"])
        if j:
            sc["judge"] = JUDGE_SCORE[j["verdict"]]
        sc["not_found"] = float(c["not_found"])
        per[r["arm"]][r["id"]] = sc
        rows_by_arm[r["arm"]].append({**r, **c})

    def primary(arm: str, group: str) -> tuple[list[str], list[float]]:
        """The question ids and scores that decide a group: code checks, and the judge for conflicts."""
        key = "judge" if group == "conflicts" else "code"
        ids = sorted(qid for qid, s in per[arm].items() if questions[qid]["group"] == group and key in s)
        return ids, [per[arm][qid][key] for qid in ids]

    table: dict[str, dict[str, Any]] = {}
    for arm in arms:
        t: dict[str, Any] = {}
        for g in GROUPS:
            ids, xs = primary(arm, g)
            t[g] = {"n": len(xs), "score": round(statistics.fmean(xs), 3) if xs else None, "ci": wilson(sum(xs), len(xs)) if xs else None}
        owners_j = [s["judge"] for qid, s in per[arm].items() if questions[qid]["group"] == "owners" and "judge" in s]
        t["owners_judged"] = {"n": len(owners_j), "score": round(statistics.fmean(owners_j), 3) if owners_j else None}
        exact = [s["exact"] for qid, s in per[arm].items() if "exact" in s]
        t["lists_exact"] = {"n": len(exact), "score": round(statistics.fmean(exact), 3) if exact else None}
        t["not_found"] = round(statistics.fmean([s["not_found"] for s in per[arm].values()]), 3) if per[arm] else None
        kinds: dict[str, list[float]] = defaultdict(list)
        for qid, s in per[arm].items():
            k = "judge" if questions[qid]["group"] == "conflicts" else "code"
            if k in s:
                kinds[questions[qid]["kind"]].append(s[k])
        t["by_kind"] = {k: {"n": len(v), "score": round(statistics.fmean(v), 3)} for k, v in sorted(kinds.items())}
        rs = rows_by_arm[arm]
        t["prompt_tokens_mean"] = round(statistics.fmean([r["prompt_tokens"] for r in rs])) if rs else None
        ms = sorted(r["ms"] for r in rs if r.get("ms") is not None)
        t["search_ms_p50"] = ms[len(ms) // 2] if ms else None
        t["search_ms_p95"] = ms[min(len(ms) - 1, int(0.95 * len(ms)))] if ms else None
        if arm == "bank+lookup":
            t["lookup_fallback"] = round(statistics.fmean([float(bool(r.get("lookup_fallback"))) for r in rs]), 3) if rs else None
        table[arm] = t

    def diff(a: str, b: str, group: str) -> dict[str, Any] | None:
        """a minus b on a group, over the questions both answered (paired)."""
        if a not in table or b not in table:
            return None
        ida, _ = primary(a, group)
        idb, _ = primary(b, group)
        ids = sorted(set(ida) & set(idb))
        if not ids:
            return None
        key = "judge" if group == "conflicts" else "code"
        xa, xb = [per[a][i][key] for i in ids], [per[b][i][key] for i in ids]
        return {"n": len(ids), "diff": round(statistics.fmean(xa) - statistics.fmean(xb), 3), "ci95": paired_ci(xa, xb)}

    def paired(a: str, b: str, group: str) -> tuple[list[float], list[float]]:
        key = "judge" if group == "conflicts" else "code"
        ids = sorted(set(primary(a, group)[0]) & set(primary(b, group)[0]))
        return [per[a][i][key] for i in ids], [per[b][i][key] for i in ids]

    def mean_diff(a: str, b: str) -> dict[str, Any] | None:
        """The mean of the groups' differences: all four, or the three code-checked ones when the judge did not run; its
        interval resamples the questions within each group."""
        ds = {g: diff(a, b, g) for g in GROUPS}
        ds = {g: x["diff"] for g, x in ds.items() if x}
        if not {"owners", "deadlines", "lists"} <= set(ds):
            return None
        return {"diff": round(statistics.fmean(ds.values()), 3), "groups": sorted(ds),
                "ci95": stratified_ci({g: paired(a, b, g) for g in ds})}

    diffs = {f"{a} - {b}": {g: diff(a, b, g) for g in GROUPS} | {"mean": mean_diff(a, b)}
             for a, b in (("bank+lookup", "plain"), ("bank", "plain"), ("bank+facts", "bank"), ("plain", "plain-words"))}
    crit = criteria(diffs)
    clear = clarity(diffs, crit)
    rep = {"questions": len(questions), "by_group": dict(Counter(q["group"] for q in questions.values())), "arms": table,
           "differences": diffs, "criteria": crit, "clearly": clear, "run": {k: v for k, v in run_meta.items() if k != "storage"},
           "storage": run_meta.get("storage"), "judge": json.loads((work / "judge.json").read_text()) if (work / "judge.json").exists() else None}
    (work / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    md = to_markdown(rep)
    (work / "report.md").write_text(md)
    log(md)
    return rep


def criteria(diffs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The pre-registered rules (docs/MEMORY_TEST_PREREGISTRATION.md). A rule that needs a group with no result (the
    judge did not run, or an arm is missing) is undecided."""

    def d(name: str, g: str) -> float | None:
        x = (diffs.get(name) or {}).get(g)
        return x.get("diff") if isinstance(x, dict) else None

    def rule(parts: list[tuple[float | None, str, float]]) -> bool | None:
        if any(v is None for v, _, _ in parts):
            return None
        return all((v >= t) if op == ">=" else (v <= t) for v, op, t in parts)

    lk, bk, fc, pv = "bank+lookup - plain", "bank - plain", "bank+facts - bank", "plain - plain-words"
    gain = max([v for v in (d(lk, "deadlines"), d(lk, "lists")) if v is not None], default=None)
    # the conflicts guards apply when the judge ran (conflicts have no code check)
    r1 = rule([(gain, ">=", 0.10), (d(lk, "owners"), ">=", -0.03)] + ([(d(lk, "conflicts"), ">=", -0.03)] if d(lk, "conflicts") is not None else []))
    r2 = rule([(d(bk, "mean"), ">=", 0.03)])
    r3 = rule([(d(fc, "mean"), ">=", 0.05)] + [(d(fc, g), ">=", -0.03) for g in GROUPS if g != "conflicts" or d(fc, g) is not None])
    r4 = rule([(d(pv, "mean"), ">=", 0.03)])
    return {"1. structured lookup earns its place": r1, "2. the bank's search earns its place": r2,
            "3. the Llama facts earn their place": r3, "4. vector search earns its place in plain search": r4}


def clarity(diffs: dict[str, dict[str, Any]], crit: dict[str, Any]) -> dict[str, bool | None]:
    """For each rule that is met: whether the interval of the difference it rests on excludes zero (rule 1: the larger of
    the deadlines and lists gains; the others: the mean of the groups)."""
    out: dict[str, bool | None] = {}
    for (name, met), key in zip(crit.items(), ("bank+lookup - plain", "bank - plain", "bank+facts - bank", "plain - plain-words"), strict=True):
        ds = diffs.get(key) or {}
        if not met:
            out[name] = None
            continue
        if key == "bank+lookup - plain":
            best = max([ds[g] for g in ("deadlines", "lists") if ds.get(g)], key=lambda x: x["diff"])
            out[name] = best["ci95"][0] > 0
        else:
            out[name] = ds["mean"]["ci95"][0] > 0
    return out


def to_markdown(rep: dict[str, Any]) -> str:
    def f(x: Any) -> str:
        return "–" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))

    run_meta = rep.get("run") or {}
    lines = [f"### Memory test: {rep['questions']} questions ({', '.join(f'{g} {n}' for g, n in rep['by_group'].items())}), "
             f"model {run_meta.get('model', '?')}", "",
             "Fictional company data (EnterpriseRAG-Bench). Owners, deadlines: share correct (code check). Lists: mean F1 of the "
             "keys or numbers listed. Conflicts: the judge's score (correct 1, partly 0.5).", "",
             "| arm | owners | deadlines | lists (F1) | conflicts (judge) | owners (judge) | lists, exact | 'not found' | prompt tokens | search p50 / p95 ms |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for arm, t in rep["arms"].items():
        lines.append(f"| {arm} | {f(t['owners']['score'])} | {f(t['deadlines']['score'])} | {f(t['lists']['score'])} | "
                     f"{f(t['conflicts']['score'])} | {f(t['owners_judged']['score'])} | {f(t['lists_exact']['score'])} | {f(t['not_found'])} | "
                     f"{f(t['prompt_tokens_mean'])} | {f(t['search_ms_p50'])} / {f(t['search_ms_p95'])} |")
    first = next(iter(rep["arms"].values()), None)
    if first:
        lines += ["", "**Per kind of question** (n per arm in the first row):", "", "| arm | " + " | ".join(
            f"{k} ({v['n']})" for k, v in first["by_kind"].items()) + " |", "|---|" + "---|" * len(first["by_kind"])]
        for arm, t in rep["arms"].items():
            lines.append(f"| {arm} | " + " | ".join(f(t["by_kind"].get(k, {}).get("score")) for k in first["by_kind"]) + " |")
    lines += ["", "**Differences** (paired over the same questions; 95% bootstrap interval):", "",
              "| comparison | owners | deadlines | lists | conflicts | mean of the four |", "|---|---|---|---|---|---|"]
    for name, ds in rep["differences"].items():
        cells = [("–" if not ds.get(g) else f"{ds[g]['diff']:+.3f} [{ds[g]['ci95'][0]:+.2f}, {ds[g]['ci95'][1]:+.2f}]") for g in GROUPS]
        m = ds.get("mean")
        mean = "–" if not m else f"{m['diff']:+.3f}" + ("" if len(m["groups"]) == len(GROUPS) else " (no conflicts: judge not run)")
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {mean} |")
    lines += ["", "**Pre-registered rules** (docs/MEMORY_TEST_PREREGISTRATION.md):", ""]
    for k, v in rep["criteria"].items():
        c = (rep.get("clearly") or {}).get(k)
        note = "" if c is None else " (clearly: its interval excludes zero)" if c else " (not clearly: its interval includes zero)"
        lines.append(f"- {k}: **{'met' if v else 'not met' if v is False else 'undecided'}**{note}")
    lk = (rep["arms"].get("bank+lookup") or {}).get("lookup_fallback")
    if lk is not None:
        lines += ["", f"bank+lookup fell back to the bank's search alone (no usable lookup, or nothing found) on {lk:.0%} of questions."]
    st = rep.get("storage")
    if st:
        lines += ["", f"**Storage for this haystack:** memory bank rows and BM25 index {st['bank_total'] / 1e6:.1f} MB "
                      f"({', '.join(f'{k} {v / 1e6:.1f}' for k, v in st['bank_bytes'].items())}; its database indexes are shared by every "
                      f"tenant and not counted); plain search {st['plain_total'] / 1e6:.1f} MB, of which words only "
                      f"{st['plain_words_total'] / 1e6:.1f} MB."]
    if rep.get("judge"):
        j = rep["judge"]
        lines += ["", f"Judge: {j['model']} (served by {j.get('served_by')}), {j['calls']} calls, {j['failed']} failed."]
    return "\n".join(lines)


# ------------------------------------------------------------------ command line
def main(argv: Iterable[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("questions", help="the haystack and the questions (no database, no model)")
    q.add_argument("--root", required=True, help="the EnterpriseRAG-Bench checkout (questions.jsonl, extra_questions.jsonl, generated_data/sources)")
    q.add_argument("--docs", type=int, default=5000)
    q.add_argument("--seed", type=int, default=5, help="5: the haystack of the earlier 5,000-document runs")
    q.add_argument("--questions", type=int, default=None, help="only the first N benchmark questions choose the haystack (a small test)")
    q.add_argument("--metadata", type=int, default=None, help="only the first N metadata questions")
    q.add_argument("--conflicting", type=int, default=None, help="only the first N conflicting_info questions")
    ld = sub.add_parser("load", help="load the haystack as a memory bank (or reuse the one that holds it)")
    ld.add_argument("--batch", type=int, default=64)
    ld.add_argument("--workers", type=int, default=None)
    ld.add_argument("--reuse", default="auto", help="auto: a tenant that holds exactly this haystack; a tenant name; or '' to load anew")
    pl = sub.add_parser("plain", help="plain search over the raw documents: passages, BM25 index, vectors")
    pl.add_argument("--no-vectors", action="store_true")
    fp = sub.add_parser("facts-passages", help="the bank's passages for cie.eval.extract_facts run, in <work>/facts")
    fp.add_argument("--workers", type=int, default=None)
    ev = sub.add_parser("evidence", help="each question's evidence for the arms that need no model")
    an = sub.add_parser("answer", help="the model plans the lookups and answers every question in every arm")
    r = sub.add_parser("run", help="evidence, then answer, in one process")
    for p in (ev, an, r):
        p.add_argument("--arms", default=None, help=f"comma-separated, from {', '.join(ARMS)} (default: all)")
    for p in (ev, r):
        p.add_argument("--facts-signature", default=None, help="the facts of this extractor (default: the one with most sections)")
    for p in (an, r):
        p.add_argument("--backend", choices=["vllm", "openai", "fake"], default="vllm")
        p.add_argument("--model", default="llama-3.1-8b")
        p.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
        p.add_argument("--concurrency", type=int, default=4)
        p.add_argument("--max-tokens", type=int, default=400)
        p.add_argument("--chunk", type=int, default=512, help="prompts per call; results are saved after each")
        p.add_argument("--gpu-mem", type=float, default=0.85)
        p.add_argument("--max-model-len", type=int, default=16384)
        p.add_argument("--max-num-seqs", type=int, default=None)
        p.add_argument("--max-num-batched-tokens", type=int, default=None)
        p.add_argument("--quantization", default="none")
    j = sub.add_parser("judge", help="an OpenAI model grades the owners and conflicts answers (OPENAI_API_KEY)")
    j.add_argument("--model", default="gpt-5.4-mini")
    j.add_argument("--concurrency", type=int, default=16)
    s = sub.add_parser("score", help="scores, differences, the pre-registered rules and storage: report.md")
    for p in (q, ld, pl, fp, ev, an, r, j, s):
        p.add_argument("--work", required=True)
    for p in (ld, pl, ev, r):
        p.add_argument("--local", default=None, help="a directory on this machine's disk for the plain index and the embedding cache "
                                                     "(default: --work)")
    a = ap.parse_args(list(argv) if argv is not None else None)
    work = Path(a.work)
    local = Path(a.local) if getattr(a, "local", None) else None
    if a.cmd == "questions":
        return build_questions(Path(a.root), work, a.docs, a.seed, a.questions, a.metadata, a.conflicting)
    if a.cmd == "load":
        return load_bank(work, a.batch, a.workers, a.reuse, local)
    if a.cmd == "plain":
        from cie.core.settings import get_settings
        from cie.memory.embeddings import get_embedding_provider

        return build_plain(work, None if a.no_vectors else get_embedding_provider(get_settings()), local)
    if a.cmd == "facts-passages":
        return facts_passages(work, a.workers)
    if a.cmd == "evidence":
        return collect_evidence(work, _arms(a.arms), a.facts_signature, local)
    if a.cmd == "answer":
        return answer(work, a)
    if a.cmd == "run":
        return run(work, a)
    if a.cmd == "judge":
        return judge(work, a.model, concurrency=a.concurrency)
    return score(work)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if main() is not None else 1)
