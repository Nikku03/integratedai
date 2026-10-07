"""Asking the fact bank: the cell repository's v2 engine (``rem/atlas/cellbank2.py``, ``new_engine``) for company facts.

1. **Seeds.**
   - Entities named in the question by an alias (an issue key, a person's full name) get relevance 1.
   - Entities found by content (SQLite FTS5 BM25 over title, fields and text, top ``k``) get 1/(1 + rank).
2. **One hop at a time, then snap** (at most 3 hops).
   - Every entity on the frontier is looked up by subject, and each of its facts casts a vote for (entity, parameter,
     value). The weight is relevance × confidence (measured 1, inferred 0.7) × authority (primary 1, secondary 0.8).
   - The snap writes the result down. For a parameter with one value per source, the value with the largest total
     wins; an exact tie between different values is a contradiction, and nothing is written. Other parameters write
     every value.
   - What is written is never decided again.
   - The entities the written values point to are the next frontier, at relevance × λ. λ = 0.863 is the cell engine's
     per-hop decay, used for ranking only.
3. **Journal.** Every write and contradiction is recorded with the facts that voted. ``replay`` rebuilds the state
   from the journal alone.
4. **An answer without a language model.**
   - The question's words choose the parameter: field names, plus a short list of synonyms. The best-ranked written
     value of that parameter is the answer.
   - A question asking which document gets the best document's title.
   - Lists ("every Linear issue assigned to P") use the inverse parameter on P (``assignee_of``), filtered by what the
     question names: a source system, a quoted status, a date window.
5. **Evidence for a model:** the written facts, one line each, best entity first, then the text of the best documents.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LAM, HOPS = 0.863, 3
MULTI = {"referenced_by", "action_item", "action_owner_of", "from_document"}
CONF_W = {"measured": 1.0, "inferred": 0.7, "estimated": 0.5, "assumed": 0.3}
AUTH_W = {"primary": 1.0, "secondary": 0.8}
STOP = set("a an the of in on for to and or is are was were be by with at from about which what who whom when where how does did do "
           "this that these those it its as into listed give every all list their there any".split())
# question words -> the parameters they ask for (beyond the parameter's own name)
CUES = {
    "own": ["owner", "redwood_owner", "account_owner", "mailbox_owner", "author"],
    "organiz": ["redwood_owner", "owner"],
    "assign": ["assignee", "se_assigned", "csm_assigned"],
    "author": ["author", "creator"], "wrote": ["author", "creator"], "written": ["author", "creator"],
    "creat": ["creator", "author", "created_at"], "open": ["author", "creator"], "report": ["reporter"], "file": ["reporter", "creator"],
    "due": ["due_date"], "deadlin": ["due_date"],
    "status": ["status", "state", "stage"], "state": ["state", "status"], "stage": ["stage", "status"],
    "review": ["reviewers"], "attend": ["redwood_attendees", "customer_attendees", "participants"],
    "team": ["team", "owner_team"], "priorit": ["priority"], "sever": ["severity"],
}
DOC_NOUNS = {"page", "document", "doc", "spreadsheet", "sheet", "file", "thread", "ticket", "issue", "deck", "memo", "note", "pr",
             "pull", "request", "meeting", "call", "deal", "account", "company"}
SYSTEM_WORDS = {"linear": "linear", "jira": "jira", "github": "github", "pull request": "github", "pr ": "github",
                "slack": "slack", "confluence": "confluence", "hubspot": "hubspot", "gmail": "gmail", "email": "gmail",
                "drive": "google_drive", "meeting": "fireflies", "fireflies": "fireflies"}
LIST_RE = re.compile(r"\b(list every|list all|which \w+ (issues|tickets|pull requests|documents|pages)|every \w+ (issue|ticket))\b", re.I)


def stem(w: str) -> str:
    w = w.lower()
    for suf in ("ings", "ing", "ers", "er", "ees", "ee", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def words(s: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", s) if w.lower() not in STOP]


@dataclass
class Written:
    entity: str
    parameter: str
    values: list[str]
    hop: int
    score: float
    facts: list[str]
    value_entities: list[str | None] = field(default_factory=list)


@dataclass
class Result:
    answer: str
    evidence: str
    journal: list[dict[str, Any]]
    written: dict[tuple[str, str], Written]
    seeds: list[tuple[str, float]]
    ms: float
    reason: str = ""


class FactBank:
    def __init__(self, path: str | Path):
        self.con = sqlite3.connect(str(path))
        self.con.row_factory = sqlite3.Row
        self.authority = {r["id"]: r["authority"] for r in self.con.execute("SELECT id, authority FROM sources")}
        self.system = {r["id"]: r["system"] for r in self.con.execute("SELECT id, system FROM sources")}
        self.names = {r["id"]: r["name"] for r in self.con.execute("SELECT id, name FROM entities")}
        self.kinds = {r["id"]: r["kind"] for r in self.con.execute("SELECT id, kind FROM entities")}
        self.aliases: dict[str, set[str]] = defaultdict(set)
        for r in self.con.execute("SELECT alias, entity FROM aliases"):
            self.aliases[r["alias"]].add(r["entity"])
        # a parameter is single-valued when no source gives one entity two values for it; inverse parameters (one entry
        # per document that points here) never are
        self.single = {r[0] for r in self.con.execute(
            "SELECT parameter FROM (SELECT parameter, max(n) m FROM (SELECT parameter, entity, source, count(*) n FROM facts "
            "GROUP BY parameter, entity, source) GROUP BY parameter) WHERE m = 1")
            if not r[0].endswith("_of") and r[0] not in MULTI}

    # ------------------------------------------------------------------ lookup
    def facts_of(self, entity: str) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM facts WHERE entity = ? ORDER BY id", (entity,)).fetchall()

    def named(self, question: str) -> list[str]:
        """Entities the question names by an alias: an identifier or a person's full name."""
        q = question.lower()
        out = []
        for alias, ents in self.aliases.items():
            if len(alias) >= 4 and re.search(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", q):
                out += sorted(ents)
        return out

    def by_content(self, question: str, k: int) -> list[str]:
        terms = sorted(set(re.findall(r"[a-z0-9]{3,}", question.lower())) - STOP)
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self.con.execute("SELECT id FROM entities_fts WHERE entities_fts MATCH ? ORDER BY bm25(entities_fts, 0.0, 3.0, 1.0) LIMIT ?",
                                (match, k)).fetchall()
        return [r["id"] for r in rows]

    # ------------------------------------------------------------------ reasoning
    def run(self, question: str, k: int = 5, hops: int = HOPS, seeds: dict[str, float] | None = None
            ) -> tuple[dict[tuple[str, str], Written], list[dict[str, Any]], list[tuple[str, float]]]:
        """Seeds (``seeds``, or found from the question), then hops with a snap. Returns what was written, the journal
        and the seeds."""
        if seeds is None:
            seeds = {}
            for e in self.named(question):
                seeds[e] = 1.0
            for i, e in enumerate(self.by_content(question, k)):
                seeds.setdefault(e, 1.0 / (1 + i))
        seeds = dict(seeds)
        written: dict[tuple[str, str], Written] = {}
        journal: list[dict[str, Any]] = [{"op": "seed", "entity": e, "relevance": round(r, 4)} for e, r in seeds.items()]
        relevance = dict(seeds)
        frontier = list(seeds)
        for hop in range(1, hops + 1):
            votes: dict[tuple[str, str, str], float] = defaultdict(float)
            why: dict[tuple[str, str, str], list[str]] = defaultdict(list)
            target: dict[tuple[str, str, str], str | None] = {}
            for e in frontier:
                for f in self.facts_of(e):
                    key = (e, f["parameter"], f["value"])
                    if (e, f["parameter"]) in written:
                        continue
                    votes[key] += relevance[e] * CONF_W.get(f["confidence"], 0.3) * AUTH_W.get(self.authority.get(f["source"], ""), 0.8)
                    why[key].append(f["id"])
                    target[key] = f["value_entity"]
            by_param: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
            for (e, p, v), w in votes.items():
                by_param[(e, p)].append((v, w))
            nxt: list[str] = []
            for (e, p), vals in sorted(by_param.items()):
                vals.sort(key=lambda x: (-x[1], x[0]))
                if p in self.single and len(vals) > 1:
                    if abs(vals[0][1] - vals[1][1]) < 1e-12:
                        journal.append({"op": "contradiction", "entity": e, "parameter": p, "values": [v for v, _ in vals], "hop": hop,
                                        "facts": [x for v, _ in vals for x in why[(e, p, v)]]})
                        continue
                    vals = vals[:1]
                w = Written(e, p, [v for v, _ in vals], hop, max(x for _, x in vals) * LAM ** hop,
                            [x for v, _ in vals for x in why[(e, p, v)]], [target[(e, p, v)] for v, _ in vals])
                written[(e, p)] = w
                journal.append({"op": "set", "entity": e, "parameter": p, "values": w.values, "hop": hop, "score": round(w.score, 6),
                                "facts": w.facts})
                for t in w.value_entities:
                    if t and t not in relevance:
                        relevance[t] = relevance[e] * LAM
                        nxt.append(t)
            if not nxt:
                break
            frontier = nxt
        return written, journal, sorted(seeds.items(), key=lambda x: -x[1])

    # ------------------------------------------------------------------ answering
    def ask(self, question: str, k: int = 5, budget: int = 24_000) -> Result:
        t = time.perf_counter()
        written, journal, seeds = self.run(question, k)
        answer, reason = self.answer(question, written, seeds)
        evidence = self.evidence(written, seeds, budget)
        return Result(answer, evidence, journal, written, seeds, (time.perf_counter() - t) * 1000, reason)

    def label(self, entity: str, written: dict[tuple[str, str], Written]) -> str:
        """An entity as the questions cite it: an issue key, a pull request number, else its name."""
        for p in ("key",):
            w = written.get((entity, p))
            if w:
                return w.values[0]
        w = written.get((entity, "pr_number"))
        if w:
            return "#" + w.values[0]
        for f in self.facts_of(entity):
            if f["parameter"] == "key":
                return f["value"]
            if f["parameter"] == "pr_number":
                return "#" + f["value"]
        return self.names.get(entity, entity)

    def wanted(self, question: str) -> dict[str, float]:
        """Parameters the question asks for, with weights: its cue words, and field names sharing its words."""
        qw = set(words(question))
        out: dict[str, float] = defaultdict(float)
        for w in qw:
            for cue, params in CUES.items():
                if w.startswith(cue):
                    for i, p in enumerate(params):
                        out[p] += 2.0 - 0.1 * i
        params = {r[0] for r in self.con.execute("SELECT DISTINCT parameter FROM facts")}
        for p in params:
            toks = {stem(x) for x in p.split("_") if x}
            hit = len(toks & qw)
            if hit and not p.endswith("_of"):
                out[p] += hit / len(toks)
        return out

    def answer(self, question: str, written: dict[tuple[str, str], Written], seeds: list[tuple[str, float]]) -> tuple[str, str]:
        ql = question.lower()
        want = self.wanted(question)
        if LIST_RE.search(question):
            return self.list_answer(question, want, written)
        rel = dict(seeds)
        best, best_s, why = None, 0.0, ""
        for (e, p), w in written.items():
            if p.endswith("_of") or p in ("referenced_by", "action_item", "from_document"):
                continue
            s = want.get(p, 0.0)
            if s <= 0:
                continue
            score = s * (rel.get(e, 0) + w.score)
            if score > best_s:
                best, best_s, why = w, score, f"{p} of {self.names.get(e, e)}"
        if best is not None:
            return ", ".join(best.values), why
        if any(n in set(re.findall(r"[a-z]+", ql)) for n in DOC_NOUNS) and seeds and re.match(r"\s*(in [^,]+,\s*)?(which|what)\b", ql):
            e = next((e for e, _ in seeds if self.kinds.get(e) == "document"), None)
            if e:
                return self.names.get(e, e), "the best document's title"
        return "not found", "no written fact matches what the question asks"

    def list_answer(self, question: str, want: dict[str, float], written: dict[tuple[str, str], Written]) -> tuple[str, str]:
        ql = question.lower() + " "
        system = next((s for w, s in SYSTEM_WORDS.items() if w in ql), None)
        status = re.findall(r"\"([^\"]+)\"", question)
        window = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question)
        people = [e for e in self.named(question) if e.startswith("person:")]
        if people:
            inv = [p + "_of" for p, _ in sorted(want.items(), key=lambda x: -x[1]) if not p.endswith("_of")][:3]
            cands = []
            for person in people:
                for p in inv:
                    w = written.get((person, p))
                    if w:
                        cands += [t for t in w.value_entities if t]
                if cands:
                    break
        elif window:
            lo, hi = min(window), max(window)
            cands = [r[0] for r in self.con.execute("SELECT DISTINCT entity FROM facts WHERE parameter = 'due_date' AND value BETWEEN ? AND ?",
                                                     (lo, hi))]
            window = []
        else:
            return "not found", "a list question that names no person and no window"
        out = []
        for e in dict.fromkeys(cands):
            facts = {f["parameter"]: f["value"] for f in self.facts_of(e)}
            src = next((f["source"] for f in self.facts_of(e)), "")
            if system and self.system.get(src) != system:
                continue
            if status and str(facts.get("status", facts.get("state", ""))).lower() not in {s.lower() for s in status}:
                continue
            if window and not (min(window) <= str(facts.get("due_date", "")) <= max(window)):
                continue
            out.append(self.label(e, written))
        return (", ".join(out) if out else "not found"), f"{len(out)} items"

    def evidence(self, written: dict[tuple[str, str], Written], seeds: list[tuple[str, float]], budget: int) -> str:
        """Written facts grouped by entity, best first; then the best documents' text, until the budget is used."""
        by_e: dict[str, list[Written]] = defaultdict(list)
        for w in written.values():
            by_e[w.entity].append(w)
        order = sorted(by_e, key=lambda e: -max(w.score for w in by_e[e]))
        parts, used = [], 0
        for e in order:
            lines = [f"[{self.kinds.get(e, '?')}] {self.names.get(e, e)}"] + [
                f"- {w.parameter.replace('_', ' ')}: {', '.join(w.values)[:400]}" for w in sorted(by_e[e], key=lambda w: w.parameter)]
            block = "\n".join(lines)
            if used + len(block) > budget:
                break
            parts.append(block)
            used += len(block) + 2
        for e, _ in seeds:
            if self.kinds.get(e) != "document" or used >= budget:
                continue
            row = self.con.execute("SELECT text FROM entities_fts WHERE id = ?", (e,)).fetchone()
            if row:
                text = row[0][: max(0, min(6000, budget - used - 50))]
                parts.append(f"[text] {self.names.get(e, e)}\n{text}")
                used += len(text) + 60
        return "\n\n".join(parts)


def replay(journal: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    """The written state rebuilt from the journal alone."""
    state: dict[tuple[str, str], list[str]] = {}
    for j in journal:
        if j["op"] == "set":
            key = (j["entity"], j["parameter"])
            if key in state:
                raise ValueError(f"{key} written twice")
            state[key] = list(j["values"])
    return state


def state_of(written: dict[tuple[str, str], Written]) -> dict[tuple[str, str], list[str]]:
    return {k: list(w.values) for k, w in written.items()}


def dump_journal(journal: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(j, ensure_ascii=False) for j in journal)
