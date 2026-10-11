"""The company brain (fact bank v15; v16 with ``Brain(..., v16=True)``): one ``ask`` for every kind of question about the company.

``Brain.ask`` (v15) takes the first route that applies:

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

v16 (round 2, ``Brain(..., v16=True)``, off by default so that v15 gives the same answers) fixes five faults of single-document
questions:
1. a question word after a verb of knowing or telling ("Do you know when…", "Can you remind me who…") asks plainly
   (``Planner.interrogative_kind`` and ``asks_field`` with ``embedded``);
2. a product or a vendor that documents name as if it were a person does not say what the question is about
   (``BrainBank.not_people``, ``Planner.named_fully``);
3. when a question word asks for a date or a person, v1's engine reads only values of that kind (``BrainBank.answer_facts``),
   and the field check weighs the fields of that kind (``Brain.reads_asked_field``);
4. a list of attendees joins the meeting's attendee fields (``BrainBank.siblings``), and "the attendees of X" asks for people
   (``Planner.asked_kind``);
5. "filed under" asks for the project or space, not who filed it (``BrainBank.wanted``).
The bank also keeps each question's ``named`` result (``BrainBank.named``), most of a question's time otherwise.

v16 also adds four routes. ``Brain.ask`` with v16 takes the first that applies, in this order:

1. **not_found**, as v15.
2. **derived:** the question names one document (``Records.start``: a ticket key, a pull request number, a quoted title or
   Gmail subject, or a quote of words, such as a Slack thread's first words, that one document's text holds) and asks for a
   fact of its history or messages (``Records.derived``): when it was created or last updated, the days from opened to
   merged, who left the first comment and when the latest was posted, its first recorded activity, the date it moved to a
   status, a Gmail thread's first sender, To, Cc, message count, attachments, account and start date, a Slack thread's
   channel and the person who started it.
3. **table:** a count, a list of keys or a list of people over one system's documents, filtered by field values the question
   writes as whole words (``Records.table``: "How many Jira tickets have priority P2?").
4. The router, as v15 (it reads ``Brain.signals``, which fault 1 changes).
5. **prose**, when the router says prose: ``cie.factbank.prose.ProseRoute`` quotes the one document whose passage best matches
   the question (BM25 over passages of the bank's document text, ``PassageIndex``) and answers "not found" when the quote
   covers too little of the question's words weighted by rarity (``quote_cov`` below its default threshold, 0.47).
6. **absent**, when the router says fact: the named document leaves empty a field that at least ``MIN_HELD`` of its system's
   documents hold, and the question asks for that field (``Records.absent``). The answer is "not found", and the reason
   names the field ("the HubSpot account X has no CSM assigned").
7. **plan** or **fact**, as v15 (with the fault fixes).

Routes derived and table answer with a fact, absent with "not found" (``cie.eval.brain2_test.route_class``). Each new route
gives the same row as the others: the answer, the reason, the evidence (what it read: the answer first, then the facts or
entries it rests on, or the passages quoted from), ``reads`` (by role, as ``Planner.reads``), a journal that starts with the
route, the router's family scores when it ran, and the time. One ``Records`` (``min_held``) and one ``ProseRoute`` (its own
passage index) serve every question of a brain, each built on its first use.

    python -m cie.factbank.brain ask --work W --single LESSONS --plans PLAN_LESSONS [--router ROUTER] [--name NAME]
        [--no-field-check] [--v16] [--min-held SHARE]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cie.factbank.engine import CUES, DOC_NOUNS, LIST_RE, STOP, FactBank, Result, Written, stem, words
from cie.factbank.learn import Lessons, norm, sigmoid
from cie.factbank.plans import (
    EMBED_SKIP,
    EMBED_VERBS,
    LINK_WORDS,
    MANY_WORDS,
    ORDER_WORDS,
    QUESTION_WORDS,
    QUOTED,
    Plan,
    PlanLessons,
    Planner,
    follows_embedding_verb,
    raw_words,
    unquoted,
)
from cie.factbank.plans import answer as plan_answer
from cie.factbank.trained import TrainedBank

if TYPE_CHECKING:
    from cie.factbank.prose import ProseRoute
    from cie.factbank.records import Records

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
# v16 (round 2's fault fixes, ``Brain(..., v16=True)``)
# fault 2: the fields whose holders are people, learned once on the train5k bank (fields with 20 or more holders, 90% or more
# of them with a first name two or more people share) and used on every bank, so that a 50-document bank needs no statistics
PERSON_FIELDS = frozenset(("redwood_owner", "se_assigned", "assignee", "creator", "author", "customer_attendees", "reporter",
                           "csm_assigned", "redwood_attendees", "reviewers", "collaborators", "owner", "participants"))
PERSON_DOCS = 3  # a "person" named in this many documents is taken to be one
# fault 3: a value of the kind a question word asks for: a date written as an ISO date (a time may follow)
ISO_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")
ENGINE_SKIP = ("referenced_by", "action_item", "from_document")  # never v1's answer (``FactBank.answer_facts``)
# fault 5: "filed under" asks for the container (a project, a space), not who filed it
FILED_UNDER = re.compile(r"\bfiled\s+under\b")
NAMED_MEMO = 256  # questions whose ``named`` result the bank keeps with ``v16``
# v16's routes: a field counts as one a system uses when this share of its documents hold it (``Records(min_held=...)``, the
# absent route; set in round 2's phase 2 so that a field such as HubSpot's csm_assigned is asked and answered alike in every zone)
MIN_HELD = 0.3
# the kinds of ``Records.derived`` answer that name people (who commented, sent, received, was copied, started a thread)
DERIVED_PEOPLE = frozenset(("first_commenter", "latest_commenter", "email_sender", "email_to", "email_cc", "slack_starter"))
# v16, fact-route abstention (``Brain.cover``): the words that say how a question asks, not what it asks about, which the
# documents a fact answer rests on need not hold: closed-class English words (prepositions, conjunctions, auxiliaries and modals,
# determiners and quantifiers, pronouns, a few adverbs), the words of asking for a count or a person, and the planner's words of
# knowing or telling, of listing, of order, of linking and of questions
CLOSED_WORDS = frozenset("""
about above across after against along among around as at before behind below beneath beside besides between beyond by despite
down during except for from in inside into like near of off on onto out outside over past per since than through throughout till
to toward towards under underneath unlike until up upon via with within without and but or nor so yet because although though
while whereas if unless whether once can could may might must shall should will would do does did done doing be been being am is
are was were has have had having get gets got getting a an the this that these those each every either neither some any no not
all both few many much more most other another such own same several i me my mine we us our ours you your yours he him his she
her hers it its they them their theirs who whom whose which what one ones someone somebody anyone anybody everyone nobody
something anything everything nothing also just only even still already again ever never always often then there here now very
too quite rather really when where why how number count total people person persons please s t d ll re ve
""".split())
COVER_STOP = frozenset(CLOSED_WORDS | EMBED_VERBS | EMBED_SKIP | MANY_WORDS | ORDER_WORDS | LINK_WORDS | QUESTION_WORDS)
# a fact answer chosen by the question's content is "not found" when the documents it rests on hold less than this share of the
# question's rare words (``Brain.cover``): the train5k fit (round 2, phase 2, step 2), the largest threshold that abstains on at
# most 2% of the answerable fact-route questions, rounded down
COVER_BELOW = 0.57
COVER_MIN_WEIGHT = 10.0  # a question whose rare words weigh no more than this (about two rare words) has nothing to check
COVER_ENDS = 50  # the plan's end entities read for the check, at most
ROUTE_UNCOVERED = "absent_doc"  # the route of that "not found" (a not_found route, ``cie.eval.brain2_test.route_class``)


def squash(s: str) -> str:
    """Lower case, letters and digits only, accents dropped as the bank's index drops them, "&" read as "and" and "+" as
    "plus": a title as a question may quote it ("Q3 roadmap - draft" for "Q3 Roadmap — Draft", "batching & queueing" for
    "batching and queueing")."""
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s).lower()) if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", s.replace("&", " and ").replace("+", " plus ")).strip()


def clause_tokens(question: str) -> list[str]:
    """The question's words and punctuation, lower case, outside quoted titles (as ``Planner.interrogative_kind`` reads it)."""
    return re.findall(r"[a-z0-9]+|[,:;.?!()\u2014\u2013]", unquoted(question.lower()))


def asks_field(question: str, embedded: bool = False) -> bool:
    """A clause-opening "what" or "which" (alone, or after "in", "on", "for"…) with a field or an item (``ASKED_NOUNS``) among the
    next few words, before any punctuation: "what is the current ticket status", "In which month", "which draft doc". With
    ``embedded`` (v16), "what" or "which" right after a verb of knowing or telling opens a clause too ("Could you tell me which
    project…", ``follows_embedding_verb``)."""
    toks = clause_tokens(question)

    def opens(j: int) -> bool:
        return j == 0 or not toks[j - 1][0].isalnum() or toks[j - 1] in OPENERS or (embedded and follows_embedding_verb(toks, j))

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
    sentence dates would otherwise outvote its own "SLA due" field.

    ``v16`` (off by default; ``Brain`` sets it) adds round 2's fault fixes to v1's engine and the bank:
    - the kind asked for (fault 3): when a plain question word asks for a date or a person, only values of that kind compete
      for the answer, if any has a positive weight (``answer_facts``, ``value_fits``);
    - attendee lists (fault 4): a list read from one multi-valued field joins the entity's other multi-valued fields with the
      same last word, ``customer_attendees`` with ``redwood_attendees`` (``siblings``);
    - "filed under" (fault 5) asks for the project or space, not the reporter (``wanted``);
    - products stored as people (fault 2): ``not_people``, which the planner leaves out of what a question names;
    - speed: ``named`` is kept per question (the alias scan is most of a question's time);
    - ``answered``: the entities v1's last answer read (the best fact's entity, the document whose title it gave, or the items
      of a list), for the brain's fact-route abstention (``Brain.cover``)."""

    v16 = False
    _not_people: set[str] | None = None
    _named_memo: dict[str, list[str]] | None = None
    answered: list[str] = []

    def named(self, question: str) -> list[str]:
        """``FactBank.named``; with ``v16``, kept for the last ``NAMED_MEMO`` questions, since the planner, the router and the
        engine each ask it again for the same question."""
        if not self.v16:
            return super().named(question)
        if self._named_memo is None or len(self._named_memo) >= NAMED_MEMO:
            self._named_memo = {}
        if question not in self._named_memo:
            self._named_memo[question] = super().named(question)
        return list(self._named_memo[question])

    def wanted(self, question: str) -> dict[str, float]:
        """``FactBank.wanted`` without the sentence facts. With ``v16``, "filed under" (outside quoted titles) asks for the
        container: the weights the cue "file" gave the reporter and the creator go, unless another word brought that cue too
        ("Who filed the file…"), and the project and the space get them instead."""
        out = {p: w for p, w in super().wanted(question).items() if not p.startswith("text_")}
        if self.v16 and FILED_UNDER.search(unquoted(question.lower())):
            out = defaultdict(float, out)
            if not any(w.startswith("file") for w in set(words(question)) - {"filed"}):  # only "filed" brought the cue
                for i, p in enumerate(("reporter", "creator")):
                    out[p] -= 2.0 - 0.1 * i
            for i, p in enumerate(("project", "space")):
                out[p] += 2.0 - 0.1 * i
            out = {p: w for p, w in out.items() if w > 1e-12}
        return out

    def not_people(self) -> set[str]:
        """v16: the bank's "people" with two or more words in their name that the bank does not show to be people, such as a
        product or a vendor that documents name as if it were a person. A name is a person's when any of these holds: its first
        word starts the names of two or more people; it holds a field whose holders are people (``PERSON_FIELDS``, as an
        assignee, an author, an attendee…); or ``PERSON_DOCS`` or more documents name it. Kept on the bank."""
        if self._not_people is None:
            people = {e: (n or "") for e, n in self.names.items() if self.kinds.get(e) == "person"}
            held: dict[str, set[str]] = defaultdict(set)
            docs: dict[str, set[str | None]] = defaultdict(set)
            for e, p, v in self.con.execute("SELECT entity, parameter, value_entity FROM facts WHERE entity LIKE 'person:%' "
                                            "AND parameter LIKE '%\\_of' ESCAPE '\\'"):
                held[e].add(p[:-3])
                docs[e].add(v)
            firsts: dict[str, set[str]] = defaultdict(set)
            for e, n in people.items():
                t = n.lower().split()
                if len(t) >= 2:
                    firsts[t[0]].add(e)
            shared = {f for f, es in firsts.items() if len(es) >= 2}
            self._not_people = {e for e, n in people.items() if len(n.split()) >= 2 and n.lower().split()[0] not in shared
                                and not held[e] & PERSON_FIELDS and len(docs[e]) < PERSON_DOCS}
        return self._not_people

    def value_fits(self, value: str, value_entity: str | None, kind: str | None) -> bool:
        """v16: whether a value is of the kind a question word asks for: a date (written as an ISO date) or a person (a person
        entity, or a person's name). Any value fits any other kind."""
        if kind == "date":
            return bool(ISO_PREFIX.match(value))
        if kind == "person":
            return (value_entity or "").startswith("person:") or value.lower() in self.people
        return True

    def answer_facts(self, question: str, written: dict[tuple[str, str], Written], seeds: list[tuple[str, float]]
                     ) -> tuple[str, str, list[str]]:
        """v1's answer (``FactBank.answer_facts``). With ``v16``, when a plain question word asks for a date or a person
        (``Planner.interrogative_kind``) and some written value with a positive weight is of that kind, only such values
        compete (``value_fits``: every value of the field must fit); the first of the best, in the order written, is picked as
        v1 picks. A list from a multi-valued field takes in its siblings' values (``siblings``). ``answered`` keeps the entities
        the answer read."""
        if not self.v16:
            return super().answer_facts(question, written, seeds)
        ql = question.lower()
        want = self.wanted(question)
        self.answered = []
        if LIST_RE.search(question):
            out = self.list_facts(question, want, written)
            if out[0] != "not found":  # the items listed, by their keys or pull request numbers
                self.answered = [e for lab in out[0].split(", ") for e in sorted(self.aliases.get(lab.lower(), ()))]
            return out
        rel = dict(seeds)
        kind = Planner.interrogative_kind(question, True)
        kind = kind if kind in ("date", "person") else None  # a count is not read from one field
        cands = []
        for (e, p), w in written.items():
            if p.endswith("_of") or p in ENGINE_SKIP:
                continue
            s = want.get(p, 0.0)
            if s <= 0:
                continue
            fits = kind is None or all(self.value_fits(v, w.value_entities[i] if i < len(w.value_entities) else None, kind)
                                       for i, v in enumerate(w.values))
            cands.append((e, p, w, s * (rel.get(e, 0) + w.score), fits))
        if kind is not None and any(c[4] for c in cands):
            cands = [c for c in cands if c[4]]
        best, best_s, why = None, 0.0, ""
        for e, p, w, score, _ in cands:  # the first of the best, in the order written, as v1 picks
            if score > best_s:
                best, best_s, why = w, score, f"{p} of {self.names.get(e, e)}"
        if best is not None:
            self.answered = [best.entity]
            values, parts = list(best.values), [best]
            for sib in self.siblings(question, best, written):
                parts.append(sib)
                values += [v for v in sib.values if v not in values]
            if len(parts) > 1:
                why += " + " + " + ".join(x.parameter for x in parts[1:])
            lines = [f"{x.parameter.replace('_', ' ')} of {self.cited(x.entity, written)}: {v[:300]}" for x in parts for v in dict.fromkeys(x.values)]
            return ", ".join(values), why, lines
        if any(n in set(re.findall(r"[a-z]+", ql)) for n in DOC_NOUNS) and seeds and re.match(r"\s*(in [^,]+,\s*)?(which|what)\b", ql):
            e = next((e for e, _ in seeds if self.kinds.get(e) == "document"), None)
            if e:
                self.answered = [e]
                lab, title = self.label(e, written), self.names.get(e, e)
                return title, "the best document's title", [f"title of {lab}: {title}"] if lab != title else []
        return "not found", "no written fact matches what the question asks", []

    def siblings(self, question: str, best: Written, written: dict[tuple[str, str], Written]) -> list[Written]:
        """v16: the other multi-valued fields written for the same entity whose names end in the same word as the best one's
        (``customer_attendees`` for ``redwood_attendees``). When the question (outside quoted titles) names a part that tells
        them apart ("the customer attendees"), only the parts it names: none if it names a part the best field does not have."""
        p = best.parameter
        if p in self.single or "_" not in p:
            return []
        last = p.split("_")[-1]
        sibs = [w for (e, q), w in written.items() if e == best.entity and q != p and q not in self.single and not q.endswith("_of")
                and q.split("_")[-1] == last]
        if not sibs:
            return []
        qw = set(words(unquoted(question)))
        own = {stem(t) for t in p.split("_")[:-1]}
        named = [w for w in [best, *sibs] if {stem(t) for t in w.parameter.split("_")[:-1]} & qw]
        if named:  # the question names one part: only the parts it names
            return [w for w in sibs if w in named] if own & qw else []
        return sibs


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
    what the question asks for (``reads_asked_field``); otherwise the engine answers, as when the start is not named.

    ``v16`` (off by default) turns on round 2's fault fixes in the bank (``BrainBank``), the planner (``Planner``) and the
    brain's own reading of the question: a question word after a verb of knowing or telling asks plainly (``signals``), and
    the field check weighs the fields of the asked kind (``reads_asked_field``). It also adds the routes derived, table,
    absent and v16's prose (see the module docstring), over one ``Records`` (``records``; ``min_held``, ``MIN_HELD`` by
    default) and one ``ProseRoute`` (``prose_route``), each built on first use."""

    def __init__(self, bank_path: str | Path, single_lessons_path: str | Path, plan_lessons_path: str | Path, router: Router | None = None,
                 *, budget: int = BUDGET, field_check: bool = True, v16: bool = False, min_held: float = MIN_HELD,
                 cover_below: float | None = None):
        self.bank = BrainBank(bank_path, Lessons.load(single_lessons_path))
        self.bank.brain = True
        self.bank.answer_first = False  # the planner path prints its own answer; the engine path sets it while it runs
        self.bank.whole_system_words = True
        self.lessons = PlanLessons.load(plan_lessons_path)
        self.lessons.brain = True
        self.planner = self.lessons.planner(self.bank)
        self.planner.brain = True
        self.v16 = self.bank.v16 = self.planner.v16 = v16
        self.router = router
        self.budget = budget
        self.field_check = field_check
        self._prefixes: set[str] | None = None
        self._titles: set[str] | None = None
        self._names: tuple[set[str], set[str]] | None = None
        self._fts: dict[str, bool] = {}
        self.min_held = min_held
        self._records: Records | None = None
        self._prose_route: ProseRoute | None = None
        self.cover_below = cover_below
        self._entity_count: int | None = None
        self._stems: dict[str, set[str]] = {}

    # ------------------------------------------------------------------ v16: records and free text, built on first use
    def records(self) -> Records:
        """v16: counts, filters, history and messages over the bank (``cie.factbank.records.Records`` with ``min_held``), one
        per brain, built on the first question that needs it."""
        if self._records is None:
            from cie.factbank.records import Records

            self._records = Records(self.bank, min_held=self.min_held)
        return self._records

    def prose_route(self) -> ProseRoute:
        """v16: the free-text route over the bank (``cie.factbank.prose.ProseRoute`` with its default threshold and the brain's
        budget), one per brain; its passage index is built on the first free-text question and kept for every later one."""
        if self._prose_route is None:
            from cie.factbank.prose import ProseRoute

            self._prose_route = ProseRoute(self.bank, budget=self.budget)
        return self._prose_route

    # ------------------------------------------------------------------ v16: fact-route abstention
    def entity_count(self) -> int:
        """The number of entities in the bank's text index (what IDF counts over)."""
        if self._entity_count is None:
            self._entity_count = self.bank.con.execute("SELECT count(*) FROM entities_fts").fetchone()[0]
        return self._entity_count

    def cover_weights(self, question: str) -> dict[str, float]:
        """v16: the question's words that the documents a fact answer rests on should hold, stem -> weight. Words as
        ``ProseRoute.weights`` takes them (``[a-z0-9]+``, two characters or more, not ``engine.STOP``, ``engine.stem``), each
        weighted by its rarity in the bank (IDF over the bank's entities, the larger for two forms of one stem), without: the words
        found only inside quoted titles; the cue words of the fields the question asks for (a word that starts with one of v1's
        ``CUES`` or is a word of a field name ``BrainBank.wanted`` weighs); the words of asking (``COVER_STOP``); and numbers."""
        ql = question.lower()
        inside = {t for m in QUOTED.finditer(ql) for t in re.findall(r"[a-z0-9]+", m.group(0))}
        outside = set(re.findall(r"[a-z0-9]+", QUOTED.sub(" ", ql)))
        asked = {stem(x) for p, w in self.bank.wanted(question).items() if w > 0 for x in p.split("_") if x}
        n = self.entity_count()
        out: dict[str, float] = {}
        for t in sorted(set(re.findall(r"[a-z0-9]+", ql))):
            if len(t) < 2 or t in STOP or t in COVER_STOP or t.isdigit() or (t in inside and t not in outside):
                continue
            s = stem(t)
            if s in asked or any(s.startswith(c) for c in CUES):
                continue
            df = self.bank.doc_freq(t)
            out[s] = max(out.get(s, 0.0), math.log(1 + (n - df + 0.5) / (df + 0.5)))
        return out

    def stems_of(self, entity: str) -> set[str]:
        """v16: the stemmed words of the stored text an entity stands for: a document's title and text, an action item's meeting's,
        or any other entity's own (a person's name). Kept for the last ``NAMED_MEMO`` documents."""
        doc = self.bank.source_doc(entity) if self.bank.kinds.get(entity) == "action_item" else entity
        if doc not in self._stems:
            if len(self._stems) >= NAMED_MEMO:
                self._stems = {}
            row = self.bank.con.execute("SELECT name, text FROM entities_fts WHERE id = ?", (doc,)).fetchone()
            text = " ".join(x or "" for x in row).lower() if row else ""
            self._stems[doc] = {stem(w) for w in re.findall(r"[a-z0-9]+", text)}
        return self._stems[doc]

    def cover(self, question: str, entities: list[str]) -> tuple[float, float, list[str]]:
        """v16: the share of the question's rare words (``cover_weights``), by weight, that the stored text of the entities a fact
        answer rests on holds, with the words' total weight and the words missing. The share is 1.0 when the words weigh no more
        than ``COVER_MIN_WEIGHT``: such a question says too little beyond what it names to check."""
        weights = self.cover_weights(question)
        total = sum(weights.values())
        if total <= COVER_MIN_WEIGHT:
            return 1.0, total, []
        have: set[str] = set()
        for e in entities:
            have |= self.stems_of(e)
        return sum(w for s, w in weights.items() if s in have) / total, total, sorted(s for s in weights if s not in have)

    def cover_step(self, question: str, start: str | None, plan: dict[str, Any] | None = None, result: Result | None = None
                   ) -> dict[str, Any] | None:
        """v16: the fact-route abstention check of a planner's answer (``plan``) or v1's (``result``), as a journal step
        {op: "cover", docs, cover, weight, missing, threshold, abstained}; None when the answer is not chosen by the question's
        content, so there is nothing to check: a plan that starts from what the question names (``Planner.about`` or
        ``Records.start``: a key, a pull request number, a quoted title, a person's full name), or an answer resting on a document
        the question names so. The entities an answer rests on are a plan's starts and the entities it ends at (up to
        ``COVER_ENDS``), or v1's answer's entities (``BrainBank.answered``) and the seeds the question names (``FactBank.named``).
        ``abstained``: the share (``cover``) is below ``cover_below``."""
        about = self.planner.about(question) | ({start} if start else set())
        if plan is not None:
            best = plan["best"]
            if set(best.starts) & about:
                return None
            docs = list(dict.fromkeys([*best.starts, *self.planner.ends(best)[:COVER_ENDS]]))
        else:
            named = set(self.bank.named(question))
            docs = list(dict.fromkeys([*self.bank.answered, *(e for e, _ in result.seeds if e in named)]))
        if set(docs) & {e for e in about if not e.startswith("person:")}:
            return None
        share, total, missing = self.cover(question, docs)
        return {"op": "cover", "docs": docs[:JOURNAL_STEPS], "cover": round(share, 4), "weight": round(total, 2), "missing": missing,
                "threshold": self.cover_below, "abstained": share < self.cover_below}

    def uncovered_row(self, step: dict[str, Any], answer: str, why: str, route: str) -> tuple[str, str]:
        """v16, route absent_doc: the reason and the evidence (the reason, then the answer the fact route would have given and
        the documents it rests on) of a fact answer withdrawn by the check (``cover_step``)."""
        reason = (f"the documents the {route} answer rests on hold {step['cover']:.3f} of the question's rare words by weight, below "
                  f"{step['threshold']} (missing: {', '.join(step['missing'][:8])})")
        lines = [f"Not found: {reason}.", f"The {route} route would have answered: {answer} ({why})"]
        lines += [f"- {self.bank.label_of(e)}: {self.bank.names.get(e, e)[:160]}" for e in step["docs"][:5]]
        return reason, "\n".join(lines)

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
        kind = Planner.interrogative_kind(question, self.v16)
        rw = raw_words(question)
        sig = {"bias": 1.0, "start_named": float(plan["start_named"]), "names": float(bool(self.planner.about(question))),
               "has_id": float(bool(TICKET.search(question) or PR_NUMBER.search(question))), "quoted": float(bool(QUOTED.search(question))),
               "plan_score": plan["score"], "plan_high": float(plan["score"] >= 0.5), "who": float(kind == "person"),
               "when": float(kind == "date"), "how_many": float(kind == "count"), "field_word": float(asks_field(question, self.v16)),
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
        the field v1 would read there (the drive area) holds no person.

        With ``v16``, the fields are weighed against each other: a plain read of one field fails when another field of the
        named thing that fits the asked kind (``BrainBank.value_fits``: any of its values; any field when no date or person is
        asked for) weighs more for the question, or weighs as much while the plan's field does not fit."""
        best = plan["best"]
        if best.path or best.aggregate != "single" or best.field == "label" or len(best.starts) != 1:
            return True
        if self.v16:
            return self.weighs_asked_field(question, best)
        want = self.bank.wanted(question)
        if want.get(best.field, 0.0) > 0:
            return True
        kind = Planner.interrogative_kind(question)
        return not any(want.get(f["parameter"], 0.0) > 0 and (kind is None or self.kind_of(f["value"]) == kind)
                       for f in self.planner.facts(best.starts[0]) if f["parameter"] != best.field)

    def weighs_asked_field(self, question: str, best: Plan) -> bool:
        """v16's field check for a plain read of one field of one start (``reads_asked_field``)."""
        want = self.bank.wanted(question)
        kind = Planner.interrogative_kind(question, True)
        vals: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
        for f in self.planner.facts(best.starts[0]):
            vals[f["parameter"]].append((f["value"], f["value_entity"]))

        def fits(p: str) -> bool:
            return kind not in ("date", "person") or any(self.bank.value_fits(v, ve, kind) for v, ve in vals.get(p, []))

        mine = want.get(best.field, 0.0)
        for p in vals:
            w = want.get(p, 0.0)
            if p == best.field or w <= 0 or not fits(p):
                continue
            if w > mine or (w == mine and not fits(best.field)):
                return False
        return True

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

    # ------------------------------------------------------------------ v16's routes
    def record_reads(self, docs: list[str], values: list[str], people: bool = False) -> dict[str, list[str]]:
        """v16: what a records route read, by role as ``Planner.reads`` gives it (normalised): the labels of the documents it
        read, the values of its answer, and the people among them (all of them with ``people``: the answer names people,
        whether or not the bank holds them as people, such as an email's sender; else the values the bank holds as people)."""
        out = {"ends": [self.bank.label_of(d) for d in docs], "values": values,
               "people": values if people else [v for v in values if v.lower() in self.bank.people]}
        return {k: list(dict.fromkeys(norm(x) for x in v if x)) for k, v in out.items()}

    def derived_row(self, start: str, d: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], dict[str, list[str]]]:
        """v16, route derived: the reason, the evidence (the answer, then the document and the fields or entries read), the
        journal and the reads of ``Records.derived``'s answer about the named document ``start``."""
        lab = self.records().label(start)
        journal = [{"op": "start", "doc": start, "label": lab}, {"op": "derived", "kind": d["kind"], "doc": start, "values": [d["answer"]]}]
        values = d["answer"].split("; " if "; " in d["answer"] else ", ")  # file names, which may hold commas, are joined by "; "
        return (f"{d['kind']} of {lab}: {d['reason']}", f"Answer: {d['answer']}\n{d['evidence']}", journal,
                self.record_reads([start], values, d["kind"] in DERIVED_PEOPLE))

    def table_row(self, t: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], dict[str, list[str]]]:
        """v16, route table: the reason, the evidence (the answer, then the documents matched and their values), the journal
        and the reads of ``Records.table``'s count or list."""
        values = [t["answer"]] if t["kind"] == "count" else [] if not t["docs"] else t["answer"].split(", ")
        journal = [{"op": "table", "kind": t["kind"], "system": t["system"], "filters": t["filters"], "count": len(t["docs"]),
                    "docs": t["docs"][:JOURNAL_STEPS], **({"field": t["field"]} if t.get("field") else {})}]
        return t["reason"], f"Answer: {t['answer']}\n{t['evidence']}", journal, self.record_reads(t["docs"], values, t["kind"] == "people")

    def absent_row(self, start: str, why: str) -> tuple[str, list[dict[str, Any]], dict[str, list[str]]]:
        """v16, route absent: the evidence (the reason, then the fields the named document does hold), the journal and the
        reads of ``Records.absent``'s "not found"."""
        rec = self.records()
        lab = rec.label(start)
        lines = [f"Not found: {why}.", f"[{rec.system_of(start)}] {lab}: {self.bank.names.get(start, start)[:160]}"]
        for p, vs in rec.doc_facts().get(start, {}).items():
            if not p.endswith("_of"):
                lines += [f"- {p.replace('_', ' ')}: {v[:200]}" for v, _ in vs[:3]]
        journal = [{"op": "start", "doc": start, "label": lab}, {"op": "absent", "doc": start, "reason": why}]
        return "\n".join(lines), journal, self.record_reads([start], [])

    def prose_row(self, question: str) -> tuple[str, str, str, list[dict[str, Any]]]:
        """v16, route prose: ``ProseRoute.answer``'s answer ("not found" when it abstains), its reason with ``quote_cov``, the
        passages handed to the quote as evidence, and a journal step with the document quoted from and the coverage."""
        route = self.prose_route()
        p = route.answer(question)
        journal = [{"op": "prose", "doc": p["doc"], "quote_cov": round(p["quote_cov"], 4), "threshold": route.threshold,
                    "abstained": p["abstained"]}]
        return p["answer"], f"{p['reason']} (quote_cov {p['quote_cov']:.3f})", p["evidence"], journal

    def ask(self, question: str) -> dict[str, Any]:
        """The brain's answer: {answer, route, reason, evidence, reads, journal, family_scores, ms}. ``route`` is 'not_found',
        'plan', 'fact' or 'prose', and with ``v16`` also 'derived', 'table' or 'absent' (in the order of the module docstring);
        ``reads`` is what the plan read when the planner answered (``Planner.reads``), or what a records route read. The
        journal starts with the route; then comes the plan's journal, the engine's steps the answer rests on (``rests_on``),
        or the step of a v16 route. ``family_scores`` are the router's, when it ran."""
        t = time.perf_counter()

        def done(answer: str, route: str, reason: str, evidence: str, journal: list, reads: Any = None,
                 scores: dict[str, float] | None = None) -> dict[str, Any]:
            head = {"op": "route", "route": route, "reason": reason, **({"family_scores": scores} if scores else {})}
            return {"answer": answer, "route": route, "reason": reason, "evidence": evidence[:self.budget], "reads": reads or [],
                    "journal": [head, *journal], "family_scores": scores or {}, "ms": round((time.perf_counter() - t) * 1000, 2)}

        miss = self.missing(question)
        if miss:
            return done("not found", "not_found", f"the bank holds no {miss}", f"Not found: the bank holds no {miss}.", [])
        start = None
        if self.v16:
            rec = self.records()
            start = rec.start(question)
            d = rec.derived(question, start) if start else None
            if d is not None:
                reason, evidence, journal, reads = self.derived_row(start, d)
                return done(d["answer"], "derived", reason, evidence, journal, reads)
            tab = rec.table(question)
            if tab is not None:
                reason, evidence, journal, reads = self.table_row(tab)
                return done(tab["answer"], "table", reason, evidence, journal, reads)
        plan = self.plan(question)
        scores = self.family_scores(question, plan)
        if scores["prose"] > scores["fact"]:
            if self.v16:
                answer, reason, evidence, journal = self.prose_row(question)
                return done(answer, "prose", reason, evidence, journal, None, scores)
            answer, reason, evidence = self.prose(question)
            return done(answer, "prose", reason, evidence, [], None, scores)
        if start:
            why = self.records().absent(question, start)
            if why:
                evidence, journal, reads = self.absent_row(start, why)
                return done("not found", "absent", why, evidence, journal, reads, scores)
        found = plan["answer"] != "not found"
        if found and plan["start_named"] and (not self.field_check or self.reads_asked_field(question, plan)):
            return done(plan["answer"], "plan", plan["best"].describe(self.bank.names), self.plan_evidence(question, plan), plan["journal"],
                        self.planner.reads(plan["best"]), scores)
        check = self.v16 and self.cover_below is not None  # a plan from a named start (above) has nothing to check
        r = self.engine(question)
        if r.answer == "not found" and found:
            why = plan["best"].describe(self.bank.names) + " (the engine found nothing)"
            step = self.cover_step(question, start, plan=plan) if check else None
            if step is not None and step["abstained"]:
                reason, evidence = self.uncovered_row(step, plan["answer"], why, "plan")
                return done("not found", ROUTE_UNCOVERED, reason, evidence, [*plan["journal"], step], None, scores)
            return done(plan["answer"], "plan", why, self.plan_evidence(question, plan), [*plan["journal"], *([step] if step else [])],
                        self.planner.reads(plan["best"]), scores)
        step = self.cover_step(question, start, result=r) if check and r.answer != "not found" else None
        if step is not None and step["abstained"]:
            reason, evidence = self.uncovered_row(step, r.answer, r.reason, "fact")
            return done("not found", ROUTE_UNCOVERED, reason, evidence, [*rests_on(r.journal, r.answer), step], None, scores)
        return done(r.answer, "fact", r.reason, r.evidence, [*rests_on(r.journal, r.answer), *([step] if step else [])], None, scores)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def ask_brain(work: Path, single: Path, plans: Path, name: str | None = None, router: Router | str | Path | None = None,
              budget: int = BUDGET, field_check: bool = True, v16: bool = False, min_held: float = MIN_HELD) -> dict[str, Any]:
    """The brain's answers to ``work/questions.jsonl`` from ``work/factbank_v2.sqlite``, written to ``work/<name>.jsonl`` as
    rows {id, answer, route, reason, evidence, ms, reads, journal, family_scores}. ``router`` is a Router or its file. The name
    is "factbank_v15", or "factbank_v16" with ``v16``, when none is given. ``min_held``: v16's ``Records`` share (``MIN_HELD``)."""
    work = Path(work)
    name = name or ("factbank_v16" if v16 else "factbank_v15")
    if isinstance(router, (str, Path)):
        router = Router.load(router)
    brain = Brain(work / "factbank_v2.sqlite", single, plans, router, budget=budget, field_check=field_check, v16=v16, min_held=min_held)
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
    a.add_argument("--name", default=None, help="the rows' file name: factbank_v15, or factbank_v16 with --v16, when left out")
    a.add_argument("--budget", type=int, default=BUDGET)
    a.add_argument("--no-field-check", action="store_true", help="the planner answers every question that names its start")
    a.add_argument("--v16", action="store_true", help="round 2's fault fixes and routes (Brain, v16)")
    a.add_argument("--min-held", type=float, default=MIN_HELD,
                   help=f"v16: the share of a system's documents that must hold a field for the absent route to call it missing "
                        f"(default {MIN_HELD})")
    args = ap.parse_args(argv)
    rep = ask_brain(args.work, args.single, args.plans, args.name, args.router, args.budget, not args.no_field_check, args.v16,
                    args.min_held)
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
