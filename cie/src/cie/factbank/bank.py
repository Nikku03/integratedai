"""The fact bank: a company memory bank built the way Nikku03/cell builds its memory bank.

The cell repository's ``memory_bank/facts`` keeps one JSON per atomic claim, each with a source, a source detail, a
context, a confidence level and its dependencies; a checker (``.invariants/check.py``) refuses a broken bank before the
index is rebuilt; and its v2 engine (``rem/atlas/cellbank2.py``) keeps every fact individually addressable, looks it up
by its source and reasons one hop at a time, writing each result down. This module is that design for company
documents:

* **Sources:** one per document: its id, title, system and date. ``authority`` is ``primary`` for the system of record
  of its objects (Linear, Jira, GitHub, HubSpot) and ``secondary`` otherwise.
* **Entities:** a document, a person, an action item, or an identifier cited but not in the bank. Documents are found
  by content: SQLite FTS5 (BM25) over their title, fields and text.
* **Facts:** one per field value. The entity is the document, the parameter is the field and the value is the
  value; a value that names a person or another document points to that entity.
  - Every fact that points to an entity has its inverse on that entity (``assignee`` → ``assignee_of``), so lookups are
    always by the fact's subject, as in the cell engine.
  - Confidence is ``measured`` for a field the source system records, and ``inferred`` for a value parsed from text by
    a rule (a meeting's action items).
* **The checker** (``check``), from the cell bank's rules:
  - every fact has every field;
  - its source resolves, and its dependencies exist;
  - its confidence is one of the four levels;
  - stale facts are flagged (by default, older than 90 days before the newest).

  Unlike the cell bank, two facts that disagree about the same entity and parameter are **not rejected**: company
  records do disagree. They are listed, and the engine settles them by weighted votes.

* **Building and updating:**
  - ``build`` writes a bank a batch of documents at a time, so its memory does not grow with the company's size.
  - ``sync`` brings a bank up to date with the documents as they are now: it adds the new ones, replaces the changed
    ones (by a hash of their content) and removes those that are gone, without building the bank again. The result
    holds the same rows as a bank built from scratch from the same documents in id order.

Plain files and SQLite, no vectors, no graph database, no GPU: "keep it boring".
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

CONFIDENCE = ("measured", "inferred", "estimated", "assumed")
REQUIRED = ("id", "claim", "entity", "parameter", "value", "source", "source_detail", "context", "confidence", "caveats",
            "dependencies", "last_verified")
PRIMARY_SYSTEMS = {"linear", "jira", "github", "hubspot"}
SKIP_FIELDS = {"dsid", "summary", "source", "commits", "files_changed", "merge_commit_sha", "head_branch", "base_branch",
               "orientation", "path"}
MAX_VALUE = 300
BUILDER = 1  # what add_document makes of a document; part of a document's content hash, so a change here re-reads it
BATCH_DOCS = 2_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, title TEXT, system TEXT, authority TEXT, date TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, kind TEXT, name TEXT, source TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(id UNINDEXED, name, text, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS aliases (alias TEXT, entity TEXT, PRIMARY KEY (alias, entity));
CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, entity TEXT, parameter TEXT, value TEXT, value_entity TEXT, claim TEXT,
  source TEXT, source_detail TEXT, context TEXT, confidence TEXT, caveats TEXT, dependencies TEXT, last_verified TEXT);
CREATE INDEX IF NOT EXISTS facts_entity ON facts(entity);
"""
# what an update needs to find a document's rows without reading the whole bank
SYNC_SCHEMA = """
CREATE INDEX IF NOT EXISTS facts_source ON facts(source);
CREATE INDEX IF NOT EXISTS aliases_entity ON aliases(entity);
CREATE TABLE IF NOT EXISTS source_hashes (id TEXT PRIMARY KEY, hash TEXT) WITHOUT ROWID;
"""


@dataclass
class Fact:
    id: str
    entity: str
    parameter: str
    value: str
    claim: str
    source: str
    source_detail: str
    context: dict[str, Any]
    confidence: str
    last_verified: str
    value_entity: str | None = None
    caveats: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    def row(self) -> tuple:
        return (self.id, self.entity, self.parameter, self.value, self.value_entity, self.claim, self.source, self.source_detail,
                json.dumps(self.context), self.confidence, json.dumps(self.caveats), json.dumps(self.dependencies), self.last_verified)


@dataclass
class Built:
    sources: list[tuple] = field(default_factory=list)
    entities: dict[str, tuple] = field(default_factory=dict)
    texts: dict[str, tuple[str, str]] = field(default_factory=dict)
    aliases: set[tuple[str, str]] = field(default_factory=set)
    facts: list[Fact] = field(default_factory=list)


def person_key(name: str) -> str:
    return "person:" + re.sub(r"\s+", " ", name.strip().lower())


def _iso(v: Any) -> str | None:
    from cie.ingest.sources import parse_when

    w = parse_when(v)
    return w.date().isoformat() if w else None


def _is_date_field(k: str) -> bool:
    return k.endswith(("_at", "_date", "_ts")) or k in ("created", "updated", "date", "due", "deadline", "forecast_close_month")


def add_document(b: Built, sd, raw: dict[str, Any], text_facts: bool = False, profile: Any = None) -> None:
    """The source, entities, aliases and facts of one document (a ``cie.ingest.sources.SourceDoc`` and its raw record).
    ``profile`` (``cie.factbank.profile.Profile``) says which fields name people, cite records and hold dates; the
    default is the lists the code holds."""
    from cie.factbank.profile import Profile
    from cie.ingest.sources import ARTEFACT_FIELDS, as_list, person_name, reference_keys

    prof = profile or Profile.default()

    dsid = sd.dsid or sd.rel
    doc = f"doc:{dsid}"
    when = (sd.updated or sd.created)
    when_s = when.date().isoformat() if when else ""
    system = sd.source
    b.sources.append((dsid, sd.title, system, "primary" if prof.primary(system) else "secondary", when_s, sd.rel))
    b.entities[doc] = (doc, "document", sd.title, dsid)
    for k in sd.keys:
        b.aliases.add((k.lower(), doc))
    pr = str(sd.meta.get("pr_number") or "")
    if system == "github" and pr.isdigit():
        b.aliases.add((f"#{pr}", doc))  # how people cite a pull request
    ctx = {"system": system, **({"project": sd.project} if sd.project else {})}
    meta_text: list[str] = []
    n = 0

    def add(entity: str, parameter: str, value: str, claim: str, detail: str, confidence: str = "measured",
            value_entity: str | None = None, deps: list[str] | None = None) -> str:
        nonlocal n
        n += 1
        fid = f"{dsid}#{n}"
        b.facts.append(Fact(fid, entity, parameter, value[:MAX_VALUE], claim[:600], dsid, detail, ctx, confidence, when_s, value_entity,
                            [], deps or []))
        return fid

    for k, v in sd.meta.items():
        if k in ARTEFACT_FIELDS or prof.skips(k) or v in (None, "", []):
            continue
        for item in as_list(v)[:40]:
            if isinstance(item, (dict, list)):
                item = json.dumps(item, ensure_ascii=False)
            s = str(item).strip()
            if not s:
                continue
            target = None
            person = person_name(s) if prof.names_people(k) else None
            if person:
                s, target = person, person_key(person)
                b.entities.setdefault(target, (target, "person", person, ""))
                b.aliases.add((person.lower(), target))
            elif prof.cites(k):
                keys = reference_keys(k, s)
                if keys:
                    target = "key:" + keys[0].lower()
            elif prof.is_date(k) and _iso(s):
                s = _iso(s) or s
            fid = add(doc, k, s, f"{sd.title} — {k.replace('_', ' ')}: {s}", f"field {k}", value_entity=target)
            meta_text.append(f"{k.replace('_', ' ')}: {s}")
            if target and target.startswith("person:"):
                add(target, f"{k}_of", sd.title, f"{s} — {k.replace('_', ' ')} of {sd.title}", f"inverse of field {k}",
                    value_entity=doc, deps=[fid])
            elif target:
                b.entities.setdefault(target, (target, "identifier", keys[0], ""))
                add(target, "referenced_by", sd.title, f"{keys[0]} is referenced by {sd.title} ({k})", f"inverse of field {k}",
                    value_entity=doc, deps=[fid])
    from cie.eval.memory_test import action_items

    for i, (owner, task, due) in enumerate(action_items(raw)):
        act = f"action:{dsid}:{i}"
        b.entities[act] = (act, "action_item", task[:300], dsid)
        b.texts[act] = (task[:300], f"{task}\nowner: {owner}\ndue: {due}\nfrom: {sd.title}")
        pk = person_key(owner)
        b.entities.setdefault(pk, (pk, "person", owner, ""))
        b.aliases.add((owner.lower(), pk))
        detail = "action_items (parsed: owner, task, due)"
        f1 = add(act, "owner", owner, f"Action item '{task[:120]}' — owner: {owner}", detail, "inferred", pk)
        add(act, "due_date", due, f"Action item '{task[:120]}' — due: {due}", detail, "inferred")
        add(act, "from_document", sd.title, f"Action item '{task[:120]}' is from {sd.title}", detail, "inferred", doc)
        add(pk, "action_owner_of", task[:300], f"{owner} owns the action item '{task[:120]}' (due {due})", detail, "inferred", act, [f1])
        add(doc, "action_item", task[:300], f"{sd.title} — action item for {owner}, due {due}: {task[:200]}", detail, "inferred", act)
    body = "\n".join(t for _, t in sd.fields)
    b.texts[doc] = (sd.title, "\n".join([sd.title, f"source: {system}", *meta_text, body]))
    if text_facts:
        for kind, value, sentence in sentence_values(body):
            add(doc, f"text_{kind}", value, sentence, "text sentence", "inferred")


SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[])|\n+")
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}(?:-\d{1,7})+\b")
MAX_TEXT_FACTS = 300


def sentence_values(body: str) -> list[tuple[str, str, str]]:
    """Dates and identifiers in a document's sentences: (kind, value, the sentence). Dates are written as ISO dates."""
    from cie.eval.memory_test import dates_in

    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for sent in SENTENCE.split(body):
        sent = sent.strip()
        if len(sent) < 12:
            continue
        sent = sent[:400]
        for kind, vals in (("date", sorted(dates_in(sent))), ("key", sorted(set(KEY_RE.findall(sent))))):
            for v in vals:
                k = (kind, v, sent)
                if k not in seen:
                    seen.add(k)
                    out.append(k)
        if len(out) >= MAX_TEXT_FACTS:
            break
    return out[:MAX_TEXT_FACTS]


def doc_hash(sd, raw: dict[str, Any], text_facts: bool = False, profile: Any = None) -> str:
    """A hash of everything ``add_document`` reads of a document: ``sync`` reads a document again only when it changes
    (or when the profile it is read with does)."""
    body = [BUILDER, bool(text_facts), sd.dsid or sd.rel, sd.source, sd.rel, sd.title, sd.fields, sd.meta, sd.keys, sd.project,
            sd.created, sd.updated, raw]
    if profile is not None and profile.source != "default":
        body.append(profile.to_json())
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _batches(docs: Iterable[Any], size: int) -> Iterator[list[Any]]:
    chunk: list[Any] = []
    for d in docs:
        chunk.append(d)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _is(prefix: str, column: str) -> str:
    """SQL: ``column`` starts with ``prefix`` (which ends with ":"), as a range the column's index can serve."""
    return f"{column} >= '{prefix}' AND {column} < '{prefix[:-1]};'"


def build(path: str | Path, docs: Iterable[tuple[Any, dict[str, Any]]], text_facts: bool = False, derived: bool = True,
          batch: int = BATCH_DOCS, profile: Any = None) -> dict[str, Any]:
    """Write a bank from (SourceDoc, raw record) pairs. Returns counts and the checker's report. ``text_facts`` also
    turns the dates and identifiers in the documents' sentences into facts (confidence "inferred"). ``derived``: the
    bank's derived tables are built too (``cie.factbank.store``: text by id, the passage index, the field table).

    The documents are read and written ``batch`` at a time, so memory does not grow with their number (it held every
    fact of the bank at once: about 1.2 million at 50,000 documents). The rows and their order are what the build in one
    piece wrote. One rule is now fixed: an identifier several documents carry points to the one with the smallest id
    (it was whichever the set's order gave; no reference of the 50,000-document bank goes through such an identifier).

    ``profile``: what the builder is told about this company's fields (``cie.factbank.profile``). It is kept in the
    bank's file, and ``sync`` and the brain read it from there."""
    path = Path(path)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA + SYNC_SCHEMA)
    con.execute("CREATE TEMP TABLE alias_stage (alias TEXT, entity TEXT)")
    n_sources = 0
    for chunk in _batches(docs, batch):
        b = Built()
        for sd, raw in chunk:
            add_document(b, sd, raw, text_facts, profile)
        con.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?)", b.sources)
        con.executemany("INSERT OR IGNORE INTO entities VALUES (?,?,?,?)", list(b.entities.values()))  # a person: first mention
        con.executemany("INSERT INTO entities_fts VALUES (?,?,?)", [(e, n, t) for e, (n, t) in b.texts.items()])
        con.executemany("INSERT INTO alias_stage VALUES (?,?)", list(b.aliases))
        con.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [f.row() for f in b.facts])
        con.executemany("INSERT INTO source_hashes VALUES (?,?)", [(sd.dsid or sd.rel, doc_hash(sd, raw, text_facts, profile)) for sd, raw in chunk])
        n_sources += len(b.sources)
        con.commit()
    con.execute("INSERT OR IGNORE INTO aliases SELECT DISTINCT alias, entity FROM alias_stage ORDER BY alias, entity")
    con.execute("DROP TABLE alias_stage")
    # identifiers point at the documents that carry them, when those are in the bank
    con.execute(f"CREATE TEMP TABLE alias_doc AS SELECT alias, min(entity) AS doc FROM aliases WHERE {_is('doc:', 'entity')} GROUP BY alias")
    con.execute("CREATE INDEX temp.alias_doc_alias ON alias_doc(alias)")
    for col in ("value_entity", "entity"):
        con.execute(f"UPDATE facts SET {col} = (SELECT doc FROM alias_doc WHERE alias = substr(facts.{col}, 5)) "
                    f"WHERE {_is('key:', col)} AND substr({col}, 5) IN (SELECT alias FROM alias_doc)")
    con.execute(f"DELETE FROM entities WHERE {_is('key:', 'id')} AND substr(id, 5) IN (SELECT alias FROM alias_doc)")
    con.execute("DROP TABLE alias_doc")
    # a person or an identifier is found by its name
    con.execute("INSERT INTO entities_fts SELECT id, name, name FROM entities WHERE kind IN ('person', 'identifier') ORDER BY rowid")
    if profile is not None and profile.source != "default":
        from cie.factbank import store

        con.executescript(store.SCHEMA)
        con.execute("INSERT OR REPLACE INTO store_meta VALUES ('profile', ?)", (json.dumps(profile.to_json()),))
    con.commit()
    rep = check(con)
    out = {"sources": n_sources, "entities": con.execute("SELECT count(*) FROM entities").fetchone()[0],
           "facts": con.execute("SELECT count(*) FROM facts").fetchone()[0], "check": rep}
    con.close()
    if derived:
        from cie.factbank import store

        out["store"] = store.ensure(path)  # what every process then reads from the file instead of building its own
    return {**out, "bytes": path.stat().st_size}


# ------------------------------------------------------------------ updating a bank without building it again
def _fact_order(fid: str) -> tuple[str, int]:
    """A fact's place in a build that reads the documents in id order: its source's id, then its number in the source."""
    src, _, n = fid.rpartition("#")
    return src, int(n) if n.isdigit() else 0


def _mentions(con: sqlite3.Connection, entity: str) -> list[tuple[str, str, str]]:
    """What names a person or an identifier: the facts its own (inverse) facts rest on, as (id, field, value), in the
    order a build in id order reads them."""
    ids = [json.loads(d or "[]")[:1] for (d,) in con.execute("SELECT dependencies FROM facts WHERE entity = ?", (entity,))]
    ids = sorted({i[0] for i in ids if i}, key=_fact_order)
    out = []
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        got = {r[0]: r for r in con.execute(f"SELECT id, parameter, value FROM facts WHERE id IN ({','.join('?' * len(part))})", part)}
        out += [got[x] for x in part if x in got]
    return out


def _drop_entity(con: sqlite3.Connection, entity: str) -> None:
    rid = con.execute("SELECT rid FROM text_rows WHERE id = ?", (entity,)).fetchone()
    if rid:
        con.execute("DELETE FROM entities_fts WHERE rowid = ?", rid)
        con.execute("DELETE FROM text_rows WHERE id = ?", (entity,))
    con.execute("DELETE FROM aliases WHERE entity = ?", (entity,))
    con.execute("DELETE FROM entities WHERE id = ?", (entity,))


def _set_text(con: sqlite3.Connection, entity: str, name: str, text: str) -> None:
    """The entity's row of the full-text table, written or replaced, and where it is (``text_rows``)."""
    rid = con.execute("SELECT rid FROM text_rows WHERE id = ?", (entity,)).fetchone()
    if rid:
        con.execute("DELETE FROM entities_fts WHERE rowid = ?", rid)
    cur = con.execute("INSERT INTO entities_fts VALUES (?,?,?)", (entity, name, text))
    con.execute("INSERT OR REPLACE INTO text_rows VALUES (?,?)", (entity, cur.lastrowid))


def _remove(con: sqlite3.Connection, dsid: str, touched: set[str], keys: dict[str, set[str]]) -> bool:
    """Take one document out: its source, its entities (itself and its action items), their text, aliases and facts.
    ``touched`` gains the people and identifiers it named; ``keys`` the identifiers it was cited by, with the document,
    so that what cited it is pointed elsewhere (``_settle``)."""
    from cie.factbank import store

    if con.execute("SELECT 1 FROM sources WHERE id = ?", (dsid,)).fetchone() is None:
        return False
    doc = f"doc:{dsid}"
    for (a,) in con.execute("SELECT alias FROM aliases WHERE entity = ?", (doc,)).fetchall():
        keys.setdefault(a, set()).add(doc)
    for e, v in con.execute("SELECT entity, value_entity FROM facts WHERE source = ?", (dsid,)):
        touched.update(x for x in (e, v) if x and x.startswith(("person:", "key:")))
    store.remove_doc(con, dsid)
    con.execute("DELETE FROM facts WHERE source = ?", (dsid,))
    acts = [r[0] for r in con.execute("SELECT id FROM entities WHERE id >= ? AND id < ? AND source = ?",
                                      (f"action:{dsid}:", f"action:{dsid};", dsid))]
    for e in (doc, *acts):
        _drop_entity(con, e)
    con.execute("DELETE FROM sources WHERE id = ?", (dsid,))
    con.execute("DELETE FROM source_hashes WHERE id = ?", (dsid,))
    return True


def _add(con: sqlite3.Connection, docs: list[tuple[Any, dict[str, Any]]], text_facts: bool, touched: set[str],
         keys: dict[str, set[str]], profile: Any = None) -> None:
    """Put documents in: what ``build`` writes for them, except the people and identifiers they name (``_tidy``)."""
    from cie.factbank import store

    b = Built()
    for sd, raw in docs:
        add_document(b, sd, raw, text_facts, profile)
    con.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?)", b.sources)
    own = [row for e, row in b.entities.items() if not e.startswith(("person:", "key:"))]
    con.executemany("INSERT INTO entities VALUES (?,?,?,?)", own)
    for e, (name, text) in b.texts.items():
        _set_text(con, e, name, text)
    con.executemany("INSERT OR IGNORE INTO aliases VALUES (?,?)", sorted((a, e) for a, e in b.aliases if not e.startswith("person:")))
    con.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [f.row() for f in b.facts])
    con.executemany("INSERT OR REPLACE INTO source_hashes VALUES (?,?)",
                    [(sd.dsid or sd.rel, doc_hash(sd, raw, text_facts, profile)) for sd, raw in docs])
    touched.update(e for e in b.entities if e.startswith(("person:", "key:")))
    for a, e in b.aliases:
        if e.startswith("doc:"):
            keys.setdefault(a, set())
    for e in b.entities:
        if e.startswith("key:"):
            keys.setdefault(e[4:], set())
    store.add_docs(con, b)


def _settle(con: sqlite3.Connection, keys: dict[str, set[str]], touched: set[str]) -> None:
    """Point what cites an identifier at the right entity: the document with the smallest id that carries it, or the
    identifier's own entity when no document does. ``keys``: the identifiers to look at, each with the documents that
    carried it and are gone."""
    from cie.ingest.sources import reference_keys

    for k in sorted(keys):
        holders = [r[0] for r in con.execute(f"SELECT entity FROM aliases WHERE alias = ? AND {_is('doc:', 'entity')} ORDER BY entity", (k,))]
        want = holders[0] if holders else f"key:{k}"
        touched.add(f"key:{k}")
        for e in sorted({f"key:{k}", *holders, *keys[k]} - {want}):
            cited = con.execute("SELECT id, dependencies FROM facts WHERE entity = ? AND parameter = 'referenced_by'", (e,)).fetchall()
            for fid, deps in cited:
                first = json.loads(deps or "[]")[:1]
                row = con.execute("SELECT parameter, value FROM facts WHERE id = ?", (first[0],)).fetchone() if first else None
                ks = reference_keys(row[0], row[1]) if row else []
                if ks and ks[0].lower() == k:
                    con.execute("UPDATE facts SET entity = ? WHERE id = ?", (want, fid))
                    con.execute("UPDATE facts SET value_entity = ? WHERE id = ?", (want, first[0]))


def _tidy(con: sqlite3.Connection, touched: set[str]) -> None:
    """A person or an identifier is in the bank while something names it. Its name is its first mention's, a person's
    aliases every way it is written; one nothing names any more is taken out."""
    from cie.ingest.sources import reference_keys

    for e in sorted(touched):
        mentions = _mentions(con, e)
        person = e.startswith("person:")
        names = [v for _, _, v in mentions] if person else [ks[0] for _, p, v in mentions if (ks := reference_keys(p, v))]
        if not names:
            _drop_entity(con, e)
            continue
        name = names[0]
        row = con.execute("SELECT name FROM entities WHERE id = ?", (e,)).fetchone()
        if row is None:
            con.execute("INSERT INTO entities VALUES (?,?,?,?)", (e, "person" if person else "identifier", name, ""))
            _set_text(con, e, name, name)
        elif row[0] != name:
            con.execute("UPDATE entities SET name = ? WHERE id = ?", (name, e))
            _set_text(con, e, name, name)
        if person:
            want = {n.lower() for n in names}
            have = {r[0] for r in con.execute("SELECT alias FROM aliases WHERE entity = ?", (e,))}
            con.executemany("DELETE FROM aliases WHERE alias = ? AND entity = ?", [(a, e) for a in have - want])
            con.executemany("INSERT OR IGNORE INTO aliases VALUES (?,?)", [(a, e) for a in sorted(want - have)])


def apply(con: sqlite3.Connection, add: Iterable[tuple[Any, dict[str, Any]]] = (), remove: Iterable[str] = (),
          text_facts: bool = False, profile: Any = None) -> dict[str, int]:
    """One change to an open bank: the documents of ``remove`` (ids) taken out and those of ``add`` put in. A document to
    replace is in both. The caller commits. The bank's derived tables are kept in step (``cie.factbank.store``). The
    documents are read with ``profile``, by default the one the bank was built with."""
    from cie.factbank import store
    from cie.factbank.profile import Profile

    profile = profile or Profile.of_bank(con)

    touched: set[str] = set()
    keys: dict[str, set[str]] = {}
    removed = sum(_remove(con, d, touched, keys) for d in remove)
    add = list(add)
    if add:
        _add(con, add, text_facts, touched, keys, profile)
    _settle(con, keys, touched)
    _tidy(con, touched)
    store.after_change(con)
    return {"added": len(add), "removed": removed}


def sync(path: str | Path, docs: Iterable[tuple[Any, dict[str, Any]]], text_facts: bool = False, remove_missing: bool = True,
         adopt: bool = False, batch: int = 500, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Bring a bank up to date with ``docs``, the company's documents as they are now, without building it again.

    - A document the bank does not hold is added; one whose content changed (``doc_hash``) is replaced; one that is the
      same is not read further.
    - ``remove_missing``: a document the bank holds that ``docs`` no longer has is taken out. Pass False when ``docs`` is
      only what changed.
    - ``adopt``: a document the bank holds without a hash (a bank built before hashes were kept) is taken as unchanged
      and its hash recorded; otherwise it is replaced.

    The result holds the same rows as ``build`` gives for the same documents read in id order; the rows' order in the
    tables differs (new rows come last), which can change the order of two passages that match a question equally.
    Each batch is one transaction. A process that has the bank open reads the new rows at once, but keeps what it had
    already read (names, kinds): ``store.revision`` tells it the bank changed."""
    from cie.factbank import store
    from cie.factbank.profile import Profile

    path = Path(path)
    store.ensure(path)
    con = sqlite3.connect(path)
    con.executescript(SYNC_SCHEMA)
    profile = Profile.of_bank(con)  # a document is read as the bank's other documents were
    known = dict(con.execute("SELECT id, hash FROM source_hashes"))
    held = {r[0] for r in con.execute("SELECT id FROM sources")}
    rep = {"added": 0, "changed": 0, "removed": 0, "same": 0, "adopted": 0}
    seen: set[str] = set()
    todo: list[tuple[Any, dict[str, Any]]] = []
    gone: list[str] = []

    def flush() -> None:
        if todo or gone:
            apply(con, todo, gone, text_facts, profile)
            con.commit()
            if log:
                log(f"  bank sync: {rep['added']:,} added, {rep['changed']:,} changed, {rep['removed']:,} removed")
            todo.clear()
            gone.clear()

    for sd, raw in docs:
        dsid = sd.dsid or sd.rel
        if dsid in seen:
            raise ValueError(f"document {dsid} is given twice")
        seen.add(dsid)
        h = doc_hash(sd, raw, text_facts, profile)
        if dsid in held:
            if known.get(dsid) == h:
                rep["same"] += 1
                continue
            if adopt and dsid not in known:
                con.execute("INSERT INTO source_hashes VALUES (?,?)", (dsid, h))
                rep["adopted"] += 1
                continue
            gone.append(dsid)
            rep["changed"] += 1
        else:
            rep["added"] += 1
        todo.append((sd, raw))
        if len(todo) + len(gone) >= batch:
            flush()
    flush()
    if remove_missing:
        for part in _batches(sorted(held - seen), batch):
            gone.extend(part)
            rep["removed"] += len(part)
            flush()
    con.commit()
    out = {**rep, "sources": con.execute("SELECT count(*) FROM sources").fetchone()[0],
           "facts": con.execute("SELECT count(*) FROM facts").fetchone()[0], "revision": store.revision(con)}
    con.close()
    return out


def check(con: sqlite3.Connection, stale_days: int = 90) -> dict[str, Any]:
    """The cell bank's invariants, for company facts. Errors make the bank unusable; contradictions and staleness are
    reported. Every rule is a query, so the check holds no fact in memory (it read them all: 1.5 GB at 50,000 documents)."""
    errors: list[str] = []
    cols = [k for k in REQUIRED if k != "caveats"] + ["caveats"]
    missing = " OR ".join(f"{k} IS NULL" for k in cols)
    for row in con.execute(f"SELECT {', '.join(cols)} FROM facts WHERE {missing} LIMIT 50"):
        fact = dict(zip(cols, row, strict=True))
        errors.append(f"{fact['id']}: missing {[k for k in REQUIRED if fact.get(k) is None]}")
    for fid, src in con.execute("SELECT id, source FROM facts WHERE source NOT IN (SELECT id FROM sources) LIMIT 50"):
        errors.append(f"{fid}: source {src} does not resolve")
    marks = ",".join("?" * len(CONFIDENCE))
    for fid, conf in con.execute(f"SELECT id, confidence FROM facts WHERE confidence NOT IN ({marks}) LIMIT 50", CONFIDENCE):
        errors.append(f"{fid}: confidence {conf!r}")
    for fid, dep in con.execute("SELECT f.id, j.value FROM facts f, json_each(f.dependencies) j WHERE f.dependencies NOT IN ('[]', '') "
                                "AND NOT EXISTS (SELECT 1 FROM facts d WHERE d.id = j.value) LIMIT 50"):
        errors.append(f"{fid}: dependency {dep} does not exist")
    n = con.execute("SELECT count(*) FROM facts").fetchone()[0]
    newest = con.execute("SELECT max(last_verified) FROM facts WHERE last_verified != ''").fetchone()[0] or ""
    stale = 0
    if newest:
        date.fromisoformat(newest)
        stale = con.execute("SELECT count(*) FROM facts WHERE last_verified != '' AND julianday(?) - julianday(last_verified) > ?",
                            (newest, stale_days)).fetchone()[0]
    contradictions = contradictions_of(con)
    return {"ok": not errors, "errors": errors[:50], "facts": n, "stale": stale, "contradictions": len(contradictions),
            "contradiction_examples": contradictions[:5]}


SINGLE_VALUED_HINT = ("status", "state", "stage", "due_date", "assignee", "owner", "author", "creator", "reporter", "priority",
                      "severity", "created_at", "updated_at", "merged_at", "last_updated", "team", "owner_team")


def contradictions_of(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Single-valued parameters with more than one value for one entity, from different sources."""
    out = []
    q = ("SELECT entity, parameter, group_concat(DISTINCT value), group_concat(DISTINCT source) FROM facts "
         f"WHERE parameter IN ({','.join('?' * len(SINGLE_VALUED_HINT))}) GROUP BY entity, parameter "
         "HAVING count(DISTINCT value) > 1 AND count(DISTINCT source) > 1")
    for e, p, vals, srcs in con.execute(q, SINGLE_VALUED_HINT):
        out.append({"entity": e, "parameter": p, "values": vals.split(","), "sources": srcs.split(",")})
    return out


def as_of(con: sqlite3.Connection) -> datetime | None:
    d = con.execute("SELECT max(last_verified) FROM facts").fetchone()[0]
    return datetime.fromisoformat(d) if d else None
