"""Complex questions for the company brain at 50,000 documents: two to four steps over two or more documents, each answer
computed from the documents' raw fields (docs/FACTBANK_50K_PLAN.md).

Round 4's multi-document questions take at most two steps: a pull request's Linear issue and one of its fields, a person's
Linear issues. These chain more, cross systems, and count, filter or order on the way:

| kind | steps | answer |
|---|---|---|
| pr_assignee_load | pull request -> its Linear issue -> the assignee -> that person's Linear issues, counted | a count |
| pr_parent_assignee | pull request -> its Linear issue -> the parent issue -> its assignee | a person |
| meeting_account_owner | Fireflies meeting -> its customer -> the customer's HubSpot account -> the owner | a person |
| meeting_account_stage | Fireflies meeting -> its customer -> the customer's HubSpot account -> the stage | a value |
| email_account_owner | email thread -> its account -> the HubSpot account -> the owner | a person |
| creator_jira_load | Linear issue -> its creator -> the Jira tickets assigned to that person, counted | a count |
| project_first_due | a Linear project -> its issues -> the one due first -> its assignee | a person |
| compare_due_assignee | two Linear issues -> the one due first -> its assignee | a person |
| assignee_open_p | Linear issue -> its assignee -> that person's open Linear issues of one priority, counted | a count |
| owner_meetings | Fireflies meeting -> its Redwood owner -> the meetings that person owned, counted | a count |

Every step must have one reading in the haystack, or the question is set aside with its reason:
- each document a question names is named by one document (``brain_questions._address``);
- a person is a full name (``brain2_questions._full_name``), and no other document of the system writes it in another form
  in the same field ('Dr. Priya Nair', 'Priya Nair, Ava Lee');
- a pull request links one Linear issue of the haystack, which no other pull request links;
- a customer or account name is the title of exactly one HubSpot account, written inside no other account's title;
- an order has no tie (the first due date is one issue's), and every issue of the project has a due date;
- a count is at least ``COUNT_MIN`` and at most ``COUNT_MAX``, so that "not found" or a guess of one is never right by chance;
- no answer is written in its question.

"Open" is a status other than Done or Canceled (``brain2_questions.CLOSED``), as round 2's counts read it. Each kind has
three wordings, one of them typed casually, drawn by the seed. ``score`` scores an answer: a count by its first number
(``brain2_questions.count_hit``), a person or value by ``brain_questions.value_hit``; "not found" scores 0.

    python -m cie.eval.complex_questions draw --work W --per-kind 16 --seed 5051 --out Q.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cie.eval import brain2_questions as Q2
from cie.eval import brain_questions as B
from cie.eval.factbank_5k import _key
from cie.eval.factbank_multi import KEY, _keys

FAMILY = "complex"
COUNT_MIN = 2
COUNT_MAX = 40
PER_KIND = 16
SEED = 5051

WORDINGS: dict[str, tuple[str, ...]] = {
    "pr_assignee_load": (
        "How many Linear issues are assigned to the person who is assigned the Linear issue linked from pull request #{n}?",
        "Pull request #{n} links a Linear issue. How many Linear issues in total are assigned to that issue's assignee?",
        "quick q - whoever owns the linear ticket from PR #{n}, how many linear issues do they have on them overall?"),
    "pr_parent_assignee": (
        "Who is assigned to the parent issue of the Linear issue that pull request #{n} links?",
        "PR #{n} references a Linear issue that has a parent issue. Who is the parent issue assigned to?",
        "who's got the parent of the linear issue tied to PR #{n}?"),
    "meeting_account_owner": (
        'Who owns the HubSpot account of the customer in the Fireflies meeting "{t}"?',
        'The meeting "{t}" was with a customer. Who is the owner of that customer\'s HubSpot account?',
        'who owns the hubspot account for the customer from the "{t}" call?'),
    "meeting_account_stage": (
        'What stage is the HubSpot account of the customer in the meeting "{t}" at?',
        'The Fireflies meeting "{t}" was with a customer. Which stage is their HubSpot account in?',
        'what stage is the customer from the "{t}" meeting at in hubspot?'),
    "email_account_owner": (
        'Who owns the HubSpot account that the email thread "{s}" is about?',
        'The email thread "{s}" is about an account. Who is the owner of that account in HubSpot?',
        'who owns the hubspot account the "{s}" email is about?'),
    "creator_jira_load": (
        "How many Jira tickets are assigned to the person who created the Linear issue {k}?",
        "Someone created Linear issue {k}. How many Jira tickets is that person assigned?",
        "the person who opened {k} in linear - how many jira tickets are assigned to them?"),
    "project_first_due": (
        'In the Linear project "{p}", who is assigned to the issue that is due first?',
        'Of the Linear issues in the project "{p}", which one is due earliest, and who is assigned to it? Give the person.',
        'who has the soonest-due issue in the "{p}" project in linear?'),
    "compare_due_assignee": (
        "Of the Linear issues {k1} and {k2}, who is assigned to the one that is due first?",
        "{k1} and {k2} are Linear issues. Whose is due sooner? Give the assignee.",
        "between {k1} and {k2}, which is due first - and who's on it?"),
    "assignee_open_p": (
        "How many open Linear issues with priority {pr} are assigned to the assignee of {k}?",
        "Who is assigned {k}? Count the Linear issues with priority {pr} that this person has and that are not Done or Canceled.",
        "how many open {pr} linear issues does the person on {k} have?"),
    "owner_meetings": (
        'How many Fireflies meetings did the Redwood owner of the meeting "{t}" own?',
        'Someone on the Redwood side owned the meeting "{t}". How many meetings did that person own in total?',
        'how many meetings has the redwood owner of "{t}" owned?'),
}
ANSWER = {"pr_assignee_load": "count", "pr_parent_assignee": "person", "meeting_account_owner": "person",
          "meeting_account_stage": "value", "email_account_owner": "person", "creator_jira_load": "count",
          "project_first_due": "person", "compare_due_assignee": "person", "assignee_open_p": "count", "owner_meetings": "count"}
STEPS = {"pr_assignee_load": 4, "pr_parent_assignee": 4, "meeting_account_owner": 4, "meeting_account_stage": 4,
         "email_account_owner": 4, "creator_jira_load": 3, "project_first_due": 3, "compare_due_assignee": 3,
         "assignee_open_p": 4, "owner_meetings": 3}
KINDS = tuple(WORDINGS)


# ------------------------------------------------------------------ what the steps read
class People:
    """The documents of a system whose field names each full name, and the names written there in another form."""

    def __init__(self, hay: Q2.Haystack, source: str, field: str):
        self.by: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.raw_text: list[tuple[dict[str, Any], str]] = []
        for d in hay.of(source):
            v = d["raw"].get(field)
            if p := Q2._full_name(v):
                self.by[p].append(d)
            if v:
                self.raw_text.append((d, json.dumps(v, ensure_ascii=False, default=str)))

    def of(self, p: str) -> tuple[list[dict[str, Any]] | None, str]:
        """The documents of person ``p``, or None when another document writes the name in another form."""
        ds = self.by.get(p, [])
        ids = {d["dsid"] for d in ds}
        if any(d["dsid"] not in ids and Q2._in(p, t) for d, t in self.raw_text):
            return None, "the name in another form"
        return ds, ""


def _linear(hay: Q2.Haystack) -> dict[str, dict[str, Any]]:
    return {k: d for d in hay.of("linear") if (k := _key(d)) and KEY.fullmatch(k) and hay.names["keys"][k] == 1}


def pr_issues(hay: Q2.Haystack) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    """(pull request, its Linear issue, the pull request's number) for every pull request named by one document that links
    exactly one Linear issue of the haystack, which no other pull request links."""
    lin = _linear(hay)
    linked: dict[str, list[dict]] = defaultdict(list)
    out = []
    for d in hay.of("github"):
        ks = [k for k in dict.fromkeys(_keys(d["raw"].get("linked_linear"))) if k in lin]
        for k in ks:
            linked[k].append(d)
    for d in hay.of("github"):
        fmt, _ = hay.address(d)
        ks = [k for k in dict.fromkeys(_keys(d["raw"].get("linked_linear"))) if k in lin]
        if fmt and len(ks) == 1 and len(linked[ks[0]]) == 1:
            out.append((d, lin[ks[0]], fmt["n"]))
    return out


def accounts(hay: Q2.Haystack) -> dict[str, dict[str, Any]]:
    """The HubSpot accounts by squashed title, each title on one document and inside no other account's title."""
    titles = Counter(Q2._squash(d["title"]) for d in hay.of("hubspot"))
    inner = Q2._nested({str(d["title"]).strip() for d in hay.of("hubspot")}, outer=True)
    return {s: d for d in hay.of("hubspot") if (s := Q2._squash(d["title"])) and titles[s] == 1 and s not in inner}


def _value(raw: Any) -> str | None:
    e, _ = B._expected(raw, "value")
    return e["value"] if e else None


def _due(d: dict[str, Any]) -> str | None:
    e, _ = B._expected(d["raw"].get("due_date"), "date")
    return e["date"] if e else None


def _open(d: dict[str, Any]) -> bool:
    s = str(d["raw"].get("status") or "").strip().lower()
    return bool(s) and s not in Q2.CLOSED["linear"]


# ------------------------------------------------------------------ the kinds
Cand = dict[str, Any]


def _cand(kind: str, fmt: dict[str, str], value: str, gold: list[str], pieces: list[str]) -> Cand:
    e: dict[str, Any] = {"value": str(value)}
    return {"kind": kind, "fmt": fmt, "expected": e, "gold": gold, "pieces": [str(p) for p in pieces]}


def k_pr_assignee_load(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    people, out = People(hay, "linear", "assignee"), []
    for pr, iss, n in pr_issues(hay):
        p = Q2._full_name(iss["raw"].get("assignee"))
        if p is None:
            aside["no full-named assignee"] += 1
            continue
        ds, why = people.of(p)
        if ds is None or not COUNT_MIN <= len(ds) <= COUNT_MAX:
            aside[why or "count out of range"] += 1
            continue
        out.append(_cand("pr_assignee_load", {"n": n}, str(len(ds)), [pr["dsid"], *(d["dsid"] for d in ds)], [n, _key(iss), p]))
    return out


def k_pr_parent_assignee(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    lin, out = _linear(hay), []
    for pr, iss, n in pr_issues(hay):
        parents = [k for k in dict.fromkeys(_keys(iss["raw"].get("parent_issue"))) if k != _key(iss)]
        if len(parents) != 1 or parents[0] not in lin:
            aside["no parent issue in the haystack"] += 1
            continue
        par = lin[parents[0]]
        p = Q2._full_name(par["raw"].get("assignee"))
        if p is None:
            aside["no full-named assignee"] += 1
            continue
        out.append(_cand("pr_parent_assignee", {"n": n}, p, [pr["dsid"], iss["dsid"], par["dsid"]], [n, _key(iss), parents[0], p]))
    return out


def _meeting_account(hay: Q2.Haystack, field: str, typ: str, kind: str, aside: Counter) -> list[Cand]:
    accts, out = accounts(hay), []
    for m in hay.of("fireflies"):
        fmt, _ = hay.address(m)
        if fmt is None:
            aside["meeting named twice or unusable"] += 1
            continue
        c = _value(m["raw"].get("customer_company"))
        a = accts.get(Q2._squash(c)) if c else None
        if a is None:
            aside["no one HubSpot account for the customer"] += 1
            continue
        v = Q2._full_name(a["raw"].get(field)) if typ == "person" else _value(a["raw"].get(field))
        if v is None:
            aside[f"no {field}"] += 1
            continue
        out.append(_cand(kind, fmt, v, [m["dsid"], a["dsid"]], [fmt["t"], str(a["title"]), v]))
    return out


def k_meeting_account_owner(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    return _meeting_account(hay, "owner", "person", "meeting_account_owner", aside)


def k_meeting_account_stage(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    return _meeting_account(hay, "stage", "value", "meeting_account_stage", aside)


def k_email_account_owner(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    accts, out = accounts(hay), []
    for t in hay.of("gmail"):
        fmt, _ = hay.address(t)
        a_name = _value(t["raw"].get("related_account"))
        a = accts.get(Q2._squash(a_name)) if a_name else None
        if fmt is None or a is None:
            aside["thread or account unusable"] += 1
            continue
        p = Q2._full_name(a["raw"].get("owner"))
        if p is None:
            aside["no full-named owner"] += 1
            continue
        out.append(_cand("email_account_owner", fmt, p, [t["dsid"], a["dsid"]], [fmt["s"], str(a["title"]), p]))
    return out


def k_creator_jira_load(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    people, out = People(hay, "jira", "assignee"), []
    for d in _linear(hay).values():
        p = Q2._full_name(d["raw"].get("creator"))
        if p is None:
            aside["no full-named creator"] += 1
            continue
        ds, why = people.of(p)
        if ds is None or not COUNT_MIN <= len(ds) <= COUNT_MAX:
            aside[why or "count out of range"] += 1
            continue
        out.append(_cand("creator_jira_load", {"k": _key(d)}, str(len(ds)), [d["dsid"], *(x["dsid"] for x in ds)], [_key(d), p]))
    return out


def k_project_first_due(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    by: dict[str, list[dict]] = defaultdict(list)
    for d in hay.of("linear"):
        if p := _value(d["raw"].get("project")):
            by[p].append(d)
    names = {Q2._squash(p) for p in by}
    out = []
    for proj, ds in sorted(by.items()):
        dues = [(_due(d), d) for d in ds]
        if not 3 <= len(ds) <= COUNT_MAX or any(x is None for x, _ in dues) or '"' in proj:
            aside["project too small, too large or with an issue not due"] += 1
            continue
        if sum(Q2._squash(proj) in n and Q2._squash(proj) != n for n in names):
            aside["project named inside another"] += 1
            continue
        dues.sort(key=lambda x: x[0])
        if dues[0][0] == dues[1][0]:
            aside["tie for first due"] += 1
            continue
        first = dues[0][1]
        p = Q2._full_name(first["raw"].get("assignee"))
        if p is None or _key(first) is None:
            aside["no full-named assignee"] += 1
            continue
        out.append(_cand("project_first_due", {"p": proj}, p, [d["dsid"] for d in ds], [proj, _key(first), dues[0][0], p]))
    return out


def k_compare_due_assignee(hay: Q2.Haystack, aside: Counter, rng: random.Random) -> list[Cand]:
    lin = _linear(hay)
    by: dict[str, list[dict]] = defaultdict(list)
    for d in lin.values():
        if (p := _value(d["raw"].get("project"))) and _due(d) and Q2._full_name(d["raw"].get("assignee")):
            by[p].append(d)
    out = []
    for proj in sorted(by):
        ds = sorted(by[proj], key=lambda d: d["dsid"])
        if len(ds) < 2:
            continue
        a, b = rng.sample(ds, 2)
        pa, pb = Q2._full_name(a["raw"].get("assignee")), Q2._full_name(b["raw"].get("assignee"))
        if _due(a) == _due(b) or pa == pb:
            aside["same due date or assignee"] += 1
            continue
        first = a if _due(a) < _due(b) else b
        p = Q2._full_name(first["raw"].get("assignee"))
        k1, k2 = sorted((_key(a), _key(b)))
        out.append(_cand("compare_due_assignee", {"k1": k1, "k2": k2}, p, [a["dsid"], b["dsid"]], [k1, k2, _key(first), p]))
    return out


def k_assignee_open_p(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    people, out = People(hay, "linear", "assignee"), []
    for d in _linear(hay).values():
        p = Q2._full_name(d["raw"].get("assignee"))
        pr = _value(d["raw"].get("priority"))
        if p is None or not pr or not re.fullmatch(r"P[0-4]", pr):
            aside["no full-named assignee or P priority"] += 1
            continue
        ds, why = people.of(p)
        if ds is None:
            aside[why] += 1
            continue
        hits = [x for x in ds if _open(x) and _value(x["raw"].get("priority")) == pr]
        if not COUNT_MIN <= len(hits) <= COUNT_MAX or len(hits) == len(ds):
            aside["count out of range, or every issue of the person counted"] += 1
            continue
        out.append(_cand("assignee_open_p", {"k": _key(d), "pr": pr}, str(len(hits)), [d["dsid"], *(x["dsid"] for x in hits)],
                         [_key(d), p, pr]))
    return out


def k_owner_meetings(hay: Q2.Haystack, aside: Counter) -> list[Cand]:
    people, out = People(hay, "fireflies", "redwood_owner"), []
    for m in hay.of("fireflies"):
        fmt, _ = hay.address(m)
        p = Q2._full_name(m["raw"].get("redwood_owner")) if fmt else None
        if p is None:
            aside["meeting unusable or no full-named owner"] += 1
            continue
        ds, why = people.of(p)
        if ds is None or not COUNT_MIN <= len(ds) <= COUNT_MAX:
            aside[why or "count out of range"] += 1
            continue
        out.append(_cand("owner_meetings", fmt, str(len(ds)), [x["dsid"] for x in ds], [fmt["t"], p]))
    return out


GENERATORS: dict[str, Callable[..., list[Cand]]] = {
    "pr_assignee_load": k_pr_assignee_load, "pr_parent_assignee": k_pr_parent_assignee,
    "meeting_account_owner": k_meeting_account_owner, "meeting_account_stage": k_meeting_account_stage,
    "email_account_owner": k_email_account_owner, "creator_jira_load": k_creator_jira_load,
    "project_first_due": k_project_first_due, "compare_due_assignee": k_compare_due_assignee,
    "assignee_open_p": k_assignee_open_p, "owner_meetings": k_owner_meetings,
}


def _leaks(c: Cand, question: str) -> bool:
    """Whether the expected answer is written in the question (a count is never: the question holds no such number)."""
    v = c["expected"]["value"]
    return ANSWER[c["kind"]] != "count" and Q2._in(v, question)


def draw(docs: list[dict[str, Any]], per_kind: int = PER_KIND, seed: int = SEED) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Up to ``per_kind`` questions of each kind, drawn by ``seed`` from the candidates every step of which has one
    reading, each in one of its kind's wordings; with the report of the candidates and the reasons the rest were set aside."""
    hay = Q2.Haystack(docs)
    rng = random.Random(seed)
    qs, rep = [], {"candidates": {}, "drawn": {}, "aside": {}}
    for kind, gen in GENERATORS.items():
        aside: Counter = Counter()
        cands = gen(hay, aside, random.Random(f"{seed}-{kind}")) if kind == "compare_due_assignee" else gen(hay, aside)
        kept = []
        seen: set[tuple] = set()
        for c in cands:
            w = WORDINGS[kind][0].format(**c["fmt"])
            if _leaks(c, w):
                aside["answer in the question"] += 1
            elif (sig := (kind, json.dumps(c["fmt"], sort_keys=True))) in seen:
                aside["asked twice"] += 1
            else:
                seen.add(sig)
                kept.append(c)
        pick = rng.sample(kept, per_kind) if len(kept) > per_kind else list(kept)
        for i, c in enumerate(pick, 1):
            text = rng.choice(WORDINGS[kind]).format(**c["fmt"])
            qs.append({"id": f"complex-{kind}-{i:03d}", "family": FAMILY, "group": "complex", "kind": kind, "answer_type": ANSWER[kind],
                       "steps": STEPS[kind], "question": text, "expected": c["expected"], "gold_docs": sorted(set(c["gold"])),
                       "pieces": c["pieces"], "generated": True})
        rep["candidates"][kind], rep["drawn"][kind], rep["aside"][kind] = len(kept), len(pick), dict(aside)
    rep["questions"] = len(qs)
    return qs, rep


def score(q: dict[str, Any], row: dict[str, Any] | str) -> float:
    """One answer's score: 0 for "not found"; a count by its first number; a person or value found in the answer line."""
    answer, route = (row, None) if isinstance(row, str) else (str(row.get("answer") or ""), row.get("route"))
    if B.says_not_found(answer, route):
        return 0.0
    if q["answer_type"] == "count":
        return Q2.count_hit(int(q["expected"]["value"]), answer)
    return B.value_hit(q["expected"], answer)


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.complex_questions", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--work", type=Path, required=True)
    d.add_argument("--per-kind", type=int, default=PER_KIND)
    d.add_argument("--seed", type=int, default=SEED)
    d.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    from cie.eval.brain_test import load_docs

    qs, rep = draw(load_docs(a.work), a.per_kind, a.seed)
    a.out.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in qs))
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
