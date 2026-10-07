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

from cie.factbank.engine import SYSTEM_WORDS, stem, words
from cie.factbank.learn import Assoc, dot, fit, norm, question_kind, sigmoid, tokens_of

AGGS = ("single", "list", "count", "earliest", "latest")
HOW_MANY = re.compile(r"\bhow many\b", re.I)
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOT_LINKS = {"from_document"}
FEATURES = ["bias", "start_named", "start_rank", "two_starts", "path_len", "path_overlap", "path_assoc", "field_overlap", "field_assoc",
            "kind_fits", "kind_conflicts", "combine_assoc", "label_field", "answer_in_question", "fanout"]
# v4 (after the first test, docs/FACTBANK_MULTI_RESULTS.md): the clue rule split by whether the question offers a choice, the
# kind of answer learned from the question's words instead of fixed patterns, and whether the answer comes from the system the
# question names
FEATURES_V4 = ["bias", "start_named", "start_rank", "two_starts", "path_len", "path_overlap", "path_assoc", "field_overlap", "field_assoc",
               "kind_assoc", "combine_assoc", "label_field", "answer_named_choice", "answer_named_clue", "system_fits", "fanout"]


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
    ``"v3"`` is the planner as first tested."""

    def __init__(self, bank, rules: str = "v3"):
        self.b = bank
        self.rules = rules
        self._facts: dict[str, list] = {}

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
            ents = [e for e in ents if self.b.system_of_entity(e) == plan.system]
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
        if self.rules == "v4":
            vals = list(dict.fromkeys(v for e in ents for v in self.field_values(e, plan.field)))
            return vals[0] if len(vals) == 1 else None  # several different values: not one answer
        vals = self.field_values(ents[0], plan.field)
        return ", ".join(vals) if vals else None

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
        system = next((s for w, s in SYSTEM_WORDS.items() if w in ql), "")
        quoted = re.findall(r"\"([^\"]+)\"", question)
        out = []
        for st, meta in starts:
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
            if self.rules == "v4":
                paths = [p for p in paths if not (len(p) == 2 and inverse(p[0], p[1]))]
            for path in paths:
                ents = self.follow(st, path)
                if not ents:
                    continue
                came_from = set(st) | {e for i in range(1, len(path)) for e in self.follow(st, path[:i])}
                echo = {self.b.label_of(e) for e in came_from}
                if self.rules == "v4" and path and set(ents) <= came_from:
                    continue  # the last hop reached nothing new
                sys_f = system if system and any(self.b.system_of_entity(e) == system for e in ents) else ""
                statuses = {v for e in ents[:30] for v in self.field_values(e, "status")}
                stat_f = tuple(q for q in quoted if q in statuses)
                fields = {"label"} | {f["parameter"] for e in ents[:5] for f in self.facts(e)
                                      if not f["parameter"].endswith("_of") and not f["parameter"].startswith("text_")
                                      and f["parameter"] not in ("referenced_by", "action_item")}
                if self.rules == "v4" and path:
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
                        plan = Plan(st, path, field, agg, sys_f, stat_f)
                        ans = self.execute(plan)
                        if ans is None:
                            continue
                        if self.rules == "v4" and agg in ("single", "list") and set(ans.split(", ")) <= echo:
                            continue  # only names what it started from or passed through
                        out.append((plan, {**meta, "answer": ans, "fanout": len(ents)}))
        return out

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
        return {"bias": 1.0, "start_named": meta["named"], "start_rank": meta["rank"], "two_starts": float(len(plan.starts) == 2),
                "path_len": float(len(plan.path)),
                "path_overlap": float(np.mean([len(t & qw) / max(1, len(t)) for t in rel_toks])) if rel_toks else 0.0,
                "path_assoc": float(np.mean([rel_assoc.score(qw, t) for t in rel_toks])) if rel_toks else 0.0,
                "field_overlap": len(f_toks & qw) / max(1, len(f_toks)), "field_assoc": rel_assoc.score(qw, f_toks) if f_toks else 0.0,
                "kind_fits": float(fits), "kind_conflicts": float(conflicts),
                "kind_assoc": kind_assoc.score(question_words(question), {okind}) if kind_assoc is not None else 0.0,
                "combine_assoc": agg_assoc.score(qw, {plan.aggregate}), "label_field": float(plan.field == "label"),
                "answer_in_question": float(in_q), "answer_named_choice": float(in_q and choice), "answer_named_clue": float(in_q and not choice),
                "system_fits": float(bool(plan.system)),
                "fanout": math.log1p(meta["fanout"])}

    def x(self, question: str, plan: Plan, meta: dict[str, Any], rel_assoc: Assoc, agg_assoc: Assoc, kind_assoc: Lift | None = None,
          names: list[str] = FEATURES) -> list[float]:
        f = self.features(question, plan, meta, rel_assoc, agg_assoc, kind_assoc)
        return [f[n] for n in names]


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


def matches(expected: dict[str, Any], answer: str) -> bool:
    from cie.eval.memory_test import ids_in

    if "ids" in expected:
        return ids_in(answer, expected["id_kind"]) == set(expected["ids"]) if expected["id_kind"] != "key" or answer else False
    if "date" in expected:
        return answer == expected["date"]
    vals = [expected["value"], *expected.get("alts", [])]
    return any(norm(v) == norm(answer) for v in vals)


def learn_plans(bank, questions: list[dict[str, Any]], log=print, features: list[str] = FEATURES_V4, rules: str = "v4") -> PlanLessons:
    """Fit the plan weights on questions with answers. Associations leave each question's own share out."""
    pl = Planner(bank, rules)
    per_q = []
    rel_total, agg_total, kind_total = Assoc(), Assoc(), Lift()
    for q in questions:
        cands = pl.candidates(q["question"])
        good = [(p, m) for p, m in cands if matches(q["expected"], m["answer"])]
        qw, kw = set(words(q["question"])), question_words(q["question"])
        rt = set().union(*[set().union(*[tokens_of(r) for r in p.path], tokens_of(p.field) if p.field != "label" else set())
                           for p, _ in good]) if good else set()
        at = {p.aggregate for p, _ in good}
        kt = {pl.out_kind(p, m["answer"]) for p, m in good}
        rel_total.add(qw, rt)
        agg_total.add(qw, at)
        kind_total.add(kw, kt)
        per_q.append((q, cands, qw, kw, rt, at, kt))
    use_kind = "kind_assoc" in features
    xs, ys = [], []
    for q, cands, qw, kw, rt, at, kt in per_q:
        rel_total.add(qw, rt, -1.0)
        agg_total.add(qw, at, -1.0)
        kind_total.add(kw, kt, -1.0)
        for p, m in cands:
            xs.append(pl.x(q["question"], p, m, rel_total, agg_total, kind_total if use_kind else None, features))
            ys.append(int(matches(q["expected"], m["answer"])))
        rel_total.add(qw, rt)
        agg_total.add(qw, at)
        kind_total.add(kw, kt)
    w = fit(np.array(xs, float), np.array(ys))
    les = PlanLessons(w, rel_total.to_json(), agg_total.to_json(),
                      {"questions": len(questions), "plans": len(ys), "right_plans": int(sum(ys)),
                       "questions_with_a_right_plan": sum(1 for qq, cands, *_rest in per_q
                                                          if any(matches(qq["expected"], m["answer"]) for _p, m in cands))},
                      list(features), kind_total.to_json() if use_kind else {}, rules)
    log("\n".join(les.describe()))
    return les


def answer(bank, lessons: PlanLessons, question: str) -> tuple[str, Plan | None, list[dict[str, Any]], list[tuple[float, Plan, str]]]:
    """The best plan's answer, its journal, and the top plans."""
    pl = Planner(bank, lessons.rules)
    ra, aa, ka = lessons.assocs()
    scored = sorted(((sigmoid(dot(lessons.weights, pl.x(question, p, m, ra, aa, ka, lessons.features))), p, m["answer"])
                     for p, m in pl.candidates(question)), key=lambda x: -x[0])
    if not scored:
        return "not found", None, [], []
    best = scored[0][1]
    journal: list[dict[str, Any]] = [{"op": "plan", "plan": best.describe(bank.names)}]
    ans = pl.execute(best, journal)
    return ans or "not found", best, journal, scored[:8]
