"""The 5,000-document test, part A (docs/FACTBANK_5K_PREREGISTRATION.md): the frozen fact bank and planner, with the bank built
from 5,000 documents instead of 50. Only the bank's size changes.

- **The set** is a new sample of the whole benchmark: every source in its share of what earlier sets left, each ticket key and
  pull request number on one document only, and a few pull requests whose ticket no other pull request references (``draw``).
- **The questions** are drawn over all 5,000 documents, as in earlier tests. Those with more than one right answer in the set
  are set aside (``unclear``): something they name, or a key their answer rests on, is on more than one document; or "tickets"
  read as Linear and Jira gives another answer than the Linear-only answer the questions expect.
- **The control:** the same questions are asked of a small bank holding only the documents they need (``small_set``), so the
  effect of the other documents is measured on identical questions and expected answers.

    python -m cie.eval.factbank_5k draw --index $IDX --root $BENCH --exclude DIRS --big W5K --small WSMALL --unclear WX
    (build both banks of W5K and WSMALL and answer with every arm: docs/benchmarks/factbank_5k/run_5k.sh)
    python -m cie.eval.factbank_5k score --big W5K --small WSMALL --unclear WX
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cie.eval.factbank_multi import (
    KEY,
    _keys,
    _person,
    at_least,
    load_wordings,
    measure,
    own_score,
    questions,
)
from cie.eval.memory_test import _iso, _jsonl, _write_jsonl, action_items

N_BIG = 5000
N_QUESTIONS = 50
PLANTED = 10
SEED, QSEED = 53, 54
TRACKERS = ("linear", "jira")
LOSS = -0.05  # rules 1, 4 and 5: at most this much lost to size
LEVEL = 0.92  # rule 2: within 0.05 of the eight earlier held-out sets' mean for v13 (0.969)
ARMS = ("v1", "v4", "v8", "v9", "v11", "v12", "v13", "v14")
FILES = {"v1": "factbank", "v4": "factbank_v4", "v8": "factbank_v8", "v9": "factbank_v9", "v11": "factbank_v11", "v12": "factbank_v12",
         "v13": "factbank_v13", "v14": "factbank_v14"}


def _key(d: dict[str, Any]) -> str | None:
    k = d["raw"].get("key") if d["source"] in TRACKERS else None
    return str(k).upper() if k else None


def _pr(d: dict[str, Any]) -> str | None:
    n = str(d["raw"].get("pr_number") or "") if d["source"] == "github" else ""
    return n or None


def remaining(index: dict[str, str], exclude: set[str]) -> dict[str, list[str]]:
    """The benchmark's documents not in ``exclude``, by source, each list sorted."""
    by_src: dict[str, list[str]] = defaultdict(list)
    for dsid, rel in sorted(index.items()):
        if dsid not in exclude:
            by_src[rel.split("/")[0]].append(dsid)
    return dict(by_src)


def draw(index: dict[str, str], exclude: set[str], load, n: int = N_BIG, seed: int = SEED, planted: int = PLANTED) -> tuple[list[str], dict]:
    """``n`` documents, every source in its share of what is left after ``exclude``.

    - **One document per name:** a ticket key (Linear and Jira share one namespace) or a pull request number (in any repository)
      already drawn is not drawn again. The benchmark reuses some keys and numbers on unrelated documents; a real company does
      not, and a question naming one would have two right answers.
    - **Planted pull requests:** ``planted`` pull requests are drawn first, each linking one Linear issue that no other pull
      request left in the benchmark references, so that "who opened the pull request for ticket K?" has one answer. A plain
      sample holds almost none (docs/benchmarks/factbank_5k/understand.json).

    ``load(dsids)`` reads documents as ``haystack_docs`` does; only the tracker and GitHub documents are read here."""
    by_src = remaining(index, exclude)
    total = sum(len(v) for v in by_src.values())
    target = {s: round(n * len(v) / total) for s, v in by_src.items()}
    target[max(target, key=lambda s: (target[s], s))] += n - sum(target.values())
    rng = random.Random(seed)
    linked = {d["dsid"]: d for d in load([x for s in ("linear", "jira", "github") for x in by_src.get(s, [])])}
    key_count = Counter(k for d in linked.values() if (k := _key(d)))
    pr_count = Counter(p for d in linked.values() if (p := _pr(d)))
    refs: dict[str, set[str]] = defaultdict(set)
    for d in linked.values():
        if d["source"] == "github":
            for k in dict.fromkeys(_keys(d["raw"].get("linked_linear"))):
                refs[k].add(d["dsid"])
    lin_by_key = {k: d for d in linked.values() if d["source"] == "linear" and (k := _key(d))}
    cands = []
    for d in sorted(linked.values(), key=lambda d: d["dsid"]):
        p = _pr(d) or ""
        if d["source"] != "github" or not p.isdigit() or len(p) < 3 or pr_count[p] != 1:
            continue
        ks = list(dict.fromkeys(k for k in _keys(d["raw"].get("linked_linear")) if k in lin_by_key))
        if len(ks) == 1 and key_count[ks[0]] == 1 and refs[ks[0]] == {d["dsid"]}:
            cands.append((d["dsid"], lin_by_key[ks[0]]["dsid"]))
    rng.shuffle(cands)
    plant = cands[:planted]
    chosen: list[str] = []
    keys: set[str] = set()
    prs: set[str] = set()
    skipped: Counter = Counter()

    def add(dsid: str) -> None:
        d = linked.get(dsid)
        if d is not None:
            if (k := _key(d)):
                keys.add(k)
            if (p := _pr(d)):
                prs.add(p)
        chosen.append(dsid)

    for pr, issue in plant:
        add(pr)
        add(issue)
    src_of = {x: s for s, v in by_src.items() for x in v}
    have = Counter(src_of[x] for x in chosen)
    taken = set(chosen)
    for s in sorted(by_src):
        pool = [x for x in by_src[s] if x not in taken]
        rng.shuffle(pool)
        for dsid in pool:
            if have[s] >= target[s]:
                break
            if s in ("linear", "jira", "github"):
                d = linked.get(dsid)
                if d is None:
                    skipped["unreadable"] += 1
                    continue
                if (k := _key(d)) and k in keys:
                    skipped["ticket key already drawn"] += 1
                    continue
                if (p := _pr(d)) and p in prs:
                    skipped["pull request number already drawn"] += 1
                    continue
            add(dsid)
            have[s] += 1
    info = {"documents": len(chosen), "targets": dict(sorted(target.items())), "drawn": dict(sorted(have.items())),
            "skipped": dict(skipped), "planted": [{"pr": a, "issue": b} for a, b in plant], "planted_candidates": len(cands),
            "remaining": total, "excluded": len(exclude)}
    return sorted(chosen), info


def _assignee_of(q: dict[str, Any], by_id: dict[str, dict]) -> str | None:
    """The person a count, first-due or action-item question asks about."""
    if q["kind"] == "action_owner_issues":
        return q["pieces"][0] if q.get("pieces") else None
    for dsid in q["gold_docs"]:
        d = by_id.get(dsid)
        if d is not None and d["source"] == "linear":
            return _person(d["raw"].get("assignee"))
    return None


def ticket_reading(q: dict[str, Any], inside: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The expected answer if "tickets" means Linear and Jira items, for the questions about a person's tickets; None when
    that reading changes nothing. The questions expect Linear issues only (factbank_multi.questions)."""
    if q["kind"] not in ("person_count", "person_first", "action_owner_issues"):
        return None
    by_id = {d["dsid"]: d for d in inside}
    p = _assignee_of(q, by_id)
    jira = [d for d in inside if d["source"] == "jira" and p and _person(d["raw"].get("assignee")) == p]
    if not jira:
        return None
    lin = [d for d in inside if d["source"] == "linear" and _person(d["raw"].get("assignee")) == p]
    both = lin + jira
    if q["kind"] == "person_count":
        alt: dict[str, Any] = {"value": str(len(both))}
    elif q["kind"] == "action_owner_issues":
        alt = {"ids": sorted(_key(d) for d in both if _key(d)), "id_kind": "key"}
    else:
        dated = sorted((_iso(d["raw"].get("due_date")), _key(d)) for d in both if _iso(d["raw"].get("due_date")) and _key(d))
        alt = {"ids": [dated[0][1]], "id_kind": "key"} if dated else q["expected"]
    return None if alt == q["expected"] else alt


def why_unclear(q: dict[str, Any], inside: list[dict[str, Any]]) -> str | None:
    """Why the question has more than one right answer in the set, or None.

    - **named:** a ticket key, pull request number or meeting title it names is on more than one document, or the action item
      it names was taken by more than one person in that meeting;
    - **answer:** a ticket key its answer rests on (``pieces``) is on more than one document;
    - **tickets:** read as Linear and Jira items, "tickets" gives another answer (``ticket_reading``)."""
    keys = Counter(k for d in inside if (k := _key(d)))
    prs = Counter(p for d in inside if (p := _pr(d)))
    meetings: dict[str, list[dict]] = defaultdict(list)
    for d in inside:
        if d["source"] == "fireflies":
            meetings[d["title"]].append(d)
    text = q["question"]
    quoted = re.findall(r'"([^"]+)"', text)
    if any(keys[k] > 1 for k in KEY.findall(text)) or any(prs[n] > 1 for n in re.findall(r"#(\d+)", text)):
        return "named"
    if q["kind"] == "action_owner_issues":
        ms = [m for t in quoted for m in meetings.get(t, [])]
        if len({m["dsid"] for m in ms}) != 1:
            return "named"
        owners = {o for o, t, _ in action_items(ms[0]["raw"]) if t in quoted}
        if len(owners) != 1:
            return "named"
    if any(keys[k] > 1 for k in KEY.findall(" ".join(map(str, q.get("pieces") or [])))):
        return "answer"
    if ticket_reading(q, inside) is not None:
        return "tickets"
    return None


def _target(q: dict[str, Any], by_id: dict[str, dict]) -> str:
    """What a question is about, for preferring questions about different things: its kind and its documents other than the
    meeting (two action items of one owner are about the same tickets)."""
    return json.dumps([q["kind"], sorted(x for x in q["gold_docs"] if by_id.get(x, {}).get("source") != "fireflies")])


def pick(qs: list[dict[str, Any]], inside: list[dict[str, Any]], n: int = N_QUESTIONS, seed: int = QSEED) -> list[dict[str, Any]]:
    """``n`` questions, the kinds taking turns in name order. Within a kind, a seeded order, with the questions about something
    no earlier question of the kind asked about first."""
    by_id = {d["dsid"]: d for d in inside}
    rng = random.Random(seed)
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for q in sorted(qs, key=lambda q: q["id"]):
        by_kind[q["kind"]].append(q)
    for k in sorted(by_kind):
        rng.shuffle(by_kind[k])
        seen: set[str] = set()
        first, later = [], []
        for q in by_kind[k]:
            t = _target(q, by_id)
            (later if t in seen else first).append(q)
            seen.add(t)
        by_kind[k] = first + later
    chosen: list[dict[str, Any]] = []
    while len(chosen) < n and any(by_kind.values()):
        for k in sorted(by_kind):
            if by_kind[k] and len(chosen) < n:
                chosen.append(by_kind[k].pop(0))
    return chosen


def small_set(qs: list[dict[str, Any]]) -> set[str]:
    """The documents the questions need: the union of their gold documents."""
    return {x for q in qs for x in q["gold_docs"]}


def not_reproduced(docs: list[dict[str, Any]], small: set[str], qs: list[dict[str, Any]], seed: int, wordings: dict) -> list[str]:
    """The questions whose expected answer is not the same when computed within ``small`` (none, when the gold documents hold
    everything the answer rests on). A pair to compare is checked from its two issues; every other question by drawing the
    small set's questions in every wording and field."""
    inside = [d for d in docs if d["dsid"] in small]
    regen: dict[str, list] = defaultdict(list)
    for q in questions(docs, small, True, seed, wordings=wordings, every_field=True, all_wordings=True, max_q=None):
        regen[q["question"]].append(q["expected"])
    due = {k: _iso(d["raw"].get("due_date")) for d in inside if d["source"] == "linear" and (k := _key(d))}
    bad = []
    for q in qs:
        if q["kind"] == "compare_two":
            a, b = KEY.findall(q["question"])[:2]
            ok = due.get(a) and due.get(b) and due[a] != due[b] and q["expected"]["ids"] == [a if due[a] < due[b] else b]
        else:
            ok = q["expected"] in regen.get(q["question"], [])
        if not ok:
            bad.append(q["id"])
    return bad


def _write_set(out: Path, root: Path, dsids: list[str] | set[str], qs: list[dict[str, Any]], index_path: Path, seed: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ids = sorted(dsids)
    (out / "haystack.json").write_text(json.dumps({"root": str(root), "n_docs": len(ids), "seed": seed, "base_questions": 0,
                                                   "documents": len(ids), "dsids": ids}))
    if not (out / "index.json").exists():
        (out / "index.json").symlink_to(index_path.resolve())
    _write_jsonl(out / "questions.jsonl", qs)


def build_sets(index_path: Path, root: Path, exclude_dirs: list[Path], big: Path, small: Path, unclear: Path, wordings_path: Path,
               seed: int = SEED, qseed: int = QSEED, haystack: Path | None = None) -> dict[str, Any]:
    """Draw the set (or take ``haystack``'s documents, for a dry run on a seen set), its questions and the small set; write the
    three folders. Only counts are returned and saved, so drawing prints nothing of the questions."""
    from cie.eval.memory_test import haystack_docs

    index = json.loads(index_path.read_text())["index"]
    sources = root / "generated_data" / "sources"
    load = lambda ids: haystack_docs(sources, index, ids)  # noqa: E731
    if haystack is not None:
        ids = sorted(json.loads((haystack / "haystack.json").read_text())["dsids"])
        info: dict[str, Any] = {"documents": len(ids), "from": str(haystack)}
    else:
        exclude = set().union(*(set(json.loads((d / "haystack.json").read_text())["dsids"]) for d in exclude_dirs))
        ids, info = draw(index, exclude, load, seed=seed)
    docs = load(ids)
    inside = {d["dsid"] for d in docs}
    wordings = load_wordings(wordings_path)
    drawn = questions(docs, inside, True, qseed, wordings=wordings, max_q=None)
    kept, aside = [], []
    for q in drawn:
        why = why_unclear(q, docs)
        if why is None:
            kept.append(q)
        else:
            alt = ticket_reading(q, docs) if why == "tickets" else None
            aside.append({**q, "unclear": why, **({"expected_alt": alt} if alt else {})})
    picked = pick(kept, docs, N_QUESTIONS, qseed)
    sm = small_set(picked)
    bad = not_reproduced(docs, sm, picked, qseed, wordings)
    if bad:  # expected answers that depend on documents outside the small set: neither bank is asked them
        picked = [q for q in picked if q["id"] not in bad]
        sm = small_set(picked)
    aside_picked = pick(aside, docs, N_QUESTIONS, qseed)
    _write_set(big, root, ids, picked, index_path, seed)
    _write_set(small, root, sm, picked, index_path, seed)
    _write_set(unclear, root, ids, aside_picked, index_path, seed)
    count = lambda qs: dict(sorted(Counter(q["kind"] for q in qs).items()))  # noqa: E731
    rep = {**info, "readable": len(docs), "questions_drawn": count(drawn),
           "unclear": {why: count([q for q in aside if q["unclear"] == why]) for why in ("named", "answer", "tickets")},
           "kept": count(kept), "picked": count(picked), "not_reproduced_in_small_set": len(bad), "small_set_documents": len(sm),
           "unclear_asked": count(aside_picked), "jira_documents": sum(1 for d in docs if d["source"] == "jira")}
    (big / "draw_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def _ms(work: Path, name: str) -> dict[str, float] | None:
    p = work / f"{name}.jsonl"
    ms = sorted(r["ms"] for r in _jsonl(p) if r.get("ms") is not None) if p.exists() else []
    if not ms:
        return None
    return {"median": round(statistics.median(ms)), "p90": round(ms[min(len(ms) - 1, int(0.9 * len(ms)))]), "max": round(ms[-1])}


def _lenient(work: Path) -> dict[str, Any]:
    """The set-aside questions scored both ways: strict (the Linear-only answer the questions expect) and lenient (right under
    either reading of "tickets")."""
    qs = _jsonl(work / "questions.jsonl")
    out: dict[str, Any] = {}
    for arm, name in FILES.items():
        p = work / f"{name}.jsonl"
        if not p.exists():
            continue
        ans = {r["id"]: r["answer"] for r in _jsonl(p)}
        strict = [own_score(q, ans.get(q["id"], "")) for q in qs]
        lenient = [max(own_score(q, ans.get(q["id"], "")), own_score({**q, "expected": q["expected_alt"]}, ans.get(q["id"], "")))
                   if q.get("expected_alt") else own_score(q, ans.get(q["id"], "")) for q in qs]
        out[arm] = {"strict": round(sum(strict) / len(strict), 3) if qs else None,
                    "lenient": round(sum(lenient) / len(lenient), 3) if qs else None}
    return {"questions": len(qs), "by_reason": dict(Counter(q.get("unclear") for q in qs)), "scores": out}


def scale_test(big: Path, small: Path, unclear: Path | None = None) -> dict[str, Any]:
    """Part A's rules (docs/FACTBANK_5K_PREREGISTRATION.md) and what is reported with them."""
    mb, ms_ = measure(big), measure(small)
    d = lambda a, b: round(a - b, 3) if a is not None and b is not None else None  # noqa: E731
    mean = lambda m, a, what="direct": (m.get(what, {}).get(a) or {}).get("mean")  # noqa: E731
    rules = {
        "1 nothing lost to size (v13 at 5,000 >= v13 on the small bank - 0.05)": at_least(d(mean(mb, "v13"), mean(ms_, "v13")), LOSS),
        "2 the level holds (v13 at 5,000 >= 0.92)": mean(mb, "v13") is not None and mean(mb, "v13") >= LEVEL,
        "3 the planner's lead holds at 5,000 (v9 - v4 >= +0.10 and v9 - v8 >= +0.05)":
            at_least(d(mean(mb, "v9"), mean(mb, "v4")), 0.10) and at_least(d(mean(mb, "v9"), mean(mb, "v8")), 0.05),
        "4 the same with the small model's form (v14 at 5,000 >= v14 on the small bank - 0.05)":
            at_least(d(mean(mb, "v14"), mean(ms_, "v14")), LOSS),
        "5 right for the right reason (v13 at 5,000 >= v13 on the small bank - 0.05)":
            at_least(d(mean(mb, "v13", "reason"), mean(ms_, "v13", "reason")), LOSS),
    }
    small_rows = {r["id"]: r for r in ms_["rows"]}
    changed = [{"id": r["id"], "kind": r["kind"], **{a: [small_rows[r["id"]]["direct"].get(a), r["direct"].get(a)] for a in ARMS
                                                     if r["direct"].get(a) != small_rows[r["id"]]["direct"].get(a)}}
               for r in mb["rows"] if any(r["direct"].get(a) != small_rows[r["id"]]["direct"].get(a) for a in ARMS)]
    builds = {}
    for w in (big, small):
        for name in ("factbank", "factbank_v2"):
            p = w / f"{name}_build.json"
            if p.exists():
                b = json.loads(p.read_text())
                builds[f"{w.name}/{name}"] = {k: b.get(k) for k in ("seconds", "bytes", "facts", "entities")}
    seed1 = big / "factbank_v13_seed1.jsonl"
    hashseed = None
    if seed1.exists() and (big / "factbank_v13.jsonl").exists():
        a0 = {r["id"]: r["answer"] for r in _jsonl(big / "factbank_v13.jsonl")}
        a1 = {r["id"]: r["answer"] for r in _jsonl(seed1)}
        hashseed = {"questions": len(a0), "different_answers": sorted(q for q in a0 if a1.get(q) != a0[q])}
    rep = {"big": {k: mb[k] for k in ("questions", "by_group", "direct", "reason", "by_kind", "rows")},
           "small": {k: ms_[k] for k in ("questions", "by_group", "direct", "reason", "by_kind", "rows")},
           "differences_5k_minus_small": {a: d(mean(mb, a), mean(ms_, a)) for a in ARMS},
           "changed_questions": changed,
           "time_ms": {a: {"5k": _ms(big, n), "small": _ms(small, n)} for a, n in FILES.items()},
           "builds": builds, "hashseed_check": hashseed,
           "draw": json.loads((big / "draw_report.json").read_text()) if (big / "draw_report.json").exists() else None,
           "unclear": _lenient(unclear) if unclear is not None and (unclear / "questions.jsonl").exists() else None,
           "rules": rules}
    (big / "scale_report.json").write_text(json.dumps(rep, indent=1, default=str))
    (big / "scale_report.md").write_text(to_markdown(rep))
    return rep


def to_markdown(rep: dict[str, Any]) -> str:
    g = ("link", "combine", "compare", "mean")
    out = ["### The fact bank and planner at 5,000 documents", "",
           f"{rep['big']['questions']} questions ({', '.join(f'{k} {v}' for k, v in rep['big']['by_group'].items())}), asked of the "
           "5,000-document bank and of a small bank holding only the documents they need.", "",
           "| arm | bank | " + " | ".join(g) + " | right for the right reason |", "|---|---|" + "---|" * (len(g) + 1)]
    for a in ARMS:
        for label, m in (("small", rep["small"]), ("5,000", rep["big"])):
            r = m["direct"].get(a)
            if r is None:
                continue
            rr = (m["reason"].get(a) or {}).get("mean")
            out.append(f"| {a} | {label} | " + " | ".join("–" if r.get(x) is None else f"{r[x]:.3f}" for x in g)
                       + f" | {'–' if rr is None else f'{rr:.3f}'} |")
    out += ["", "Rules:"] + [f"- {k}: **{'met' if v else 'not met'}**" for k, v in rep["rules"].items()]
    out += ["", f"- differences, 5,000 minus small: {json.dumps(rep['differences_5k_minus_small'])}",
            f"- changed questions: {json.dumps(rep['changed_questions'])}", f"- time per question (ms): {json.dumps(rep['time_ms'])}",
            f"- builds: {json.dumps(rep['builds'])}", f"- hash seed check: {json.dumps(rep['hashseed_check'])}",
            f"- draw: {json.dumps(rep['draw'])}", f"- set-aside questions: {json.dumps(rep['unclear'])}"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.factbank_5k")
    ap.add_argument("cmd", choices=["draw", "score"])
    ap.add_argument("--index")
    ap.add_argument("--root")
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--haystack", default=None, help="draw: take this folder's documents instead of drawing (a dry run on a seen set)")
    ap.add_argument("--big", required=True)
    ap.add_argument("--small", required=True)
    ap.add_argument("--unclear", default=None)
    ap.add_argument("--wordings", default=None)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--qseed", type=int, default=QSEED)
    a = ap.parse_args(argv)
    if a.cmd == "draw":
        rep = build_sets(Path(a.index), Path(a.root), [Path(x) for x in a.exclude], Path(a.big), Path(a.small), Path(a.unclear),
                         Path(a.wordings), a.seed, a.qseed, Path(a.haystack) if a.haystack else None)
    else:
        rep = scale_test(Path(a.big), Path(a.small), Path(a.unclear) if a.unclear else None)
        rep = {"rules": rep["rules"], "differences_5k_minus_small": rep["differences_5k_minus_small"]}
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
