"""Facts a language model extracted from the memory bank's sections, stored beside them (table ``section_facts``).

One row holds the facts of one section for one extractor. The extractor's ``signature`` is a hash of everything
that shapes the facts: model, revision, instructions, output cap, and whether repeated text was left out. The store
is built to be filled in parts:

* **Partial.** A row is written only for a section the model answered. A section that failed, or that no run has
  reached yet, has no row: ``pending`` lists it, and the next run (or import) picks it up. Every write is idempotent
  (one row per section and signature), so importing a file twice, or a file that overlaps an earlier import, adds
  only what is missing, and a run can stop at any point.
* **Never checked twice.** The checks are made once, when the facts are written, and stored with each line:
  - a number not in the section;
  - word support;
  - a tag line.

  Reading never checks again.
* **Never asked twice.** ``input_sha256`` is the hash of the section's own part of the prompt (document title,
  source, section title, text). Under one signature, a section whose input matches one already extracted takes
  those facts without asking the model. An example is a new version of a document with this part unchanged.
* **Permissions.** Scope and sensitivity are the section's, copied so that reads filter like every other read.

Two ways in, with the same signature for the same model and settings:
* ``import_file``: a facts file written by ``cie.eval.extract_facts run`` (the Colab notebook). Its passages are
  matched to sections by document (``dsid``) and position. A passage whose text differs from its section is left
  out as stale, and never stored against the wrong text.
* ``extract``: straight from the database, for the sections with no row yet (new documents, new versions). It
  commits after every chunk.

Command line: ``python -m cie.memory.facts {status,import,extract} ...``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

COLS = ("id, tenant_id, section_id, document_id, scope_id, sensitivity, extractor, signature, settings, section_sha256, input_sha256, "
        "status, facts, text, n_facts, prompt_tokens, output_tokens, embedding")
TYPES = ["uuid", "uuid", "uuid", "uuid", "uuid", "int4", "text", "text", "jsonb", "text", "text", "text", "jsonb", "text", "int4", "int4",
         "int4", "vector"]
TSV = "to_tsvector('english', text)"
STATUSES = ("done", "empty", "capped", "skipped")


def signature(settings: dict[str, Any]) -> str:
    """A short hash of an extractor's settings (``extract_facts.run_signature`` plus the model repository)."""
    return hashlib.sha1(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]


def input_sha256(p: dict[str, Any]) -> str:
    """The hash of a passage's own part of the prompt; the instructions are in the signature."""
    from cie.eval.extract_facts import passage_block

    return hashlib.sha256(passage_block(p).encode()).hexdigest()


def status_of(finish_reason: str | None, n_facts: int) -> str | None:
    """done, empty (the model found no fact), capped (the output cap cut the list), skipped (the passage only repeats
    the previous one), or None for a failed request: no row, so the section stays pending."""
    fr = str(finish_reason or "")
    if fr.startswith("error"):
        return None
    if fr.startswith("skipped"):
        return "skipped"
    if fr == "length":
        return "capped"
    return "done" if n_facts else "empty"


def checked(facts: list[str], section_title: str, section_text: str) -> list[dict[str, Any]]:
    """Each fact line with the checks made once, when it is stored.

    - ``numbers_in_section``: whether every number in the line is in the section (None: the line has no number).
    - ``support``: the share of the line's content words found in the section.
    - ``tag``: whether it is a tag line rather than a fact.
    """
    from cie.eval.evidence_audit import _stems
    from cie.eval.extract_facts import _TAG_LINE, grounded_numbers, word_support

    src = f"{section_title or ''}\n{section_text}"
    stems = _stems(src)
    return [{"text": f, "numbers_in_section": grounded_numbers(f, src), "support": round(word_support(f, stems), 2),
             "tag": bool(_TAG_LINE.match(f))} for f in facts]


def _connect(url: str):
    import psycopg
    from pgvector.psycopg import register_vector

    conn = psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"))
    register_vector(conn)
    return conn


def tenant_id_of(conn, tenant: str) -> uuid.UUID:
    """A tenant by id or by name."""
    try:
        return uuid.UUID(tenant)
    except ValueError:
        row = conn.execute("SELECT id FROM tenants WHERE name = %s", (tenant,)).fetchone()
        if not row:
            raise SystemExit(f"no tenant named {tenant!r}") from None
        return row[0]


def write(conn, rows: list[dict[str, Any]], embedder=None) -> int:
    """Stores rows (dicts with the table's columns) and commits; a row whose section already has facts for its
    signature is left as it is. Returns the number of rows added."""
    if not rows:
        return 0
    vecs: list[Any] = [None] * len(rows)
    if embedder is not None:
        idx = [i for i, r in enumerate(rows) if r["text"]]
        for i, v in zip(idx, embedder.embed([rows[i]["text"] for i in idx]), strict=True):
            vecs[i] = v
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS stage_section_facts (LIKE section_facts INCLUDING DEFAULTS) ON COMMIT DELETE ROWS")
        with cur.copy(f"COPY stage_section_facts ({COLS}) FROM STDIN WITH (FORMAT BINARY)") as cp:
            cp.set_types(TYPES)
            for r, v in zip(rows, vecs, strict=True):
                cp.write_row((r.get("id") or uuid.uuid4(), r["tenant_id"], r["section_id"], r["document_id"], r["scope_id"], r["sensitivity"],
                              r["extractor"][:200], r["signature"], Jsonb(r["settings"]), r["section_sha256"], r["input_sha256"], r["status"],
                              Jsonb(r["facts"]), r["text"], r["n_facts"], r.get("prompt_tokens", 0), r.get("output_tokens", 0), v))
        cur.execute(f"INSERT INTO section_facts ({COLS}, tsv) SELECT {COLS}, {TSV} FROM stage_section_facts "
                    "ON CONFLICT (section_id, signature) DO NOTHING")
        added = cur.rowcount
    conn.commit()
    return added


def _row(sec: dict[str, Any], *, tenant_id, extractor: str, sig: str, settings: dict, inp: str, status: str, facts: list[str],
         prompt_tokens: int = 0, output_tokens: int = 0, checks: list[dict] | None = None) -> dict[str, Any]:
    checks = checks if checks is not None else checked(facts, sec["title"], sec["text"])
    return {"tenant_id": tenant_id, "section_id": sec["section_id"], "document_id": sec["document_id"], "scope_id": sec["scope_id"],
            "sensitivity": sec["sensitivity"], "extractor": extractor, "signature": sig, "settings": settings, "section_sha256": sec["sha"],
            "input_sha256": inp, "status": status, "facts": checks, "text": "\n".join(c["text"] for c in checks), "n_facts": len(checks),
            "prompt_tokens": prompt_tokens, "output_tokens": output_tokens}


# ------------------------------------------------------------------ import a facts file
def import_file(conn, tenant_id: uuid.UUID, work: Path, facts_file: Path, embedder=None, batch: int = 2000, log=print) -> dict[str, Any]:
    """Stores the facts of a ``cie.eval.extract_facts run`` file, matched to the sections of this tenant's current document
    versions by document and position."""
    from cie.eval.extract_facts import load_facts, load_jsonl, without_repeats

    meta_file = facts_file.with_suffix(".run.json")
    if not meta_file.exists():
        raise SystemExit(f"{meta_file} is missing: the settings the facts were made with are unknown")
    meta = json.loads(meta_file.read_text())
    if not meta.get("signature"):
        raise SystemExit(f"{meta_file} has no signature: re-run the extraction with this version of cie.eval.extract_facts")
    settings = {**meta["signature"], "model_repo": meta.get("model_repo")}
    sig = signature(settings)
    extractor = str(meta.get("model_repo") or meta["signature"]["model"])
    passages = load_jsonl(work / "passages.jsonl")
    if meta["signature"].get("repeats_removed"):
        passages = without_repeats(passages)  # as the run did, so the input hash is of what the model was given
    by_id = {p["id"]: p for p in passages}
    rows = load_facts(facts_file)
    stats: Counter = Counter(rows=len(rows))
    dsids = sorted({p["doc"] for p in passages})
    secs: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for i in range(0, len(dsids), 5000):
        for r in conn.execute(
                "SELECT d.extra->>'dsid', s.order_index, s.id, s.document_id, s.scope_id, s.sensitivity, s.text_sha256, s.title, s.text "
                "FROM sections s JOIN documents d ON d.id = s.document_id "
                "WHERE d.tenant_id = %s AND d.deleted_at IS NULL AND d.extra->>'dsid' = ANY(%s) "
                "AND NOT EXISTS (SELECT 1 FROM documents n WHERE n.previous_version_id = d.id)", (tenant_id, dsids[i:i + 5000])):
            secs.setdefault((r[0], r[1]), []).append({"section_id": r[2], "document_id": r[3], "scope_id": r[4], "sensitivity": r[5],
                                                      "sha": r[6], "title": r[7] or "", "text": r[8]})
    out: list[dict[str, Any]] = []
    for row in rows:
        p = by_id.get(row["id"])
        st = status_of(row.get("finish_reason"), len(row.get("facts") or []))
        if st is None:
            stats["failed_in_file"] += 1  # left pending: the next run asks again
            continue
        if p is None:
            stats["passage_unknown"] += 1
            continue
        targets = secs.get((p["doc"], p["k"]), [])
        if not targets:
            stats["no_such_section"] += 1  # the document is not in this memory bank
            continue
        sha = hashlib.sha256(p["text"].encode()).hexdigest()
        inp = input_sha256(p)
        for sec in targets:
            if sec["sha"] != sha:
                stats["stale"] += 1  # the section's text is not what the model read
                continue
            out.append(_row(sec, tenant_id=tenant_id, extractor=extractor, sig=sig, settings=settings, inp=inp, status=st,
                            facts=row.get("facts") or [], prompt_tokens=row.get("prompt_tokens") or 0, output_tokens=row.get("output_tokens") or 0))
        if len(out) >= batch:
            stats["added"] += write(conn, out, embedder)
            stats["matched"] += len(out)
            out = []
    stats["added"] += write(conn, out, embedder)
    stats["matched"] += len(out)
    stats["already_stored"] = stats["matched"] - stats["added"]
    res = {"extractor": extractor, "signature": sig, **stats}
    log(f"  imported {facts_file.name}: {res}")
    return res


# ------------------------------------------------------------------ the queue
def pending(conn, tenant_id: uuid.UUID, sig: str, limit: int = 0) -> list[dict[str, Any]]:
    """The current sections (latest document versions) that have no facts for this signature, in document order,
    each with the text of the section before it (for leaving out repeated text)."""
    q = ("SELECT * FROM (SELECT s.id, s.document_id, s.order_index, s.scope_id, s.sensitivity, s.text_sha256, s.title, s.text, "
         "coalesce(d.extra->>'display_title', d.title), d.source, "
         "lag(s.text) OVER (PARTITION BY s.document_id ORDER BY s.order_index) "
         "FROM sections s JOIN documents d ON d.id = s.document_id "
         "WHERE s.tenant_id = %s AND d.deleted_at IS NULL "
         "AND NOT EXISTS (SELECT 1 FROM documents n WHERE n.previous_version_id = d.id)) x "
         "WHERE NOT EXISTS (SELECT 1 FROM section_facts f WHERE f.section_id = x.id AND f.signature = %s) "
         "ORDER BY x.document_id, x.order_index" + (" LIMIT %s" if limit else ""))
    args: tuple = (tenant_id, sig, limit) if limit else (tenant_id, sig)
    return [{"section_id": r[0], "document_id": r[1], "k": r[2], "scope_id": r[3], "sensitivity": r[4], "sha": r[5], "title": r[6] or "",
             "text": r[7], "doc_title": r[8] or "", "source": r[9] or "", "prev_text": r[10]} for r in conn.execute(q, args)]


def extract(conn, tenant_id: uuid.UUID, generate: Callable[[list[list[dict[str, str]]]], list[dict[str, Any]]], settings: dict[str, Any],
            prompt: str = "full", strip: bool = False, chunk: int = 4096, limit: int = 0, embedder=None, log=print) -> dict[str, Any]:
    """Facts for the sections that have none for this extractor, a chunk at a time, committed after each chunk.

    Before asking the model, a section whose input matches facts already stored under this signature takes them. A
    section that only repeats the previous one (with ``strip``) is stored as skipped. A failed request stores nothing,
    so the section stays pending.
    """
    from cie.eval.extract_facts import conversation, parse_facts, repeated_start

    sig = signature(settings)
    extractor = str(settings.get("model_repo") or settings.get("model"))
    todo = pending(conn, tenant_id, sig, limit)
    stats: Counter = Counter(pending=len(todo))
    log(f"  {extractor} ({sig}): {len(todo):,} sections without facts")
    t0 = time.time()
    for i in range(0, len(todo), chunk):
        part = todo[i: i + chunk]
        for p in part:
            n = repeated_start(p["prev_text"], p["text"]) if strip and p["prev_text"] else 0
            if n:
                p["fresh"] = p["text"][n:].lstrip()
            p["input"] = input_sha256(p)
        known: dict[str, tuple] = {}
        for r in conn.execute("SELECT DISTINCT ON (input_sha256) input_sha256, status, facts FROM section_facts "
                              "WHERE tenant_id = %s AND signature = %s AND input_sha256 = ANY(%s)", (tenant_id, sig, [p["input"] for p in part])):
            known[r[0]] = (r[1], r[2])
        rows, ask = [], []
        for p in part:
            if p["input"] in known:
                st, checks = known[p["input"]]
                rows.append(_row(p, tenant_id=tenant_id, extractor=extractor, sig=sig, settings=settings, inp=p["input"], status=st, facts=[],
                                 checks=checks))
                stats["reused"] += 1
            elif p.get("fresh", "x") == "":
                rows.append(_row(p, tenant_id=tenant_id, extractor=extractor, sig=sig, settings=settings, inp=p["input"], status="skipped", facts=[]))
                stats["skipped"] += 1
            else:
                ask.append(p)
        res = generate([conversation(p, prompt) for p in ask]) if ask else []
        for p, r in zip(ask, res, strict=True):
            facts, _counts = parse_facts(r["text"])
            st = status_of(r.get("finish_reason"), len(facts))
            if st is None:
                stats["failed"] += 1
                continue
            rows.append(_row(p, tenant_id=tenant_id, extractor=extractor, sig=sig, settings=settings, inp=p["input"], status=st, facts=facts,
                             prompt_tokens=r.get("prompt_tokens", 0), output_tokens=r.get("output_tokens", 0)))
            stats["asked"] += 1
        stats["added"] += write(conn, rows, embedder)
        log(f"  chunk {i // chunk + 1}: {len(part):,} sections, {stats['added']:,} stored so far ({time.time() - t0:,.0f} s)")
    res = {"extractor": extractor, "signature": sig, **stats}
    log(f"  done: {res}")
    return res


# ------------------------------------------------------------------ reading
def facts_for_sections(session, tenant_id: uuid.UUID, vis, section_ids: Iterable[uuid.UUID], sig: str | None = None) -> dict[uuid.UUID, dict]:
    """The stored facts of these sections that ``vis`` may read: the given signature's, or else each section's newest."""
    from sqlalchemy import select

    from cie.core.models import SectionFacts

    ids = list(section_ids)
    if not ids:
        return {}
    stmt = (select(SectionFacts).where(SectionFacts.tenant_id == tenant_id, SectionFacts.section_id.in_(ids),
                                       vis.sql_filter(SectionFacts.scope_id, SectionFacts.sensitivity))
            .order_by(SectionFacts.created_at.desc()))
    if sig:
        stmt = stmt.where(SectionFacts.signature == sig)
    out: dict[uuid.UUID, dict] = {}
    for f in session.scalars(stmt):
        out.setdefault(f.section_id, {"extractor": f.extractor, "signature": f.signature, "status": f.status, "facts": f.facts})
    return out


def status(conn, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Per extractor: sections with facts, by status, and how many current sections have none yet."""
    total = conn.execute("SELECT count(*) FROM sections s JOIN documents d ON d.id = s.document_id WHERE s.tenant_id = %s "
                         "AND d.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM documents n WHERE n.previous_version_id = d.id)",
                         (tenant_id,)).fetchone()[0]
    out = []
    for sig, extractor, st, n, lines in conn.execute(
            "SELECT signature, extractor, status, count(*), sum(n_facts) FROM section_facts WHERE tenant_id = %s "
            "GROUP BY signature, extractor, status ORDER BY signature, status", (tenant_id,)):
        if not out or out[-1]["signature"] != sig:
            out.append({"signature": sig, "extractor": extractor, "sections": 0, "fact_lines": 0, "by_status": {}})
        out[-1]["by_status"][st] = n
        out[-1]["sections"] += n
        out[-1]["fact_lines"] += int(lines or 0)
    for o in out:
        covered = conn.execute("SELECT count(*) FROM section_facts f JOIN documents d ON d.id = f.document_id WHERE f.tenant_id = %s "
                               "AND f.signature = %s AND d.deleted_at IS NULL "
                               "AND NOT EXISTS (SELECT 1 FROM documents n WHERE n.previous_version_id = d.id)",
                               (tenant_id, o["signature"])).fetchone()[0]
        o["pending"] = total - covered
    return [{"current_sections": total}, *out]


# ------------------------------------------------------------------ command line
def _embedder(on: bool, cache: str | None):
    if not on:
        return None
    from cie.ingest.bulk import CachedEmbedder
    from cie.memory.embeddings import get_embedding_provider

    return CachedEmbedder(get_embedding_provider(), Path(cache) if cache else None)


def main(argv: Iterable[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(description="facts extracted by a language model, stored in the memory bank")
    ap.add_argument("--db", default=None, help="database URL (default: the configured one)")
    ap.add_argument("--tenant", required=True, help="tenant id or name")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="sections with facts, per extractor, and how many are still pending")
    im = sub.add_parser("import", help="store a facts file written by cie.eval.extract_facts run")
    im.add_argument("--work", required=True, help="the extraction's work folder (passages.jsonl)")
    im.add_argument("--facts", nargs="+", required=True, help="facts_*.jsonl files (each with its .run.json)")
    ex = sub.add_parser("extract", help="extract facts for the sections that have none for this extractor")
    ex.add_argument("--model", default="llama-3.1-8b")
    ex.add_argument("--backend", choices=["vllm", "openai"], default="vllm")
    ex.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    ex.add_argument("--concurrency", type=int, default=4)
    ex.add_argument("--max-tokens", type=int, default=768)
    ex.add_argument("--quantization", default="none")
    ex.add_argument("--prompt", choices=["full", "short"], default="full")
    ex.add_argument("--strip-overlap", action="store_true")
    ex.add_argument("--gpu-mem", type=float, default=0.92)
    ex.add_argument("--max-model-len", type=int, default=4096)
    ex.add_argument("--max-num-seqs", type=int, default=None)
    ex.add_argument("--max-num-batched-tokens", type=int, default=None)
    ex.add_argument("--chunk", type=int, default=4096)
    ex.add_argument("--limit", type=int, default=0)
    for p in (im, ex):
        p.add_argument("--embed", action="store_true", help="also embed the facts (the configured embedding provider)")
        p.add_argument("--embed-cache", default=None)
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.db is None:
        from cie.core.settings import get_settings

        a.db = get_settings().database_url
    conn = _connect(a.db)
    tid = tenant_id_of(conn, a.tenant)
    if a.cmd == "status":
        res = status(conn, tid)
        print(json.dumps(res, indent=1, default=str))
        return res
    if a.cmd == "import":
        emb = _embedder(a.embed, a.embed_cache)
        return [import_file(conn, tid, Path(a.work), Path(f), emb) for f in a.facts]
    from cie.eval import extract_facts as ef

    if a.backend == "vllm":
        repo, rev = ef.resolve_model(a.model)
        engine = ef._vllm_engine(repo, rev, a)
        model_repo = f"{repo}@{rev}" if rev else repo
        generate = lambda convs: ef._vllm_generate(engine, convs, a)  # noqa: E731
    else:
        model_repo = f"{a.model} at {a.base_url}"
        generate = lambda convs: ef._openai_generate(convs, a)  # noqa: E731
    settings = {**ef.run_signature(a.model, a.max_tokens, a.quantization, a.prompt, a.strip_overlap), "model_repo": model_repo}
    return extract(conn, tid, generate, settings, a.prompt, a.strip_overlap, a.chunk, a.limit, _embedder(a.embed, a.embed_cache))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if main() is not None else 1)
