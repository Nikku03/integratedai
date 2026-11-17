"""Building a fact bank a batch at a time, and bringing one up to date without building it again (``bank.sync``): after
any run of additions, changes and removals the bank holds the rows a fresh build of the same documents holds, in its own
tables and in the derived ones (``cie.factbank.store``)."""

from __future__ import annotations

import random
import sqlite3
from datetime import UTC, datetime

import pytest

from cie.factbank import bank as B
from cie.factbank import store
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)
PEOPLE = ["Maya Chen", "Omar Singh", "Priya Nair", "Liam Chen", "Ava Chen", "Dana Reyes", "maya chen", "OMAR SINGH"]
RARE = ["Zed Okafor", "Uma Brandt", "Ines Duarte", "Kofi Mensah"]  # each named by one or two documents: they come and go
STATUS = ["Open", "Done", "In Progress", "Blocked"]
WORDS = ("allocator latency batches rollout quota billing export webhook retries staging cache index shard tenant audit "
         "pipeline schema migration backlog dashboard").split()


def make(i: int, rng: random.Random, n: int) -> tuple[SourceDoc, dict]:
    """Document ``i`` of a company of ``n``: a ticket that names people, cites other tickets by key (some that do not
    exist, some in another case), may share an extra identifier with others, and may hold action items."""
    key = f"ENG-{100 + i}"
    cites = [f"ENG-{100 + rng.randrange(n + 3)}" for _ in range(rng.randrange(3))]
    if cites and rng.random() < 0.3:
        cites[0] = cites[0].lower()  # the key written another way: the same identifier
    meta = {"key": key, "status": rng.choice(STATUS), "assignee": rng.choice(PEOPLE), "creator": rng.choice(PEOPLE),
            "reviewers": rng.sample(PEOPLE, rng.randrange(3)), "linked_issues": cites, "due_date": f"2026-04-{1 + rng.randrange(28):02d}",
            "crm_account_id": f"ACC-{rng.randrange(4)}" if rng.random() < 0.4 else ""}
    if i % 5 == 0:
        meta["reporter"] = RARE[i // 5 % len(RARE)]
    keys = [key] + ([f"id:acc-{rng.randrange(4)}"] if rng.random() < 0.3 else [])  # an identifier several documents carry
    body = " ".join(rng.choice(WORDS) for _ in range(rng.randrange(20, 260))) + f". Shipped on 2026-05-{1 + rng.randrange(28):02d} with {key}."
    raw = {"action_items": [f"{rng.choice(PEOPLE[:6])} - send the {rng.choice(WORDS)} report to finance - Due: 2026-05-{1 + rng.randrange(28):02d}"
                            for _ in range(rng.randrange(3))]}
    sd = SourceDoc(dsid=f"d{i:03d}", source=rng.choice(["linear", "jira", "confluence"]), rel=f"x/d{i:03d}.json",
                   title=f"{rng.choice(WORDS).title()} {rng.choice(WORDS)} work {i}", fields=[("body", body)], meta=meta, updated=WHEN, keys=keys)
    return sd, raw


def company(seed: int, n: int) -> dict[str, tuple[SourceDoc, dict]]:
    rng = random.Random(seed)
    return {f"d{i:03d}": make(i, rng, n) for i in range(n)}


TABLES = {
    "sources": "SELECT * FROM sources",
    "entities": "SELECT * FROM entities",
    "aliases": "SELECT * FROM aliases",
    "facts": "SELECT * FROM facts",
    "source_hashes": "SELECT * FROM source_hashes",
    "entities_fts": "SELECT id, name, text FROM entities_fts",
    "text_rows": "SELECT t.id, f.id, f.name FROM text_rows t JOIN entities_fts f ON f.rowid = t.rid",
    "doc_fields": "SELECT * FROM doc_fields",
    "schema_fields": "SELECT * FROM schema_fields",
    "passage_docs": "SELECT doc, n FROM passage_docs",
}


ORDERED = ("sources", "entities", "aliases", "facts", "doc_fields", "entities_fts")  # tables whose rows have an order


def rows(path, with_rowid: bool = False) -> dict[str, list]:
    """Every table's rows: sorted, or (``with_rowid``) with their place in the table."""
    con = sqlite3.connect(path)
    out = {}
    for name, sql in TABLES.items():
        if with_rowid and name in ORDERED:
            sql = sql.replace("SELECT ", "SELECT rowid, ", 1) + " ORDER BY rowid"
        got = con.execute(sql).fetchall()
        out[name] = got if with_rowid and name in ORDERED else sorted(got, key=repr)
    if with_rowid:
        out["passages"] = con.execute("SELECT doc, first, n FROM passage_docs ORDER BY first").fetchall()
    out["meta"] = sorted((k, repr(v)) for k, v in store.meta(con).items() if k != "revision")
    con.close()
    return out


def passages_found(path, words: list[str]) -> list[list]:
    """What the stored passage index finds for each word: the documents, by rank (rowids differ after an update)."""
    con = sqlite3.connect(path)
    out = []
    for w in words:
        hits = con.execute("SELECT d.doc, p.rowid - d.first, round(bm25(passages_fts), 6) FROM passages_fts p JOIN passage_docs d "
                           "ON d.first = (SELECT max(first) FROM passage_docs WHERE first <= p.rowid) WHERE passages_fts MATCH ?", (w,)).fetchall()
        out.append(sorted(hits))
    con.close()
    return out


def test_a_build_does_not_depend_on_its_batches(tmp_path):
    docs = list(company(1, 40).values())
    a, b, c = (tmp_path / f"{n}.sqlite" for n in "abc")
    ra, rb, rc = B.build(a, docs, text_facts=True, batch=1), B.build(b, iter(docs), text_facts=True, batch=7), B.build(c, docs, text_facts=True)
    assert ra["check"]["ok"] and (ra["sources"], ra["entities"], ra["facts"]) == (rb["sources"], rb["entities"], rb["facts"]) == \
        (rc["sources"], rc["entities"], rc["facts"]) and ra["sources"] == 40
    assert rows(a, True) == rows(b, True) == rows(c, True), "the same rows in the same order, whatever the batch"
    con = sqlite3.connect(a)
    assert con.execute("SELECT count(*) FROM entities WHERE kind = 'identifier'").fetchone()[0] > 0, "a key no document carries stays an identifier"
    held = {r[0] for r in con.execute("SELECT alias FROM aliases WHERE entity LIKE 'doc:%'")}
    assert not [r for r in con.execute("SELECT id FROM entities WHERE kind = 'identifier'") if r[0][4:] in held], "one a document carries does not"
    shared = con.execute("SELECT alias, min(entity) FROM aliases WHERE entity LIKE 'doc:%' GROUP BY alias HAVING count(*) > 1").fetchall()
    cited = [(a_, d) for a_, d in shared if con.execute("SELECT 1 FROM facts WHERE parameter = 'crm_account_id' AND lower(value) = ?",
                                                        (a_[3:],)).fetchone()]
    assert cited, "the company has an identifier that several documents carry and another cites"
    for alias, first in cited:
        got = {r[0] for r in con.execute("SELECT value_entity FROM facts WHERE parameter = 'crm_account_id' AND lower(value) = ?", (alias[3:],))}
        assert got == {first}, "it points to the document with the smallest id"


@pytest.mark.parametrize("seed", [3, 4, 5])
def test_a_synced_bank_holds_what_a_fresh_build_holds(tmp_path, seed):
    rng = random.Random(seed)
    n = 36
    pool = company(seed, n)  # every document the company may ever hold
    now = {k: pool[k] for k in sorted(pool)[:20]}
    path, fresh = tmp_path / "bank.sqlite", tmp_path / "fresh.sqlite"
    B.build(path, list(now.values()), text_facts=True)
    words = ["allocator", "billing", "webhook", "shipped", "work"]
    for step in range(6):
        gone = rng.sample(sorted(now), rng.randrange(1, 5))
        for k in gone:
            del now[k]
        for k in rng.sample(sorted(set(pool) - set(now)), rng.randrange(1, 6)):
            now[k] = pool[k]
        for k in rng.sample(sorted(now), 3):  # changed in place: other people, other keys cited, another text
            now[k] = make(int(k[1:]), random.Random(seed * 1000 + step * 37 + int(k[1:])), n)
        rep = B.sync(path, [now[k] for k in sorted(now)], text_facts=True, batch=rng.choice([1, 4, 500]))
        assert rep["sources"] == len(now) and rep["revision"] == store.revision(sqlite3.connect(path)) >= step + 1
        B.build(fresh, [now[k] for k in sorted(now)], text_facts=True)
        got, want = rows(path), rows(fresh)
        for t in want:
            assert got[t] == want[t], f"step {step}: {t} differs"
        assert passages_found(path, words) == passages_found(fresh, words), f"step {step}: the passage index finds the same"
        assert B.check(sqlite3.connect(path))["ok"]
    assert B.sync(path, [now[k] for k in sorted(now)], text_facts=True) | {"revision": 0} == \
        {"added": 0, "changed": 0, "removed": 0, "same": len(now), "adopted": 0, "sources": len(now), "revision": 0,
         "facts": sqlite3.connect(path).execute("SELECT count(*) FROM facts").fetchone()[0]}, "nothing changed: nothing is read again"
    assert store.ensure(path) == {}, "and the derived tables are whole"


def test_sync_options(tmp_path):
    pool = company(9, 12)
    docs = [pool[k] for k in sorted(pool)]
    path = tmp_path / "bank.sqlite"
    B.build(path, docs[:8], text_facts=True)
    rep = B.sync(path, docs[8:10], text_facts=True, remove_missing=False)
    assert (rep["added"], rep["removed"], rep["sources"]) == (2, 0, 10), "only what changed is given: nothing is taken out"
    with pytest.raises(ValueError, match="given twice"):
        B.sync(path, [docs[0], docs[0]], text_facts=True)
    con = sqlite3.connect(path)
    con.execute("DELETE FROM source_hashes")  # a bank built before hashes were kept
    con.commit()
    con.close()
    rep = B.sync(path, docs[:10], text_facts=True, adopt=True)
    assert (rep["adopted"], rep["changed"], rep["same"]) == (10, 0, 0)
    assert B.sync(path, docs[:10], text_facts=True)["same"] == 10
    con = sqlite3.connect(path)
    con.execute("DELETE FROM source_hashes")
    con.commit()
    con.close()
    assert B.sync(path, docs[:10], text_facts=True)["changed"] == 10, "without adopt, a document with no hash is read again"
    sd, raw = docs[0]
    assert B.doc_hash(sd, raw, True) != B.doc_hash(sd, raw, False) and B.doc_hash(sd, raw) == B.doc_hash(sd, dict(raw))
    other = SourceDoc(**{**sd.__dict__, "title": sd.title + "!"})
    assert B.doc_hash(other, raw) != B.doc_hash(sd, raw)


def test_an_open_bank_knows_it_went_stale(tmp_path):
    from cie.factbank.engine import FactBank

    pool = company(21, 10)
    docs = [pool[k] for k in sorted(pool)]
    path = tmp_path / "bank.sqlite"
    B.build(path, docs[:8], text_facts=True)
    fb = FactBank(path)
    key = docs[0][0].meta["key"]
    before = fb.ask(f"What is the status of {key}?").answer
    assert not fb.stale() and before == docs[0][0].meta["status"]
    sd = docs[0][0]
    other = next(s for s in STATUS if s != sd.meta["status"])
    changed = SourceDoc(**{**sd.__dict__, "meta": {**sd.meta, "status": other}})
    rep = B.sync(path, [(changed, docs[0][1]), *docs[1:]], text_facts=True)
    assert (rep["changed"], rep["added"], rep["same"]) == (1, 2, 7)
    assert fb.stale(), "the file changed under it"
    again = FactBank(path)
    assert not again.stale() and again.ask(f"What is the status of {key}?").answer == other
    assert "doc:d009" in again.names and "doc:d009" not in fb.names, "a document added by the update: the stale bank does not know it"
    fresh = tmp_path / "fresh.sqlite"
    B.build(fresh, [(changed, docs[0][1]), *docs[1:]], text_facts=True)
    for d in (docs[9], docs[3]):
        q = f"What is the status of {d[0].meta['key']}?"
        assert again.ask(q).answer == FactBank(fresh).ask(q).answer, "the updated bank answers as the bank built from scratch"


# ------------------------------------------------------------------ cases a review found (each failed before its fix)
def _doc(dsid: str, meta: dict, keys: list[str] | None = None, body: str = "Some text about the rollout.") -> tuple[SourceDoc, dict]:
    return SourceDoc(dsid=dsid, source="linear", rel=f"x/{dsid}.json", title=f"Ticket {dsid}", fields=[("body", body)], meta=meta,
                     updated=WHEN, keys=keys or []), {}


def _same_as_fresh(path, docs, tmp_path, **kw):
    fresh = tmp_path / "fresh_check.sqlite"
    B.build(fresh, [docs[k] for k in sorted(docs)], **kw)
    got, want = rows(path), rows(fresh)
    return [t for t in want if got[t] != want[t]]


def test_a_citation_longer_than_a_stored_value_is_followed(tmp_path):
    a = _doc("d001", {"key": "ENG-101"}, ["ENG-101"])
    note = ("Blocked by the allocator rollout and the quota migration, which both wait on the billing export; " * 3) + "see ENG-101 for the plan"
    cite = _doc("d004", {"key": "ENG-104", "parent_issue": note}, ["ENG-104"])
    assert len(note) > B.MAX_VALUE and "ENG-101" not in note[:B.MAX_VALUE], "the stored value is cut before the key"
    for start, end in (({"d001": a}, {"d001": a, "d004": cite}), ({"d001": a, "d004": cite}, {"d004": cite})):
        path = tmp_path / "bank.sqlite"
        B.build(path, list(start.values()))
        B.sync(path, [end[k] for k in sorted(end)])
        assert _same_as_fresh(path, end, tmp_path) == []


def test_fields_in_another_order_are_another_document(tmp_path):
    m1 = _doc("d005", {"assignee": "Omar Singh", "creator": "OMAR SINGH", "status": "Open"})
    m2 = _doc("d005", {"status": "Open", "creator": "OMAR SINGH", "assignee": "Omar Singh"})
    assert B.doc_hash(*m1) != B.doc_hash(*m2), "the builder reads the fields in their order: a person's first-written name, the facts' numbers"
    path = tmp_path / "bank.sqlite"
    B.build(path, [m1])
    assert B.sync(path, [m2])["changed"] == 1 and _same_as_fresh(path, {"d005": m2}, tmp_path) == []


def test_an_update_on_a_bank_built_without_its_derived_tables(tmp_path):
    pool = company(31, 8)
    docs = [pool[k] for k in sorted(pool)]
    path = tmp_path / "bank.sqlite"
    B.build(path, docs[:6], text_facts=True, derived=False)
    con = sqlite3.connect(path)
    B.apply(con, add=docs[6:], text_facts=True)
    con.commit()
    con.close()
    assert _same_as_fresh(path, {sd.dsid: (sd, raw) for sd, raw in docs}, tmp_path, text_facts=True) == []
    assert store.ensure(path) == {}


def test_sync_reads_documents_as_the_bank_was_built(tmp_path):
    pool = company(33, 8)
    docs = [pool[k] for k in sorted(pool)]
    path = tmp_path / "bank.sqlite"
    B.build(path, docs[:6], text_facts=True)
    rep = B.sync(path, docs)
    assert (rep["added"], rep["same"]) == (2, 6), "with sentence facts, as it was built: the six it holds are the same"
    assert _same_as_fresh(path, {sd.dsid: (sd, raw) for sd, raw in docs}, tmp_path, text_facts=True) == []


def test_documents_an_open_bank_does_not_know_are_read_one_by_one(tmp_path):
    from cie.factbank.engine import FactBank
    from cie.factbank.records import DocFacts, Records

    first = [_doc(f"a{i:03d}", {"key": f"ENG-{100 + i}", "status": "Open"}, [f"ENG-{100 + i}"]) for i in range(3)]
    more = [_doc(f"n{i:03d}", {"key": f"OPS-{100 + i}", "status": "Done"}, [f"OPS-{100 + i}"]) for i in range(DocFacts.BULK + 20)]
    path = tmp_path / "bank.sqlite"
    B.build(path, first)
    fb = FactBank(path)  # opened before the update: it knows no system for the new documents
    B.sync(path, first + more)
    rec = Records(fb)
    got = [rec.doc_facts().get(f"doc:{sd.dsid}", {}) for sd, _ in more]
    assert all(g.get("status") == [("Done", None)] for g in got) and rec.doc_facts().get("doc:n000", {}).get("key") == [("OPS-100", None)]
