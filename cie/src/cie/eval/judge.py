"""A language-model judge for answers that word matching cannot score (docs/FACTBANK_FIXES.md, section 9).

The 50,000-document test scored free text by the words of the expected facts an answer holds. A reader then found that
score to follow wording and length: the model's free-text answers were right 77 times in 80 and plain search's 76, and
the scores were 0.813 and 0.702. This judge reads the answer instead. For each answer it is given the question, the
reference answer and the reference's facts, and says:

- **facts:** for each fact, whether the answer states it, in any wording (figures, names and dates must agree);
- **correct:** whether the answer agrees with the reference as a whole: it gives what the question asks for and says
  nothing that contradicts the reference. When the reference says the records do not hold the answer, only an answer
  that says so is correct.

``completeness`` is the share of the facts stated. These are the two measures of EnterpriseRAG-Bench's own judge
(``cie.eval.grade_answers`` runs that one, which needs a paid API); this one runs on the model that is already loaded
(any ``reasoner`` backend), so every arm is judged by the same judge.

**A judge is only as good as its agreement with people.** ``sample`` writes answers for a person to label, and
``agreement`` compares the judge with those labels (accuracy and Cohen's kappa). Until that is done on a few hundred
answers, the judge's numbers are a second measure beside the word-matching score, not a replacement.

    python -m cie.eval.judge sample --answers A.jsonl --questions Q.jsonl --n 100 --out labels.csv
    python -m cie.eval.judge agreement --labels labels.csv --verdicts verdicts.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

ANSWER_CHARS = 3000  # of the answer (and its quotes) the judge reads
NOT_FOUND = "not found"

SYSTEM = """You grade an answer to a question about one company's internal records. You are given the question, a \
reference answer that is known to be right, the facts of the reference, and the answer to grade.

Reply with exactly one JSON object and nothing else:
  {"facts": [true, false], "correct": true}

- "facts": one true or false for each fact of the reference, in order: true when the answer states that fact. The wording \
may differ; figures, names, dates and identifiers must agree with the fact. A fact the answer only hints at, or states \
with another value, is false.
- "correct": true when the answer agrees with the reference as a whole: it gives what the question asks for and nothing \
in it contradicts the reference. Extra detail that is not wrong does not matter. An answer that leaves out the main \
point, answers another question, or gives a wrong figure, name or date is false.
- When the reference says the records do not hold the answer, "correct" is true only for an answer that says so ("not \
found", or that the records do not say); an answer that gives something else is false.
- An answer that is only "not found" when the reference has an answer is false, and so is every fact.
Grade what the answer says, not how well it is written."""

USER = """Question: {question}

Reference answer: {gold}

Facts of the reference:
{facts}

Answer to grade:
{answer}"""
AGAIN = 'Reply with exactly one JSON object: {"facts": [true or false for each fact, in order], "correct": true or false}.'


def conversation(item: dict[str, Any]) -> list[dict[str, str]]:
    """The judge's one turn for an item {question, gold, facts, answer}."""
    facts = "\n".join(f"{n}. {f}" for n, f in enumerate(item.get("facts") or [], 1)) or "(none listed)"
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(question=item["question"], gold=item.get("gold") or "(see the facts)", facts=facts,
                                                    answer=str(item.get("answer") or "")[:ANSWER_CHARS] or "(no answer)")}]


def _visible(text: str) -> str:
    from cie.factbank.reasoner import visible

    return visible(text)


def parse_verdict(text: str, n_facts: int) -> dict[str, Any] | None:
    """{facts, correct} from the judge's reply: its last JSON object that has "correct"; None when it has none, or the
    facts are not one per fact of the reference."""
    from cie.factbank.reasoner import _objects

    for blob in reversed(_objects(_visible(text))):
        try:
            obj = json.loads(blob, strict=False)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or "correct" not in obj:
            continue
        facts = obj.get("facts")
        if not isinstance(facts, list):
            facts = []
        facts = [bool(x) if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1") for x in facts]
        if len(facts) != n_facts:
            return None
        c = obj["correct"]
        return {"facts": facts, "correct": bool(c) if isinstance(c, bool) else str(c).strip().lower() in ("true", "yes", "1")}
    return None


def judge(items: list[dict[str, Any]], generate: Callable[[list[list[dict[str, str]]]], list[dict[str, Any]]],
          log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """One verdict per item, in order: {id, arm, correct, facts, completeness, failed}. A reply that cannot be read is
    asked for once more; an item with no verdict after that is ``failed`` (correct and completeness None), never
    counted as wrong."""
    convs = [conversation(x) for x in items]
    outs = generate(convs) if convs else []
    verdicts = [parse_verdict(o.get("text") or "", len(x.get("facts") or [])) for o, x in zip(outs, items, strict=True)]
    again = [i for i, v in enumerate(verdicts) if v is None]
    if again:
        more = generate([[*convs[i], {"role": "assistant", "content": _visible(outs[i].get("text") or "")[:1000] or "(no reply)"},
                          {"role": "user", "content": AGAIN}] for i in again])
        for i, o in zip(again, more, strict=True):
            verdicts[i] = parse_verdict(o.get("text") or "", len(items[i].get("facts") or []))
    out = []
    for x, v in zip(items, verdicts, strict=True):
        row = {k: x[k] for k in ("id", "arm") if k in x}
        if v is None:
            out.append({**row, "correct": None, "facts": None, "completeness": None, "failed": True})
        else:
            n = len(v["facts"])
            out.append({**row, "correct": v["correct"], "facts": v["facts"],
                        "completeness": round(sum(v["facts"]) / n, 4) if n else (1.0 if v["correct"] else 0.0), "failed": False})
    failed = sum(v["failed"] for v in out)
    log(f"  judged {len(out)} answers ({len(again)} asked twice, {failed} without a verdict)")
    return out


def summarise(verdicts: list[dict[str, Any]], by: dict[str, str] | None = None) -> dict[str, Any]:
    """Correctness and completeness over the verdicts that were given (``failed`` ones counted apart), in all and for each
    group of ``by`` (an id's group: its question type)."""
    def one(vs: list[dict[str, Any]]) -> dict[str, Any]:
        ok = [v for v in vs if not v["failed"]]
        return {"answers": len(vs), "failed": len(vs) - len(ok),
                "correct": round(sum(v["correct"] for v in ok) / len(ok), 3) if ok else None,
                "completeness": round(sum(v["completeness"] for v in ok) / len(ok), 3) if ok else None}

    out = {"all": one(verdicts)}
    if by:
        groups: dict[str, list] = defaultdict(list)
        for v in verdicts:
            groups[by.get(v["id"], "?")].append(v)
        out["by_group"] = {g: one(vs) for g, vs in sorted(groups.items())}
    return out


# ------------------------------------------------------------------ people's labels
FIELDS = ("id", "arm", "question", "reference", "facts", "answer", "correct (yes/no)", "notes")


def sample(items: list[dict[str, Any]], n: int, seed: int = 0) -> list[dict[str, str]]:
    """``n`` items drawn evenly over the arms, as rows for a person to label: the question, the reference, its facts and
    the answer, with an empty "correct (yes/no)" column. The arm is in the file; hide that column while labelling."""
    rng = random.Random(seed)
    by_arm: dict[str, list] = defaultdict(list)
    for x in items:
        by_arm[str(x.get("arm", ""))].append(x)
    picked: list[dict[str, Any]] = []
    arms = sorted(by_arm)
    for a in arms:
        rng.shuffle(by_arm[a])
    i = 0
    while len(picked) < n and any(by_arm.values()):
        a = arms[i % len(arms)]
        if by_arm[a]:
            picked.append(by_arm[a].pop())
        i += 1
    rng.shuffle(picked)
    return [{"id": str(x["id"]), "arm": str(x.get("arm", "")), "question": x["question"], "reference": str(x.get("gold") or ""),
             "facts": " | ".join(x.get("facts") or []), "answer": str(x.get("answer") or "")[:ANSWER_CHARS], "correct (yes/no)": "", "notes": ""}
            for x in picked]


def agreement(labels: list[dict[str, str]], verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """The judge against people's labels on the answers both judged: how often they agree, Cohen's kappa (agreement
    beyond chance), and the four counts. A label is yes/no (or true/false, 1/0); rows without one are left out."""
    by = {(str(v["id"]), str(v.get("arm", ""))): v for v in verdicts if not v.get("failed")}
    pairs = []
    for row in labels:
        raw = str(row.get("correct (yes/no)") or row.get("correct") or "").strip().lower()
        if raw not in ("yes", "no", "true", "false", "1", "0", "y", "n"):
            continue
        v = by.get((str(row["id"]), str(row.get("arm", ""))))
        if v is not None:
            pairs.append((raw in ("yes", "true", "1", "y"), bool(v["correct"])))
    n = len(pairs)
    if not n:
        return {"answers": 0}
    both = sum(h and j for h, j in pairs)
    neither = sum(not h and not j for h, j in pairs)
    human, judged = sum(h for h, _ in pairs) / n, sum(j for _, j in pairs) / n
    agree = (both + neither) / n
    chance = human * judged + (1 - human) * (1 - judged)
    return {"answers": n, "agree": round(agree, 3), "kappa": round((agree - chance) / (1 - chance), 3) if chance < 1 else None,
            "both_right": both, "both_wrong": neither, "judge_right_person_wrong": sum(j and not h for h, j in pairs),
            "judge_wrong_person_right": sum(h and not j for h, j in pairs)}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().split("\n") if x.strip()]


def items_of(questions: list[dict[str, Any]], answers: dict[str, dict[str, Any]], arm: str,
             text: Callable[[dict[str, Any], dict[str, Any]], str] | None = None) -> list[dict[str, Any]]:
    """The judge's items for an arm's answers: every question that has a reference (``expected.gold`` or
    ``expected.facts``) and an answer. ``text``: what of the row is judged (the answer with its quotes by default)."""
    out = []
    for q in questions:
        e, row = q.get("expected") or {}, answers.get(q["id"])
        none = e.get("not_found") or e.get("unanswerable")  # the generated questions' word for it, and the benchmark's
        if row is None or not (e.get("gold") or e.get("facts") or none):
            continue
        gold = e.get("gold") or ("The records do not hold the answer: not found." if none else "")
        answer = text(q, row) if text else "\n".join(str(x) for x in (row.get("answer"), row.get("support")) if x)
        out.append({"id": q["id"], "arm": arm, "question": q["question"], "gold": gold, "facts": list(e.get("facts") or []),
                    "answer": re.sub(r"\n{3,}", "\n\n", answer)})
    return out


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.judge", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="answers for a person to label, as a CSV file")
    s.add_argument("--questions", type=Path, required=True)
    s.add_argument("--answers", type=Path, nargs="+", required=True, help="answer files; an arm is a file's name")
    s.add_argument("--n", type=int, default=100)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("agreement", help="the judge against a person's labels")
    a.add_argument("--labels", type=Path, required=True)
    a.add_argument("--verdicts", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "sample":
        qs = _jsonl(args.questions)
        items = [x for f in args.answers for x in items_of(qs, {r["id"]: r for r in _jsonl(f)}, f.name.removesuffix(".jsonl"))]
        rows = sample(items, args.n, args.seed)
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} answers to label in {args.out}")
        return rows
    with open(args.labels, newline="") as f:
        labels = list(csv.DictReader(f))
    rep = agreement(labels, _jsonl(args.verdicts))
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
