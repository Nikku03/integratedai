"""Questions whose answer is spread over several documents: plans over the fact bank, carried out one hop at a time.

A **plan** has four parts:
1. **Start:** the entities the question names (an issue key, a pull request number, a person), or the documents it
   describes.
2. **Path:** the relations to follow. Each hop follows the facts that point from one entity to another, such as a pull
   request's ``linked_linear`` to the Linear issue, or a person's ``assignee_of`` to their issues. Each entity
   reached is written down before the next hop, as in the cell engine.
3. **Field:** what to read on the entities reached: a field (``assignee``, ``due_date``, ``status``…) or their label
   (issue key, pull request number, title).
4. **Combine:** one value, a list, a count, the earliest or the latest (by a date field).

Every plan the bank allows is enumerated: starts × paths of up to two hops × fields × ways to combine. Each one is
carried out, and learned weights (``learn_plans``) pick one. The weights cover:
- how well the relation and field names match the question's words, and their learned associations;
- whether the kind of answer fits the question;
- a learned association between question words and the way to combine;
- the clue rule: an answer the question already contains is not the answer.

Nothing learned is a value from the training documents.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

import numpy as np

from cie.factbank.engine import STOP, SYSTEM_WORDS, stem, words
from cie.factbank.learn import Assoc, dot, fit, norm, question_kind, sigmoid, tokens_of

AGGS = ("single", "list", "count", "earliest", "latest")
TYPE_TOKENS = ("who", "when", "state", "num")  # cie.factbank.lexicon.TYPES
HOW_MANY = re.compile(r"\bhow many\b", re.I)
KEY_OR_NUMBER = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{2,7}\b|#?\b\d+\b")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# v11 (docs/FACTBANK_TICKET_PREREGISTRATION.md): "ticket" or "issue" means an item in a ticket tracker, Linear or Jira, when
# the question names no tracker. "ticket" is then a system of its own that Linear and Jira items belong to.
TICKET_WORD = re.compile(r"\b(?:tickets?|issues?)\b", re.I)
TICKET_SYSTEMS = frozenset({"linear", "jira"})
TICKET_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{1,7}$")
# v13 (docs/FACTBANK_ORDER_PREREGISTRATION.md): a question that asks for several things ("which tickets are assigned to them?
# ticket keys please", "list the IDs") is not answered with the first or the last one by a date, unless it also asks for one
# thing ("which of", "which one", "which ticket") or uses a word of order ("next", "soonest", "most urgent"). Words are read
# as written, outside quoted titles; plurals are not stemmed away.
MANY_WORDS = frozenset(("list", "lists", "listing", "enumerate", "itemize", "keys", "ids", "identifiers", "numbers", "all", "every",
                        "each"))
MANY_ITEMS = frozenset(("tickets", "issues", "ones", "items", "tasks", "bugs", "cards", "jiras"))
ONE_ITEMS = frozenset(("ticket", "issue", "one", "item", "task", "bug", "card", "jira"))
ORDER_WORDS = frozenset(("first", "1st", "next", "earliest", "earlier", "soonest", "sooner", "nearest", "nearer", "closest", "closer",
                         "last", "latest", "later", "final", "oldest", "newest", "recent", "urgent", "overdue", "tightest", "pressing",
                         "top", "asap", "upcoming", "prior", "priority"))
NOT_ORDER_AFTER = {"next": frozenset(("meeting", "meetings", "call", "calls", "week", "month", "quarter", "sprint", "sync", "standup",
                                      "review", "time", "step", "steps", "year", "day", "1"))}
# v15 (the company brain, ``brain``): a question word that opens a clause says what kind of answer is asked for, when it asks
# plainly (Planner.interrogative_kind); "what" or "which" asks for a date only before a date word, and for a count only before
# "number of" (not "the number of the pull request", which asks for one item's number)
QUESTION_WORDS = frozenset(("who", "whom", "whose", "when", "how", "what", "which", "where", "why"))
CLAUSE_OPENERS = frozenset(("and", "but", "so", "then", "also"))
PREPOSITIONS = frozenset(("by", "until", "till", "since", "on", "at", "to", "for", "from"))
DATE_NOUNS = frozenset(("date", "dates", "day", "days", "deadline", "deadlines"))
BEFORE_NOUN = frozenset(("is", "was", "s", "the", "its", "their", "exact", "target", "expected", "planned", "final", "due", "total"))
ONE_ITEM = frozenset(("the", "that", "this", "its"))
ASKS_COUNT = re.compile(r"\bhow many\b|\bnumber of\b(?!\s+(?:the|that|this|its)\b)|\bcount\b", re.I)
QUOTED = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d')
# v15 (``brain``): words that make a "person" a team, a group or a role ("Customer Success", "People Ops", "Recorder Bot"); documents'
# owner fields hold them as if they were people's names, and a question naming one is not about a person
TEAM_NAME = re.compile(r"\b(?:teams?|ops|operations|success|engineering|support|sales|security|finance|people|product|platform|infra|"
                       r"infrastructure|marketing|legal|customers?|group|council|committee|department|staff|bot|recorder|notetaker|"
                       r"assistant|org|squad|rotation|leads?|growth|everyone|unknown|research|devrel|partnerships?|enablement)\b")
# v15 (``brain``, check 7): words that ask to follow a link from what the question names ("the ticket linked to PR #4821", "its
# assignee", "whoever took it", "ENG-1 is tied to another ticket"); a question without one is answered from the named thing
# itself when a plan can
LINK_WORDS = frozenset(("link", "links", "linked", "linking", "reference", "references", "referenced", "referencing", "ref", "refs",
                        "other", "another", "parent", "child", "children", "blocked", "blocks", "blocking", "blocker", "depend",
                        "depends", "dependent", "dependency", "dependencies", "related", "behind", "attached", "connected", "connects",
                        "connection", "tied", "ties", "points", "pointing", "pointed", "mentions", "mentioned", "mentioning",
                        "associated", "corresponding", "underlying", "its", "whoever", "someone", "somebody"))
LINK_PHRASES = re.compile(r"\bowner of\b|\bperson who\b|\bthe one that\b|\bthat (?:one|ticket|issue|pr|person)\b|\bgoes? with\b|"
                          r"\bwent to\b|\bworked on in\b")

NOT_LINKS = {"from_document"}
FEATURES = ["bias", "start_named", "start_rank", "two_starts", "path_len", "path_overlap", "path_assoc", "field_overlap", "field_assoc",
            "kind_fits", "kind_conflicts", "combine_assoc", "label_field", "answer_in_question", "fanout"]
# v4 (after the first test, docs/FACTBANK_MULTI_RESULTS.md): the clue rule split by whether the question offers a choice, the
# kind of answer learned from the question's words instead of fixed patterns, and whether the answer comes from the system the
# question names
# v5 (docs/FACTBANK_WORDS_PREREGISTRATION.md) has v4's features. What changes is the words they are computed from: with
# word meanings learned from the company's documents (cie.factbank.lexicon), a question word brings the kinds of value it
# goes with, and a word no training question used borrows the known words and field-name words nearest it (Planner.enrich).
FEATURES_V4 = ["bias", "start_named", "start_rank", "two_starts", "path_len", "path_overlap", "path_assoc", "field_overlap", "field_assoc",
               "kind_assoc", "combine_assoc", "label_field", "answer_named_choice", "answer_named_clue", "system_fits", "fanout"]
FEATURES_V5 = FEATURES_V4


@dataclass(frozen=True)
class Plan:
    starts: tuple[str, ...]
    path: tuple[str, ...]
    field: str
    aggregate: str
    system: str = ""
    status: tuple[str, ...] = ()

    def describe(self, names: dict[str, str]) -> str:
        s = " + ".join(names.get(e, e) for e in self.starts)
        hops = "".join(f" → {r}" for r in self.path)
        filt = (f" [{self.system}]" if self.system else "") + (f" [status {', '.join(self.status)}]" if self.status else "")
        return f"{s}{hops}{filt} → {self.field} → {self.aggregate}"


class Planner:
    """``rules="v4"`` (after the first test): every hop must reach something new, no plan walks or reads straight back the way it
    came or answers with only what it started from or passed through, and "one value" needs every entity reached to agree on it.
    ``"v3"`` is the planner as first tested.

    ``brain`` (v15, the company brain) changes these things, all off by default: a plainly asked question word ("who", "when",
    "how many") overrides the learned kind of answer (``asked_kind``); a question asking for several things gets no count unless
    it asks for one (``check``, 5b); a person named only by a one-word alias does not say what the question is about
    (``named_fully``); a question that names something and asks for no link is answered without a hop when it can be
    (``check``, 7); and, when the bank reads system words as whole words (``FactBank.whole_system_words``), so does the
    planner (``systems_named``)."""

    def __init__(self, bank, rules: str = "v3", lexicon=None, known: list[str] | None = None, general=None, combine: str = "company",
                 floor: float = 0.5, brain: bool = False):
        self.b = bank
        self.rules = rules
        self.lex = lexicon  # v5: learned word meanings (cie.factbank.lexicon.Lexicon)
        self.known = sorted(known or [])  # the words the training questions used
        self.general = general  # v6: word meanings counted over general English (a Lexicon with no value kinds)
        self.combine = combine  # v6: how a lender's closeness is read: "company", "general", "max" or "mean" of the two spaces
        self.floor = floor  # how close a known word must be to lend its meaning
        self.glossary = None  # v8: cie.factbank.reader.Glossary, everyday phrases written once by a large language model
        self.tickets = False  # v11: "ticket" or "issue" means a Linear or Jira item (TICKET_WORD)
        self.orders = False  # v13: a question asking for several things gets no first or last by a date (asks_several, check 5)
        self.brain = brain  # v15: question words over the learned kind, no count for several things, no one-word person aliases
        self._person_aliases: dict[str, list[str]] | None = None
        self._facts: dict[str, list] = {}
        self._expanded: dict[frozenset, dict[str, float]] = {}

    def enrich(self, ws: set[str], plain: set[str], floor: float | None = None, type_floor: float = 0.1) -> dict[str, float]:
        """v5: the question's words (weight 1), plus for each plain word the kinds of value it goes with ("zzwhen" for a
        word about dates), and, for a word no training question used, the known words and field-name words nearest it in
        meaning."""
        floor = self.floor if floor is None else floor
        key = frozenset(ws) | {f"\0enrich {floor} {type_floor} {self.combine}"}  # the settings are part of the key
        if key not in self._expanded:
            out = dict.fromkeys(ws, 1.0)
            known = set(self.known)
            lenders = sorted(known | self.field_words())
            for w in ws & plain:
                for t in TYPE_TOKENS:
                    sc = self.lex.kind_of(w, t)
                    if sc >= type_floor:
                        out["zz" + t] = max(out.get("zz" + t, 0.0), sc)
                if w not in known:
                    for n, sim in self.lenders(w, lenders, 3, floor):
                        out[n] = max(out.get(n, 0.0), sim)
            self._expanded[key] = out
        return self._expanded[key]

    def lenders(self, w: str, among: list[str], k: int, floor: float) -> list[tuple[str, float]]:
        """The known words nearest ``w``, by the company's word space, general English's (v6), or both."""
        if self.general is None or self.combine == "company":
            return self.lex.space.neighbours(w, among, k, floor)
        if self.combine == "general":
            return self.general.space.neighbours(w, among, k, floor)
        sc = []
        for n in among:
            if n == w:
                continue
            a = self.lex.space.sim(w, n) if w in self.lex.space.ix and n in self.lex.space.ix else None
            b = self.general.space.sim(w, n) if w in self.general.space.ix and n in self.general.space.ix else None
            have = [x for x in (a, b) if x is not None]
            if have:
                sc.append((n, max(have) if self.combine == "max" else sum(have) / len(have)))
        sc.sort(key=lambda x: -x[1])
        return [(n, v) for n, v in sc[:k] if v >= floor]

    def glossary_words(self, question: str) -> tuple[set[str], set[str]]:
        if not hasattr(self, "_glossary_cache"):
            self._glossary_cache: dict[str, tuple[set[str], set[str]]] = {}
        if question not in self._glossary_cache:
            self._glossary_cache[question] = self.glossary.words(question)
        return self._glossary_cache[question]

    def field_words(self) -> set[str]:
        """The words of the bank's own field and relation names (``due_date`` gives "due" and "date"): a new word may borrow
        their meaning too."""
        if not hasattr(self, "_field_words"):
            params = [r[0] for r in self.b.con.execute("SELECT DISTINCT parameter FROM facts")]
            self._field_words = {t for p in params if not p.startswith("text_") for t in tokens_of(p[:-3] if p.endswith("_of") else p)}
        return self._field_words

    def plain_words(self, question: str) -> set[str]:
        """The words that may lend their meaning: outside quoted titles, keys and numbers, not a named person's name, and not
        a word too common to mean anything on its own (the engine's stop words)."""
        text = KEY_OR_NUMBER.sub(" ", re.sub(r'"[^"]*"', " ", question))
        names = {t for e in self.b.named(question) if e.startswith("person:") for t in words(self.b.names.get(e, ""))}
        return {w for w in words(text) if w not in names and w not in STOP}

    def facts(self, e: str) -> list:
        if e not in self._facts:
            self._facts[e] = self.b.facts_of(e)
        return self._facts[e]

    def links(self, e: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for f in self.facts(e):
            if f["value_entity"] and f["parameter"] not in NOT_LINKS and f["value_entity"] in self.b.kinds:
                out[f["parameter"]].append(f["value_entity"])
        return out

    def follow(self, starts: tuple[str, ...], path: tuple[str, ...], journal: list | None = None) -> list[str]:
        frontier = list(dict.fromkeys(starts))
        for hop, rel in enumerate(path, 1):
            nxt = []
            for e in frontier:
                nxt += self.links(e).get(rel, [])
            frontier = list(dict.fromkeys(nxt))
            if journal is not None:
                journal.append({"op": "hop", "hop": hop, "relation": rel, "reached": frontier[:50]})
        return frontier

    def field_values(self, e: str, field: str) -> list[str]:
        if field == "label":
            return [self.b.label_of(e)]
        return list(dict.fromkeys(f["value"] for f in self.facts(e) if f["parameter"] == field))

    def execute(self, plan: Plan, journal: list | None = None) -> str | None:
        ents = self.follow(plan.starts, plan.path, journal)
        if plan.system:
            ents = [e for e in ents if self.in_system(e, plan.system)]
        if plan.status:
            want = {s.lower() for s in plan.status}
            ents = [e for e in ents if {v.lower() for v in self.field_values(e, "status") + self.field_values(e, "state")} & want]
        if not ents:
            return None
        if plan.aggregate == "count":
            return str(len(ents))
        if plan.aggregate == "list":
            return ", ".join(sorted(self.b.label_of(e) for e in ents))
        if plan.aggregate in ("earliest", "latest"):
            dated = [(v, e) for e in ents for v in self.field_values(e, plan.field)[:1] if ISO.match(v)]
            if len(dated) < 2:
                return None
            dated.sort()
            pick = dated[0] if plan.aggregate == "earliest" else dated[-1]
            if sum(1 for v, _ in dated if v == pick[0]) > 1:
                return None  # a tie: no single answer
            return self.b.label_of(pick[1])
        if self.rules in ("v4", "v9"):
            vals = list(dict.fromkeys(v for e in ents for v in self.field_values(e, plan.field)))
            return vals[0] if len(vals) == 1 else None  # several different values: not one answer
        vals = self.field_values(ents[0], plan.field)
        return ", ".join(vals) if vals else None

    def ends(self, plan: Plan) -> list[str]:
        """The entities a plan ends at, after its system and status filters (as ``execute`` reads them)."""
        ents = self.follow(plan.starts, plan.path)
        if plan.system:
            ents = [e for e in ents if self.in_system(e, plan.system)]
        if plan.status:
            want = {s.lower() for s in plan.status}
            ents = [e for e in ents if {v.lower() for v in self.field_values(e, "status") + self.field_values(e, "state")} & want]
        return ents

    def reads(self, plan: Plan) -> dict[str, list[str]]:
        """v9: what carrying out a plan reads, by role (normalised): the labels of the entities it ends at (what it answers
        about, counts or lists), the values of its field on them, and the names of the people it starts from or passes
        through (an action item's owner)."""
        passed = list(dict.fromkeys(list(plan.starts) + [e for i in range(1, len(plan.path)) for e in self.follow(plan.starts, plan.path[:i])]))
        ends = self.ends(plan)
        values = [v for e in ends for v in self.field_values(e, plan.field)] if plan.field != "label" else []
        out = {"ends": [self.b.label_of(e) for e in ends], "values": values,
               "people": [self.b.names.get(e, "") for e in passed + ends if e.startswith("person:")]}
        return {k: list(dict.fromkeys(norm(x) for x in v if x)) for k, v in out.items()}

    def kind9(self, plan: Plan, answer: str) -> str:
        """v9: the kind of answer, where a person's label (``assignee → label``) is a person, not an item's key. ``out_kind``
        is kept as it was for the v4 to v8 features."""
        if plan.field == "label" and plan.aggregate in ("single", "list") and all(v.lower() in self.b.people for v in answer.split(", ")):
            return "person"
        return self.out_kind(plan, answer)

    def candidates(self, question: str, max_len: int = 2) -> list[tuple[Plan, dict[str, Any]]]:
        """Every plan the bank allows for the question, with what carrying it out gives."""
        named = [e for e in self.b.named(question) if e in self.b.kinds]
        content = [c["entity"] for c in self.b.entity_candidates(question)[:3]]
        starts: list[tuple[tuple[str, ...], dict[str, float]]] = []
        for e in dict.fromkeys(named):
            starts.append(((e,), {"named": 1.0, "rank": 1.0}))
        things = [e for e in dict.fromkeys(named) if not e.startswith("person:")]
        if len(things) == 2:
            starts.append((tuple(things), {"named": 1.0, "rank": 1.0}))
        for i, e in enumerate(content):
            if e not in named:
                starts.append(((e,), {"named": 0.0, "rank": 1.0 / (1 + i)}))
        ql = question.lower() + " "
        if self.whole_words():
            system = (self.b.named_systems(question) or [""])[0]
        else:
            system = next((s for w, s in SYSTEM_WORDS.items() if w in ql), "")
        systems = self.systems_named(question)
        quoted = re.findall(r"\"([^\"]+)\"", question)
        out = []
        for st, meta in starts:
            if self.rules == "v9":
                system = self.target_system(systems, st)
                if system == "ticket" and "ticket" in self.own_systems(st):
                    system = ""  # v11: a question that starts from a ticket and names no other system asks about no system, as in v9
            paths: list[tuple[str, ...]] = [()]
            frontier1 = {}
            for e in st:
                for rel, ts in self.links(e).items():
                    frontier1.setdefault(rel, []).extend(ts)
            for rel, ts in frontier1.items():
                paths.append((rel,))
                if max_len >= 2:
                    rels2 = set()
                    for t in dict.fromkeys(ts):
                        rels2 |= set(self.links(t))
                    paths += [(rel, r2) for r2 in sorted(rels2)]
            if self.rules in ("v4", "v9"):
                paths = [p for p in paths if not (len(p) == 2 and inverse(p[0], p[1]))]
            for path in paths:
                ents = self.follow(st, path)
                if not ents:
                    continue
                came_from = set(st) | {e for i in range(1, len(path)) for e in self.follow(st, path[:i])}
                echo = {self.b.label_of(e) for e in came_from}
                if self.rules in ("v4", "v9") and path and set(ents) <= came_from:
                    continue  # the last hop reached nothing new
                sys_f = system if system and any(self.in_system(e, system) for e in ents) else ""
                statuses = {v for e in ents[:30] for v in self.field_values(e, "status")}
                stat_f = tuple(q for q in quoted if q in statuses)
                fields = {"label"} | {f["parameter"] for e in ents[:5] for f in self.facts(e)
                                      if not f["parameter"].endswith("_of") and not f["parameter"].startswith("text_")
                                      and f["parameter"] not in ("referenced_by", "action_item")}
                if self.rules in ("v4", "v9") and path:
                    back = {f["parameter"] for e in ents[:5] for f in self.facts(e) if f["value_entity"] in came_from}
                    fields = {f for f in fields if not inverse(path[-1], f) and f not in back}  # no reading back where it came from
                for field in sorted(fields):
                    dated = any(ISO.match(v) for e in ents[:5] for v in self.field_values(e, field)[:1])
                    for agg in AGGS:
                        if agg in ("list", "count") and field != "label":
                            continue
                        if agg in ("earliest", "latest") and not dated:
                            continue
                        if agg == "single" and len(st) > 1:
                            continue
                        if self.rules == "v9" and agg in ("count", "list") and self.one_by_construction(st, path):
                            continue  # counting or listing what can only be one thing
                        plan = Plan(st, path, field, agg, sys_f, stat_f)
                        ans = self.execute(plan)
                        if ans is None:
                            continue
                        if self.rules in ("v4", "v9") and agg in ("single", "list") and set(ans.split(", ")) <= echo:
                            continue  # only names what it started from or passed through
                        out.append((plan, {**meta, "answer": ans, "fanout": len(ents)}))
        return out

    def titled(self, question: str) -> list[str]:
        """v9: the things a quoted title in the question names: the entities whose name is exactly that title."""
        if not hasattr(self, "_titles"):
            self._titles: dict[str, list[str]] = defaultdict(list)
            for e, name in self.b.names.items():
                if e in self.b.kinds and not e.startswith("person:") and name:
                    self._titles[norm(name)].append(e)
        return list(dict.fromkeys(e for qt in re.findall(r'"([^"]+)"', question) for e in self._titles.get(norm(qt), [])))

    def target_system(self, systems: list[str], starts: tuple[str, ...]) -> str:
        """v9: the system the question asks about. A question that names two systems starts in one and asks about the other
        ("who opened the GitHub pull request that references Linear issue ENG-1?" asks about GitHub); one that names only the
        start's own system asks about that one."""
        own = self.own_systems(starts)
        return next((s for s in systems if s not in own), systems[0] if systems else "")

    @classmethod
    def wants_several(cls, question: str) -> bool:
        """v13: check 5 acts: the question asks for several things, not for one thing, and uses no word of order."""
        return cls.asks_several(question) and not cls.asks_one(question) and not cls.asks_order(question)

    @staticmethod
    def asks_several(question: str) -> bool:
        """v13: the question asks for several things: it says "list", "all", "each" or "every", asks for "keys" or "IDs", or asks
        "which tickets", "what Linear issues" or "what are"."""
        w = raw_words(question)
        if set(w) & MANY_WORDS:
            return True
        for i, x in enumerate(w):
            if x in ("which", "what"):
                n = w[i + 1:i + 3]
                if n and (n[0] in ("are", "were") or n[0] in MANY_ITEMS):
                    return True
                if len(n) == 2 and n[0] not in ("of", "one") and n[1] in MANY_ITEMS:
                    return True
        return False

    @staticmethod
    def asks_one(question: str) -> bool:
        """v13: the question asks for one thing: "which of", "which one", "which ticket", "which Linear issue", "just one", "the
        top one", "a single"."""
        w = raw_words(question)
        for i, x in enumerate(w):
            n = w[i + 1:i + 4]
            if x == "which" and n and n[0] in ("of", "one"):
                return True
            if x == "which" and n and (n[0] in ONE_ITEMS or len(n) > 1 and n[1] in ONE_ITEMS and n[0] != "of"):
                k = 0 if n[0] in ONE_ITEMS else 1
                if k + 1 >= len(n) or n[k + 1] not in MANY_WORDS | MANY_ITEMS:
                    return True
            if x in ("just", "only", "top") and n and n[0] == "one" or x == "single":
                return True
        return False

    @staticmethod
    def asks_order(question: str) -> bool:
        """v13: the question uses a word of order ("next", "soonest", "most urgent", ``ORDER_WORDS``), or "before" or "ahead of"
        the others, the rest or anything else. "next" before a meeting, a call or a week is not one."""
        w = raw_words(question)
        for i, x in enumerate(w):
            if x in ORDER_WORDS and (i + 1 >= len(w) or w[i + 1] not in NOT_ORDER_AFTER.get(x, ())):
                return True
            if x in ("before", "ahead") and set(w[i + 1:i + 4]) & {"others", "other", "rest", "else", "anything", "everything"}:
                return True
        return False

    @staticmethod
    def interrogative_kind(question: str) -> str | None:
        """v15: the kind of answer the question words ask for, when they ask plainly: "who", "whom" or "whose" a person;
        "when", "what date" or "what is the due date" a date; "how many" or "what is the number of" a count. Only a question
        word that opens a clause counts (at the start, after punctuation, or after "and"), alone or after a preposition that
        does ("By when", "on what date", "to whom"), so "the person who took it" asks nothing. Any other question word opening
        a clause ("which ticket", "what is the status", "where"), or two that disagree, leaves the kind open (None). "Which
        deadline is sooner?", "whose due date is earlier?", "what is the deadline of the next one?" and "what is the number
        of the pull request?" ask for an item, so they leave it open too."""
        toks = re.findall(r"[a-z0-9]+|[,:;.?!()\u2014\u2013]|(?<=\s)-(?=\s)", unquoted(question.lower()))

        def opens(j: int) -> bool:
            return j == 0 or not toks[j - 1][0].isalnum() or toks[j - 1] in CLAUSE_OPENERS

        kinds = []
        for i, t in enumerate(toks):
            if t not in QUESTION_WORDS or not (opens(i) or toks[i - 1] in PREPOSITIONS and opens(i - 1)):
                continue
            nxt = toks[i + 1:i + 7]
            if t in ("who", "whom"):
                kinds.append("person")
            elif t == "whose":
                kinds.append(None if set(nxt[:3]) & (DATE_NOUNS | {"due"}) else "person")
            elif t == "when":
                kinds.append("date")
            elif t == "how":
                kinds.append("count" if nxt[:1] == ["many"] else None)
            elif t == "what":
                rest = list(nxt)
                while rest and rest[0] in BEFORE_NOUN:
                    rest.pop(0)
                if rest[:1] and rest[0] in DATE_NOUNS and not Planner.asks_order(question):
                    kinds.append("date")
                else:
                    kinds.append("count" if rest[:2] == ["number", "of"] and not set(rest[2:3]) & ONE_ITEM else None)
            else:
                kinds.append(None)
        return kinds[0] if kinds and len(set(kinds)) == 1 else None

    def asked_kind(self, question: str, learned: str | None) -> str | None:
        """The kind of answer check 4 uses: the learned one (``AskedKind``). With ``brain`` (v15), a kind the question words ask
        for plainly (``interrogative_kind``) replaces a learned one that differs, and fills in when the lessons are not sure."""
        return (self.interrogative_kind(question) or learned) if self.brain else learned

    def named_fully(self, question: str) -> list[str]:
        """v15: the entities the question names (``bank.named``), without a person named only by a one-word alias ("Priya",
        "Redwood"): among thousands of documents, a first name, or a word that is also somebody's name, does not say who the
        question is about. A full name still counts, unless it is a team's or a role's ("Customer Success", "People Ops"), which
        documents' owner fields hold as if it were a person's (``TEAM_NAME``)."""
        if self._person_aliases is None:
            self._person_aliases = defaultdict(list)
            for alias, ents in self.b.aliases.items():
                if len(alias.split()) > 1:
                    for e in ents:
                        if e.startswith("person:"):
                            self._person_aliases[e].append(alias)
        q = question.lower()

        def full(e: str) -> bool:
            return any(len(a) >= 4 and re.search(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", q) for a in self._person_aliases.get(e, ()))

        return [e for e in self.b.named(question) if not e.startswith("person:") or (full(e) and not TEAM_NAME.search(e[7:]))]

    def about(self, question: str) -> set[str]:
        """v15: what the question is about for check 1 with ``brain``: the entities it names (``named_fully``) and its quoted
        titles."""
        return {e for e in self.named_fully(question) if e in self.b.kinds} | set(self.titled(question))

    def start_named(self, plan: Plan, question: str) -> bool:
        """v15: the plan starts from something the question names: a key, a pull request number, a person's full name or a
        quoted title (check 1's set, without one-word person aliases, whether or not ``brain`` is on)."""
        return bool(set(plan.starts) & self.about(question))

    def whole_words(self) -> bool:
        """v15: system words count only as whole words, as the bank reads them: ``brain`` and the bank's
        ``whole_system_words``."""
        return self.brain and bool(getattr(self.b, "whole_system_words", False))

    @staticmethod
    def asks_link(question: str) -> bool:
        """v15: the question asks to follow a link from what it names: a word such as "linked", "parent", "blocks", "its" or
        "whoever" (``LINK_WORDS``), or "owner of", "person who" or "the one that", outside quoted titles."""
        w = raw_words(question)
        return bool(set(w) & LINK_WORDS or LINK_PHRASES.search(" ".join(w)))

    def systems_named(self, question: str) -> list[str]:
        """The systems a question names, in the order of ``SYSTEM_WORDS``. With ``tickets`` (v11), "ticket" or "issue" also
        names the ticket trackers, after any system named by name, so "the Linear ticket" still asks about Linear. With
        ``whole_words`` (v15), a system word counts only as a whole word ("CI-driven" names no Google Drive)."""
        if self.whole_words():
            systems = self.b.named_systems(question)
        else:
            ql = question.lower() + " "
            systems = list(dict.fromkeys(s for w, s in SYSTEM_WORDS.items() if w in ql))
        if self.tickets and TICKET_WORD.search(question) and "ticket" not in systems:
            systems.append("ticket")
        return systems

    def in_system(self, e: str, system: str) -> bool:
        """Whether an entity belongs to a system. A Linear or Jira item belongs to "ticket" too (v11), and so does a ticket key
        the bank has no document for (``ENG-123`` named in a link), so that the filter never narrows a set of linked tickets
        to the ones that happen to have a document."""
        s = self.b.system_of_entity(e)
        if system == "ticket":
            return s in TICKET_SYSTEMS or (not s and self.b.kinds.get(e) == "identifier" and bool(TICKET_KEY.match(self.b.label_of(e))))
        return s == system

    def own_systems(self, starts: tuple[str, ...]) -> set[str]:
        """The systems the starts belong to; a Linear or Jira start is in "ticket" too (v11)."""
        own = {self.b.system_of_entity(e) for e in starts}
        return own | {"ticket"} if self.tickets and own & TICKET_SYSTEMS else own

    def one_by_construction(self, starts: tuple[str, ...], path: tuple[str, ...]) -> bool:
        """v9: a plan that can only ever reach one thing: no hop, or one start and only single-valued hops (``assignee``)."""
        return not path or (len(starts) == 1 and all(r in self.b.single for r in path))

    def check(self, question: str, cands: list[tuple[Plan, dict[str, Any]]], asked: str | None = None,
              fields: tuple[str, ...] = ()) -> list[tuple[Plan, dict[str, Any]]]:
        """v9: the plans that pass the checks. The checks apply in turn; a check that no remaining plan passes is skipped.

        1. **What the question is about:** a question that names something (a key, a pull request number, a person, a quoted
           title) is about it: the plan must start from something it names.
        2. **The system asked about:** a question that starts in one system and asks about another ("who opened the GitHub
           pull request that references Linear issue ENG-1?") is answered from the other: the plan must end there.
        3. **A choice:** a question that names two or more things to choose between is answered by comparing exactly those
           things: the plan must start from all of them and follow no link.
        4. **The kind of answer:** when the question's kind of answer is known (``asked``: a count, an item's key, a person, a
           date or another value), the plan must give that kind.
        5. **Several, not the first** (v13): when the question asks for several things, asks for no single thing and uses no
           word of order, a plan that picks the first or the last by a date is dropped (``asks_several``, ``asks_one``,
           ``asks_order``).
        5b. **Several, not how many** (v15, ``brain``): such a question that does not ask "how many", "the number of" or to
           count gets no count either.
        6. **The field** (v10, from the small model's form): a plan answering with one value must read one of ``fields``; a
           plan choosing an item by date must order by one of them.
        7. **No hop asked for** (v15, ``brain``): when the question names something and asks for no link (``asks_link``), a
           plan that follows a link from a named start is dropped if a plan that reads that start itself is still there
           ("when is the Linear issue "X" due?" reads X's due date, not that of a ticket X depends on); and of the plans from a
           named start, only those with the fewest hops stay ("the attendees of the meeting "X"" reads its attendees, not
           the meetings they attended).

        With ``brain``, check 1 leaves out a person named only by a one-word alias (``named_fully``)."""
        named = {e for e in self.b.named(question) if e in self.b.kinds and not e.startswith("person:")}
        if self.brain:
            about = self.about(question)
        else:
            about = {e for e in self.b.named(question) if e in self.b.kinds} | set(self.titled(question))
        systems = self.systems_named(question)

        def other_system(p: Plan) -> bool:
            """The question asks about a system other than the one it starts in, and the plan's answer comes from it."""
            target = self.target_system(systems, p.starts)
            return not target or target in self.own_systems(p.starts) or p.system == target

        def field_fits(p: Plan, k: str) -> bool:
            if k in ("person", "date", "other"):
                return p.field in fields
            if k == "key" and p.aggregate in ("earliest", "latest"):
                return p.field in fields or not any(f.endswith("date") for f in fields)
            return True

        several = self.orders and self.wants_several(question)
        rules = [lambda p, k: not about or bool(set(p.starts) & about),
                 lambda p, k: other_system(p),
                 lambda p, k: not (len(named) >= 2 and (p.path or set(p.starts) != named)),
                 lambda p, k: not asked or k == asked,
                 lambda p, k: not several or p.aggregate not in ("earliest", "latest"),
                 lambda p, k: not fields or field_fits(p, k)]
        if self.brain and self.wants_several(question) and not ASKS_COUNT.search(QUOTED.sub(" ", question)):
            rules.insert(5, lambda p, k: p.aggregate != "count")
        keep = cands
        for rule in rules:
            nxt = [(p, m) for p, m in keep if rule(p, self.kind9(p, m["answer"]))]
            if nxt:
                keep = nxt
        if self.brain and about and not self.asks_link(question):
            bare = {p.starts for p, _ in keep if not p.path and set(p.starts) & about}
            keep = [(p, m) for p, m in keep if not (p.path and p.starts in bare)]
            from_named = [len(p.path) for p, _ in keep if set(p.starts) & about]
            if from_named:  # no hop asked for: the shortest way from what the question names ("the attendees of the meeting")
                keep = [(p, m) for p, m in keep if not (set(p.starts) & about and len(p.path) > min(from_named))]
        return keep

    def out_kind(self, plan: Plan, answer: str) -> str:
        """The kind of answer a plan gives: a count, an item (key, number or title), a date, a person or another value."""
        if plan.aggregate == "count":
            return "count"
        if plan.aggregate in ("list", "earliest", "latest") or plan.field == "label":
            return "key"
        v = answer.split(", ")[0]
        return "date" if ISO.match(v) else ("person" if v.lower() in self.b.people else "other")

    def offers_choice(self, question: str) -> bool:
        """The question names two or more things to choose between (not people)."""
        return sum(1 for e in dict.fromkeys(self.b.named(question)) if e in self.b.kinds and not e.startswith("person:")) >= 2

    def features(self, question: str, plan: Plan, meta: dict[str, Any], rel_assoc: Assoc, agg_assoc: Assoc,
                 kind_assoc: Lift | None = None) -> dict[str, float]:
        qw = set(words(question))
        rel_toks = [tokens_of(r) for r in plan.path]
        f_toks = tokens_of(plan.field) if plan.field != "label" else set()
        qkind = "count" if HOW_MANY.search(question) else question_kind(question)
        okind = self.out_kind(plan, meta["answer"])
        fits = qkind != "other" and (qkind == okind or (qkind == "title" and okind == "key"))
        conflicts = qkind != "other" and okind != "other" and not fits
        ans = norm(meta["answer"])
        in_q = bool(len(ans) >= 3 and re.search(r"(?<!\w)" + re.escape(ans) + r"(?!\w)", norm(question)))
        choice = self.offers_choice(question) if in_q else False
        if self.lex is not None or self.glossary is not None:
            # v5/v6: associations through the words' kinds of value and, for new words, the nearest known words;
            # v8: plus the standard words of the glossary phrases the question contains
            kw = question_words(question)
            if self.lex is not None:
                plain = self.plain_words(question)
                qx, kx = dict(self.enrich(qw, plain)), dict(self.enrich(kw, plain))
            else:
                qx, kx = dict.fromkeys(qw, 1.0), dict.fromkeys(kw, 1.0)
            if self.glossary is not None:
                gq, gk = self.glossary_words(question)
                qx.update(dict.fromkeys(gq, 1.0))
                kx.update(dict.fromkeys(gk, 1.0))
            rel = lambda t: weighted(rel_assoc, qx, t)  # noqa: E731
            overlap = lambda t: sum(qx.get(x, 0.0) for x in t) / max(1, len(t))  # noqa: E731 - a borrowed word overlaps as much as it is near
            agg = weighted(agg_assoc, qx, {plan.aggregate})
            kind = weighted_lift(kind_assoc, kx, {okind}) if kind_assoc is not None else 0.0
        else:
            rel = lambda t: rel_assoc.score(qw, t)  # noqa: E731
            overlap = lambda t: len(t & qw) / max(1, len(t))  # noqa: E731
            agg = agg_assoc.score(qw, {plan.aggregate})
            kind = kind_assoc.score(question_words(question), {okind}) if kind_assoc is not None else 0.0
        return {"bias": 1.0, "start_named": meta["named"], "start_rank": meta["rank"], "two_starts": float(len(plan.starts) == 2),
                "path_len": float(len(plan.path)),
                "path_overlap": float(np.mean([overlap(t) for t in rel_toks])) if rel_toks else 0.0,
                "path_assoc": float(np.mean([rel(t) for t in rel_toks])) if rel_toks else 0.0,
                "field_overlap": overlap(f_toks), "field_assoc": rel(f_toks) if f_toks else 0.0,
                "kind_fits": float(fits), "kind_conflicts": float(conflicts), "kind_assoc": kind,
                "combine_assoc": agg, "label_field": float(plan.field == "label"),
                "answer_in_question": float(in_q), "answer_named_choice": float(in_q and choice), "answer_named_clue": float(in_q and not choice),
                "system_fits": float(bool(plan.system)),
                "fanout": math.log1p(meta["fanout"])}

    def x(self, question: str, plan: Plan, meta: dict[str, Any], rel_assoc: Assoc, agg_assoc: Assoc, kind_assoc: Lift | None = None,
          names: list[str] = FEATURES) -> list[float]:
        f = self.features(question, plan, meta, rel_assoc, agg_assoc, kind_assoc)
        return [f[n] for n in names]


def weighted(assoc: Assoc, qx: dict[str, float], ptoks: set[str]) -> float:
    """``Assoc.score`` with weighted question words: a near word counts as much as it is near."""
    if not ptoks:
        return 0.0
    tot = 0.0
    for t in ptoks:
        tot += max((wt * assoc.pair.get(w, {}).get(t, 0.0) / (assoc.word.get(w, 0.0) + 2.0) for w, wt in qx.items()), default=0.0)
    return tot / len(ptoks)


def weighted_lift(lift: Lift, qx: dict[str, float], targets: set[str]) -> float:
    """``Lift.score`` with weighted question words."""
    if not targets or lift.n <= 0:
        return 0.0
    tot = 0.0
    for t in targets:
        prior = lift.target.get(t, 0.0) / lift.n
        tot += max((wt * ((lift.pair.get(w, {}).get(t, 0.0) + 2 * prior) / (lift.word.get(w, 0.0) + 2) - prior) for w, wt in qx.items()),
                   default=0.0)
    return tot / len(targets)


def inverse(a: str, b: str) -> bool:
    """``assignee`` and ``assignee_of`` lead back to where one started."""
    return a == b + "_of" or b == a + "_of"


class Lift:
    """How much more often a question word comes with a target (a kind of answer) than targets come in general."""

    def __init__(self, d: dict[str, Any] | None = None):
        d = d or {}
        self.n = float(d.get("n", 0.0))
        self.target: dict[str, float] = defaultdict(float, d.get("target", {}))
        self.word: dict[str, float] = defaultdict(float, d.get("word", {}))
        self.pair: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for w, v in d.get("pair", {}).items():
            self.pair[w].update(v)

    def add(self, qwords: set[str], targets: set[str], sign: float = 1.0) -> None:
        self.n += sign
        for t in targets:
            self.target[t] += sign
        for w in qwords:
            self.word[w] += sign
            for t in targets:
                self.pair[w][t] += sign

    def score(self, qwords: set[str], targets: set[str]) -> float:
        if not targets or self.n <= 0:
            return 0.0
        tot = 0.0
        for t in targets:
            prior = self.target.get(t, 0.0) / self.n
            tot += max(((self.pair.get(w, {}).get(t, 0.0) + 2 * prior) / (self.word.get(w, 0.0) + 2) - prior for w in qwords), default=0.0)
        return tot / len(targets)

    def to_json(self) -> dict[str, Any]:
        return {"n": self.n, "target": dict(self.target), "word": dict(self.word),
                "pair": {w: dict(v) for w, v in self.pair.items() if any(v.values())}}


class AskedKind:
    """v9: what kind of answer a question asks for: a count, an item's key, a person, a date or another value. Learned from the
    training questions (the kind of answer their right plans give) as a Bernoulli naive Bayes over the question's words."""

    KINDS = ("count", "key", "person", "date", "other")

    def __init__(self, d: dict[str, Any] | None = None):
        d = d or {}
        self.n = float(d.get("n", 0.0))
        self.kind: dict[str, float] = defaultdict(float, d.get("kind", {}))
        self.word: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for k, v in d.get("word", {}).items():
            self.word[k].update(v)

    def add(self, qwords: set[str], kinds: set[str]) -> None:
        for k in kinds:
            self.n += 1
            self.kind[k] += 1
            for w in qwords:
                self.word[k][w] += 1

    def posterior(self, qwords: set[str]) -> dict[str, float]:
        kinds = [k for k in self.KINDS if self.kind.get(k, 0) > 0]
        if not kinds:
            return {}
        vocab = {w for k in kinds for w in self.word[k]}
        lp = {}
        for k in kinds:
            nk = self.kind[k]
            lp[k] = math.log(nk / self.n) + sum(
                math.log((self.word[k].get(w, 0.0) + 0.5) / (nk + 1)) if w in qwords else math.log(1 - (self.word[k].get(w, 0.0) + 0.5) / (nk + 1))
                for w in vocab)
        top = max(lp.values())
        z = sum(math.exp(v - top) for v in lp.values())
        return {k: math.exp(v - top) / z for k, v in lp.items()}

    def asked(self, question: str, floor: float = 0.9) -> str | None:
        """The kind of answer the question asks for, if the lessons are sure of it (posterior at least ``floor``)."""
        post = self.posterior(question_words(question))
        if not post:
            return None
        k = max(post, key=post.get)
        return k if post[k] >= floor else None

    def to_json(self) -> dict[str, Any]:
        return {"n": self.n, "kind": dict(self.kind), "word": {k: dict(v) for k, v in self.word.items()}}


def unquoted(text: str) -> str:
    """The text without its quoted titles, keeping a full stop, question mark or exclamation mark that ends one, so in
    'item "send the checklist." When is it due?' a new sentence still starts at "When"."""
    return QUOTED.sub(lambda m: " " + (m.group(0)[-2] if m.group(0)[-2] in ".?!" else "") + " ", text)


def raw_words(question: str) -> list[str]:
    """v13: the question's words as written, lower case, outside quoted titles (straight or curly double quotes). "ticket(s)"
    reads as "tickets", and "key's" or "ID's" as "keys" or "ids"."""
    q = re.sub(r'"[^"]*"|\u201c[^\u201d]*\u201d', " ", question).lower()
    q = re.sub(r"\b(key|id)['\u2019]s\b", r"\1s", re.sub(r"\(s\)", "s", q))
    return re.findall(r"[a-z0-9]+", q)


def question_words(question: str) -> set[str]:
    """Every word of the question outside quoted titles, question words included (they say what kind of answer is wanted)."""
    return {stem(w) for w in re.findall(r"[a-z]+", re.sub(r'"[^"]*"', " ", question).lower())}


@dataclass
class PlanLessons:
    weights: list[float]
    rel_assoc: dict[str, Any]
    agg_assoc: dict[str, Any]
    trained_on: dict[str, Any]
    features: list[str] = dc_field(default_factory=lambda: list(FEATURES))  # lessons saved before v4 have none: the v3 features
    kind_assoc: dict[str, Any] = dc_field(default_factory=dict)
    rules: str = "v3"
    lexicon: str = ""  # v5: the learned word meanings (a cie.factbank.lexicon file); empty before v5
    known_words: list[str] = dc_field(default_factory=list)  # v5: the training questions' plain words, which lend their meaning
    general_lexicon: str = ""  # v6: word meanings counted over general English; empty before v6
    combine: str = "company"  # v6: how the two word spaces combine
    floor: float = 0.5  # how close a known word must be to lend its meaning
    glossary: str = ""  # v8: everyday phrases written once by a large language model (a JSON list); empty before v8
    asked_kind: dict[str, Any] = dc_field(default_factory=dict)  # v9: what kind of answer a question asks for (AskedKind)
    kind_floor: float = 0.9  # v9: how sure the lessons must be of the kind of answer before the check uses it
    tickets: bool = False  # v11: "ticket" or "issue" means a Linear or Jira item; False for every earlier version
    orders: bool = False  # v13: a question asking for several things gets no first or last by a date; False before v13
    brain: bool = False  # v15: the company brain's planner fixes (Planner, ``brain``); False before v15

    def known(self) -> list[str]:
        return list(self.known_words)

    def planner(self, bank, lexicon=None, general=None) -> Planner:
        from cie.factbank.lexicon import Lexicon

        if self.lexicon and lexicon is None:
            lexicon = Lexicon.load(self.lexicon)
        if self.general_lexicon and general is None:
            general = Lexicon.load(self.general_lexicon)
        pl = Planner(bank, self.rules, lexicon if self.lexicon else None, self.known(), general if self.general_lexicon else None,
                     self.combine, self.floor, self.brain)
        if self.glossary:
            from cie.factbank.reader import Glossary

            pl.glossary = Glossary.load(self.glossary)
        pl.tickets = self.tickets
        pl.orders = self.orders
        return pl

    def assocs(self) -> tuple[Assoc, Assoc, Lift | None]:
        return (Assoc.from_json(self.rel_assoc), Assoc.from_json(self.agg_assoc),
                Lift(self.kind_assoc) if "kind_assoc" in self.features else None)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls, path: str | Path) -> PlanLessons:
        return cls(**json.loads(Path(path).read_text()))

    def describe(self) -> list[str]:
        pairs = sorted(((f, w) for f, w in zip(self.features, self.weights, strict=True) if f != "bias"), key=lambda x: -abs(x[1]))
        agg = sorted(((w, t, c) for w, d in self.agg_assoc.get("pair", {}).items() for t, c in d.items() if c > 0), key=lambda x: -x[2])[:12]
        rel = sorted(((w, t, c) for w, d in self.rel_assoc.get("pair", {}).items() for t, c in d.items() if c > 0), key=lambda x: -x[2])[:12]
        ka = Lift(self.kind_assoc)
        kind = sorted(((w, t, ka.score({w}, {t})) for w, d in ka.pair.items() for t in d), key=lambda x: -x[2])[:12]
        return ["choosing a plan: " + ", ".join(f"{f} {w:+.2f}" for f, w in pairs),
                "words → way to combine: " + ", ".join(f"'{w}'→{t}" for w, t, _ in agg),
                "words → relation/field: " + ", ".join(f"'{w}'→'{t}'" for w, t, _ in rel)] + \
            (["words → kind of answer: " + ", ".join(f"'{w}'→{t}" for w, t, _ in kind)] if kind else [])


PIECE_KEY = re.compile(r"^(?:[a-z][a-z0-9]{1,9}-\d{2,7}|#?\d{2,7})$")


def rests_on(pieces: list[str], read: dict[str, list[str]] | list[str]) -> bool:
    """v9: the plan read every fact the answer rests on (the question's pieces: the keys, values and dates it was built from),
    each in its role. A key or pull request number must be one of the things the plan ends at; any other piece (a date, a
    status, a name) must be a value of the plan's field on them, or a person the plan went through. A plan whose answer is right
    by coincidence, such as comparing two issues by when they were created when the question asks which is due first, or
    reading another ticket's assignee who happens to be the author, does not. (A flat list, as recorded before roles, counts
    for every role.)"""
    if isinstance(read, list):
        read = {"ends": read, "values": read, "people": read}

    def found(p: str, where: list[str]) -> bool:
        return any(re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", r) for r in where)

    for piece in pieces:
        p = norm(piece)
        if not p:
            continue
        if PIECE_KEY.match(p):
            if not found(p, read.get("ends", [])):
                return False
        elif not (found(p, read.get("values", [])) or found(p, read.get("people", [])) or p in read.get("ends", [])):
            return False
    return True


def matches(expected: dict[str, Any], answer: str) -> bool:
    from cie.eval.memory_test import ids_in

    if "ids" in expected:
        return ids_in(answer, expected["id_kind"]) == set(expected["ids"]) if expected["id_kind"] != "key" or answer else False
    if "date" in expected:
        return answer == expected["date"]
    vals = [expected["value"], *expected.get("alts", [])]
    return any(norm(v) == norm(answer) for v in vals)


def learn_plans(bank, questions: list[dict[str, Any]], log=print, features: list[str] = FEATURES_V4, rules: str = "v4",
                lexicon=None, lexicon_path: str = "", general=None, general_path: str = "", combine: str = "company",
                floor: float = 0.5, glossary_path: str = "", proper: bool = False, tickets: bool = False,
                orders: bool = False, brain: bool = False) -> PlanLessons:
    """Fit the plan weights on questions with answers. Associations leave each question's own share out. With a lexicon (v5),
    question words also reach the known words nearest them; with a general-English lexicon too (v6), nearness can be read
    from general English. With ``proper`` (v9), a plan counts as right only if its answer is right and it read every fact the
    answer rests on (``rests_on``), so that plans right by coincidence teach nothing."""
    pl = Planner(bank, rules, lexicon, None, general, combine, floor)
    pl.tickets = tickets
    if glossary_path:
        from cie.factbank.reader import Glossary

        pl.glossary = Glossary.load(glossary_path)
    pl.known = sorted({w for q in questions for w in pl.plain_words(q["question"])})
    per_q = []
    rel_total, agg_total, kind_total = Assoc(), Assoc(), Lift()
    asked = AskedKind()
    for q in questions:
        cands = pl.candidates(q["question"])
        right = [proper_right(pl, q, p, m) if proper else matches(q["expected"], m["answer"]) for p, m in cands]
        good = [(p, m) for (p, m), ok in zip(cands, right, strict=True) if ok]
        qw, kw = set(words(q["question"])), question_words(q["question"])
        if lexicon is not None:  # v5: the words' kinds of value join them (all training words are known: nothing is borrowed)
            plain = pl.plain_words(q["question"])
            qw, kw = qw | set(pl.enrich(qw, plain)), kw | set(pl.enrich(kw, plain))
        if pl.glossary is not None:  # v8: the glossary's standard words join them too
            gq, gk = pl.glossary_words(q["question"])
            qw, kw = qw | gq, kw | gk
        rt = set().union(*[set().union(*[tokens_of(r) for r in p.path], tokens_of(p.field) if p.field != "label" else set())
                           for p, _ in good]) if good else set()
        at = {p.aggregate for p, _ in good}
        kt = {pl.out_kind(p, m["answer"]) for p, m in good}
        kt9 = {pl.kind9(p, m["answer"]) for p, m in good}  # v9: what kind of answer the question asks for
        rel_total.add(qw, rt)
        agg_total.add(qw, at)
        kind_total.add(kw, kt)
        asked.add(question_words(q["question"]), kt9)
        per_q.append((q, cands, right, qw, kw, rt, at, kt))
    use_kind = "kind_assoc" in features
    xs, ys = [], []
    for q, cands, right, qw, kw, rt, at, kt in per_q:
        rel_total.add(qw, rt, -1.0)
        agg_total.add(qw, at, -1.0)
        kind_total.add(kw, kt, -1.0)
        for (p, m), ok in zip(cands, right, strict=True):
            xs.append(pl.x(q["question"], p, m, rel_total, agg_total, kind_total if use_kind else None, features))
            ys.append(int(ok))
        rel_total.add(qw, rt)
        agg_total.add(qw, at)
        kind_total.add(kw, kt)
    w = fit(np.array(xs, float), np.array(ys))
    les = PlanLessons(w, rel_total.to_json(), agg_total.to_json(),
                      {"questions": len(questions), "plans": len(ys), "right_plans": int(sum(ys)),
                       "questions_with_a_right_plan": sum(1 for _qq, _cands, right, *_rest in per_q if any(right)), "proper": proper},
                      list(features), kind_total.to_json() if use_kind else {}, rules, lexicon_path if lexicon is not None else "",
                      pl.known if lexicon is not None else [], general_path if general is not None else "",
                      combine if general is not None else "company", floor, glossary_path,
                      asked.to_json() if rules == "v9" else {}, 0.9, tickets, orders, brain)
    log("\n".join(les.describe()))
    return les


def proper_right(pl: Planner, q: dict[str, Any], plan: Plan, meta: dict[str, Any]) -> bool:
    return matches(q["expected"], meta["answer"]) and rests_on(q.get("pieces") or [], pl.reads(plan))


def answer(bank, lessons: PlanLessons, question: str, planner: Planner | None = None, form: dict[str, Any] | None = None
           ) -> tuple[str, Plan | None, list[dict[str, Any]], list[tuple[float, Plan, str]]]:
    """The best plan's answer, its journal, and the top plans. Pass ``planner`` (``lessons.planner(bank)``) to reuse one.

    With ``form`` (v10: cie.factbank.reader.Former), the small model's form helps where the bank's own lessons are not sure: its
    kind of answer is used only when the lessons are not sure of one, and its field only when its kind is the one used."""
    pl = planner or lessons.planner(bank)
    ra, aa, ka = lessons.assocs()
    cands = pl.candidates(question)
    if lessons.rules == "v9":  # v9: only plans that pass the checks
        asked = AskedKind(lessons.asked_kind).asked(question, lessons.kind_floor) if lessons.asked_kind else None
        asked = pl.asked_kind(question, asked)  # v15: with ``brain``, a plainly asked question word decides
        fields: tuple[str, ...] = ()
        if form is not None and form.get("kind"):
            asked = asked or form["kind"]
            fields = tuple(form.get("fields") or ()) if form["kind"] == asked else ()
        cands = pl.check(question, cands, asked, fields)
    scored = sorted(((sigmoid(dot(lessons.weights, pl.x(question, p, m, ra, aa, ka, lessons.features))), p, m["answer"])
                     for p, m in cands), key=lambda x: -x[0])
    if not scored:
        return "not found", None, [], []
    best = scored[0][1]
    journal: list[dict[str, Any]] = [{"op": "plan", "plan": best.describe(bank.names)}]
    ans = pl.execute(best, journal)
    return ans or "not found", best, journal, scored[:8]
