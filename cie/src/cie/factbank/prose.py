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
from collections import Counter
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
# v18 (round 4, ``ProseRoute(..., v18=True)``): the quote chosen inside the one document (``quote_v18``). A question asks one
# thing or several ("what was the hotfix and how much jitter will the fix allow?"); each ask is a part, from a question word
# near the start of a clause to the clause's end, and gets its own sentence first. The words outside every part describe the
# document, which is already chosen, and weigh DESC_WEIGHT; the words of asking and chat weigh nothing. A sentence holding a value
# of the kind a part asks for (a date, a number, a person, a ticket key, a flag or setting), one the question does not write,
# gains KIND_BONUS. The quote keeps v16's length (QUOTE_CAP characters) and form.
QUOTE_CAP = 1100
DESC_WEIGHT = 0.3
KIND_BONUS = 0.3
QUOTE_PRIOR = 0.15  # v16's penalty for a lower-ranked passage (``quote_answer``'s prior)
TITLE_DOWN = True  # the document's title words weigh DESC_WEIGHT too
WH_WORDS = r"(?:what|what's|whats|which|who|who's|whos|whom|whose|when|when's|where|why|how)"
WH = re.compile(rf"\b{WH_WORDS}\b", re.I)
# a clause break before an ask: "and", "&", "plus", "also" or punctuation, then a question word within two words
PART_BREAK = re.compile(rf"(?:,?\s+(?:and|&|plus|also)\s+|[,;]\s+|\s+[-\u2013\u2014]+\s+|\s*[\u2013\u2014]\s*)(?=(?:[\w']+\s+){{0,2}}?{WH_WORDS}\b)", re.I)
# a question word opens a part when only words of asking and chat come before it in its clause ("hey quick q, what…", "can
# someone remind me when…"), or a verb of knowing or telling does within three words before it ("before my call can someone remind
# me what…"); otherwise it is relative ("the incident where pods failed")
PART_LEAD = frozenset(("so", "and", "but", "also", "then", "re", "ok", "okay", "hey", "hi", "yo"))
KINDS = (
    ("date", re.compile(r"^(?:when|when's)\b|^(?:what|which)\s+(?:new\s+)?(?:date|dates|day|days|time|times|slot|slots|deadline|week|month)\b|"
                        r"^(?:by when|how soon)\b", re.I)),
    ("number", re.compile(r"^how\s+(?:much|many|long|far|big|large|fast|often|soon|high|low)\b|^(?:what|which)(?:'s|\s+is|\s+are|\s+was)?"
                          r"\s+(?:the\s+)?(?:\w+\s+){0,2}?(?:percent|percentage|rate|rates|threshold|thresholds|limit|limits|size|number|count|"
                          r"multiplier|range|latency|latencies|overhead|margin|margins|budget|price|pricing|cost|ratio|split|gain|gains|turnaround|"
                          r"duration|timeout|ttl|p95|p99|target|targets|window|discount|credits?)\b", re.I)),
    ("person", re.compile(r"^(?:who|who's|whos|whom|whose)\b|^(?:which|what)\s+(?:person|people|engineer|owner|teammate|ae|se|csm|contact)\b", re.I)),
    ("key", re.compile(r"^(?:which|what)(?:'s|\s+is)?\s+(?:the\s+)?(?:\w+\s+){0,2}?(?:ticket|tickets|issue|issues|pr|prs|key|keys)\b", re.I)),
    ("code", re.compile(r"^(?:which|what)(?:'s|\s+is|\s+are)?\s+(?:the\s+)?(?:\w+\s+){0,2}?(?:flag|flags|setting|settings|env|variable|variables|"
                        r"vars|config|command|commands|endpoint|scope|scopes|parameter|parameters|header|headers)\b", re.I)),
)
MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
KIND_VALUE = {
    "date": re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}/\d{{1,2}}\b|\b{MONTHS}\.?\s+\d{{1,2}}\b|\b\d{{1,2}}\s+{MONTHS}\b|"
                       r"\b(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day)?\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b|"
                       r"\b(?:tomorrow|tonight|eod|end of (?:day|week|month))\b", re.I),
    "number": re.compile(r"\d+(?:[.,]\d+)*"),
    "person": re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z'\u2019-]+\b|@[A-Za-z][\w.-]+|^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s*(?:\([^)]*\))?\s*:"),
    "key": re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,7}\b|(?:#|\bPR\s*#?)\d{2,7}\b"),
    "code": re.compile(r"`[^`]+`|\b\w+[_=.:]\w+(?:[_=.:]\w+)*\b|--[a-z][\w-]+|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b"),
}


class Passage(NamedTuple):
    doc: str  # the document's entity id ("doc:<dsid>")
    i: int  # the passage's place in its document
    title: str
    text: str


class PassageIndex:
    """The bank's document text cut into passages (``size``, ``engine.windows``) in an FTS5 table. ``PassageIndex.of(bank)``
    is the bank's shared index (what ``ProseRoute`` uses): the one stored in the bank's file when it has one
    (``StoredPassages``, nothing to build or load), else this class, which builds the table in memory on first use
    (``build``), as does a private ``PassageIndex(bank)``. Passage ``rowid`` r is ``rows[r - 1]``; ``by_doc`` gives a
    document's rowids in document order (one run of rowids: the passages are numbered document by document)."""

    table = "p"

    def __init__(self, bank: FactBank, size: tuple[int, int] = PROSE_SIZE):
        self.bank = bank
        self.size = size
        self.rows: Any = []
        self.by_doc: Any = {}
        self.seconds = 0.0
        self._con: sqlite3.Connection | None = None

    @classmethod
    def of(cls, bank: FactBank, size: tuple[int, int] = PROSE_SIZE) -> PassageIndex:
        """The one index of ``bank`` for ``size``, kept on the bank object (``_prose_indexes``), so that every ``ProseRoute``
        over a bank shares it; it goes when the bank does. A bank file that stores its passages for this size is read from
        disk; any other is cut and indexed in memory once (about 110 MB and 2-3 seconds for a 5,000-document bank)."""
        shared = vars(bank).setdefault("_prose_indexes", {})
        if size not in shared:
            shared[size] = StoredPassages(bank, size) if cls is PassageIndex and StoredPassages.held(bank, size) else cls(bank, size)
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

    def _query(self, question: str) -> str | None:
        from cie.retrieval.lexical import _terms

        terms = list(dict.fromkeys(_terms(question)))
        return " OR ".join(f'"{t}"' for t in terms) if terms else None

    @property
    def _rank(self) -> str:
        return f"bm25({self.table}, {TITLE_WEIGHT}, 1.0)"

    def search(self, question: str, exclude: Iterable[str] = ()) -> list[tuple[int, float]]:
        """Every passage holding any of the question's content words (plain search's terms, an OR query), as (rowid, BM25
        score, higher better), best first; passages of the documents in ``exclude`` are left out."""
        match = self._query(question)
        if match is None:
            return []
        con = self.build()._con
        hits = con.execute(f"SELECT rowid, {self._rank} FROM {self.table} WHERE {self.table} MATCH ? ORDER BY {self._rank}, rowid", (match,))
        skip = set(exclude)
        if not skip:
            return [(r, -s) for r, s in hits]
        return [(r, -s) for r, s in hits if self.rows[r - 1].doc not in skip]

    def top(self, question: str, exclude: Iterable[str] = (), page: int = 32) -> int | None:
        """The rowid of the best passage outside ``exclude`` (``search``'s first hit), or None; read a page at a time, so a
        question whose words match most of the bank does not list every passage."""
        match = self._query(question)
        if match is None:
            return None
        con = self.build()._con
        skip = set(exclude)
        seen = 0
        while True:
            hits = con.execute(f"SELECT rowid FROM {self.table} WHERE {self.table} MATCH ? ORDER BY {self._rank}, rowid LIMIT ?",
                               (match, page)).fetchall()
            for (r,) in hits[seen:]:
                if not skip or self.rows[r - 1].doc not in skip:
                    return r
            if len(hits) < page:
                return None
            seen, page = len(hits), page * 4

    def top_rows(self, question: str, k: int) -> list[int]:
        """The rowids of the ``k`` best passages (``search``'s first ``k`` hits)."""
        match = self._query(question)
        if match is None:
            return []
        con = self.build()._con
        return [r for (r,) in con.execute(f"SELECT rowid FROM {self.table} WHERE {self.table} MATCH ? ORDER BY {self._rank}, rowid LIMIT ?",
                                          (match, k))]

    def doc_hits(self, question: str, doc: str) -> list[int]:
        """The rowids of one document's passages that hold a question word, best first (``search``'s hits of that document,
        in its order: a passage's BM25 score does not depend on what else is asked for)."""
        match = self._query(question)
        own = self.by_doc[doc] if match is not None and doc in self.by_doc else []
        if not own:
            return []
        con = self.build()._con
        return [r for (r,) in con.execute(f"SELECT rowid FROM {self.table} WHERE {self.table} MATCH ? AND rowid BETWEEN ? AND ? "
                                          f"ORDER BY {self._rank}, rowid", (match, own[0], own[-1]))]

    def best_document(self, question: str, exclude: Iterable[str] = (), limit: int = QUOTE_PASSAGES) -> tuple[str | None, list[Passage]]:
        """The document of the best passage and the passages to quote from: that document's matching passages in BM25 order,
        then its other passages in document order, at most ``limit``. (None, []) when no passage holds a question word."""
        best = self.top(question, exclude)
        if best is None:
            return None, []
        doc = self.rows[best - 1].doc
        order = self.doc_hits(question, doc)
        seen = set(order)
        order += [r for r in self.by_doc[doc] if r not in seen]
        return doc, [self.rows[r - 1] for r in order[:limit]]


class _StoredRows:
    """``rows[r - 1]`` of a stored index: the passage, with its text cut again from its document."""

    def __init__(self, ix: StoredPassages):
        self.ix = ix

    def __getitem__(self, i: int) -> Passage:
        return self.ix.passage(i + 1)

    def __len__(self) -> int:
        return self.ix.count

    def __eq__(self, other: object) -> bool:
        return isinstance(other, list) and len(self) == len(other) and all(self[i] == other[i] for i in range(len(other)))

    __hash__ = None  # type: ignore[assignment]


class _StoredByDoc:
    """``by_doc[doc]`` of a stored index: the document's passage rowids in document order."""

    def __init__(self, ix: StoredPassages):
        self.ix = ix

    def __contains__(self, doc: object) -> bool:
        return self.ix.span(str(doc)) is not None

    def __getitem__(self, doc: str) -> list[int]:
        span = self.ix.span(doc)
        if span is None:
            raise KeyError(doc)
        return list(range(span[0], span[0] + span[1]))

    def get(self, doc: str, default: Any = None) -> Any:
        return self[doc] if doc in self else default

    def __iter__(self):
        return (r[0] for r in self.ix.bank.con.execute("SELECT doc FROM passage_docs ORDER BY doc"))

    def __len__(self) -> int:
        return self.ix.bank.con.execute("SELECT count(*) FROM passage_docs").fetchone()[0]

    def values(self):
        return (self[d] for d in self)


class StoredPassages(PassageIndex):
    """The passage index stored in the bank's file (``cie.factbank.store.build_passages``): the same passages, rowids and
    ranking as the in-memory index, with nothing built or loaded by the process. Only the index is stored; a passage's
    text is cut again from its document (``engine.windows``) when it is read."""

    table = "passages_fts"
    KEPT = 64  # documents whose cut text is kept

    def __init__(self, bank: FactBank, size: tuple[int, int] = PROSE_SIZE):
        super().__init__(bank, size)
        self._con = bank.con
        self.rows, self.by_doc = _StoredRows(self), _StoredByDoc(self)
        self._cut: dict[str, list[str]] = {}
        self._spans: dict[str, tuple[int, int] | None] = {}
        self._count: int | None = None

    @staticmethod
    def held(bank: FactBank, size: tuple[int, int]) -> bool:
        from cie.factbank import store

        return store.has(bank.con, "passages_fts") and (store.meta(bank.con).get("passages") or {}).get("size") == list(size)

    @property
    def count(self) -> int:
        if self._count is None:
            self._count = int((self.bank.con.execute("SELECT max(first + n - 1) FROM passage_docs").fetchone()[0]) or 0)
        return self._count

    def span(self, doc: str) -> tuple[int, int] | None:
        """A document's first passage rowid and how many passages it has."""
        if doc not in self._spans:
            if len(self._spans) > 4096:
                self._spans.clear()
            row = self.bank.con.execute("SELECT first, n FROM passage_docs WHERE doc = ?", (doc,)).fetchone()
            self._spans[doc] = None if row is None else (row[0], row[1])
        return self._spans[doc]

    def passage(self, r: int) -> Passage:
        row = self.bank.con.execute("SELECT doc, first, n FROM passage_docs WHERE first <= ? ORDER BY first DESC LIMIT 1", (r,)).fetchone()
        if row is None or r < 1 or r >= row[1] + row[2]:
            raise IndexError(r)
        doc, i = row[0], r - row[1]
        if doc not in self._cut:
            if len(self._cut) >= self.KEPT:
                self._cut.pop(next(iter(self._cut)))
            self._cut[doc] = windows(self.bank.text_of(doc) or "", *self.size)
        return Passage(doc, i, self.bank.names.get(doc) or "", self._cut[doc][i])

    def search(self, question: str, exclude: Iterable[str] = ()) -> list[tuple[int, float]]:
        hits = super().search(question)
        spans = [s for d in set(exclude) if (s := self.span(d)) is not None]
        if not spans:
            return hits
        return [(r, s) for r, s in hits if not any(a <= r < a + n for a, n in spans)]

    def top(self, question: str, exclude: Iterable[str] = (), page: int = 32) -> int | None:
        match = self._query(question)
        if match is None:
            return None
        spans = [s for d in set(exclude) if (s := self.span(d)) is not None]
        seen = 0
        while True:
            hits = self._con.execute(f"SELECT rowid FROM {self.table} WHERE {self.table} MATCH ? ORDER BY {self._rank}, rowid LIMIT ?",
                                     (match, page)).fetchall()
            for (r,) in hits[seen:]:
                if not any(a <= r < a + n for a, n in spans):
                    return r
            if len(hits) < page:
                return None
            seen, page = len(hits), page * 4


def coverage(weights: dict[str, float], text: str) -> float:
    """The weighted share of the question's words (stem -> weight) that a text holds, its words stemmed (``engine.stem``)."""
    have = {stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}
    return sum(w for t, w in weights.items() if t in have) / (sum(weights.values()) or 1.0)


def question_parts(question: str) -> tuple[list[str], str]:
    """v18: the asks of a question and the words outside them (the description). The question is cut at the clause breaks before
    a question word (``PART_BREAK``); a clause whose question word opens an ask (``PART_LEAD``, words of asking and chat, or a
    verb of knowing or telling among the three words before it) gives one part, from that word to the clause's end; every other word is description ("re the vault transit rewrap incident where runner pods couldn't
    claim tokens" before "— what was the hotfix")."""
    from cie.factbank.plans import EMBED_SKIP, EMBED_VERBS
    from cie.factbank.records import FILLER

    lead = FILLER | STOP | PART_LEAD | EMBED_VERBS | EMBED_SKIP
    parts, desc = [], []
    for clause in PART_BREAK.split(question):
        m = next((m for m in WH.finditer(clause) if all(w in lead for w in re.findall(r"[a-z']+", clause[:m.start()].lower()))
                  or set(re.findall(r"[a-z']+", clause[:m.start()].lower())[-3:]) & EMBED_VERBS), None)
        if m:
            parts.append(clause[m.start():].strip())
            desc.append(clause[:m.start()])
        else:
            desc.append(clause)
    return parts, " ".join(desc)


def part_kind(part: str) -> str | None:
    """v18: what a part asks for: "date", "number", "person", "key", "code", or None (``KINDS``)."""
    return next((k for k, r in KINDS if r.search(part)), None)


def quote_v18(items: list[dict[str, Any]], question: str, cap: int = QUOTE_CAP, pool: int = 20, window: int = 1,
              stop: Iterable[str] = ()) -> tuple[str, list[dict[str, Any]]] | None:
    """v18's quote from one document's passages (``items`` as ``quote_answer`` takes them): each part's best sentence first, then
    the best sentences overall, each with the sentence after it, at most ``cap`` characters with the labels, in the form of
    ``cie.retrieval.answer.quote_answer``. A sentence scores the share of a part's words it holds, each word weighted by its
    rarity among the document's sentences (and ``DESC_WEIGHT`` for a description word), plus ``KIND_BONUS`` for a value of the
    part's kind that the question does not write, less ``QUOTE_PRIOR`` for a lower-ranked passage. ``stop``: words that weigh
    nothing (the words of asking and chat). None when no sentence holds a word of the question."""
    from cie.retrieval import answer as A
    from cie.retrieval.bm25 import query_terms

    head = items[:pool]
    stop = {t for w in stop for t in A._tokens(w)}
    terms = [t for t in query_terms(question) if len(t) > 2 and t not in stop]
    if not terms or not head:
        return None
    parts, desc = question_parts(question)
    sents: list[list[str]] = []
    for it in head:
        body = re.sub(r"[ \t]+", " ", it.get("detail") or "")
        sents.append([x.strip() for x in A._SENT_SPLIT.split(body) if len(x.strip()) >= 25])
    toks = [[A._tokens(x) for x in ss] for ss in sents]
    n = sum(len(ss) for ss in sents) or 1
    df = Counter(t for ts in toks for tk in ts for t in tk)
    idf = {t: math.log(1 + n / (1 + df[t])) for t in terms}
    asked = [[t for t in query_terms(p) if t in idf] for p in parts] or [terms]
    kinds = [part_kind(p) for p in parts] or [None]
    in_parts = {t for ts in asked for t in ts}
    titled = A._tokens(head[0].get("summary") or "") if TITLE_DOWN else set()  # the document's title describes it, as the description does
    weight = {t: idf[t] * (1.0 if (t in in_parts or not parts) and t not in titled else DESC_WEIGHT) for t in terms}

    asked_values = {k: {m.group(0).lower() for m in r.finditer(question)} for k, r in KIND_VALUE.items()}

    def has_kind(x: str, kind: str | None) -> bool:
        return kind is not None and any(m.group(0).lower() not in asked_values[kind] for m in KIND_VALUE[kind].finditer(x))

    def score(i: int, j: int, ts: list[str], kind: str | None, w: dict[str, float]) -> float:
        total = sum(w[t] for t in ts) or 1.0
        share = sum(w[t] for t in ts if t in toks[i][j]) / total
        if share <= 0:
            return 0.0
        return share + (KIND_BONUS if has_kind(sents[i][j], kind) else 0.0) - QUOTE_PRIOR * i / len(head)

    def label(i: int) -> str:
        t = re.sub(r"\s+", " ", head[i].get("summary") or "").strip()
        return t if len(t) <= 60 else t[:60].rsplit(" ", 1)[0].rstrip(" ,;:-\u2014") + "\u2026"

    chosen: dict[int, set[int]] = {}
    seen: set[str] = set()
    used = 0

    def take(i: int, j: int) -> None:
        nonlocal used
        for k in range(j, min(j + window + 1, len(sents[i]))):
            x = sents[i][k]
            key = x[:80].lower()
            if key in seen:
                continue
            cost = len(x) + 5 + (0 if i in chosen else len(label(i)) + 10)
            if used + cost > cap:
                continue
            seen.add(key)
            chosen.setdefault(i, set()).add(k)
            used += cost

    cells = [(i, j) for i in range(len(sents)) for j in range(len(sents[i]))]
    for ts, kind in zip(asked, kinds):
        w = {t: idf[t] * (DESC_WEIGHT if t in titled else 1.0) for t in ts}
        best = max(cells, key=lambda c: (score(c[0], c[1], ts, kind, w), -c[0], -c[1]), default=None) if ts else None
        if best is not None and score(best[0], best[1], ts, kind, w) > 0:
            take(*best)
    ranked = sorted(((max(score(i, j, terms, k, weight) for k in kinds), i, j) for i, j in cells), key=lambda x: (-x[0], x[1], x[2]))
    for sc, i, j in ranked:
        if sc <= 0 or used >= cap * 0.95:
            break
        take(i, j)
    if not chosen:
        return None
    out, cites = [], []
    for m, i in enumerate(sorted(chosen), start=1):
        cites.append(A._cite(head[i], m))
        quote = " ... ".join(sents[i][k] for k in sorted(chosen[i]))
        out.append(f"{label(i)}: \"{quote}\" [{m}].")
    return " ".join(out), cites


class ProseRoute:
    """The free-text route over one bank: ``answer`` quotes the best document's passages and abstains when the quote covers
    less than ``threshold`` of the question's words weighted by rarity. ``index`` is the bank's shared passage index
    (``PassageIndex.of``) unless one is given; it is built on the first question asked of the bank, by any route over it."""

    def __init__(self, bank: FactBank, *, budget: int = BUDGET, threshold: float = ABSTAIN_BELOW, index: PassageIndex | None = None,
                 v18: bool = False, stop: Iterable[str] = ()):
        self.bank = bank
        self.v18 = v18  # round 4's quote (``quote_v18``), with ``stop`` as its words of asking and chat
        self.stop = frozenset(stop)
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
        if self.v18 and cov >= self.threshold:
            # v18 answers with its own quote; whether to answer stays v16's decision, on v16's quote
            quoted = quote_v18(items, question, stop=self.stop) or quoted
        if cov < self.threshold:
            return done(NOT_FOUND, f"the quote from {doc} holds {cov:.3f} of the question's words weighted by rarity, below {self.threshold}",
                        quoted[0], cov)
        return done(quoted[0], f"quoted from {len(quoted[1])} passage(s) of {doc}; it holds {cov:.3f} of the question's words weighted by rarity",
                    quoted[0], cov)
