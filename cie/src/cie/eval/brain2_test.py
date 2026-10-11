"""The company brain's test, round 2 (v16): v15's families and the new kinds in one question set, every arm's answers with the
v16 brain beside them, and one score over eight families.

- **questions:** one W/questions.jsonl in three parts, each drawn by its own module so that no part changes another:
  (a) v15's four families (single, multi, not_found, prose) drawn exactly as ``brain_test.draw`` draws them, in a v15 mix
  (``MIX15``, v15's test mix, by default), with the writers' prose and descriptive questions; (b) the new kinds,
  ``brain2_questions.draw_questions`` in ``MIX16`` (counts, history, email_chat, the two-document multi kinds, field_absent and
  the embedded single kinds; a key of ``MIX16`` may name no kind of v15's, which belong in the v15 mix); (c) the held-out
  writers' questions that ``brain2_draw collect`` kept (family unanswerable, kind heldout: a natural question whose answer is in
  a document outside the haystack). Ids are unique across the parts. Set aside, and written with their reasons to
  W/set_aside_questions.jsonl: what ``brain_test.draw`` sets aside, and a held-out question that expects an answer, has gold
  documents, has no held-out document or one inside the haystack, or repeats another; the new kinds' generators only count
  what they set aside (W/questions_report.json). With ``--small``, the control folder holds only the questions' gold documents,
  and the questions whose expected answer is not the same there are recorded: v15's by ``brain_test.not_reproduced``, the new
  kinds by drawing them again within the set (``not_reproduced2``).
- **ask:** one arm's answers. v1, v2, v13 and v15 are ``brain_test.ask`` unchanged; v16 is ``cie.factbank.brain.ask_brain``
  with ``v16=True`` (default answers file factbank_v16.jsonl); quotes is ``brain_test.ask_quotes`` unchanged, with the
  documents of its quoted passages recorded on the way into each row ("quote_docs", one per citation marker, in turn), so
  that a strict free-text score can be computed. W/arms.json records, for every arm, the sha256 of its lessons files and the
  PYTHONHASHSEED it ran under (the v15 post-run review asked for both).
- **score:** every arm's answers scored by ``brain2_questions.score`` (``brain_questions.score`` for v15's kinds; a held-out
  question scores 1 when the answer says not found), over ``FAMILIES2``: per family, group and kind, the mean over the eight
  families and over v15's four, route accuracy (``ROUTE2``), false "not found" on answerable questions, the strict free-text
  score (``strict_prose``), the paired difference of v16 and the best other arm in each family with its bootstrap interval,
  the hash-seed check (v16 against v16_seed1), the small set's differences (``brain_test.against_small``) and time per
  question. ``preregistered2`` holds the rules; ``--preregistered`` applies them (``brain_test.rules``).

The banks come from ``brain_test build``. A work folder may link a bank built elsewhere from the same documents (W/banks.json
records which documents each bank holds).

    python -m cie.eval.brain2_test questions --work W --seed 16 [--mix15 JSON] [--mix16 JSON] [--prose F] [--descriptive F] \\
        [--heldout F] [--small WS]
    python -m cie.eval.brain2_test ask --work W --arm v16 --single LESSONS --plans PLAN_LESSONS --router ROUTER [--name N]
    python -m cie.eval.brain2_test score --work W [--small WS] [--out DIR] [--preregistered]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cie.eval import brain2_questions as Q2
from cie.eval import brain_questions as B
from cie.eval import brain_test as H
from cie.eval import factbank_5k
from cie.eval.brain_test import Rule, _count, _mean, _read
from cie.eval.factbank_5k_b import _ms
from cie.eval.memory_test import _jsonl, _norm, _write_jsonl

FAMILIES2 = ("single", "multi", "prose", "not_found", "counts", "history", "email_chat", "unanswerable")
ANSWERABLE = tuple(f for f in FAMILIES2 if f not in ("not_found", "unanswerable"))
NEW_FAMILIES = ("counts", "history", "email_chat")
ARMS2 = (*H.ARMS, "v16")
FILES2 = {**H.FILES, "v16": "factbank_v16"}
OWN = ("v16", "v16_seed1")  # the v16 brain's own answers, with every label asked as arm v16 (``own_labels``); the rest are other arms
HELDOUT = "heldout"  # the kind and group of the held-out writers' questions
# the right route for each family: single, multi, counts, history and email_chat a fact route, prose the prose route, not_found
# "not found"; an unanswerable question may be declined by any route, so it is not counted
ROUTE2 = {"single": "fact", "multi": "fact", "counts": "fact", "history": "fact", "email_chat": "fact", "prose": "prose",
          "not_found": "not_found"}
NOT_FOUND_ROUTES = ("not_found", "absent")  # route names (prefixes) that decline; "prose" quotes; every other is a fact route
# v15's test mix (docs/FACTBANK_BRAIN_PREREGISTRATION.md); with no "descriptive" key, every descriptive question that passes
MIX15 = {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50}
# the new kinds, an even spread over the new families: about 40 questions each of counts, history and email and chat (each
# shared out over its kinds in turn), 20 of the two-document kinds (named one by one: 'link' and 'combine' are v15's groups
# too), 20 empty-field questions with no answer and 20 embedded single-document questions
MIX16 = {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3,
         "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}
QUOTED_FROM = re.compile(r"quoted from \d+ passage\(s\) of (?:\d+ document\(s\): )?([^;]+)")  # the brain's prose routes' reason
PROVENANCE = ("single_sha256", "plans_sha256", "router_sha256", "pythonhashseed")


# ------------------------------------------------------------------ questions
def part(q: dict[str, Any]) -> str:
    """Which part of the question set a question belongs to: 'heldout', 'v16' (a kind of ``brain2_questions``) or 'v15'."""
    return HELDOUT if q.get("kind") == HELDOUT else "v16" if q.get("kind") in Q2.CATALOGUE else "v15"


def check_mix16(mix: dict[str, int]) -> None:
    """Raise ValueError when a key of the new kinds' mix names a kind of v15's too ('multi', 'link', 'fields'): those are
    drawn in the v15 mix, as ``brain_test.draw`` draws them."""
    for key in mix:
        old = sorted(Q2.resolve(key) - set(Q2.CATALOGUE))
        if old:
            raise ValueError(f"the mix16 key {key!r} names v15's kinds too ({', '.join(old[:4])}): draw those in mix15")


def load_heldout(path: str | Path) -> list[dict[str, Any]]:
    """The held-out writers' questions ``brain2_draw collect`` kept, from a JSONL file: each {id, question, expected
    {"not_found": true}, gold_docs [], heldout_doc, ...}, in family 'unanswerable', kind and group 'heldout' unless it says
    otherwise (``why_heldout_aside`` sets such a row aside). An id that does not start with 'heldout' gets 'heldout-' before
    it, so that it cannot be another part's."""
    out = []
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        if not str(r.get("question") or "").strip():
            raise ValueError(f"{path}:{i}: a held-out question needs a question")
        rid = str(r.get("id") or f"{len(out) + 1:03d}")
        out.append({"family": "unanswerable", "group": HELDOUT, "kind": HELDOUT, "pieces": list(r.get("answer_facts") or []),
                    "origin": HELDOUT, **r, "id": rid if rid.startswith(HELDOUT) else f"{HELDOUT}-{rid}",
                    "gold_docs": list(r.get("gold_docs") or [])})
    return out


def why_heldout_aside(q: dict[str, Any], dsids: set[str], asked: set[str]) -> str | None:
    """Why a held-out question is set aside, or None: it is not of family unanswerable and kind heldout, it expects an
    answer, it has gold documents, it names no held-out document or one the haystack holds, or another held-out question
    asks the same (``asked``: the questions kept so far, normalised)."""
    if q.get("family") != "unanswerable" or q.get("kind") != HELDOUT:
        return "not an unanswerable held-out question"
    if q.get("expected") != {"not_found": True}:
        return "expects an answer"
    if q.get("gold_docs"):
        return "has gold documents"
    if not q.get("heldout_doc"):
        return "no held-out document"
    if q["heldout_doc"] in dsids:
        return "held-out document in the haystack"
    if _norm(q["question"]) in asked:
        return "asked twice"
    return None


def draw2(docs: list[dict[str, Any]], seed: int = Q2.SEED, mix15: dict[str, int] | None = None, mix16: dict[str, int] | None = None,
          prose: list[dict[str, Any]] | None = None, descriptive: list[dict[str, Any]] | None = None,
          heldout: list[dict[str, Any]] | None = None, multi_wordings: dict | None = None
          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """The questions (v15's part, the new kinds, the held-out questions, in that order), those set aside, and a report.

    v15's part is ``brain_test.draw(docs, seed, mix15, prose, descriptive, multi_wordings)``; the new kinds are
    ``brain2_questions.draw_questions(docs, seed, mix16)``, with what their generators make and set aside counted by
    ``brain2_questions.generate``; the held-out questions are those ``why_heldout_aside`` keeps. ValueError when an id is used
    twice or a key of ``mix16`` names v15's kinds."""
    mix15 = dict(MIX15 if mix15 is None else mix15)
    mix16 = dict(MIX16 if mix16 is None else mix16)
    check_mix16(mix16)
    qs15, aside, rep15 = H.draw(docs, seed, mix15, prose, descriptive, multi_wordings)
    qs16 = Q2.draw_questions(docs, seed, mix16)
    wanted = set().union(*(Q2.resolve(k) for k in mix16)) if mix16 else set()
    gen = Q2.generate(docs, seed, kinds=wanted)[1] if wanted else {"by_kind": {}, "aside": {}}
    dsids = {d["dsid"] for d in docs}
    held, asked, why_held = [], set(), Counter()
    for q in heldout or []:
        why = why_heldout_aside(q, dsids, asked)
        if why is None:
            held.append(q)
            asked.add(_norm(q["question"]))
        else:
            why_held[why] += 1
            aside.append({**q, "unclear": why})
    qs = qs15 + qs16 + held
    twice = sorted(i for i, c in Counter(q["id"] for q in qs).items() if c > 1)
    if twice:
        raise ValueError(f"question ids used twice: {twice}")
    given16 = {k: sum(1 for q in qs16 if q["kind"] in Q2.resolve(k)) for k in mix16}
    rep = {"documents": len(docs), "seed": seed, "questions": len(qs), "by_part": _count(qs, part), "by_family": _count(qs, Q2.family),
           "by_group": _count(qs, lambda q: str(q.get("group"))), "by_kind": _count(qs, lambda q: str(q.get("kind"))),
           "mix15": {"asked": rep15["mix"], "given": rep15["mix_given"]}, "mix16": {"asked": mix16, "given": given16},
           "v15": rep15, "v16": {"questions": len(qs16), "available": gen["by_kind"], "set_aside": gen["aside"]},
           "heldout": {"read": len(heldout or []), "kept": len(held), "set_aside": dict(sorted(why_held.items()))},
           "set_aside_written": _count(aside, lambda q: str(q.get("kind"))), "gold_documents": len(factbank_5k.small_set(qs))}
    return qs, aside, rep


def _recount(q: dict[str, Any], inside: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> bool | None:
    """For a count or filter question, whether its filters counted over ``inside`` give its expected answer again (the
    count, or the keys); None for any other question. A document holds a filter's value as ``brain2_questions`` reads it: a
    short value or a full-named person, "open" by its status, a mailbox owner by full name, an account by its squashed name."""
    filters = q.get("filters")
    if not filters or not (q["kind"].startswith(("count1_", "count2_")) or q["kind"] in ("count_gmail", "filter_list")):
        return None
    if q["kind"] == "count_gmail":
        src = "gmail"
    elif q["kind"] == "filter_list":
        src = by_id[q["gold_docs"][0]]["source"] if q.get("gold_docs") and q["gold_docs"][0] in by_id else ""
    else:
        src = q["kind"].split("_", 1)[1]
    spec = Q2.COUNT_FIELDS.get(src, {})

    def holds(d: dict[str, Any], f: str, v: str) -> bool:
        raw = d["raw"].get(f)
        if f == "open":
            return Q2._count_value(d, "open", "open") == "open"
        if f == "mailbox_owner":
            return Q2._full_name(raw) == v
        if f == "related_account":
            return isinstance(raw, str) and B._squash(raw) == B._squash(v)
        got = Q2._count_value(d, f, spec.get(f, "value"))
        return got is not None and B._squash(got) == B._squash(v)

    hits = [d for d in inside if d["source"] == src and all(holds(d, f, v) for f, v in filters)]
    e = q["expected"]
    if "ids" in e:
        return sorted(k for d in hits if (k := factbank_5k._key(d))) == sorted(e["ids"])
    return str(len(hits)) == str(e.get("value"))


def _owner_accounts_again(q: dict[str, Any], inside: list[dict[str, Any]]) -> bool:
    """Whether an owner_accounts question's answer is the same within ``inside``: the HubSpot accounts there owned by the
    meeting owner's name (its first piece) are as many as it expects or, for the 'which one' question, that one account.
    The draw picks one of the two questions at random, so the draw there may have asked the other."""
    owned = sorted(str(d["title"]).strip() for d in inside if d["source"] == "hubspot" and B._person(d["raw"].get("owner")) == q["pieces"][0])
    if q.get("field") == "name":
        return owned == [q["expected"].get("value")]
    return str(len(owned)) == str(q["expected"].get("value"))


def not_reproduced2(docs: list[dict[str, Any]], small: set[str], qs: list[dict[str, Any]], seed: int = Q2.SEED) -> dict[str, str]:
    """The questions of the new kinds and the held-out questions whose expected answer is not the same within ``small``, each
    with why ('differs' or 'not asked'); v15's questions are left to ``brain_test.not_reproduced``.

    - the new generated kinds: drawn again within the set, the question about the same documents and name
      (``brain_test._ident``) has the same field and expected answer; a count or filter not drawn so is counted again there
      (``_recount``: another filter may hold the same set there and be drawn instead), an owner_accounts question whose
      other form was drawn is read again (``_owner_accounts_again``);
    - field_absent: its gold document is in the set (the field is empty on the document itself);
    - held-out questions: always the same, since the set holds fewer documents than the haystack, none of them the held-out
      one."""
    inside = [d for d in docs if d["dsid"] in small]
    by_id = {d["dsid"]: d for d in inside}
    again = {q["kind"] for q in qs if part(q) == "v16" and q["kind"] != "field_absent"}
    by_ident: dict[tuple, list] = defaultdict(list)
    if again:
        for r in Q2.generate(inside, seed, kinds=again)[0]:
            by_ident[H._ident(r)].append(r)
    out: dict[str, str] = {}
    for q in qs:
        k = q["kind"]
        if part(q) == HELDOUT or (part(q) == "v16" and k == "field_absent"):
            why = None if set(q.get("gold_docs") or []) <= small else "gold document outside the set"
        elif part(q) == "v16":
            seen = by_ident.get(H._ident(q)) or []
            same = any((r.get("field"), r["expected"]) == (q.get("field"), q["expected"]) for r in seen)
            if not same and (rc := _recount(q, inside, by_id)) is not None:
                same, seen = rc, seen or [q]
            elif not same and k == "owner_accounts" and seen:
                same = _owner_accounts_again(q, inside)
            why = "not asked" if not seen else None if same else "differs"
        else:
            continue
        if why:
            out[q["id"]] = why
    return dict(sorted(out.items()))


def write_questions(work: Path, seed: int = Q2.SEED, mix15: dict[str, int] | None = None, mix16: dict[str, int] | None = None,
                    prose: Path | None = None, descriptive: Path | None = None, heldout: Path | None = None,
                    small: Path | None = None, multi_wordings: Path | None = None) -> dict[str, Any]:
    """Draw the questions of a work folder (``draw2``) and write W/questions.jsonl, W/set_aside_questions.jsonl and
    W/questions_report.json; with ``small``, the control folder too, recording the questions whose expected answer is not the
    same there (``brain_test.not_reproduced`` for v15's part, ``not_reproduced2`` for the rest)."""
    from cie.eval.factbank_multi import load_wordings

    if small is not None and small.resolve() == work.resolve():
        raise ValueError("the small folder must be another folder")
    t = time.perf_counter()
    hay = json.loads((work / "haystack.json").read_text())
    docs = H.load_docs(work)
    wordings = load_wordings(multi_wordings) if multi_wordings else None
    qs, aside, rep = draw2(docs, seed, mix15, mix16, B.load_prose(prose) if prose else None,
                           H.load_descriptive(descriptive) if descriptive else None, load_heldout(heldout) if heldout else None, wordings)
    _write_jsonl(work / "questions.jsonl", qs)
    _write_jsonl(work / "set_aside_questions.jsonl", aside)
    rep |= {"prose_file": str(prose) if prose else None, "descriptive_file": str(descriptive) if descriptive else None,
            "heldout_file": str(heldout) if heldout else None, "multi_wordings": str(multi_wordings) if multi_wordings else None,
            "readable": len(docs), "listed": len(hay["dsids"]), "small": None}
    if small is not None:
        sm = factbank_5k.small_set(qs)
        bad = {**H.not_reproduced(docs, sm, [q for q in qs if part(q) == "v15"], seed, wordings),
               **not_reproduced2(docs, sm, [q for q in qs if part(q) != "v15"], seed)}
        factbank_5k._write_set(small, Path(hay["root"]), sm, qs, work / "index.json", seed)
        rep["small"] = {"folder": str(small), "documents": len(sm), "not_reproduced": dict(sorted(bad.items()))}
        (small / H.REPORT).write_text(json.dumps({"control_of": str(work), **rep["small"]}, indent=1))
    rep["seconds"] = round(time.perf_counter() - t, 1)
    (work / H.REPORT).write_text(json.dumps(rep, indent=1))
    return rep


# ------------------------------------------------------------------ ask
def _file_sha(path: Any) -> str | None:
    """The sha256 of a lessons file, or None when there is none (a router may be named rather than given as a file)."""
    if path is None or not Path(path).is_file():
        return None
    return H._sha(Path(path))


@contextmanager
def _quote_documents() -> Iterator[list[tuple[str, list[str]]]]:
    """While open, each call of ``cie.retrieval.answer.quote_answer`` (which ``brain_test.ask_quotes`` looks up when it runs)
    is recorded with its answer and the documents of its quoted passages, in the order of their citation markers. The answers
    are the function's own."""
    from cie.retrieval import answer as A

    real, calls = A.quote_answer, []

    def recording(items: list[dict], question: str, *args: Any, **kw: Any):
        res = real(items, question, *args, **kw)
        calls.append((res[0] if res else "", [str(c.get("document_id")) for c in res[1]] if res else []))
        return res

    A.quote_answer = recording
    try:
        yield calls
    finally:
        A.quote_answer = real


def _ask_quotes(work: Path, name: str) -> dict[str, Any]:
    """``brain_test.ask`` for the quotes arm, then each row given "quote_docs": the documents of its quoted passages, one per
    citation marker, in turn. The answers are not changed: each recorded answer must be its row's."""
    with _quote_documents() as calls:
        rec = H.ask(work, "quotes", name=name)
    rows = _jsonl(work / f"{name}.jsonl")
    if len(calls) != len(rows) or any(c[0] != r["answer"] for c, r in zip(calls, rows, strict=False)):
        raise RuntimeError("the quoted passages recorded do not match the quotes arm's answers")
    _write_jsonl(work / f"{name}.jsonl", [{**r, "quote_docs": docs} for r, (_, docs) in zip(rows, calls, strict=True)])
    return rec


def _ask_v16(work: Path, single: Path | None, plans: Path | None, router: str | None, name: str) -> dict[str, Any]:
    """The v16 brain's answers (``cie.factbank.brain.ask_brain`` with ``v16=True``), recorded in W/arms.json as
    ``brain_test.ask`` records an arm, after the same checks: both lessons given, a name no other arm's answers hold nor
    another label names, and a v2 bank built from the folder's present documents."""
    if single is None:
        raise ValueError("arm v16 needs the single-document lessons (--single)")
    if plans is None:
        raise ValueError("arm v16 needs the plan lessons (--plans)")
    reg = H.registry(work)
    if reg.get(name, {}).get("arm") not in (None, "v16"):
        raise ValueError(f"{name}.jsonl holds arm {reg[name]['arm']}'s answers: choose another name")
    label = "v16" if name == FILES2["v16"] else name
    if clash := sorted(n for n, r in reg.items() if r["label"] == label and n != name):
        raise ValueError(f"the label {label!r} already names the answers in {clash[0]}.jsonl")
    try:
        from cie.factbank.brain import ask_brain
    except ModuleNotFoundError as e:
        if e.name != "cie.factbank.brain":
            raise
        raise SystemExit("arm v16 needs cie.factbank.brain (ask_brain), which is not there") from e
    hay = H.haystack_sha(work)
    built = H.banks(work).get(H.BANK["v15"])
    if built is None:
        raise ValueError(f"{H.BANK['v15']}.sqlite has no record of its build here: build it with `brain_test build`")
    if built.get("haystack_sha256") != hay:
        raise ValueError(f"{H.BANK['v15']}.sqlite was built from other documents than the folder's haystack holds: build it again")
    t = time.perf_counter()
    rep = ask_brain(work, single, plans, name=name, router=router, v16=True)
    rec = {"arm": "v16", "label": label, "file": f"{name}.jsonl", "single": str(single), "plans": str(plans), "router": router,
           "seconds": round(time.perf_counter() - t, 2), "answers": len(_jsonl(work / f"{name}.jsonl")),
           "questions_sha256": H._sha(work / "questions.jsonl"), "haystack_sha256": hay}
    reg = H.registry(work)  # read again: another arm may have been asked meanwhile
    reg[name] = rec
    (work / H.REGISTRY).write_text(json.dumps(reg, indent=1))
    return {**rec, "result": rep}


def ask(work: Path, arm: str, single: Path | None = None, plans: Path | None = None, router: str | None = None,
        name: str | None = None) -> dict[str, Any]:
    """One arm's answers to W/questions.jsonl, written to W/<name>.jsonl (``FILES2[arm]`` by default): v1, v2, v13 and v15 by
    ``brain_test.ask``, quotes by ``brain_test.ask`` with the quoted documents recorded (``_ask_quotes``), v16 by
    ``_ask_v16``. The arm's record in W/arms.json gets the sha256 of each lessons file it was given (single, plans, router)
    and the PYTHONHASHSEED it ran under (None: not set, so random). A name may not be another arm's answers file, nor
    another arm's name ('v15', 'quotes'), nor, for an arm other than v16, a label of v16's own answers (``OWN``)."""
    if arm not in ARMS2:
        raise ValueError(f"unknown arm {arm!r}: one of {', '.join(ARMS2)}")
    name = name or FILES2[arm]
    if not re.fullmatch(r"[\w.-]+", name) or name in H.RESERVED:
        raise ValueError(f"{name!r} cannot name an answers file")
    if other := next((a for a, f in FILES2.items() if f == name and a != arm), None):
        raise ValueError(f"{name}.jsonl is arm {other}'s answers file: choose another name")
    if name in ARMS2 and name != arm:
        raise ValueError(f"{name!r} is arm {name}'s label: choose another name")
    if arm != "v16" and name in OWN:
        raise ValueError(f"{name!r} labels the v16 brain's answers: choose another name")
    if arm == "v16":
        rec = _ask_v16(work, single, plans, router, name)
    elif arm == "quotes":
        rec = _ask_quotes(work, name)
    else:
        rec = H.ask(work, arm, single, plans, router, name)
    extra = {"single_sha256": _file_sha(rec.get("single")), "plans_sha256": _file_sha(rec.get("plans")),
             "router_sha256": _file_sha(rec.get("router")), "pythonhashseed": os.environ.get("PYTHONHASHSEED")}
    reg = H.registry(work)
    reg[name] = {**reg[name], **extra}
    (work / H.REGISTRY).write_text(json.dumps(reg, indent=1))
    return {**rec, **extra}


# ------------------------------------------------------------------ score
def route_class(route: Any) -> str | None:
    """The kind of a route: 'not_found' (not_found, absent), 'prose', or 'fact' for any other (plan, fact, table, derived,
    v1's answer, ...)."""
    if route is None:
        return None
    r = str(route).lower().replace(" ", "_")
    return "not_found" if r.startswith(NOT_FOUND_ROUTES) else "prose" if r.startswith("prose") else "fact"


def score_one(q: dict[str, Any], row: dict[str, Any] | str) -> float | None:
    """One answer's score: ``brain2_questions.score``, and for an unanswerable question of no catalogue kind (the held-out
    writers' questions) 1 if the answer says not found (``brain_questions.says_not_found``), else 0."""
    if Q2.family(q) == "unanswerable" and q.get("kind") not in Q2.CATALOGUE:
        answer, route = (row, None) if isinstance(row, str) else (str(row.get("answer") or ""), row.get("route"))
        return float(B.says_not_found(answer, route))
    return Q2.score(q, row)


def _dsid(doc: Any) -> str:
    s = str(doc or "").strip()
    return s[len("doc:"):] if s.startswith("doc:") else s


def provenance(row: dict[str, Any]) -> tuple[list[str], bool] | None:
    """The documents a quoted answer's text came from, or None when that is not known: (the documents of its quoted passages,
    one per citation marker in turn, True) when the row lists them ("quote_docs", the quotes arm); ([the document], False)
    when the whole answer is quoted from one document: the row's "doc", or a reason naming one document as the brain's prose
    routes write it ("quoted from 2 passage(s) of doc:X; ..."). A reason naming several documents does not say which text
    came from which."""
    if isinstance(row.get("quote_docs"), list):
        return [_dsid(d) for d in row["quote_docs"]], True
    if row.get("doc"):
        return [_dsid(row["doc"])], False
    m = QUOTED_FROM.search(str(row.get("reason") or ""))
    docs = [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []
    return ([_dsid(docs[0])], False) if len(docs) == 1 else None


def quoted_parts(answer: str) -> list[str]:
    """A quoted answer cut at its citation markers "[1]", "[2]", ... in turn: the text of each quoted passage, its label
    included. A marker out of turn is part of the text."""
    parts, start, n = [], 0, 1
    for m in H.CITATION.finditer(answer):
        if m.group().strip() == f"[{n}]":
            parts.append(answer[start:m.start()])
            start, n = m.end(), n + 1
    return parts


def strict_prose(q: dict[str, Any], row: dict[str, Any]) -> float | None:
    """A free-text question's fact share (``brain_questions.fact_share``) counted only over the text quoted from one of its
    gold documents (``provenance``): with quote_docs, the quoted passages of gold documents; with one document, the whole
    answer if it is a gold document, else nothing. 0 for an answer of not found; None when the documents are not known."""
    answer = str(row.get("answer") or "")
    if B.says_not_found(H.plain_answer(answer), row.get("route")):
        return 0.0
    prov = provenance(row)
    if prov is None:
        return None
    docs, per_part = prov
    gold = set(q.get("gold_docs") or [])
    if per_part:
        parts = quoted_parts(answer)
        if len(parts) != len(docs):
            return None
        text = " ".join(p for p, d in zip(parts, docs, strict=True) if d in gold)
    else:
        text = H.plain_answer(answer) if docs[0] in gold else ""
    return B.fact_share((q.get("expected") or {}).get("facts") or [], text)


def score_rows2(work: Path) -> dict[str, Any]:
    """Every arm's score on every question of the folder (``score_one``; None: code cannot check it), as
    ``brain_test.score_rows`` gives it: whether it said not found, its route, its time and the answer's length, and for a
    free-text question the facts its evidence reaches within each budget and the strict score ("strict": {score, quoted}: a
    quoted answer by ``strict_prose``, any other by its own score). Answers are scored without their citation markers."""
    qs = _jsonl(work / "questions.jsonl")
    files, stale = H.answered(work)
    answers = {label: {r["id"]: r for r in _jsonl(work / f"{name}.jsonl")} for label, name in files.items()}
    rows = []
    for q in qs:
        fam = Q2.family(q)
        r: dict[str, Any] = {"id": q["id"], "family": fam, "group": q.get("group"), "kind": q.get("kind"), "score": {},
                             "not_found": {}, "route": {}, "reach": {}, "strict": {}, "ms": {}, "chars": {}}
        for label, by_id in answers.items():
            row = by_id.get(q["id"])
            if row is None:
                continue
            plain = H.plain_answer(row.get("answer"))
            r["score"][label] = score_one(q, {**row, "answer": plain})
            r["not_found"][label] = B.says_not_found(plain, row.get("route"))
            if row.get("route") is not None:
                r["route"][label] = row["route"]
            if fam == "prose":
                r["reach"][label] = {str(b): B.prose_reach(q, str(row.get("evidence") or ""), b) for b in H.BUDGETS}
                quoted = route_class(row.get("route")) == "prose"
                r["strict"][label] = {"score": strict_prose(q, row) if quoted else r["score"][label], "quoted": quoted}
            r["ms"][label] = row.get("ms")
            r["chars"][label] = len(str(row.get("answer") or ""))
        rows.append(r)
    return {"labels": list(answers), "stale": stale, "rows": rows}


def routes2(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    """An arm's routes by family: the routes it took, their kinds (``route_class``), and the share of questions routed to
    their family's kind (``ROUTE2``; unanswerable questions are not counted), per family, as the mean over families and over
    all counted questions."""
    counts: dict[str, Counter] = defaultdict(Counter)
    kinds: dict[str, Counter] = defaultdict(Counter)
    right: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if label not in r["score"]:
            continue
        route = r["route"].get(label)
        counts[r["family"]][str(route)] += 1
        kinds[r["family"]][str(route_class(route))] += 1
        if r["family"] in ROUTE2:
            right[r["family"]].append(float(route_class(route) == ROUTE2[r["family"]]))
    acc = {f: _mean(right[f]) for f in FAMILIES2 if right[f]}
    return {"counts": {f: dict(sorted(counts[f].items())) for f in FAMILIES2 if counts[f]},
            "kinds": {f: dict(sorted(kinds[f].items())) for f in FAMILIES2 if kinds[f]},
            "accuracy": acc, "accuracy_mean_over_families": _mean(acc.values()),
            "accuracy_all": _mean(x for f in right for x in right[f])}


def summarise2(rows: list[dict[str, Any]], labels: list[str]) -> dict[str, Any]:
    """Each arm's means by family (``FAMILIES2``), group and kind, over the families it has and over v15's four, the
    questions it left out or did not answer, false "not found" on answerable questions (``ANSWERABLE``, by family and in
    all), prose facts in its evidence, the strict free-text score (given only when the arm quoted some answer and every
    quoted answer's documents are known), time per question, the answers' length and its routes."""
    out = {}
    for a in labels:
        mine = [r for r in rows if a in r["score"]]
        fam = {f: _mean(r["score"][a] for r in mine if r["family"] == f) for f in FAMILIES2}
        groups = sorted({str(r["group"]) for r in mine})
        kinds = sorted({str(r["kind"]) for r in mine})
        nf: dict[str, float | None] = {f: _mean(float(r["not_found"][a]) for r in mine if r["family"] == f) for f in ANSWERABLE}
        nf["all"] = _mean(float(r["not_found"][a]) for r in mine if r["family"] in ANSWERABLE)
        prose = [r for r in mine if a in r["reach"]]
        strict = [r["strict"][a] for r in prose]
        quoted = [s for s in strict if s["quoted"]]
        unknown = sum(1 for s in quoted if s["score"] is None)
        out[a] = {
            "answered": len(mine), "missing": len(rows) - len(mine), "left_out": sum(1 for r in mine if r["score"][a] is None),
            "by_family": fam, "mean_of_families": _mean(fam[f] for f in FAMILIES2), "mean_of_v15_families": _mean(fam[f] for f in B.FAMILIES),
            "families": [f for f in FAMILIES2 if fam[f] is not None],
            "by_group": {g: _mean(r["score"][a] for r in mine if str(r["group"]) == g) for g in groups},
            "by_kind": {k: {"mean": _mean(r["score"][a] for r in mine if str(r["kind"]) == k), "n": sum(1 for r in mine if str(r["kind"]) == k)}
                        for k in kinds},
            "false_not_found": nf,
            "prose_reach": {str(b): _mean(r["reach"][a][str(b)] for r in prose) for b in H.BUDGETS} if prose else None,
            "strict_prose": {"mean": _mean(s["score"] for s in strict) if quoted and not unknown else None, "questions": len(strict),
                             "quoted": len(quoted), "documents_unknown": unknown},
            "time_ms": _ms([r["ms"].get(a) for r in mine]),
            "answer_chars": _ms([r["chars"][a] for r in mine]),
            "routes": routes2(rows, a) if any(a in r["route"] for r in mine) else None,
        }
    return out


def own_labels(arms: dict[str, Any] | None) -> list[str]:
    """The labels of the v16 brain's own answers, which are never another arm: ``OWN`` and every label whose record (a
    report's "arms", label -> its record in W/arms.json) names arm v16, such as v16 asked again under another name with other
    lessons ('--arm v16 --name v16b')."""
    return sorted(set(OWN) | {label for label, rec in (arms or {}).items() if (rec or {}).get("arm") == "v16"})


def best_other(scores: dict[str, Any], family: str, own: Iterable[str] = OWN) -> tuple[str, float] | None:
    """The other arm (not one of ``own``, the v16 brain's own labels: ``own_labels``) with the highest mean on the family, and
    its mean (ties: the first label in name order); None when no other arm has one."""
    own = set(own)
    others = {a: m["by_family"][family] for a, m in scores.items() if a not in own and m["by_family"].get(family) is not None}
    if not others:
        return None
    a = max(sorted(others), key=lambda x: others[x])
    return a, others[a]


def paired2(rows: list[dict[str, Any]], scores: dict[str, Any], arm: str = "v16", own: Iterable[str] = OWN) -> dict[str, Any]:
    """For each family, the mean paired difference of ``arm`` minus the best other arm on that family (``best_other``, not one
    of ``own``) over the questions both scored, its 95% bootstrap interval (``memory_test.paired_ci``) and the questions it is
    over, as ``brain_test.paired_intervals`` reports them. Reported, not decided on."""
    from cie.eval.memory_test import paired_ci

    out = {}
    for fam in FAMILIES2:
        best = best_other(scores, fam, own)
        if best is None or arm not in scores:
            continue
        other = best[0]
        pairs = [(r["score"][arm], r["score"][other]) for r in rows
                 if r["family"] == fam and r["score"].get(arm) is not None and r["score"].get(other) is not None]
        a, b = [x for x, _ in pairs], [y for _, y in pairs]
        out[fam] = {"other": other, "questions": len(pairs), "mean": round(sum(a) / len(a) - sum(b) / len(b), 3) if pairs else None,
                    "interval_95": paired_ci(a, b) if pairs else None}
    return out


# ------------------------------------------------------------------ rules
# The thresholds of the rules: placeholders, each set before the freeze (docs/FACTBANK_BRAIN2_PREREGISTRATION.md). A rule reads
# v16's answers (label "v16") and, where it says so, the best other arm on the family (``best_other``); no label of the v16
# brain's own answers is another arm (``own_labels``: v16_seed1 and any label asked as arm v16, read from the report's "arms").
EPS = H.EPS
SINGLE_MARGIN = 0.03  # set before the freeze: single, v16 >= the best other arm - this
MULTI_MARGIN = 0.03  # set before the freeze: multi, v16 >= the best other arm - this
PROSE_MARGIN = 0.05  # set before the freeze: free text, v16 >= the best other arm - this
NOT_FOUND_MIN = 0.80  # set before the freeze: questions about nothing in the bank
UNANSWERABLE_MIN = 0.60  # set before the freeze: natural questions with no answer in the haystack
FALSE_NOT_FOUND_MAX = 0.05  # set before the freeze: "not found" said to answerable questions
NEW_MIN = 0.60  # set before the freeze: counts, history, email and chat, each at least this
NEW_LEAD = 0.10  # set before the freeze: ... and at least the best other arm + this
MEAN_LEAD = 0.20  # set before the freeze: the mean over the eight families >= every other arm's + this
ROUTE_MIN = 0.90  # set before the freeze: route accuracy, mean over families
SIZE_MARGIN = 0.05  # set before the freeze: single, multi and free text at 5,000 documents >= the small set - this, each


def _fam(r: dict[str, Any], family: str, arm: str = "v16") -> float:
    return r["scores"][arm]["by_family"][family]


def _own(r: dict[str, Any]) -> list[str]:
    return own_labels(r.get("arms"))


def _best(r: dict[str, Any], family: str) -> float:
    best = best_other(r["scores"], family, _own(r))
    if best is None:
        raise KeyError(f"no other arm has a {family} score")
    return best[1]


def preregistered2() -> dict[str, Rule]:
    """The rules of the v16 test, each named with its threshold (the module constants above, set before the freeze); applied
    by ``brain_test.rules``, which gives None when the report lacks what a rule reads."""
    others = lambda r: [a for a in r["scores"] if a not in _own(r)]  # noqa: E731
    out: dict[str, Rule] = {
        f"1 single-document questions: v16 >= the best other arm - {SINGLE_MARGIN}":
            lambda r: _fam(r, "single") >= _best(r, "single") - SINGLE_MARGIN - EPS,
        f"2 multi-document questions: v16 >= the best other arm - {MULTI_MARGIN}":
            lambda r: _fam(r, "multi") >= _best(r, "multi") - MULTI_MARGIN - EPS,
        f"3 free text: v16 >= the best other arm - {PROSE_MARGIN}": lambda r: _fam(r, "prose") >= _best(r, "prose") - PROSE_MARGIN - EPS,
        f"4 not found: v16 >= {NOT_FOUND_MIN} on questions about nothing in the bank":
            lambda r: _fam(r, "not_found") >= NOT_FOUND_MIN - EPS,
        f"5 no answer in the haystack: v16 >= {UNANSWERABLE_MIN} on the unanswerable questions":
            lambda r: _fam(r, "unanswerable") >= UNANSWERABLE_MIN - EPS,
        f"6 false 'not found': v16 says not found to at most {FALSE_NOT_FOUND_MAX} of the answerable questions":
            lambda r: r["scores"]["v16"]["false_not_found"]["all"] <= FALSE_NOT_FOUND_MAX + EPS,
    }
    for i, fam in enumerate(NEW_FAMILIES, 7):
        out[f"{i} {fam}: v16 >= {NEW_MIN} and >= the best other arm + {NEW_LEAD}"] = \
            lambda r, fam=fam: _fam(r, fam) >= NEW_MIN - EPS and _fam(r, fam) >= _best(r, fam) + NEW_LEAD - EPS
    out |= {
        f"10 one brain for every kind: v16's mean over the eight families >= every other arm's + {MEAN_LEAD}":
            lambda r: r["scores"]["v16"]["mean_of_families"] >= max(r["scores"][a]["mean_of_families"] for a in others(r)) + MEAN_LEAD - EPS,
        f"11 the right route: v16's route accuracy, mean over families, >= {ROUTE_MIN}":
            lambda r: r["scores"]["v16"]["routes"]["accuracy_mean_over_families"] >= ROUTE_MIN - EPS,
        f"12 it holds at size: v16 at 5,000 documents >= the small set - {SIZE_MARGIN} on each of single, multi and free text":
            lambda r: all(r["small"]["differences"]["v16"]["big_minus_small"][f] >= -SIZE_MARGIN - EPS for f in H.SIZE_FAMILIES),
    }
    return out


def score(work: Path, small: Path | None = None, out: Path | None = None, rule_fns: dict[str, Rule] | None = None) -> dict[str, Any]:
    """Score every arm answered in ``work`` (and in ``small``, the control folder) and write report.json and report.md to
    ``out`` (``work`` by default), as ``brain_test.score`` does over ``FAMILIES2``: the big-minus-small differences
    (``brain_test.against_small``) only when the control folder holds the same questions, leaving out those its draw found
    not to reproduce there; the paired differences of v16 and the best other arm per family, where no label asked as arm v16
    is another arm ("own": ``own_labels``); and the hash-seed check of v16 against v16_seed1."""
    out = out or work
    big = score_rows2(work)
    qs = _jsonl(work / "questions.jsonl")
    draw_rep = _read(work / H.REPORT) or {}
    keep = ("arm", "file", "single", "plans", "router", "seconds", "answers", *PROVENANCE)
    rep: dict[str, Any] = {
        "work": str(work), "questions": len(qs), "by_part": _count(qs, part), "by_family": _count(qs, Q2.family),
        "by_group": _count(qs, lambda q: str(q.get("group"))), "by_kind": _count(qs, lambda q: str(q.get("kind"))),
        "arms": {rec["label"]: {k: rec.get(k) for k in keep} for rec in H.registry(work).values() if rec["label"] in big["labels"]},
        "stale_arms": big["stale"], "scores": summarise2(big["rows"], big["labels"]),
        "builds": {n: b for n in ("factbank", "factbank_v2") if (b := _read(work / f"{n}_build.json")) is not None},
        "draw": draw_rep, "small": None}
    rep["own"] = own = own_labels(rep["arms"])
    rep["best_other"] = {f: dict(zip(("arm", "mean"), b, strict=True)) for f in FAMILIES2 if (b := best_other(rep["scores"], f, own))}
    if small is not None:
        sm = score_rows2(small)
        same = H._asked(qs) == H._asked(_jsonl(small / "questions.jsonl"))
        skip = set(((_read(small / H.REPORT) or draw_rep.get("small") or {}).get("not_reproduced") or {}) if same else ())
        rep["small"] = {"work": str(small), "same_questions": same, "not_reproduced": sorted(skip), "stale_arms": sm["stale"],
                        "scores": summarise2(sm["rows"], sm["labels"]), "differences": H.against_small(big, sm, skip) if same else None,
                        "note": None if same else "the control folder holds other questions (another draw's): no differences",
                        "builds": {n: b for n in ("factbank", "factbank_v2") if (b := _read(small / f"{n}_build.json")) is not None},
                        "rows": sm["rows"]}
    rep["seed_check"] = H.seed_check(work, "v16", "v16_seed1")
    rep["paired"] = paired2(big["rows"], rep["scores"], own=own) if "v16" in big["labels"] else None
    why: dict[str, str] = {}
    rep["rules"] = H.rules(rep, rule_fns or {}, why)
    rep["rules_why"] = why
    rep["rows"] = big["rows"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    (out / "report.md").write_text(to_markdown(rep))
    return rep


def _f(x: Any, digits: int = 3) -> str:
    return H._f(x, digits)


def _table(head: Iterable[str], rows: Iterable[Iterable[Any]]) -> list[str]:
    head = list(head)
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *("| " + " | ".join(_f(x) for x in r) + " |" for r in rows)]


def to_markdown(rep: dict[str, Any]) -> str:
    fams = FAMILIES2
    s = rep["scores"]
    out = ["### The company brain test, round 2 (v16)", "",
           f"{rep['questions']} questions ({', '.join(f'{k} {v}' for k, v in rep['by_family'].items())}; parts "
           f"{', '.join(f'{k} {v}' for k, v in rep['by_part'].items())}) on {rep['work']}.", ""]
    out += _table(["arm", *fams, "mean of 8", "mean of v15's 4", "left out", "not answered"],
                  [[a, *(m["by_family"][f] for f in fams), m["mean_of_families"], m["mean_of_v15_families"], m["left_out"], m["missing"]]
                   for a, m in s.items()])
    groups = sorted({g for m in s.values() for g in m["by_group"]})
    out += ["", "By group:", ""] + _table(["arm", *groups], [[a, *(m["by_group"].get(g) for g in groups)] for a, m in s.items()])
    out += ["", "False \"not found\" on answerable questions, the strict free-text score (facts quoted from a gold document; – when"
            " the arm quotes nothing or the quoted documents are not known), free-text facts in the evidence, route accuracy"
            " (mean over families), time per question (ms) and the answers' length (characters):", ""]
    rows = []
    for a, m in s.items():
        pr, t, sp = m["prose_reach"] or {}, m["time_ms"] or {}, m["strict_prose"]
        rows.append([a, m["false_not_found"]["all"], sp["mean"], f"{sp['quoted']}/{sp['questions']}", *(pr.get(str(b)) for b in H.BUDGETS),
                     (m["routes"] or {}).get("accuracy_mean_over_families"), *(_f(t.get(x), 1) for x in ("median", "p90", "max")),
                     _f((m["answer_chars"] or {}).get("median"), 0)])
    out += _table(["arm", "false not found", "strict prose", "quoted", "prose 2,000", "prose 6,000", "prose 24,000", "route accuracy",
                   "median ms", "p90 ms", "max ms", "median chars"], rows)
    for a, m in s.items():
        if m["routes"]:
            r = m["routes"]
            out += ["", f"Routes of {a} (right route: a fact route for single, multi, counts, history and email_chat; prose for free"
                    " text; not found for not_found; unanswerable not counted):", ""]
            out += _table(["family", "routes", "right route"],
                          [[f, json.dumps(r["counts"].get(f, {})), r["accuracy"].get(f)] for f in fams if f in r["counts"]])
            out.append(f"| mean over families | | **{_f(r['accuracy_mean_over_families'])}** |")
    if rep.get("paired"):
        out += ["", "v16 minus the best other arm on each family (paired over the family's questions; 95% bootstrap interval):", ""]
        out += _table(["family", "best other arm", "questions", "v16 - other", "95% interval"],
                      [[f, p["other"], p["questions"], p["mean"], json.dumps(p["interval_95"])] for f, p in rep["paired"].items()])
    kinds = sorted({k for m in s.values() for k in m["by_kind"]})
    if kinds:
        n = {k: max(m["by_kind"].get(k, {}).get("n", 0) for m in s.values()) for k in kinds}
        out += ["", "By kind:", ""] + _table(["kind", "n", *s], [[k, n[k], *(m["by_kind"].get(k, {}).get("mean") for m in s.values())]
                                                                 for k in kinds])
    if rep["small"] and rep["small"]["differences"] is None:
        out += ["", f"Big folder minus the small one ({rep['small']['work']}): none, {rep['small']['note']}."]
    elif rep["small"]:
        sm = rep["small"]
        out += ["", f"Big folder minus the small one ({sm['work']}; not reproduced there, left out: {len(sm['not_reproduced'])}):", ""]
        out += _table(["arm", "questions", *H.SIZE_FAMILIES, "changed"],
                      [[a, d["questions"], *(d["big_minus_small"][f] for f in H.SIZE_FAMILIES), len(d["changed"])]
                       for a, d in sm["differences"].items()])
    out += ["", "Rules:" if rep["rules"] else "Rules: none applied (`--preregistered` applies them)."]
    out += [f"- {k}: **{'met' if v else 'not met' if v is not None else 'n/a'}**" + (f" ({rep['rules_why'][k]})" if k in rep["rules_why"] else "")
            for k, v in rep["rules"].items()]
    out += ["", f"- best other arm per family: {json.dumps(rep.get('best_other'))}",
            f"- the v16 brain's own answers, never another arm: {json.dumps(rep.get('own'))}",
            f"- hash-seed check (v16 under another hash seed, v16_seed1): {json.dumps(rep.get('seed_check'))}",
            f"- arms: {json.dumps(rep['arms'])}", f"- left out as stale: {json.dumps(rep['stale_arms'])}",
            f"- builds: {json.dumps(rep['builds'])}",
            f"- draw: {json.dumps({k: rep['draw'].get(k) for k in ('seed', 'mix15', 'mix16', 'heldout', 'set_aside_written', 'gold_documents')})}"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain2_test")
    ap.add_argument("cmd", choices=["questions", "ask", "score"])
    ap.add_argument("--work", required=True)
    ap.add_argument("--seed", type=int, default=Q2.SEED)
    ap.add_argument("--mix15", default=None, help="questions: v15's part, {kind, group, family or 'descriptive': number} (default MIX15)")
    ap.add_argument("--mix16", default=None, help="questions: the new kinds, {kind, group or family: number} (default MIX16)")
    ap.add_argument("--prose", default=None, help="questions: writer-made prose questions (brain_questions.load_prose)")
    ap.add_argument("--descriptive", default=None, help="questions: writer-made field questions (brain_test.load_descriptive)")
    ap.add_argument("--heldout", default=None, help="questions: held-out unanswerable questions (brain2_draw collect)")
    ap.add_argument("--wordings", default=None, help="questions: wordings for v15's multi-document kinds (factbank_multi.load_wordings)")
    ap.add_argument("--small", default=None, help="questions: write the control folder here; score: compare with it")
    ap.add_argument("--arm", choices=ARMS2)
    ap.add_argument("--single", default=None, help="ask: the single-document lessons")
    ap.add_argument("--plans", default=None, help="ask: the plan lessons")
    ap.add_argument("--router", default=None, help="ask, v15 and v16: the router, as cie.factbank.brain names it")
    ap.add_argument("--name", default=None, help="ask: the answers file (default: the arm's)")
    ap.add_argument("--out", default=None, help="score: where to write report.json and report.md (default: --work)")
    ap.add_argument("--preregistered", action="store_true", help="score: apply the rules (preregistered2)")
    a = ap.parse_args(argv)
    work = Path(a.work)
    path = lambda x: Path(x) if x else None  # noqa: E731
    if a.cmd == "questions":
        rep = write_questions(work, a.seed, H.parse_mix(a.mix15), H.parse_mix(a.mix16), path(a.prose), path(a.descriptive),
                              path(a.heldout), path(a.small), path(a.wordings))
        rep = {k: rep[k] for k in ("questions", "by_part", "by_family", "mix15", "mix16", "heldout", "small", "seconds")}
    elif a.cmd == "ask":
        if a.arm is None:
            ap.error("ask needs --arm")
        rep = ask(work, a.arm, path(a.single), path(a.plans), a.router, a.name)
    else:
        r = score(work, path(a.small), path(a.out), preregistered2() if a.preregistered else None)
        rep = {a_: {"by_family": m["by_family"], "mean_of_families": m["mean_of_families"]} for a_, m in r["scores"].items()}
        if a.preregistered:
            rep["rules"] = r["rules"]
    print(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    main()
