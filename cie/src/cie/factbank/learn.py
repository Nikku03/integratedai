"""Lessons for the fact bank, learned from questions with their answers (docs/FACTBANK_LEARNING_PREREGISTRATION.md).

Everything learned is a weight on a *principle*, never a value from the training data, so it carries over to other
documents, other wording and changed information:

* **Which entity the question means.** Its keyword rank; whether the question names it (an identifier, a person); how
  many of its own field values the question repeats ("clues"); how much of its title the question repeats.
* **Which fact is the answer.**
  - The entity's relevance, and the hop it was reached at.
  - The question's overlap with the field's name.
  - An association between question words and field-name words, learned from the training answers. In training,
    each question's own contribution is left out.
  - For a value read from a sentence, the sentence's overlap with the question.
  - Whether the kind of value fits the question: a date for "when", a person for "who", a title for "which page".
  - Whether the value already appears in the question: a clue, not the answer.
* **Whether the question wants a list.** Plural item nouns, "list" or "every", "keys" or "numbers".
* **Which relation a list means.** Field-name overlap and association; and, by source system, how often each relation
  was the one meant in training (pull requests → author).

Weights are fitted by logistic regression on the training questions and saved as JSON (``Lessons.save``).
``Lessons.describe`` lists them in words.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from cie.factbank.engine import STOP, stem, words

DATE_Q = re.compile(r"\b(when|what date|which date|deadline|due|by what date|by when)\b", re.I)
PERSON_Q = re.compile(r"\b(who|whom|whose)\b", re.I)
TITLE_Q = re.compile(r"\b(which|what)\b[^?]{0,60}?\b(page|document|doc|spreadsheet|sheet|playbook|deck|memo|pull request|pr|thread|account|"
                     r"company|deal|report|runbook|guide|title|note|notes|canvas|template|templates|plan|post|article)\b", re.I)
KEY_Q = re.compile(r"\b(identifier|ticket|key|id|incident|jira|number)\b", re.I)
PLURAL_ITEMS = re.compile(r"\b(issues|tickets|prs|pull requests|documents|pages|items|tasks|keys|numbers)\b", re.I)
LIST_WORDS = re.compile(r"\b(list|every|all|each)\b", re.I)
ID_WORDS = re.compile(r"\b(keys|numbers|ids)\b", re.I)
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEY_V = re.compile(r"^[A-Z][A-Z0-9]{1,9}(?:-\d{1,7})+$")

ENTITY_FEATURES = ["bias", "rank", "named", "clues", "title_overlap", "is_action"]
ANSWER_FEATURES = ["bias", "relevance", "hop", "name_overlap", "association", "sentence_overlap", "kind_fits", "kind_conflicts",
                   "in_question", "is_title", "title_asked", "from_text", "inferred"]
LIST_FEATURES = ["bias", "plural_items", "list_words", "id_words", "which_or_what"]
RELATION_FEATURES = ["bias", "name_overlap", "association", "system_prior", "system_coverage"]


def norm(s: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w@.\- ]+", " ", str(s).lower())).strip()


def question_kind(q: str) -> str:
    if DATE_Q.search(q):
        return "date"
    if PERSON_Q.search(q):
        return "person"
    if TITLE_Q.search(q):
        return "title"
    if KEY_Q.search(q):
        return "key"
    return "other"


def value_kind(v: str, parameter: str, people: set[str], is_title: bool) -> str:
    from cie.ingest.sources import PEOPLE_FIELDS

    if is_title:
        return "title"
    if ISO.match(v) or parameter.endswith("date"):
        return "date"
    if parameter in PEOPLE_FIELDS or v.lower() in people or parameter in ("owner",):
        return "person"
    if KEY_V.match(v) or parameter == "text_key":
        return "key"
    return "other"


def tokens_of(parameter: str) -> set[str]:
    return {stem(x) for x in re.split(r"[_\s]+", parameter) if x and x not in STOP}


@dataclass
class Assoc:
    """How often a question word came with an answer whose field name holds a given word."""

    pair: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))
    word: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def add(self, qwords: set[str], ptoks: set[str], sign: float = 1.0) -> None:
        for w in qwords:
            self.word[w] += sign
            for t in ptoks:
                self.pair[w][t] += sign

    def score(self, qwords: set[str], ptoks: set[str]) -> float:
        if not ptoks:
            return 0.0
        tot = 0.0
        for t in ptoks:
            tot += max((self.pair.get(w, {}).get(t, 0.0) / (self.word.get(w, 0.0) + 2.0) for w in qwords), default=0.0)
        return tot / len(ptoks)

    def to_json(self) -> dict[str, Any]:
        return {"pair": {w: dict(v) for w, v in self.pair.items() if any(v.values())}, "word": dict(self.word)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Assoc:
        a = cls()
        for w, v in d.get("pair", {}).items():
            a.pair[w].update(v)
        a.word.update(d.get("word", {}))
        return a


def fit(x: np.ndarray, y: np.ndarray, l2: float = 1.0) -> list[float]:
    """Logistic regression weights (the first feature is the bias)."""
    from sklearn.linear_model import LogisticRegression

    if len(set(y.tolist())) < 2:
        return [0.0] * x.shape[1]
    m = LogisticRegression(C=1.0 / l2, class_weight="balanced", max_iter=2000, fit_intercept=False)
    m.fit(x, y)
    return [float(v) for v in m.coef_[0]]


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


@dataclass
class Lessons:
    entity_w: list[float]
    answer_w: list[float]
    list_w: list[float]
    relation_w: list[float]
    assoc: dict[str, Any]
    system_prior: dict[str, dict[str, float]]
    trained_on: dict[str, Any]

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls, path: str | Path) -> Lessons:
        return cls(**json.loads(Path(path).read_text()))

    def describe(self) -> list[str]:
        out = []
        for name, feats, w in (("finding the entity", ENTITY_FEATURES, self.entity_w), ("choosing the answer", ANSWER_FEATURES, self.answer_w),
                               ("telling a list question", LIST_FEATURES, self.list_w), ("choosing a list's relation", RELATION_FEATURES, self.relation_w)):
            pairs = sorted(((f, v) for f, v in zip(feats, w, strict=True) if f != "bias"), key=lambda x: -abs(x[1]))
            out.append(f"{name}: " + ", ".join(f"{f} {v:+.2f}" for f, v in pairs))
        top = sorted(((w, t, c) for w, d in self.assoc.get("pair", {}).items() for t, c in d.items() if c > 0), key=lambda x: -x[2])[:12]
        out.append("strongest question-word → field-word links: " + ", ".join(f"'{w}'→'{t}'" for w, t, _ in top))
        out.append("list relation by system: " + ", ".join(f"{s}: {max(d, key=d.get)}" for s, d in self.system_prior.items() if d))
        return out


def dot(w: list[float], x: list[float]) -> float:
    return sum(a * b for a, b in zip(w, x, strict=True))


# ---------------------------------------------------------------------------------------------- training
def _matches(expected: dict[str, Any], value: str) -> bool:
    if "date" in expected:
        return value == expected["date"]
    if "value" in expected:
        vals = [expected["value"], *expected.get("alts", [])]
        return any(norm(v) == norm(value) for v in vals)
    return False


def train(bank, questions: list[dict[str, Any]], log=print) -> Lessons:
    """Fit the lessons on questions with expected answers, using ``bank`` (a ``TrainedBank`` over the training
    documents, without lessons yet)."""
    from cie.factbank.engine import SYSTEM_WORDS

    # 1. which entity: gold documents and their action items are positives
    ex, ey = [], []
    for q in questions:
        if q["group"] == "lists":
            continue
        gold = {f"doc:{d}" for d in q["gold_docs"]}
        for c in bank.entity_candidates(q["question"]):
            ex.append(c["x"])
            ey.append(int(c["entity"] in gold or bank.source_doc(c["entity"]) in gold))
    entity_w = fit(np.array(ex, float), np.array(ey))
    bank.lessons = Lessons(entity_w, [0.0] * len(ANSWER_FEATURES), [0.0] * len(LIST_FEATURES), [0.0] * len(RELATION_FEATURES),
                           {}, {}, {})
    # 2. association, counted per question, so each question's own share can be left out
    per_q: list[tuple[set[str], set[str]]] = []
    total = Assoc()
    cands_by_q = []
    for q in questions:
        if q["group"] == "lists":
            continue
        cands = bank.answer_candidates(q["question"])
        pos = [c for c in cands if _matches(q["expected"], c["value"])]
        qw = set(words(q["question"]))
        pt = set().union(*[tokens_of(c["parameter"]) for c in pos]) if pos else set()
        per_q.append((qw, pt))
        total.add(qw, pt)
        cands_by_q.append((q, cands))
    ax, ay = [], []
    for (q, cands), (qw, pt) in zip(cands_by_q, per_q, strict=True):
        total.add(qw, pt, -1.0)  # leave this question out of its own association
        for c in cands:
            ax.append(bank.answer_x(q["question"], c, total))
            ay.append(int(_matches(q["expected"], c["value"])))
        total.add(qw, pt, 1.0)
    answer_w = fit(np.array(ax, float), np.array(ay))
    # 3. list questions, and which relation a list means
    lx = [bank.list_x(q["question"]) for q in questions]
    ly = [int(q["group"] == "lists") for q in questions]
    list_w = fit(np.array(lx, float), np.array(ly))
    prior: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    rel_rows = []
    for q in questions:
        if q["group"] != "lists":
            continue
        system = next((s for w, s in SYSTEM_WORDS.items() if w in q["question"].lower() + " "), "")
        want = set(q["expected"]["ids"])
        for person in [e for e in bank.named(q["question"]) if e.startswith("person:")]:
            for rel, docs in bank.relations(person).items():
                got = {bank.label_of(d) .lstrip("#") for d in docs if not system or bank.system_of_entity(d) == system}
                hit = len(got & want)
                good = hit and hit / len(want) >= 0.5
                rel_rows.append((q["question"], person, rel, system, int(bool(good))))
                if good:
                    prior[system][rel] += 1.0
                    total.add(set(words(q["question"])), tokens_of(rel[:-3]))
    sp = {s: {r: c / sum(d.values()) for r, c in d.items()} for s, d in prior.items()}
    bank.lessons.system_prior = sp
    bank.lessons.assoc = total.to_json()
    rx = [bank.relation_x(qq, person, rel, system) for qq, person, rel, system, _ in rel_rows]
    relation_w = fit(np.array(rx, float), np.array([r[-1] for r in rel_rows])) if rx else [0.0] * len(RELATION_FEATURES)
    lessons = Lessons(entity_w, answer_w, list_w, relation_w, total.to_json(), sp,
                      {"questions": len(questions), "entity_rows": len(ey), "answer_rows": len(ay), "answer_positives": int(sum(ay)),
                       "relation_rows": len(rel_rows)})
    log("\n".join(lessons.describe()))
    return lessons
