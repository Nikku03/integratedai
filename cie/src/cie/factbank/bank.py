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

Plain files and SQLite, no vectors, no graph database, no GPU: "keep it boring".
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
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

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, title TEXT, system TEXT, authority TEXT, date TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, kind TEXT, name TEXT, source TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(id UNINDEXED, name, text, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS aliases (alias TEXT, entity TEXT, PRIMARY KEY (alias, entity));
CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, entity TEXT, parameter TEXT, value TEXT, value_entity TEXT, claim TEXT,
  source TEXT, source_detail TEXT, context TEXT, confidence TEXT, caveats TEXT, dependencies TEXT, last_verified TEXT);
CREATE INDEX IF NOT EXISTS facts_entity ON facts(entity);
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


def add_document(b: Built, sd, raw: dict[str, Any]) -> None:
    """The source, entities, aliases and facts of one document (a ``cie.ingest.sources.SourceDoc`` and its raw record)."""
    from cie.ingest.sources import (
        ARTEFACT_FIELDS,
        PEOPLE_FIELDS,
        REF_FIELDS,
        as_list,
        person_name,
        reference_keys,
    )

    dsid = sd.dsid or sd.rel
    doc = f"doc:{dsid}"
    when = (sd.updated or sd.created)
    when_s = when.date().isoformat() if when else ""
    system = sd.source
    b.sources.append((dsid, sd.title, system, "primary" if system in PRIMARY_SYSTEMS else "secondary", when_s, sd.rel))
    b.entities[doc] = (doc, "document", sd.title, dsid)
    for k in sd.keys:
        b.aliases.add((k.lower(), doc))
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
        if k in ARTEFACT_FIELDS or k in SKIP_FIELDS or v in (None, "", []):
            continue
        for item in as_list(v)[:40]:
            if isinstance(item, (dict, list)):
                item = json.dumps(item, ensure_ascii=False)
            s = str(item).strip()
            if not s:
                continue
            target = None
            person = person_name(s) if k in PEOPLE_FIELDS else None
            if person:
                s, target = person, person_key(person)
                b.entities.setdefault(target, (target, "person", person, ""))
                b.aliases.add((person.lower(), target))
            elif k in REF_FIELDS:
                keys = reference_keys(k, s)
                if keys:
                    target = "key:" + keys[0].lower()
            elif _is_date_field(k) and _iso(s):
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


def resolve(b: Built) -> None:
    """Point identifier entities at the documents that carry them, when those are in the bank."""
    alias_doc = {a: e for a, e in b.aliases if e.startswith("doc:")}
    for f in b.facts:
        if f.value_entity and f.value_entity.startswith("key:") and f.value_entity[4:] in alias_doc:
            f.value_entity = alias_doc[f.value_entity[4:]]
        if f.entity.startswith("key:") and f.entity[4:] in alias_doc:
            f.entity = alias_doc[f.entity[4:]]
    for e in [e for e in b.entities if e.startswith("key:") and e[4:] in alias_doc]:
        del b.entities[e]


def build(path: str | Path, docs: Iterable[tuple[Any, dict[str, Any]]]) -> dict[str, Any]:
    """Write a bank from (SourceDoc, raw record) pairs. Returns counts and the checker's report."""
    path = Path(path)
    if path.exists():
        path.unlink()
    b = Built()
    for sd, raw in docs:
        add_document(b, sd, raw)
    resolve(b)
    for e, (_, _kind, name, _src) in b.entities.items():
        if e not in b.texts:
            b.texts[e] = (name, name)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?)", b.sources)
    con.executemany("INSERT INTO entities VALUES (?,?,?,?)", list(b.entities.values()))
    con.executemany("INSERT INTO entities_fts VALUES (?,?,?)", [(e, n, t) for e, (n, t) in b.texts.items()])
    con.executemany("INSERT OR IGNORE INTO aliases VALUES (?,?)", sorted(b.aliases))
    con.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [f.row() for f in b.facts])
    con.commit()
    rep = check(con)
    con.close()
    return {"sources": len(b.sources), "entities": len(b.entities), "facts": len(b.facts), "bytes": path.stat().st_size, "check": rep}


def check(con: sqlite3.Connection, stale_days: int = 90) -> dict[str, Any]:
    """The cell bank's invariants, for company facts. Errors make the bank unusable; contradictions and staleness are
    reported."""
    errors: list[str] = []
    sources = {r[0] for r in con.execute("SELECT id FROM sources")}
    ids = set()
    rows = con.execute("SELECT id, entity, parameter, value, claim, source, source_detail, context, confidence, caveats, dependencies, "
                       "last_verified FROM facts").fetchall()
    for r in rows:
        fact = dict(zip(("id", "entity", "parameter", "value", "claim", "source", "source_detail", "context", "confidence", "caveats",
                         "dependencies", "last_verified"), r, strict=True))
        missing = [k for k in REQUIRED if fact.get(k) in (None,)]
        if missing:
            errors.append(f"{fact['id']}: missing {missing}")
        if fact["source"] not in sources:
            errors.append(f"{fact['id']}: source {fact['source']} does not resolve")
        if fact["confidence"] not in CONFIDENCE:
            errors.append(f"{fact['id']}: confidence {fact['confidence']!r}")
        ids.add(fact["id"])
    for fid, deps in con.execute("SELECT id, dependencies FROM facts"):
        for d in json.loads(deps or "[]"):
            if d not in ids:
                errors.append(f"{fid}: dependency {d} does not exist")
    dates = [r[0] for r in con.execute("SELECT last_verified FROM facts WHERE last_verified != ''")]
    newest = max(dates) if dates else ""
    stale = 0
    if newest:
        ref = date.fromisoformat(newest)
        stale = sum(1 for d in dates if (ref - date.fromisoformat(d)).days > stale_days)
    contradictions = contradictions_of(con)
    return {"ok": not errors, "errors": errors[:50], "facts": len(rows), "stale": stale, "contradictions": len(contradictions),
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
