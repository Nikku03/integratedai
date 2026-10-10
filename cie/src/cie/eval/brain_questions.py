"""Every kind of question the company brain (fact bank v15) is tested on, with expected answers from the documents' fields,
and one scorer.

Four families of questions:

* **single:** one document's field, or one lookup over the documents' fields: the memory test's deadlines and lists
  (``memory_test.generate_questions``), a field of a uniquely named document ('Who owns the Google Drive document "X"?'),
  the people listed on one document (a meeting's attendees, a pull request's reviewers), the people on a Linear project,
  and a customer's Jira tickets;
* **multi:** the answer is spread over several documents: the link, combine and compare questions of
  ``factbank_multi.questions``, and the status or assignee of a Linear issue's parent;
* **not_found:** the question names a ticket key, pull request number, quoted title or full person name that no document
  in the haystack holds; the right answer is "not found";
* **prose:** writer-made questions whose answer is a few short facts written in a document (``load_prose``).

Every expected answer is computed from the documents' own fields. A question with more than one right answer in the
haystack is set aside: a title, key or number on two documents, a field with several values, a list that holds an entry
that is not a person (a bot, a team, a role label), a name or field value written as whole words inside another whatever
the hyphens and spaces ('redwood' in 'redwood-docs', 'AcmeAI' in 'Acme AI (Corp)'), and the reasons of
``factbank_5k.why_unclear``.

``kinds()`` is the catalogue, ``generate`` makes every question the documents allow and counts what it sets aside,
``draw_questions`` draws a seeded sample in a given mix, and ``score`` scores one answer.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any

from cie.eval import factbank_multi
from cie.eval.factbank_5k import _key, _pr, why_unclear
from cie.eval.factbank_multi import KEY, _keys, own_score
from cie.eval.factbank_test import direct
from cie.eval.memory_test import (
    CAPS,
    EVIDENCE_CHARS,
    MONTH_NAMES,
    _iso,
    _norm,
    final_answer,
    generate_questions,
)

SEED = 15
FAMILIES = ("single", "multi", "prose", "not_found")
LIST_MAX = 10
NF_POOL = 60  # not-found questions made per kind when no cap is given
ALL = 10**9
EMPTY = {"none", "null", "n/a", "na", "tbd", "unknown", "-", "[]", "{}"}
ADDRESS = {"google_drive": "title", "confluence": "title", "hubspot": "title", "fireflies": "title", "jira": "key", "linear": "key",
           "github": "pr"}
NOT_FOUND_RE = re.compile(r"^\W*(?:not found|none found|no such)\b", re.I)
NOT_PERSON_RE = re.compile(r"[&:]|\b(?:bot|recorder|notetaker|taker|assistant|teams?|group|engineering|ops|growth|council|all|org|support|"
                           r"everyone|squad|committee|department|staff|platform|customer|unknown|unidentified|unattributed|participants?|"
                           r"speaker|caller|rotation|leads?)\b", re.I)


@dataclass(frozen=True)
class Kind:
    name: str
    family: str
    group: str
    scored: str
    source: str


FIELDS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {  # kind: (source, field, value type, wordings)
    "drive_owner": ("google_drive", "owner", "person", ('Who owns the Google Drive document "{t}"?', 'Who is the owner of the Drive doc "{t}"?',
                                                        'Whose Google Drive document is "{t}"?')),
    "drive_status": ("google_drive", "status", "value", ('What is the status of the Google Drive document "{t}"?',
                                                         'What state is the Drive doc "{t}" in?')),
    "drive_created": ("google_drive", "created_at", "date", ('When was the Google Drive document "{t}" created?',
                                                             'On what date was the Drive doc "{t}" created?')),
    "confluence_author": ("confluence", "author", "person", ('Who authored the Confluence page "{t}"?', 'Who wrote the Confluence page "{t}"?',
                                                             'Who is the author of the Confluence page "{t}"?')),
    "confluence_space": ("confluence", "space", "value", ('Which Confluence space is the page "{t}" in?',
                                                          'In what Confluence space does the page "{t}" live?')),
    "confluence_updated": ("confluence", "last_updated", "date", ('When was the Confluence page "{t}" last updated?',
                                                                  'What is the last-updated date of the Confluence page "{t}"?')),
    "hubspot_owner": ("hubspot", "owner", "person", ('Who is the account owner of the HubSpot account "{t}"?', 'Who owns the HubSpot account "{t}"?',
                                                     'In HubSpot, who is the owner of the account "{t}"?')),
    "hubspot_stage": ("hubspot", "stage", "value", ('What stage is the HubSpot account "{t}" in?', 'What is the deal stage of the HubSpot account "{t}"?')),
    "hubspot_close": ("hubspot", "forecast_close_month", "month", ('What is the forecast close month of the HubSpot account "{t}"?',
                                                                   'In which month is the HubSpot account "{t}" forecast to close?')),
    "hubspot_se": ("hubspot", "se_assigned", "person", ('Who is the solutions engineer assigned to the HubSpot account "{t}"?',
                                                        'Which solutions engineer covers the HubSpot account "{t}"?')),
    "jira_status": ("jira", "status", "value", ("What is the status of the Jira ticket {k}?", "What state is Jira ticket {k} in?",
                                                "Where does the Jira ticket {k} stand? Give its status.")),
    "jira_priority": ("jira", "priority", "value", ("What is the priority of the Jira ticket {k}?", "What priority does Jira ticket {k} have?")),
    "jira_sla": ("jira", "sla_due_at", "date", ("When is the SLA due for Jira ticket {k}?", "What is the SLA due date of the Jira ticket {k}?")),
    "jira_reporter": ("jira", "reporter", "person", ("Who reported the Jira ticket {k}?", "Who is the reporter of Jira ticket {k}?")),
    "jira_ticket_assignee": ("jira", "assignee", "person", ("Who is assigned to the Jira ticket {k}?", "Who is the assignee of Jira ticket {k}?")),
    "jira_customer": ("jira", "customer_company", "customer", ("Which customer is the Jira ticket {k} for?",
                                                               "Which customer company raised the Jira ticket {k}?")),
    "linear_issue_status": ("linear", "status", "value", ("What is the status of the Linear issue {k}?", "What state is Linear issue {k} in?")),
    "linear_issue_priority": ("linear", "priority", "value", ("What is the priority of the Linear issue {k}?",
                                                              "What priority does Linear issue {k} have?")),
    "linear_issue_assignee": ("linear", "assignee", "person", ("Who is assigned to the Linear issue {k}?", "Who is the assignee of Linear issue {k}?")),
    "linear_issue_project": ("linear", "project", "value", ("Which Linear project is the issue {k} part of?",
                                                            "What project does the Linear issue {k} belong to?")),
    "linear_issue_creator": ("linear", "creator", "person", ("Who created the Linear issue {k}?", "Who is the creator of Linear issue {k}?")),
    "pr_author": ("github", "author", "person", ("Who authored pull request #{n}?", "Who opened PR #{n}?",
                                                 "Who is the author of the GitHub pull request #{n}?")),
    "pr_repo": ("github", "repo", "value", ("Which repository is pull request #{n} in?", "In which GitHub repository was PR #{n} opened?")),
    "pr_merged": ("github", "merged_at", "date", ("When was pull request #{n} merged?", "On what date was PR #{n} merged?")),
    "meeting_owner": ("fireflies", "redwood_owner", "person", ('Who was the Redwood owner of the meeting "{t}"?',
                                                               'Which Redwood person owned the meeting "{t}"?')),
    "meeting_customer": ("fireflies", "customer_company", "customer", ('Which customer was the meeting "{t}" with?',
                                                                       'What customer company was in the meeting "{t}"?')),
    "meeting_date": ("fireflies", "recorded_at", "date", ('When was the meeting "{t}" recorded?', 'On what date did the meeting "{t}" take place?')),
}
NAMES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {  # kind: (source, fields listing people, wordings)
    "meeting_attendees": ("fireflies", ("redwood_attendees", "customer_attendees"),
                          ('Who attended the meeting "{t}"?', 'List the attendees of the meeting "{t}".',
                           'Who was in the meeting "{t}"? Name every attendee.')),
    "pr_reviewers": ("github", ("reviewers",), ("Who reviewed pull request #{n}?", "List the reviewers of PR #{n}.",
                                                "Which people reviewed the GitHub pull request #{n}?")),
}
PROJECT_WORDINGS = ('Who is assigned issues in the Linear project "{p}"?', 'Which people have Linear issues in the project "{p}"?',
                    'List everyone assigned to an issue in the Linear project "{p}".')
CUSTOMER_WORDINGS = ("Which Jira tickets were raised by {c}? Give the ticket keys.", "List the Jira tickets for the customer {c}. Give the keys.",
                     "What Jira tickets has {c} opened? Keys please.")
PARENT_WORDINGS = {"status": ("What is the status of the parent issue of {k}?", "{k} sits under a parent issue. What state is that parent in?"),
                   "assignee": ("Who is assigned to the parent issue of {k}?", "{k} has a parent issue. Who is its assignee?")}
NF_TICKET = {"jira": ("What is the status of the Jira ticket {k}?", "Who is assigned to the Jira ticket {k}?"),
             "linear": ("Who is assigned to the Linear issue {k}?", "What is the status of the Linear issue {k}?")}
NF_PR = ("Who authored pull request #{n}?", "When was PR #{n} merged?", "Which repository is pull request #{n} in?")
NF_TITLE = {"google_drive": ('Who owns the Google Drive document "{t}"?', 'What is the status of the Drive doc "{t}"?'),
            "confluence": ('Who authored the Confluence page "{t}"?', 'When was the Confluence page "{t}" last updated?'),
            "hubspot": ('What stage is the HubSpot account "{t}" in?', 'Who owns the HubSpot account "{t}"?'),
            "fireflies": ('Who attended the meeting "{t}"?', 'When was the meeting "{t}" recorded?'),
            "linear": ('When is the Linear issue "{t}" due?',)}
NF_PERSON = ("List every Linear issue assigned to {p}. Give the issue keys.", "Which Jira tickets are assigned to {p}? Give the ticket keys.",
             "List every GitHub pull request authored by {p}. Give the pull request numbers.")
PERSON_FIELDS = ("assignee", "owner", "author", "reporter", "creator", "redwood_owner", "se_assigned")

_MEMORY = {"linear_due": "deadlines", "action_due": "deadlines", "linear_assignee": "lists", "linear_status": "lists",
           "linear_due_window": "lists", "jira_assignee": "lists", "github_author": "lists"}
CATALOGUE: dict[str, Kind] = {
    **{k: Kind(k, "single", g, "date, exact (factbank_test.direct)" if g == "deadlines" else "key or number list, F1 (factbank_test.direct)",
               "memory_test.generate_questions") for k, g in _MEMORY.items()},
    "metadata": Kind("metadata", "single", "owners", "the gold field value in the answer (factbank_test.direct)",
                     "the benchmark's metadata questions (memory_test.benchmark_questions)"),
    **{k: Kind(k, "single", "fields", f"{'date, exact' if t == 'date' else 'value in the answer'} (factbank_test.direct)",
               f"{s}.{f} of a uniquely named document") for k, (s, f, t, _) in FIELDS.items()},
    **{k: Kind(k, "single", "names", "person names, F1 (name_f1)", f"{s}: {', '.join(fs)}") for k, (s, fs, _) in NAMES.items()},
    "linear_project_members": Kind("linear_project_members", "single", "names", "person names, F1 (name_f1)",
                                   "linear: the assignees of a project's issues"),
    "customer_tickets": Kind("customer_tickets", "single", "lists", "key list, F1 (factbank_test.direct)", "jira: the tickets of a customer_company"),
    **{k: Kind(k, "multi", g, "values and dates exact, single keys exact, lists F1 (factbank_multi.own_score)", "factbank_multi.questions")
       for k, g in factbank_multi.GROUP.items()},
    "parent_issue": Kind("parent_issue", "multi", "link", "value in the answer (factbank_multi.own_score)",
                         "linear: parent_issue, then the parent's status or assignee"),
    **{k: Kind(k, "not_found", "not_found", "1 if the answer says not found, else 0", w) for k, w in (
        ("nf_ticket", "a ticket key in an existing prefix, written nowhere in the haystack"),
        ("nf_pr", "a pull request number written nowhere in the haystack"),
        ("nf_title", "a quoted title spliced from two real ones, written nowhere in the haystack"),
        ("nf_person", "a real first name and a real last name, the full name written nowhere in the haystack"))},
    "prose": Kind("prose", "prose", "prose", "share of the answer facts in the answer (evidence_audit.present)", "writers (load_prose)"),
}
MEMORY_KINDS = tuple(_MEMORY)
MULTI_KINDS = tuple(factbank_multi.GROUP)
DEFAULT_MIX = {"deadlines": 10, "lists": 10, "fields": 20, "names": 10, "link": 12, "combine": 12, "compare": 6, "not_found": 10, "prose": 10}


def kinds() -> list[dict[str, str]]:
    """The catalogue: each kind's name, family, group, how it is scored and where its questions come from."""
    return [asdict(k) for k in CATALOGUE.values()]


def family(q: dict[str, Any]) -> str:
    """The question's family: its own, its kind's, or read from its expected answer."""
    if q.get("family"):
        return q["family"]
    if q.get("kind") in CATALOGUE:
        return CATALOGUE[q["kind"]].family
    e = q.get("expected") or {}
    return "not_found" if e.get("not_found") else "prose" if "facts" in e else "single"


# ------------------------------------------------------------------ helpers
def _of(docs: Iterable[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    return sorted((d for d in docs if d["source"] == source), key=lambda d: d["dsid"])


def _names(docs: list[dict[str, Any]]) -> dict[str, Counter]:
    """How often each title (normalised), ticket key and pull request number names a document of the haystack."""
    return {"titles": Counter(_norm(d["title"]) for d in docs), "keys": Counter(k for d in docs if (k := _key(d))),
            "prs": Counter(p for d in docs if (p := _pr(d)))}


def _address(d: dict[str, Any], names: dict[str, Counter]) -> tuple[dict[str, str] | None, str]:
    """How a question names the document ({"t": title}, {"k": key} or {"n": number}) and that name; or None and why not."""
    how = ADDRESS[d["source"]]
    if how == "title":
        t = str(d["title"] or "").strip()
        if len(t) < 6 or '"' in t:
            return None, "title unusable"
        return ({"t": t}, t) if names["titles"][_norm(t)] == 1 else (None, "named twice")
    if how == "key":
        k = _key(d)
        if not k or not KEY.fullmatch(k):
            return None, "key unusable"
        return ({"k": k}, k) if names["keys"][k] == 1 else (None, "named twice")
    n = _pr(d)
    if not n or not n.isdigit() or not 2 <= len(n) <= 7:
        return None, "number unusable"
    return ({"n": n}, n) if names["prs"][n] == 1 else (None, "named twice")


def _alts(s: str) -> list[str]:
    return sorted({s.replace("_", " "), s.replace("-", " "), s.replace("_", " ").replace("-", " ")} - {s})


def _expected(v: Any, typ: str) -> tuple[dict[str, Any] | None, str]:
    """The expected answer for a field value of a type (person, value, customer, date, month), or None and why not."""
    if isinstance(v, list):
        if len(v) > 1:
            return None, "several values"
        v = v[0] if v else None
    if isinstance(v, dict):
        return None, "several values"
    s = str(v if v is not None else "").strip()
    if not s or s.lower() in EMPTY:
        return None, "no value"
    if typ == "date":
        x = _iso(s[:10]) or _iso(s)
        if not x:
            return None, "no value"
        try:
            date.fromisoformat(x)
        except ValueError:
            return None, "impossible date"
        try:
            when = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            when = None
        if when is not None and when.tzinfo is not None and when.astimezone(UTC).date() != when.date():
            return None, "several values"  # the local and the UTC date differ: two readings
        return {"date": x}, ""
    if typ == "month":
        m = re.fullmatch(r"(\d{4})-(\d{2})", s)
        if not m or not 1 <= int(m.group(2)) <= 12:
            return None, "no value"
        return {"value": s, "alts": [f"{MONTH_NAMES[int(m.group(2)) - 1]} {m.group(1)}"]}, ""
    if typ == "person":
        if re.search(r"[,;&/]|\band\b", s):
            return None, "several values"
        from cie.ingest.sources import person_name

        p = person_name(s)
        return ({"value": p}, "") if p else (None, "not a person")
    if len(s) > 80:
        return None, "no value"
    if typ == "customer" and s.lower().startswith("redwood"):
        return None, "internal"
    alts = _alts(s)
    return {"value": s, **({"alts": alts} if alts else {})}, ""


def _person(raw: Any) -> str | None:
    """A person's name (``person_name``), or None for a bot, a team, a group or a role label ('Redwood Recorder Bot',
    'Product Team', 'Revenue & Growth', 'Finance: Priya Desai', 'Unknown Speaker')."""
    from cie.ingest.sources import person_name

    p = person_name(raw)
    return None if p is None or NOT_PERSON_RE.search(p) else p


def _people(raw: dict[str, Any], fields: Iterable[str]) -> tuple[list[str] | None, str]:
    """The distinct people the fields list, or None and why not (an entry that is not a person makes the list inexact)."""
    from cie.ingest.sources import as_list

    items = [x for f in fields for x in as_list(raw.get(f)) if str(x).strip()]
    if not items:
        return None, "no value"
    names = [_person(x) for x in items]
    if any(n is None for n in names):
        return None, "not a person"
    out = list(dict.fromkeys(names))
    return (out, "") if len(out) <= LIST_MAX else (None, "too many")


def _words(s: Any) -> list[str]:
    return re.findall(r"[^\W_]+", str(s).lower())


def _squash(s: Any) -> str:
    """A name in lower case with only its letters and digits: 'AcmeAI', 'Acme AI' and 'acme-ai' are one name."""
    return "".join(_words(s))


def _nested(names: Iterable[str], outer: bool = True) -> set[str]:
    """The squashed names (``_squash``) of the names written as a run of whole words inside another name
    ('runtime-stability' in 'runtime-stability-2025', 'AcmeAI' in 'Acme AI (Corp)'), and with ``outer`` those of the names
    holding one too: one reading of such a name would name both."""
    names = list(names)
    runs: dict[str, set[str]] = defaultdict(set)
    for n in names:
        w = _words(n)
        for i in range(len(w)):
            for j in range(i + 1, len(w) + 1):
                if j - i < len(w):
                    runs["".join(w[i:j])].add("".join(w))
    out: set[str] = set()
    for n in names:
        s = _squash(n)
        holders = runs.get(s, set()) - {s}
        if holders:
            out.add(s)
            if outer:
                out |= holders
    return out


def _note(aside: Counter | None, why: str) -> None:
    if aside is not None:
        aside[why] += 1


def _emit(kind: str, cands: list[dict[str, Any]], rng: random.Random, cap: int | None) -> list[dict[str, Any]]:
    """Up to ``cap`` candidates (all when None) as questions, each in one of its wordings drawn by ``rng``."""
    if cap is not None and cap < len(cands):
        cands = rng.sample(cands, cap)
    k = CATALOGUE[kind]
    out = []
    for i, c in enumerate(cands, 1):
        w = rng.choice(c["wordings"])
        out.append({"id": f"{kind}-{i:03d}", "group": k.group, "kind": kind, "family": k.family, **({"field": c["field"]} if c.get("field") else {}),
                    "question": w.format(**c["fmt"]), "expected": c["expected"], "gold_docs": sorted(set(c["gold"])), "pieces": c["pieces"]})
    return out


# ------------------------------------------------------------------ single-document and list generators
def field_questions(kind: str, docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                    aside: Counter | None = None) -> list[dict[str, Any]]:
    """One field of a document named by a unique title, key or pull request number (``FIELDS``). A value written inside
    another value of the field ('redwood' in 'redwood-docs', 'Onboarding Revamp' in 'Dedicated Onboarding Revamp') is set
    aside: the other value would hold the expected one."""
    src, field, typ, wordings = FIELDS[kind]
    names = _names(docs)
    mine = _of(docs, src)
    exps = [_expected(d["raw"].get(field), typ) for d in mine]
    inner = _nested({e["value"] for e, _ in exps if e and "value" in e}, outer=False)
    cands = []
    for d, (exp, why) in zip(mine, exps, strict=True):
        fmt, name = _address(d, names)
        if fmt is None:
            exp, why = None, name
        elif exp is not None and "value" in exp and _squash(exp["value"]) in inner:
            exp, why = None, "named inside another"
        if exp is None:
            _note(aside, why)
            continue
        cands.append({"fmt": fmt, "expected": exp, "gold": [d["dsid"]], "pieces": [name, exp.get("date") or exp["value"]],
                      "wordings": wordings, "field": field})
    return _emit(kind, cands, rng, cap)


def name_questions(kind: str, docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                   aside: Counter | None = None) -> list[dict[str, Any]]:
    """The people one document lists (``NAMES``): a meeting's attendees, a pull request's reviewers."""
    src, fields, wordings = NAMES[kind]
    names = _names(docs)
    cands = []
    for d in _of(docs, src):
        fmt, name = _address(d, names)
        people, why = _people(d["raw"], fields) if fmt else (None, name)
        if people is None:
            _note(aside, why)
            continue
        cands.append({"fmt": fmt, "expected": {"names": people}, "gold": [d["dsid"]], "pieces": [name, *people], "wordings": wordings})
    return _emit(kind, cands, rng, cap)


def project_members(docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                    aside: Counter | None = None) -> list[dict[str, Any]]:
    """The people assigned issues in a Linear project of two or more issues ('model-onboarding' and 'Model Onboarding' are
    one project; one written inside another, as in 'model-onboarding-v2', is set aside)."""
    by: dict[str, list[dict]] = defaultdict(list)
    for d in _of(docs, "linear"):
        p = str(d["raw"].get("project") or "").strip()
        if p and p.lower() not in EMPTY and _squash(p):
            by[_squash(p)].append(d)
    nested = _nested({str(d["raw"]["project"]).strip() for ds in by.values() for d in ds})
    cands = []
    for key in sorted(by):
        ds = by[key]
        if len(ds) < 2:
            continue
        name = sorted({str(d["raw"]["project"]).strip() for d in ds})[0]
        if '"' in name:
            _note(aside, "title unusable")
            continue
        if key in nested:
            _note(aside, "named inside another")
            continue
        people, why = _people({"a": [d["raw"].get("assignee") for d in ds]}, ["a"])
        if people is None:
            _note(aside, why)
            continue
        cands.append({"fmt": {"p": name}, "expected": {"names": sorted(people)}, "gold": [d["dsid"] for d in ds],
                      "pieces": [name, *sorted(people)], "wordings": PROJECT_WORDINGS})
    return _emit("linear_project_members", cands, rng, cap)


def customer_tickets(docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                     aside: Counter | None = None) -> list[dict[str, Any]]:
    """The keys of every Jira ticket of one customer company (one to ``LIST_MAX`` tickets). 'AcmeAI' and 'Acme AI' are one
    customer; a customer written inside another, as 'Acme AI' in 'Acme AI (Corp)', is set aside."""
    names = _names(docs)
    by: dict[str, list[dict]] = defaultdict(list)
    for d in _of(docs, "jira"):
        c = str(d["raw"].get("customer_company") or "").strip()
        if c and c.lower() not in EMPTY and not c.lower().startswith("redwood") and _squash(c):
            by[_squash(c)].append(d)
    nested = _nested({str(d["raw"]["customer_company"]).strip() for ds in by.values() for d in ds})
    cands = []
    for key in sorted(by):
        ds = by[key]
        name = sorted({str(d["raw"]["customer_company"]).strip() for d in ds})[0]
        keys = sorted(_key(d) or "" for d in ds)
        if any(not k or not KEY.fullmatch(k) or names["keys"][k] != 1 for k in keys):
            _note(aside, "named twice")
            continue
        if key in nested:
            _note(aside, "named inside another")
            continue
        if len(keys) > LIST_MAX:
            _note(aside, "too many")
            continue
        cands.append({"fmt": {"c": name}, "expected": {"ids": keys, "id_kind": "key"}, "gold": [d["dsid"] for d in ds],
                      "pieces": [name, *keys], "wordings": CUSTOMER_WORDINGS})
    return _emit("customer_tickets", cands, rng, cap)


def parent_issue(docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                 aside: Counter | None = None) -> list[dict[str, Any]]:
    """The status or assignee of the parent of a Linear issue, both in the haystack (multi family)."""
    names = _names(docs)
    lin = {k: d for d in _of(docs, "linear") if (k := _key(d)) and KEY.fullmatch(k)}
    cands = []
    for k in sorted(lin):
        d = lin[k]
        parents = [p for p in dict.fromkeys(_keys(d["raw"].get("parent_issue"))) if p != k]
        if not parents or not any(p in lin for p in parents):
            continue
        if len(parents) > 1:
            _note(aside, "several values")
            continue
        p = parents[0]
        if names["keys"][k] != 1 or names["keys"][p] != 1:
            _note(aside, "named twice")
            continue
        have = [(f, e) for f, typ in (("status", "value"), ("assignee", "person")) if (e := _expected(lin[p]["raw"].get(f), typ)[0])]
        if not have:
            _note(aside, "no value")
            continue
        f, exp = rng.choice(have)
        cands.append({"fmt": {"k": k}, "expected": exp, "gold": [d["dsid"], lin[p]["dsid"]], "pieces": [p, exp["value"]],
                      "wordings": PARENT_WORDINGS[f], "field": f})
    return _emit("parent_issue", cands, rng, cap)


# ------------------------------------------------------------------ not-found generators
def _written(docs: list[dict[str, Any]]) -> str:
    """The haystack's whole text, titles and every field, in lower case."""
    return "\n".join(f"{d['title']}\n{json.dumps(d['raw'], ensure_ascii=False, default=str)}" for d in docs).lower()


def _invent(kind: str, make: Callable[[], dict[str, Any] | None], rng: random.Random, cap: int | None) -> list[dict[str, Any]]:
    """Up to ``cap`` (or ``NF_POOL``) distinct invented questions; ``make`` returns one candidate or None."""
    n = NF_POOL if cap is None else cap
    cands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _ in range(50 * n):
        if len(cands) >= n:
            break
        c = make()
        if c is not None and c["pieces"][0] not in seen:
            seen.add(c["pieces"][0])
            cands.append({**c, "expected": {"not_found": True}, "gold": []})
    return _emit(kind, cands, rng, None)


def missing_tickets(docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                    aside: Counter | None = None) -> list[dict[str, Any]]:
    """A Jira or Linear key in a prefix the haystack uses, with a number of the same length that no document writes."""
    real = sorted({(d["source"], k) for d in docs if (k := _key(d)) and KEY.fullmatch(k)})
    if not real:
        return []
    text = _written(docs)

    def make() -> dict[str, Any] | None:
        src, k = rng.choice(real)
        prefix, num = k.rsplit("-", 1)
        new = f"{prefix}-{rng.randrange(10 ** (len(num) - 1), 10 ** len(num))}"
        return None if new.lower() in text else {"fmt": {"k": new}, "pieces": [new], "wordings": NF_TICKET[src]}

    return _invent("nf_ticket", make, rng, cap)


def missing_prs(docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                aside: Counter | None = None) -> list[dict[str, Any]]:
    """A pull request number as long as a real one that no document writes, as a number or inside one."""
    real = sorted({p for d in docs if (p := _pr(d)) and p.isdigit() and 2 <= len(p) <= 7})
    if not real:
        return []
    text = _written(docs)

    def make() -> dict[str, Any] | None:
        size = len(rng.choice(real))
        new = str(rng.randrange(10 ** (size - 1), 10 ** size))
        return None if new in text else {"fmt": {"n": new}, "pieces": [new], "wordings": NF_PR}

    return _invent("nf_pr", make, rng, cap)


def missing_titles(docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                   aside: Counter | None = None) -> list[dict[str, Any]]:
    """A title spliced from the first half of one real title and the second half of another of the same source, that no
    document writes."""
    pools = {s: sorted({str(d["title"]).strip() for d in docs if d["source"] == s and '"' not in str(d["title"])
                        and len(str(d["title"]).split()) >= 2}) for s in NF_TITLE}
    pools = {s: v for s, v in pools.items() if len(v) >= 2}
    if not pools:
        return []
    titles = {_norm(d["title"]) for d in docs}
    text = _written(docs)

    def make() -> dict[str, Any] | None:
        src = rng.choice(sorted(pools))
        a, b = (x.split() for x in rng.sample(pools[src], 2))
        t = " ".join(a[: (len(a) + 1) // 2]).strip(" -–—:;,|") + " " + " ".join(b[len(b) // 2:]).strip(" -–—:;,|")
        t = t.strip()
        if len(t) < 6 or _norm(t) in titles or t.lower() in text:
            return None
        return {"fmt": {"t": t}, "pieces": [t], "wordings": NF_TITLE[src]}

    return _invent("nf_title", make, rng, cap)


def missing_people(docs: list[dict[str, Any]], rng: random.Random, cap: int | None = None,
                   aside: Counter | None = None) -> list[dict[str, Any]]:
    """A real first name and a real last name whose full name no document writes."""
    people = sorted({p for d in docs for f in PERSON_FIELDS if (p := _person(d["raw"].get(f))) and len(p.split()) == 2})
    if len(people) < 2:
        return []
    firsts, lasts = sorted({p.split()[0] for p in people}), sorted({p.split()[1] for p in people})
    text = _written(docs)
    known = {p.lower() for p in people}

    def make() -> dict[str, Any] | None:
        p = f"{rng.choice(firsts)} {rng.choice(lasts)}"
        return None if p.lower() in known or p.lower() in text else {"fmt": {"p": p}, "pieces": [p], "wordings": NF_PERSON}

    return _invent("nf_person", make, rng, cap)


GENERATORS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    **{k: partial(field_questions, k) for k in FIELDS}, **{k: partial(name_questions, k) for k in NAMES},
    "linear_project_members": project_members, "customer_tickets": customer_tickets, "parent_issue": parent_issue,
    "nf_ticket": missing_tickets, "nf_pr": missing_prs, "nf_title": missing_titles, "nf_person": missing_people,
}


# ------------------------------------------------------------------ prose questions
def load_prose(path: str | Path) -> list[dict[str, Any]]:
    """Writer-made questions from a JSONL file of {question, answer_facts, gold_docs} (``expected_doc_ids``, as the benchmark
    writes it, is read as ``gold_docs`` too), in family 'prose'. The answer facts are short strings written in the document."""
    out = []
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        facts = r.get("answer_facts")
        if not str(r.get("question") or "").strip() or not isinstance(facts, list) or not facts \
                or not all(isinstance(f, str) and f.strip() for f in facts):
            raise ValueError(f"{path}:{i}: a prose question needs a question and a list of answer facts")
        out.append({"id": str(r.get("id") or r.get("question_id") or f"prose-{len(out) + 1:03d}"), "group": "prose", "kind": "prose",
                    "family": "prose", "question": r["question"], "expected": {"facts": facts},
                    "gold_docs": list(r.get("gold_docs") or r.get("expected_doc_ids") or []), "pieces": facts})
    return out


# ------------------------------------------------------------------ every question, and a draw
def _memory_pieces(q: dict[str, Any]) -> list[str]:
    e = q["expected"]
    if "ids" in e:
        return list(e["ids"])
    return re.findall(r'"([^"]+)"', q["question"])[:1] + ([e["date"]] if "date" in e else [])


def _capped(qs: list[dict[str, Any]], cap: int | None, rng: random.Random) -> list[dict[str, Any]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for q in qs:
        by[q["kind"]].append(q)
    return [q for k in sorted(by) for q in (by[k] if cap is None or cap >= len(by[k]) else rng.sample(by[k], cap))]


def generate(docs: list[dict[str, Any]], seed: int = SEED, kinds: Iterable[str] | None = None, cap: int | None = None,
             multi_wordings: dict | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every question of the kinds (all but prose by default) the documents allow, at most ``cap`` per kind, and a report:
    questions per kind and what was set aside, by reason.

    The memory test's kinds come from ``memory_test.generate_questions`` and the multi-document kinds from
    ``factbank_multi.questions`` (held-out wordings, or ``multi_wordings``), unchanged; the latter are set aside by
    ``factbank_5k.why_unclear``. Each question gets its family, and the memory test's their pieces."""
    want = set(kinds) if kinds is not None else set(CATALOGUE) - {"prose", "metadata"}
    unknown = want - set(CATALOGUE)
    if unknown:
        raise ValueError(f"unknown kind(s) {sorted(unknown)}")
    out: list[dict[str, Any]] = []
    aside: dict[str, Counter] = defaultdict(Counter)
    if want & set(MEMORY_KINDS):
        for q in generate_questions(docs, seed, caps={k: ALL if cap is None else cap for k in CAPS}):
            if q["kind"] in want:
                out.append({**q, "family": "single", "pieces": q.get("pieces") or _memory_pieces(q)})
    if want & set(MULTI_KINDS):
        kept = []
        for q in factbank_multi.questions(docs, {d["dsid"] for d in docs}, True, seed, wordings=multi_wordings, max_q=None):
            if q["kind"] not in want:
                continue
            why = why_unclear(q, docs)
            if why:
                aside[q["kind"]][why] += 1
            else:
                kept.append({**q, "family": "multi"})
        out += _capped(kept, cap, random.Random(f"{seed}/multi"))
    for k in sorted(want & set(GENERATORS)):
        out += GENERATORS[k](docs, random.Random(f"{seed}/{k}"), cap, aside=aside[k])
    by_kind = Counter(q["kind"] for q in out)
    return out, {"by_kind": {k: by_kind[k] for k in CATALOGUE if k in want}, "aside": {k: dict(v) for k, v in sorted(aside.items()) if v}}


def resolve(key: str) -> set[str]:
    """The kinds a mix key names: a kind, a group or a family."""
    if key in CATALOGUE:
        return {key}
    out = {k.name for k in CATALOGUE.values() if key in (k.group, k.family)}
    if not out:
        raise ValueError(f"{key!r} is not a kind, group or family")
    return out


def quotas(mix: dict[str, int], available: Counter, seed: int = SEED) -> dict[str, int]:
    """Questions per kind for a mix: a group's or family's number is shared out among its kinds in turn, as far as each kind
    has questions; when it does not reach every kind, a seeded order decides which kinds come first."""
    quota: Counter = Counter()
    for key, n in mix.items():
        ks = sorted(k for k in resolve(key) if available[k] > quota[k])
        random.Random(f"{seed}/{key}").shuffle(ks)
        while n > 0 and ks:
            for k in list(ks):
                if n == 0:
                    break
                quota[k] += 1
                n -= 1
                if quota[k] >= available[k]:
                    ks.remove(k)
    return dict(quota)


def _about(q: dict[str, Any], by_id: dict[str, dict]) -> set[str]:
    """The documents a question is about: its gold documents, the meeting left out when there are others (two action items
    of one owner are about the same tickets)."""
    gold = set(q.get("gold_docs") or [])
    other = {x for x in gold if by_id.get(x, {}).get("source") != "fireflies"}
    return other or gold


def pick(qs: list[dict[str, Any]], docs: list[dict[str, Any]], quota: dict[str, int], seed: int = SEED) -> list[dict[str, Any]]:
    """``quota[kind]`` questions of each kind, as ``factbank_5k.pick`` picks them: kinds take turns in name order; within a
    kind a seeded order with the questions about something no earlier question of the kind asked about first; at each turn
    the first question about documents no chosen question is about, if there is one."""
    by_id = {d["dsid"]: d for d in docs}
    rng = random.Random(seed)
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for q in sorted(qs, key=lambda q: q["id"]):
        by_kind[q["kind"]].append(q)
    for k in sorted(by_kind):
        rng.shuffle(by_kind[k])
        seen: set[str] = set()
        first, later = [], []
        for q in by_kind[k]:
            t = json.dumps(sorted(_about(q, by_id)) or q.get("pieces") or q["question"])
            (later if t in seen else first).append(q)
            seen.add(t)
        by_kind[k] = first + later
    left = {k: n for k, n in quota.items() if n > 0}
    chosen: list[dict[str, Any]] = []
    about: set[str] = set()
    while any(left[k] and by_kind[k] for k in left):
        for k in sorted(left):
            if left[k] and by_kind[k]:
                i = next((j for j, q in enumerate(by_kind[k]) if not _about(q, by_id) & about), 0)
                q = by_kind[k].pop(i)
                chosen.append(q)
                about |= _about(q, by_id)
                left[k] -= 1
    return chosen


def draw_questions(docs: list[dict[str, Any]], seed: int = SEED, mix: dict[str, int] | None = None,
                   prose: list[dict[str, Any]] | None = None, multi_wordings: dict | None = None) -> list[dict[str, Any]]:
    """A seeded sample of the questions the documents allow, in a mix of {kind, group or family: number} (``DEFAULT_MIX``);
    prose questions come from ``prose`` (``load_prose``), those code can check (``checkable``). A kind with too few
    questions gives what it has."""
    mix = dict(DEFAULT_MIX if mix is None else mix)
    wanted = set().union(*(resolve(k) for k in mix)) if mix else set()
    pool, _ = generate(docs, seed, kinds=wanted - {"prose", "metadata"}, multi_wordings=multi_wordings)
    if "prose" in wanted:
        pool += [q for q in prose or [] if checkable(q)]
    return pick(pool, docs, quotas(mix, Counter(q["kind"] for q in pool), seed), seed)


# ------------------------------------------------------------------ scoring
def says_not_found(answer: str, route: str | None = None) -> bool:
    """Whether the answer is "not found": the brain's route says so, or its answer line starts with it."""
    return route == "not_found" or bool(NOT_FOUND_RE.match(final_answer(answer or "")))


def _name_key(s: str) -> str:
    from cie.ingest.sources import person_name

    t = re.sub(r"[^\w\s-]", " ", _norm(person_name(s) or s))
    return re.sub(r"^(?:dr|mr|mrs|ms|prof)\s+", "", re.sub(r"\s+", " ", t).strip())


def name_f1(names: list[str], answer: str) -> float:
    """F1 of an answer's names against the expected names, normalised (roles, titles, quotes and case dropped). The answer
    line is cut at commas, semicolons, line breaks and "and"; a part is right when it holds an expected name."""
    want = {k for k in (_name_key(n) for n in names) if k}
    parts = [k for k in (_name_key(p) for p in re.split(r"[,;\n&]|\band\b", final_answer(answer or ""), flags=re.I)) if k]
    if not want or not parts:
        return 0.0

    def holds(part: str, name: str) -> bool:
        return bool(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", part))

    p = sum(1 for x in parts if any(holds(x, w) for w in want)) / len(parts)
    r = sum(1 for w in want if any(holds(x, w) for x in parts)) / len(want)
    return round(2 * p * r / (p + r), 3) if p and r else 0.0


def _checkable(facts: list[str]) -> list[str]:
    from cie.eval.evidence_audit import fact_terms

    return [f for f in facts if any(fact_terms(f))]


def fact_share(facts: list[str], text: str) -> float:
    """The share of the answer facts (those with a number or a content word) present in the text (``evidence_audit.present``)."""
    from cie.eval.evidence_audit import _stems, present

    facts = _checkable(facts)
    if not facts:
        return 0.0
    stems = _stems(text or "")
    return round(sum(present(f, text or "", stems) for f in facts) / len(facts), 3)


def prose_reach(q: dict[str, Any], evidence: str, budget: int = EVIDENCE_CHARS) -> float:
    """The share of a prose question's answer facts within the first ``budget`` characters of the evidence, each held by one
    passage (blocks between blank lines), as ``evidence_audit`` counts them."""
    from cie.eval.evidence_audit import _stems, present

    facts = _checkable((q.get("expected") or {}).get("facts") or [])
    if not facts:
        return 0.0
    blocks = [(b, _stems(b)) for b in re.split(r"\n\s*\n", (evidence or "")[:budget]) if b.strip()]
    return round(sum(any(present(f, b, st) for b, st in blocks) for f in facts) / len(facts), 3)


def checkable(q: dict[str, Any]) -> bool:
    """Whether code can score an answer to the question: it expects not found, names, a value, a date, keys, or answer facts
    with a number or a content word. A benchmark metadata question whose field held nothing cannot be scored
    (``memory_test.check`` marks it None)."""
    e = q.get("expected") or {}
    fam = family(q)
    if fam == "not_found":
        return True
    if fam == "prose":
        return bool(_checkable(e.get("facts") or []))
    return any(e.get(x) for x in ("names", "value", "date", "ids"))


def value_hit(e: dict[str, Any], answer: str) -> float:
    """1 if the answer line, read as ``factbank_test.direct`` reads it, holds the expected value or one of its alternatives
    between boundaries that no letter, digit or hyphen crosses ('redwood-docs' does not hold 'redwood'), else 0."""
    line = _norm(final_answer("Answer: " + answer))
    return float(any(re.search(r"(?<![\w-])" + re.escape(_norm(v)) + r"(?![\w-])", line) for v in [e["value"], *e.get("alts", [])]))


def score(q: dict[str, Any], row: dict[str, Any] | str) -> float | None:
    """One answer's score in [0, 1]. ``row`` is the brain's row ({"answer", "route"?}) or the answer itself. A question of a
    catalogue kind that code cannot check (``checkable``) scores None, and callers leave it out, as ``memory_test.check``
    does; one of another kind raises ValueError.

    - not_found: 1 if the answer says not found, else 0; for every other kind an answer of not found scores 0;
    - prose: the share of the answer facts in the answer;
    - name lists: ``name_f1``;
    - multi: ``factbank_multi.own_score``;
    - the field kinds with a value: ``value_hit``. For the field kinds a timestamp in the answer ("2027-03-25T15:00:00Z") is
      read as its date, as the field was;
    - the rest (the memory test's kinds, the field kinds with a date, and the list kinds): ``factbank_test.direct``."""
    if not checkable(q):
        if q.get("kind") in CATALOGUE:
            return None
        raise ValueError(f"{q.get('id')}: no expected answer that code can check")
    answer, route = (row, None) if isinstance(row, str) else (str(row.get("answer") or ""), row.get("route"))
    if q.get("kind") in FIELDS:
        answer = re.sub(r"\b(\d{4}-\d{2}-\d{2})T(?=\d)", r"\1 ", answer)
    nf = says_not_found(answer, route)
    fam = family(q)
    if fam == "not_found":
        return float(nf)
    if nf:
        return 0.0
    e = q.get("expected") or {}
    if fam == "prose":
        return fact_share(e.get("facts") or [], answer)
    if "names" in e:
        return name_f1(e["names"], answer)
    if q.get("kind") in FIELDS and "value" in e:
        return value_hit(e, answer)
    return own_score(q, answer) if fam == "multi" else direct(q, answer)
