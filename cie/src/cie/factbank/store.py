"""What is derived from a fact bank's own tables and kept in its file, so that every process reads it from disk instead of
building its own copy in memory (docs/FACTBANK_FIXES.md):

- **text_rows:** an entity's row in ``entities_fts``. The full-text table does not index its ``id`` column, so
  ``WHERE id = ?`` read every row; ``FactBank.text_of`` goes through this table instead.
- **passages:** the brain's passage index (``prose.PassageIndex``): every document's text cut into passages
  (``engine.windows``) in an FTS5 table. It was built in memory by each process on its first free-text question (about
  40 seconds and 1 GB at 50,000 documents). Here it is built once. Only the index is stored (a contentless FTS5 table):
  a passage's text is cut again from its document when it is read, so the text is not kept twice.
- **doc_fields:** every document's field values, one row each, with the forms they are compared in (``norm``,
  ``loose``), a date and a number where the value is one; indexed, so a filter is a query and not a scan
  (``reasoner.Toolbox``).
- **schema_fields:** the bank's own schema, read from the data: every system's fields, what kind of value each holds,
  how many records hold it and a few of its values.

``ensure(path)`` adds what a bank file lacks (a bank built before this module gains the tables; the facts are not
touched), and ``bank.build`` calls it. Everything here can be dropped and built again from the bank's own tables.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

VERSION = 2
PASSAGE_SIZE = (600, 1000)  # prose.PROSE_SIZE
BATCH = 20_000
EXAMPLES = 5
NOT_FIELDS = ("text_date", "text_key", "referenced_by")  # facts of a document that are not its fields

SCHEMA = """
CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS text_rows (id TEXT PRIMARY KEY, rid INTEGER) WITHOUT ROWID;
"""
PASSAGES = """
CREATE VIRTUAL TABLE passages_fts USING fts5(title, body, content='', tokenize='porter unicode61');
CREATE TABLE passage_docs (doc TEXT PRIMARY KEY, first INTEGER, n INTEGER) WITHOUT ROWID;
CREATE INDEX passage_docs_first ON passage_docs(first);
"""
FIELDS = """
CREATE TABLE doc_fields (doc TEXT, system TEXT, field TEXT, value TEXT, norm TEXT, loose TEXT, day TEXT, num REAL, ref TEXT);
CREATE TABLE schema_fields (system TEXT, field TEXT, kind TEXT, records INTEGER, distinct_values INTEGER, examples TEXT,
  PRIMARY KEY (system, field)) WITHOUT ROWID;
"""
FIELD_INDEXES = """
CREATE INDEX doc_fields_norm ON doc_fields(system, field, norm);
CREATE INDEX doc_fields_loose ON doc_fields(system, field, loose);
CREATE INDEX doc_fields_doc ON doc_fields(doc, field);
"""


def norm(s: Any) -> str:
    """A value as an exact filter compares it: lower case, runs of spaces as one."""
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


LOOSE_DROP = re.compile(r"[\s\-_'\u2018\u2019`/]+")


def loose(s: Any) -> str:
    """A value as a loose match compares it: lower case, accents dropped, and no spaces, hyphens, underscores,
    apostrophes or slashes ("Solstice Health", "SolsticeHealth" and "solstice-health" are one; "O'Connor" and "OConnor"
    too), nor a closing full stop ("Acme Corp."). Other punctuation stays: "1.0" is not "10", "v1.2" is not "v12"."""
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return LOOSE_DROP.sub("", t).rstrip(".,;:")


ISO_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ]\d{2}:\d{2}.*)?$")
NUMBER = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")


def day_of(value: str) -> str | None:
    """The ISO day a value starts with, when the value is a date or a date and time."""
    m = ISO_DAY.match(value.strip())
    return m.group(1) if m else None


def number_of(value: str) -> float | None:
    """The number a value is ("1,200", "3.5", "-4"), or None; a date or a key is not a number."""
    v = value.strip().lstrip("$€£").rstrip("%")
    return float(v.replace(",", "")) if NUMBER.match(v) else None


def has(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None


def meta(con: sqlite3.Connection) -> dict[str, Any]:
    if not has(con, "store_meta"):
        return {}
    return {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM store_meta")}


def _set(con: sqlite3.Connection, key: str, value: Any) -> None:
    con.execute("INSERT OR REPLACE INTO store_meta VALUES (?, ?)", (key, json.dumps(value)))


def build_text_rows(con: sqlite3.Connection) -> int:
    con.execute("DELETE FROM text_rows")
    con.execute("INSERT INTO text_rows SELECT id, rowid FROM entities_fts")
    return con.execute("SELECT count(*) FROM text_rows").fetchone()[0]


def _pages(con: sqlite3.Connection, sql: str, key: int, start: Any, size: int = BATCH, args: tuple = ()):
    """The rows of ``sql`` (which filters on its key ``> ?``, orders by it and ends with ``LIMIT ?``), a page at a time:
    each page is read whole before the caller writes, so no read is open while the same connection writes."""
    last = start
    while True:
        page = con.execute(sql, (*args, last, size)).fetchall()
        if not page:
            return
        yield from page
        last = page[-1][key]


def build_passages(con: sqlite3.Connection, size: tuple[int, int] = PASSAGE_SIZE) -> int:
    """Every document's stored text cut into passages and indexed, in document id order: passage rowids, titles and text
    are exactly what ``prose.PassageIndex.build`` made in memory."""
    from cie.factbank.engine import windows

    for t in ("passages_fts", "passage_docs"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.executescript(PASSAGES)
    n = 0
    rows: list[tuple[int, str, str]] = []
    docs: list[tuple[str, int, int]] = []
    sql = ("SELECT e.id, e.name, f.text FROM entities e JOIN text_rows t ON t.id = e.id JOIN entities_fts f ON f.rowid = t.rid "
           "WHERE e.kind = 'document' AND e.id > ? ORDER BY e.id LIMIT ?")
    for doc, name, text in _pages(con, sql, 0, "", 2000):
        cut = windows(text or "", *size)
        if cut:
            docs.append((doc, n + 1, len(cut)))
        for body in cut:
            n += 1
            rows.append((n, name or "", body))
        if len(rows) >= BATCH:
            con.executemany("INSERT INTO passages_fts(rowid, title, body) VALUES (?, ?, ?)", rows)
            rows.clear()
    con.executemany("INSERT INTO passages_fts(rowid, title, body) VALUES (?, ?, ?)", rows)
    con.executemany("INSERT INTO passage_docs VALUES (?, ?, ?)", docs)
    _set(con, "passages", {"size": list(size), "passages": n})
    return n


def field_kind(field: str, n: int, days: int, nums: int, people: int, refs: int, long_: int) -> str:
    """What a field holds, from its values: a person, another record, a date, a number, text (long values) or a value."""
    if field == "title":
        return "title"
    if people >= 0.5 * n:
        return "person"
    if refs >= 0.5 * n:
        return "record"
    if days >= 0.9 * n:
        return "date"
    if nums >= 0.9 * n:
        return "number"
    return "text" if long_ >= 0.5 * n else "value"


def build_fields(con: sqlite3.Connection) -> dict[str, int]:
    """``doc_fields`` (every field value of every document, in the bank's order, and its title as the field "title") and
    ``schema_fields`` (each system's fields: the kind of value, how many records hold it, how many different values, and
    its commonest values). The bank's facts must be committed."""
    for t in ("doc_fields", "schema_fields"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.executescript(FIELDS)
    system = dict(con.execute("SELECT id, system FROM sources"))
    rows: list[tuple] = []

    def add(doc: str, sys_: str, field: str, value: Any, target: str | None = None) -> None:
        value = str(value).strip()
        ref = None if not target else "person" if target.startswith("person:") else "record"
        rows.append((doc, sys_, field, value, norm(value), loose(value), day_of(value), number_of(value), ref))
        if len(rows) >= BATCH:
            con.executemany("INSERT INTO doc_fields VALUES (?,?,?,?,?,?,?,?,?)", rows)
            rows.clear()

    for i, title, sys_ in _pages(con, "SELECT id, title, system FROM sources WHERE id > ? ORDER BY id LIMIT ?", 0, ""):
        if title:
            add(i, sys_, "title", title)
    marks = ",".join("?" * len(NOT_FIELDS))
    sql = ("SELECT rowid, source, parameter, value, value_entity FROM facts WHERE entity = 'doc:' || source "
           f"AND parameter NOT IN ({marks}) AND parameter NOT LIKE 'text\\_%' ESCAPE '\\' AND rowid > ? ORDER BY rowid LIMIT ?")
    for _, src, p, v, target in _pages(con, sql, 0, 0, args=NOT_FIELDS):
        if src in system and v not in (None, ""):
            add(src, system[src], p, v, target)
    if rows:
        con.executemany("INSERT INTO doc_fields VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.executescript(FIELD_INDEXES)
    stats = con.execute(
        "SELECT system, field, count(*), count(DISTINCT doc), count(DISTINCT norm), sum(day IS NOT NULL), sum(num IS NOT NULL), "
        "sum(ref = 'person'), sum(ref = 'record'), sum(length(value) > 80) FROM doc_fields GROUP BY system, field").fetchall()
    out = []
    for sys_, field, n, docs, distinct, days, nums, people, refs, long_ in stats:
        top = con.execute("SELECT min(value), count(*) c FROM doc_fields WHERE system = ? AND field = ? GROUP BY norm "
                          "ORDER BY c DESC, norm LIMIT ?", (sys_, field, EXAMPLES)).fetchall()
        kind = field_kind(field, n, days or 0, nums or 0, people or 0, refs or 0, long_ or 0)
        out.append((sys_, field, kind, docs, distinct, json.dumps([str(v)[:60] for v, _ in top], ensure_ascii=False)))
    con.executemany("INSERT INTO schema_fields VALUES (?,?,?,?,?,?)", out)
    info = {"rows": con.execute("SELECT count(*) FROM doc_fields").fetchone()[0], "fields": len(out)}
    _set(con, "fields", info)
    return info


def ensure(path: str | Path, log: Callable[[str], None] | None = None, passages: bool = True, fields: bool = True) -> dict[str, Any]:
    """Add to a bank file the derived tables it lacks (or that another version of this module made). Returns what it
    built, with the seconds each took; nothing when the file was complete."""
    con = sqlite3.connect(str(path))
    built: dict[str, Any] = {}
    try:
        if not (has(con, "facts") and has(con, "entities_fts")):
            return built  # not a bank file (yet): whoever opens it next says so
        con.executescript(SCHEMA)
        m = meta(con)
        fresh = m.get("version") == VERSION and m.get("facts") == con.execute("SELECT count(*) FROM facts").fetchone()[0]
        t = time.perf_counter()
        if not fresh or not m.get("text_rows"):
            built["text_rows"] = build_text_rows(con)
            _set(con, "text_rows", built["text_rows"])
            built["text_rows_s"] = round(time.perf_counter() - t, 1)
        t = time.perf_counter()
        if passages and (not fresh or (m.get("passages") or {}).get("size") != list(PASSAGE_SIZE) or not has(con, "passages_fts")):
            built["passages"] = build_passages(con)
            built["passages_s"] = round(time.perf_counter() - t, 1)
        t = time.perf_counter()
        if fields and (not fresh or not m.get("fields") or not has(con, "doc_fields")):
            built["fields"] = build_fields(con)
            built["fields_s"] = round(time.perf_counter() - t, 1)
        if built:
            _set(con, "version", VERSION)
            _set(con, "facts", con.execute("SELECT count(*) FROM facts").fetchone()[0])
            con.commit()
            if log:
                log(f"  bank store: built {', '.join(k for k in built if not k.endswith('_s'))} in "
                    f"{sum(v for k, v in built.items() if k.endswith('_s')):.0f} s")
    finally:
        con.close()
    return built
