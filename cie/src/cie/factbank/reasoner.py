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
MAX_STEPS = 8  # tool calls a conversation may make before it must answer
ANSWER_CAP = 1100  # characters of a final answer, as the brain's free-text quote is capped (prose.QUOTE_CAP)
RAG_PASSAGES = 12
RAG_CHARS = 9000
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
said, decided or planned, answer in at most three sentences with the exact figures, names and dates of the record."""

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
the question asks what was said, decided or planned, answer in at most three sentences with the exact figures, names and \
dates of the passages."""


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
        show = [str(s) for s in (show or [])][:6]
        rows = []
        for dsid in sorted(hits, key=lambda d: (self.docs[d][0] or "", d))[:FIND_ROWS]:
            lab = self._label(dsid)
            fs = self.fields(dsid)
            rows.append({**{k: lab[k] for k in ("doc", "title", "key") if k in lab}, **{s: ", ".join(fs.get(s, [])) or None for s in show}})
        out: dict[str, Any] = {"count": len(hits), "records": rows}
        if len(hits) > FIND_ROWS:
            out["note"] = f"{len(hits)} records match; the first {FIND_ROWS} are shown"
        return out

    def values(self, system: str, field: str) -> dict[str, Any]:
        if self._by_value is None:
            self._index()
        system = _norm(system).replace(" ", "_")
        counts = sorted(((len(ds), v) for (s, f, v), ds in self._by_value.items() if s == system and f == field), reverse=True)
        if not counts:
            fs = sorted({f for (s, f, _v) in self._by_value if s == system})
            return {"error": f"no field {field!r} in {system!r}", "fields": fs[:80]}
        return {"values": [{"value": self._shown[(system, field, v)], "records": n} for n, v in counts[:VALUES_ROWS]],
                "distinct": len(counts)}

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


def brain_view(r: dict[str, Any], chars: int = EVIDENCE_CHARS) -> dict[str, Any]:
    """What the model sees of a brain row: its answer, route, reason and evidence (cut to ``chars``)."""
    ev = str(r.get("evidence") or "")
    return {"answer": r.get("answer"), "route": r.get("route"), "reason": str(r.get("reason") or "")[:400],
            "evidence": ev[:chars] + (" [...]" if len(ev) > chars else "")}


# ------------------------------------------------------------------ tool processes
_BOX: Toolbox | None = None


def _init_worker(bank: str, single: str | None, plans: str | None, router: str | None) -> None:
    global _BOX
    brain = None
    if single and plans:
        from cie.factbank.brain import Brain, Router

        brain = Brain(bank, single, plans, Router.load(router) if router else None, v16=True, v17=True, v18=True)
    _BOX = Toolbox(bank, brain)


def _run_call(call: tuple[str, dict[str, Any]]) -> tuple[dict[str, Any], float]:
    t = time.perf_counter()
    out = _BOX.run(*call) if _BOX is not None else {"error": "no toolbox"}
    return out, round(time.perf_counter() - t, 3)


class ToolPool:
    """Tool calls run in ``workers`` processes, each with its own toolbox and brain (forked before any model is loaded)."""

    def __init__(self, bank: Path, single: Path | None = None, plans: Path | None = None, router: Path | None = None,
                 workers: int | None = None):
        import multiprocessing as mp

        self.workers = workers or max(1, min(10, (os.cpu_count() or 2) - 2))
        init = (str(bank), str(single) if single else None, str(plans) if plans else None, str(router) if router else None)
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
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            elif ch != "\\":
                esc = False
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


def parse_action(text: str) -> dict[str, Any] | None:
    """The reply's action: {"tool", "args"} or {"answer"}, from its last JSON object that names one; an "Answer:" line
    is taken as an answer when there is no such object; None when the reply has neither."""
    body = visible(text)
    for blob in reversed(_objects(body)):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "answer" in obj:
            a = obj["answer"]
            return {"answer": ", ".join(map(str, a)) if isinstance(a, list) else str(a)}
        if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {k: v for k, v in obj.items() if k != "tool"}
            return {"tool": obj["tool"].strip().lower(), "args": args}
    if (line := answer_line(body)) is not None:
        return {"answer": line}
    return None


def answer_line(body: str) -> str | None:
    """The answer of the reply's last "Answer:" line (markdown stars dropped), or the lines after it when it holds nothing
    else; None when there is no such line."""
    lines = (body or "").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        m = re.match(r"^\W*answer\s*\**\s*:\s*\**\s*(.*)$", lines[i], re.I)
        if m:
            rest = m.group(1).strip().strip("*").strip()
            return rest or " ".join(x.strip() for x in lines[i + 1:] if x.strip())
    return None


def final(answer: str) -> str:
    """The answer as stored: one "not found" for every way of saying it, the rest capped at ``ANSWER_CAP`` characters."""
    a = (answer or "").strip().strip('"').strip()
    if re.fullmatch(r"<[^<>]{0,40}>\W*|\W*", a):  # a placeholder copied from the instructions, or nothing
        return NOT_FOUND
    if re.match(r"^\W*(?:not found|none found|no such|unknown|n/?a)\b", a, re.I):
        return NOT_FOUND
    return a[:ANSWER_CAP]


def _result_text(result: dict[str, Any]) -> str:
    return "Tool result:\n" + json.dumps(result, ensure_ascii=False, default=str)


# ------------------------------------------------------------------ the loop
Generate = Callable[[list[list[dict[str, str]]]], list[dict[str, Any]]]


def reason(questions: list[dict[str, Any]], brain_rows: dict[str, dict[str, Any]], generate: Generate, tools: Any,
           max_steps: int = MAX_STEPS, log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Every question's conversation, advanced in lockstep: one batched ``generate`` per step for all that are still
    open, then their tool calls in one ``tools.run``. A conversation ends with an answer, or after ``max_steps`` tool
    calls with one more turn that must answer. Rows: {id, answer, route "reasoner", reason, steps, tokens, ms}."""
    convs: dict[str, list[dict[str, str]]] = {}
    state: dict[str, dict[str, Any]] = {}
    for q in questions:
        b = brain_rows.get(q["id"])
        shown = json.dumps(brain_view(b), ensure_ascii=False) if b else "(no answer)"
        convs[q["id"]] = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": FIRST.format(question=q["question"], brain=shown)}]
        state[q["id"]] = {"brain_answer": str((b or {}).get("answer") or NOT_FOUND), "steps": [], "calls": 0, "prompt_tokens": 0,
                          "output_tokens": 0, "answer": None, "retries": 0, "gen_s": 0.0, "tool_s": 0.0}
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
            act = parse_action(o.get("text") or "")
            last = st["calls"] >= max_steps
            if act is not None and "answer" in act:
                st["answer"] = final(act["answer"])
                st["steps"].append({"answer": st["answer"]})
                continue
            if act is None or act.get("tool") not in TOOLS or last:
                st["retries"] += 1
                if st["retries"] > 2 or (last and st["retries"] > 1):
                    st["answer"] = final(st["brain_answer"])  # no answer of its own: the brain's stands
                    st["steps"].append({"gave_up": True, "finish": o.get("finish_reason"), "answer": st["answer"]})
                    continue
                convs[i].append({"role": "assistant", "content": visible(o.get("text") or "")[:2000] or "(no reply)"})
                note = LAST if last else CUT if o.get("finish_reason") == "length" and not visible(o.get("text") or "") else AGAIN
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
                convs[i].append({"role": "user", "content": text + ("\n\n" + LAST if st["calls"] >= max_steps else "")})
            log(f"  turn {turn}: {len(open_)} open, {len(calls)} tool calls, generation {gen:.0f} s, tools {time.perf_counter() - t:.0f} s")
        else:
            log(f"  turn {turn}: {len(open_)} open, generation {gen:.0f} s")
    rows = []
    for q in questions:
        st = state[q["id"]]
        tools_used = [s["tool"] for s in st["steps"] if "tool" in s]
        rows.append({"id": q["id"], "answer": st["answer"], "route": "reasoner",
                     "reason": f"{len(tools_used)} tool call(s): {', '.join(tools_used) or 'none'}", "steps": st["steps"],
                     "prompt_tokens": st["prompt_tokens"], "output_tokens": st["output_tokens"],
                     "ms": round((st["gen_s"] + st["tool_s"]) * 1000, 1)})
    return rows


def rag_conversation(question: str, passages: list[dict[str, str]], chars: int = RAG_CHARS) -> list[dict[str, str]]:
    """The plain-search arm's one turn: the question and the best passages, numbered, up to ``chars`` characters."""
    parts, used = [], 0
    for n, p in enumerate(passages, 1):
        block = f"[{n}] ({p['source']}) {p['title']}\n{p['text']}"
        if used + len(block) > chars and parts:
            break
        parts.append(block)
        used += len(block)
    return [{"role": "system", "content": RAG_SYSTEM},
            {"role": "user", "content": "Passages:\n\n" + "\n\n".join(parts) + f"\n\nQuestion: {question}"}]


def rag_answer(text: str) -> str:
    """The plain-search arm's answer: its last "Answer:" line, or its whole visible reply."""
    body = visible(text)
    line = answer_line(body)
    return final(body if line is None else line)


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
    if name.startswith("qwen3.8") or "Qwen3.8" in name:
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
        self.name, self.max_tokens = name, max_tokens
        self.kwargs = template_kwargs(name if name in MODELS else repo, effort, thinking)
        self.thinks = bool(self.kwargs.get("enable_thinking"))

    def __call__(self, convs: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
        from vllm import SamplingParams

        if self.thinks:  # the model card's settings for thinking
            sp = SamplingParams(temperature=1.0, top_p=0.95, top_k=20, max_tokens=self.max_tokens, seed=0)
        else:
            sp = SamplingParams(temperature=0.0, max_tokens=self.max_tokens, seed=0)
        outs = self.llm.chat(convs, sp, use_tqdm=False, chat_template_kwargs=self.kwargs)
        return [{"text": o.outputs[0].text, "prompt_tokens": len(o.prompt_token_ids or []), "output_tokens": len(o.outputs[0].token_ids),
                 "finish_reason": o.outputs[0].finish_reason} for o in outs]


class OpenAIBackend:
    """Any OpenAI-compatible chat endpoint (Ollama, a vLLM server, OpenAI): for runs without a local GPU and for tests."""

    def __init__(self, model: str, base_url: str, max_tokens: int = 6144, concurrency: int = 8, api_key: str | None = None,
                 extra: dict[str, Any] | None = None):
        self.model, self.base_url, self.max_tokens, self.concurrency = model, base_url.rstrip("/"), max_tokens, concurrency
        self.api_key = api_key or os.environ.get("REASONER_API_KEY") or os.environ.get("OPENAI_API_KEY") or "none"
        self.extra = extra or {}
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
                return {"text": c["message"].get("content") or "", "prompt_tokens": u.get("prompt_tokens", 0),
                        "output_tokens": u.get("completion_tokens", 0), "finish_reason": c.get("finish_reason")}
            except Exception as e:  # noqa: BLE001 - a busy server: wait and ask again
                err = e
                time.sleep(2 ** attempt)
        return {"text": "", "prompt_tokens": 0, "output_tokens": 0, "finish_reason": f"error: {type(err).__name__}: {err}"[:200]}

    def __call__(self, convs: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
        with ThreadPoolExecutor(self.concurrency) as ex:
            return list(ex.map(self._one, convs))


# ------------------------------------------------------------------ arms over a work folder
def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def ask_reasoner(work: Path, generate: Generate, tools: Any, brain_file: str = "factbank_v18", name: str = "reasoner",
                 limit: int | None = None, max_steps: int = MAX_STEPS, log: Callable[[str], None] = print) -> dict[str, Any]:
    """The reasoning engine's answers to ``work``/questions.jsonl, starting from the brain's answers in
    ``work``/<brain_file>.jsonl, written to ``work``/<name>.jsonl."""
    qs = _jsonl(work / "questions.jsonl")[: limit or None]
    brain_rows = {r["id"]: r for r in _jsonl(work / f"{brain_file}.jsonl")}
    if missing := [q["id"] for q in qs if q["id"] not in brain_rows]:
        raise SystemExit(f"{len(missing)} questions have no brain answer in {brain_file}.jsonl: ask the v18 arm first")
    t = time.time()
    rows = reason(qs, brain_rows, generate, tools, max_steps=max_steps, log=log)
    (work / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return {"questions": len(rows), "written": f"{name}.jsonl", "seconds": round(time.time() - t, 1),
            "tool_calls": sum(sum(1 for s in r["steps"] if "tool" in s) for r in rows),
            "not_found": sum(r["answer"] == NOT_FOUND for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows), "prompt_tokens": sum(r["prompt_tokens"] for r in rows)}


def ask_rag(work: Path, generate: Generate, name: str = "rag", limit: int | None = None, k: int = 60,
            log: Callable[[str], None] = print) -> dict[str, Any]:
    """The plain-search arm: each question with the best passages of a keyword search over the haystack's documents
    (``brain_test.Passages``, as the quotes arm searches), answered in one turn; written to ``work``/<name>.jsonl."""
    from cie.eval.brain_test import Passages

    qs = _jsonl(work / "questions.jsonl")[: limit or None]
    t = time.time()
    ps = Passages(work)
    log(f"  passages: {len(ps.rows):,} of {ps.documents:,} documents in {ps.seconds:.0f} s")
    hits = {q["id"]: ps.search(q["question"], k)[:RAG_PASSAGES] for q in qs}
    t2 = time.time()
    outs = generate([rag_conversation(q["question"], hits[q["id"]]) for q in qs])
    gen = time.time() - t2
    rows = [{"id": q["id"], "answer": rag_answer(o.get("text") or ""), "route": "rag", "reason": f"{len(hits[q['id']])} passages",
             "docs": list(dict.fromkeys(h["dsid"] for h in hits[q["id"]])), "prompt_tokens": o.get("prompt_tokens", 0),
             "output_tokens": o.get("output_tokens", 0), "finish": o.get("finish_reason"), "ms": round(gen / max(1, len(qs)) * 1000, 1)}
            for q, o in zip(qs, outs, strict=True)]
    (work / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return {"questions": len(rows), "written": f"{name}.jsonl", "seconds": round(time.time() - t, 1), "generation_seconds": round(gen, 1),
            "not_found": sum(r["answer"] == NOT_FOUND for r in rows), "output_tokens": sum(r["output_tokens"] for r in rows)}
