"""A large language model as the company brain's reasoning engine (docs/FACTBANK_50K_PLAN.md, docs/FACTBANK_FIXES.md).

The brain (``cie.factbank.brain``) answers by exact lookups and plans of at most two steps, and quotes sentences for free
text. The reasoning engine is a language model that works on top of it, through tools that read the same fact bank
(``cie.factbank.tools``): brain, search, read, find, values and schema.

The model is told the brain's answer to the question first and decides: keep it, check it, or work the question out in
steps (``MAX_STEPS`` tool calls at most). It replies with one JSON object a turn ({"tool", "args"} or {"answer"}); its
thinking, when the model thinks, is dropped from the conversation. Every conversation advances in lockstep: one batched
generation per step for all of them (vLLM's offline engine, or any OpenAI-compatible endpoint), then every tool call of
that step run in parallel processes (``ToolPool``).

What the first test showed and what changed (docs/FACTBANK_FIXES.md):

- **The model worked half-blind:** it never saw a real field name. Its instructions now list every system's main fields
  with their kinds, read from the bank (``Toolbox.schema_brief``), and the tools read names as people write them.
- **Every loss came from changing the brain's answer, and nothing checked a change.** A final answer now passes guards
  (``GUARDS``), each of which may send the conversation back once: "not found" over a brain answer needs a tool call
  that worked; an answer where the brain found nothing is checked against what the question names; a figure, date or
  key in the answer must be in something a tool returned; a record the question names outright must have been seen.
- **Free text:** the answer is a short direct line plus ``quotes``, sentences copied word for word from a record. The
  quotes are checked against what the model was shown and kept apart from the answer (``support``), so shortening an
  answer loses nothing.
- **Where the brain is reliable the model is not asked** (``SKIP_ROUTES``): exact lookups in a record the question
  names, counts, and names the company does not have.

The arms (``ARMS``) differ only in what the model may use, so that each part's share can be measured:
"reasoner" (the brain's answer and every tool), "nobrain" (every tool but the brain, and no first answer), "agent"
(search and read only: a model that searches by itself, with no fact bank structure), "notools" (the brain's answer and
evidence, no tool) and the plain-search arm "rag" (the passages a keyword search finds, one turn).
A conversation that ends with no answer of its own (no reply it can read after two reminders) keeps the brain's answer.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cie.factbank import store
from cie.factbank.tools import (  # noqa: F401 - re-exported: the tools were defined here first
    FIELD_CHARS,
    FIND_ROWS,
    READ_CHARS,
    RESULT_CHARS,
    SEARCH_K,
    TOOLS,
    VALUES_ROWS,
    Toolbox,
    brain_view,
)

CONV_CHARS = 60000  # a conversation this long must answer at its next turn (as after MAX_STEPS tool calls)
MAX_STEPS = 8  # tool calls a conversation may make before it must answer
ANSWER_CAP = 1100  # characters of a final answer, as the brain's free-text quote is capped (prose.QUOTE_CAP)
SUPPORT_CAP = 1100  # characters of the quotes kept with an answer
RAW_CHARS = 1500  # characters of the model's visible reply kept with each answer, to read it again without the GPU
STEP_RESULT_CHARS = 1200  # characters of each tool result kept in the answer's row
RAG_PASSAGES = 12
RAG_CHARS = 14000  # room for all 12 passages (about 1,000 characters each)
MIN_ROOM = 2048  # tokens of the model's window a turn needs at least; a conversation with less left ends (the brain's answer)
NOT_FOUND = "not found"
MAX_PUSHBACKS = 2  # times a conversation's final answer may be sent back by a guard
# the brain's routes whose answer stands without the model: a field or a history line of a record the question names
# ("derived"), a count or a list by exact filters ("table"), a named key, title or person the company does not have
# ("not_found") and a field the named record does not have ("absent"). On the 635 questions of the 50,000-document test
# the model changed 5 of these 213 answers: 2 for the better, 3 for the worse, at 18% of its prompt tokens.
SKIP_ROUTES = frozenset(("derived", "table", "not_found", "absent"))
# A guard that showed a count differing from the brain's beside it was tried on the stored answers of the first test and
# dropped: it would have spoken 32 times, each time on a right answer.
GUARDS = frozenset(("absence", "similar", "named", "grounded", "quotes"))

# (repository, pinned revision) for each model name; the 8B models are fact extraction's (``cie.eval.extract_facts``)
MODELS: dict[str, list[tuple[str, str | None]]] = {
    # Qwen3.8-27B (August 2026, Apache-2.0): 27B dense, thinking on by default; bf16 (55 GB) for an 80 GB GPU, Qwen's own
    # FP8 copy (28 GB, weight-only through vLLM's Marlin kernels on an A100) for a 40 GB one. Revisions checked 2026-10-17.
    "qwen3.8-27b": [("Qwen/Qwen3.8-27B", "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0")],
    "qwen3.8-27b-fp8": [("Qwen/Qwen3.8-27B-FP8", "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a")],
}
# chat template arguments by model family: Qwen3.8 thinks by default; its effort is set by the template
THINKING = {"qwen3.8": True}


@dataclass(frozen=True)
class Arm:
    """What a model arm may use: the tools it may call, whether it is shown the brain's first answer, whether its
    instructions list the bank's systems and fields, its tool calls at most, the guards its final answer passes, and
    the brain routes whose answer stands without asking the model."""

    name: str
    tools: tuple[str, ...]
    brain_first: bool
    schema: bool = True
    max_steps: int = MAX_STEPS
    guards: frozenset[str] = frozenset()
    skip_routes: frozenset[str] = frozenset()


ARMS: dict[str, Arm] = {
    "reasoner": Arm("reasoner", TOOLS, True, guards=GUARDS, skip_routes=SKIP_ROUTES),
    # every tool but the brain, and no first answer: what the model and the bank's exact tools do without the rules
    "nobrain": Arm("nobrain", tuple(t for t in TOOLS if t != "brain"), False, guards=GUARDS - {"absence", "similar"}),
    # search and read only: a model that searches by itself (agentic search), with nothing of the fact bank's structure
    "agent": Arm("agent", ("search", "read"), False, schema=False, guards=frozenset(("named", "grounded", "quotes"))),
    # the brain's answer and evidence, and no tool: what the model adds by reading alone
    "notools": Arm("notools", (), True, schema=False, max_steps=0, guards=frozenset(("quotes",))),
}

# ------------------------------------------------------------------ instructions
INTRO = ("You answer questions about one company from its internal records. You see the records only through tools that read "
         "the company's fact bank, which holds every record and every field of it exactly.")
INTRO_NOTOOLS = ("You answer questions about one company from its internal records. A rule-based system, the company brain, has "
                 "looked the question up in the records: you are shown its answer and its evidence.")
SCHEMA_HEAD = ("The records, by system, with the fields that most of a system's records have (a field's kind in brackets when it "
               "is not a plain value):")
REPLY = ('Each turn, reply with exactly one JSON object and nothing else: a tool call such as\n  {call}\n'
         'or, when you are done, your final answer such as\n  {{"answer": "DEMO-7"}}')
REPLY_NOTOOLS = 'Reply with exactly one JSON object and nothing else: your final answer, such as\n  {"answer": "DEMO-7"}'
TOOL_TEXT = {
    "brain": ('brain {"question": "..."}: the company brain answers one question by exact lookups in the records, and says how (its '
              'route, the records it read and its evidence). It is reliable for one field of a record the question names, counts with '
              "plain filters, and links of two steps. For a longer chain, ask it one step at a time."),
    "search": ('search {"query": "...", "system": "..."}: the records whose text best matches the words (keyword search), up to 8, each '
               'with its id ("doc"), system, title and date. A record the query names outright (its key, its number, its exact title) '
               'comes first. "all_words" says whether a result holds every word: one that does not may be about something else. '
               '"system" is optional.'),
    "read": ('read {"doc": "...", "query": "..."}: one record, by its id, its ticket key, its pull request number or its exact title: '
             'its fields under their real names, and its text. "query" is optional and picks the passages of a long record.'),
    "find": ('find {"system": "...", "where": {"<field>": <condition>}, "show": ["<field>"], "sort": "<field>", "limit": 5, "group_by": '
             '"<field>"}: every record of the system that meets every condition: how many ("count"), and up to 40 of them with the '
             'fields in "show". A condition is a value (case, spacing and punctuation do not matter; a person by full name), a list '
             'of values (any of them), or an object: {"not": value}, {"contains": "text"}, {"before": "2026-04-01"}, {"after": ...}, '
             '{"between": ["2026-01-01", "2026-03-31"]}, {"gt": 5}, {"gte": ...}, {"lt": ...}, {"lte": ...}, {"exists": false}. '
             '"sort" orders the records by a field ("-<field>" for the latest or largest first); "group_by" counts them by a field\'s '
             'values. Only "system" is required. Use find to count, list, rank and compare.'),
    "values": ('values {"system": "...", "field": "...", "like": "..."}: the values a field takes in a system, with how many records '
               'hold each; "like" keeps the values that contain a text. Use it to learn how a value is written.'),
    "schema": ('schema {"system": "..."}: every field of a system with the kind of value it holds; without "system", the systems.'),
}
RULE_TOOLS = "Answer only from what the tools return, never from what you assume."
RULE_NOTOOLS = "Answer only from the brain's answer and evidence, never from what you assume."
RULE_ERRORS = ("A tool says so when a field, a system or a value does not exist, and names the closest ones: correct the call. A "
               "call that failed shows nothing about the records.")
RULE_NOT_FOUND = ('If the records do not hold the answer, answer "not found". If the question names a record, person or thing the '
                  'company does not have, answer "not found": never answer from a similar one.')
RULE_FIND = "Count, list, rank and compare with find, never by hand from search results."
RULE_FORMAT = ("Write the final answer the way a colleague would want it: a name, a number, a date (YYYY-MM-DD), an id or a list "
               "(separated by commas) when the question asks for one; a count starts with the number.")
RULE_QUOTES = ('When the question asks what was said, decided or planned, give a short direct answer and add "quotes": the one to '
               'three sentences of the record that say it, copied word for word, such as\n'
               '  {"answer": "The office closes at 6 pm on Fridays.", "quotes": ["From March the office closes at 6 pm on Fridays."]}\n'
               "Figures, names and dates stay as the record writes them.")
EXAMPLE_SEARCH = '{"tool": "search", "args": {"query": "office closing hours"}}'


def system_prompt(arm: Arm, schema: str = "", example: str = "") -> str:
    """An arm's instructions: what it sees, the bank's systems and fields (``schema``, from ``Toolbox.schema_brief``),
    the reply format with one tool call as an example (``example``, from ``Toolbox.example_call``), its tools and the
    rules."""
    if not arm.tools:
        return "\n\n".join([INTRO_NOTOOLS, REPLY_NOTOOLS, "Rules:\n" + "\n".join(f"- {r}" for r in (RULE_NOTOOLS, RULE_NOT_FOUND, RULE_FORMAT,
                                                                                                    RULE_QUOTES))])
    parts = [INTRO]
    if arm.schema and schema:
        parts.append(SCHEMA_HEAD + "\n" + schema)
    call = example if example and "find" in arm.tools else EXAMPLE_SEARCH
    parts.append(REPLY.format(call=call))
    parts.append("Tools:\n" + "\n".join(f"- {TOOL_TEXT[t]}" for t in arm.tools))
    rules = [RULE_TOOLS, RULE_ERRORS, RULE_NOT_FOUND, *([RULE_FIND] if "find" in arm.tools else []), RULE_FORMAT, RULE_QUOTES]
    parts.append("Rules:\n" + "\n".join(f"- {r}" for r in rules))
    return "\n\n".join(parts)


FIRST_BRAIN = """Question: {question}

The company brain's first answer:
{brain}

Decide whether this answers the question. If it does, reply {{"answer": ...}} with it. If it does not, or you are not \
sure, use the tools."""
FIRST_NOTOOLS = """Question: {question}

The company brain's answer:
{brain}

Reply with your final answer: the brain's answer if it answers the question, what its evidence shows if it does not, or \
"not found"."""
FIRST_PLAIN = "Question: {question}"

LAST = ('You have used every tool call. Reply now with {{"answer": ...}}: your best answer from what the tools returned{keep}, '
        'or "not found" if the records do not hold it.')
LAST_KEEP = ', the brain\'s answer ({brain}) if the tools did not settle it'
AGAIN = 'Reply with exactly one JSON object: a tool call {"tool": ..., "args": {...}} or your final answer {"answer": ...}.'
AGAIN_NOTOOLS = 'Reply with exactly one JSON object: your final answer {"answer": ...}.'
CUT = 'Your reply was cut off. Think less and reply with exactly one JSON object now.'

# what a guard says when it sends a final answer back (``check``); each ends by asking for the final answer again
PUSH = {
    "absence": ('The brain answered {brain} ({reason}). You answer "not found", but no tool call of yours has worked yet, so nothing '
                "shows that the records lack it. Check with a tool: read the record the brain used, or search for what the question "
                "names. Then reply with your final answer."),
    "similar": ('The brain found nothing for this question ({reason}). You answer {answer}. Check that the record you answer from is '
                "the one the question names (the same title, key or name, not a similar one) and that it has what the question asks "
                'for. If it is, repeat your answer; if it is not, answer "not found".'),
    "named": ("The question names {names}, which is in nothing the tools returned. Look it up (read it, or search for it). If the "
              'company has no such record, the answer is "not found". Then reply with your final answer.'),
    "grounded": ("These parts of your answer are in nothing the tools returned: {parts}. If you worked them out yourself, check them "
                 "with a tool (find counts, sorts and compares); if a record writes them another way, keep them. Then reply with "
                 "your final answer."),
    "quotes": ("These quotes are not word for word in any record you were shown: {parts}. Copy the sentences exactly as the record "
               'writes them (read the record again if you need to), or leave "quotes" out. Then reply with your final answer.'),
}

RAG_SYSTEM = """You answer questions about one company from passages of its internal records (Linear, Jira, GitHub, \
HubSpot, Gmail, Slack, Google Drive, Confluence, Fireflies meeting notes), found by a keyword search.

Rules:
- Answer only from the passages. If they do not hold the answer, or the question names a record, person or thing that is \
not in them, the answer is "not found": never answer from a similar one.
- End with one line that starts with "Answer:" and gives your final answer, such as "Answer: 3" or "Answer: not found". \
Write the answer the way a colleague would want it: a name, a number, a date \
(YYYY-MM-DD), an id or a list (separated by commas) when the question asks for one; a count starts with the number.
- When the question asks what was said, decided or planned, give a short direct answer on the "Answer:" line and, before \
it, the one to three sentences of the passages that say it, copied word for word, each on its own line that starts with \
"Quote:". Figures, names and dates stay as the passages write them."""
RAG_CUT = 'Your reply was cut off. Think less, and end with one line that starts with "Answer:".'
RAG_AGAIN = 'End your reply with one line that starts with "Answer:" and gives your final answer.'


# ------------------------------------------------------------------ tool processes
_BOX: Toolbox | None = None
_BOX_ERROR: str | None = None


def _make_box(bank: str, single: str | None, plans: str | None, router: str | None, v19: bool = False) -> Toolbox:
    brain = None
    if single and plans:
        from cie.factbank.brain import Brain, Router, general_words

        brain = Brain(bank, single, plans, Router.load(router) if router else None, v16=True, v17=True, v18=True, v19=v19)
        general_words()  # read once here: processes forked after this share it
    return Toolbox(bank, brain)


def _init_worker(bank: str, single: str | None, plans: str | None, router: str | None, v19: bool = False) -> None:
    """A worker's toolbox; one that fails to load is kept as its error, which ``ToolPool`` raises (never answered as a tool
    result: the model would go on without the brain)."""
    global _BOX, _BOX_ERROR
    try:
        _BOX = _make_box(bank, single, plans, router, v19)
    except Exception as e:  # noqa: BLE001 - raised by ToolPool
        _BOX_ERROR = f"{type(e).__name__}: {e}"


def _run_call(call: tuple[str, dict[str, Any]]) -> tuple[dict[str, Any], float]:
    if _BOX is None:
        raise RuntimeError(f"the toolbox did not load in a worker: {_BOX_ERROR}")
    t = time.perf_counter()
    out = _BOX.run(*call)
    return out, round(time.perf_counter() - t, 3)


class ToolPool:
    """Tool calls run in ``workers`` processes, each with its own toolbox and brain (forked before any model is loaded).
    The bank's derived tables are added first when it lacks them (``store.ensure``)."""

    def __init__(self, bank: Path, single: Path | None = None, plans: Path | None = None, router: Path | None = None,
                 workers: int | None = None, v19: bool = False):
        import multiprocessing as mp

        self.workers = workers or max(1, min(10, (os.cpu_count() or 2) - 2))
        store.ensure(bank)
        init = (str(bank), str(single) if single else None, str(plans) if plans else None, str(router) if router else None, v19)
        self.box = _make_box(*init)  # a broken setup (a lessons file, a glossary) stops here, before any process starts
        self.pool = ProcessPoolExecutor(self.workers, mp_context=mp.get_context("fork"), initializer=_init_worker, initargs=init)
        list(self.pool.map(_run_call, [("schema", {})] * self.workers))  # load them all now

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


def _quotes(obj: dict[str, Any]) -> dict[str, Any]:
    """An answer object's quotes (under "quotes", "quote" or "evidence"; one text or a list), as {"quotes": [...]}."""
    q = next((obj[k] for k in ("quotes", "quote", "evidence") if obj.get(k)), None)
    q = [q] if isinstance(q, str) else q if isinstance(q, list) else []
    q = [str(x) for x in q if isinstance(x, str | int | float) and str(x).strip()]
    return {"quotes": q[:6]} if q else {}


ANSWER_TOOLS = ("answer", "final_answer", "final")  # an answer written as a call: {"name": "answer", "arguments": {"answer": ...}}


def parse_action(text: str) -> dict[str, Any] | None:
    """The reply's action: {"tool", "args"} or {"answer"} (with its "quotes" when it gives some), from its last JSON object
    that names one (raw line breaks in its strings allowed); then Qwen's own <function=...> tool call; then an "Answer:"
    line; None when the reply has none."""
    body = visible(text)
    for blob in reversed(_objects(body)):
        try:
            obj = json.loads(blob, strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "answer" in obj:
            return {**_answer(obj["answer"]), **_quotes(obj)}
        if isinstance(obj, dict) and (call := _tool_call(obj)) is not None:
            if call["tool"] in ANSWER_TOOLS and "answer" in call["args"]:
                return {**_answer(call["args"]["answer"]), **_quotes(call["args"])}
            return call
    if calls := FUNCTION.findall(body):
        name, inner = calls[-1]
        args: dict[str, Any] = {}
        for k, v in PARAMETER.findall(inner):
            try:
                args[k] = json.loads(v, strict=False)
            except json.JSONDecodeError:
                args[k] = v.strip()
        name = name.strip().lower()
        return {**_answer(args["answer"]), **_quotes(args)} if name in ANSWER_TOOLS and "answer" in args else {"tool": name, "args": args}
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


# ------------------------------------------------------------------ guards
TICKET_KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,7}\b")
PR_NAMED = re.compile(r"(?:(?<![\w&#])#|\b(?:PR|pull request)\s*[#-]?\s*)(\d{2,7})\b", re.I)
QUOTED_NAME = re.compile(r'"([^"\n]{3,120})"|“([^”\n]{3,120})”')
FIGURE = re.compile(r"[A-Za-z]*\d[\w.,:/#-]*")
UNSEEN_KEYS = ("error", "note", "why_none")  # what a tool says about a call, not what a record holds


def strings(x: Any, skip: tuple[str, ...] = UNSEEN_KEYS) -> list[str]:
    """Every text and number inside a tool result or a brain row, apart from the tool's own messages."""
    out: list[str] = []
    if isinstance(x, str):
        out.append(x)
    elif isinstance(x, bool) or x is None:
        pass
    elif isinstance(x, int | float):
        out.append(str(x))
    elif isinstance(x, dict):
        for k, v in x.items():
            if k not in skip:
                out += strings(v, skip)
    elif isinstance(x, list | tuple):
        for v in x:
            out += strings(v, skip)
    return out


def flat(s: str) -> str:
    """A text as the guards compare it: lower case, curly quotes straight, no comma inside a number, spaces as one."""
    s = (s or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", re.sub(r"(?<=\d),(?=\d{3})", "", s))


def named_things(question: str) -> list[str]:
    """What a question names outright: ticket keys, pull request numbers and quoted titles."""
    out = TICKET_KEY.findall(question) + ["#" + n for n in PR_NAMED.findall(question)]
    out += [a or b for a, b in QUOTED_NAME.findall(question)]
    return list(dict.fromkeys(x.strip() for x in out if x.strip()))


def seen_name(name: str, seen_flat: str, seen_loose: str) -> bool:
    if name.startswith("#"):
        return re.search(r"(?<!\d)" + re.escape(name[1:]) + r"(?!\d)", seen_flat) is not None
    return store.loose(name) in seen_loose


def unseen_figures(answer: str, seen_flat: str) -> list[str]:
    """The figures, dates and keys of an answer (its words that hold a digit) that are in nothing the model was shown."""
    out = []
    for tok in FIGURE.findall(answer):
        t = flat(tok).strip(".,:;/-#")
        if t and not re.search(r"(?<![0-9a-z])" + re.escape(t) + r"(?![0-9a-z])", seen_flat):
            out.append(tok.strip(".,:;"))
    return list(dict.fromkeys(out))


def quote_key(s: str) -> str:
    return flat(s).strip(" \"'.…")


def verify_quotes(quotes: list[str], seen_flat: str) -> tuple[list[str], list[str]]:
    """(the quotes that are word for word in what the model was shown, the others)."""
    kept, dropped = [], []
    for q in quotes:
        k = quote_key(q)
        (kept if len(k) >= 8 and k in seen_flat else dropped).append(q.strip())
    return kept, dropped


def check(arm: Arm, st: dict[str, Any], question: str, answer: str, dropped: list[str], kept: list[str]) -> tuple[str, str] | None:
    """The guard that sends a final answer back, and what it says; None when the answer stands. Each guard speaks once a
    conversation, ``MAX_PUSHBACKS`` in all, and none once the tool calls are used up (the answer could not be checked)."""
    if st["pushed"] >= MAX_PUSHBACKS or (arm.tools and (st["calls"] >= arm.max_steps or st["must"])):
        return None
    brain = st["brain_answer"]
    if arm.brain_first and flat(answer) == flat(brain):
        return None

    def on(name: str) -> bool:
        return name in arm.guards and name not in st["guards"]

    cut = lambda x, n=80: x if len(x) <= n else x[:n] + "..."  # noqa: E731
    is_nf, brain_nf = answer == NOT_FOUND, final(brain, refusals=False) == NOT_FOUND
    why = st["brain_reason"] or "no reason given"
    if on("quotes") and dropped and not kept:
        return "quotes", PUSH["quotes"].format(parts="; ".join(json.dumps(cut(d), ensure_ascii=False) for d in dropped[:2]))
    if arm.brain_first and on("absence") and is_nf and not brain_nf and not st["worked"]:
        return "absence", PUSH["absence"].format(brain=json.dumps(cut(brain, 200), ensure_ascii=False), reason=cut(why, 300))
    if arm.brain_first and on("similar") and brain_nf and not is_nf:
        return "similar", PUSH["similar"].format(answer=json.dumps(cut(answer, 200), ensure_ascii=False), reason=cut(why, 300))
    if is_nf or not arm.tools:
        return None
    tool_flat = flat("\n".join(st["seen"]))
    brain_flat = "" if brain_nf else flat("\n".join(st["seen_brain"]))
    if on("named"):
        both, both_loose = tool_flat + "\n" + brain_flat, store.loose(tool_flat + brain_flat)
        missing = [n for n in named_things(question) if not seen_name(n, both, both_loose)]
        if missing:
            return "named", PUSH["named"].format(names=", ".join(json.dumps(cut(n), ensure_ascii=False) for n in missing[:3]))
    if on("grounded") and len(answer) <= 200:
        parts = unseen_figures(answer, tool_flat + "\n" + flat("\n".join(st["seen_brain"])) + "\n" + flat(question))
        if parts:
            return "grounded", PUSH["grounded"].format(parts=", ".join(json.dumps(p, ensure_ascii=False) for p in parts[:4]))
    return None


# ------------------------------------------------------------------ the loop
Generate = Callable[[list[list[dict[str, str]]]], list[dict[str, Any]]]


def _chars(conv: list[dict[str, str]]) -> int:
    return sum(len(m["content"]) for m in conv)


def _result_text(result: dict[str, Any]) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > RESULT_CHARS + 2000:  # find and values keep what fits; this only bounds anything else
        text = text[: RESULT_CHARS + 2000] + " [... the rest of the result is left out]"
    return "Tool result:\n" + text


def reason(questions: list[dict[str, Any]], brain_rows: dict[str, dict[str, Any]], generate: Generate, tools: Any,
           max_steps: int | None = None, log: Callable[[str], None] = print,
           on_done: Callable[[dict[str, Any]], None] | None = None, arm: str | Arm = "reasoner") -> list[dict[str, Any]]:
    """Every question's conversation, advanced in lockstep: one batched ``generate`` per step for all that are still
    open, then their tool calls in one ``tools.run``. ``arm`` says what the model may use (``ARMS``).

    - A question whose brain answer came by a route in the arm's ``skip_routes`` is not asked of the model: the brain's
      answer stands.
    - A conversation ends with an answer that passes the arm's guards (``check``), or after ``max_steps`` tool calls (or
      ``CONV_CHARS`` characters) with one more turn that must answer.
    - One that has no answer of its own (no reply it can read after two reminders, or too long for the model's window)
      keeps the brain's answer when the arm sees it, else "not found".
    ``on_done`` gets each row as its conversation ends. Rows: {id, answer, support, route (the arm's name), reason, steps,
    tokens, turns, ms}; ``support`` holds the quotes that go with a free-text answer (checked word for word against
    what the model was shown), or the brain's quote when the model kept the brain's document and quoted nothing."""
    arm = ARMS[arm] if isinstance(arm, str) else arm
    if max_steps is not None:
        arm = Arm(arm.name, arm.tools, arm.brain_first, arm.schema, max_steps, arm.guards, arm.skip_routes)
    box = getattr(tools, "box", None)
    system = system_prompt(arm, box.schema_brief() if box is not None and arm.schema else "",
                           box.example_call() if box is not None else "")
    first = FIRST_NOTOOLS if not arm.tools else FIRST_BRAIN if arm.brain_first else FIRST_PLAIN
    convs: dict[str, list[dict[str, str]]] = {}
    state: dict[str, dict[str, Any]] = {}
    qs = {q["id"]: q for q in questions}
    rows: dict[str, dict[str, Any]] = {}

    def done(i: str) -> None:
        st = state[i]
        tools_used = [s["tool"] for s in st["steps"] if "tool" in s]
        rows[i] = {"id": i, "answer": st["answer"], "route": arm.name,
                   "reason": st.get("why") or f"{len(tools_used)} tool call(s): {', '.join(tools_used) or 'none'}", "steps": st["steps"],
                   "prompt_tokens": st["prompt_tokens"], "output_tokens": st["output_tokens"], "cut_turns": st["cut"],
                   "turns": st["turns"], "ms": round((st["gen_s"] + st["tool_s"]) * 1000, 1)}
        if st.get("support"):
            rows[i]["support"], rows[i]["support_from"] = st["support"][:SUPPORT_CAP], st["support_from"]
        if on_done is not None:
            on_done(rows[i])

    for q in questions:
        b = brain_rows.get(q["id"]) if arm.brain_first else None
        answer = str((b or {}).get("answer") or NOT_FOUND)
        state[q["id"]] = {"brain_answer": answer, "brain_route": (b or {}).get("route"), "brain_reason": str((b or {}).get("reason") or "")[:400],
                          "steps": [], "calls": 0, "prompt_tokens": 0, "output_tokens": 0, "answer": None, "retries": 0, "gen_s": 0.0,
                          "tool_s": 0.0, "cut": 0, "must": False, "turns": 0, "pushed": 0, "guards": set(), "worked": False, "seen": [],
                          "seen_brain": strings({k: (b or {}).get(k) for k in ("answer", "evidence")}) if b else []}
        if b is not None and b.get("route") in arm.skip_routes:
            st = state[q["id"]]
            st["answer"] = final(answer, refusals=False)
            st["why"] = f"the brain's answer stands (route {b.get('route')}): the model is not asked"
            st["steps"].append({"kept": b.get("route"), "answer": st["answer"]})
            done(q["id"])
            continue
        shown = json.dumps(brain_view(b), ensure_ascii=False) if b else "(no answer)"
        convs[q["id"]] = [{"role": "system", "content": system},
                          {"role": "user", "content": first.format(question=q["question"], brain=shown)}]

    def give_up(i: str, finish: Any, text: str) -> None:
        st = state[i]
        st["answer"] = final(st["brain_answer"], refusals=False)  # no answer of its own: the brain's stands, as it gave it
        st["steps"].append({"gave_up": True, "finish": finish, "answer": st["answer"], "raw": visible(text)[:500]})
        done(i)

    def last_note(st: dict[str, Any]) -> str:
        keep = ""
        if arm.brain_first and final(st["brain_answer"], refusals=False) != NOT_FOUND:
            keep = LAST_KEEP.format(brain=json.dumps(st["brain_answer"][:200], ensure_ascii=False))
        return LAST.format(keep=keep)

    def settle(i: str, act: dict[str, Any], finish: Any, text: str) -> bool:
        """A final answer: stored, or sent back by a guard (True when the conversation is over)."""
        st = state[i]
        answer = final(act["answer"], join=act.get("join", False))
        seen_all = flat("\n".join(st["seen"] + st["seen_brain"]))
        kept, dropped = verify_quotes([str(x) for x in act.get("quotes") or [] if str(x).strip()], seen_all)
        pushed = check(arm, st, qs[i]["question"], answer, dropped, kept)
        if pushed is not None:
            guard, note = pushed
            st["pushed"] += 1
            st["guards"].add(guard)
            st["steps"].append({"pushback": guard, "answer": answer})
            convs[i].append({"role": "assistant", "content": json.dumps({"answer": answer, **({"quotes": act["quotes"]} if act.get("quotes") else {})},
                                                                         ensure_ascii=False)[:2000]})
            convs[i].append({"role": "user", "content": note})
            return False
        st["answer"] = answer
        step = {"answer": answer, "finish": finish, "raw": visible(text)[:RAW_CHARS]}
        if kept:
            st["support"], st["support_from"] = "\n".join(kept), "quotes"
            step["quotes"] = kept
        elif (arm.brain_first and st["brain_route"] == "prose" and not st["calls"] and answer != NOT_FOUND
              and final(st["brain_answer"], refusals=False) != NOT_FOUND and flat(answer) != flat(st["brain_answer"])):
            # the model kept the brain's document and quoted nothing: the brain's own quote goes with its answer
            st["support"], st["support_from"] = st["brain_answer"], "brain"
        if dropped:
            step["quotes_dropped"] = len(dropped)
        st["steps"].append(step)
        done(i)
        return True

    turn = 0
    while open_ := [i for i in convs if state[i]["answer"] is None]:
        turn += 1
        t = time.perf_counter()
        outs = generate([convs[i] for i in open_])
        gen = time.perf_counter() - t
        calls: list[tuple[str, tuple[str, dict[str, Any]]]] = []
        for i, o in zip(open_, outs, strict=True):
            st = state[i]
            st["turns"] += 1
            st["gen_s"] += gen / len(open_)
            st["prompt_tokens"] += int(o.get("prompt_tokens") or 0)
            st["output_tokens"] += int(o.get("output_tokens") or 0)
            text, finish = o.get("text") or "", o.get("finish_reason")
            st["cut"] += finish == "length"
            if finish == "too_long":  # no room left in the model's window for a reply
                give_up(i, finish, text)
                continue
            act = parse_action(text)
            last = st["calls"] >= arm.max_steps or st["must"]
            if act is not None and "answer" in act:
                settle(i, act, finish, text)
                continue
            if act is None or act.get("tool") not in arm.tools or last:
                st["retries"] += 1
                if st["retries"] > 2 or (last and st["retries"] > 1):
                    give_up(i, finish, text)
                    continue
                convs[i].append({"role": "assistant", "content": visible(text)[:2000] or "(no reply)"})
                again = AGAIN if arm.tools else AGAIN_NOTOOLS
                note = last_note(st) if last and arm.tools else CUT if finish == "length" and not visible(text) else again
                if act is not None and act.get("tool") not in arm.tools and not last:
                    note = f"No tool {act.get('tool')!r}: use one of {', '.join(arm.tools)}. " + again
                convs[i].append({"role": "user", "content": note})
                continue
            st["calls"] += 1
            st["retries"] = 0
            convs[i].append({"role": "assistant", "content": json.dumps({"tool": act["tool"], "args": act["args"]}, ensure_ascii=False)})
            calls.append((i, (act["tool"], act["args"])))
        if calls:
            t = time.perf_counter()
            results = tools.run([c for _, c in calls])
            for (i, (tool, args)), (res, secs) in zip(calls, results, strict=True):
                st = state[i]
                st["tool_s"] += secs
                text = _result_text(res)
                st["worked"] = st["worked"] or "error" not in res
                st["seen"] += strings(res)
                st["steps"].append({"tool": tool, "args": args, "result_chars": len(text), "error": res.get("error"), "s": secs,
                                    "result": text[len("Tool result:\n"):][:STEP_RESULT_CHARS]})
                st["must"] = st["must"] or _chars(convs[i]) + len(text) > CONV_CHARS
                convs[i].append({"role": "user", "content": text + ("\n\n" + last_note(st) if st["calls"] >= arm.max_steps or st["must"] else "")})
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


QUOTE_LINE = re.compile(r"^\W*quotes?\s*\**\s*:\s*\**\s*(.+)$", re.I)


def rag_support(text: str, passages: list[dict[str, str]]) -> str:
    """The plain-search arm's quotes: its "Quote:" lines that are word for word in the passages it was shown."""
    quotes = [m.group(1).strip() for line in visible(text).splitlines() if (m := QUOTE_LINE.match(line))]
    kept, _ = verify_quotes(quotes, flat("\n".join(f"{p['title']}\n{p['text']}" for p in passages)))
    return "\n".join(kept)[:SUPPORT_CAP]


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
                 log: Callable[[str], None] = print, seed: int = 0):
        from vllm import LLM

        repo, rev = resolve_model(name, os.environ.get("HF_TOKEN"), log=log)
        # prefix caching is left to vLLM: Qwen3.8 mixes linear-attention layers with attention, which it may not cache
        kw: dict[str, Any] = {"model": repo, "dtype": "bfloat16", "gpu_memory_utilization": gpu_mem, "max_model_len": max_model_len,
                              "seed": seed}
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
        self.name, self.max_tokens, self.max_model_len, self.log, self.seed = name, max_tokens, max_model_len, log, seed
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
        base = dict(temperature=1.0, top_p=0.95, top_k=20, seed=self.seed) if self.thinks else dict(temperature=0.0, seed=self.seed)
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
                 extra: dict[str, Any] | None = None, effort: str | None = None, thinking: bool | None = None, seed: int = 0):
        self.model, self.base_url, self.max_tokens, self.concurrency = model, base_url.rstrip("/"), max_tokens, concurrency
        self.seed = seed
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

        body = {"model": self.model, "messages": msgs, "max_tokens": self.max_tokens, "temperature": 0, "seed": self.seed, **self.extra}
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
