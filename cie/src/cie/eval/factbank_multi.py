"""Questions that need several documents: a training set and a held-out set (docs/FACTBANK_MULTI_PREREGISTRATION.md).

Each question's answer is spread over two or more documents, and code can check it:
* **link:** follow a link from one document to another and read a field there:
  - a pull request → the Linear issue it links → its assignee, due date or status;
  - a Linear issue → the pull request that references it → its author;
  - a Jira or Linear ticket → the ticket it links → its status or assignee.
* **combine:** gather facts from several documents:
  - how many Linear issues a person has;
  - which of their issues is due first;
  - the Linear issues of whoever took a given meeting action item (meeting → action item → person → their issues).
* **compare:** which of two Linear issues is due first.

The two sets share no document. Each has 50 documents and every document a question needs, and every expected answer is
computed within its own set. The training questions use three wordings per kind, the held-out questions two others. All
wordings were written before anything was learned.

    python -m cie.eval.factbank_multi build --docs hay5k_docs.json --index <index.json> --root <benchmark> --train $A --test $B
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from cie.eval.memory_test import _iso, _jsonl, _write_jsonl, action_items

N_DOCS = 50
MAX_Q = 50
SEED = 11
KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{2,7}\b")
GROUP = {"pr_issue": "link", "issue_pr_author": "link", "ticket_link": "link", "person_count": "combine", "person_first": "combine",
         "action_owner_issues": "combine", "compare_two": "compare"}

T = {  # kind (and field) -> (training wordings, held-out wordings)
    ("pr_issue", "assignee"): (["Who is assigned to the Linear issue that pull request #{n} is linked to?",
                                "Pull request #{n} links a Linear ticket. Who is its assignee?",
                                "Which person has the Linear issue referenced by PR #{n} assigned to them?"],
                               ["PR #{n} points at a Linear issue. Who's working on it?",
                                "Find the Linear ticket tied to pull request #{n}: who is it assigned to?"]),
    ("pr_issue", "due_date"): (["When is the Linear issue linked from PR #{n} due?",
                                "What is the due date of the Linear ticket that pull request #{n} references?",
                                "Pull request #{n} is tied to a Linear issue. What is that issue's deadline?"],
                               ["By when does the Linear work behind PR #{n} need to be done?",
                                "PR #{n} links a Linear ticket; when is that ticket due?"]),
    ("pr_issue", "status"): (["What is the status of the Linear ticket that pull request #{n} references?",
                              "Pull request #{n} is linked to a Linear issue; what state is that issue in?",
                              "What's the current status of the Linear issue tied to PR #{n}?"],
                             ["Where does the Linear issue behind PR #{n} stand right now? Give its status.",
                              "PR #{n} references a Linear ticket. What status is it in?"]),
    ("issue_pr_author", "author"): (["Who authored the pull request linked to Linear issue {k}?",
                                     "Linear ticket {k} is referenced by a pull request. Who wrote that PR?",
                                     "Which person opened the PR that references {k}?"],
                                    ["Somebody opened a PR that points at {k}. Who was it?",
                                     "Who is the author of the GitHub pull request tied to {k}?"]),
    ("ticket_link", "status"): (["What is the status of the ticket that {k} is linked to?",
                                 "{k} links another ticket. What state is that ticket in?",
                                 "Give the status of the issue linked from {k}."],
                                ["{k} is tied to another ticket. Where does that one stand?",
                                 "Check the ticket linked from {k}: what's its status?"]),
    ("ticket_link", "assignee"): (["Who is assigned to the ticket that {k} is linked to?",
                                   "{k} links another ticket. Who is its assignee?",
                                   "Which person has the issue linked from {k}?"],
                                  ["{k} points at another ticket. Who's on it?",
                                   "Find the ticket linked from {k}: who is it assigned to?"]),
    ("person_count", ""): (["How many Linear issues are assigned to {p}?",
                            "What is the number of Linear tickets with {p} as assignee?",
                            "Count the Linear issues assigned to {p}."],
                           ["How many Linear tickets does {p} have on their plate?",
                            "{p}: how many Linear issues are assigned to them?"]),
    ("person_first", ""): (["Which of the Linear issues assigned to {p} is due first? Give the key.",
                            "Among the Linear tickets assigned to {p}, which has the earliest due date? Give the key.",
                            "What is the first Linear issue {p} has due? Give the key."],
                           ["Of the Linear work assigned to {p}, which ticket's deadline comes soonest? Key please.",
                            "Which Linear issue on {p}'s plate must be finished first? Give the key."]),
    ("compare_two", ""): (["Which is due sooner, {a} or {b}?",
                           "Between Linear issues {a} and {b}, which has the earlier due date?",
                           "{a} or {b}: which one is due first?"],
                          ["Of {a} and {b}, which deadline comes first?",
                           "Which needs finishing earlier: {a} or {b}?"]),
    ("action_owner_issues", ""): (['Which Linear issues are assigned to the person who took the action item "{t}" in the meeting "{m}"? '
                                   'Give the keys.',
                                   'In the meeting "{m}", someone took the action item "{t}". List the Linear tickets assigned to that '
                                   'person. Give the keys.',
                                   'Give the keys of the Linear issues assigned to whoever owns the action item "{t}" from "{m}".'],
                                  ['Whoever picked up "{t}" in "{m}": which Linear tickets are on their plate? Keys only.',
                                   'The action item "{t}" from "{m}" went to someone. What Linear issues are assigned to them? Keys please.']),
}


# The retest (docs/FACTBANK_MULTI_RETEST_PREREGISTRATION.md): a third pair of wordings per kind, written after the first test and
# before the retest's documents were chosen. Neither the first test's documents nor its wordings are used again.
RETEST = {
    ("pr_issue", "assignee"): ["Whose name is on the Linear issue that PR #{n} is connected to?",
                               "Pull request #{n} is attached to a Linear ticket. Who owns that ticket?"],
    ("pr_issue", "due_date"): ["What deadline does the Linear issue connected to PR #{n} have?",
                               "Pull request #{n} is attached to a Linear ticket. When does that ticket have to be finished?"],
    ("pr_issue", "status"): ["Is the Linear ticket connected to PR #{n} done yet? Tell me its status.",
                             "What status does the Linear issue attached to pull request #{n} show?"],
    ("issue_pr_author", "author"): ["Who wrote the pull request connected to {k}?",
                                    "{k} has a pull request attached to it. Whose PR is it?"],
    ("ticket_link", "status"): ["{k} is connected to another ticket. What status does that other ticket show?",
                                "What is the state of the other ticket that {k} is connected to?"],
    ("ticket_link", "assignee"): ["{k} is connected to another ticket. Whose name is on that one?",
                                  "Who owns the other ticket that {k} is connected to?"],
    ("person_count", ""): ["How many Linear issues does {p} currently own?",
                           "What's the total number of Linear tickets on {p}'s list?"],
    ("person_first", ""): ["{p} has several Linear issues. Which one has the nearest deadline? Answer with the key.",
                           "Which Linear ticket assigned to {p} comes due before all the others? Key only."],
    ("compare_two", ""): ["{a} and {b}: whose due date is earlier?",
                          "Which deadline is sooner, the one for {a} or the one for {b}?"],
    ("action_owner_issues", ""): ['Someone in "{m}" agreed to "{t}". Which Linear issues does that person have? Give the keys.',
                                  'Find who owns the action item "{t}" from the meeting "{m}", then list the keys of the Linear tickets '
                                  'assigned to them.'],
}
# The new-words test (docs/FACTBANK_WORDS_PREREGISTRATION.md): a fourth pair of wordings per kind, written before any of the
# word learning was built, in the way a manager might ask in chat. They use words no earlier question used.
NEW_WORDS = {
    ("pr_issue", "assignee"): ["Who is responsible for the Linear ticket behind PR #{n}?",
                               "PR #{n} ties back to a Linear issue. Who is handling that issue?"],
    ("pr_issue", "due_date"): ["What's the target date on the Linear ticket behind PR #{n}?",
                               "PR #{n} ties back to a Linear issue. When is that issue expected to land?"],
    ("pr_issue", "status"): ["How far along is the Linear ticket behind PR #{n}?",
                             "PR #{n} ties back to a Linear issue. Which stage is that issue at?"],
    ("issue_pr_author", "author"): ["Which engineer submitted the PR for {k}?",
                                    "{k} was worked on in a pull request. Who created that PR?"],
    ("ticket_link", "status"): ["{k} references another ticket. How far along is that one?",
                                "Which stage is the ticket referenced from {k} at?"],
    ("ticket_link", "assignee"): ["{k} references another ticket. Who is responsible for it?",
                                  "Who's handling the ticket referenced from {k}?"],
    ("person_count", ""): ["How big is {p}'s Linear queue, in issues?",
                           "Tally the Linear tickets {p} is responsible for."],
    ("person_first", ""): ["Which of {p}'s Linear tickets is most urgent by date? Key only.",
                           "Out of everything in {p}'s Linear queue, what lands soonest? Give the key."],
    ("compare_two", ""): ["{a} vs {b}: which one has to ship first?",
                          "Which lands earlier on the calendar, {a} or {b}?"],
    ("action_owner_issues", ""): ['The follow-up "{t}" from "{m}": whoever is responsible for it, which Linear tickets do they hold? Keys.',
                                  'After "{m}", someone was tasked with "{t}". List that person\'s Linear issue keys.'],
}
WORDINGS = {"retest": RETEST, "words": NEW_WORDS}
FRESH_SEED = 13
POOL_DOCS = 20_000
LINKED_SOURCES = ("linear", "github", "jira", "fireflies")


def _person(v: Any) -> str | None:
    from cie.ingest.sources import person_name

    return person_name(v) if v else None


def _keys(v: Any) -> list[str]:
    return KEY.findall(json.dumps(v)) if v else []


def units(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Groups of documents that, together, answer at least one multi-document question."""
    lin = {str(d["raw"]["key"]).upper(): d for d in docs if d["source"] == "linear" and d["raw"].get("key")}
    tick = {**lin, **{str(d["raw"]["key"]).upper(): d for d in docs if d["source"] == "jira" and d["raw"].get("key")}}
    by_person: dict[str, list[dict]] = defaultdict(list)
    for d in lin.values():
        p = _person(d["raw"].get("assignee"))
        if p:
            by_person[p].append(d)
    out: list[dict[str, Any]] = []
    for p, ds in by_person.items():
        if 2 <= len(ds) <= 4:
            out.append({"kind": "person", "person": p, "docs": sorted(d["dsid"] for d in ds)})
    for d in docs:
        if d["source"] == "github" and str(d["raw"].get("pr_number") or "").isdigit() and len(str(d["raw"]["pr_number"])) >= 3:
            ks = [k for k in dict.fromkeys(_keys(d["raw"].get("linked_linear"))) if k in lin]
            if len(ks) == 1:
                out.append({"kind": "pr", "pr": d["dsid"], "issue": lin[ks[0]]["dsid"], "docs": sorted({d["dsid"], lin[ks[0]]["dsid"]})})
        if d["source"] in ("jira", "linear") and d["raw"].get("key"):
            fields = ("linked_issues",) if d["source"] == "jira" else ("dependencies", "parent_issue", "sub_issues", "linked_issues")
            ks = [k for f in fields for k in _keys(d["raw"].get(f)) if k in tick and k != str(d["raw"]["key"]).upper()]
            ks = list(dict.fromkeys(ks))
            if len(ks) == 1 and tick[ks[0]]["source"] == d["source"]:
                out.append({"kind": "ticket", "from": d["dsid"], "to": tick[ks[0]]["dsid"], "docs": sorted({d["dsid"], tick[ks[0]]["dsid"]})})
        if d["source"] == "fireflies":
            for o, t, _ in action_items(d["raw"]):
                if 2 <= len(by_person.get(o, [])) <= 4:
                    out.append({"kind": "action", "meeting": d["dsid"], "owner": o, "task": t,
                                "docs": sorted({d["dsid"], *(x["dsid"] for x in by_person[o])})})
    return out


def split(docs: list[dict[str, Any]], seed: int = SEED) -> tuple[set[str], set[str]]:
    """Two disjoint sets of at most 50 documents, built from whole units, alternating between them."""
    us = units(docs)
    rng = random.Random(seed)
    rng.shuffle(us)
    sets: list[set[str]] = [set(), set()]
    kinds_in: list[dict[str, int]] = [defaultdict(int), defaultdict(int)]
    for u in sorted(us, key=lambda u: {"action": 0, "pr": 1, "ticket": 2, "person": 3}[u["kind"]]):
        need = set(u["docs"])
        order = sorted((0, 1), key=lambda i: (kinds_in[i][u["kind"]], len(sets[i])))
        for i in order:
            other = sets[1 - i]
            if need & other or len(sets[i] | need) > N_DOCS or kinds_in[i][u["kind"]] >= 8:
                continue
            sets[i] |= need
            kinds_in[i][u["kind"]] += 1
            break
    return sets[0], sets[1]


def questions(docs: list[dict[str, Any]], dsids: set[str], held_out: bool, seed: int, retest: bool = False,
              wordings: dict | None = None) -> list[dict[str, Any]]:
    """The questions answerable within ``dsids``, with expected answers computed there, worded for training, held-out, the retest
    (``retest``) or another set of wordings (``wordings``)."""
    if retest:
        wordings = RETEST
    rng = random.Random(seed)
    inside = [d for d in docs if d["dsid"] in dsids]
    by_id = {d["dsid"]: d for d in inside}
    lin = {str(d["raw"]["key"]).upper(): d for d in inside if d["source"] == "linear" and d["raw"].get("key")}
    by_person: dict[str, list[dict]] = defaultdict(list)
    for d in lin.values():
        p = _person(d["raw"].get("assignee"))
        if p:
            by_person[p].append(d)
    out: list[dict[str, Any]] = []

    def add(kind: str, field: str, fmt: dict[str, str], expected: dict[str, Any], gold: list[str], pieces: list[str]) -> None:
        options = wordings[(kind, field)] if wordings else T[(kind, field)][1 if held_out else 0]
        out.append({"id": f"{kind}{'-' + field if field else ''}-{len(out) + 1:03d}", "group": GROUP[kind], "kind": kind, "field": field,
                    "question": rng.choice(options).format(**fmt), "expected": expected, "gold_docs": sorted(set(gold)), "pieces": pieces})

    for u in units(inside):
        if not set(u["docs"]) <= dsids:
            continue
        if u["kind"] == "pr":
            pr, iss = by_id[u["pr"]], by_id[u["issue"]]
            n, key = str(pr["raw"]["pr_number"]), str(iss["raw"]["key"]).upper()
            field = rng.choice([f for f in ("assignee", "due_date", "status") if iss["raw"].get(f)] or ["status"])
            val = _person(iss["raw"].get("assignee")) if field == "assignee" else (_iso(iss["raw"].get("due_date")) if field == "due_date"
                                                                                 else str(iss["raw"].get("status") or ""))
            if val:
                add("pr_issue", field, {"n": n}, {"date": val} if field == "due_date" else {"value": val}, u["docs"], [key, val])
            author = _person(pr["raw"].get("author"))
            refs = [d for d in inside if d["source"] == "github" and key in _keys(d["raw"].get("linked_linear"))]
            if author and len(refs) == 1:
                add("issue_pr_author", "author", {"k": key}, {"value": author}, u["docs"], [n, author])
        elif u["kind"] == "ticket":
            a, b = by_id[u["from"]], by_id[u["to"]]
            field = rng.choice([f for f in ("status", "assignee") if b["raw"].get(f)] or ["status"])
            val = str(b["raw"].get("status") or "") if field == "status" else _person(b["raw"].get("assignee"))
            if val:
                add("ticket_link", field, {"k": str(a["raw"]["key"]).upper()}, {"value": val}, u["docs"],
                    [str(b["raw"]["key"]).upper(), val])
        elif u["kind"] == "person":
            ds = by_person.get(u["person"], [])
            keys = sorted(str(d["raw"]["key"]).upper() for d in ds)
            add("person_count", "", {"p": u["person"]}, {"value": str(len(ds))}, [d["dsid"] for d in ds], keys)
            dated = sorted((_iso(d["raw"].get("due_date")), str(d["raw"]["key"]).upper()) for d in ds if _iso(d["raw"].get("due_date")))
            if len(dated) >= 2 and dated[0][0] != dated[1][0]:
                add("person_first", "", {"p": u["person"]}, {"ids": [dated[0][1]], "id_kind": "key"}, [d["dsid"] for d in ds],
                    [x for pair in dated for x in pair])
        elif u["kind"] == "action":
            ds = by_person.get(u["owner"], [])
            m = by_id[u["meeting"]]
            add("action_owner_issues", "", {"t": u["task"], "m": m["title"]}, {"ids": sorted(str(d["raw"]["key"]).upper() for d in ds),
                                                                               "id_kind": "key"},
                [m["dsid"], *(d["dsid"] for d in ds)], [u["owner"], *sorted(str(d["raw"]["key"]).upper() for d in ds)])
    dated = [(_iso(d["raw"].get("due_date")), str(d["raw"]["key"]).upper(), d["dsid"]) for d in lin.values() if _iso(d["raw"].get("due_date"))]
    rng.shuffle(dated)
    pairs = 0
    for (d1, k1, s1), (d2, k2, s2) in zip(dated[::2], dated[1::2], strict=False):
        if d1 != d2 and pairs < 8:
            first = k1 if d1 < d2 else k2
            add("compare_two", "", {"a": k1, "b": k2}, {"ids": [first], "id_kind": "key"}, [s1, s2], [d1, d2])
            pairs += 1
    # at most 50, kinds interleaved so that every kind keeps its share
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for q in out:
        by_kind[q["kind"]].append(q)
    chosen: list[dict[str, Any]] = []
    while len(chosen) < MAX_Q and any(by_kind.values()):
        for k in sorted(by_kind):
            if by_kind[k] and len(chosen) < MAX_Q:
                chosen.append(by_kind[k].pop(0))
    return chosen


def fresh(docs: list[dict[str, Any]], exclude: set[str], seed: int = FRESH_SEED) -> set[str]:
    """At most 50 documents sharing none with ``exclude``, built from whole units, at most 8 units of each kind."""
    us = [u for u in units(docs) if not set(u["docs"]) & exclude]
    random.Random(seed).shuffle(us)
    out: set[str] = set()
    kinds_in: dict[str, int] = defaultdict(int)
    for u in sorted(us, key=lambda u: {"action": 0, "pr": 1, "ticket": 2, "person": 3}[u["kind"]]):
        need = set(u["docs"])
        if len(out | need) > N_DOCS or kinds_in[u["kind"]] >= 8:
            continue
        out |= need
        kinds_in[u["kind"]] += 1
    return out


def pool(index: dict[str, str], exclude: set[str], n: int = POOL_DOCS, seed: int = FRESH_SEED) -> list[str]:
    """A new sample of the whole benchmark, stratified by source, none of it in ``exclude``; only the sources whose documents link."""
    by_src: dict[str, list[str]] = defaultdict(list)
    for dsid, rel in sorted(index.items()):
        if dsid not in exclude:
            by_src[rel.split("/")[0]].append(dsid)
    total = sum(len(v) for v in by_src.values())
    rng = random.Random(seed)
    picked: list[str] = []
    for src in sorted(by_src):
        k = min(len(by_src[src]), round(n * len(by_src[src]) / total))
        if src in LINKED_SOURCES:
            picked += rng.sample(by_src[src], k)
    return sorted(picked)


def build_fresh(index_path: Path, root: str, exclude_dirs: list[Path], out: Path, seed: int = FRESH_SEED, wordings: str = "retest") -> dict[str, Any]:
    """A new set: new documents drawn from the whole benchmark (none from ``exclude_dirs``), new wordings. Seed 13 with the retest
    wordings made the retest's set; seed 17 with the new-words wordings made the new-words test's set."""
    from cie.eval.memory_test import haystack_docs

    index = json.loads(index_path.read_text())["index"]
    exclude = set().union(*(set(json.loads((d / "haystack.json").read_text())["dsids"]) for d in exclude_dirs))
    docs = haystack_docs(Path(root) / "generated_data" / "sources", index, pool(index, exclude, seed=seed))
    ids = fresh(docs, exclude, seed)
    qs = questions(docs, ids, True, seed + 1, wordings=WORDINGS[wordings])
    out.mkdir(parents=True, exist_ok=True)
    (out / "haystack.json").write_text(json.dumps({"root": root, "n_docs": N_DOCS, "seed": seed, "base_questions": 0,
                                                   "documents": len(ids), "dsids": sorted(ids)}))
    if not (out / "index.json").exists():
        (out / "index.json").symlink_to(index_path.resolve())
    _write_jsonl(out / "questions.jsonl", qs)
    kinds: dict[str, int] = defaultdict(int)
    for q in qs:
        kinds[q["kind"]] += 1
    return {"documents": len(ids), "questions": len(qs), "kinds": dict(kinds), "pool": len(docs), "excluded_documents": len(exclude),
            "shared_with_excluded": len(ids & exclude)}


def build(docs_path: Path, index: Path, root: str, train_dir: Path, test_dir: Path) -> dict[str, Any]:
    docs = json.loads(docs_path.read_text())
    a, b = split(docs)
    rep = {}
    for name, d, ids, held in (("training", train_dir, a, False), ("held_out", test_dir, b, True)):
        qs = questions(docs, ids, held, SEED + (1 if held else 0))
        d.mkdir(parents=True, exist_ok=True)
        (d / "haystack.json").write_text(json.dumps({"root": root, "n_docs": N_DOCS, "seed": SEED, "base_questions": 0, "documents": len(ids),
                                                     "dsids": sorted(ids)}))
        if not (d / "index.json").exists():
            (d / "index.json").symlink_to(index.resolve())
        _write_jsonl(d / "questions.jsonl", qs)
        kinds: dict[str, int] = defaultdict(int)
        for q in qs:
            kinds[q["kind"]] += 1
        rep[name] = {"documents": len(ids), "questions": len(qs), "kinds": dict(kinds)}
    rep["shared_documents"] = len(a & b)
    return rep


# ---------------------------------------------------------------------------------------------- training and asking
def train(work: Path, single: Path, out: Path, rules: str = "v4", lexicon: Path | None = None) -> dict[str, Any]:
    """``rules="v3"`` reproduces the plan lessons of the first test; ``"v4"`` is the planner revised after it. With a lexicon
    (``cie.factbank.lexicon``), v4 plus learned word meanings: v5."""
    from cie.eval.factbank_test import build as build_bank
    from cie.factbank.learn import Lessons
    from cie.factbank.plans import FEATURES, FEATURES_V4, FEATURES_V5, learn_plans
    from cie.factbank.trained import TrainedBank

    if not (work / "factbank_v2.sqlite").exists():
        build_bank(work, "factbank_v2", text_facts=True)
    lex = None
    if lexicon is not None:
        from cie.factbank.lexicon import Lexicon

        lex = Lexicon.load(lexicon)
    les = learn_plans(TrainedBank(work / "factbank_v2.sqlite", Lessons.load(single)), _jsonl(work / "questions.jsonl"),
                      features=(FEATURES_V5 if lex is not None else FEATURES_V4) if rules == "v4" else FEATURES, rules=rules,
                      lexicon=lex, lexicon_path=str(lexicon.resolve()) if lexicon is not None else "")
    les.save(out)
    return {"plan_lessons": str(out), "describe": les.describe(), "trained_on": les.trained_on}


def ask_plans(work: Path, single: Path, plan_lessons: Path, budget: int = 24_000, name: str = "factbank_v3") -> dict[str, Any]:
    """v3 (or v4): the best plan's answer; its evidence starts with every entity each hop reached and their main fields."""
    import time

    from cie.factbank import plans
    from cie.factbank.learn import Lessons
    from cie.factbank.trained import TrainedBank

    tb = TrainedBank(work / "factbank_v2.sqlite", Lessons.load(single))
    pl = plans.PlanLessons.load(plan_lessons)
    planner = pl.planner(tb)
    rows = []
    for q in _jsonl(work / "questions.jsonl"):
        t = time.perf_counter()
        ans, best, journal, top = plans.answer(tb, pl, q["question"], planner)
        lines = []
        if best is not None:
            lines.append("Plan: " + best.describe(tb.names))
            shown = list(best.starts) + [e for j in journal if j.get("op") == "hop" for e in j["reached"]]
            for e in list(dict.fromkeys(shown))[:40]:
                main = {f["parameter"]: f["value"] for f in planner.facts(e)
                        if f["parameter"] in ("key", "pr_number", "status", "assignee", "author", "due_date", "owner")}
                lines.append(f"- {tb.label_of(e)}: {tb.names.get(e, e)[:120]}" + "".join(f"; {k}: {v}" for k, v in main.items()))
            lines += [f"(other plan: {p.describe(tb.names)} → {a})" for _, p, a in top[1:4]]
        head = "\n".join(lines)
        rest = tb.ask(q["question"], budget=max(0, budget - len(head) - 2)).evidence
        rows.append({"id": q["id"], "answer": ans, "reason": best.describe(tb.names) if best else "", "evidence": (head + "\n\n" + rest)[:budget],
                     "ms": round((time.perf_counter() - t) * 1000, 2), "journal": journal})
    _write_jsonl(work / f"{name}.jsonl", rows)
    return {"questions": len(rows), "written": f"{name}.jsonl"}


def pieces_in(q: dict[str, Any], text: str) -> float:
    from cie.eval.memory_test import _norm, dates_in

    ds = dates_in(text)
    t = _norm(text)
    hits = 0
    for p in q.get("pieces") or []:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
            hits += p in ds
        elif KEY.fullmatch(p):
            hits += p in text
        else:
            hits += bool(re.search(r"(?<!\w)" + re.escape(_norm(p)) + r"(?!\w)", t))
    return hits / max(1, len(q.get("pieces") or []))


def measure(work: Path) -> dict[str, Any]:
    from cie.eval.factbank_test import direct

    qs = _jsonl(work / "questions.jsonl")
    ev = {r["id"]: r for r in _jsonl(work / "evidence.jsonl")} if (work / "evidence.jsonl").exists() else {}
    fbs = {label: {r["id"]: r for r in _jsonl(work / f"{name}.jsonl")}
           for label, name in (("v1", "factbank"), ("v2", "factbank_v2"), ("v3", "factbank_v3"), ("v4", "factbank_v4"), ("v5", "factbank_v5"))
           if (work / f"{name}.jsonl").exists()}
    rows = []
    for q in qs:
        r: dict[str, Any] = {"id": q["id"], "group": q["group"], "kind": q["kind"], "question": q["question"], "expected": q["expected"],
                             "direct": {}, "answers": {}, "pieces": {}}
        for label, d in fbs.items():
            if q["id"] in d:
                r["direct"][label] = direct(q, d[q["id"]]["answer"])
                r["answers"][label] = d[q["id"]]["answer"]
        texts = {a: ev.get(q["id"], {}).get(a) for a in ("plain-words", "plain", "bank")}
        texts.update({label: d.get(q["id"], {}).get("evidence") for label, d in fbs.items()})
        for a, t in texts.items():
            if t is not None:
                r["pieces"][a] = {b: pieces_in(q, t[:int(b)]) for b in ("2000", "24000")}
        rows.append(r)
    groups = ("link", "combine", "compare")

    def gm(fn) -> dict[str, float | None]:
        out = {}
        for g in groups:
            vals = [v for v in (fn(r) for r in rows if r["group"] == g) if v is not None]
            out[g] = round(sum(vals) / len(vals), 3) if vals else None
        have = [v for v in out.values() if v is not None]
        out["mean"] = round(sum(have) / len(have), 3) if have else None
        return out

    arms = sorted({a for r in rows for a in r["pieces"]})
    by_kind: dict[str, dict[str, float]] = {}
    for k in sorted({r["kind"] for r in rows}):
        rk = [r for r in rows if r["kind"] == k]
        by_kind[k] = {label: round(sum(r["direct"].get(label, 0) for r in rk) / len(rk), 3) for label in fbs} | {"n": len(rk)}
    return {"questions": len(rows), "by_group": {g: sum(1 for r in rows if r["group"] == g) for g in groups},
            "direct": {label: gm(lambda r, label=label: r["direct"].get(label)) for label in fbs},
            "pieces": {a: {b: gm(lambda r, a=a, b=b: (r["pieces"].get(a) or {}).get(b)) for b in ("2000", "24000")} for a in arms},
            "by_kind": by_kind, "rows": rows}


def at_least(diff: float | None, threshold: float) -> bool:
    """A rule on a difference: met when the difference is known and reaches the threshold. A difference of exactly 0 is a
    difference like any other (the first version wrote ``(diff or -1)``, which read 0 as missing)."""
    return diff is not None and diff >= threshold


def compare(test: Path, changed: Path, training: Path) -> dict[str, Any]:
    m = {"training": measure(training), "held_out": measure(test), "changed": measure(changed)}
    d = lambda a, b: round(a - b, 3) if a is not None and b is not None else None  # noqa: E731
    h = m["held_out"]
    rules = {
        "1 learned plans answer multi-document questions (v3 - v1 >= +0.20, held-out)":
            at_least(d(h["direct"]["v3"]["mean"], h["direct"]["v1"]["mean"]), 0.20),
        "2 principles, not memorisation (v3 held-out >= v3 training - 0.15)":
            at_least(d(h["direct"]["v3"]["mean"], m["training"]["direct"]["v3"]["mean"]), -0.15),
        "3 holds when the information changes (v3 changed >= v3 held-out - 0.05)":
            at_least(d(m["changed"]["direct"]["v3"]["mean"], h["direct"]["v3"]["mean"]), -0.05),
        "4 brings the fragments together (v3 - memory bank >= +0.10, all pieces within 24,000 chars, held-out)":
            at_least(d(h["pieces"]["v3"]["24000"]["mean"], h["pieces"]["bank"]["24000"]["mean"]), 0.10),
    }
    rep = {**m, "rules": rules}
    (test / "multi_report.json").write_text(json.dumps(rep, indent=1, default=str))
    (test / "multi_report.md").write_text(to_markdown(rep))
    return rep


def retest(fresh_dir: Path, changed: Path, training: Path) -> dict[str, Any]:
    """The retest's rules (docs/FACTBANK_MULTI_RETEST_PREREGISTRATION.md): v4 on new documents and new wordings."""
    m = {"training": measure(training), "held_out": measure(fresh_dir), "changed": measure(changed)}
    d = lambda a, b: round(a - b, 3) if a is not None and b is not None else None  # noqa: E731
    h = m["held_out"]
    rules = {
        "1 learned plans answer multi-document questions (v4 - v1 >= +0.20, new set)":
            at_least(d(h["direct"]["v4"]["mean"], h["direct"]["v1"]["mean"]), 0.20),
        "2 the revision helps on new data (v4 - v3 >= +0.20, new set)":
            at_least(d(h["direct"]["v4"]["mean"], h["direct"]["v3"]["mean"]), 0.20),
        "3 principles, not memorisation (v4 new set >= v4 training - 0.15)":
            at_least(d(h["direct"]["v4"]["mean"], m["training"]["direct"]["v4"]["mean"]), -0.15),
        "4 holds when the information changes (v4 changed >= v4 new set - 0.05)":
            at_least(d(m["changed"]["direct"]["v4"]["mean"], h["direct"]["v4"]["mean"]), -0.05),
    }
    rep = {**m, "rules": rules}
    (fresh_dir / "retest_report.json").write_text(json.dumps(rep, indent=1, default=str))
    (fresh_dir / "retest_report.md").write_text(to_markdown(rep, "Questions that need several documents: the retest on new documents"))
    return rep


def words_test(words_dir: Path, changed: Path, training: Path, retest_dir: Path) -> dict[str, Any]:
    """The new-words test's rules (docs/FACTBANK_WORDS_PREREGISTRATION.md): v5 against v4 on new wordings."""
    m = {"training": measure(training), "held_out": measure(words_dir), "changed": measure(changed), "retest": measure(retest_dir)}
    d = lambda a, b: round(a - b, 3) if a is not None and b is not None else None  # noqa: E731
    h, t, r = m["held_out"]["direct"], m["training"]["direct"], m["retest"]["direct"]
    rules = {
        "1 new words are understood (v5 - v4 >= +0.10, new-words set)": at_least(d(h["v5"]["mean"], h["v4"]["mean"]), 0.10),
        "2 principles, not memorisation (v5 new-words set >= v5 training - 0.15)": at_least(d(h["v5"]["mean"], t["v5"]["mean"]), -0.15),
        "3 holds when the information changes (v5 changed >= v5 new-words set - 0.05)":
            at_least(d(m["changed"]["direct"]["v5"]["mean"], h["v5"]["mean"]), -0.05),
        "4 no harm where v4 already worked (v5 >= v4 - 0.03 on the retest set and on the training questions)":
            at_least(d(r["v5"]["mean"], r["v4"]["mean"]), -0.03) and at_least(d(t["v5"]["mean"], t["v4"]["mean"]), -0.03),
    }
    rep = {**m, "rules": rules}
    (words_dir / "words_report.json").write_text(json.dumps(rep, indent=1, default=str))
    (words_dir / "words_report.md").write_text(to_markdown(rep, "Understanding new words: the new-words set", ("training", "held_out", "changed", "retest")))
    return rep


def to_markdown(rep: dict[str, Any], title: str = "Questions that need several documents",
                parts: tuple[str, ...] = ("training", "held_out", "changed")) -> str:
    g = ("link", "combine", "compare", "mean")
    lines = [f"### {title}", ""]
    for name in parts:
        m = rep[name]
        lines += [f"**{name.replace('_', '-')}** ({m['questions']} questions: {', '.join(f'{k} {v}' for k, v in m['by_group'].items())})", "",
                  "| | " + " | ".join(g) + " |", "|---|" + "---|" * len(g)]
        for label, r in m["direct"].items():
            lines.append(f"| own answers, {label} | " + " | ".join("–" if r.get(x) is None else f"{r[x]:.3f}" for x in g) + " |")
        for a, rr in m["pieces"].items():
            for b, r in rr.items():
                lines.append(f"| all pieces within {int(b):,} chars, {a} | " + " | ".join("–" if r.get(x) is None else f"{r[x]:.3f}" for x in g) + " |")
        lines += ["", "By kind (own answers): " + "; ".join(f"{k} ({v['n']}): " + ", ".join(f"{a} {s}" for a, s in v.items() if a != "n")
                                                         for k, v in m["by_kind"].items()), ""]
    lines += ["Rules:"] + [f"- {k}: **{'met' if v else 'not met'}**" for k, v in rep["rules"].items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.factbank_multi")
    ap.add_argument("cmd", choices=["build", "train", "ask", "compare", "fresh", "retest", "words"])
    ap.add_argument("--docs", help="the haystack's documents as JSON: dsid, source, title, raw")
    ap.add_argument("--index")
    ap.add_argument("--root")
    ap.add_argument("--train")
    ap.add_argument("--test")
    ap.add_argument("--work")
    ap.add_argument("--changed")
    ap.add_argument("--single", help="the single-document lessons (lessons.json)")
    ap.add_argument("--plans", help="the plan lessons (plan_lessons.json)")
    ap.add_argument("--rules", default="v4", choices=["v3", "v4"], help="train: the planner as first tested (v3) or as revised (v4)")
    ap.add_argument("--seed", type=int, default=FRESH_SEED, help="fresh: 13 made the retest's set, 17 the new-words test's set")
    ap.add_argument("--wordings", default="retest", choices=sorted(WORDINGS), help="fresh: which wordings")
    ap.add_argument("--lexicon", help="train: learned word meanings (cie.factbank.lexicon); makes v5")
    ap.add_argument("--name", default="factbank_v3", help="ask: the answers' file name (factbank_v3 or factbank_v4)")
    ap.add_argument("--exclude", nargs="*", default=[], help="fresh: work folders whose documents the new set must not use")
    ap.add_argument("--out")
    ap.add_argument("--retest", help="words: the retest's work folder")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        out = build(Path(a.docs), Path(a.index), a.root, Path(a.train), Path(a.test))
    elif a.cmd == "fresh":
        out = build_fresh(Path(a.index), a.root, [Path(x) for x in a.exclude], Path(a.out), a.seed, a.wordings)
    elif a.cmd == "train":
        out = train(Path(a.work), Path(a.single), Path(a.plans), a.rules, Path(a.lexicon) if a.lexicon else None)
    elif a.cmd == "ask":
        out = ask_plans(Path(a.work), Path(a.single), Path(a.plans), name=a.name)
    elif a.cmd == "words":
        out = words_test(Path(a.work), Path(a.changed), Path(a.train), Path(a.retest))
        print(to_markdown(out, "Understanding new words: the new-words set", ("training", "held_out", "changed", "retest")))
        return out
    elif a.cmd == "retest":
        out = retest(Path(a.work), Path(a.changed), Path(a.train))
        print(to_markdown(out, "Questions that need several documents: the retest on new documents"))
        return out
    else:
        out = compare(Path(a.work), Path(a.changed), Path(a.train))
        print(to_markdown(out))
        return out
    print(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    main()
