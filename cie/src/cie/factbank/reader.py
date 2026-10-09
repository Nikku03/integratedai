"""A small language model reads the question; the fact bank finds the facts and reasons (v7).

The model (Llama 3.2 3B, local, through Ollama) sees only the question and a menu of standard questions. It never sees a
document. It rewrites the question as the closest standard question, with the question's own names, keys and numbers.
The fact bank then answers the rewrite exactly as it answers any question, with its plan and journal.

A rewrite is used only if it keeps every key, pull request number, quoted title and named person of the original.
Otherwise the original question is used. Every rewrite is kept in a cache file, so a run can be repeated without the
model and checked afterwards.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{2,7}\b")
PR = re.compile(r"#\d{2,7}\b")
QUOTED = re.compile(r'"([^"]+)"')
MODEL = "llama3.2:3b"
LETTERS = {"n": "N", "k": "K", "p": "P", "a": "A", "b": "B", "t": "T", "m": "M"}


def menu() -> list[str]:
    """The standard questions: the first training wording of each kind (and field), placeholders as capital letters."""
    from cie.eval.factbank_multi import T

    out = []
    for (_kind, _field), (train, _held) in T.items():
        w = train[0]
        for ph, letter in LETTERS.items():
            w = w.replace("{" + ph + "}", letter)
        out.append(w)
    return out


def system_prompt() -> str:
    lines = "\n".join(f"{i}. {w}" for i, w in enumerate(menu(), 1))
    return ("You turn a person's question into the closest one of these standard questions, filling in the names, keys, numbers "
            "and quoted titles from the person's question exactly as they are written. Answer with the standard question only.\n"
            + lines)


def must_keep(question: str, people: list[str]) -> list[str]:
    """What a rewrite has to keep: keys, pull request numbers, quoted titles and the people the question names."""
    return list(dict.fromkeys(KEY.findall(question) + PR.findall(question) + QUOTED.findall(question) + people))


def keeps(rewrite: str, needed: list[str]) -> bool:
    low = rewrite.lower()
    return all(x.lower() in low for x in needed)


class Reader:
    def __init__(self, cache: str | Path, model: str = MODEL, host: str | None = None, timeout: float = 600.0):
        self.cache_path = Path(cache)
        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
        self.timeout = timeout
        self.cache: dict[str, dict[str, Any]] = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.cache[r["question"]] = r

    def _ask(self, question: str) -> str:
        body = json.dumps({"model": self.model, "stream": False, "options": {"temperature": 0, "seed": 0, "num_predict": 120},
                           "messages": [{"role": "system", "content": system_prompt()}, {"role": "user", "content": question}]}).encode()
        url = self.host if self.host.startswith("http") else f"http://{self.host}"
        req = urllib.request.Request(f"{url}/api/chat", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["message"]["content"].strip().strip('"').strip()

    def read(self, question: str, people: list[str]) -> dict[str, Any]:
        """The question to answer: the model's rewrite if it keeps what it must, otherwise the original."""
        if question not in self.cache:
            raw = self._ask(question)
            self.cache[question] = {"question": question, "model": self.model, "rewrite": raw}
            with self.cache_path.open("a") as f:
                f.write(json.dumps(self.cache[question]) + "\n")
        raw = self.cache[question]["rewrite"]
        needed = must_keep(question, people)
        ok = bool(raw) and keeps(raw, needed)
        return {"asked": raw if ok else question, "rewrite": raw, "used_rewrite": ok, "must_keep": needed}


def people_named(bank, question: str) -> list[str]:
    return [bank.names.get(e, e) for e in bank.named(question) if e.startswith("person:")]


# ------------------------------------------------------------------------------------------------------------------ the glossary
# v8: a glossary of everyday phrases, written once by a large language model that saw only the bank's fields
# (docs/benchmarks/factbank_llm/glossary.json). At question time no model runs: a phrase found in the question adds the
# standard words of what it points at. The standard words are taken from the training questions' own wordings.
CANON = {
    "assignee": "assigned", "due_date": "due date deadline", "status": "status state", "author": "authored wrote opened",
    "creator": "created", "reviewers": "reviewers", "owner": "owns took",
    "linked": "linked links", "references": "references referenced",
    "count": "how many number count", "earliest": "first earliest sooner", "latest": "latest", "list": "list keys",
    "person": "who", "date": "when", "number": "how many", "ticket key": "key",
}


def _stems(text: str) -> list[str]:
    from cie.factbank.engine import stem

    return [stem(w) for w in re.findall(r"[a-z]+", text.lower())]


class Glossary:
    def __init__(self, entries: list[dict[str, str]]):
        self.entries = [(tuple(_stems(e["phrase"])), CANON[e["target"]]) for e in entries if e.get("target") in CANON and _stems(e["phrase"])]

    @classmethod
    def load(cls, path: str | Path) -> Glossary:
        return cls(json.loads(Path(path).read_text()))

    def words(self, question: str) -> tuple[set[str], set[str]]:
        """The standard words added for the question: for the plan's words (stop words dropped) and for its kind of answer."""
        from cie.factbank.engine import words
        from cie.factbank.plans import question_words

        toks = _stems(QUOTED.sub(" ", question))
        found = [canon for phrase, canon in self.entries
                 if any(tuple(toks[i:i + len(phrase)]) == phrase for i in range(len(toks) - len(phrase) + 1))]
        text = " ".join(dict.fromkeys(found))
        return set(words(text)), question_words(text)


# ------------------------------------------------------------------------------------------------------------------ the form
# v10 (docs/FACTBANK_PLAN_PREREGISTRATION.md): the small model does not rewrite the question. It fills in a two-line form:
# what kind of thing the answer is, and which property it is read from. The fact bank keeps only the plans that fit the form,
# picks one with its learned weights, carries it out and checks it. The model never sees a document.
FORM_SYSTEM = """You read a question about work tickets and pull requests and fill in a small form about it. Do not answer the question.
- "answer": what kind of thing the answer is: "person" (a name), "date", "number" (a count), "ticket key" (one or more ticket identifiers such as ENG-123), or "status" (a state such as In Progress or Done).
- "field": which property the answer is read from: "assignee" (who a ticket is assigned to), "due date", "status", "author" (who opened a pull request), "creator" (who created a ticket), "owner" (who owns a meeting action item), or "none".
Reply with the JSON form only.

Examples:
"Who is assigned to the Linear issue that pull request #123 is linked to?" -> {"answer": "person", "field": "assignee"}
"When is the Linear issue linked from PR #123 due?" -> {"answer": "date", "field": "due date"}
"What is the status of the ticket that ENG-1 is linked to?" -> {"answer": "status", "field": "status"}
"Who authored the pull request linked to Linear issue ENG-1?" -> {"answer": "person", "field": "author"}
"How many Linear issues are assigned to Ann Lee?" -> {"answer": "number", "field": "none"}
"Which of the Linear issues assigned to Ann Lee is due first? Give the key." -> {"answer": "ticket key", "field": "due date"}
"Which is due sooner, ENG-1 or ENG-2?" -> {"answer": "ticket key", "field": "due date"}"""
FORM_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string", "enum": ["person", "date", "number", "ticket key", "status"]},
    "field": {"type": "string", "enum": ["assignee", "due date", "status", "author", "creator", "owner", "none"]}},
    "required": ["answer", "field"]}
# the form's words → the planner's kinds of answer and the bank's fields
FORM_KIND = {"person": "person", "date": "date", "number": "count", "ticket key": "key", "status": "other"}
FORM_FIELD = {"assignee": ("assignee",), "due date": ("due_date",), "status": ("status", "state"), "author": ("author",),
              "creator": ("creator",), "owner": ("owner",), "none": ()}


def form_fingerprint() -> str:
    import hashlib

    return hashlib.sha256((FORM_SYSTEM + json.dumps(FORM_SCHEMA, sort_keys=True)).encode()).hexdigest()[:16]


class Former:
    """The small model's form for each question, kept in a cache file (keyed by the question and the prompt's fingerprint, so
    a changed prompt never reuses old forms)."""

    def __init__(self, cache: str | Path, model: str = MODEL, host: str | None = None, timeout: float = 600.0):
        self.cache_path = Path(cache)
        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
        self.timeout = timeout
        self.fp = form_fingerprint()
        self.cache: dict[tuple[str, str], dict[str, Any]] = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.cache[(r["question"], r["prompt"])] = r

    def _ask(self, question: str) -> dict[str, str]:
        body = json.dumps({"model": self.model, "stream": False, "format": FORM_SCHEMA,
                           "options": {"temperature": 0, "seed": 0, "num_predict": 60},
                           "messages": [{"role": "system", "content": FORM_SYSTEM}, {"role": "user", "content": question}]}).encode()
        url = self.host if self.host.startswith("http") else f"http://{self.host}"
        req = urllib.request.Request(f"{url}/api/chat", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(json.loads(r.read())["message"]["content"])

    def form(self, question: str) -> dict[str, Any]:
        """The filled form: ``kind`` (the planner's kind of answer) and ``fields`` (the bank fields it may be read from)."""
        key = (question, self.fp)
        if key not in self.cache:
            import time

            t = time.perf_counter()
            raw = self._ask(question)
            self.cache[key] = {"question": question, "prompt": self.fp, "model": self.model, "form": raw,
                               "ms": round((time.perf_counter() - t) * 1000, 1)}
            with self.cache_path.open("a") as f:
                f.write(json.dumps(self.cache[key]) + "\n")
        raw = self.cache[key]["form"]
        return {"kind": FORM_KIND.get(raw.get("answer", "")), "fields": FORM_FIELD.get(raw.get("field", ""), ()), "raw": raw,
                "model_ms": self.cache[key].get("ms")}
