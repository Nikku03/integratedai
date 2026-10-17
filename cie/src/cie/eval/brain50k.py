"""The company brain at 50,000 documents, with and without a large language model as its reasoning engine
(docs/FACTBANK_50K_PLAN.md).

- **draw:** the 50,000-document haystack is round 4's 5,000 test documents (``docs/benchmarks/brain4/test/test5k``) and
  45,000 more of the benchmark, every source in its share of what is left (``grow``). Left out of the 45,000: round 4's
  held-out documents (their questions must stay unanswerable), and any document that would give a round-4 question a
  second right answer by name: a ticket key or pull request number already drawn, and a document that links a ticket of
  the 5,000. The draw does not read the questions' answers.
- **questions:** two parts, in two folders that share one bank (``write_questions``): W holds the generators' wordings,
  W_messy the rewriters' (which decide, as in round 4).
  (a) round 4's 587 questions, each kept only if its expected answer still holds among 50,000 documents
  (``still_holds``); a count or list whose filters now hold more documents is counted again there, and the rest that
  changed are set aside with their reason;
  (b) the complex questions (``cie.eval.complex_questions``): two to four steps over two or more documents, with a
  checkable answer, drawn from the 50,000 documents.
- **ask:** the arms. v18 is the brain with no model (``cie.factbank.brain``), asked in parallel processes; "rag" is the
  model alone, given the passages a keyword search finds (search, then a model: the usual AI search); "reasoner" is the
  model as the brain's reasoning engine (``cie.factbank.reasoner``), which reads the brain's answer and can ask it more,
  search, read documents and count before it answers. Answers are appended as they come, so a stopped run goes on.
- **score:** every arm scored as round 4 scores it (``brain2_test.score_one``; the complex questions by
  ``complex_questions.score``), per family, with the complex family by kind and by steps, the paired differences of the
  arms, and the plan's rules (``rules``) on the messy folder.

    python -m cie.eval.brain50k draw --index INDEX --root BENCH --out W
    python -m cie.eval.brain50k questions --work W
    python -m cie.eval.brain50k ask --arm v18 --work W_messy W --workers 10
    python -m cie.eval.brain50k ask --arm reasoner --work W_messy --model qwen3.8-27b --workers 10
    python -m cie.eval.brain50k score --messy W_messy --tidy W
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from cie.eval import factbank_5k
from cie.eval.factbank_multi import KEY, _keys

N_DOCS = 50_000
SEED = 5050  # the draw
QSEED = 5051  # the complex questions
LINKED = ("linear", "jira", "github")
BASE = Path("docs/benchmarks/brain4/test/test5k")  # round 4's tidy folder: its haystack.json and questions.jsonl
BASE_MESSY = Path("docs/benchmarks/brain4/test/test5k_messy")  # the same questions in the rewriters' wordings


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dsids_sha(ids: Iterable[str]) -> str:
    """A fingerprint of a haystack's documents that does not depend on where the benchmark is on disk."""
    return hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()


def links(d: dict[str, Any]) -> set[str]:
    """The ticket keys a document links: the fields the bank follows both ways and a pull request's linked Linear issues."""
    out = factbank_5k._refs(d)
    if d["source"] == "github":
        out |= set(_keys(d["raw"].get("linked_linear")))
    return out


def grow(index: dict[str, str], base: list[str], exclude: set[str], load: Callable[[list[str]], list[dict[str, Any]]],
         n: int = N_DOCS, seed: int = SEED) -> tuple[list[str], dict[str, Any]]:
    """``base`` and ``n - len(base)`` more documents, every source in its share of what is left after ``base`` and
    ``exclude``, by ``factbank_5k.draw``'s rules (one document per ticket key and pull request number), and none that links
    a ticket of ``base`` or whose ticket ``base`` links: a question about the base documents keeps its one right answer by
    name. ``load(dsids)`` reads documents as ``memory_test.haystack_docs`` does; only tracker and GitHub documents are read."""
    taken = set(base)
    if len(taken) != len(base):
        raise ValueError("the base set repeats a document")
    if missing := taken - set(index):
        raise ValueError(f"the index lacks {len(missing)} base documents")
    more = n - len(base)
    if more < 0:
        raise ValueError(f"the base set already holds {len(base)} documents, more than {n}")
    by_src = factbank_5k.remaining(index, taken | set(exclude))
    total = sum(len(v) for v in by_src.values())
    target = {s: round(more * len(v) / total) for s, v in by_src.items()}
    target[max(target, key=lambda s: (target[s], s))] += more - sum(target.values())
    base_linked = [d for d in load([x for x in sorted(base) if index[x].split("/")[0] in LINKED])]
    keys = {k for d in base_linked if (k := factbank_5k._key(d))}
    prs = {p for d in base_linked if (p := factbank_5k._pr(d))}
    base_keys = set(keys)
    base_links = set().union(*(links(d) for d in base_linked)) if base_linked else set()
    linked = {d["dsid"]: d for d in load([x for s in LINKED for x in by_src.get(s, [])])}
    rng = random.Random(seed)
    chosen: list[str] = []
    have: Counter = Counter()
    skipped: Counter = Counter()
    for s in sorted(by_src):
        pool = list(by_src[s])
        rng.shuffle(pool)
        for dsid in pool:
            if have[s] >= target[s]:
                break
            if s in LINKED:
                d = linked.get(dsid)
                if d is None:
                    skipped["unreadable"] += 1
                    continue
                k, p = factbank_5k._key(d), factbank_5k._pr(d)
                if k and not KEY.fullmatch(k):
                    skipped["key not a plain ticket key"] += 1
                    continue
                if k and k in keys:
                    skipped["ticket key already drawn"] += 1
                    continue
                if p and p in prs:
                    skipped["pull request number already drawn"] += 1
                    continue
                if links(d) & base_keys:
                    skipped["links a ticket of the base set"] += 1
                    continue
                if k and k in base_links:
                    skipped["a ticket the base set links"] += 1
                    continue
                if k:
                    keys.add(k)
                if p:
                    prs.add(p)
            chosen.append(dsid)
            have[s] += 1
    short = {s: target[s] - have[s] for s in target if have[s] < target[s]}
    ids = sorted(taken | set(chosen))
    info = {"documents": len(ids), "base": len(base), "added": len(chosen), "targets": dict(sorted(target.items())),
            "added_by_source": dict(sorted(have.items())), "short": short, "skipped": dict(skipped), "excluded": len(exclude),
            "remaining": total, "seed": seed}
    return ids, info


def heldout_docs(questions: Iterable[dict[str, Any]]) -> set[str]:
    """The held-out documents of a question set: each held-out question's answer is in one, outside the haystack."""
    return {q["heldout_doc"] for q in questions if q.get("heldout_doc")}


def write_draw(base: Path, questions: Path, index_path: Path, root: Path, out: Path, n: int = N_DOCS, seed: int = SEED,
               load: Callable[[list[str]], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """The 50,000-document folder: ``out``/haystack.json (``brain_draw.write_draw``'s format: root, dsids), the folder index
    linked as ``out``/index.json, and ``out``/draw_report.json. The held-out documents of ``questions`` stay out."""
    from cie.eval import brain_draw

    index = brain_draw.load_folder_index(index_path, root)
    base_ids = sorted(json.loads((base / "haystack.json").read_text())["dsids"])
    qs = [json.loads(line) for line in questions.read_text().splitlines() if line.strip()]
    held = heldout_docs(qs)
    if inside := held & set(base_ids):
        raise ValueError(f"{len(inside)} held-out documents are in the base set")
    ids, info = grow(index, base_ids, held, load or brain_draw._loader(root, index), n=n, seed=seed)
    out.mkdir(parents=True, exist_ok=True)
    hay = out / "haystack.json"
    hay.write_text(json.dumps({"root": str(root), "n_docs": len(ids), "seed": seed, "base_questions": 0, "documents": len(ids),
                               "base": str(base), "index": str(index_path), "dsids": ids}))
    link = out / "index.json"
    if not (link.exists() or link.is_symlink()):
        link.symlink_to(index_path.resolve())
    rep = {**info, "n": n, "heldout_left_out": len(held), "dsids_sha256": dsids_sha(ids), "base_haystack_sha256": _sha(base / "haystack.json"),
           "questions_sha256": _sha(questions), "by_source": brain_draw._by_source(index, ids), "index": str(index_path),
           "haystack_sha256": _sha(hay)}
    (out / "draw_report.json").write_text(json.dumps(rep, indent=1))
    return rep


# ------------------------------------------------------------------ questions
R4_SEED = 1020  # round 4's question seed: its generated questions are drawn again with it to check them at 50,000


def _recount_hits(q: dict[str, Any], docs: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The documents a count or filter question's filters hold among ``docs``, read as ``brain2_test._recount`` reads them;
    None for any other question."""
    from cie.eval import brain2_questions as Q2
    from cie.eval import brain_questions as B

    filters = q.get("filters")
    if not filters or not (q["kind"].startswith(("count1_", "count2_")) or q["kind"] in ("count_gmail", "filter_list")):
        return None
    if q["kind"] == "count_gmail":
        src = "gmail"
    elif q["kind"] == "filter_list":
        by_id = {d["dsid"]: d for d in docs}
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

    return [d for d in docs if d["source"] == src and all(holds(d, f, v) for f, v in filters)]


def recount(q: dict[str, Any], docs: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """A count or filter question with its expected answer counted again among ``docs`` (its count, or its keys, and its gold
    documents), or None and why not: no documents hold the filters, or a list grew past ``brain2_questions.FILTER_MAX``."""
    from cie.eval import brain2_questions as Q2

    hits = _recount_hits(q, docs)
    if hits is None:
        return None, "not a count"
    if not hits:
        return None, "no documents hold the filters"
    if "ids" in q["expected"]:
        keys = sorted(k for d in hits if (k := factbank_5k._key(d)))
        if len(keys) > Q2.FILTER_MAX or len(keys) != len(hits):
            return None, "the list grew too long"
        return {**q, "expected": {**q["expected"], "ids": keys}, "gold_docs": sorted(d["dsid"] for d in hits), "recounted": True}, ""
    return {**q, "expected": {**q["expected"], "value": str(len(hits))}, "gold_docs": sorted(d["dsid"] for d in hits),
            "recounted": True}, ""


def heldout_holds(q: dict[str, Any], held: dict[str, Any], text: str, titles: dict[str, list[set[str]]], overlap: float,
                  hay4: Any) -> str | None:
    """Why a held-out question no longer holds among the 50,000 documents, or None: ``brain2_draw.heldout``'s checks (1) to
    (3) on its held-out document and ``brain2_draw.collect``'s check (4) on its answer facts, run against them."""
    from cie.eval import brain2_draw as D

    anc = D.anchors(held)
    if any(D.is_written(text, a["text"]) for a in anc if a["kind"] != "person"):
        return "anchor written in the haystack"
    tw = D.title_words(held["title"])
    if max((D.jaccard(tw, t) for t in titles.get(held["source"], [])), default=0.0) >= D.TITLE_JACCARD:
        return f"title Jaccard >= {D.TITLE_JACCARD}"
    if overlap >= D.SHINGLE_MAX:
        return f"shingle overlap >= {D.SHINGLE_MAX}"
    words, _ = hay4.check_words(anc)
    if not words:
        return D.UNTESTED
    if hay4.holder(q.get("answer_facts") or q.get("pieces") or [], anc) is not None:
        return D.FOUND
    return None


def still_holds(docs: list[dict[str, Any]], qs: list[dict[str, Any]], sources: Path, index: dict[str, str], seed: int = R4_SEED,
                log: Callable[[str], None] = print) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    """Round 4's questions that still have their one right answer among ``docs``: the kept questions (a recounted count or
    list with its new answer), the reasons the others were set aside by id, and a report.

    - generated questions: drawn again among ``docs`` with round 4's seed, the question about the same documents and name
      has the same answer (``brain_test.not_reproduced``, ``brain2_test.not_reproduced2``, which read the haystack as a set);
      a count or list that differs is counted again (``recount``);
    - questions about a document the company does not have: the name is still written nowhere (the same functions);
    - the writers' free-text and descriptive questions: ``brain_test.why_aside`` again (a title they quote names one
      document, a key one document);
    - held-out questions: their document is still outside, and checks (1) to (4) still pass (``heldout_holds``)."""
    from cie.eval import brain2_draw as D
    from cie.eval import brain2_test as T2
    from cie.eval import brain_questions as B
    from cie.eval import brain_test as H

    ids = {d["dsid"] for d in docs}
    v15 = [q for q in qs if T2.part(q) == "v15" and q["kind"] not in ("prose", "descriptive")]
    v16 = [q for q in qs if T2.part(q) == "v16"]
    log(f"  generated questions drawn again among {len(docs):,} documents: {len(v15)} of round 1's kinds, {len(v16)} of round 2's")
    bad = {**H.not_reproduced(docs, ids, v15, seed), **T2.not_reproduced2(docs, ids, v16, seed)}
    titles = B._names(docs)["titles"]
    for q in qs:
        if q["kind"] in ("prose", "descriptive") and (w := H.why_aside(q, docs, ids, titles)):
            bad[q["id"]] = w
    held_qs = [q for q in qs if q.get("kind") == T2.HELDOUT]
    if held_qs:
        log(f"  held-out questions: checks (1) to (4) against {len(docs):,} documents")
        held_docs = {d["dsid"]: d for d in D.read_docs(sources, index, sorted({q["heldout_doc"] for q in held_qs}))}
        full = D.read_docs(sources, index, sorted(ids))
        text = D.written_text(full)
        by_src: dict[str, list[set[str]]] = defaultdict(list)
        for x in full:
            by_src[x["source"]].append(D.title_words(x["title"]))
        order = sorted(held_docs)
        overlap = dict(zip(order, D.shingle_overlap([D.shingles(held_docs[h]["doc"].body) for h in order], (x["doc"].body for x in full)),
                           strict=True))
        hay4 = D.Haystack(full)
        del full
        for q in held_qs:
            h = q["heldout_doc"]
            if h in ids:
                bad[q["id"]] = "held-out document in the haystack"
            elif h not in held_docs:
                bad[q["id"]] = "held-out document unreadable"
            elif w := heldout_holds(q, held_docs[h], text, by_src, overlap[h], hay4):
                bad[q["id"]] = w
    kept, aside, changed = [], {}, {}
    for q in qs:
        if q["id"] not in bad:
            kept.append(q)
            continue
        new, why = recount(q, docs)
        if new is not None:
            kept.append(new)
            changed[q["id"]] = {"was": q["expected"], "now": new["expected"]}
        else:
            aside[q["id"]] = bad[q["id"]] if why == "not a count" else f"{bad[q['id']]}; {why}"
    by_family_kept = Counter(q["family"] for q in kept)
    rep = {"questions": len(qs), "kept": len(kept), "recounted": len(changed), "set_aside": len(aside),
           "kept_by_family": dict(sorted(by_family_kept.items())),
           "set_aside_by_family": dict(sorted(Counter(next(q["family"] for q in qs if q["id"] == i) for i in aside).items())),
           "set_aside_reasons": dict(Counter(aside.values()).most_common())}
    return kept, aside, rep | {"changed": changed}


def write_questions(work: Path, tidy: Path = BASE / "questions.jsonl", messy: Path = BASE_MESSY / "questions.jsonl",
                    per_kind: int | None = None, complex_seed: int = QSEED, log: Callable[[str], None] = print) -> dict[str, Any]:
    """The 50,000-document questions: round 4's that still hold (``still_holds``) and the complex ones
    (``complex_questions.draw``), in two folders sharing one bank: ``work`` (round 4's questions in the generators' wordings)
    and ``work``_messy (in the rewriters' wordings, as round 4's decided set). Each holds questions.jsonl, set_aside.json
    and questions_report.json; the messy folder links the tidy one's haystack, index and banks."""
    import os

    from cie.eval import brain_test as H
    from cie.eval import complex_questions as C

    hay = json.loads((work / "haystack.json").read_text())
    index = json.loads((work / "index.json").read_text())["index"]
    sources = Path(hay["root"]) / "generated_data" / "sources"
    log(f"  reading {len(hay['dsids']):,} documents")
    docs = H.load_docs(work)
    tidy_qs = [json.loads(line) for line in tidy.read_text().splitlines() if line.strip()]
    messy_qs = {q["id"]: q for q in (json.loads(line) for line in messy.read_text().splitlines() if line.strip())}
    kept, aside, rep = still_holds(docs, tidy_qs, sources, index, log=log)
    log(f"  round 4's questions: {rep['kept']} of {rep['questions']} still hold ({rep['recounted']} counted again)")
    cq, crep = C.draw(docs, per_kind or C.PER_KIND, complex_seed)
    log(f"  complex questions: {crep['questions']} ({crep['drawn']})")
    messy_dir = work.parent / f"{work.name}_messy"
    messy_dir.mkdir(exist_ok=True)
    for n in ("haystack.json", "index.json", "factbank_v2.sqlite", "banks.json", "draw_report.json"):
        if (work / n).exists() and not (messy_dir / n).exists():
            os.symlink((work / n).resolve(), messy_dir / n)
    reworded = [{**q, "question": messy_qs[q["id"]]["question"]} for q in kept if q["id"] in messy_qs]
    out = {}
    for folder, qs in ((work, kept + cq), (messy_dir, reworded + cq)):
        (folder / "questions.jsonl").write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in qs))
        (folder / "set_aside.json").write_text(json.dumps(aside, indent=1))
        r = {"round4": {k: v for k, v in rep.items() if k != "changed"}, "complex": crep, "questions": len(qs),
             "by_family": dict(sorted(Counter(q["family"] for q in qs).items())), "tidy_sha256": _sha(tidy), "messy_sha256": _sha(messy),
             "not_reworded": len(kept) - len(reworded) if folder == messy_dir else 0}
        (folder / "questions_report.json").write_text(json.dumps(r | {"changed": rep["changed"]}, indent=1))
        out[str(folder)] = r
    return out


# ------------------------------------------------------------------ ask
LESSONS = Path("docs/benchmarks/brain2/lessons")  # the lessons v18 was frozen with (round 4)
FILES = {"v18": "factbank_v18", "rag": "rag", "reasoner": "reasoner"}
_BRAIN: Any = None


def _init_brain(bank: str, single: str, plans: str, router: str) -> None:
    global _BRAIN
    from cie.factbank.brain import Brain, Router

    _BRAIN = Brain(bank, single, plans, Router.load(router), v16=True, v17=True, v18=True)


def _ask_one(q: dict[str, Any]) -> dict[str, Any]:
    r = _BRAIN.ask(q["question"])
    return {"id": q["id"], **{k: r[k] for k in ("answer", "route", "reason", "evidence", "ms", "reads", "journal", "family_scores")}}


def _rows(path: Path) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in (json.loads(line) for line in path.read_text().splitlines() if line.strip())} if path.exists() else {}


def _questions(work: Path, limit: int | None = None) -> list[dict[str, Any]]:
    qs = [json.loads(line) for line in (work / "questions.jsonl").read_text().splitlines() if line.strip()]
    return qs[: limit or None]


def _finish(work: Path, name: str, qs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The answers file in question order, each question once (the last answer written wins)."""
    have = _rows(work / f"{name}.jsonl")
    (work / f"{name}.jsonl").write_text("".join(json.dumps(have[q["id"]], ensure_ascii=False) + "\n" for q in qs if q["id"] in have))
    return have


def record(work: Path, label: str, info: dict[str, Any]) -> None:
    """What an arm ran with, in ``work``/arms50k.json: its settings, the questions' sha256 and the hash seed."""
    import os

    f = work / "arms50k.json"
    reg = json.loads(f.read_text()) if f.exists() else {}
    reg[label] = {**info, "questions_sha256": _sha(work / "questions.jsonl"), "pythonhashseed": os.environ.get("PYTHONHASHSEED")}
    f.write_text(json.dumps(reg, indent=1))


def ask_v18(work: Path, workers: int = 4, lessons: Path = LESSONS, limit: int | None = None, name: str = "factbank_v18",
            log: Callable[[str], None] = print) -> dict[str, Any]:
    """v18's answers, from ``workers`` processes with a brain each (``Brain(..., v18=True)``, round 4's lessons), appended to
    ``work``/<name>.jsonl as they come: a run stopped half way goes on from the questions not yet answered."""
    import multiprocessing as mp
    import time

    qs = _questions(work, limit)
    done = _rows(work / f"{name}.jsonl")
    todo = [q for q in qs if q["id"] not in done]
    log(f"  {len(qs)} questions, {len(done)} answered before, {len(todo)} to ask in {workers} processes")
    t = time.time()
    args = (str(work / "factbank_v2.sqlite"), str(lessons / "single_lessons.json"), str(lessons / "plan_lessons.json"),
            str(lessons / "router.json"))
    if todo:
        with mp.get_context("fork").Pool(workers, initializer=_init_brain, initargs=args) as pool, open(work / f"{name}.jsonl", "a") as f:
            for i, row in enumerate(pool.imap_unordered(_ask_one, todo, chunksize=1), 1):
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                if i % 100 == 0:
                    log(f"  {i} of {len(todo)} in {time.time() - t:.0f} s")
    have = _finish(work, name, qs)
    ms = sorted(have[q["id"]]["ms"] for q in qs if q["id"] in have)
    rep = {"questions": len(have), "seconds": round(time.time() - t, 1), "workers": workers,
           "median_ms": ms[len(ms) // 2] if ms else None, "mean_ms": round(sum(ms) / len(ms), 1) if ms else None,
           "routes": dict(Counter(r["route"] for r in have.values()))}
    record(work, "v18", {"file": f"{name}.jsonl", "lessons": str(lessons), **{k: rep[k] for k in ("seconds", "workers", "median_ms")}})
    return rep


def backend(model: str, base_url: str | None = None, **kw: Any) -> Any:
    """The model: vLLM's offline engine on this machine's GPU, or an OpenAI-compatible endpoint when ``base_url`` is given."""
    from cie.factbank import reasoner as R

    if base_url:
        return R.OpenAIBackend(model, base_url, max_tokens=kw.get("max_tokens", 6144), concurrency=kw.get("concurrency", 8))
    return R.VLLMBackend(model, **{k: v for k, v in kw.items() if k in ("max_model_len", "gpu_mem", "max_tokens", "max_num_seqs", "effort",
                                                                         "thinking")})


def ask_llm(works: list[Path], arm: str, generate: Any, tools: Any = None, name: str | None = None, chunk: int = 256,
            limit: int | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """The model's arms over each folder of ``works``: "rag" (plain search, one turn) or "reasoner" (the brain's reasoning
    engine, from v18's answers in the folder), ``chunk`` questions at a time, each chunk appended to ``work``/<name>.jsonl
    when it is done: a run stopped half way goes on from the next chunk."""
    import time

    from cie.factbank import reasoner as R

    name = name or FILES[arm]
    out = {}
    for work in works:
        qs = _questions(work, limit)
        done = _rows(work / f"{name}.jsonl")
        todo = [q for q in qs if q["id"] not in done]
        log(f"{work.name}: {len(qs)} questions, {len(done)} answered before, {len(todo)} to ask ({arm})")
        t = time.time()
        stats: Counter = Counter()
        if arm == "rag":
            ps = None
            for i in range(0, len(todo), chunk):
                part = todo[i: i + chunk]
                if ps is None:
                    from cie.eval.brain_test import Passages

                    ps = Passages(work)
                    log(f"  passages: {len(ps.rows):,} of {ps.documents:,} documents in {ps.seconds:.0f} s")
                hits = {q["id"]: ps.search(q["question"], 60)[: R.RAG_PASSAGES] for q in part}
                outs = generate([R.rag_conversation(q["question"], hits[q["id"]]) for q in part])
                with open(work / f"{name}.jsonl", "a") as f:
                    for q, o in zip(part, outs, strict=True):
                        row = {"id": q["id"], "answer": R.rag_answer(o.get("text") or ""), "route": "rag",
                               "docs": list(dict.fromkeys(h["dsid"] for h in hits[q["id"]])), "prompt_tokens": o.get("prompt_tokens", 0),
                               "output_tokens": o.get("output_tokens", 0), "finish": o.get("finish_reason")}
                        stats["output_tokens"] += row["output_tokens"]
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                log(f"  {min(i + chunk, len(todo))} of {len(todo)} in {time.time() - t:.0f} s")
        else:
            brain_rows = _rows(work / f"{FILES['v18']}.jsonl")
            if missing := [q["id"] for q in todo if q["id"] not in brain_rows]:
                raise SystemExit(f"{len(missing)} questions of {work} have no v18 answer: ask v18 first")
            for i in range(0, len(todo), chunk):
                part = todo[i: i + chunk]
                rows = R.reason(part, brain_rows, generate, tools, log=log)
                with open(work / f"{name}.jsonl", "a") as f:
                    for row in rows:
                        stats["output_tokens"] += row["output_tokens"]
                        stats["tool_calls"] += sum(1 for s in row["steps"] if "tool" in s)
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                log(f"  {min(i + chunk, len(todo))} of {len(todo)} in {time.time() - t:.0f} s")
        have = _finish(work, name, qs)
        out[str(work)] = {"questions": len(have), "seconds": round(time.time() - t, 1), **stats}
        record(work, arm if name == FILES[arm] else name, {"arm": arm, "file": f"{name}.jsonl", "model": getattr(generate, "repo", None),
                                                         "seconds": out[str(work)]["seconds"], **stats})
    return out


# ------------------------------------------------------------------ score
def score_one(q: dict[str, Any], row: dict[str, Any]) -> float | None:
    """A complex question by ``complex_questions.score``; every other as round 4 scores it (``brain2_test.score_one``),
    without citation markers."""
    from cie.eval import brain2_test as T2
    from cie.eval import brain_test as H
    from cie.eval import complex_questions as C

    row = {**row, "answer": H.plain_answer(row.get("answer"))}
    return C.score(q, row) if q.get("family") == C.FAMILY else T2.score_one(q, row)


def _mean(xs: Iterable[float]) -> float | None:
    xs = list(xs)
    return round(sum(xs) / len(xs), 3) if xs else None


def _paired(rows: list[dict[str, Any]], labs: list[str], fams: list[str]) -> dict[str, Any]:
    """Each pair of arms' paired difference per family and over all: the mean, its 95% bootstrap interval
    (``memory_test.paired_ci``) and how many questions got better and worse, over the questions both scored."""
    from cie.eval.memory_test import paired_ci

    out = {}
    for i, a in enumerate(labs):
        for b in labs[i + 1:]:
            d = {}
            for f in [*fams, "all"]:
                sel = [r for r in rows if (f == "all" or r["family"] == f) and r["score"].get(a) is not None and r["score"].get(b) is not None]
                x, y = [r["score"][a] for r in sel], [r["score"][b] for r in sel]
                if sel:
                    d[f] = {"questions": len(sel), "mean": round(sum(x) / len(x) - sum(y) / len(y), 3), "interval_95": paired_ci(x, y),
                            "better": sum(p > q for p, q in zip(x, y, strict=True)), "worse": sum(p < q for p, q in zip(x, y, strict=True))}
            out[f"{a} - {b}"] = d
    return out


def score_folder(work: Path, labels: Iterable[str] = ("reasoner", "rag", "v18"), extra: dict[str, Path] | None = None) -> dict[str, Any]:
    """Every arm's score on every question of the folder, by family (round 4's eight and "complex"), with the mean of
    round 4's eight families, the complex family by kind and by steps, false "not found" on answerable questions, the
    paired differences of the arms, answer length and token counts. ``extra``: more answer files by label (round 4's v18
    at 5,000 documents), scored on the questions they answer that were not counted again here (a recounted question has
    another answer there)."""
    from cie.eval import brain2_test as T2
    from cie.eval import brain_questions as B

    qs = _questions(work)
    files = {lab: work / f"{FILES.get(lab, lab)}.jsonl" for lab in labels}
    answers = {lab: _rows(f) for lab, f in files.items() if f.exists()}
    extras = {lab: _rows(f) for lab, f in (extra or {}).items() if f.exists()}
    rows = []
    for q in qs:
        r = {"id": q["id"], "family": q["family"], "kind": q["kind"], "steps": q.get("steps"), "recounted": bool(q.get("recounted")),
             "score": {}, "not_found": {}, "chars": {}, "tokens": {}}
        for lab, by in {**answers, **extras}.items():
            a = by.get(q["id"])
            if a is None or (lab in extras and r["recounted"]):
                continue
            r["score"][lab] = score_one(q, a)
            r["not_found"][lab] = B.says_not_found(str(a.get("answer") or ""), a.get("route"))
            r["chars"][lab] = len(str(a.get("answer") or ""))
            if a.get("output_tokens") is not None:
                r["tokens"][lab] = int(a.get("output_tokens") or 0)
        rows.append(r)
    fams = [*T2.FAMILIES2, "complex"]
    rep: dict[str, Any] = {"folder": str(work), "questions": len(qs), "by_family_count": dict(Counter(q["family"] for q in qs)),
                           "recounted": sum(r["recounted"] for r in rows), "arms": {}}
    for lab in [*answers, *extras]:
        sc = [r for r in rows if r["score"].get(lab) is not None]
        by_f = {f: _mean(r["score"][lab] for r in sc if r["family"] == f) for f in fams}
        eight = [by_f[f] for f in T2.FAMILIES2 if by_f[f] is not None]
        answerable = [r for r in sc if r["family"] in (*T2.ANSWERABLE, "complex")]
        cx = [r for r in sc if r["family"] == "complex"]
        toks = [r["tokens"][lab] for r in sc if lab in r["tokens"]]
        rep["arms"][lab] = {
            "answered": len(sc), "by_family": by_f,
            "mean_of_eight": round(sum(eight) / len(eight), 3) if len(eight) == len(T2.FAMILIES2) else None,
            "complex_by_kind": {k: _mean(r["score"][lab] for r in cx if r["kind"] == k) for k in sorted({r["kind"] for r in cx})},
            "complex_by_steps": {str(s): _mean(r["score"][lab] for r in cx if r["steps"] == s) for s in sorted({r["steps"] for r in cx})},
            "false_not_found": _mean(float(r["not_found"][lab]) for r in answerable),
            "prose_chars": _mean(r["chars"][lab] for r in sc if r["family"] == "prose"),
            "output_tokens_per_question": _mean(toks) if toks else None}
    rep["paired"] = _paired(rows, [*answers, *extras], fams)
    rep["rows"] = rows
    return rep


def score(messy: Path, tidy: Path | None = None, base5k: Path | None = BASE_MESSY, out: Path | None = None) -> dict[str, Any]:
    """The report: both folders scored (``score_folder``), with round 4's v18 answers at 5,000 documents
    (``base5k``/factbank_v18.jsonl[.gz]) beside v18's at 50,000 on the messy folder, and the plan's rules (``rules``) on
    the messy folder. Written to ``out`` (default the messy folder) as report50k.json and report50k.md."""
    import gzip

    extra = {}
    if base5k is not None:
        f, g = base5k / "factbank_v18.jsonl", base5k / "factbank_v18.jsonl.gz"
        if not f.exists() and g.exists():
            f = messy / "v18_5k.jsonl"
            f.write_bytes(gzip.decompress(g.read_bytes()))
        if f.exists():
            extra["v18_5k"] = f
    rep = {"messy": score_folder(messy, extra=extra)}
    if tidy is not None:
        rep["tidy"] = score_folder(tidy)
    rep["rules"] = {k: _try(fn, rep) for k, fn in rules().items()}
    out = out or messy
    (out / "report50k.json").write_text(json.dumps(rep, indent=1, default=str))
    (out / "report50k.md").write_text(to_markdown(rep))
    return rep


def _try(fn: Callable[[dict[str, Any]], bool], rep: dict[str, Any]) -> bool | None:
    try:
        return bool(fn(rep))
    except (KeyError, TypeError):
        return None  # an arm or a family is missing: undecided


# The plan's rules (docs/FACTBANK_50K_PLAN.md), set before any model answered; read on the messy folder
SIZE_MARGIN = 0.05  # 1: v18 at 50,000 documents >= v18 at 5,000 - this, on the mean of the families both answer
MEAN_LEAD = 0.03  # 2: the reasoner's mean of the eight families >= v18's + this
PROSE_LEAD = 0.10  # 3: the reasoner on free text >= v18 + this
COMPLEX_LEAD = 0.20  # 4: the reasoner on the complex questions >= v18 + this
KEEP_MARGIN = 0.05  # 5: the reasoner on not found, counts and unanswerable, each >= v18 - this
FALSE_NOT_FOUND_MAX = 0.05  # 6: the reasoner's false "not found" on answerable questions <= this
RAG_LEAD = 0.05  # 7: the reasoner's mean of the eight families >= plain search with the same model + this
RAG_COMPLEX_LEAD = 0.10  # 8: ... and on the complex questions >= it + this


def _fam(rep: dict[str, Any], arm: str, f: str) -> float:
    v = rep["messy"]["arms"][arm]["by_family"][f]
    if v is None:
        raise KeyError(f)
    return v


def _size_rule(rep: dict[str, Any]) -> bool:
    from cie.eval import brain2_test as T2

    d = rep["messy"]["paired"].get("v18 - v18_5k") or {}  # v18 at 50,000 minus v18 at 5,000
    fams = [f for f in T2.FAMILIES2 if f in d]
    if len(fams) != len(T2.FAMILIES2):
        raise KeyError("v18_5k")
    return sum(d[f]["mean"] for f in fams) / len(fams) >= -SIZE_MARGIN - 1e-9


def rules() -> dict[str, Callable[[dict[str, Any]], bool]]:
    m = lambda rep, a: rep["messy"]["arms"][a]["mean_of_eight"]  # noqa: E731
    return {
        f"1 size: v18 at 50,000 documents >= v18 at 5,000 - {SIZE_MARGIN} (mean over the eight families of the paired difference)": _size_rule,
        f"2 the reasoner's mean of the eight families >= v18's + {MEAN_LEAD}": lambda r: m(r, "reasoner") >= m(r, "v18") + MEAN_LEAD - 1e-9,
        f"3 free text: the reasoner >= v18 + {PROSE_LEAD}": lambda r: _fam(r, "reasoner", "prose") >= _fam(r, "v18", "prose") + PROSE_LEAD - 1e-9,
        f"4 complex questions: the reasoner >= v18 + {COMPLEX_LEAD}":
            lambda r: _fam(r, "reasoner", "complex") >= _fam(r, "v18", "complex") + COMPLEX_LEAD - 1e-9,
        f"5 no harm where the brain is exact: not found, counts and unanswerable, the reasoner each >= v18 - {KEEP_MARGIN}":
            lambda r: all(_fam(r, "reasoner", f) >= _fam(r, "v18", f) - KEEP_MARGIN - 1e-9 for f in ("not_found", "counts", "unanswerable")),
        f"6 the reasoner's false 'not found' on answerable questions <= {FALSE_NOT_FOUND_MAX}":
            lambda r: r["messy"]["arms"]["reasoner"]["false_not_found"] <= FALSE_NOT_FOUND_MAX + 1e-9,
        f"7 the reasoner's mean of the eight families >= plain search with the same model + {RAG_LEAD}":
            lambda r: m(r, "reasoner") >= m(r, "rag") + RAG_LEAD - 1e-9,
        f"8 complex questions: the reasoner >= plain search with the same model + {RAG_COMPLEX_LEAD}":
            lambda r: _fam(r, "reasoner", "complex") >= _fam(r, "rag", "complex") + RAG_COMPLEX_LEAD - 1e-9,
    }


def _f(x: Any) -> str:
    return "" if x is None else f"{x:.3f}" if isinstance(x, float) else str(x)


def to_markdown(rep: dict[str, Any]) -> str:
    from cie.eval import brain2_test as T2

    fams = [*T2.FAMILIES2, "complex"]
    out = ["# The company brain at 50,000 documents: report", ""]
    if rep.get("rules"):
        said = {True: "met", False: "NOT met", None: "undecided (an arm or a family has no answers)"}
        out += ["## The plan's rules (messy set)", "", "| rule | met |", "|---|---|", *(f"| {k} | {said[v]} |" for k, v in rep["rules"].items()), ""]
    for part in ("messy", "tidy"):
        r = rep.get(part)
        if not r:
            continue
        out += [f"## The {part} set ({r['questions']} questions)", "", "| arm | " + " | ".join(fams) + " | mean of 8 | false not found |",
                "|---" * (len(fams) + 3) + "|"]
        for lab, a in r["arms"].items():
            out.append(f"| {lab} | " + " | ".join(_f(a["by_family"].get(f)) for f in fams) + f" | {_f(a['mean_of_eight'])} | {_f(a['false_not_found'])} |")
        out += ["", "Paired differences (mean, 95% interval, better / worse):", "", "| | " + " | ".join([*fams, "all"]) + " |",
                "|---" * (len(fams) + 2) + "|"]
        for key, d in r["paired"].items():
            out.append(f"| {key} | " + " | ".join(f"{_f(d[f]['mean'])} [{d[f]['interval_95'][0]}, {d[f]['interval_95'][1]}] {d[f]['better']}/{d[f]['worse']}"
                                                  if f in d else "" for f in [*fams, "all"]) + " |")
        cx = {lab: a["complex_by_kind"] for lab, a in r["arms"].items() if a["complex_by_kind"]}
        if cx:
            kinds = sorted({k for v in cx.values() for k in v})
            out += ["", "Complex questions by kind:", "", "| arm | " + " | ".join(kinds) + " |", "|---" * (len(kinds) + 1) + "|"]
            out += [f"| {lab} | " + " | ".join(_f(v.get(k)) for k in kinds) + " |" for lab, v in cx.items()]
        out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain50k", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw", help="round 4's test documents and 45,000 more")
    d.add_argument("--base", type=Path, default=BASE)
    d.add_argument("--questions", type=Path, default=BASE / "questions.jsonl")
    d.add_argument("--index", type=Path, required=True, help="the folder index of the benchmark (root, index)")
    d.add_argument("--root", type=Path, required=True, help="the benchmark checkout")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--n", type=int, default=N_DOCS)
    d.add_argument("--seed", type=int, default=SEED)
    q = sub.add_parser("questions", help="round 4's questions that still hold, and the complex ones")
    q.add_argument("--work", type=Path, required=True)
    q.add_argument("--tidy", type=Path, default=BASE / "questions.jsonl")
    q.add_argument("--messy", type=Path, default=BASE_MESSY / "questions.jsonl")
    q.add_argument("--per-kind", type=int, default=None)
    q.add_argument("--seed", type=int, default=QSEED)
    k = sub.add_parser("ask", help="one arm's answers: v18, rag or reasoner")
    k.add_argument("--work", type=Path, nargs="+", required=True)
    k.add_argument("--arm", choices=("v18", "rag", "reasoner"), required=True)
    k.add_argument("--workers", type=int, default=4, help="processes for v18 and for the reasoner's tools")
    k.add_argument("--model", default="qwen3.8-27b")
    k.add_argument("--base-url", default=None, help="an OpenAI-compatible endpoint instead of vLLM on this machine")
    k.add_argument("--name", default=None)
    k.add_argument("--limit", type=int, default=None)
    k.add_argument("--chunk", type=int, default=256)
    k.add_argument("--max-model-len", type=int, default=32768)
    k.add_argument("--gpu-mem", type=float, default=0.90)
    k.add_argument("--max-tokens", type=int, default=6144)
    k.add_argument("--max-num-seqs", type=int, default=None)
    k.add_argument("--effort", default="medium", help="Qwen3.8's reasoning effort: low, medium or xhigh")
    k.add_argument("--no-thinking", action="store_true")
    s = sub.add_parser("score", help="the report, with the plan's rules on the messy folder")
    s.add_argument("--messy", type=Path, required=True)
    s.add_argument("--tidy", type=Path, default=None)
    s.add_argument("--base5k", type=Path, default=BASE_MESSY)
    a = ap.parse_args(argv)
    if a.cmd == "ask":
        if a.arm == "v18":
            rep = {str(w): ask_v18(w, a.workers, limit=a.limit) for w in a.work}
            print(json.dumps(rep, indent=1))
            return rep
        tools = None
        if a.arm == "reasoner":
            from cie.factbank.reasoner import ToolPool

            tools = ToolPool(a.work[0] / "factbank_v2.sqlite", LESSONS / "single_lessons.json", LESSONS / "plan_lessons.json",
                             LESSONS / "router.json", workers=a.workers)  # forked before the model is loaded
        gen = backend(a.model, a.base_url, max_model_len=a.max_model_len, gpu_mem=a.gpu_mem, max_tokens=a.max_tokens,
                      max_num_seqs=a.max_num_seqs, effort=a.effort, thinking=False if a.no_thinking else None)
        rep = ask_llm(a.work, a.arm, gen, tools, a.name, a.chunk, a.limit)
        print(json.dumps(rep, indent=1))
        return rep
    if a.cmd == "score":
        rep = score(a.messy, a.tidy, a.base5k)
        print(json.dumps({"rules": rep["rules"], **{p: {lab: {"mean_of_eight": v["mean_of_eight"], **v["by_family"]} for lab, v in rep[p]["arms"].items()}
                                                   for p in ("messy", "tidy") if p in rep}}, indent=1))
        return rep
    if a.cmd == "questions":
        rep = write_questions(a.work, a.tidy, a.messy, a.per_kind, a.seed)
        print(json.dumps({f: {k: r[k] for k in ("questions", "by_family")} for f, r in rep.items()}, indent=1))
        return rep
    if a.cmd == "draw":
        rep = write_draw(a.base, a.questions, a.index, a.root, a.out, a.n, a.seed)
        print(json.dumps({k: rep[k] for k in ("documents", "base", "added", "short", "skipped", "heldout_left_out")}, indent=1))
        return rep
    return None


if __name__ == "__main__":
    main()
