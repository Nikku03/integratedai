"""Facts extracted by an open model (Llama) from the memory bank's passages, at load time and without any question.

The Colab notebook ``notebooks/fact_extraction_colab.ipynb`` runs four steps, each a subcommand:

``build``
    The documents of the 5,000-document memory bank: every gold document plus a sample stratified by source, as
    ``cie.eval.bench_enterprise`` selects them (default seed 5). Their passages are cut by the memory bank's own builder
    (``cie.ingest.builder``). The rule-based records the builder extracts today are written alongside, for comparison.
``run``
    One model turns every passage into a list of standalone facts. vLLM serves it on a GPU; any OpenAI-compatible
    server works for a small test. Output is written in chunks, so an interrupted run resumes where it stopped.
``score``
    No model needed. How many of the benchmark's answer facts survive extraction, using the evidence audit's word
    check. Also: numbers that are not in the source passage, duplicates, size and speed.
``judge``
    Optional, with an OpenAI model, on samples:
    - whether an answer fact survives (judged rather than word-matched);
    - whether an extracted fact is correct.

What is measured, and what decides, is fixed in ``docs/FACT_EXTRACTION_PREREGISTRATION.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# (repository, pinned revision): the official repository first, when the token has access (Meta reviews requests by
# hand, sometimes for days); then mirrors with the same bf16 weights and chat template, checked file by file on
# 2026-10-04. RedHatAI's 8B copy is identical in every file; unsloth's keep the weights and template and add a pad token.
MODELS: dict[str, list[tuple[str, str | None]]] = {
    "llama-3.1-8b": [("meta-llama/Llama-3.1-8B-Instruct", None),
                     ("RedHatAI/Llama-3.1-8B-Instruct", "83c927477af31b2c66de4c0210ae5fa04b28289b"),
                     ("unsloth/Llama-3.1-8B-Instruct", "4699cc75b550f9c6f3173fb80f4703b62d946aa5")],
    "llama-3.2-3b": [("meta-llama/Llama-3.2-3B-Instruct", None),
                     ("unsloth/Llama-3.2-3B-Instruct", "006f5dcd1393c3add266de40994ba96225e9689d")],
}
# Llama 3.2's chat template writes today's date into every prompt; a fixed date keeps prompts identical from day to day
CHAT_TEMPLATE_KWARGS = {"date_string": "26 Jul 2024"}
# USD per million tokens (input, output), OpenAI's list prices on 2026-10-04; used only to report the judge's cost
JUDGE_PRICES = {"gpt-5.4": (2.50, 15.00), "gpt-5.4-mini": (0.75, 4.50), "gpt-5.4-nano": (0.20, 1.25), "gpt-5-mini": (0.25, 2.00),
                "gpt-6-luna": (0.10, 0.50)}

MAX_PASSAGE_CHARS = 8000  # the memory bank's passages are about 1,000 characters; a guard so no prompt can outgrow the context
SYSTEM = "You turn passages of a company's internal documents into facts for a search index."
# the instructions come before the passage, so every prompt shares one long prefix (the server's prefix cache reuses it)
INSTRUCTIONS = """List every fact the passage below states, one per line, each line starting with "- ".
- Write each fact as one complete sentence that names who or what it is about; never write "it", "this" or "they".
- Keep numbers, units, names, identifiers, dates, thresholds and conditions exactly as written.
- Keep each person's role exactly as the passage gives it (who asked, decided, owns, approved or was asked); never swap roles.
- Include decisions and their reasons, causes and effects, owners, deadlines, requirements, steps and status.
- Do not add anything the passage does not say, and do not repeat a fact.
- Put a list of tags or labels on one line.
- If the passage states no facts, write "- none"."""


def conversation(p: dict[str, Any]) -> list[dict[str, str]]:
    """The chat messages that ask for the facts of one passage."""
    head = f"Document: {p.get('doc_title') or ''}\nSource: {p.get('source') or ''}"
    body = f"{p.get('title') or ''}\n{p.get('text') or ''}".strip()[:MAX_PASSAGE_CHARS]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"{INSTRUCTIONS}\n\n{head}\n\nPassage:\n{body}"}]


_BULLET = re.compile(r"^\s*(?:[-*•‣–]|\d{1,3}[.)])\s+")
_PREAMBLE = re.compile(r"^(here (are|is)|the following|below (are|is)|sure\b|facts?\b.*:$|passage\b.*:$)", re.I)
_NONE = {"none", "no facts", "n/a", "no facts stated"}


def parse_facts(text: str) -> tuple[list[str], dict[str, int]]:
    """The fact lines of a model's answer, without preamble, "none" and exact repeats (counted, not kept)."""
    facts: list[str] = []
    seen: set[str] = set()
    counts = {"preamble": 0, "duplicates": 0, "none": 0}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        bullet = bool(_BULLET.match(line))
        while _BULLET.match(line):  # "- - From: ..." and "1. - ..." lose every marker
            line = _BULLET.sub("", line, count=1).strip()
        line = line.strip('"').strip()
        if not line:
            continue
        if line.lower().rstrip(".") in _NONE:
            counts["none"] += 1
            continue
        if not bullet and (_PREAMBLE.match(line) or line.endswith(":")):
            counts["preamble"] += 1
            continue
        key = re.sub(r"\W+", " ", line.lower()).strip()
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        facts.append(line)
    return facts, counts


# ------------------------------------------------------------------ build
def _build_one(args: tuple[str, str, str]) -> dict[str, Any] | None:
    from cie.ingest.builder import build
    from cie.ingest.sources import read

    sources_root, dsid, rel = args
    try:
        m = build(read(Path(sources_root) / rel, rel))
    except Exception:  # noqa: BLE001 - one malformed export must not stop the build
        return None
    title = m.display_title or m.title
    passages = [{"id": f"{dsid}#{k}", "doc": dsid, "k": k, "doc_title": title, "source": m.source, "title": t or "", "text": s or ""}
                for k, (t, s, _e) in enumerate(m.sections)]
    records = [{"doc": dsid, "section": r.section, "type": r.type, "text": f"{r.summary}\n{r.detail}".strip()} for r in m.records]
    return {"doc": dsid, "passages": passages, "records": records}


def build_set(root: Path, out: Path, n_docs: int | None = 5000, seed: int = 5, n_questions: int | None = None,
              workers: int | None = None, log=print) -> dict[str, Any]:
    """The documents of the memory bank and their passages; writes passages.jsonl, records.jsonl and set.json."""
    from multiprocessing import Pool

    from cie.eval.bench_enterprise import build_index, select_docs

    questions = [json.loads(line) for line in (root / "questions.jsonl").read_text().splitlines() if line.strip()]
    if n_questions:
        questions = questions[:n_questions]
    sources_root = root / "generated_data" / "sources"
    gold = {d for q in questions for d in q["expected_doc_ids"]}
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    index = build_index(sources_root, cache=out / "index.json", must_contain=gold, log=log)
    missing = gold - set(index)
    if not index or missing:
        raise SystemExit(f"corpus incomplete under {sources_root}: {len(index):,} documents indexed, {len(missing)} gold documents missing")
    dsids = select_docs(index, questions, n_docs, seed)
    log(f"  {len(dsids):,} documents ({len(gold & set(dsids))} gold) of {len(index):,}; indexed in {time.time() - t0:.0f} s")
    t1 = time.time()
    jobs = [(str(sources_root), d, index[d]) for d in dsids]
    with Pool(workers or max(1, (os.cpu_count() or 2) - 1)) as pool:
        built = [b for b in pool.imap(_build_one, jobs, chunksize=16) if b]
    n_pass = n_rec = chars = 0
    with open(out / "passages.jsonl", "w") as fp, open(out / "records.jsonl", "w") as fr:
        for b in built:
            for p in b["passages"]:
                fp.write(json.dumps(p) + "\n")
                chars += len(p["text"])
            for r in b["records"]:
                fr.write(json.dumps(r) + "\n")
            n_pass += len(b["passages"])
            n_rec += len(b["records"])
    info = {"documents": len(built), "failed": len(dsids) - len(built), "gold_documents": len(gold & {b["doc"] for b in built}),
            "passages": n_pass, "passage_chars": chars, "records": n_rec, "seed": seed, "n_docs": n_docs, "questions": len(questions),
            "corpus_documents": len(index), "build_seconds": round(time.time() - t1, 1), "root": str(root)}
    (out / "set.json").write_text(json.dumps({**info, "dsids": [b["doc"] for b in built]}, indent=1))
    log(f"  {n_pass:,} passages ({chars:,} characters) and {n_rec:,} rule-based records in {info['build_seconds']} s")
    return info


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Rows of a JSON-lines file; a last line cut off by a disconnect mid-write is skipped (its passages are asked again)."""
    if not Path(path).exists():
        return []
    lines = [line for line in Path(path).read_text().splitlines() if line.strip()]
    rows = []
    for i, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise
    return rows


def failed(row: dict[str, Any]) -> bool:
    return str(row.get("finish_reason") or "").startswith("error")


def load_facts(path: Path) -> list[dict[str, Any]]:
    """One row per passage: a passage retried after a failed request keeps its latest row."""
    return list({r["id"]: r for r in load_jsonl(path)}.values())


# ------------------------------------------------------------------ run
def resolve_model(name: str, token: str | None = None, log=print) -> tuple[str, str | None]:
    """(repository, revision) the token can download: the official repository when it has access, else a mirror."""
    if "/" in name or os.path.isdir(name):
        return name, None
    if name not in MODELS:
        raise SystemExit(f"unknown model {name!r}: use one of {', '.join(MODELS)} or a Hugging Face repository id")
    from huggingface_hub import hf_hub_download

    for repo, rev in MODELS[name]:
        try:
            hf_hub_download(repo, "config.json", revision=rev, token=token)
            return repo, rev
        except Exception as e:  # noqa: BLE001 - gated without access, missing, or offline: try the next
            log(f"  {repo}: not downloadable here ({type(e).__name__}); trying the next")
    raise SystemExit(f"no repository for {name} could be downloaded; set HF_TOKEN with access to {MODELS[name][0][0]}")


def _vllm_engine(model: str, revision: str | None, args: argparse.Namespace, log=print):
    from vllm import LLM

    kw: dict[str, Any] = {"model": model, "dtype": "bfloat16", "gpu_memory_utilization": args.gpu_mem,
                          "max_model_len": args.max_model_len, "enable_prefix_caching": True, "seed": 0}
    if revision:
        kw["revision"] = revision
    if args.max_num_seqs:
        kw["max_num_seqs"] = args.max_num_seqs
    if args.max_num_batched_tokens:
        kw["max_num_batched_tokens"] = args.max_num_batched_tokens
    if args.quantization and args.quantization != "none":
        kw["quantization"] = args.quantization
    log(f"  vLLM engine: {kw}")
    return LLM(**kw)


def _vllm_generate(engine, convs: list[list[dict[str, str]]], args: argparse.Namespace) -> list[dict[str, Any]]:
    from vllm import SamplingParams

    # explicit sampling parameters: without them vLLM samples (the models' generation_config: temperature 0.6, top_p 0.9)
    sp = SamplingParams(temperature=0.0, max_tokens=args.max_tokens, seed=0)
    outs = engine.chat(convs, sp, use_tqdm=True, chat_template_kwargs=CHAT_TEMPLATE_KWARGS)
    return [{"text": o.outputs[0].text, "prompt_tokens": len(o.prompt_token_ids or []), "output_tokens": len(o.outputs[0].token_ids),
             "cached_tokens": getattr(o, "num_cached_tokens", None) or 0, "finish_reason": o.outputs[0].finish_reason} for o in outs]


def _openai_generate(convs: list[list[dict[str, str]]], args: argparse.Namespace) -> list[dict[str, Any]]:
    """Any OpenAI-compatible chat endpoint (Ollama, a vLLM server): for small tests without a GPU."""
    import urllib.request

    def one(msgs):
        body = {"model": args.model, "messages": msgs, "temperature": 0, "max_tokens": args.max_tokens}
        err = None
        for attempt in range(4):  # a busy or still-loading server answers 5xx: wait and ask again
            try:
                req = urllib.request.Request(args.base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json",
                                                      "Authorization": f"Bearer {os.environ.get('EXTRACT_API_KEY', 'none')}"})
                r = json.load(urllib.request.urlopen(req, timeout=3600))
                c = r["choices"][0]
                u = r.get("usage") or {}
                return {"text": c["message"]["content"] or "", "prompt_tokens": u.get("prompt_tokens", 0),
                        "output_tokens": u.get("completion_tokens", 0), "finish_reason": c.get("finish_reason")}
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(2 ** attempt * 2)
        # recorded as a failed passage (no facts), never a crash of the whole chunk
        return {"text": "", "prompt_tokens": 0, "output_tokens": 0, "finish_reason": f"error: {type(err).__name__}: {err}"[:200]}

    with ThreadPoolExecutor(args.concurrency) as ex:
        return list(ex.map(one, convs))


def run_extraction(passages_file: Path, out: Path, args: argparse.Namespace, generate: Callable | None = None, log=print) -> dict[str, Any]:
    """Facts for every passage not yet in ``out``, in chunks; ``out`` gets one line per passage, a sidecar .run.json the timings."""
    passages = load_jsonl(passages_file)
    if args.limit:
        passages = passages[: args.limit]
    done = {r["id"] for r in load_facts(out) if not failed(r)}  # a failed passage is asked again
    todo = [p for p in passages if p["id"] not in done]
    meta_file = out.with_suffix(".run.json")
    meta = json.loads(meta_file.read_text()) if meta_file.exists() and done else {"chunks": []}
    # a resumed file must come from the same model, prompt and output settings, or its facts would mix two runs
    signature = {"model": args.model, "max_tokens": args.max_tokens, "quantization": args.quantization or "none",
                 "prompt": hashlib.sha1((SYSTEM + INSTRUCTIONS).encode()).hexdigest()[:12]}
    if done and meta.get("signature") and meta["signature"] != signature:
        raise SystemExit(f"{out} holds facts from other settings ({meta['signature']}, now {signature}): "
                         f"give this run another --name, or delete the file to start again")
    meta["signature"] = signature
    log(f"  {len(passages):,} passages, {len(done):,} already extracted, {len(todo):,} to go")
    engine = None
    if generate is None:
        if args.backend == "vllm":
            if not todo:
                log("  nothing to extract")
                return meta
            t = time.time()
            model, revision = resolve_model(args.model, os.environ.get("HF_TOKEN"), log=log)
            engine = _vllm_engine(model, revision, args, log=log)
            _vllm_generate(engine, [conversation(p) for p in todo[:8]], args)  # warm-up, outside the timing
            meta.setdefault("model_load_seconds", []).append(round(time.time() - t, 1))
            meta["model_repo"] = f"{model}@{revision}" if revision else model
            generate = lambda convs: _vllm_generate(engine, convs, args)  # noqa: E731
        else:
            generate = lambda convs: _openai_generate(convs, args)  # noqa: E731
            meta["model_repo"] = f"{args.model} at {args.base_url}"
    meta.update({"model": args.model, "backend": args.backend, "max_tokens": args.max_tokens, "settings": {
        k: getattr(args, k, None) for k in ("gpu_mem", "max_model_len", "max_num_seqs", "max_num_batched_tokens", "quantization", "chunk")}})
    meta["gpu"] = _gpu_name()
    out.parent.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(todo), args.chunk):
        part = todo[i: i + args.chunk]
        t = time.time()
        res = generate([conversation(p) for p in part])
        secs = time.time() - t
        with open(out, "a") as f:
            for p, r in zip(part, res, strict=True):
                facts, counts = parse_facts(r["text"])
                f.write(json.dumps({"id": p["id"], "doc": p["doc"], "facts": facts, **counts, "prompt_tokens": r["prompt_tokens"],
                                    "output_tokens": r["output_tokens"], "finish_reason": r["finish_reason"], "raw": r["text"]}) + "\n")
        c = {"passages": len(part), "seconds": round(secs, 4), "prompt_tokens": sum(r["prompt_tokens"] for r in res),
             "output_tokens": sum(r["output_tokens"] for r in res), "cached_prompt_tokens": sum(r.get("cached_tokens", 0) for r in res)}
        meta["chunks"].append(c)
        meta_file.write_text(json.dumps(meta, indent=1))
        log(f"  chunk {i // args.chunk + 1}: {c['passages']:,} passages in {secs:.0f} s, {c['output_tokens'] / max(secs, 1e-9):,.0f} output tokens/s")
    s = speed(meta)
    meta["summary"] = s
    meta_file.write_text(json.dumps(meta, indent=1))
    log(f"  done: {s}")
    return meta


def speed(meta: dict[str, Any]) -> dict[str, Any]:
    ch = meta.get("chunks", [])
    secs = sum(c["seconds"] for c in ch)
    n = sum(c["passages"] for c in ch)
    out_t = sum(c["output_tokens"] for c in ch)
    in_t = sum(c["prompt_tokens"] for c in ch)
    cached = sum(c.get("cached_prompt_tokens", 0) for c in ch)
    return {"passages": n, "generation_seconds": round(secs, 1), "prompt_tokens": in_t, "output_tokens": out_t,
            "prompt_tokens_from_cache": round(cached / in_t, 3) if in_t else None,
            "output_tokens_per_second": round(out_t / secs, 1) if secs else None,
            "passages_per_second": round(n / secs, 2) if secs else None,
            "model_load_seconds": sum(meta.get("model_load_seconds", [])) or None, "gpu": meta.get("gpu")}


def _gpu_name() -> str | None:
    import subprocess

    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ score
_NUMBER = re.compile(r"\d[\d,.:/\-]*\d|\d")


def _plain_numbers(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", s or "")


def grounded_numbers(fact: str, source: str) -> bool | None:
    """Every number in the fact appears in the source (thousands separators ignored); None when the fact has none."""
    from cie.eval.evidence_audit import _has_number

    nums = [n.strip(".,:/-") for n in _NUMBER.findall(_plain_numbers(fact))]
    nums = [n for n in nums if n]
    if not nums:
        return None
    low = _plain_numbers(source).lower()
    return all(_has_number(n, low) for n in nums)


def grounded_numbers_each(fact: str, source: str) -> bool | None:
    """As grounded_numbers, but each number of a range or date is checked on its own ("15-30" is 15 and 30) and the
    source is everything the model was shown (the document title too)."""
    from cie.eval.evidence_audit import _has_number

    nums = [n.strip(".,") for n in re.findall(r"\d+(?:[.,]\d+)*", _plain_numbers(fact))]
    nums = [n for n in nums if n]
    if not nums:
        return None
    low = _plain_numbers(source).lower()
    return all(_has_number(n, low) for n in nums)


def word_support(fact: str, source_stems: set[str]) -> float:
    from cie.eval.evidence_audit import fact_terms

    _, words = fact_terms(fact)
    return sum(1 for w in words if w in source_stems) / len(words) if words else 1.0


BASELINE = "rule-based records (today)"
CARD_FREE = "rule-based records, card without its copied passages"


def card_without_passages(r: dict[str, Any]) -> str:
    """A record's text; for the document card, only its own lines (summary, tags, people...): the builder appends the
    document's first two passages to the card word for word, which is copied text, not extracted facts."""
    return r["text"].split("\n\n", 1)[0] if r.get("type") == "document" else r["text"]


def positive_facts(q: dict[str, Any]) -> list[tuple[str, str]]:
    """(fact id, fact) of a question's answer facts that evidence can hold ("The answer must not ..." facts constrain the answer)."""
    return [(f"F{i + 1}", f) for i, f in enumerate(q.get("answer_facts") or []) if not f.lower().startswith("the answer must not")]


def score(work: Path, root: Path, facts_files: list[Path], out: Path | None = None, log=print) -> dict[str, Any]:
    """Answer facts kept, numbers grounded, duplicates, size and speed, for each facts file and the rule-based records."""
    from cie.eval.evidence_audit import _stems, present

    for stale in ("judge.json", "judge_detail.jsonl"):  # a judge of earlier facts must not decide for these
        (work / stale).unlink(missing_ok=True)
    st = json.loads((work / "set.json").read_text())
    docs = set(st["dsids"])
    passages = load_jsonl(work / "passages.jsonl")
    by_pid = {p["id"]: p for p in passages}
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for p in passages:
        by_doc[p["doc"]].append(p)
    text_of = {p["id"]: f"{p['title']}\n{p['text']}" for p in passages}
    stems_of: dict[str, set[str]] = {}

    def stems(pid: str) -> set[str]:
        if pid not in stems_of:
            stems_of[pid] = _stems(text_of[pid])
        return stems_of[pid]

    # methods: units of text per document, each unit checked on its own (as the evidence audit checks one passage at a time)
    methods: dict[str, dict[str, list[str]]] = {}
    recs = load_jsonl(work / "records.jsonl")
    rec_units: dict[str, dict[Any, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in recs:
        rec_units[r["doc"]][r["section"]].append(r["text"])
    methods[BASELINE] = {d: ["\n".join(v) for v in u.values()] for d, u in rec_units.items()}
    # for information: the document card copies the first two passages word for word; without that copy
    card_free: dict[str, dict[Any, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in recs:
        card_free[r["doc"]][r["section"]].append(card_without_passages(r))
    methods[CARD_FREE] = {d: ["\n".join(v) for v in u.values()] for d, u in card_free.items()}
    facts_by_method: dict[str, list[dict]] = {}
    for f in facts_files:
        rows = load_facts(f)
        name = f.stem.replace("facts_", "")
        facts_by_method[name] = rows
        units: dict[str, list[str]] = defaultdict(list)
        for r in rows:
            if r["facts"]:
                units[r["doc"]].append("\n".join(r["facts"]))
        methods[name] = dict(units)
    lines_by_method = {name: {d: [ln for u in units for ln in u.split("\n")] for d, units in m.items()} for name, m in methods.items()}

    qs = [json.loads(line) for line in (root / "questions.jsonl").read_text().splitlines() if line.strip()]
    qs = qs[: st.get("questions") or None]  # the questions the build used (all, or the first N of a small test)
    qs = [q for q in qs if q["expected_doc_ids"] and set(q["expected_doc_ids"]) <= docs]
    totals = {"facts": 0, "checkable": 0}
    kept = {name: {"unit": 0, "line": 0} for name in methods}
    by_type: dict[str, dict[str, Any]] = defaultdict(lambda: {"checkable": 0, **{name: 0 for name in methods}})
    rows_out = []
    for q in qs:
        gold_passages = [p["id"] for d in q["expected_doc_ids"] for p in by_doc.get(d, [])]
        for fid, fact in positive_facts(q):
            totals["facts"] += 1
            holders = [pid for pid in gold_passages if present(fact, text_of[pid], stems(pid))]
            if not holders:
                continue
            totals["checkable"] += 1
            t = by_type[q["question_type"]]
            t["checkable"] += 1
            row = {"question_id": q["question_id"], "fid": fid, "type": q["question_type"], "holders": holders[:5]}
            for name in methods:
                units = [u for d in q["expected_doc_ids"] for u in methods[name].get(d, [])]
                lines = [ln for d in q["expected_doc_ids"] for ln in lines_by_method[name].get(d, [])]
                u_ok = any(present(fact, u) for u in units)
                l_ok = u_ok and any(present(fact, ln) for ln in lines)
                kept[name]["unit"] += u_ok
                kept[name]["line"] += l_ok
                t[name] += u_ok
                row[name] = u_ok
            rows_out.append(row)
    ck = totals["checkable"] or 1
    report: dict[str, Any] = {
        "set": {k: v for k, v in st.items() if k != "dsids"}, "questions": len(qs), "answer_facts": totals["facts"],
        "checkable_in_passages": totals["checkable"],
        "kept": {name: {"in_a_passage_list": v["unit"], "in_one_line": v["line"], "share": round(v["unit"] / ck, 3)} for name, v in kept.items()},
        "kept_by_question_type": {k: dict(v) for k, v in sorted(by_type.items())},
        "methods": {},
    }
    for name, rows in facts_by_method.items():
        n_lines = sum(len(r["facts"]) for r in rows)
        pass_chars = sum(len(by_pid[r["id"]]["text"]) for r in rows if r["id"] in by_pid)  # the passages this model has done
        with_num = grounded = grounded_each = 0
        weak = 0
        for r in rows:
            src = text_of.get(r["id"], "")
            shown = f"{by_pid[r['id']]['doc_title']}\n{src}" if r["id"] in by_pid else src
            for ln in r["facts"]:
                g = grounded_numbers(ln, src)
                if g is not None:
                    with_num += 1
                    grounded += g
                    grounded_each += bool(grounded_numbers_each(ln, shown))
                if word_support(ln, stems(r["id"]) if r["id"] in text_of else set()) < 0.5:
                    weak += 1
        meta_file = next((f.with_suffix(".run.json") for f in facts_files if f.stem.replace("facts_", "") == name), None)
        meta = json.loads(meta_file.read_text()) if meta_file and meta_file.exists() else {}
        sp = speed(meta) if meta else {}
        per_doc = len(passages) / max(1, len({p["doc"] for p in passages}))  # this set's; gold documents run longer than average
        pps = sp.get("passages_per_second")
        report["methods"][name] = {
            "passages_done": len(rows), "passage_count": len(passages), "passages_with_no_fact": sum(1 for r in rows if not r["facts"]),
            "fact_lines": n_lines, "fact_lines_per_passage": round(n_lines / max(1, len(rows)), 1),
            "fact_chars": sum(len(ln) for r in rows for ln in r["facts"]), "passage_chars": pass_chars,
            "duplicates_dropped": sum(r.get("duplicates", 0) for r in rows), "preamble_dropped": sum(r.get("preamble", 0) for r in rows),
            "hit_output_cap": sum(1 for r in rows if r.get("finish_reason") == "length"),
            "failed": sum(1 for r in rows if failed(r)),
            "lines_with_numbers": with_num, "lines_with_a_number_not_in_the_passage": with_num - grounded,
            "lines_with_a_number_not_shown_to_the_model": with_num - grounded_each,
            "lines_with_weak_word_support": weak,
            "speed": sp,
            "hours_on_this_gpu": {f"{n:,} documents": round(n * per_doc / pps / 3600, 2) for n in (5000, 50000, 512000)} if pps else None,
            "passages_per_document": round(per_doc, 2),
        }
    out = out or work / "report.json"
    out.write_text(json.dumps(report, indent=1))
    (out.with_name(out.stem + "_rows.jsonl")).write_text("\n".join(json.dumps(r) for r in rows_out) + "\n")
    md = to_markdown(report)
    out.with_suffix(".md").write_text(md)
    log(md)
    return report


def to_markdown(rep: dict[str, Any]) -> str:
    st = rep["set"]
    ck = rep["checkable_in_passages"]
    lines = [f"**Set:** {st.get('documents', 0):,} documents, {st.get('passages', 0):,} passages, {rep['questions']} questions, "
             f"{rep['answer_facts']:,} answer facts, {ck:,} found word for word in a gold passage (the ceiling).", "",
             "| | answer facts kept (word check) | share | in one line |", "|---|---|---|---|"]
    for name, k in rep["kept"].items():
        lines.append(f"| {name} | {k['in_a_passage_list']:,} of {ck:,} | {k['share']:.0%} | {k['in_one_line']:,} |")
    if rep["methods"]:
        lines += ["", "| model | passages done | fact lines | per passage | size against the passages | number not in passage (registered) | "
                      "number not shown to the model | weak word support | duplicates dropped | hit output cap | output tokens/s | passages/s | "
                      "hours: 5k / 50k / 512k documents |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, m in rep["methods"].items():
            sp = m["speed"] or {}
            h = m["hours_on_this_gpu"] or {}
            nl = max(1, m["fact_lines"])
            lines.append(f"| {name} | {m['passages_done']:,} of {m['passage_count']:,} | {m['fact_lines']:,} | {m['fact_lines_per_passage']} | "
                         f"{m['fact_chars'] / max(1, m['passage_chars']):.2f}x | {m['lines_with_a_number_not_in_the_passage']:,} "
                         f"({m['lines_with_a_number_not_in_the_passage'] / nl:.1%}) | {m['lines_with_a_number_not_shown_to_the_model']:,} "
                         f"({m['lines_with_a_number_not_shown_to_the_model'] / nl:.1%}) | {m['lines_with_weak_word_support']:,} "
                         f"({m['lines_with_weak_word_support'] / nl:.1%}) | {m['duplicates_dropped']:,} | {m['hit_output_cap']:,} | "
                         f"{sp.get('output_tokens_per_second') or '–'} | {sp.get('passages_per_second') or '–'} | "
                         f"{' / '.join(str(v) for v in h.values()) or '–'} |")
    lines += ["", "By question type (answer facts kept, word check):", "",
              "| type | checkable | " + " | ".join(rep["kept"]) + " |", "|---|---|" + "---|" * len(rep["kept"])]
    for t, v in rep["kept_by_question_type"].items():
        lines.append(f"| {t} | {v['checkable']} | " + " | ".join(str(v.get(n, 0)) for n in rep["kept"]) + " |")
    return "\n".join(lines)


# ------------------------------------------------------------------ judge
RETENTION_PROMPT = """You check whether a list of facts extracted from a document states a given fact.
Fact: {fact}

Extracted facts:
{units}

Does the list state the fact? "covered": every specific in the fact (numbers, names, labels, list members, conditions) is stated; paraphrase is fine. "partly": some of it is stated but a specific is missing or changed. "missed": it is not stated. "contradicted": the list states something incompatible with it.
Answer with JSON: {{"verdict": "covered|partly|missed|contradicted", "note": "<at most 15 words>"}}"""

CORRECTNESS_PROMPT = """You check a fact extracted from a passage of a company document.
Passage:
{passage}

Extracted fact: {fact}

Is the extracted fact correct according to the passage? "correct": the passage states it (paraphrase is fine). "wrong": it contradicts the passage or gets a number, name, date, role or relation wrong. "unsupported": it adds something the passage does not say.
Answer with JSON: {{"verdict": "correct|wrong|unsupported", "note": "<at most 15 words>"}}"""


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(max(0.0, (c - r) / d), 3), round(min(1.0, (c + r) / d), 3))


VERDICTS = {"retention": ["covered", "partly", "missed", "contradicted"], "correctness": ["correct", "wrong", "unsupported"]}


def openai_judge(model: str, effort: str | None = None) -> Callable[[str, str], dict[str, Any]]:
    """One verdict per prompt from an OpenAI model (OPENAI_API_KEY), as strict JSON; usage is returned for the cost.

    gpt-5.4 models take reasoning effort none/low/medium/high, gpt-5 models minimal/low/medium/high: an effort the model
    rejects is dropped, as is the strict schema (JSON mode is used instead). The cap counts reasoning tokens; an answer
    cut by it is asked again with a larger cap once."""
    from openai import BadRequestError, OpenAI

    client = OpenAI(max_retries=8, timeout=120.0)
    state: dict[str, Any] = {"effort": effort or ("low" if model.startswith("gpt-5.4") else "minimal"), "schema": True, "served_by": None}

    def call(prompt: str, kind: str = "correctness", cap: int = 1000) -> dict[str, Any]:
        kw: dict[str, Any] = {"model": model, "max_completion_tokens": cap,
                              "messages": [{"role": "developer", "content": "You are a strict grader. Reply with JSON only."},
                                           {"role": "user", "content": prompt}]}
        if state["schema"]:
            kw["response_format"] = {"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": {
                "type": "object", "additionalProperties": False, "required": ["verdict", "note"],
                "properties": {"verdict": {"type": "string", "enum": VERDICTS[kind]}, "note": {"type": "string"}}}}}
        else:
            kw["response_format"] = {"type": "json_object"}
        if state["effort"]:
            kw["reasoning_effort"] = state["effort"]
        try:
            r = client.chat.completions.create(**kw)
        except BadRequestError as e:
            msg = str(e).lower()
            if state["effort"] and "reasoning" in msg:
                state["effort"] = None  # this model takes no such effort: its default
                return call(prompt, kind, cap)
            if state["schema"] and ("response_format" in msg or "json_schema" in msg):
                state["schema"] = False
                return call(prompt, kind, cap)
            raise
        state["served_by"] = getattr(r, "model", None) or state["served_by"]
        ch = r.choices[0]
        if not (ch.message.content or "").strip() and ch.finish_reason == "length" and cap < 4000:
            return call(prompt, kind, cap * 4)  # the reasoning used up the cap
        try:
            v = json.loads(ch.message.content or "{}")
        except json.JSONDecodeError:
            v = {}
        u = r.usage
        return {"verdict": str(v.get("verdict", "")).strip().lower() or "judge_failed", "note": v.get("note", ""),
                "in": getattr(u, "prompt_tokens", 0) or 0, "out": getattr(u, "completion_tokens", 0) or 0}

    call.state = state  # type: ignore[attr-defined]
    return call


def judge(work: Path, root: Path, facts_files: list[Path], model: str = "gpt-5.4-mini", n_retention: int = 300, n_lines: int = 300,
          seed: int = 7, concurrency: int = 16, call: Callable[[str], dict[str, Any]] | None = None, out: Path | None = None,
          log=print) -> dict[str, Any]:
    """On samples: is a word-checkable answer fact stated in the facts extracted from the passage that holds it (and in the
    rule-based records of that passage)? Is a sampled extracted fact correct according to its passage?"""
    call = call or openai_judge(model)
    rows_file = work / "report_rows.jsonl"
    if not rows_file.exists():
        raise SystemExit("run the score step first (it writes report_rows.jsonl)")
    rows = load_jsonl(rows_file)
    passages = {p["id"]: p for p in load_jsonl(work / "passages.jsonl")}
    recs: dict[tuple[str, Any], list[dict]] = defaultdict(list)
    for r in load_jsonl(work / "records.jsonl"):
        recs[(r["doc"], r["section"])].append(r)
    qs = {json.loads(line)["question_id"]: json.loads(line) for line in (root / "questions.jsonl").read_text().splitlines() if line.strip()}
    rng = random.Random(seed)
    sample = rng.sample(rows, min(n_retention, len(rows)))
    facts_by_method = {f.stem.replace("facts_", ""): {r["id"]: r for r in load_facts(f)} for f in facts_files}
    tasks: list[tuple[str, str, str]] = []  # (kind, method, prompt)
    keys: list[dict[str, Any]] = []
    for row in sample:
        fact = dict(positive_facts(qs[row["question_id"]]))[row["fid"]]
        # every method gets what it made of the same passages: those that hold the fact word for word (up to 3)
        pids = row["holders"][:3]
        rs = [r for pid in pids for r in recs.get((passages[pid]["doc"], passages[pid]["k"]), [])]
        units = {BASELINE: [r["text"] for r in rs], CARD_FREE: [card_without_passages(r) for r in rs]}
        for name, by_id in facts_by_method.items():
            units[name] = list(dict.fromkeys(f for pid in pids for f in (by_id.get(pid) or {}).get("facts", [])))
        for name, u in units.items():
            keys.append({"kind": "retention", "method": name, "question_id": row["question_id"], "fid": row["fid"], "passages": pids})
            tasks.append(("retention", name, RETENTION_PROMPT.format(fact=fact, units="\n".join(f"- {x}" for x in u)) if u else ""))
    for name, by_id in facts_by_method.items():
        pool = [(pid, ln) for pid, r in by_id.items() for ln in r["facts"] if pid in passages]
        for pid, ln in rng.sample(pool, min(n_lines, len(pool))):
            p = passages[pid]
            keys.append({"kind": "correctness", "method": name, "passage": pid, "fact": ln})
            tasks.append(("correctness", name, CORRECTNESS_PROMPT.format(passage=f"{p['doc_title']}\n{p['title']}\n{p['text']}", fact=ln)))

    def go(t):
        kind, _name, prompt = t
        if not prompt:  # nothing was extracted from those passages: missed, without a call
            return {"verdict": "missed", "note": "nothing extracted", "in": 0, "out": 0, "called": False}
        try:
            return call(prompt, kind)
        except Exception as e:  # noqa: BLE001 - one failed call is counted, not fatal
            return {"verdict": "judge_failed", "note": f"{type(e).__name__}: {e}"[:200], "in": 0, "out": 0}

    t0 = time.time()
    with ThreadPoolExecutor(concurrency) as ex:
        verdicts = list(ex.map(go, tasks))
    detail = [{**k, **v} for k, v in zip(keys, verdicts, strict=True)]
    summary: dict[str, Any] = {"model": model, "served_by": getattr(call, "state", {}).get("served_by"), "seconds": round(time.time() - t0, 1), "retention_sample": len(sample), "line_sample_per_model": n_lines,
                               "retention": {}, "correctness": {}}
    for kind in ("retention", "correctness"):
        for name in {d["method"] for d in detail if d["kind"] == kind}:
            ds = [d for d in detail if d["kind"] == kind and d["method"] == name]
            c = Counter(d["verdict"] for d in ds)
            n = len(ds) - c.get("judge_failed", 0)
            good = c.get("covered" if kind == "retention" else "correct", 0)
            bad = c.get("wrong", 0) + c.get("unsupported", 0) if kind == "correctness" else c.get("missed", 0) + c.get("contradicted", 0)
            summary[kind][name] = {"n": n, "counts": dict(c), "good_share": round(good / n, 3) if n else None, "good_ci95": wilson(good, n),
                                   "bad_share": round(bad / n, 3) if n else None, "bad_ci95": wilson(bad, n),
                                   "judge_failed": c.get("judge_failed", 0)}
    tin, tout = sum(d.get("in", 0) for d in detail), sum(d.get("out", 0) for d in detail)
    price = JUDGE_PRICES.get(model)
    summary["tokens"] = {"input": tin, "output": tout, "cost_usd": round(tin / 1e6 * price[0] + tout / 1e6 * price[1], 3) if price else None}
    summary["judge_failed"] = sum(1 for d in detail if d["verdict"] == "judge_failed")
    summary["calls"] = sum(1 for d in detail if d.get("called", True))  # verdicts the judge was actually asked for
    summary["failed_share"] = round(summary["judge_failed"] / summary["calls"], 3) if summary["calls"] else None
    out = out or work / "judge.json"
    out.write_text(json.dumps(summary, indent=1))
    out.with_name(out.stem + "_detail.jsonl").write_text("\n".join(json.dumps(d) for d in detail) + "\n")
    log(judge_markdown(summary))
    return summary


def judge_markdown(s: dict[str, Any]) -> str:
    pct = lambda v, d=0: "–" if v is None else f"{v:.{d}%}"  # noqa: E731
    lines = [f"**Judge:** {s['model']}" + (f" (served by {s['served_by']})" if s.get("served_by") else "") +
             f", {s['retention_sample']} sampled answer facts, {s['line_sample_per_model']} sampled fact lines per model; "
             f"{s['judge_failed']} of {s.get('calls', '?')} calls failed; cost ${s['tokens']['cost_usd']}", "",
             "| | answer facts covered | 95% interval | missed or contradicted |", "|---|---|---|---|"]
    for name, v in s["retention"].items():
        lines.append(f"| {name} | {pct(v['good_share'])} of {v['n']} | {pct(v['good_ci95'][0])}–{pct(v['good_ci95'][1])} | {pct(v['bad_share'])} |")
    lines += ["", "| model | extracted facts correct | wrong or unsupported | 95% interval (wrong or unsupported) |", "|---|---|---|---|"]
    for name, v in s["correctness"].items():
        lines.append(f"| {name} | {pct(v['good_share'])} of {v['n']} | {pct(v['bad_share'], 1)} | {pct(v['bad_ci95'][0], 1)}–{pct(v['bad_ci95'][1], 1)} |")
    return "\n".join(lines)


# ------------------------------------------------------------------ cli
def main(argv: Iterable[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="the documents and their passages")
    b.add_argument("--root", required=True, help="the EnterpriseRAG-Bench checkout (questions.jsonl, generated_data/sources)")
    b.add_argument("--work", required=True)
    b.add_argument("--docs", type=int, default=5000)
    b.add_argument("--seed", type=int, default=5, help="5: the same documents as the memory bank's 5,000-document load")
    b.add_argument("--questions", type=int, default=None, help="only the first N questions (a small test)")
    b.add_argument("--workers", type=int, default=None)
    r = sub.add_parser("run", help="extract facts from every passage with one model")
    r.add_argument("--work", required=True)
    r.add_argument("--model", default="llama-3.1-8b", help=f"{', '.join(MODELS)} or a Hugging Face repository id (backend openai: the served model's name)")
    r.add_argument("--name", default=None, help="results are written to facts_<name>.jsonl (default: the model)")
    r.add_argument("--backend", choices=["vllm", "openai"], default="vllm")
    r.add_argument("--base-url", default="http://127.0.0.1:11434/v1", help="backend openai: the server")
    r.add_argument("--concurrency", type=int, default=4, help="backend openai: requests in flight")
    r.add_argument("--max-tokens", type=int, default=768)
    r.add_argument("--gpu-mem", type=float, default=0.92)
    r.add_argument("--max-model-len", type=int, default=4096)
    r.add_argument("--max-num-seqs", type=int, default=None)
    r.add_argument("--max-num-batched-tokens", type=int, default=None)
    r.add_argument("--quantization", default="none", help="none, or a vLLM quantization such as fp8")
    r.add_argument("--chunk", type=int, default=4096, help="passages per call; results are saved after each")
    r.add_argument("--limit", type=int, default=0, help="only the first N passages (0: all)")
    s = sub.add_parser("score", help="answer facts kept, grounding, size and speed")
    s.add_argument("--work", required=True)
    s.add_argument("--root", required=True)
    s.add_argument("--facts", nargs="*", default=None, help="facts files (default: every facts_*.jsonl in --work)")
    s.add_argument("--quiet", action="store_true", help="write report.md without printing it")
    j = sub.add_parser("judge", help="optional: an OpenAI model judges samples")
    j.add_argument("--work", required=True)
    j.add_argument("--root", required=True)
    j.add_argument("--facts", nargs="*", default=None)
    j.add_argument("--model", default="gpt-5.4-mini")
    j.add_argument("--retention", type=int, default=300)
    j.add_argument("--lines", type=int, default=300)
    j.add_argument("--concurrency", type=int, default=16)
    j.add_argument("--seed", type=int, default=7)
    j.add_argument("--quiet", action="store_true")
    a = ap.parse_args(list(argv) if argv is not None else None)
    work = Path(a.work)
    if a.cmd == "build":
        return build_set(Path(a.root), work, a.docs, a.seed, a.questions, a.workers)
    if a.cmd == "run":
        name = a.name or a.model.split("/")[-1]
        return run_extraction(work / "passages.jsonl", work / f"facts_{name}.jsonl", a)
    facts = [Path(f) for f in a.facts] if a.facts else sorted(work.glob("facts_*.jsonl"))
    quiet = (lambda *x: None) if getattr(a, "quiet", False) else print
    if a.cmd == "score":
        return score(work, Path(a.root), facts, log=quiet)
    return judge(work, Path(a.root), facts, a.model, a.retention, a.lines, a.seed, a.concurrency, log=quiet)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if main() is not None else 1)
