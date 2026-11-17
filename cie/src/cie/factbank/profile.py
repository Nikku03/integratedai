"""What the fact bank is told about one company's records, in one place, and how much of it the records tell by themselves.

The builder and the brain were written against one company's exports. What they knew of that company sat in lists in
the code: which fields name people (``sources.PEOPLE_FIELDS``, with the company's own name in two of them), which cite
other records (``REF_FIELDS``), which hold dates (a rule on the field's name), which systems are systems of record,
which fields name companies. A ``Profile`` holds those lists. ``Profile.default()`` is exactly what the code held, so a
bank built with it is the bank built before. ``derive`` reads a profile from the documents instead: a field names
people when its values are people's names, holds dates when its values are dates, cites records when its values hold
identifiers that records carry.

The profile a bank was built with is kept in the bank's file (``store_meta``); the brain reads its lists from there.

What a profile does **not** hold, and stays written by hand (docs/FACTBANK_FIXES.md lists it):
- the words of a question that point to a field ("who owns" for ``owner``): ``engine.FIELD_WORDS``, ``records.CUES``;
- the readers of each system's export (``cie.ingest.sources``: a record's own identifiers, its title and text fields);
- words of the language, not of the company: stop words, chat shorthand, the list of ordinary English words;
- which fields name companies: a company's name and a person's name look alike ("Acme Retail", "Maya Chen"), and
  nothing in the values tells them apart. ``derive`` keeps the listed ones.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

NAMED_SHARE = 0.1  # a field may name people when at least this share of its values are shaped like a person's name ...
KNOWN_SHARE = 0.4  # ... and it does when this share of those names are held by another field that surely names people
CERTAIN_SHARE = 0.85  # a field surely names people when this share of its values are shaped like names
DATE_SHARE = 0.9
REF_SHARE = 0.5
MIN_VALUES = 20  # a field with fewer values is left as the profile it starts from has it
DATE_CHARS = 32  # a value longer than this is a sentence that holds a date, not a date
# the fields whose holders are people for certain (an assignee, an author, an attendee): the default ``person_fields``
PERSON_FIELDS = frozenset(("redwood_owner", "se_assigned", "assignee", "creator", "author", "customer_attendees", "reporter",
                           "csm_assigned", "redwood_attendees", "reviewers", "collaborators", "owner", "participants"))


@dataclass(frozen=True)
class Profile:
    people_fields: tuple[str, ...]  # their values are people: each becomes a person entity
    ref_fields: tuple[str, ...]  # their values cite other records by identifier
    date_fields: tuple[str, ...] | None  # their values are dates; None: told by the field's name (``bank._is_date_field``)
    org_fields: tuple[str, ...]  # their values are companies
    person_fields: tuple[str, ...]  # a holder of one of these is a person for certain (``BrainBank.not_people``)
    primary_systems: tuple[str, ...]  # systems of record: their facts outweigh what other systems say of the same thing
    skip_fields: tuple[str, ...]  # fields that are not facts (the export's own bookkeeping)
    source: str = "default"
    # the fields a derived profile read from the documents; a field outside them (one the documents it was read from
    # did not hold) is a date by its name, as in the default profile. None: every field is told by the lists above
    seen_fields: tuple[str, ...] | None = None

    @staticmethod
    def default() -> Profile:
        """The lists the code held: a bank built with this profile is the bank built before profiles."""
        from cie.factbank.bank import PRIMARY_SYSTEMS, SKIP_FIELDS
        from cie.ingest.sources import ORG_FIELDS, PEOPLE_FIELDS, REF_FIELDS

        return Profile(tuple(PEOPLE_FIELDS), tuple(REF_FIELDS), None, tuple(ORG_FIELDS), tuple(sorted(PERSON_FIELDS)),
                       tuple(sorted(PRIMARY_SYSTEMS)), tuple(sorted(SKIP_FIELDS)))

    def is_date(self, field: str) -> bool:
        if self.date_fields is None or (field not in self._dates and self._seen is not None and field not in self._seen):
            from cie.factbank.bank import _is_date_field

            return _is_date_field(field)
        return field in self._dates

    def is_default(self) -> bool:
        """Whether this profile holds the default lists, whatever its ``source`` says: a bank built with it is the bank
        built without one."""
        return replace(self, source="default") == Profile.default()

    def __post_init__(self) -> None:
        for name in ("people", "ref", "skip"):
            object.__setattr__(self, f"_{name}", frozenset(getattr(self, f"{name}_fields")))
        object.__setattr__(self, "_dates", frozenset(self.date_fields or ()))
        object.__setattr__(self, "_seen", None if self.seen_fields is None else frozenset(self.seen_fields))
        object.__setattr__(self, "_primary", frozenset(self.primary_systems))

    def names_people(self, field: str) -> bool:
        return field in self._people  # type: ignore[attr-defined]

    def cites(self, field: str) -> bool:
        return field in self._ref  # type: ignore[attr-defined]

    def skips(self, field: str) -> bool:
        return field in self._skip  # type: ignore[attr-defined]

    def primary(self, system: str) -> bool:
        return system in self._primary  # type: ignore[attr-defined]

    def to_json(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(self).items()}

    @staticmethod
    def from_json(d: dict[str, Any]) -> Profile:
        base = Profile.default().to_json()
        unknown = set(d) - set(base)
        if unknown:
            raise ValueError(f"a profile has no {sorted(unknown)}; it has {sorted(base)}")
        d = {**base, **d}
        return Profile(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items()})

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), indent=1))

    @staticmethod
    def load(path: str | Path) -> Profile:
        return Profile.from_json(json.loads(Path(path).read_text()))

    @staticmethod
    def of_bank(con: sqlite3.Connection) -> Profile:
        """The profile a bank was built with; the default for a bank built before profiles were kept."""
        from cie.factbank import store

        d = store.meta(con).get("profile")
        return Profile.from_json(d) if d else Profile.default()


def form_keys(value: str) -> list[str]:
    """The identifiers a value holds, told by their form alone: a ticket key ("ENG-123"), a pull request's address."""
    from cie.ingest.sources import PR_URL_RE, TICKET_RE, slug

    return [m.upper() for m in TICKET_RE.findall(value)] + [f"pr:{slug(r)}#{n}" for r, n in PR_URL_RE.findall(value)]


def survey(docs: Iterable[tuple[Any, dict[str, Any]]]) -> dict[str, Any]:
    """What the documents' fields hold. For each field: how many values; how many are shaped like a person's name
    (``people``), and how many of those names another field that surely names people holds too (``known``); how many are
    dates; how many hold an identifier by its form (``keys``); how many are an identifier that another record carries
    (``carried``). A value that is the record's own identifier counts as none of these (``own``)."""
    from cie.factbank.bank import _iso, person_key
    from cie.ingest.sources import ARTEFACT_FIELDS, as_list, person_name

    fields: dict[str, Counter] = {}
    carried: set[str] = set()
    held: dict[str, Counter] = {}  # field -> its short values (lower case), checked afterwards against what records carry
    names: dict[str, Counter] = {}  # field -> the people it names
    records: Counter = Counter()
    for sd, _raw in docs:
        records[sd.source] += 1
        own = {k.lower() for k in sd.keys}
        carried |= own
        for k, v in sd.meta.items():
            if k in ARTEFACT_FIELDS or v in (None, "", []):
                continue
            c = fields.setdefault(k, Counter())
            for item in as_list(v)[:40]:
                if isinstance(item, dict | list):
                    c["nested"] += 1
                    continue
                text = str(item).strip()
                if not text:
                    continue
                c["values"] += 1
                low = text.lower()
                keys = [x.lower() for x in form_keys(text)]
                if low in own or f"id:{low}" in own or (keys and set(keys) <= own):
                    c["own"] += 1
                    continue
                person = person_name(text)
                if person:
                    c["people"] += 1
                    names.setdefault(k, Counter())[person_key(person)] += 1
                day = _iso(text) if len(text) <= DATE_CHARS else None
                # "2026-W10" reads as a day but is a week; digits alone are epoch seconds (Slack's timestamps). A
                # number of 9 to 11 digits that is neither (a phone number) reads as a date too: nothing in the value
                # tells them apart. An identifier other records carry is told first (``derive``)
                c["dates"] += day is not None and (day in text or text.isdigit())
                c["keys"] += bool(keys)
                if len(text) <= 80:
                    held.setdefault(k, Counter())[low] += 1
    for k, vals in held.items():
        fields[k]["carried"] = sum(n for v, n in vals.items() if v in carried or f"id:{v}" in carried)
    sure = {k for k, c in fields.items() if c["values"] >= MIN_VALUES and c["people"] >= CERTAIN_SHARE * c["values"]}
    in_fields: Counter = Counter()
    for k in sure:
        in_fields.update(names[k].keys())
    for k, held_names in names.items():
        fields[k]["known"] = sum(n for person, n in held_names.items() if in_fields[person] > (k in sure))
    return {"fields": {k: dict(c) for k, c in fields.items()}, "records": dict(records)}


def derive(docs: Iterable[tuple[Any, dict[str, Any]]], base: Profile | None = None) -> tuple[Profile, dict[str, Any]]:
    """A profile read from the documents, and the survey it was read from.

    - A field cites records when ``REF_SHARE`` of its values hold an identifier by its form, or are one another record
      carries. This is asked first: an identifier of digits can read as a date.
    - It holds dates when ``DATE_SHARE`` of its values are dates.
    - It names people when ``NAMED_SHARE`` of its values are shaped like names and ``KNOWN_SHARE`` of those names are
      held by another field that surely names people (people turn up in several roles; a company's domain or a team's
      name does not). Its holders are people for certain when ``CERTAIN_SHARE`` of its values are shaped like names.
    - A field with fewer than ``MIN_VALUES`` values is kept as ``base`` has it (the default profile). So are the fields
      that name companies, the fields to skip and the systems of record: the values do not tell them. A field the
      documents do not hold at all (``seen_fields`` lists those they hold) keeps the base's lists, and is a date by its
      name: documents added later can hold it."""
    base = base or Profile.default()
    sv = survey(docs)
    people, dates, refs, certain = set(), set(), set(), set()
    for k, c in sv["fields"].items():
        n = c.get("values", 0)
        if n < MIN_VALUES:
            if base.names_people(k):
                people.add(k)
                certain |= {k} & set(base.person_fields)
            elif base.cites(k):
                refs.add(k)
            elif base.is_date(k):
                dates.add(k)
            continue
        if max(c.get("keys", 0), c.get("carried", 0)) >= REF_SHARE * n:
            refs.add(k)
        elif c.get("dates", 0) >= DATE_SHARE * n:
            dates.add(k)
        elif c.get("people", 0) >= NAMED_SHARE * n and c.get("known", 0) >= KNOWN_SHARE * c["people"] and k not in base.org_fields:
            people.add(k)
            if c["people"] >= CERTAIN_SHARE * n:
                certain.add(k)
    seen = set(sv["fields"])
    people |= set(base.people_fields) - seen
    refs |= set(base.ref_fields) - seen
    certain |= set(base.person_fields) - seen
    if base.date_fields is not None:
        dates |= set(base.date_fields) - seen
    prof = replace(base, people_fields=tuple(sorted(people)), ref_fields=tuple(sorted(refs)), date_fields=tuple(sorted(dates)),
                   person_fields=tuple(sorted(certain)), source="derived", seen_fields=tuple(sorted(seen)))
    return prof, sv


def agreement(base: Profile, derived: Profile, sv: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """How far a derived profile agrees with a written one on the fields the documents hold, counted in field values (a
    field with many values weighs more): for people, references and dates, the values of the fields both hold, only the
    written one and only the derived one, with the fields."""
    n = {k: c.get("values", 0) for k, c in sv["fields"].items() if c.get("values", 0)}  # the fields the documents hold
    out = {}
    lists = {"people": (set(base.people_fields) & set(n), set(derived.people_fields) & set(n)),
             "references": (set(base.ref_fields) & set(n), set(derived.ref_fields) & set(n)),
             "dates": ({k for k in n if base.is_date(k)}, {k for k in n if derived.is_date(k)})}
    for name, (x, y) in lists.items():
        both, only_x, only_y = x & y, x - y, y - x
        out[name] = {"fields_both": len(both), "values_both": sum(n.get(k, 0) for k in both),
                     "only_written": {k: n.get(k, 0) for k in sorted(only_x, key=lambda k: -n.get(k, 0))},
                     "only_derived": {k: n.get(k, 0) for k in sorted(only_y, key=lambda k: -n.get(k, 0))}}
    return out


def compare(a: Profile, b: Profile) -> dict[str, dict[str, list[str]]]:
    """Where two profiles differ: for each list, what only the first has and what only the second has."""
    out = {}
    for name in ("people_fields", "ref_fields", "date_fields", "org_fields", "person_fields", "primary_systems", "skip_fields"):
        x, y = set(getattr(a, name) or ()), set(getattr(b, name) or ())
        if x != y:
            out[name] = {"only_first": sorted(x - y), "only_second": sorted(y - x), "both": sorted(x & y)}
    return out
