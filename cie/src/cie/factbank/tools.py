"""The tools a language model reads the fact bank through (``cie.factbank.reasoner``), over the bank's own tables on disk
(``cie.factbank.store``: ``doc_fields``, ``schema_fields``, ``text_rows``). Nothing of the bank is copied into memory.

The first version of these tools (docs/FACTBANK_50K_RESULTS.md) failed in ways the model could not see: one call in five
of the 50,000-document run was wasted (docs/FACTBANK_FIXES.md). What changed:

- **Names are read as people write them.** A field is found whatever its case, spaces, hyphens or camel case
  ("due date", "dueDate" and "due_date" are one field); "title", "name" and "subject" are a record's title; a system
  goes by its usual names ("gdrive", "emails", "pull requests"). A field or system that does not exist is an error that
  names the closest ones, never an empty result.
- **A record is read by any of its names:** its id, its ticket key, its pull request number or its exact title.
- **Values are compared loosely and it is said.** "Solstice Health" also matches a record that writes
  "SolsticeHealth", and the result lists the spellings it counted. A filter that matches nothing says which condition
  matched nothing and which values come close.
- **find sorts, groups, limits and filters by range:** ``sort``, ``group_by``, ``limit``, and conditions ``not``,
  ``contains``, ``before``/``after``/``between`` (dates), ``gt``/``gte``/``lt``/``lte`` (numbers), ``exists``.
- **search** filters by system before it ranks, keeps short words that are names ("AI"), puts a record with exactly
  that title first, and marks the hits that hold every word.
- **schema** lists the systems and a system's fields with the kind of value each holds; a short form of it is in the
  model's instructions (``schema_brief``), so the model sees the real field names before its first call.
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cie.factbank import store

SEARCH_K = 8
FIND_ROWS = 40
VALUES_ROWS = 40
GROUP_ROWS = 40
SHOW_FIELDS = 8
READ_CHARS = 6000
READ_FIELDS_CHARS = 2500
SNIPPET = 160
FIELD_CHARS = 300
RESULT_CHARS = 8000
CLOSEST = 6
SCHEMA_FIELDS = 40  # fields of a system the schema tool describes in full; the rest are named
BRIEF_FIELDS = 20  # fields of a system named in the model's instructions
BRIEF_SHARE = 0.5  # ... those that at least this share of the system's records hold
TITLE_NAMES = frozenset(("title", "name", "subject"))
ID_NAMES = frozenset(("id", "doc", "doc_id", "record", "record_id", "dsid"))  # a record's own id: every result row has it as "doc"
# the usual names of the usual systems; one applies only when the bank has that system
SYSTEM_NAMES = {
    "google_drive": ("gdrive", "drive", "google drive", "googledrive", "gdoc", "gdocs", "google docs"),
    "gmail": ("email", "emails", "mail", "e-mail", "google mail"),
    "github": ("gh", "pr", "prs", "pull request", "pull requests", "pulls"),
    "fireflies": ("meeting", "meetings", "call", "calls", "transcript", "transcripts", "meeting notes"),
    "hubspot": ("crm", "account", "accounts", "company", "companies"),
    "confluence": ("wiki",),
    "slack": ("chat", "channel", "channels"),
    "linear": ("linear issues",),
    "jira": ("jira tickets",),
}
STOP = frozenset(("what", "when", "who", "which", "how", "does", "the", "and", "for", "with", "about", "this", "that", "are", "was",
                  "were", "have", "has", "from", "into", "under", "did", "will", "there", "their", "of", "in", "on", "to", "is",
                  "it", "at", "by", "or", "an", "as", "be", "do", "we", "our", "my"))
OPS = ("not", "any", "contains", "before", "after", "on", "between", "gt", "gte", "lt", "lte", "exists")
DAY = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")
PR_REF = re.compile(r"^(?:#|pr\s*[#-]?\s*|pull request\s*[#-]?\s*)?(\d{1,7})$", re.I)


def canon(name: Any) -> str:
    """A field or system name as it is compared: camel case split, lower case, anything but letters and digits as "_"."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name or "").strip())
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _cut(s: Any, chars: int = FIELD_CHARS) -> Any:
    return s[:chars] + " [...]" if isinstance(s, str) and len(s) > chars else s


def search_terms(query: str) -> list[str]:
    """A search's words: three letters or more outside the stop words, numbers, and a shorter word written in capitals
    or with a digit ("AI", "EU", "Q3"), which is a name."""
    out = []
    for w in re.findall(r"[A-Za-z0-9]+", query or ""):
        low = w.lower()
        if low in STOP and not (w.isupper() and len(w) == 2 and low not in ("is", "it", "at", "by", "or", "an", "as", "be", "do", "we", "my", "of", "in", "on", "to")):
            continue
        if len(low) >= 3 or low.isdigit() or (len(low) == 2 and (w.isupper() or any(c.isdigit() for c in w))):
            out.append(low)
    return list(dict.fromkeys(out))


class Toolbox:
    """The tools over one fact bank file with its derived tables (``store.ensure`` adds them). ``brain`` is a
    ``cie.factbank.brain.Brain`` or a callable question -> its row; without one the brain tool says it is not there."""

    def __init__(self, bank_path: str | Path, brain: Any = None):
        self.con = sqlite3.connect(f"file:{Path(bank_path)}?mode=ro", uri=True, check_same_thread=False)
        if not store.has(self.con, "doc_fields"):
            raise RuntimeError(f"{bank_path} has no derived tables: run cie.factbank.store.ensure on it first")
        self.brain = brain
        self.systems: dict[str, int] = dict(self.con.execute("SELECT system, count(*) FROM sources GROUP BY system"))
        # every system's fields, most held first: {system: {field: (kind, records, distinct values, examples)}}
        self.schema: dict[str, dict[str, tuple[str, int, int, list[str]]]] = {s: {} for s in self.systems}
        for s, f, kind, n, d, ex in self.con.execute("SELECT system, field, kind, records, distinct_values, examples FROM schema_fields "
                                                     "ORDER BY system, records DESC, field"):
            self.schema.setdefault(s, {})[f] = (kind, n, d, json.loads(ex or "[]"))
        self._canon = {s: {canon(f): f for f in reversed(list(fs))} for s, fs in self.schema.items()}
        self._names = {canon(s): s for s in self.systems}
        for s, names in SYSTEM_NAMES.items():
            if s in self.systems:
                for n in names:
                    self._names.setdefault(canon(n), s)

    # ------------------------------------------------------------------ names
    def system(self, name: Any) -> tuple[str | None, dict[str, Any] | None]:
        """(the system a name means, None), or (None, the error that lists the bank's systems)."""
        s = self._names.get(canon(name))
        if s is not None:
            return s, None
        return None, {"error": f"no system {str(name)!r}. The systems are: "
                               + ", ".join(f"{k} ({n:,} records)" for k, n in sorted(self.systems.items()))}

    def closest(self, system: str, name: str, k: int = CLOSEST) -> list[str]:
        """The system's fields nearest a name it does not have: those sharing a word of it, then those spelled alike; the
        most held first."""
        fields = list(self.schema.get(system, {}))
        want = canon(name)
        toks = {t for t in want.split("_") if len(t) >= 3}
        share = [f for f in fields if toks & set(canon(f).split("_"))]
        alike = difflib.get_close_matches(want, [canon(f) for f in fields], n=k, cutoff=0.6)
        by_canon = self._canon.get(system, {})
        return list(dict.fromkeys(share + [by_canon[a] for a in alike if a in by_canon]))[:k]

    def field(self, system: str, name: Any) -> tuple[str | None, dict[str, Any] | None]:
        """(the system's field a name means, None), or (None, the error that names the closest fields). A name is read
        whatever its case, spacing or camel case; "title", "name" and "subject" are the record's title unless the system has
        a field so named."""
        c = canon(name)
        by = self._canon.get(system, {})
        if c in by:
            return by[c], None
        if c in TITLE_NAMES:
            return "title", None
        squashed = {k.replace("_", ""): f for k, f in by.items()}
        if c.replace("_", "") in squashed:
            return squashed[c.replace("_", "")], None
        near = self.closest(system, str(name))
        main = [f for f in self.schema.get(system, {}) if f not in near][:10]
        return None, {"error": f"no field {str(name)!r} in {system}." + (f" Closest: {', '.join(near)}." if near else "")
                               + f" Its most held fields: {', '.join(main)}. "
                               + f'Call schema {{"system": "{system}"}} for all {len(self.schema.get(system, {}))} fields.'}

    # ------------------------------------------------------------------ records
    @staticmethod
    def _dsid(doc: Any) -> str:
        return str(doc or "").strip().removeprefix("doc:")

    def _source(self, dsid: str) -> tuple[str, str, str] | None:
        return self.con.execute("SELECT title, system, date FROM sources WHERE id = ?", (dsid,)).fetchone()

    def fields(self, dsid: str) -> dict[str, list[str]]:
        """A record's fields and their values, in the bank's order (its title is the field "title")."""
        out: dict[str, list[str]] = {}
        for f, v in self.con.execute("SELECT field, value FROM doc_fields WHERE doc = ? ORDER BY rowid", (dsid,)):
            out.setdefault(f, []).append(v)
        return out

    def _first(self, dsid: str, field: str) -> str | None:
        row = self.con.execute("SELECT value FROM doc_fields WHERE doc = ? AND field = ? ORDER BY rowid LIMIT 1", (dsid, field)).fetchone()
        return row[0] if row else None

    def _label(self, dsid: str) -> dict[str, Any]:
        title, system, date = self._source(dsid) or ("", "", "")
        out = {"doc": dsid, "system": system, "title": title, "date": date}
        if key := (self._first(dsid, "key") or self._first(dsid, "pr_number")):
            out["key"] = key
        return out

    def resolve(self, ref: Any) -> tuple[list[str], str]:
        """The records a reference names, and how it was read: a record id, a ticket key, a pull request number ("#412",
        "PR 412") or an exact title (compared loosely)."""
        raw = str(ref or "").strip().strip('"').strip()
        dsid = self._dsid(raw)
        if self._source(dsid) is not None:
            return [dsid], "id"
        alias = [e[4:] for (e,) in self.con.execute("SELECT entity FROM aliases WHERE alias = ? AND entity LIKE 'doc:%' ORDER BY entity",
                                                    (raw.lower(),))]
        if alias:
            return alias, "key"
        if (m := PR_REF.match(raw)) is not None:
            hits = [e[4:] for (e,) in self.con.execute("SELECT entity FROM aliases WHERE alias = ? AND entity LIKE 'doc:%' ORDER BY entity",
                                                       (f"#{m.group(1)}",))]
            if hits:
                return hits, "pull request number"
        for col, how in (("norm", "title"), ("loose", "title, written another way")):
            val = store.norm(raw) if col == "norm" else store.loose(raw)
            hits = [d for (d,) in self.con.execute(f"SELECT DISTINCT doc FROM doc_fields WHERE field = 'title' AND {col} = ? ORDER BY doc LIMIT 50",
                                                   (val,))] if val else []
            if hits:
                return hits, how
        return [], ""

    # ------------------------------------------------------------------ search
    def search(self, query: str, system: str | None = None, k: int = SEARCH_K) -> dict[str, Any]:
        sys_ = None
        if system not in (None, ""):
            sys_, err = self.system(system)
            if err:
                return err
        terms = search_terms(query)
        if not terms:
            return {"results": [], "note": "no searchable words in the query"}
        # a record the query names outright (its key, its number, its exact title) comes first; a title that many records
        # share (a channel's name) names none of them
        titled = [d for d in self.resolve(query)[0] if sys_ is None or (self._source(d) or ("", "", ""))[1] == sys_]
        titled = titled if len(titled) <= 3 else []
        join = "JOIN sources s ON s.id = substr(f.id, 5) " if sys_ else ""
        where = "AND s.system = ? " if sys_ else ""
        sql = (f"SELECT substr(f.id, 5), f.text FROM entities_fts f {join}WHERE f.entities_fts MATCH ? AND f.id LIKE 'doc:%' {where}"
               "ORDER BY bm25(f.entities_fts, 0.0, 4.0, 1.0) LIMIT ?")
        args = (sys_, k) if sys_ else (k,)
        every = self.con.execute(sql, (" AND ".join(f'"{t}"' for t in terms), *args)).fetchall() if len(terms) > 1 else []
        some = self.con.execute(sql, (" OR ".join(f'"{t}"' for t in terms), *args)).fetchall()
        all_ids = {d for d, _ in every} if len(terms) > 1 else {d for d, _ in some}
        text = dict(some) | dict(every)
        out = []
        for dsid in dict.fromkeys(titled + [d for d, _ in every] + [d for d, _ in some]):
            body = re.sub(r"\s+", " ", str(text.get(dsid) if dsid in text else (self._text(dsid) or "")))
            low = body.lower()
            hit = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
            row = {**self._label(dsid), "snippet": body[max(0, hit - 40): max(0, hit - 40) + SNIPPET]}
            if dsid in titled:
                row["exact_title"] = True
            row["all_words"] = dsid in all_ids or all(t in low for t in terms)
            out.append(row)
            if len(out) >= k:
                break
        res: dict[str, Any] = {"results": out}
        if not out:
            res["note"] = "no record holds any of these words" + (f" in {sys_}" if sys_ else "")
        elif len(terms) > 1 and not any(r["all_words"] for r in out):
            res["note"] = "no record holds all of these words: the results hold some of them, and may be about something else"
        return res

    def _text(self, dsid: str) -> str | None:
        row = self.con.execute("SELECT f.text FROM text_rows t JOIN entities_fts f ON f.rowid = t.rid WHERE t.id = ?", (f"doc:{dsid}",)).fetchone()
        return None if row is None else str(row[0] or "")

    # ------------------------------------------------------------------ read
    def read(self, doc: Any, query: str | None = None, chars: int = READ_CHARS) -> dict[str, Any]:
        found, how = self.resolve(doc)
        if not found:
            return {"error": f"no record {str(doc)!r}: give a record's id (the \"doc\" of a search or find result), its ticket key, "
                             "its pull request number or its exact title; or search for it"}
        if len(found) > 1:
            return {"error": f"{len(found)} records are named {str(doc)!r}: read one by its id",
                    "records": [self._label(d) for d in found[:SEARCH_K]]}
        dsid = found[0]
        text = self._text(dsid) or ""
        if len(text) > chars:
            text = self._passages(text, query or "", chars)
        shown, used = {}, 0
        for f, vals in self.fields(dsid).items():
            if f == "title":
                continue
            v = _cut(", ".join(vals))
            used += len(f) + len(v) + 6
            if used > READ_FIELDS_CHARS:
                shown["..."] = "more fields are in the text below"
                break
            shown[f] = v
        return {**self._label(dsid), **({} if how == "id" else {"found_by": how}), "fields": shown, "text": text}

    @staticmethod
    def _passages(text: str, query: str, chars: int, window: int = 700) -> str:
        """The document's start (its fields) and the windows of about ``window`` characters, cut at sentence and line ends,
        that hold the most of the query's words, in their order, up to ``chars``."""
        cut = min(window, chars // 3)
        head = text[:cut]
        parts = re.split(r"(?<=[.!?\n])\s+", text[cut:])
        windows, cur = [], ""
        for x in parts:
            if cur and len(cur) + len(x) > min(window, chars // 3):
                windows.append(cur)
                cur = ""
            cur = f"{cur} {x}" if cur else x
        if cur:
            windows.append(cur)
        terms = set(search_terms(query))
        rank = sorted(range(len(windows)), key=lambda i: (-len({t for t in terms if t in windows[i].lower()}), i))
        keep, used = [], len(head)
        for i in rank:
            if used + len(windows[i]) > chars:
                break
            keep.append(i)
            used += len(windows[i]) + 5
        return "\n[...]\n".join([head, *(windows[i] for i in sorted(keep))]) + "\n[... the rest of the record is left out]"

    # ------------------------------------------------------------------ find
    def _all(self, system: str) -> set[str]:
        return {d for (d,) in self.con.execute("SELECT id FROM sources WHERE system = ?", (system,))}

    def _holding(self, system: str, field: str) -> set[str]:
        return {d for (d,) in self.con.execute("SELECT DISTINCT doc FROM doc_fields WHERE system = ? AND field = ?", (system, field))}

    def _equal(self, system: str, field: str, value: Any, exact: bool) -> tuple[set[str], list[str]]:
        """The records whose field holds a value, compared loosely unless ``exact`` (then only by case and spacing), and the
        spellings counted when there is more than one."""
        col, v = ("norm", store.norm(value)) if exact else ("loose", store.loose(value))
        if isinstance(value, bool):  # true and false as the records write them: "True", "true", "yes"...
            v = store.norm(str(value))
            col = "norm"
        rows = self.con.execute(f"SELECT doc, value FROM doc_fields WHERE system = ? AND field = ? AND {col} = ?", (system, field, v)).fetchall()
        if not rows and not exact and store.day_of(str(value)) is None and store.number_of(str(value)) is None:
            rows = self.con.execute("SELECT doc, value FROM doc_fields WHERE system = ? AND field = ? AND norm = ?",
                                    (system, field, store.norm(value))).fetchall()
        spellings = list(dict.fromkeys(val for _, val in rows))
        return {d for d, _ in rows}, spellings if len({store.norm(s) for s in spellings}) > 1 else []

    def _near_values(self, system: str, field: str, value: Any, k: int = CLOSEST) -> list[dict[str, Any]]:
        """The field's values nearest one it does not hold: those that contain it or that it contains, then those spelled
        alike among its commonest values."""
        v = store.norm(value)
        rows = self.con.execute("SELECT min(value), count(DISTINCT doc), norm FROM doc_fields WHERE system = ? AND field = ? "
                                "GROUP BY norm ORDER BY 2 DESC, norm LIMIT 3000", (system, field)).fetchall()
        part = [(val, n) for val, n, nv in rows if v and (v in nv or (len(nv) >= 4 and nv in v))]
        alike = difflib.get_close_matches(v, [nv for _, _, nv in rows], n=k, cutoff=0.75)
        by_norm = {nv: (val, n) for val, n, nv in rows}
        out = list(dict.fromkeys(part + [by_norm[a] for a in alike]))[:k]
        return [{"value": _cut(val, 80), "records": n} for val, n in out]

    def _condition(self, system: str, field: str, cond: Any, exact: bool) -> tuple[set[str], dict[str, Any]]:
        """The records one condition keeps, and what to tell about it: an error, the spellings counted, or why it kept
        none. A plain value is equality; a list is any of its values; an object is one or more operators (``OPS``)."""
        info: dict[str, Any] = {}
        if cond is None:
            cond = {"exists": False}  # {"assignee": null}: the records with no assignee
        if not isinstance(cond, dict):
            vals = cond if isinstance(cond, list) else [cond]
            got: set[str] = set()
            for x in vals:
                docs, spell = self._equal(system, field, x, exact)
                got |= docs
                if spell:
                    info.setdefault("also_written", []).extend(spell)
            return got, info
        unknown = [k for k in cond if k not in OPS]
        if unknown:
            return set(), {"error": f"no operator {unknown[0]!r} for {field}: use a value, a list of values, or one of {', '.join(OPS)}"}
        got = None

        def keep(docs: set[str]) -> None:
            nonlocal got
            got = docs if got is None else got & docs

        base = "SELECT DISTINCT doc FROM doc_fields WHERE system = ? AND field = ? AND "
        for op, x in cond.items():
            if op == "any":
                docs, more = self._condition(system, field, x if isinstance(x, list) else [x], exact)
                info.update(more)
                keep(docs)
            elif op == "not":
                docs, _ = self._condition(system, field, x, exact)
                keep(self._all(system) - docs)
            elif op == "exists":
                held = self._holding(system, field)
                keep(held if x not in (False, "false", "no", 0) else self._all(system) - held)
            elif op == "contains":
                like = "%" + store.norm(x).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                keep({d for (d,) in self.con.execute(base + "norm LIKE ? ESCAPE '\\'", (system, field, like))})
            elif op in ("before", "after", "on", "between"):
                days = [str(v).strip() for v in (x if isinstance(x, list) else [x])]
                if any(not DAY.match(d) for d in days) or (op == "between" and len(days) != 2):
                    return set(), {"error": f'{op} takes a date as YYYY-MM-DD (or YYYY-MM, YYYY){"; between takes two" if op == "between" else ""}'}
                lo, hi = days[0], days[-1] + "￿"  # a month or a year covers every day in it
                if op == "before":
                    q, args = "day < ?", (lo,)
                elif op == "after":
                    q, args = "day > ?", (hi,)
                else:
                    q, args = "day >= ? AND day <= ?", (lo, hi)
                keep({d for (d,) in self.con.execute(base + q, (system, field, *args))})
            else:
                try:
                    n = float(str(x).replace(",", ""))
                except ValueError:
                    return set(), {"error": f"{op} takes a number"}
                sign = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
                keep({d for (d,) in self.con.execute(base + f"num {sign} ?", (system, field, n))})
        return got or set(), info

    def _sort_key(self, system: str, field: str, docs: Iterable[str]) -> dict[str, tuple]:
        """Each record's place when sorted by a field: by its date, its number, else its text; its first value counts."""
        kind = self.schema[system][field][0]
        out: dict[str, tuple] = {}
        for d, norm_, day, num in self.con.execute("SELECT doc, norm, day, num FROM doc_fields WHERE system = ? AND field = ? ORDER BY rowid",
                                                    (system, field)):
            if d not in out:
                out[d] = (day or "",) if kind == "date" else (num if num is not None else float("inf"),) if kind == "number" else (norm_,)
        return {d: out[d] for d in docs if d in out}

    def find(self, system: Any, where: dict[str, Any] | None = None, show: Any = None, sort: Any = None, limit: Any = None,
             group_by: Any = None, exact: bool = False) -> dict[str, Any]:
        sys_, err = self.system(system)
        if err:
            return err
        hits: set[str] | None = None
        notes: list[str] = []
        empty: list[str] = []
        spelled: dict[str, list[str]] = {}
        for name, cond in (where or {}).items():
            if canon(name) in ID_NAMES and canon(name) not in self._canon.get(sys_, {}):
                # {"id": "PM-58337"}: the record itself, by its id, its key, its number or its title
                docs = {d for x in (cond if isinstance(cond, list) else [cond]) for d in self.resolve(x)[0]
                        if (self._source(d) or ("", "", ""))[1] == sys_}
                if not docs:
                    empty.append(f"no {sys_} record is named {json.dumps(cond, ensure_ascii=False)}")
                hits = docs if hits is None else hits & docs
                continue
            f, err = self.field(sys_, name)
            if err:
                return err
            docs, info = self._condition(sys_, f, cond, exact)
            if "error" in info:
                return info
            if info.get("also_written"):
                spelled[f] = list(dict.fromkeys(info["also_written"]))
            if not docs:
                why = f"no {sys_} record has {f} {json.dumps(cond, ensure_ascii=False)}"
                if not isinstance(cond, dict | list):
                    near = self._near_values(sys_, f, cond)
                    why += ("; closest values: " + ", ".join(f"{n['value']!r} ({n['records']})" for n in near)) if near else \
                        f'; call values {{"system": "{sys_}", "field": "{f}"}} to see how its values are written'
                empty.append(why)
            hits = docs if hits is None else hits & docs
        if hits is None:
            hits = self._all(sys_)
        out: dict[str, Any] = {"count": len(hits)}
        if spelled:
            out["counted_spellings"] = {f: [_cut(v, 80) for v in vs[:8]] for f, vs in spelled.items()}
        if empty:
            out["why_none"] = empty
        elif not hits and len(where or {}) > 1:
            out["why_none"] = ["each condition matches some records, but no record matches them all"]
        if group_by not in (None, "", []):
            g, err = self.field(sys_, group_by[0] if isinstance(group_by, list) and group_by else group_by)
            if err:
                return err
            counts: dict[str, tuple[str, set[str]]] = {}
            for d, v, nv in self.con.execute("SELECT doc, value, norm FROM doc_fields WHERE system = ? AND field = ? ORDER BY rowid", (sys_, g)):
                if d in hits:
                    counts.setdefault(nv, (v, set()))[1].add(d)
            groups = sorted(((len(ds), v) for v, ds in counts.values()), key=lambda x: (-x[0], x[1]))
            out["groups"] = [{g: _cut(v, 80), "records": n} for n, v in groups[:GROUP_ROWS]]
            without = len(hits) - len({d for _, ds in counts.values() for d in ds})
            if without:
                out["records_without_" + g] = without
            if len(groups) > GROUP_ROWS:
                notes.append(f"{len(groups)} different values of {g}; the {GROUP_ROWS} most held are shown")
            if show in (None, "", []):
                if notes:
                    out["note"] = "; ".join(notes)
                return out
        if isinstance(show, str):  # "key, status", as Qwen's own tool-call format writes a value
            show = [x.strip() for x in show.split(",") if x.strip()]
        shown: list[str] = []
        for name in [str(s) for s in (show or [])][:SHOW_FIELDS]:
            if canon(name) in ID_NAMES and canon(name) not in self._canon.get(sys_, {}):
                continue  # every row has the record's id as "doc"
            f, err = self.field(sys_, name)
            if err:
                notes.append(err["error"])
            elif f not in shown:
                shown.append(f)
        if len(hits) <= 200:
            order = sorted(hits, key=lambda d: ((self._source(d) or ("",))[0] or "", d))
        else:  # by title, then id, as above: one pass over the system's records
            order = [d for (d,) in self.con.execute("SELECT id FROM sources WHERE system = ? ORDER BY coalesce(title, ''), id", (sys_,))
                     if d in hits]
        if sort not in (None, "", {}, []):
            if isinstance(sort, dict):
                by, desc = sort.get("by") or sort.get("field"), str(sort.get("order", "asc")).lower().startswith("desc")
            else:  # "due_date", "-due_date", "due date desc"
                text = str(sort[0] if isinstance(sort, list) and sort else sort).strip()
                m = re.match(r"^-?\s*(.*?)(?:\s+(asc|desc)(?:ending)?)?$", text, re.I)
                by, desc = m.group(1), text.startswith("-") or (m.group(2) or "").lower() == "desc"
            f, err = self.field(sys_, by)
            if err:
                return err
            keys = self._sort_key(sys_, f, hits)
            have = sorted((d for d in hits if d in keys), key=lambda d: (keys[d], d), reverse=desc)
            order = have + [d for d in order if d not in keys]
            if len(have) < len(hits):
                notes.append(f"{len(hits) - len(have)} records have no {f}: they come last")
            if f not in shown:
                shown.insert(0, f)
        try:
            cap = max(1, min(FIND_ROWS, int(limit))) if limit not in (None, "") else FIND_ROWS
        except (TypeError, ValueError):
            cap = FIND_ROWS
        rows, used = [], 0
        for dsid in order[:cap]:
            lab = self._label(dsid)
            fs = self.fields(dsid) if shown else {}
            row = {k: _cut(lab[k]) for k in ("doc", "title", "key") if k in lab}
            for f in shown:
                if f != "title":
                    row[f] = _cut(", ".join(fs.get(f, []))) or None
            used += len(json.dumps(row, ensure_ascii=False, default=str)) + 2
            if rows and used > RESULT_CHARS:
                break
            rows.append(row)
        out["records"] = rows
        if len(hits) > len(rows):
            notes.append(f"{len(hits)} records match; the first {len(rows)} are shown"
                         + ("" if len(rows) == min(len(hits), cap) else ' (narrow "where" or ask for fewer "show" fields to see more)'))
        if notes:
            out["note"] = "; ".join(notes)
        return out

    # ------------------------------------------------------------------ values, schema
    def values(self, system: Any, field: Any, like: Any = None) -> dict[str, Any]:
        sys_, err = self.system(system)
        if err:
            return err
        f, err = self.field(sys_, field)
        if err:
            return err
        rows = self.con.execute("SELECT min(value), count(DISTINCT doc), norm, loose FROM doc_fields WHERE system = ? AND field = ? "
                                "GROUP BY norm ORDER BY 2 DESC, norm", (sys_, f)).fetchall()
        distinct = len(rows)
        if like not in (None, ""):
            n, lo = store.norm(like), store.loose(like)
            rows = [r for r in rows if n in r[2] or (lo and lo in r[3])]
        vals, used = [], 0
        for v, n, _, _ in rows[:VALUES_ROWS]:
            x = {"value": _cut(v, FIELD_CHARS // 2), "records": n}
            used += len(json.dumps(x, ensure_ascii=False)) + 2
            if vals and used > RESULT_CHARS:
                break
            vals.append(x)
        out: dict[str, Any] = {"field": f, "kind": self.schema[sys_][f][0], "values": vals, "distinct": distinct}
        if like not in (None, ""):
            out["matching"] = len(rows)
        if len(rows) > len(vals):
            out["note"] = (f"{len(rows)} values{' match' if like not in (None, '') else ''}; the {len(vals)} most held are shown. "
                           'Give "like" (a part of the value) to look one up')
        return out

    def describe(self, system: Any = None) -> dict[str, Any]:
        """The schema tool: the systems, or one system's fields with the kind of value each holds."""
        if system in (None, ""):
            return {"systems": [{"system": s, "records": n, "fields": len(self.schema.get(s, {}))} for s, n in sorted(self.systems.items())]}
        sys_, err = self.system(system)
        if err:
            return err
        fs = self.schema.get(sys_, {})
        rows = [{"field": f, "kind": kind, "records": n, **({"examples": [_cut(x, 40) for x in ex[:3]]} if kind in ("value", "person") else {})}
                for f, (kind, n, _, ex) in list(fs.items())[:SCHEMA_FIELDS]]
        out: dict[str, Any] = {"system": sys_, "records": self.systems[sys_], "fields": rows}
        rest = list(fs)[SCHEMA_FIELDS:]
        if rest:
            names, used = [], 0
            for f in rest:
                used += len(f) + 2
                if used > 3000:
                    break
                names.append(f)
            out["other_fields"] = names
            if len(names) < len(rest):
                out["note"] = f"{len(rest) - len(names)} more fields, each held by few records"
        return out

    def schema_brief(self) -> str:
        """The systems and their main fields, for the model's instructions: a system's ``BRIEF_FIELDS`` most held fields
        that at least ``BRIEF_SHARE`` of its records hold, each with its kind when it is not a plain value."""
        lines = []
        for s, n in sorted(self.systems.items()):
            fs = [f"{f} ({kind})" if kind in ("person", "date", "number", "record", "text") else f
                  for f, (kind, held, _, _) in self.schema.get(s, {}).items() if held >= BRIEF_SHARE * n and f != "title"][:BRIEF_FIELDS]
            lines.append(f"- {s} ({n:,} records; {len(self.schema.get(s, {}))} fields): title, " + ", ".join(fs))
        return "\n".join(lines)

    def example_call(self) -> str:
        """One find call over the bank's own names, for the model's instructions: the first system (by name) with a field
        that most of its records hold and that takes a handful of values, filtered on its commonest value."""
        for s in sorted(self.systems):
            for f, (kind, held, distinct, ex) in self.schema.get(s, {}).items():
                if kind == "value" and 2 <= distinct <= 12 and held >= 0.9 * self.systems[s] and ex:
                    return json.dumps({"tool": "find", "args": {"system": s, "where": {f: ex[0]}}}, ensure_ascii=False)
        s = sorted(self.systems)[0] if self.systems else "system"
        return json.dumps({"tool": "find", "args": {"system": s, "where": {}}})

    # ------------------------------------------------------------------ the brain, and the calls
    def ask_brain(self, question: str) -> dict[str, Any]:
        if self.brain is None:
            return {"error": "the brain is not available here"}
        r = self.brain(question) if callable(self.brain) else self.brain.ask(question)
        return brain_view(r)

    def run(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """One tool call; a wrong call is answered with what was wrong, never raised."""
        try:
            if tool == "brain":
                return self.ask_brain(str(args["question"]))
            if tool == "search":
                return self.search(str(args["query"]), args.get("system"))
            if tool == "read":
                doc = next((args[k] for k in ("doc", "id", "record", "key", "title") if args.get(k) not in (None, "")), None)
                if doc is None:
                    return {"error": 'missing argument "doc": a record\'s id, ticket key, pull request number or exact title'}
                return self.read(doc, args.get("query"))
            if tool == "find":
                where = args.get("where") or {}
                if not isinstance(where, dict):
                    return {"error": '"where" must be an object of field: value'}
                return self.find(args["system"], where, args.get("show"), args.get("sort"), args.get("limit"), args.get("group_by"),
                                 bool(args.get("exact")))
            if tool == "values":
                return self.values(args["system"], args["field"], args.get("like"))
            if tool == "schema":
                return self.describe(args.get("system"))
        except KeyError as e:
            return {"error": f"missing argument {e}"}
        except Exception as e:  # noqa: BLE001 - the model sees the error and can try again
            return {"error": f"{type(e).__name__}: {e}"[:300]}
        return {"error": f"no tool {tool!r}: one of {', '.join(TOOLS)}"}


TOOLS = ("brain", "search", "read", "find", "values", "schema")
EVIDENCE_CHARS = 2500
EVIDENCE_CHARS_PROSE = 6000  # a free-text answer is a quote: the model is shown more of it and of what it was chosen from
RECORDS_SHOWN = 8


def brain_view(r: dict[str, Any], chars: int | None = None) -> dict[str, Any]:
    """What the model sees of a brain row: its answer, route, reason, the records it read (ids a tool takes) and its
    evidence, cut to ``chars`` (more for a free-text answer)."""
    ev = str(r.get("evidence") or "")
    chars = chars or (EVIDENCE_CHARS_PROSE if r.get("route") == "prose" else EVIDENCE_CHARS)
    out = {"answer": r.get("answer"), "route": r.get("route"), "reason": str(r.get("reason") or "")[:400]}
    docs = records_read(r)
    if docs:
        out["records"] = docs[:RECORDS_SHOWN]
    if r.get("candidates"):  # v19: the other records or answers that come close: worth a look before the answer is kept
        out["also_close"] = [{k: (v[4:] if k == "doc" and str(v).startswith("doc:") else v) for k, v in c.items()} for c in r["candidates"][:4]]
    out["evidence"] = ev[:chars] + (" [...]" if len(ev) > chars else "")
    return out


DOC_ID = re.compile(r"\bdoc:([A-Za-z0-9_.:-]+)")


def records_read(r: dict[str, Any]) -> list[str]:
    """The ids of the records a brain row rests on, in the order it met them: from its journal's steps and its reason."""
    out: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, str):
            out.extend(m.rstrip(".:,;)") for m in DOC_ID.findall(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list | tuple):
            for v in x:
                walk(v)

    walk(r.get("reason"))
    j = r.get("journal")
    if isinstance(j, str):
        try:
            j = json.loads(j)
        except json.JSONDecodeError:
            pass
    walk(j)
    return list(dict.fromkeys(out))
