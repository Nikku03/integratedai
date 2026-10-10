"""The fact bank with learned lessons (``cie.factbank.learn``): it finds the entity, chooses the answer and orders its
evidence by learned weights, then reasons with the same hops, snap and journal as before.

Without lessons, ``entity_candidates`` and ``answer_candidates`` still work; ``cie.factbank.learn.train`` uses them to
fit the lessons.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any

from cie.factbank.engine import LAM, FactBank, Result, words
from cie.factbank.learn import (
    ID_WORDS,
    LIST_WORDS,
    PLURAL_ITEMS,
    Assoc,
    Lessons,
    dot,
    norm,
    question_kind,
    sigmoid,
    tokens_of,
    value_kind,
)

SKIP_PARAMS = {"referenced_by", "action_item", "action_owner_of", "from_document"}


class TrainedBank(FactBank):
    def __init__(self, path, lessons: Lessons | None = None):
        super().__init__(path)
        self.lessons = lessons
        self.people = {n.lower() for e, n in self.names.items() if self.kinds.get(e) == "person"}
        self.src_of = {r["id"]: r["source"] for r in self.con.execute("SELECT id, source FROM entities")}
        n_ent = max(1, len(self.names))
        self.df = {r[0]: r[1] / n_ent for r in self.con.execute(
            "SELECT lower(value), count(DISTINCT entity) FROM facts WHERE parameter NOT LIKE 'text_%' GROUP BY lower(value)")}
        self._assoc: Assoc | None = None

    @property
    def assoc(self) -> Assoc:
        if self._assoc is None:
            self._assoc = Assoc.from_json(self.lessons.assoc if self.lessons else {})
        return self._assoc

    # ------------------------------------------------------------------ helpers
    def source_doc(self, e: str) -> str:
        return e if e.startswith("doc:") else (f"doc:{self.src_of[e]}" if self.src_of.get(e) else e)

    def system_of_entity(self, e: str) -> str:
        return self.system.get(self.source_doc(e)[4:], "")

    def label_of(self, e: str) -> str:
        return self.label(e, {})

    def relations(self, person: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for f in self.facts_of(person):
            if f["parameter"].endswith("_of") and f["value_entity"]:
                out[f["parameter"]].append(f["value_entity"])
        return dict(out)

    # ------------------------------------------------------------------ which entity
    def entity_candidates(self, question: str, k: int = 20) -> list[dict[str, Any]]:
        qn = norm(question)
        qw = set(words(question))
        named = [e for e in self.named(question) if not e.startswith("person:")]
        ranked = [e for e in self.by_content(question, k) if self.kinds.get(e) in ("document", "action_item")]
        out = []
        for e in dict.fromkeys(named + ranked):
            if self.kinds.get(e) not in ("document", "action_item"):
                continue
            rank = 1.0 / (1 + ranked.index(e)) if e in ranked else 0.0
            clues = set()
            for f in self.facts_of(e):
                v = norm(f["value"])
                if f["parameter"].startswith("text_") or len(v) < 4 or self.df.get(f["value"].lower(), 0) > 0.2:
                    continue
                if re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", qn):
                    clues.add(v)
            tw = set(words(self.names.get(e, "")))
            x = [1.0, rank, float(e in named), min(3, len(clues)) / 3, len(tw & qw) / max(1, len(tw)),
                 float(self.kinds.get(e) == "action_item")]
            rel = sigmoid(dot(self.lessons.entity_w, x)) if self.lessons else rank
            out.append({"entity": e, "x": x, "relevance": rel})
        out.sort(key=lambda c: -c["relevance"])
        return out

    # ------------------------------------------------------------------ which fact
    def answer_candidates(self, question: str, top: int = 8) -> list[dict[str, Any]]:
        ents = self.entity_candidates(question)[:top]
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        def add(e: str, f, rel: float, hop: int) -> None:
            key = (e, f["parameter"], f["value"])
            if key in seen or f["parameter"].endswith("_of") or f["parameter"] in SKIP_PARAMS:
                return
            seen.add(key)
            out.append({"entity": e, "parameter": f["parameter"], "value": f["value"], "claim": f["claim"], "confidence": f["confidence"],
                        "relevance": rel, "hop": hop, "is_title": False})

        for c in ents:
            e, rel = c["entity"], c["relevance"]
            if self.kinds.get(e) == "document":
                out.append({"entity": e, "parameter": "title", "value": self.names.get(e, ""), "claim": self.names.get(e, ""),
                            "confidence": "measured", "relevance": rel, "hop": 0, "is_title": True})
            linked = []
            for f in self.facts_of(e):
                add(e, f, rel, 0)
                if f["value_entity"] and self.kinds.get(f["value_entity"]) in ("action_item", "document"):
                    linked.append(f["value_entity"])
            for t in list(dict.fromkeys(linked))[:10]:  # one hop: what this entity points to
                for f in self.facts_of(t):
                    add(t, f, rel * LAM, 1)
        return out

    def answer_x(self, question: str, c: dict[str, Any], assoc: Assoc | None = None) -> list[float]:
        assoc = assoc or self.assoc
        qw = set(words(question))
        qkind = question_kind(question)
        toks = tokens_of(c["parameter"])
        vkind = value_kind(c["value"], c["parameter"], self.people, c["is_title"])
        from_text = c["parameter"].startswith("text_")
        sent = set(words(c["claim"])) if from_text else set()
        v = norm(c["value"])
        in_q = bool(len(v) >= 3 and re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", norm(question)))
        return [1.0, c["relevance"], float(c["hop"]), len(toks & qw) / max(1, len(toks)), assoc.score(qw, toks),
                len(sent & qw) / max(1, len(qw)) if from_text else 0.0, float(qkind != "other" and qkind == vkind),
                float(qkind != "other" and vkind != "other" and qkind != vkind), float(in_q), float(c["is_title"]),
                float(c["is_title"] and qkind == "title"), float(from_text), float(c["confidence"] == "inferred")]

    # ------------------------------------------------------------------ lists
    def list_x(self, question: str) -> list[float]:
        q = re.sub(r"\"[^\"]*\"", " ", question)  # words inside a quoted title are not the question's own
        return [1.0, float(bool(PLURAL_ITEMS.search(q))), float(bool(LIST_WORDS.search(q))),
                float(bool(ID_WORDS.search(q))), float(bool(re.match(r"\s*(\w+[,:]?\s+){0,4}?(which|what)\b", q, re.I)))]

    def relation_x(self, question: str, person: str, rel: str, system: str) -> list[float]:
        qw = set(words(question))
        toks = tokens_of(rel[:-3])
        prior = (self.lessons.system_prior.get(system, {}) if self.lessons else {}).get(rel, 0.0)
        docs = self.relations(person).get(rel, [])
        cover = (sum(1 for d in docs if self.system_of_entity(d) == system) / len(docs)) if (docs and system) else 0.5
        return [1.0, len(toks & qw) / max(1, len(toks)), self.assoc.score(qw, toks), prior, cover]

    # ------------------------------------------------------------------ asking
    def ask(self, question: str, k: int = 5, budget: int = 24_000) -> Result:
        t = time.perf_counter()
        if self.lessons is None:
            return super().ask(question, k, budget)
        ents = self.entity_candidates(question)
        seeds = {c["entity"]: c["relevance"] for c in ents[:k]}
        for e in self.named(question):
            seeds.setdefault(e, 1.0)
        written, journal, seed_list = self.run(question, seeds=seeds)
        is_list = sigmoid(dot(self.lessons.list_w, self.list_x(question))) > 0.5
        head: list[str] = []
        facts: list[str] = []  # with ``brain``: the facts the answer rests on, to print first
        if is_list:
            answer, reason, head = self.list_ask(question)
            facts = [x[2:] for x in head]
        else:
            cands = self.answer_candidates(question)
            scored = sorted(((sigmoid(dot(self.lessons.answer_w, self.answer_x(question, c))), c) for c in cands), key=lambda x: -x[0])
            if scored:
                best = scored[0][1]
                answer, reason = best["value"], f"{best['parameter']} of {self.names.get(best['entity'], best['entity'])}"
                if self.brain:
                    ctx = f' — "{best["claim"][:240]}"' if best["parameter"].startswith("text_") else ""
                    facts = [f"{best['parameter'].replace('_', ' ')} of {self.cited(best['entity'], {})}: {best['value'][:300]}{ctx}"]
            else:
                answer, reason = "not found", "no candidate"
            for _s, c in scored[:8]:
                src = self.names.get(c["entity"], c["entity"])
                ctx = f' — "{c["claim"][:240]}"' if c["parameter"].startswith("text_") else ""
                head.append(f"- {c['parameter'].replace('_', ' ')}: {c['value'][:300]} — {src}{ctx}")
        if not self.brain:
            top = "Most likely answers, best first:\n" + "\n".join(head) if head else ""
        else:  # the answer and the facts it rests on, then the other candidates
            others = [] if is_list else head[1:]
            more = "Other likely answers, best first:\n" + "\n".join(others) if others else ""
            top = "\n\n".join(x for x in (self.head(answer, facts), more) if x)
        rest = self.evidence(written, seed_list, max(0, budget - len(top) - 2))
        return Result(answer, (top + "\n\n" + rest).strip()[:budget], journal, written, seed_list, (time.perf_counter() - t) * 1000, reason)

    def list_ask(self, question: str) -> tuple[str, str, list[str]]:
        system = (self.named_systems(question) or [""])[0]
        status = re.findall(r"\"([^\"]+)\"", question)
        window = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question)
        people = [e for e in self.named(question) if e.startswith("person:")]
        docs: list[str] = []
        reason = ""
        best = None
        if people:
            for person in people:
                for rel in self.relations(person):
                    s = sigmoid(dot(self.lessons.relation_w, self.relation_x(question, person, rel, system)))
                    if best is None or s > best[0]:
                        best = (s, person, rel)
            if best:
                docs = self.relations(best[1])[best[2]]
                reason = f"{best[2]} of {self.names.get(best[1], best[1])}"
        elif window:
            lo, hi = min(window), max(window)
            docs = [r[0] for r in self.con.execute("SELECT DISTINCT entity FROM facts WHERE parameter = 'due_date' AND value BETWEEN ? AND ?",
                                                    (lo, hi))]
            reason, window = f"due between {lo} and {hi}", []
        out, lines = [], []
        for e in dict.fromkeys(docs):
            facts = {f["parameter"]: f["value"] for f in self.facts_of(e)}
            if system and self.system_of_entity(e) != system:
                continue
            if status and str(facts.get("status", facts.get("state", ""))).lower() not in {s.lower() for s in status}:
                continue
            if window and not (min(window) <= str(facts.get("due_date", "")) <= max(window)):
                continue
            lab = self.label_of(e)
            out.append(lab)
            if not self.brain:
                lines.append(f"- {lab}: {self.names.get(e, e)}")
            elif people and best:  # one line per item: the fact that put it on the list
                lines.append(f"- {best[2][:-3].replace('_', ' ')} of {self.cited(e, {})}: {self.names.get(best[1], best[1])}")
            else:
                lines.append(f"- due date of {self.cited(e, {})}: {facts.get('due_date', '')}")
        return (", ".join(out) if out else "not found"), reason, lines
