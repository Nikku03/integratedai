"""A large language model as the company brain's reasoning engine (docs/FACTBANK_50K_PLAN.md).

The brain (``cie.factbank.brain``, v18) answers by exact lookups and plans of at most two steps, and quotes sentences for
free text. The reasoning engine is a language model that works on top of it, through tools that read the same fact bank:

- **brain** {question}: the brain's answer, route, reason and evidence. Exact for a field of a document it names.
- **search** {query, system?}: the documents whose text best matches the words (SQLite FTS5, BM25), up to ``SEARCH_K``.
- **read** {doc, query?}: one document's text and fields; a long one cut to the passages that best match the query.
- **find** {system, where, show?}: every document of a system whose fields hold exactly these values (case and spacing do
  not matter; a person by full name), how many there are, and up to ``FIND_ROWS`` of them with the fields asked for.
- **values** {system, field}: the values a field takes in a system, with how many documents hold each.

The model is told the brain's answer to the question first (the v18 arm's answer, so the brain is not asked twice) and
decides: keep it, check it, or work the question out in steps (``MAX_STEPS`` tool calls at most). It replies with one JSON
object a turn ({"tool", "args"} or {"answer"}); its thinking, when the model thinks, is dropped from the conversation.
Every conversation advances in lockstep: one batched generation per step for all of them (vLLM's offline engine, or any
OpenAI-compatible endpoint), then every tool call of that step run in parallel processes (``ToolPool``).

The plain-search arm ("rag") is the same model with no brain: it reads the passages a keyword search finds
(``brain_test.Passages``) and answers in one turn. It is the standard AI search baseline: search, then a model.
A conversation that ends with no answer of its own (no reply it can read after two reminders) keeps the brain's answer.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Any

SEARCH_K = 8
FIND_ROWS = 40
VALUES_ROWS = 40
READ_CHARS = 6000
EVIDENCE_CHARS = 2500
SNIPPET = 160
# What one tool result may hold, so that eight of them and the replies fit the model's window (32,768 tokens, at about
# three characters a token): a field's value is cut at FIELD_CHARS, and a find or values result keeps the rows that fit.
FIELD_CHARS = 300
RESULT_CHARS = 8000
CONV_CHARS = 60000  # a conversation this long must answer at its next turn (as after MAX_STEPS tool calls)
MAX_STEPS = 8  # tool calls a conversation may make before it must answer
ANSWER_CAP = 1100  # characters of a final answer, as the brain's free-text quote is capped (prose.QUOTE_CAP)
RAW_CHARS = 1500  # characters of the model's visible reply kept with each answer, to read it again without the GPU
RAG_PASSAGES = 12
RAG_CHARS = 14000  # room for all 12 passages (about 1,000 characters each)
MIN_ROOM = 2048  # tokens of the model's window a turn needs at least; a conversation with less left ends (the brain's answer)
TOOLS = ("brain", "search", "read", "find", "values")
NOT_FOUND = "not found"

# (repository, pinned revision) for each model name; the 8B models are fact extraction's (``cie.eval.extract_facts``)
MODELS: dict[str, list[tuple[str, str | None]]] = {
    # Qwen3.8-27B (August 2026, Apache-2.0): 27B dense, thinking on by default; bf16 (55 GB) for an 80 GB GPU, Qwen's own
    # FP8 copy (28 GB, weight-only through vLLM's Marlin kernels on an A100) for a 40 GB one. Revisions checked 2026-10-17.
    "qwen3.8-27b": [("Qwen/Qwen3.8-27B", "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0")],
    "qwen3.8-27b-fp8": [("Qwen/Qwen3.8-27B-FP8", "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a")],
}
# chat template arguments by model family: Qwen3.8 thinks by default; its effort is set by the template
THINKING = {"qwen3.8": True}

SYSTEM = """You answer questions about one company from its internal records: Linear issues, Jira tickets, GitHub pull \
requests, HubSpot accounts, Gmail threads, Slack threads, Google Drive files, Confluence pages and Fireflies meeting notes. \
You see the records only through tools that read the company's fact bank, which holds every record and every field of it \
exactly.

Each turn, reply with exactly one JSON object and nothing else: a tool call such as
  {"tool": "find", "args": {"system": "linear", "where": {"status": "Todo"}}}
or, when you are done, your final answer such as
  {"answer": "ENG-4833"}

Tools:
- brain {"question": "..."}: the company brain answers one question by exact lookups in the records, and says how (its \
route and evidence). It is reliable for one field of a record the question names ("When is ENG-12 due?"), counts with \
plain filters, and links of two steps. For a longer chain, ask it one step at a time.
- search {"query": "...", "system": "linear"}: the records whose text best matches the words (keyword search), up to 8, \
each with its id, system, title and date. "system" is optional.
- read {"doc": "<id>", "query": "..."}: one record's fields and text. "query" is optional and picks the passages of a \
long record.
- find {"system": "jira", "where": {"assignee": "Ava Chen", "priority": "P1"}, "show": ["key", "status"]}: every record of \
that system whose fields hold exactly these values (case does not matter; a person by full name), how many there are, and \
up to 40 of them with the fields in "show". Use it to count and to list.
- values {"system": "linear", "field": "status"}: the values a field takes in a system, with how many records hold each. \
Use it to learn how a value is written before you filter on it.

Rules:
- Answer only from what the tools return, never from what you assume.
- If the records do not hold the answer, answer "not found". If the question names a record, person or thing the company \
does not have, answer "not found": never answer from a similar one.
- Count and list with find, never by hand from search results.
- Write the final answer the way a colleague would want it: a name, a number, a date (YYYY-MM-DD), an id or a list \
(separated by commas) when the question asks for one; a count starts with the number. When the question asks what was \
said, decided or planned, answer in at most three sentences that keep the record's own words: copy its key phrases, \
figures, names and dates as the record writes them."""

FIRST = """Question: {question}

The company brain's first answer:
{brain}

Decide whether this answers the question. If it does, reply {{"answer": ...}} with it. If it does not, or you are not \
sure, use the tools."""

LAST = ('You have used every tool call. Reply now with {"answer": ...} holding your best answer from what the tools returned, '
        'or {"answer": "not found"}.')
AGAIN = 'Reply with exactly one JSON object: a tool call {"tool": ..., "args": {...}} or your final answer {"answer": ...}.'
CUT = 'Your reply was cut off. Think less and reply with exactly one JSON object now.'

RAG_SYSTEM = """You answer questions about one company from passages of its internal records (Linear, Jira, GitHub, \
HubSpot, Gmail, Slack, Google Drive, Confluence, Fireflies meeting notes), found by a keyword search.

Rules:
- Answer only from the passages. If they do not hold the answer, or the question names a record, person or thing that is \
not in them, the answer is "not found": never answer from a similar one.
- End with one line that starts with "Answer:" and gives your final answer, such as "Answer: 3" or "Answer: not found". \
Write the answer the way a colleague would want it: a name, a number, a date \
(YYYY-MM-DD), an id or a list (separated by commas) when the question asks for one; a count starts with the number. When \
the question asks what was said, decided or planned, answer in at most three sentences that keep the passages' own words: \
copy their key phrases, figures, names and dates as the passages write them."""
RAG_CUT = 'Your reply was cut off. Think less, and end with one line that starts with "Answer:".'
RAG_AGAIN = 'End your reply with one line that starts with "Answer:" and gives your final answer.'


# ------------------------------------------------------------------ tools
def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _terms(q: str) -> list[str]:
    from cie.retrieval.lexical import _terms as lexical_terms

    return list(dict.fromkeys(lexical_terms(q)))


class Toolbox:
    """The tools over one fact bank (``factbank_v2.sqlite``). ``brain`` is a ``cie.factbank.brain.Brain`` or a callable
    question -> its row; without one the brain tool says it is not there."""

    def __init__(self, bank_path: str | Path, brain: Any = None):
        self.con = sqlite3.connect(f"file:{Path(bank_path)}?mode=ro", uri=True, check_same_thread=False)
        self.brain = brain
        self.docs = {i: (t, s, d) for i, t, s, d in self.con.execute("SELECT id, title, system, date FROM sources")}
        self.systems = {v[1] for v in self.docs.values()}
        self._by_value: dict[tuple[str, str, str], set[str]] | None = None
        self._fields: dict[str, dict[str, list[str]]] | None = None

    def _index(self) -> None:
        """Every (system, field, value) -> the documents holding it, and every document's fields, read once."""
        by: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        shown: dict[tuple[str, str, str], str] = {}
        fields: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for p, v, src in self.con.execute("SELECT parameter, value, source FROM facts WHERE entity LIKE 'doc:%'"):
            info = self.docs.get(src)
            if info is None or p in ("text_date", "text_key", "referenced_by"):
                continue
            key = (info[1], p, _norm(v))
            by[key].add(src)
            shown.setdefault(key, str(v).strip())
            fields[src][p].append(str(v))
        self._by_value, self._fields, self._shown = dict(by), {k: dict(v) for k, v in fields.items()}, shown

    def fields(self, dsid: str) -> dict[str, list[str]]:
        if self._fields is None:
            self._index()
        return self._fields.get(dsid, {})

    @staticmethod
    def _dsid(doc: str) -> str:
        return str(doc).strip().removeprefix("doc:")

    def _label(self, dsid: str) -> dict[str, Any]:
        title, system, date = self.docs.get(dsid, ("", "", ""))
        out = {"doc": dsid, "system": system, "title": title, "date": date}
        if key := (self.fields(dsid).get("key") or self.fields(dsid).get("pr_number") or [None])[0]:
            out["key"] = key
        return out

    def search(self, query: str, system: str | None = None, k: int = SEARCH_K) -> dict[str, Any]:
        terms = _terms(query)
        if not terms:
            return {"results": [], "note": "no searchable words in the query"}
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self.con.execute("SELECT id, text FROM entities_fts WHERE entities_fts MATCH ? AND id LIKE 'doc:%' "
                                "ORDER BY bm25(entities_fts, 0.0, 4.0, 1.0) LIMIT ?", (match, 200 if system else k))
        out = []
        for i, text in rows:
            dsid = self._dsid(i)
            lab = self._label(dsid)
            if system and lab["system"] != _norm(system).replace(" ", "_"):
                continue
            body = re.sub(r"\s+", " ", str(text or ""))
            hit = min((body.lower().find(t) for t in terms if body.lower().find(t) >= 0), default=0)
            out.append({**lab, "snippet": body[max(0, hit - 40): max(0, hit - 40) + SNIPPET]})
            if len(out) >= k:
                break
        return {"results": out}

    def read(self, doc: str, query: str | None = None, chars: int = READ_CHARS) -> dict[str, Any]:
        dsid = self._dsid(doc)
        row = self.con.execute("SELECT name, text FROM entities_fts WHERE id = ?", (f"doc:{dsid}",)).fetchone()
        if row is None:
            return {"error": f"no record {doc!r}: use an id that search or find returned"}
        text = str(row[1] or "")
        if len(text) > chars:
            text = self._passages(text, query or "", chars)
        return {**self._label(dsid), "text": text}

    @staticmethod
    def _passages(text: str, query: str, chars: int, window: int = 700) -> str:
        """The document's start (its fields) and the windows of about ``window`` characters, cut at sentence and line ends,
        that hold the most of the query's words, in their order, up to ``chars``."""
        cut = min(window, chars // 3)
        head = text[:cut]
        parts = re.split(r"(?<=[.!?\n])\s+", text[cut:])
        windows, cur = [], ""
        for x in parts:
            if cur and len(cur) + len(x) > min(window, chars // 3):
                windows.append(cur)
                cur = ""
            cur = f"{cur} {x}" if cur else x
        if cur:
            windows.append(cur)
        terms = set(_terms(query))
        rank = sorted(range(len(windows)), key=lambda i: (-len({t for t in terms if t in windows[i].lower()}), i))
        keep, used = [], len(head)
        for i in rank:
            if used + len(windows[i]) > chars:
                break
            keep.append(i)
            used += len(windows[i]) + 5
        return "\n[...]\n".join([head, *(windows[i] for i in sorted(keep))]) + "\n[... the rest of the record is left out]"

    def find(self, system: str, where: dict[str, Any] | None = None, show: Iterable[str] | None = None) -> dict[str, Any]:
        if self._by_value is None:
            self._index()
        system = _norm(system).replace(" ", "_")
        if system not in self.systems:
            return {"error": f"no system {system!r}: one of " + ", ".join(sorted(self.systems))}
        hits: set[str] | None = None
        for f, v in (where or {}).items():
            vals = v if isinstance(v, list) else [v]
            got: set[str] = set()
            for x in vals:
                got |= self._by_value.get((system, str(f), _norm(x)), set())
            hits = got if hits is None else hits & got
        if hits is None:
            hits = {d for d, info in self.docs.items() if info[1] == system}
        if isinstance(show, str):  # "key, status", as Qwen's own tool-call format writes a value
            show = [x.strip() for x in show.split(",") if x.strip()]
        show = [str(s) for s in (show or [])][:6]
        rows, used = [], 0
        for dsid in sorted(hits, key=lambda d: (self.docs[d][0] or "", d))[:FIND_ROWS]:
            lab = self._label(dsid)
            fs = self.fields(dsid)
            row = {**{k: _cut(lab[k]) for k in ("doc", "title", "key") if k in lab}, **{s: _cut(", ".join(fs.get(s, []))) or None for s in show}}
            used += len(json.dumps(row, ensure_ascii=False, default=str)) + 2
            if rows and used > RESULT_CHARS:
                break
            rows.append(row)
        out: dict[str, Any] = {"count": len(hits), "records": rows}
        if len(hits) > len(rows):
            out["note"] = f"{len(hits)} records match; the first {len(rows)} are shown" + (
                "" if len(rows) == min(len(hits), FIND_ROWS) else ' (narrow "where" or ask for fewer "show" fields to see more)')
        return out

    def values(self, system: str, field: str) -> dict[str, Any]:
        if self._by_value is None:
            self._index()
        system = _norm(system).replace(" ", "_")
        counts = sorted(((len(ds), v) for (s, f, v), ds in self._by_value.items() if s == system and f == field), reverse=True)
        if not counts:
            fs = sorted({f for (s, f, _v) in self._by_value if s == system})
            return {"error": f"no field {field!r} in {system!r}", "fields": fs[:80]}
        vals, used = [], 0
        for n, v in counts[:VALUES_ROWS]:
            x = {"value": _cut(self._shown[(system, field, v)], FIELD_CHARS // 2), "records": n}
            used += len(json.dumps(x, ensure_ascii=False)) + 2
            if vals and used > RESULT_CHARS:
                break
            vals.append(x)
        return {"values": vals, "distinct": len(counts)}

    def ask_brain(self, question: str) -> dict[str, Any]:
        if self.brain is None:
            return {"error": "the brain is not available here"}
        r = self.brain(question) if callable(self.brain) else self.brain.ask(question)
        return brain_view(r)

    def run(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """One tool call; a wrong call is answered with what was wrong, never raised."""
        try:
            if tool == "brain":
                return self.ask_brain(str(args["question"]))
            if tool == "search":
                return self.search(str(args["query"]), args.get("system"))
            if tool == "read":
                return self.read(str(args["doc"]), args.get("query"))
            if tool == "find":
                where = args.get("where") or {}
                if not isinstance(where, dict):
                    return {"error": '"where" must be an object of field: value'}
                return self.find(str(args["system"]), where, args.get("show"))
            if tool == "values":
                return self.values(str(args["system"]), str(args["field"]))
        except KeyError as e:
            return {"error": f"missing argument {e}"}
        except Exception as e:  # noqa: BLE001 - the model sees the error and can try again
            return {"error": f"{type(e).__name__}: {e}"[:300]}
        return {"error": f"no tool {tool!r}: one of {', '.join(TOOLS)}"}


def _cut(s: Any, chars: int = FIELD_CHARS) -> Any:
    """A field's value cut at ``chars`` characters (what is not a string is kept as it is)."""
    return s[:chars] + " [...]" if isinstance(s, str) and len(s) > chars else s


def brain_view(r: dict[str, Any], chars: int = EVIDENCE_CHARS) -> dict[str, Any]:
    """What the model sees of a brain row: its answer, route, reason and evidence (cut to ``chars``)."""
    ev = str(r.get("evidence") or "")
    return {"answer": r.get("answer"), "route": r.get("route"), "reason": str(r.get("reason") or "")[:400],
            "evidence": ev[:chars] + (" [...]" if len(ev) > chars else "")}


# ------------------------------------------------------------------ tool processes
_BOX: Toolbox | None = None
_BOX_ERROR: str | None = None


def _make_box(bank: str, single: str | None, plans: str | None, router: str | None) -> Toolbox:
    brain = None
    if single and plans:
        from cie.factbank.brain import Brain, Router, general_words

        brain = Brain(bank, single, plans, Router.load(router) if router else None, v16=True, v17=True, v18=True)
        general_words()  # read once here: processes forked after this share it
    return Toolbox(bank, brain)


def _init_worker(bank: str, single: str | None, plans: str | None, router: str | None) -> None:
    """A worker's toolbox; one that fails to load is kept as its error, which ``ToolPool`` raises (never answered as a tool
    result: the model would go on without the brain)."""
    global _BOX, _BOX_ERROR
    try:
        _BOX = _make_box(bank, single, plans, router)
    except Exception as e:  # noqa: BLE001 - raised by ToolPool
        _BOX_ERROR = f"{type(e).__name__}: {e}"


def _run_call(call: tuple[str, dict[str, Any]]) -> tuple[dict[str, Any], float]:
    if _BOX is None:
        raise RuntimeError(f"the toolbox did not load in a worker: {_BOX_ERROR}")
    t = time.perf_counter()
    out = _BOX.run(*call)
    return out, round(time.perf_counter() - t, 3)


class ToolPool:
    """Tool calls run in ``workers`` processes, each with its own toolbox and brain (forked before any model is loaded)."""

    def __init__(self, bank: Path, single: Path | None = None, plans: Path | None = None, router: Path | None = None,
                 workers: int | None = None):
        import multiprocessing as mp

        self.workers = workers or max(1, min(10, (os.cpu_count() or 2) - 2))
        init = (str(bank), str(single) if single else None, str(plans) if plans else None, str(router) if router else None)
        _make_box(*init)  # a broken setup (a lessons file, a glossary) stops here, before any process starts
        self.pool = ProcessPoolExecutor(self.workers, mp_context=mp.get_context("fork"), initializer=_init_worker, initargs=init)
        list(self.pool.map(_run_call, [("values", {"system": "linear", "field": "status"})] * self.workers))  # load them all now

    def run(self, calls: list[tuple[str, dict[str, Any]]]) -> list[tuple[dict[str, Any], float]]:
        return list(self.pool.map(_run_call, calls, chunksize=1))

    def close(self) -> None:
        self.pool.shutdown()


class LocalTools:
    """Tool calls in this process (tests, small runs)."""

    def __init__(self, box: Toolbox):
        self.box = box

    def run(self, calls: list[tuple[str, dict[str, Any]]]) -> list[tuple[dict[str, Any], float]]:
        out = []
        for c in calls:
            t = time.perf_counter()
            out.append((self.box.run(*c), round(time.perf_counter() - t, 3)))
        return out


# ------------------------------------------------------------------ replies
THINK_END = re.compile(r"</think>", re.I)


def visible(text: str) -> str:
    """The reply without its thinking: what follows the last ``</think>``, or nothing when the thinking never ended."""
    text = text or ""
    if THINK_END.search(text):
        return THINK_END.split(text)[-1].strip()
    if re.match(r"\s*<think>", text):
        return ""
    return text.strip()


def _objects(text: str) -> list[str]:
    """Every balanced {...} of the text, outermost first, in order (braces inside JSON strings are skipped)."""
    out, depth, start, in_str, esc = [], 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"' and depth:
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                out.append(text[start: i + 1])
    return out


FUNCTION = re.compile(r"<function=([\w.-]+)>(.*?)</function>", re.S)  # Qwen's own tool-call format
PARAMETER = re.compile(r"<parameter=([\w.-]+)>\n?(.*?)\n?</parameter>", re.S)


def _tool_call(obj: dict[str, Any]) -> dict[str, Any] | None:
    """{"tool", "args"} from a JSON tool call: ours ({"tool", "args"}) or the usual ones ({"name", "arguments" or
    "parameters"})."""
    name = obj.get("tool") if isinstance(obj.get("tool"), str) else obj.get("name") if isinstance(obj.get("name"), str) else None
    if name is None or (obj.get("tool") is None and not ({"arguments", "args", "parameters"} & set(obj))):
        return None
    args = obj.get("args", obj.get("arguments", obj.get("parameters")))
    if isinstance(args, str):
        try:
            args = json.loads(args, strict=False)
        except json.JSONDecodeError:
            args = None
    if not isinstance(args, dict):
        args = {k: v for k, v in obj.items() if k not in ("tool", "name", "args", "arguments", "parameters")}
    return {"tool": name.strip().lower(), "args": args}


def _answer(a: Any) -> dict[str, Any]:
    """An answer object's answer as the reply's action: none is "not found", a list its items, a list over several lines
    one line (``one_line``)."""
    if a is None:
        return {"answer": NOT_FOUND}
    return {"answer": ", ".join(map(str, a)) if isinstance(a, list) else one_line(str(a))}


ANSWER_TOOLS = ("answer", "final_answer", "final")  # an answer written as a call: {"name": "answer", "arguments": {"answer": ...}}


def parse_action(text: str) -> dict[str, Any] | None:
    """The reply's action: {"tool", "args"} or {"answer"}, from its last JSON object that names one (raw line breaks in
    its strings allowed); then Qwen's own <function=...> tool call; then an "Answer:" line; None when the reply has none."""
    body = visible(text)
    for blob in reversed(_objects(body)):
        try:
            obj = json.loads(blob, strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "answer" in obj:
            return _answer(obj["answer"])
        if isinstance(obj, dict) and (call := _tool_call(obj)) is not None:
            return _answer(call["args"]["answer"]) if call["tool"] in ANSWER_TOOLS and "answer" in call["args"] else call
    if calls := FUNCTION.findall(body):
        name, inner = calls[-1]
        args: dict[str, Any] = {}
        for k, v in PARAMETER.findall(inner):
            try:
                args[k] = json.loads(v, strict=False)
            except json.JSONDecodeError:
                args[k] = v.strip()
        name = name.strip().lower()
        return _answer(args["answer"]) if name in ANSWER_TOOLS and "answer" in args else {"tool": name, "args": args}
    if (line := answer_line(body)) is not None:
        return {"answer": line, "join": True}
    return None


ANSWER_LABEL = re.compile(r"^\W*(?:final\s+)?answer\s*\**\s*:\s*\**\s*(.*)$", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def answer_line(body: str) -> str | None:
    """The answer of the reply's last "Answer:" (or "Final answer:") line, markdown stars dropped. When the line holds
    nothing else or ends with ":", the answer is the lines below it, and a list there ends the answer (a note after the
    list is left out; an item's indented lines stay with it); a list is made one line (``one_line``). Lines below an
    answer of its own are its explanation, left out. None when there is no such line."""
    lines = (body or "").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        m = ANSWER_LABEL.match(lines[i])
        if not m:
            continue
        rest = m.group(1).strip().strip("*").strip()
        if rest and not rest.endswith(":"):
            return rest
        block: list[str] = []
        in_list = False
        for raw in lines[i + 1:]:
            x = raw.strip()
            if not x:
                continue
            if LIST_ITEM.match(x):
                in_list = True
                block.append(x)
            elif in_list and raw[:1].isspace():
                block[-1] += " " + x
            elif in_list:
                break
            else:
                block.append(x)
        return one_line("\n".join([rest, *block] if rest else block)) if block else rest
    return None


def one_line(answer: str) -> str:
    """A list written over several lines (two items or more, or items under a line that ends with ":") as one line, for
    the scorers read the first line for a value, a date or keys: the lines before it, then its items (bullets or numbers
    dropped) joined by "; ". Any other answer is kept as it is."""
    lines = [x.strip() for x in (answer or "").splitlines() if x.strip()]
    first = next((n for n, x in enumerate(lines) if LIST_ITEM.match(x)), None)
    if first is None or not (sum(bool(LIST_ITEM.match(x)) for x in lines) >= 2 or (first and lines[first - 1].endswith(":"))):
        return (answer or "").strip()
    head, items = lines[:first], []
    for x in lines[first:]:
        if LIST_ITEM.match(x):
            items.append(LIST_ITEM.sub("", x).strip().strip("*").strip())
        else:
            items[-1] += " " + x
    return " ".join([*head, "; ".join(items)]).strip()


# a reply that says there is no answer in other words than "not found": mapped to "not found" when it is one short
# sentence and nothing else (so a free-text answer such as "There is no rollback plan; it moves to Q3" is kept)
REFUSAL = re.compile(
    r"^\W*(?:"
    r"(?:the |these |those )?(?:passages?|records?|documents?|context|tools?|results?|search results?|data|fact bank) "
    r"(?:do(?:es)?|did)(?: not|n[o']t) (?:contain|mention|say|include|hold|show|specify|state|list|name|give|provide|record|have)"
    r"|(?:i )?(?:could|can|did)(?: not|not|n[o']t) find"
    r"|(?:it is |this is |that is |it's )?not (?:mentioned|specified|stated|listed|given|provided|recorded|available|present|known)\b"
    r"|not in the (?:passages|records|documents|data)"
    r"|(?:the )?answer is not (?:found|known|available|given|in)"
    r"|there (?:is|are|was|were) no\b"
    r"|no (?:[\w-]+ ){0,4}(?:is|are|was|were|has been|have been) (?:listed|assigned|found|mentioned|recorded|specified|given|set|named|shown)\b"
    r"|no (?:record|records|mention|information|data|match|matches|result|results|answer)\b)", re.I)
NOTHING = re.compile(r"\W*(?:none|null|nil|nothing|nobody|no one|no-one|n/?a)\W*", re.I)
# what makes a refusal more than a refusal: a second clause or sentence, or a contrast ("not stated, but it is 2028-01-24")
MORE = re.compile(r"[;:,()\n]|[.!?]\s+\S|\b(?:but|though|although|however|except|instead|whereas)\b", re.I)


def final(answer: str, refusals: bool = True, join: bool = False) -> str:
    """The answer as stored: one "not found" for every way of saying it, the rest capped at ``ANSWER_CAP`` characters.
    ``refusals``: also a bare "none" and a refusal in other words (``REFUSAL``) when it is the whole answer, one short
    sentence and nothing more (``MORE``); off for the brain's own answer, which is stored as the brain gave it. ``join``:
    the lines made one (an "Answer:" line's answer written below it)."""
    a = (answer or "").strip().strip('"').strip()
    if re.fullmatch(r"<[^<>]{0,40}>\W*|\W*", a):  # a placeholder copied from the instructions, or nothing
        return NOT_FOUND
    if re.match(r"^\W*(?:not found|none found|no such|unknown|n/?a)\b", a, re.I):
        return NOT_FOUND
    if refusals and (NOTHING.fullmatch(a) or (len(a) <= 160 and not MORE.search(a) and REFUSAL.match(a))):
        return NOT_FOUND
    if join:
        a = " ".join(x.strip() for x in a.splitlines() if x.strip())
    return a[:ANSWER_CAP]


def _result_text(result: dict[str, Any]) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > RESULT_CHARS + 2000:  # find and values keep what fits; this only bounds anything else
        text = text[: RESULT_CHARS + 2000] + " [... the rest of the result is left out]"
    return "Tool result:\n" + text


# ------------------------------------------------------------------ the loop
Generate = Callable[[list[list[dict[str, str]]]], list[dict[str, Any]]]


def _chars(conv: list[dict[str, str]]) -> int:
    return sum(len(m["content"]) for m in conv)


def reason(questions: list[dict[str, Any]], brain_rows: dict[str, dict[str, Any]], generate: Generate, tools: Any,
           max_steps: int = MAX_STEPS, log: Callable[[str], None] = print,
           on_done: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Every question's conversation, advanced in lockstep: one batched ``generate`` per step for all that are still
    open, then their tool calls in one ``tools.run``. A conversation ends with an answer, or after ``max_steps`` tool
    calls (or ``CONV_CHARS`` characters) with one more turn that must answer. One that has no answer of its own (no
    reply it can read after two reminders, or too long for the model's window) keeps the brain's answer. ``on_done``
    gets each row as its conversation ends. Rows: {id, answer, route "reasoner", reason, steps, tokens, ms}."""
    convs: dict[str, list[dict[str, str]]] = {}
    state: dict[str, dict[str, Any]] = {}
    qs = {q["id"]: q for q in questions}
    for q in questions:
        b = brain_rows.get(q["id"])
        shown = json.dumps(brain_view(b), ensure_ascii=False) if b else "(no answer)"
        convs[q["id"]] = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": FIRST.format(question=q["question"], brain=shown)}]
        state[q["id"]] = {"brain_answer": str((b or {}).get("answer") or NOT_FOUND), "steps": [], "calls": 0, "prompt_tokens": 0,
                          "output_tokens": 0, "answer": None, "retries": 0, "gen_s": 0.0, "tool_s": 0.0, "cut": 0, "must": False}
    rows: dict[str, dict[str, Any]] = {}

    def done(i: str) -> None:
        st = state[i]
        tools_used = [s["tool"] for s in st["steps"] if "tool" in s]
        rows[i] = {"id": i, "answer": st["answer"], "route": "reasoner",
                   "reason": f"{len(tools_used)} tool call(s): {', '.join(tools_used) or 'none'}", "steps": st["steps"],
                   "prompt_tokens": st["prompt_tokens"], "output_tokens": st["output_tokens"], "cut_turns": st["cut"],
                   "ms": round((st["gen_s"] + st["tool_s"]) * 1000, 1)}
        if on_done is not None:
            on_done(rows[i])

    def give_up(i: str, finish: Any, text: str) -> None:
        st = state[i]
        st["answer"] = final(st["brain_answer"], refusals=False)  # no answer of its own: the brain's stands, as it gave it
        st["steps"].append({"gave_up": True, "finish": finish, "answer": st["answer"], "raw": visible(text)[:500]})
        done(i)

    turn = 0
    while open_ := [i for i in convs if state[i]["answer"] is None]:
        turn += 1
        t = time.perf_counter()
        outs = generate([convs[i] for i in open_])
        gen = time.perf_counter() - t
        calls: list[tuple[str, tuple[str, dict[str, Any]]]] = []
        for i, o in zip(open_, outs, strict=True):
            st = state[i]
            st["gen_s"] += gen / len(open_)
            st["prompt_tokens"] += int(o.get("prompt_tokens") or 0)
            st["output_tokens"] += int(o.get("output_tokens") or 0)
            text, finish = o.get("text") or "", o.get("finish_reason")
            st["cut"] += finish == "length"
            if finish == "too_long":  # no room left in the model's window for a reply
                give_up(i, finish, text)
                continue
            act = parse_action(text)
            last = st["calls"] >= max_steps or st["must"]
            if act is not None and "answer" in act:
                st["answer"] = final(act["answer"], join=act.get("join", False))
                st["steps"].append({"answer": st["answer"], "finish": finish, "raw": visible(text)[:RAW_CHARS]})
                done(i)
                continue
            if act is None or act.get("tool") not in TOOLS or last:
                st["retries"] += 1
                if st["retries"] > 2 or (last and st["retries"] > 1):
                    give_up(i, finish, text)
                    continue
                convs[i].append({"role": "assistant", "content": visible(text)[:2000] or "(no reply)"})
                note = LAST if last else CUT if finish == "length" and not visible(text) else AGAIN
                if act is not None and act.get("tool") not in TOOLS and not last:
                    note = f"No tool {act.get('tool')!r}: use one of {', '.join(TOOLS)}. " + AGAIN
                convs[i].append({"role": "user", "content": note})
                continue
            st["calls"] += 1
            convs[i].append({"role": "assistant", "content": json.dumps({"tool": act["tool"], "args": act["args"]}, ensure_ascii=False)})
            calls.append((i, (act["tool"], act["args"])))
        if calls:
            t = time.perf_counter()
            results = tools.run([c for _, c in calls])
            for (i, (tool, args)), (res, secs) in zip(calls, results, strict=True):
                st = state[i]
                st["tool_s"] += secs
                text = _result_text(res)
                st["steps"].append({"tool": tool, "args": args, "result_chars": len(text), "error": res.get("error"), "s": secs})
                st["must"] = st["must"] or _chars(convs[i]) + len(text) > CONV_CHARS
                convs[i].append({"role": "user", "content": text + ("\n\n" + LAST if st["calls"] >= max_steps or st["must"] else "")})
            log(f"  turn {turn}: {len(open_)} open, {len(calls)} tool calls, generation {gen:.0f} s, tools {time.perf_counter() - t:.0f} s")
        else:
            log(f"  turn {turn}: {len(open_)} open, generation {gen:.0f} s")
    return [rows[q] for q in qs]


def rag_blocks(passages: list[dict[str, str]], chars: int = RAG_CHARS) -> list[str]:
    """The passages the plain-search arm is shown: the best ones, numbered, up to ``chars`` characters."""
    parts, used = [], 0
    for n, p in enumerate(passages, 1):
        block = f"[{n}] ({p['source']}) {p['title']}\n{p['text']}"
        if used + len(block) > chars and parts:
            break
        parts.append(block)
        used += len(block)
    return parts


def rag_conversation(question: str, passages: list[dict[str, str]], chars: int = RAG_CHARS) -> list[dict[str, str]]:
    """The plain-search arm's one turn: the question and the best passages (``rag_blocks``)."""
    return [{"role": "system", "content": RAG_SYSTEM},
            {"role": "user", "content": "Passages:\n\n" + "\n\n".join(rag_blocks(passages, chars)) + f"\n\nQuestion: {question}"}]


def rag_turns(convs: list[list[dict[str, str]]], generate: Generate) -> list[dict[str, Any]]:
    """The plain-search arm's replies: one turn each, and one more for a reply with no "Answer:" line (cut off while
    thinking, empty, or another format), as the reasoner is reminded; the second reply is kept when it has one."""
    outs = generate(convs)
    again = [i for i, o in enumerate(outs) if answer_line(visible(o.get("text") or "")) is None]
    if again:
        more = generate([[*convs[i], {"role": "assistant", "content": visible(outs[i].get("text") or "")[:2000] or "(no reply)"},
                          {"role": "user", "content": RAG_CUT if outs[i].get("finish_reason") == "length" else RAG_AGAIN}]
                         for i in again])
        for i, o in zip(again, more, strict=True):
            first = outs[i]
            keep = o if answer_line(visible(o.get("text") or "")) is not None or not visible(first.get("text") or "") else first
            outs[i] = {**keep, "prompt_tokens": int(first.get("prompt_tokens") or 0) + int(o.get("prompt_tokens") or 0),
                       "output_tokens": int(first.get("output_tokens") or 0) + int(o.get("output_tokens") or 0),
                       "retried": first.get("finish_reason")}
    return outs


def rag_answer(text: str, finish: str | None = None) -> str:
    """The plain-search arm's answer: its last "Answer:" line, or its whole visible reply; a reply with nothing visible
    (cut off while thinking, or empty) is no answer, never "not found"."""
    body = visible(text)
    if not body:
        return "(no reply: cut off)" if finish == "length" else "(no reply)"
    line = answer_line(body)
    return final(body if line is None else line, join=line is not None)


# ------------------------------------------------------------------ backends
def resolve_model(name: str, token: str | None = None, log: Callable[[str], None] = print) -> tuple[str, str | None]:
    """The repository and revision for a model name (``MODELS``, or fact extraction's), or a repository id as given."""
    from cie.eval import extract_facts as X

    table = {**X.MODELS, **MODELS}
    if name not in table:
        if "/" in name:
            return name, None
        raise SystemExit(f"unknown model {name!r}: use one of {', '.join(table)} or a Hugging Face repository id")
    from huggingface_hub import hf_hub_download

    for repo, rev in table[name]:
        try:
            hf_hub_download(repo, "config.json", revision=rev, token=token)
            return repo, rev
        except Exception as e:  # noqa: BLE001 - gated without access, missing or offline: try the next
            log(f"  {repo}: not downloadable here ({type(e).__name__}); trying the next")
    raise SystemExit(f"no repository for {name} could be downloaded")


def template_kwargs(name: str, effort: str | None, thinking: bool | None) -> dict[str, Any]:
    """The chat template arguments for a model: Qwen3.8's thinking switch and effort, Llama 3.2's fixed date."""
    from cie.eval.extract_facts import CHAT_TEMPLATE_KWARGS

    kw: dict[str, Any] = dict(CHAT_TEMPLATE_KWARGS) if name.startswith("llama") else {}
    if "qwen3.8" in name.lower():
        on = THINKING["qwen3.8"] if thinking is None else thinking
        kw.update({"enable_thinking": on, "preserve_thinking": False})
        if on and effort:
            kw["reasoning_effort"] = effort
    return kw


class VLLMBackend:
    """vLLM's offline engine: one ``chat`` call per step for every open conversation."""

    def __init__(self, name: str, max_model_len: int = 32768, gpu_mem: float = 0.90, max_tokens: int = 6144,
                 max_num_seqs: int | None = None, effort: str | None = "medium", thinking: bool | None = None,
                 log: Callable[[str], None] = print):
        from vllm import LLM

        repo, rev = resolve_model(name, os.environ.get("HF_TOKEN"), log=log)
        # prefix caching is left to vLLM: Qwen3.8 mixes linear-attention layers with attention, which it may not cache
        kw: dict[str, Any] = {"model": repo, "dtype": "bfloat16", "gpu_memory_utilization": gpu_mem, "max_model_len": max_model_len,
                              "seed": 0}
        if rev:
            kw["revision"] = rev
        if max_num_seqs:
            kw["max_num_seqs"] = max_num_seqs
        if "Qwen3.8" in repo:
            kw["limit_mm_per_prompt"] = {"image": 0, "video": 0}  # text only: no memory kept for the vision encoder's inputs
        log(f"  vLLM engine: {kw}")
        t = time.time()
        self.llm = LLM(**kw)
        self.load_seconds = round(time.time() - t, 1)
        self.repo = f"{repo}@{rev}" if rev else repo
        self.name, self.max_tokens, self.max_model_len, self.log = name, max_tokens, max_model_len, log
        self.kwargs = template_kwargs(name if name in MODELS else repo, effort, thinking)
        self.tok = self.llm.get_tokenizer()
        self._count_failed = False
        try:  # whether the template opens the reply with "<think>" (Qwen3.8 does unless thinking is off)
            self.thinks = self.tok.apply_chat_template([{"role": "user", "content": "x"}], tokenize=False, add_generation_prompt=True,
                                                       **self.kwargs).rstrip().endswith("<think>")
        except Exception:  # noqa: BLE001 - the name then says it
            self.thinks = bool(self.kwargs.get("enable_thinking"))
        log(f"  the reply opens inside the thinking: {self.thinks}")

    def count(self, conv: list[dict[str, str]]) -> int:
        """The prompt's tokens, as the chat template makes it (vLLM renders it the same way); if that fails, an
        over-estimate from its characters."""
        try:
            ids = self.tok.apply_chat_template(conv, tokenize=True, add_generation_prompt=True, return_dict=False, **self.kwargs)
            return len(ids if isinstance(ids, list) else ids["input_ids"])
        except Exception as e:  # noqa: BLE001 - never stop a run over a count
            if not self._count_failed:
                self._count_failed = True
                self.log(f"  counting a prompt's tokens failed ({type(e).__name__}: {e}); estimating from characters")
            return _chars(conv) // 2

    def __call__(self, convs: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
        """One reply per conversation. A conversation whose prompt leaves less than ``MIN_ROOM`` tokens of the window is
        not sent (finish "too_long"); the others get at most the room they have, so no prompt fails the batch."""
        from vllm import SamplingParams

        # the model card's settings for thinking; greedy without it
        base = dict(temperature=1.0, top_p=0.95, top_k=20, seed=0) if self.thinks else dict(temperature=0.0, seed=0)
        outs: list[dict[str, Any] | None] = [None] * len(convs)
        send, sps = [], []
        for i, c in enumerate(convs):
            n = self.count(c)
            room = self.max_model_len - n - 16  # a few tokens of slack for the engine's own rendering
            if room < MIN_ROOM:
                outs[i] = {"text": "", "prompt_tokens": n, "output_tokens": 0, "finish_reason": "too_long"}
            else:
                send.append(i)
                sps.append(SamplingParams(max_tokens=min(self.max_tokens, room), **base))
        for i, o in zip(send, self._chat([convs[i] for i in send], sps), strict=True):
            outs[i] = o
        return outs  # type: ignore[return-value]

    def _chat(self, convs: list[list[dict[str, str]]], sps: list[Any]) -> list[dict[str, Any]]:
        if not convs:
            return []
        try:
            outs = self.llm.chat(convs, sps, use_tqdm=False, chat_template_kwargs=self.kwargs)
        except Exception as e:
            # a prompt the engine finds too long after all fails the whole batch: find it by halves, keep the rest
            if not re.search(r"maximum (?:model|context) length", str(e)):
                raise
            if len(convs) == 1:
                return [{"text": "", "prompt_tokens": 0, "output_tokens": 0, "finish_reason": "too_long"}]
            h = len(convs) // 2
            return self._chat(convs[:h], sps[:h]) + self._chat(convs[h:], sps[h:])
        res = []
        for o in outs:
            text = o.outputs[0].text
            # Qwen3.8's template ends the prompt with "<think>\n", so the reply starts inside the thinking: put the opener
            # back, so that a reply cut off while thinking reads as no reply (``visible``), never as an answer
            if self.thinks and not text.lstrip().startswith("<think>"):
                text = "<think>\n" + text
            res.append({"text": text, "prompt_tokens": len(o.prompt_token_ids or []), "output_tokens": len(o.outputs[0].token_ids),
                        "finish_reason": o.outputs[0].finish_reason})
        return res


class OpenAIBackend:
    """Any OpenAI-compatible chat endpoint (Ollama, a vLLM server, OpenAI): for runs without a local GPU and for tests."""

    def __init__(self, model: str, base_url: str, max_tokens: int = 6144, concurrency: int = 8, api_key: str | None = None,
                 extra: dict[str, Any] | None = None, effort: str | None = None, thinking: bool | None = None):
        self.model, self.base_url, self.max_tokens, self.concurrency = model, base_url.rstrip("/"), max_tokens, concurrency
        self.api_key = api_key or os.environ.get("REASONER_API_KEY") or os.environ.get("OPENAI_API_KEY") or "none"
        self.extra = dict(extra or {})
        # Qwen3.8 behind a vLLM server: its template settings, and its reply opens inside the thinking unless the server
        # splits the thinking off (Ollama does, and ignores the settings)
        kw = template_kwargs(model, effort, thinking) if "qwen3.8" in model.lower() else {}
        if kw:
            self.extra.setdefault("chat_template_kwargs", kw)
        self.thinks = bool(kw.get("enable_thinking"))
        self.repo = f"{model} at {self.base_url}"

    def _one(self, msgs: list[dict[str, str]]) -> dict[str, Any]:
        import urllib.request

        body = {"model": self.model, "messages": msgs, "max_tokens": self.max_tokens, "temperature": 0, **self.extra}
        err: Exception | None = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
                r = json.load(urllib.request.urlopen(req, timeout=1800))
                c, u = r["choices"][0], r.get("usage") or {}
                text, msg = c["message"].get("content") or "", c["message"]
                if self.thinks and not (msg.get("reasoning_content") or msg.get("reasoning")) and not text.lstrip().startswith("<think>"):
                    text = "<think>\n" + text  # as VLLMBackend: a reply cut off while thinking reads as no reply
                return {"text": text, "prompt_tokens": u.get("prompt_tokens", 0),
                        "output_tokens": u.get("completion_tokens", 0), "finish_reason": c.get("finish_reason")}
            except Exception as e:  # noqa: BLE001 - a busy server: wait and ask again
                err = e
                time.sleep(2 ** attempt)
        return {"text": "", "prompt_tokens": 0, "output_tokens": 0, "finish_reason": f"error: {type(err).__name__}: {err}"[:200]}

    def __call__(self, convs: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
        with ThreadPoolExecutor(self.concurrency) as ex:
            return list(ex.map(self._one, convs))
