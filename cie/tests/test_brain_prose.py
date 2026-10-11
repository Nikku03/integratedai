"""The company brain's free-text route (v16, ``cie.factbank.prose``): the passage index over the bank's document text, the one
document quoted from, the quote, and the abstention rule (``quote_cov`` below 0.47 means "not found")."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from cie.factbank import bank as B
from cie.factbank import prose as PR
from cie.factbank.engine import FactBank, stem, windows
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)
RUNBOOK = ("Overview of the service. " * 40 + "To verify the telemetry mode, query the status endpoint on port 9100. "
           "The mode should then read local-only. " + "Unrelated closing notes follow here. " * 30)


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)], meta=meta, updated=WHEN,
                     keys=list(keys))


DOCS = [
    (_doc("d1", "linear", "Fix keycard reader timeouts", {"key": "ENG-11", "status": "In Progress", "assignee": "Omar Singh"},
          "Badge readers time out at night.", ["ENG-11"]), {}),
    (_doc("d3", "linear", "Replace the badge printer", {"key": "ENG-13", "status": "Todo", "assignee": "Liam Chen"}, "", ["ENG-13"]), {}),
    (_doc("d5", "confluence", "Telemetry Runbook: local-only mode", {"author": "Maya Chen", "space": "eng-private"}, RUNBOOK), {}),
    (_doc("d6", "fireflies", "Badge rollout sync", {"redwood_attendees": ["Omar Singh", "Lena Muller"]}, "We talked about badges."),
     {"action_items": ["Priya | send the badge rollout checklist to facilities | Due: 2026-03-25"]}),
    (_doc("d7", "confluence", "Lobby kiosk audit", {"author": "Liam Chen"}, "Scope and owners are listed below. " * 6), {}),
    (_doc("d8", "confluence", "Facilities notes", {"author": "Omar Singh"}, "The lobby kiosk audit is due in May; the lobby kiosk audit list grows."),
     {}),
]
PORT = "Which port does the status endpoint use?"
ZEBRA = "How does the zebra crossing policy handle the badge printer?"


@pytest.fixture
def bank(tmp_path):
    B.build(tmp_path / "factbank_v2.sqlite", DOCS, text_facts=True)
    return FactBank(tmp_path / "factbank_v2.sqlite")


@pytest.fixture
def route(bank):
    return PR.ProseRoute(bank)


def stored_text(bank, doc):
    return bank.con.execute("SELECT text FROM entities_fts WHERE id = ?", (doc,)).fetchone()[0]


# ------------------------------------------------------------------ the passage index
def test_the_index_is_built_once_on_first_use(bank, route):
    assert not route.index.built and route.index.rows == []
    route.answer(PORT)
    ix = route.index
    assert ix.built and ix.seconds >= 0
    con, rows = ix._con, ix.rows
    assert ix.build() is ix and ix._con is con and ix.rows is rows, "a second build changes nothing"


def test_the_index_holds_every_documents_stored_text_cut_in_windows(bank):
    ix = PR.PassageIndex(bank).build()
    docs = sorted(e for e, k in bank.kinds.items() if k == "document")
    assert sorted(ix.by_doc) == docs, "documents only: no action items, people or keys"
    for doc in docs:
        cut = windows(stored_text(bank, doc), *PR.PROSE_SIZE)
        assert [ix.rows[r - 1].text for r in ix.by_doc[doc]] == cut, "what FactBank.passages reads, cut as the brain cuts it"
        assert {ix.rows[r - 1].title for r in ix.by_doc[doc]} == {bank.names[doc]}
        assert [ix.rows[r - 1].i for r in ix.by_doc[doc]] == list(range(len(cut)))
    assert len(ix.by_doc["doc:d5"]) == 3 and len(ix.rows) == sum(len(v) for v in ix.by_doc.values())
    assert [p.doc for p in ix.rows] == sorted(p.doc for p in ix.rows), "rowids follow document ids"


def test_search_ranks_passages_by_bm25(bank):
    ix = PR.PassageIndex(bank)
    hits = ix.search(PORT)
    assert ix.rows[hits[0][0] - 1] == ("doc:d5", 1, "Telemetry Runbook: local-only mode", ix.rows[hits[0][0] - 1].text)
    assert "port 9100" in ix.rows[hits[0][0] - 1].text
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True) and all(s > 0 for _, s in hits)
    assert ix.search("Zygomorphic quasars?") == [] and ix.search("Is it?") == [], "no passage holds a word, or no word to search"


def test_the_title_weighs_more_than_the_body(bank, monkeypatch):
    ix = PR.PassageIndex(bank)
    q = "What is in the lobby kiosk audit?"
    assert [ix.rows[r - 1].doc for r, _ in ix.search(q)] == ["doc:d7", "doc:d8"], "the words in d7's title, twice in d8's text"
    monkeypatch.setattr(PR, "TITLE_WEIGHT", 0.0)
    assert [ix.rows[r - 1].doc for r, _ in ix.search(q)] == ["doc:d8", "doc:d7"]


def test_every_passage_of_a_document_carries_its_title(bank):
    ix = PR.PassageIndex(bank)
    hits = ix.search("Which runbook?")
    assert sorted(r for r, _ in hits) == ix.by_doc["doc:d5"], "a word of the title matches every passage of the document"


def test_one_document_its_matching_passages_first(bank):
    ix = PR.PassageIndex(bank)
    doc, ps = ix.best_document(PORT)
    assert doc == "doc:d5" and [p.i for p in ps] == [1, 0, 2], "the matching passage, then the rest in document order"
    assert {p.doc for p in ps} == {"doc:d5"}, "other documents match too, but only the best passage's document is quoted"
    assert {ix.rows[r - 1].doc for r, _ in ix.search(PORT)} > {"doc:d5"}
    assert [p.i for p in ix.best_document(PORT, limit=2)[1]] == [1, 0]
    assert ix.best_document("Zygomorphic quasars?") == (None, [])


def test_documents_left_out(bank):
    ix = PR.PassageIndex(bank)
    doc, ps = ix.best_document(PORT, exclude=["doc:d5"])
    assert doc not in (None, "doc:d5") and all(p.doc == doc for p in ps)
    assert all(ix.rows[r - 1].doc != "doc:d5" for r, _ in ix.search(PORT, ["doc:d5"]))


# ------------------------------------------------------------------ the answer
def test_answer_quotes_the_best_document(route):
    r = route.answer(PORT)
    assert set(r) >= {"answer", "reason", "evidence", "doc", "quote_cov", "abstained"}
    assert not r["abstained"] and r["answer"] == r["quote"] and "port 9100" in r["answer"] and "Telemetry Runbook" in r["answer"]
    assert r["doc"] == "doc:d5" and "doc:d5" in r["reason"] and r["quote_cov"] >= PR.ABSTAIN_BELOW
    blocks = r["evidence"].split("\n\n")
    assert len(blocks) == 3 and all(b.startswith("[passage] Telemetry Runbook: local-only mode\n") for b in blocks)
    assert "port 9100" in blocks[0], "the passages in the order handed to quote_answer"
    assert len(r["evidence"]) <= PR.BUDGET


def test_evidence_within_a_small_budget(bank):
    r = PR.ProseRoute(bank, budget=1200).answer(PORT)
    assert r["evidence"].startswith("[passage] ") and len(r["evidence"]) <= 1200 and r["evidence"].count("[passage] ") == 1
    assert r["answer"] == r["quote"], "the budget cuts the evidence, not what quote_answer reads"


def test_not_found_when_the_quote_misses_the_rare_words(route):
    r = route.answer(ZEBRA)
    assert r["abstained"] and r["answer"] == "not found" and r["doc"] == "doc:d3"
    assert r["quote"] and "badge printer" in r["quote"], "the quote is kept for inspection"
    assert r["quote_cov"] < PR.ABSTAIN_BELOW and "below 0.47" in r["reason"] and r["evidence"].startswith("[passage] Replace the badge printer")


def test_not_found_when_no_passage_matches(route):
    r = route.answer("Zygomorphic quasars?")
    assert r == {"answer": "not found", "reason": "no passage holds a word of the question", "evidence": "", "doc": None, "quote_cov": 0.0,
                 "abstained": True, "quote": ""}


def test_not_found_when_no_sentence_can_be_quoted(route):
    r = route.answer("What is in the lobby kiosk audit?")  # d7's title line is too short to quote; its text holds no question word
    assert r["doc"] == "doc:d7" and r["abstained"] and r["quote"] == "" and r["quote_cov"] == 0.0
    assert r["reason"] == "no sentence of doc:d7 holds a word of the question" and r["evidence"]


def test_quote_answer_declining_means_not_found(route, monkeypatch):
    import cie.retrieval.answer as A

    monkeypatch.setattr(A, "quote_answer", lambda items, question: None)
    r = route.answer(PORT)
    assert (r["answer"], r["abstained"], r["doc"], r["quote"]) == ("not found", True, "doc:d5", "") and r["evidence"]


def test_the_threshold(bank):
    assert not PR.ProseRoute(bank, threshold=0.0).answer(ZEBRA)["abstained"]
    assert PR.ProseRoute(bank, threshold=1.01).answer(PORT)["abstained"]
    assert PR.ABSTAIN_BELOW == 0.47


# ------------------------------------------------------------------ quote_cov
def test_weights_are_the_passages_idf(bank, route):
    q = "Who sends the badge rollout checklist to facilities, and is it 2 weeks late?"
    n = bank.con.execute("SELECT count(*) FROM entities_fts").fetchone()[0]
    want = {}
    for t in {"sends", "badge", "rollout", "checklist", "facilities", "weeks", "late"}:  # stop words, "2" and "is" are not counted
        want[stem(t)] = max(want.get(stem(t), 0.0), math.log(1 + (n - bank.doc_freq(t) + 0.5) / (bank.doc_freq(t) + 0.5)))
    got = route.weights(q)
    assert got.keys() == want.keys() and all(math.isclose(got[k], want[k]) for k in want)


def test_weights_without_the_documents_left_out(bank, route):
    assert route.left_out(["doc:d6"]) == ["doc:d6", "action:d6:0"], "a meeting and the action items taken from it"
    assert route.left_out(["person:priya", "doc:nope"]) == []
    n = bank.con.execute("SELECT count(*) FROM entities_fts").fetchone()[0]
    assert bank.doc_freq("checklist") == 1
    assert math.isclose(route.weights("checklist")["checklist"], math.log(1 + (n - 1 + 0.5) / 1.5))
    assert math.isclose(route.weights("checklist", ["doc:d6"])["checklist"], math.log(1 + (n - 2 + 0.5) / 0.5))
    assert route.weights("checklist") == route.weights("checklist", ["doc:nope"])


def test_coverage():
    assert PR.coverage({"port": 3.0, "zebra": 1.0}, "Query PORT 9100.") == 0.75
    assert PR.coverage({"badge": 1.0}, "Badges") == 0.0 and PR.coverage({stem("badges"): 1.0}, "badges") == 1.0, "words as engine.stem takes them"
    assert PR.coverage({}, "anything") == 0.0


def test_quote_cov_is_the_coverage_of_the_quote(route):
    r = route.answer(PORT)
    assert math.isclose(r["quote_cov"], PR.coverage(route.weights(PORT), r["quote"]))
    left = route.answer(PORT, exclude=["doc:d5"])
    assert left["doc"] != "doc:d5" and left["abstained"], "with the runbook left out the question has no answer"
