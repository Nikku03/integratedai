"""The company brain's free-text route (v16): sentences quoted from the one document that best matches the question, or
"not found" when the quote does not cover what the question asks about.

1. **Passage index** (``PassageIndex``): the bank's stored text of every document (title, fields and body, as
   ``FactBank.passages`` reads it), cut into passages of whole sentences of 600-1,000 characters (``engine.windows``), in an
   in-memory SQLite FTS5 table (title, body; tokenizer porter unicode61). It is built once per bank, on first use, and
   shared by every route over that bank (``PassageIndex.of``; about 30,000 passages, 110 MB and 2-3 seconds for a
   5,000-document bank).
2. **One document.** The question's content words, as plain search takes them (``cie.retrieval.lexical._terms``), are an OR
   query ranked by BM25 with the title weighted 2.5 and the body 1.0. The document of the best passage is the only document
   quoted from: its passages in BM25 order, then its other passages in document order, up to 60.
3. **Quote.** ``cie.retrieval.answer.quote_answer`` over those passages (it reads the first 20).
4. **Abstention** (``ProseRoute.answer``): ``quote_cov`` is the share of the question's words present in the quoted answer,
   each word weighted by its rarity in the bank (IDF over the bank's entities, as ``FactBank.passages`` weighs the words:
   ``[a-z0-9]+`` minus ``engine.STOP``, two characters or more, ``engine.stem``). Below ``ABSTAIN_BELOW`` (0.47) the answer
   is "not found".

Chosen in the v16 survey of prose-route designs on the 111 train5k prose questions and checked on the 52 dev5k ones, with
answers scored by ``cie.eval.brain_questions.score`` after ``cie.eval.brain_test.plain_answer``: train 0.716, dev 0.804,
against v15's route (``FactBank.passages``, five documents, IDF-share) 0.544 and 0.673 and plain search 0.494 and 0.654.
Quoting from one document matters most; BM25 with the title weighted beats the IDF share at every number of documents.

The threshold is the survey's train fit rounded. The survey's rule, applied to train only, takes the most correct
abstentions (questions asked with their gold document left out) with at most 5% of the answerable questions abstained; on
``quote_cov`` rounded to four decimals it gave 0.4718, and the design rounded that to 0.47 and kept it (not moved after
seeing dev). So 0.47 is not the rule's optimum: on unrounded values the rule is best for any threshold in (0.4707,
0.4718], and 0.47 abstains on the same 5 answerable train questions but on one gold-removed train question fewer.
With 0.47, on train: 5/111 answerable questions abstain (the train score goes from 0.716 to 0.694); 86/111 are correctly
answered "not found" when asked with their gold document left out (51/65 of those whose facts no other single document
holds), and 43/52 dev questions asked of the train bank (17/21). On dev: 0/52 answerable questions abstain (0.804 stays);
39/52 with their gold document left out (17/24), and 80/111 train questions asked of the dev bank, where their document
does not exist (52/70). The survey's 87/111 (52/65) and 81/111 (53/70) are the counts at 0.4718 on rounded values; one
question in each lies between 0.47 and 0.4718. The threshold belongs to this design (text, cut, ranking, one document); a
change to any of them needs it refitted on train.

``exclude`` (documents left out at query time) simulates a question whose document the bank does not hold: the passages
of those documents are skipped, and the rarity weights count document frequency as if those documents and their action
items were not in the bank. The index's own BM25 statistics still count them.
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
from collections.abc import Iterable
from typing import Any, NamedTuple

from cie.factbank.engine import STOP, FactBank, stem, windows

PROSE_SIZE = (600, 1000)
TITLE_WEIGHT = 2.5  # BM25 weight of a passage's title (its document's title); the body weighs 1.0
QUOTE_PASSAGES = 60  # passages handed to quote_answer (it reads the first 20)
BUDGET = 24_000  # characters of evidence (``brain.BUDGET``)
ABSTAIN_BELOW = 0.47  # "not found" when quote_cov is below this (the train5k fit, 0.4718, rounded; see the module docstring)
NOT_FOUND = "not found"


class Passage(NamedTuple):
    doc: str  # the document's entity id ("doc:<dsid>")
    i: int  # the passage's place in its document
    title: str
    text: str


class PassageIndex:
    """The bank's document text cut into passages (``size``, ``engine.windows``) in an in-memory FTS5 table, built on first use
    (``build``). Passage ``rowid`` r is ``rows[r - 1]``; ``by_doc`` gives a document's rowids in document order.
    ``PassageIndex.of(bank)`` is the bank's shared index (what ``ProseRoute`` uses); ``PassageIndex(bank)`` a private one."""

    def __init__(self, bank: FactBank, size: tuple[int, int] = PROSE_SIZE):
        self.bank = bank
        self.size = size
        self.rows: list[Passage] = []
        self.by_doc: dict[str, list[int]] = {}
        self.seconds = 0.0
        self._con: sqlite3.Connection | None = None

    @classmethod
    def of(cls, bank: FactBank, size: tuple[int, int] = PROSE_SIZE) -> PassageIndex:
        """The one index of ``bank`` for ``size``, kept on the bank object (``_prose_indexes``), so that every ``ProseRoute``
        over a bank shares it and it is built once per bank (about 110 MB and 2-3 seconds for a 5,000-document bank); it
        goes when the bank does."""
        shared = vars(bank).setdefault("_prose_indexes", {})
        if size not in shared:
            shared[size] = cls(bank, size)
        return shared[size]

    @property
    def built(self) -> bool:
        return self._con is not None

    def build(self) -> PassageIndex:
        """Cut every document's stored text (``entities_fts``) and index the passages, in document id order; once."""
        if self._con is not None:
            return self
        t = time.perf_counter()
        kinds, names = self.bank.kinds, self.bank.names
        texts = {r[0]: r[1] or "" for r in self.bank.con.execute("SELECT id, text FROM entities_fts") if kinds.get(r[0]) == "document"}
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE p USING fts5(title, body, tokenize='porter unicode61')")
        rows: list[Passage] = []
        by_doc: dict[str, list[int]] = {}
        for doc in sorted(texts):
            title = names.get(doc) or ""
            for i, text in enumerate(windows(texts[doc], *self.size)):
                rows.append(Passage(doc, i, title, text))
                by_doc.setdefault(doc, []).append(len(rows))
        con.executemany("INSERT INTO p(rowid, title, body) VALUES (?, ?, ?)", ((n, p.title, p.text) for n, p in enumerate(rows, start=1)))
        self.rows, self.by_doc, self._con = rows, by_doc, con
        self.seconds = round(time.perf_counter() - t, 2)
        return self

    def search(self, question: str, exclude: Iterable[str] = ()) -> list[tuple[int, float]]:
        """Every passage holding any of the question's content words (plain search's terms, an OR query), as (rowid, BM25
        score, higher better), best first; passages of the documents in ``exclude`` are left out."""
        from cie.retrieval.lexical import _terms

        terms = list(dict.fromkeys(_terms(question)))
        if not terms:
            return []
        con = self.build()._con
        rank = f"bm25(p, {TITLE_WEIGHT}, 1.0)"
        hits = con.execute(f"SELECT rowid, {rank} FROM p WHERE p MATCH ? ORDER BY {rank}, rowid", (" OR ".join(f'"{t}"' for t in terms),))
        skip = set(exclude)
        return [(r, -s) for r, s in hits if self.rows[r - 1].doc not in skip]

    def best_document(self, question: str, exclude: Iterable[str] = (), limit: int = QUOTE_PASSAGES) -> tuple[str | None, list[Passage]]:
        """The document of the best passage and the passages to quote from: that document's matching passages in BM25 order,
        then its other passages in document order, at most ``limit``. (None, []) when no passage holds a question word."""
        hits = self.search(question, exclude)
        if not hits:
            return None, []
        doc = self.rows[hits[0][0] - 1].doc
        order = [r for r, _ in hits if self.rows[r - 1].doc == doc]
        seen = set(order)
        order += [r for r in self.by_doc[doc] if r not in seen]
        return doc, [self.rows[r - 1] for r in order[:limit]]


def coverage(weights: dict[str, float], text: str) -> float:
    """The weighted share of the question's words (stem -> weight) that a text holds, its words stemmed (``engine.stem``)."""
    have = {stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}
    return sum(w for t, w in weights.items() if t in have) / (sum(weights.values()) or 1.0)


class ProseRoute:
    """The free-text route over one bank: ``answer`` quotes the best document's passages and abstains when the quote covers
    less than ``threshold`` of the question's words weighted by rarity. ``index`` is the bank's shared passage index
    (``PassageIndex.of``) unless one is given; it is built on the first question asked of the bank, by any route over it."""

    def __init__(self, bank: FactBank, *, budget: int = BUDGET, threshold: float = ABSTAIN_BELOW, index: PassageIndex | None = None):
        self.bank = bank
        self.budget = budget
        self.threshold = threshold
        self.index = index if index is not None else PassageIndex.of(bank)
        self._n: int | None = None

    def entity_count(self) -> int:
        if self._n is None:
            self._n = self.bank.con.execute("SELECT count(*) FROM entities_fts").fetchone()[0]
        return self._n

    def left_out(self, exclude: Iterable[str]) -> list[str]:
        """The entities the documents in ``exclude`` stand for: each document and the action items taken from it."""
        out: list[str] = []
        for doc in dict.fromkeys(exclude):
            if self.bank.kinds.get(doc) != "document":
                continue
            out.append(doc)
            out += [r[0] for r in self.bank.con.execute("SELECT id FROM entities WHERE source = ? AND kind = 'action_item' ORDER BY id",
                                                        (doc.removeprefix("doc:"),))]
        return out

    def weights(self, question: str, exclude: Iterable[str] = ()) -> dict[str, float]:
        """The question's words as ``FactBank.passages`` takes them (stem -> IDF over the bank's entities, the larger for two
        forms of one stem), with the documents in ``exclude`` and their action items not counted."""
        gone = self.left_out(exclude)
        n = self.entity_count() - len(gone)
        marks = ",".join("?" * len(gone))
        out: dict[str, float] = {}
        for t in sorted(set(re.findall(r"[a-z0-9]+", question.lower())) - STOP):
            if len(t) < 2:
                continue
            df = self.bank.doc_freq(t)
            if gone and df:
                df -= self.bank.con.execute(f"SELECT count(*) FROM entities_fts WHERE entities_fts MATCH ? AND id IN ({marks})",
                                            (f'"{t}"', *gone)).fetchone()[0]
            w = math.log(1 + (n - df + 0.5) / (df + 0.5))
            s = stem(t)
            out[s] = max(out.get(s, 0.0), w)
        return out

    def evidence(self, passages: list[Passage]) -> str:
        """The passages handed to quote_answer, one block each ("[passage] <title>" and its text), in order, within the budget."""
        blocks, used = [], 0
        for p in passages:
            block = f"[passage] {p.title}\n{p.text}"
            if used + len(block) > self.budget:
                break
            blocks.append(block)
            used += len(block) + 2
        return "\n\n".join(blocks)

    def answer(self, question: str, exclude: Iterable[str] = ()) -> dict[str, Any]:
        """{answer, reason, evidence, doc, quote_cov, abstained, quote}. ``answer`` is the quote, or "not found" when there is
        none or ``quote_cov`` (its weighted share of the question's words) is below the threshold; ``quote`` is the quote
        either way ("" when there is none); ``doc`` the document quoted from ("doc:<dsid>", None when no passage holds a
        question word). ``exclude``: documents to leave out (see the module's docstring)."""
        from cie.retrieval.answer import quote_answer

        exclude = list(exclude)
        doc, passages = self.index.best_document(question, exclude)

        def done(answer: str, reason: str, quote: str = "", cov: float = 0.0) -> dict[str, Any]:
            return {"answer": answer, "reason": reason, "evidence": self.evidence(passages), "doc": doc, "quote_cov": cov,
                    "abstained": answer == NOT_FOUND, "quote": quote}

        if doc is None:
            return done(NOT_FOUND, "no passage holds a word of the question")
        items = [{"id": f"{p.doc}:{p.i}", "kind": "passage", "summary": p.title, "detail": p.text, "document_id": p.doc} for p in passages]
        quoted = quote_answer(items, question)
        if quoted is None:
            return done(NOT_FOUND, f"no sentence of {doc} holds a word of the question")
        cov = coverage(self.weights(question, exclude), quoted[0])
        if cov < self.threshold:
            return done(NOT_FOUND, f"the quote from {doc} holds {cov:.3f} of the question's words weighted by rarity, below {self.threshold}",
                        quoted[0], cov)
        return done(quoted[0], f"quoted from {len(quoted[1])} passage(s) of {doc}; it holds {cov:.3f} of the question's words weighted by rarity",
                    quoted[0], cov)
