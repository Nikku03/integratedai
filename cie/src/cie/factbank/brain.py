"""The company brain (fact bank v15): one ``ask`` for every kind of question about the company.

``Brain.ask`` takes the first route that applies:

1. **not_found:** the question names a ticket key, a pull request number, a quoted title or a person's full name that the
   bank does not hold (``Brain.missing``). The answer is "not found", and the reason names what is missing.
2. **Fact or prose:** a router reads the question and a few signals (``Brain.signals``) and decides whether it asks for a
   fact (a field, a person, a date, a count, a list of keys) or for something written in prose. ``Router`` is a small
   logistic regression trained on questions labelled by family; without one, a rule decides (``Router.rule``).
3. **fact:** the planner's answer when its best plan starts from something the question names, it found one and, for a plain
   read of one field, the question asks for that field (route ``plan``, ``Brain.reads_asked_field``). Otherwise the single-document engine's answer: v1's ``FactBank.ask`` on the same bank, reading the documents'
   fields as v1 did (``BrainBank``), with the brain's evidence (route ``fact``), or the planner's answer when the engine finds
   nothing.
4. **prose:** sentences quoted from the passages of document text that best match the question
   (``cie.retrieval.answer.quote_answer`` over ``FactBank.passages``), or "not found" when no sentence holds a question word.

One bank serves every route: the v2 bank file with the single-fact lessons, in the brain's modes (``brain``, whole-word
system names), and the plan lessons with the planner's brain fixes, whatever the lessons file says.

    python -m cie.factbank.brain ask --work W --single LESSONS --plans PLAN_LESSONS [--router ROUTER] [--name factbank_v15]
        [--no-field-check]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from cie.factbank.engine import FactBank, Result, stem
from cie.factbank.learn import Lessons, sigmoid
from cie.factbank.plans import QUOTED, PlanLessons, Planner, raw_words, unquoted
from cie.factbank.plans import answer as plan_answer
from cie.factbank.trained import TrainedBank

BUDGET = 24_000
PROSE_SIZE = (600, 1000)
TICKET = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,7})\b")
PR_NUMBER = re.compile(r"(?:(?<![\w&#])#|\b(?:PR|pull request)\s*[#-]?\s*)(\d{2,7})\b", re.I)
NAME_WORD = r"[A-Z\u00c0-\u00de\u0100-\u017f][A-Za-z\u00c0-\u00ff\u0100-\u017f'\u2019-]*[a-z\u00df-\u00ff\u0100-\u017f]"
PERSON_SPAN = re.compile(rf"\b{NAME_WORD}(?:\s+{NAME_WORD}){{1,2}}\b")
KEY_ALIAS = re.compile(r"^([a-z][a-z0-9]{1,9})-\d{1,7}$")
# the word next to a quoted string that makes it a document's title ('the Confluence page "X"', 'the "X" meeting'); an action
# item's text ('took this action item: "X"') or a status ('the status "Done"') is not one
TITLE_NOUNS = frozenset(("document", "doc", "page", "account", "meeting", "issue", "ticket", "thread", "file", "deck", "spreadsheet",
                         "sheet", "memo", "note", "notes", "call", "pr", "request", "runbook", "playbook", "project", "epic", "deal",
                         "email", "repo", "repository"))
TITLE_LEADS = frozenset(("titled", "called", "named", "entitled"))
# a field or an item asked for after "what" or "which" ("what is the current ticket status", "which draft doc"): the question
# asks for a fact
ASKED_NOUNS = frozenset(("status", "state", "stage", "priority", "severity", "release", "version", "environment", "owner", "assignee",
                         "reporter", "author", "creator", "organizer", "engineer", "reviewer", "reviewers", "attendees", "repo",
                         "repository", "space", "project", "team", "tier", "region", "deadline", "due", "date", "month", "filename",
                         "filenames", "attachment", "attachments", "quality", "method", "tag", "label", "labels", "identifier", "id",
                         "key", "keys", "number", "ticket", "tickets", "issue", "issues", "pr", "prs", "pull", "sla", "customer",
                         "document", "doc", "page", "runbook", "playbook", "account", "meeting", "call", "thread", "deck",
                         "spreadsheet", "sheet", "note", "file"))
KEY_WORDS = frozenset(("keys", "ids", "identifiers"))  # plural: a list of keys ("the key quota checks", "corr-id" ask for none)
OPENERS = frozenset(("and", "but", "so", "then", "also"))
LEAD_INS = frozenset(("by", "until", "till", "since", "on", "at", "to", "for", "from", "in", "of", "with"))
ASK_WINDOW = 7
JOURNAL_STEPS = 200
SIGNALS = ("start_named", "names", "has_id", "quoted", "plan_score", "plan_high", "who", "when", "how_many", "field_word", "keys", "list",
           "what_is_the", "how_do", "why", "what_caused", "long")
RULE_FACT = ("start_named", "names", "who", "when", "how_many", "field_word", "keys")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WHAT_IS_THE = re.compile(r"\bwhat (?:is|are|was|were) the\b")
HOW_DO = re.compile(r"\bhow (?:do|does|did|should|can|could|would|to|is|are|was|were)\b")
WHAT_CAUSED = re.compile(r"\bwhat (?:caused|causes|led to)\b|\b(?:root )?cause\b")


def squash(s: str) -> str:
    """Lower case, letters and digits only, accents dropped as the bank's index drops them, "&" read as "and" and "+" as
    "plus": a title as a question may quote it ("Q3 roadmap - draft" for "Q3 Roadmap — Draft", "batching & queueing" for
    "batching and queueing")."""
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s).lower()) if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", s.replace("&", " and ").replace("+", " plus ")).strip()


def clause_tokens(question: str) -> list[str]:
    """The question's words and punctuation, lower case, outside quoted titles (as ``Planner.interrogative_kind`` reads it)."""
    return re.findall(r"[a-z0-9]+|[,:;.?!()\u2014\u2013]", unquoted(question.lower()))


def asks_field(question: str) -> bool:
    """A clause-opening "what" or "which" (alone, or after "in", "on", "for"…) with a field or an item (``ASKED_NOUNS``) among the
    next few words, before any punctuation: "what is the current ticket status", "In which month", "which draft doc"."""
    toks = clause_tokens(question)

    def opens(j: int) -> bool:
        return j == 0 or not toks[j - 1][0].isalnum() or toks[j - 1] in OPENERS

    for i, t in enumerate(toks):
        if t not in ("what", "which") or not (opens(i) or toks[i - 1] in LEAD_INS and opens(i - 1)):
            continue
        for x in toks[i + 1:i + 1 + ASK_WINDOW]:
            if not x[0].isalnum():
                break
            if x in ASKED_NOUNS:
                return True
    return False


def rests_on(journal: list[dict[str, Any]], answer: str, limit: int = JOURNAL_STEPS) -> list[dict[str, Any]]:
    """The engine's journal cut to what an answer rests on: the seeds, then the writes and contradictions whose values hold the
    answer or one of its items (at most ``limit`` steps), and a last step counting them all. On thousands of documents the
    whole journal runs to megabytes a question; ``Brain.engine`` gives it in full."""
    parts = {answer, *answer.split(", ")}
    keep = [j for j in journal if j.get("op") == "seed" or set(j.get("values") or ()) & parts]
    return [*keep[:limit], {"op": "steps", "count": len(journal)}]


class BrainBank(TrainedBank):
    """The bank under the brain. v1's engine (``FactBank.ask``) answers from the documents' fields only, not from the dates and
    keys taken from their sentences (``text_*`` facts), as on the v1 bank file it was measured on: in the v2 bank a document's
    sentence dates would otherwise outvote its own "SLA due" field."""

    def wanted(self, question: str) -> dict[str, float]:
        return {p: w for p, w in super().wanted(question).items() if not p.startswith("text_")}


def question_words(question: str) -> set[str]:
    """The question's words for the router, stemmed, outside quoted titles, without keys and numbers."""
    text = PR_NUMBER.sub(" ", TICKET.sub(" ", QUOTED.sub(" ", question)))
    return {stem(w) for w in re.findall(r"[a-z]{2,}", text.lower())}


class Router:
    """Fact or prose: a logistic regression over the question's words (``w:<stem>``) and the brain's signals (``SIGNALS``),
    trained on questions labelled by family (``train``). Without weights, ``rule`` decides."""

    def __init__(self, features: list[str] | None = None, weights: list[float] | None = None, trained_on: dict[str, Any] | None = None):
        self.features = list(features or [])
        self.weights = list(weights or [])
        self.trained_on = dict(trained_on or {})

    @staticmethod
    def rule(sig: dict[str, float]) -> dict[str, float]:
        """Prose when the question has no field-like question word (who, when, how many, keys, or what or which before a field
        or an item) and names no start (the best plan's start, or anything the planner reads as named: a key, a pull request
        number, a full name, a quoted title); fact otherwise."""
        fact = float(any(sig.get(k, 0.0) for k in RULE_FACT))
        return {"fact": fact, "prose": 1.0 - fact}

    def scores(self, sig: dict[str, float]) -> dict[str, float]:
        """How sure the router is of each family, summing to 1."""
        if not self.weights:
            return self.rule(sig)
        p = sigmoid(sum(w * sig.get(f, 0.0) for f, w in zip(self.features, self.weights, strict=True)))
        return {"fact": round(1.0 - p, 4), "prose": round(p, 4)}

    @staticmethod
    def label(q: dict[str, Any]) -> int:
        """1 for a prose question (its ``route`` or ``family`` says so), 0 for any other."""
        return int((q.get("route") or q.get("family")) == "prose")

    @classmethod
    def train(cls, questions: list[dict[str, Any]], brain: Brain, min_count: int = 2, l2: float = 1.0) -> Router:
        """Fit on questions with a family ({"question", "family"}; the families of ``cie.eval.brain_questions``). Words that
        fewer than ``min_count`` questions use are left out."""
        import numpy as np

        from cie.factbank.learn import fit

        sigs = [brain.signals(q["question"]) for q in questions]
        ys = [cls.label(q) for q in questions]
        counts = Counter(f for s in sigs for f in s if f.startswith("w:"))
        feats = ["bias", *SIGNALS, *sorted(f for f, c in counts.items() if c >= min_count)]
        x = np.array([[s.get(f, 0.0) for f in feats] for s in sigs], float)
        return cls(feats, fit(x, np.array(ys), l2), {"questions": len(questions), "prose": sum(ys), "min_count": min_count, "l2": l2})

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"features": self.features, "weights": self.weights, "trained_on": self.trained_on}, indent=1))

    @classmethod
    def load(cls, path: str | Path) -> Router:
        d = json.loads(Path(path).read_text())
        return cls(d.get("features"), d.get("weights"), d.get("trained_on"))


class Brain:
    """The company brain over one bank (``bank_path``, a v2 bank file), the single-fact lessons and the plan lessons. With
    ``field_check`` (the default), the planner's answer to a question that names its start stands only when its plan reads
    what the question asks for (``reads_asked_field``); otherwise the engine answers, as when the start is not named."""

    def __init__(self, bank_path: str | Path, single_lessons_path: str | Path, plan_lessons_path: str | Path, router: Router | None = None,
                 *, budget: int = BUDGET, field_check: bool = True):
        self.bank = BrainBank(bank_path, Lessons.load(single_lessons_path))
        self.bank.brain = True
        self.bank.answer_first = False  # the planner path prints its own answer; the engine path sets it while it runs
        self.bank.whole_system_words = True
        self.lessons = PlanLessons.load(plan_lessons_path)
        self.lessons.brain = True
        self.planner = self.lessons.planner(self.bank)
        self.planner.brain = True
        self.router = router
        self.budget = budget
        self.field_check = field_check
        self._prefixes: set[str] | None = None
        self._titles: set[str] | None = None
        self._names: tuple[set[str], set[str]] | None = None
        self._fts: dict[str, bool] = {}

    # ------------------------------------------------------------------ not found
    def holds_text(self, phrase: str) -> bool:
        """Whether any entity's name or text writes the phrase as whole words, both read as ``squash`` reads them: case,
        punctuation, accents and "&" for "and" do not matter, word forms do ("Luca Chen" is not "Lucas Chen", though the
        stemmed index matches both). A phrase with no letters or digits counts as held."""
        if phrase not in self._fts:
            want = squash(phrase)
            self._fts[phrase] = not want or any(f" {want} " in f" {squash(n)} " or f" {want} " in f" {squash(t)} "
                                                for n, t in self.index_rows(want))
        return self._fts[phrase]

    def index_rows(self, want: str) -> Iterator[tuple[str, str]]:
        """The (name, text) rows the stemmed index matches for a squashed phrase, then for it without the words "and" and
        "plus" (an "&" or a "+" in the text, which the index does not keep)."""
        bare = " ".join(re.sub(r"\b(?:and|plus)\b", " ", want).split())
        for q in dict.fromkeys(x for x in (want, bare) if x):
            yield from self.bank.con.execute("SELECT name, text FROM entities_fts WHERE entities_fts MATCH ?", (f'"{q}"',))

    def ticket_prefixes(self) -> set[str]:
        """The prefixes of the ticket keys the bank knows ("ENG", "PM"), from its documents' keys and the keys they cite."""
        if self._prefixes is None:
            out = {m.group(1).upper() for a in self.bank.aliases if (m := KEY_ALIAS.match(a))}
            out |= {m.group(1) for e, k in self.bank.kinds.items() if k == "identifier" and (m := TICKET.fullmatch(self.bank.names.get(e, "")))}
            self._prefixes = out
        return self._prefixes

    def holds_title(self, title: str) -> bool:
        """Whether an entity (a document, an action item) has the title, both read as ``squash`` reads them, or any text holds
        it (``holds_text``)."""
        if self._titles is None:
            self._titles = {squash(n) for e, n in self.bank.names.items() if n and not e.startswith("person:")}
        return squash(title) in self._titles or self.holds_text(title)

    def titles_asked(self, question: str) -> list[str]:
        """The quoted strings the question gives as a document's title: next to a word such as "document", "page" or "meeting"
        ('the Confluence page "X"', 'the "X" meeting', 'the issue titled "X"')."""
        out = []
        for m in QUOTED.finditer(question):
            inner = m.group(0)[1:-1].strip()
            if len(inner) < 3:
                continue
            before = re.findall(r"[a-z]+", question[:m.start()].lower())
            while before and before[-1] in TITLE_LEADS:
                before.pop()
            after = re.findall(r"[a-z]+", question[m.end():m.end() + 40].lower())[:1]
            if (before and before[-1] in TITLE_NOUNS) or (after and after[0] in TITLE_NOUNS):
                out.append(inner)
        return out

    def person_names(self) -> tuple[set[str], set[str]]:
        """The first and the last words of the bank's people's full names, lower case."""
        if self._names is None:
            full = [n.lower().split() for e, n in self.bank.names.items() if e.startswith("person:") and len(n.split()) >= 2]
            self._names = ({w[0] for w in full}, {w[-1] for w in full})
        return self._names

    def is_person_alias(self, name: str) -> bool:
        return any(e.startswith("person:") for e in self.bank.aliases.get(name.lower(), ()))

    def people_asked(self, text: str) -> list[str]:
        """The full names in a text (outside quoted titles) that look like a person's and that the bank does not hold: two or
        three capitalised words, the first a first name and the last a last name of someone in the bank, not a person's alias
        (in part: "Will Omar Singh" holds "Omar Singh") and written nowhere."""
        firsts, lasts = self.person_names()
        out = []
        for m in PERSON_SPAN.finditer(text):
            ws = [re.sub(r"['\u2019]s$", "", w) for w in m.group(0).split()]
            spans = [ws[i:j] for i in range(len(ws)) for j in range(i + 2, len(ws) + 1)]
            if any(self.is_person_alias(" ".join(s)) for s in spans):
                continue
            like = [s for s in spans if s[0].lower() in firsts and s[-1].lower() in lasts]
            if like and not any(self.holds_text(" ".join(s)) for s in like):
                out.append(" ".join(max(like, key=len)))
        return out

    def holds_key(self, key: str) -> bool:
        """Whether the bank holds a ticket key: a document's alias, a key its documents cite, or written in its text."""
        k = key.lower()
        return k in self.bank.aliases or f"key:{k}" in self.bank.kinds or self.holds_text(key)

    def missing(self, question: str) -> str | None:
        """What the question names that the bank does not hold, or None: a ticket key in a prefix the bank uses ("ticket
        ENG-123"), a pull request number ("pull request #4821", also written "PR 4821" or "PR-4821"), a quoted document title
        ('title "X"') or a person's full name ("person Jane Doe"). Anything the bank's text writes counts as held, so a
        question quoting a document's words does not fire. "PR-4821" is read as a pull request even where a document cites a
        "PR-…" key, and is held if the bank holds either."""
        text = QUOTED.sub(" ", question)
        b = self.bank
        for m in TICKET.finditer(text):
            key = m.group(0)
            if m.group(1) != "PR" and m.group(1) in self.ticket_prefixes() and not self.holds_key(key):
                return f"ticket {key}"
        for m in PR_NUMBER.finditer(text):
            n = m.group(1)
            if f"#{n}" not in b.aliases and f"pr-{n}" not in b.aliases and f"key:pr-{n}" not in b.kinds and not self.holds_text(n):
                return f"pull request #{n}"
        for title in self.titles_asked(question):
            if not self.holds_title(title):
                return f'title "{title}"'
        people = self.people_asked(text)
        return f"person {people[0]}" if people else None

    # ------------------------------------------------------------------ planning and routing
    def plan(self, question: str) -> dict[str, Any]:
        """The planner's answer, best plan, journal and top plans, the best plan's score, and whether it starts from something
        the question names."""
        ans, best, journal, top = plan_answer(self.bank, self.lessons, question, self.planner)
        return {"answer": ans, "best": best, "journal": journal, "top": top, "score": float(top[0][0]) if top else 0.0,
                "start_named": best is not None and self.planner.start_named(best, question)}

    def signals(self, question: str, plan: dict[str, Any] | None = None) -> dict[str, float]:
        """What the router reads: ``bias``, the signals of ``SIGNALS`` and the question's words (``w:<stem>``)."""
        plan = plan if plan is not None else self.plan(question)
        ql = unquoted(question.lower())
        kind = Planner.interrogative_kind(question)
        rw = raw_words(question)
        sig = {"bias": 1.0, "start_named": float(plan["start_named"]), "names": float(bool(self.planner.about(question))),
               "has_id": float(bool(TICKET.search(question) or PR_NUMBER.search(question))), "quoted": float(bool(QUOTED.search(question))),
               "plan_score": plan["score"], "plan_high": float(plan["score"] >= 0.5), "who": float(kind == "person"),
               "when": float(kind == "date"), "how_many": float(kind == "count"), "field_word": float(asks_field(question)),
               "keys": float(bool(set(rw) & KEY_WORDS)), "list": float(Planner.asks_several(question)),
               "what_is_the": float(bool(WHAT_IS_THE.search(ql))), "how_do": float(bool(HOW_DO.search(ql))),
               "why": float("why" in rw), "what_caused": float(bool(WHAT_CAUSED.search(ql))), "long": min(1.0, len(rw) / 40)}
        sig.update({"w:" + w: 1.0 for w in question_words(question)})
        return sig

    def reads_asked_field(self, question: str, plan: dict[str, Any]) -> bool:
        """Whether the best plan reads what the question asks for. A plan that follows a link, lists, counts, orders or gives
        an item does. A plain read of one field of the named thing does unless v1's engine reads the question as asking for
        another field the thing has (``FactBank.wanted``: its cue words and field names), of the kind a plainly asked question
        word wants ("who": a person). The plan lessons learned from multi-document questions read "What is the priority of
        ENG-1?" as its assignee; v1's engine reads the priority. 'Whose document is "X"?' keeps the planner's owner, since
        the field v1 would read there (the drive area) holds no person."""
        best = plan["best"]
        if best.path or best.aggregate != "single" or best.field == "label" or len(best.starts) != 1:
            return True
        want = self.bank.wanted(question)
        if want.get(best.field, 0.0) > 0:
            return True
        kind = Planner.interrogative_kind(question)
        return not any(want.get(f["parameter"], 0.0) > 0 and (kind is None or self.kind_of(f["value"]) == kind)
                       for f in self.planner.facts(best.starts[0]) if f["parameter"] != best.field)

    def kind_of(self, value: str) -> str:
        """A field value's kind as a question word asks for it: a person, a date, a count or another value."""
        if value.lower() in self.bank.people:
            return "person"
        return "date" if ISO_DATE.match(value) else "count" if value.isdigit() else "other"

    def family_scores(self, question: str, plan: dict[str, Any]) -> dict[str, float]:
        sig = self.signals(question, plan)
        return self.router.scores(sig) if self.router is not None else Router.rule(sig)

    # ------------------------------------------------------------------ answering
    def engine(self, question: str) -> Result:
        """v1's ``FactBank.ask`` on the bank, with the brain's evidence (the answer and the facts it rests on first)."""
        self.bank.answer_first = True
        try:
            return FactBank.ask(self.bank, question, budget=self.budget)
        finally:
            self.bank.answer_first = False

    def plan_evidence(self, question: str, plan: dict[str, Any]) -> str:
        """The planner's answer and plan, every entity each hop reached with its main fields and the next plans, then the
        bank's own evidence (as ``factbank_multi.ask_plans`` writes it, the answer first)."""
        best, names = plan["best"], self.bank.names
        lines = [f"Answer: {plan['answer']}", "Plan: " + best.describe(names)]
        shown = list(best.starts) + [e for j in plan["journal"] if j.get("op") == "hop" for e in j["reached"]]
        for e in list(dict.fromkeys(shown))[:40]:
            main = {f["parameter"]: f["value"] for f in self.planner.facts(e)
                    if f["parameter"] in ("key", "pr_number", "status", "assignee", "author", "due_date", "owner")}
            lines.append(f"- {self.bank.label_of(e)}: {names.get(e, e)[:120]}" + "".join(f"; {k}: {v}" for k, v in main.items()))
        lines += [f"(other plan: {p.describe(names)} → {a})" for _, p, a in plan["top"][1:4]]
        head = "\n".join(lines)
        rest = self.bank.ask(question, budget=max(0, self.budget - len(head) - 2)).evidence
        return (head + "\n\n" + rest)[:self.budget]

    def prose(self, question: str) -> tuple[str, str, str]:
        """The answer quoted from the best passages, the reason, and the passages as evidence (text first, within the budget)."""
        from cie.retrieval.answer import quote_answer

        ps = self.bank.passages(question, budget=self.budget, size=PROSE_SIZE)
        items = [{"id": f"{p['doc']}:{i}", "kind": "passage", "summary": p["title"], "detail": p["text"], "document_id": p["doc"],
                  "score": p["score"]} for i, p in enumerate(ps)]
        quoted = quote_answer(items, question) if items else None
        blocks, used = [], 0
        for p in ps:
            block = f"[passage] {p['title']}\n{p['text']}"
            if used + len(block) > self.budget:
                break
            blocks.append(block)
            used += len(block) + 2
        if quoted is None:
            return "not found", "no passage sentence holds a word of the question", "\n\n".join(blocks)
        docs = list(dict.fromkeys(c["document_id"] for c in quoted[1]))
        return quoted[0], f"quoted from {len(quoted[1])} passage(s) of {len(docs)} document(s): {', '.join(docs)}", "\n\n".join(blocks)

    def ask(self, question: str) -> dict[str, Any]:
        """The brain's answer: {answer, route, reason, evidence, reads, journal, family_scores, ms}. ``route`` is 'not_found',
        'plan', 'fact' or 'prose'; ``reads`` is what the plan read when the planner answered (``Planner.reads``). The journal
        starts with the route; then comes the plan's journal, or the engine's steps the answer rests on (``rests_on``)."""
        t = time.perf_counter()

        def done(answer: str, route: str, reason: str, evidence: str, journal: list, reads: Any = None,
                 scores: dict[str, float] | None = None) -> dict[str, Any]:
            head = {"op": "route", "route": route, "reason": reason, **({"family_scores": scores} if scores else {})}
            return {"answer": answer, "route": route, "reason": reason, "evidence": evidence[:self.budget], "reads": reads or [],
                    "journal": [head, *journal], "family_scores": scores or {}, "ms": round((time.perf_counter() - t) * 1000, 2)}

        miss = self.missing(question)
        if miss:
            return done("not found", "not_found", f"the bank holds no {miss}", f"Not found: the bank holds no {miss}.", [])
        plan = self.plan(question)
        scores = self.family_scores(question, plan)
        if scores["prose"] > scores["fact"]:
            answer, reason, evidence = self.prose(question)
            return done(answer, "prose", reason, evidence, [], None, scores)
        found = plan["answer"] != "not found"
        if found and plan["start_named"] and (not self.field_check or self.reads_asked_field(question, plan)):
            return done(plan["answer"], "plan", plan["best"].describe(self.bank.names), self.plan_evidence(question, plan), plan["journal"],
                        self.planner.reads(plan["best"]), scores)
        r = self.engine(question)
        if r.answer == "not found" and found:
            return done(plan["answer"], "plan", plan["best"].describe(self.bank.names) + " (the engine found nothing)",
                        self.plan_evidence(question, plan), plan["journal"], self.planner.reads(plan["best"]), scores)
        return done(r.answer, "fact", r.reason, r.evidence, rests_on(r.journal, r.answer), None, scores)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def ask_brain(work: Path, single: Path, plans: Path, name: str = "factbank_v15", router: Router | str | Path | None = None,
              budget: int = BUDGET, field_check: bool = True) -> dict[str, Any]:
    """The brain's answers to ``work/questions.jsonl`` from ``work/factbank_v2.sqlite``, written to ``work/<name>.jsonl`` as
    rows {id, answer, route, reason, evidence, ms, reads, journal, family_scores}. ``router`` is a Router or its file."""
    work = Path(work)
    if isinstance(router, (str, Path)):
        router = Router.load(router)
    brain = Brain(work / "factbank_v2.sqlite", single, plans, router, budget=budget, field_check=field_check)
    rows = []
    for q in _jsonl(work / "questions.jsonl"):
        r = brain.ask(q["question"])
        rows.append({"id": q["id"], **{k: r[k] for k in ("answer", "route", "reason", "evidence", "ms", "reads", "journal", "family_scores")}})
    (work / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    ms = sorted(r["ms"] for r in rows)
    return {"questions": len(rows), "written": f"{name}.jsonl", "routes": dict(Counter(r["route"] for r in rows)),
            "median_ms": ms[len(ms) // 2] if ms else None, "mean_ms": round(math.fsum(ms) / len(ms), 1) if ms else None}


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="python -m cie.factbank.brain")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="answer a work folder's questions")
    a.add_argument("--work", type=Path, required=True)
    a.add_argument("--single", type=Path, required=True, help="the single-fact lessons (cie.factbank.learn)")
    a.add_argument("--plans", type=Path, required=True, help="the plan lessons (cie.factbank.plans)")
    a.add_argument("--router", type=Path, default=None, help="a trained Router; the rule when left out")
    a.add_argument("--name", default="factbank_v15")
    a.add_argument("--budget", type=int, default=BUDGET)
    a.add_argument("--no-field-check", action="store_true", help="the planner answers every question that names its start")
    args = ap.parse_args(argv)
    rep = ask_brain(args.work, args.single, args.plans, args.name, args.router, args.budget, not args.no_field_check)
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
