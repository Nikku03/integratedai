"""BM25 keyword search over the memory bank, with Tantivy (an embedded, Lucene-like search library).

PostgreSQL full-text ranking scores every row that matches a query before it can return the best k, so a question
with a common word waits for thousands of rows to be ranked (at 50,000 documents the keyword step took up to 5.6 s at
p95). A BM25 index with block-max pruning returns the best k without scoring every match.

How it fits the memory bank:

* **One index per tenant**, on the local filesystem under ``CIE_LEXICAL_INDEX_DIR``. It holds each record and section
  once: its id, whether it is a record or a section, the document it comes from, a ``title`` (a record's summary and
  keywords, or a section's title) and a ``body`` (a record's detail, or a section's text). It holds no permissions.
* **BM25 proposes, SQL disposes.** The index returns the tenant's best candidates. Every candidate then passes the
  same SQL filter as full-text search (scope, clearance, access list, deletion, supersession, validity time) before it
  is returned. When too few pass (a principal who sees a small share of the tenant), more candidates are fetched,
  4 times as many each round up to ``MAX_FETCH``, like the vector index's iterative scan.
* **Nothing committed is invisible.** Triggers on ``memory_records`` and ``sections`` put every new or re-worded row
  in ``lexical_queue``, in the writing transaction (``install``). ``sync`` moves queued rows into the index. Until
  then search scores them straight from the database (the "tail"), with the same BM25 formula and the index's own
  statistics, and ignores the index's older copy of a re-worded row.
* **Rebuilds are atomic.** ``build`` indexes one database snapshot into a new version directory, points ``CURRENT``
  at it, and removes from the queue exactly the rows that snapshot contained. Readers switch on their next search.
* **Fallback.** A tenant without a ready index, or with more than ``lexical_tail_max`` rows waiting, is served by
  PostgreSQL full text (``search`` returns None).

The BM25 parameters are Tantivy's (k1 = 1.2, b = 0.75). A title match weighs 2.5 times a body match, the ratio of
the full-text weights A and B (1.0 and 0.4) that the full-text ranking used.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from cie.core.models import MemoryRecord, Section
from cie.core.settings import Settings, get_settings
from cie.retrieval.lexical_models import LexicalQueue, LexicalState

TITLE_BOOST = 2.5
K1, B = 1.2, 0.75
MAX_FETCH = 5000
BATCH = 5000  # rows per sync step
RELOAD_SECONDS = 1.0  # a reader looks for newly committed segments at most this often
_BODY_CHARS = 20000  # as the full-text vector of a record's detail

KINDS = {"r": MemoryRecord, "s": Section}


def _kind(model) -> str:
    return "r" if model.__tablename__ == "memory_records" else "s"


# ------------------------------------------------------------------ schema and text
@lru_cache(maxsize=1)
def schema():
    import tantivy

    sb = tantivy.SchemaBuilder()
    sb.add_text_field("id", stored=True, tokenizer_name="raw", index_option="basic")
    sb.add_text_field("kind", tokenizer_name="raw", index_option="basic")
    sb.add_text_field("doc", tokenizer_name="raw", index_option="basic")
    sb.add_text_field("title", tokenizer_name="en_stem", index_option="freq")
    sb.add_text_field("body", tokenizer_name="en_stem", index_option="freq")
    return sb.build()


@lru_cache(maxsize=1)
def _analyzer():
    """The ``en_stem`` pipeline of the index: split on non-alphanumerics, drop tokens over 40 bytes, lower-case,
    English Snowball stemmer. The tail and query terms go through it so they meet the index's terms."""
    import tantivy

    return (tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.simple()).filter(tantivy.Filter.remove_long(40))
            .filter(tantivy.Filter.lowercase()).filter(tantivy.Filter.stemmer("english")).build())


def analyze(s: str) -> list[str]:
    return _analyzer().analyze(s or "") if s else []


def record_text(summary: str | None, keywords: list[str] | None, detail: str | None) -> tuple[str, str]:
    return f"{summary or ''} {' '.join(keywords or [])}".strip(), (detail or "")[:_BODY_CHARS]


def section_text(title: str | None, body: str | None) -> tuple[str, str]:
    return title or "", body or ""


def query_terms(q: str) -> list[str]:
    """The question's content words (as full-text search takes them), then stemmed by the index's analyzer."""
    from cie.retrieval.lexical import _terms

    words = _terms(q) or [w.lower() for w in re.findall(r"[A-Za-z0-9]+", q or "")]
    out: list[str] = []
    for w in words:
        for t in analyze(w):
            if t not in out:
                out.append(t)
    return out


# ------------------------------------------------------------------ triggers
INSTALL_SQL = """
CREATE OR REPLACE FUNCTION cie_lexical_enqueue() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO lexical_queue (tenant_id, kind, row_id) SELECT n.tenant_id, TG_ARGV[0], n.id FROM new_rows n;
  ELSIF TG_ARGV[0] = 'r' THEN
    INSERT INTO lexical_queue (tenant_id, kind, row_id)
      SELECT n.tenant_id, 'r', n.id FROM new_rows n JOIN old_rows o ON o.id = n.id
      WHERE (n.summary, n.detail, n.keywords) IS DISTINCT FROM (o.summary, o.detail, o.keywords);
  ELSE
    INSERT INTO lexical_queue (tenant_id, kind, row_id)
      SELECT n.tenant_id, 's', n.id FROM new_rows n JOIN old_rows o ON o.id = n.id
      WHERE (n.title, n.text) IS DISTINCT FROM (o.title, o.text);
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_records_lexical_ins ON memory_records;
CREATE TRIGGER trg_records_lexical_ins AFTER INSERT ON memory_records REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION cie_lexical_enqueue('r');
DROP TRIGGER IF EXISTS trg_records_lexical_upd ON memory_records;
CREATE TRIGGER trg_records_lexical_upd AFTER UPDATE ON memory_records REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION cie_lexical_enqueue('r');
DROP TRIGGER IF EXISTS trg_sections_lexical_ins ON sections;
CREATE TRIGGER trg_sections_lexical_ins AFTER INSERT ON sections REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION cie_lexical_enqueue('s');
DROP TRIGGER IF EXISTS trg_sections_lexical_upd ON sections;
CREATE TRIGGER trg_sections_lexical_upd AFTER UPDATE ON sections REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION cie_lexical_enqueue('s');
"""

UNINSTALL_SQL = """
DROP TRIGGER IF EXISTS trg_records_lexical_ins ON memory_records;
DROP TRIGGER IF EXISTS trg_records_lexical_upd ON memory_records;
DROP TRIGGER IF EXISTS trg_sections_lexical_ins ON sections;
DROP TRIGGER IF EXISTS trg_sections_lexical_upd ON sections;
DROP FUNCTION IF EXISTS cie_lexical_enqueue();
"""


def install(conn) -> None:
    """Create (or replace) the queue triggers. ``conn`` is a SQLAlchemy connection or a psycopg connection."""
    if hasattr(conn, "exec_driver_sql"):
        conn.exec_driver_sql(INSTALL_SQL)
    else:
        conn.execute(INSTALL_SQL)


# ------------------------------------------------------------------ files
def root(settings: Settings | None = None) -> Path:
    return Path((settings or get_settings()).lexical_index_dir)


def tenant_dir(tenant_id: uuid.UUID, settings: Settings | None = None) -> Path:
    return root(settings) / str(tenant_id)


def current_version(d: Path) -> str | None:
    try:
        v = (d / "CURRENT").read_text().strip()
    except OSError:
        return None
    return v if v and (d / v).is_dir() else None


def _point(d: Path, version: str) -> None:
    tmp = d / f"CURRENT.{os.getpid()}.tmp"
    tmp.write_text(version)
    os.replace(tmp, d / "CURRENT")


def _read_stats(path: Path) -> dict[str, float]:
    try:
        return json.loads((path / "stats.json").read_text())
    except (OSError, ValueError):
        return {}


def _write_stats(path: Path, stats: dict[str, float]) -> None:
    tmp = path / "stats.json.tmp"
    tmp.write_text(json.dumps(stats))
    os.replace(tmp, path / "stats.json")


@dataclass
class _Reader:
    version: str
    path: Path
    index: Any
    checked: float = 0.0
    stats: dict[str, float] = field(default_factory=dict)


_readers: dict[str, _Reader] = {}
_lock = threading.Lock()


def _reader(tenant_id: uuid.UUID, settings: Settings | None = None) -> _Reader | None:
    import tantivy

    d = tenant_dir(tenant_id, settings)
    v = current_version(d)
    if v is None:
        return None
    key = str(d)
    now = time.monotonic()
    with _lock:
        r = _readers.get(key)
        if r is None or r.version != v:
            r = _Reader(v, d / v, tantivy.Index.open(str(d / v)), now, _read_stats(d / v))
            _readers[key] = r
        elif now - r.checked > RELOAD_SECONDS:
            r.index.reload()  # segments committed by sync since the last look
            r.stats = _read_stats(r.path)
            r.checked = now
    return r


# ------------------------------------------------------------------ search
def ready(session: Session, tenant_id: uuid.UUID, settings: Settings | None = None) -> bool:
    """A ready index whose waiting rows are few enough to score from the database."""
    settings = settings or get_settings()
    row = session.execute(text(
        "SELECT s.status, (SELECT count(*) FROM (SELECT 1 FROM lexical_queue q WHERE q.tenant_id = s.tenant_id LIMIT :m) x) "
        "FROM lexical_state s WHERE s.tenant_id = :t"), {"t": tenant_id, "m": settings.lexical_tail_max + 1}).first()
    return bool(row) and row[0] == "ready" and row[1] <= settings.lexical_tail_max and current_version(tenant_dir(tenant_id, settings)) is not None


def search(session: Session, model, q: str, base_filter, k: int, tenant_id: uuid.UUID, *, document_ids: list | None = None,
           settings: Settings | None = None, info: dict | None = None) -> list[tuple[uuid.UUID, float]] | None:
    """The best ``k`` rows of ``model`` for ``q`` that pass ``base_filter``, by BM25; None when the tenant has no
    ready index (the caller then uses full-text search)."""
    import tantivy

    settings = settings or get_settings()
    if not ready(session, tenant_id, settings):
        return None
    r = _reader(tenant_id, settings)
    if r is None:
        return None
    terms = query_terms(q)
    if info is not None:
        info.update({"engine": "bm25", "terms": len(terms)})
    if not terms:
        return []
    kind = _kind(model)
    sch = r.index.schema
    parts = [(tantivy.Occur.Must, r.index.parse_query(" ".join(terms), ["title", "body"], field_boosts={"title": TITLE_BOOST})),
             (tantivy.Occur.Must, tantivy.Query.term_query(sch, "kind", kind))]
    if document_ids:
        parts.append((tantivy.Occur.Must, tantivy.Query.term_set_query(sch, "doc", [str(d) for d in document_ids])))
    query = tantivy.Query.boolean_query(parts)
    searcher = r.index.searcher()

    queued, tail = _tail(session, model, kind, terms, base_filter, tenant_id, document_ids, searcher, r.stats)
    fetch, rounds = max(4 * k, 100), 0
    while True:
        rounds += 1
        res = searcher.search(query, fetch, count=False)
        raw = [(uuid.UUID(searcher.doc(a)["id"][0]), float(sc)) for sc, a in res.hits]
        raw = [(rid, sc) for rid, sc in raw if rid not in queued]  # a queued row is scored from its current text
        ids = [rid for rid, _ in raw]
        ok = set(session.scalars(select(model.id).where(model.id.in_(ids), base_filter))) if ids else set()
        hits = [(rid, sc) for rid, sc in raw if rid in ok]
        if len(hits) >= k or len(res.hits) < fetch or fetch >= MAX_FETCH:
            break
        fetch = min(fetch * 4, MAX_FETCH)
    if info is not None:
        info.update({"fetched": len(res.hits), "rounds": rounds, "tail": len(tail), "queued": len(queued)})
    return sorted(hits + tail, key=lambda x: -x[1])[:k]


def _tail(session: Session, model, kind: str, terms: list[str], base_filter, tenant_id: uuid.UUID, document_ids,
          searcher, stats: dict[str, float]) -> tuple[set[uuid.UUID], list[tuple[uuid.UUID, float]]]:
    """Rows waiting in the queue: all their ids (the index's copy of them is out of date or missing), and the BM25
    score of those that pass ``base_filter``, computed from their text in the database."""
    queued = set(session.scalars(select(LexicalQueue.row_id).where(LexicalQueue.tenant_id == tenant_id, LexicalQueue.kind == kind)))
    if not queued:
        return queued, []
    if kind == "r":
        cols = (MemoryRecord.id, MemoryRecord.summary, MemoryRecord.keywords, func.left(MemoryRecord.detail, _BODY_CHARS))
        doc_col = MemoryRecord.source_document_id
    else:
        cols = (Section.id, Section.title, Section.text)
        doc_col = Section.document_id
    stmt = select(*cols).where(model.id.in_(queued), base_filter)
    if document_ids:
        stmt = stmt.where(doc_col.in_(list(document_ids)))
    n = max(searcher.num_docs, 1)
    idf = {}
    for f in ("title", "body"):
        for t in terms:
            df = searcher.doc_freq(f, t)
            idf[(f, t)] = math.log(1 + (n - df + 0.5) / (df + 0.5))
    avg = {"title": stats.get("title_tokens", 0) / max(stats.get("docs", 0), 1) or 1.0,
           "body": stats.get("body_tokens", 0) / max(stats.get("docs", 0), 1) or 1.0}
    out = []
    for row in session.execute(stmt):
        title, body = record_text(row[1], row[2], row[3]) if kind == "r" else section_text(row[1], row[2])
        score = 0.0
        for fname, s, boost in (("title", title, TITLE_BOOST), ("body", body, 1.0)):
            toks = analyze(s)
            if not toks:
                continue
            tf = Counter(toks)
            dl = len(toks)
            for t in terms:
                f = tf.get(t)
                if f:
                    score += boost * idf[(fname, t)] * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / avg[fname]))
        if score > 0:
            out.append((row[0], score))
    return queued, out


# ------------------------------------------------------------------ writing
def _lock_key(tenant_id: uuid.UUID) -> int:
    return int.from_bytes(hashlib.blake2b(f"cie-lexical:{tenant_id}".encode(), digest_size=8).digest(), "big", signed=True)


def _doc(tantivy, rid, kind, doc, title, body):
    return tantivy.Document(id=str(rid), kind=kind, doc=str(doc or ""), title=title, body=body)


def build(url: str, tenant_id: uuid.UUID, settings: Settings | None = None, log=print, heap_mb: int = 512) -> dict[str, Any]:
    """Index every record and section of the tenant from one database snapshot, switch readers to it, and drop from
    the queue exactly the rows the snapshot held. Waits for a build or sync of the same tenant in progress."""
    import psycopg
    import tantivy

    settings = settings or get_settings()
    url = url.replace("postgresql+psycopg://", "postgresql://")
    t0 = time.perf_counter()
    d = tenant_dir(tenant_id, settings)
    d.mkdir(parents=True, exist_ok=True)
    version = f"v{int(time.time() * 1000)}"
    path = d / version
    with psycopg.connect(url, autocommit=True) as lockc:
        lockc.execute("SELECT pg_advisory_lock(%s)", (_lock_key(tenant_id),))
        try:
            # the state row makes search consider the tenant once it is ready; a rebuild keeps serving the old version
            lockc.execute("INSERT INTO lexical_state (tenant_id, status, docs, detail) VALUES (%s, 'building', 0, '{}') "
                          "ON CONFLICT (tenant_id) DO NOTHING", (tenant_id,))
            with psycopg.connect(url) as c:
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                path.mkdir()
                index = tantivy.Index(schema(), path=str(path))
                writer = index.writer(heap_mb * 1_000_000, max(1, min(4, (os.cpu_count() or 2) - 1)))
                stats = {"docs": 0, "title_tokens": 0, "body_tokens": 0}
                counts = {"r": 0, "s": 0}
                for kind, sql in (("r", "SELECT id, source_document_id, summary, keywords, left(detail, %s) FROM memory_records WHERE tenant_id = %s"),
                                  ("s", "SELECT id, document_id, title, text, NULL FROM sections WHERE tenant_id = %s")):
                    with c.cursor(name=f"lex_{kind}") as cur:
                        cur.itersize = 5000
                        cur.execute(sql, (_BODY_CHARS, tenant_id) if kind == "r" else (tenant_id,))
                        for rid, doc, a, b_, det in cur:
                            title, body = record_text(a, b_, det) if kind == "r" else section_text(a, b_)
                            writer.add_document(_doc(tantivy, rid, kind, doc, title, body))
                            stats["docs"] += 1
                            stats["title_tokens"] += len(analyze(title))
                            stats["body_tokens"] += len(analyze(body))
                            counts[kind] += 1
                writer.commit()
                writer.wait_merging_threads()
                _write_stats(path, stats)
                _point(d, version)  # before the queue is cleared: a crash in between only leaves rows scored twice
                deleted = c.execute("DELETE FROM lexical_queue WHERE tenant_id = %s", (tenant_id,)).rowcount
                size = sum(f.stat().st_size for f in path.iterdir() if f.is_file())
                detail = {**stats, "records": counts["r"], "sections": counts["s"], "bytes": size,
                          "seconds": round(time.perf_counter() - t0, 1)}
                c.execute("UPDATE lexical_state SET status = 'ready', version = %s, built_at = now(), docs = %s, detail = %s "
                          "WHERE tenant_id = %s", (version, stats["docs"], json.dumps(detail), tenant_id))
                c.commit()
        finally:
            lockc.execute("SELECT pg_advisory_unlock(%s)", (_lock_key(tenant_id),))
    for old in d.iterdir():  # readers still holding an old version keep their open files
        if old.is_dir() and old.name != version:
            shutil.rmtree(old, ignore_errors=True)
    log(f"  BM25 index of tenant {tenant_id}: {counts['r']:,} records and {counts['s']:,} sections, "
        f"{size / 1e6:.1f} MB, {detail['seconds']} s ({deleted:,} queued rows taken in)")
    return {"version": version, **detail, "queue_cleared": deleted}


def sync(url: str, tenant_id: uuid.UUID, settings: Settings | None = None, batch: int = BATCH, max_batches: int = 1000) -> int:
    """Move queued rows of one tenant into its index. Returns the number taken in; 0 when another process holds the
    tenant or it has no index."""
    import psycopg
    import tantivy

    settings = settings or get_settings()
    url = url.replace("postgresql+psycopg://", "postgresql://")
    d = tenant_dir(tenant_id, settings)
    done = 0
    with psycopg.connect(url, autocommit=True) as lockc:
        if not lockc.execute("SELECT pg_try_advisory_lock(%s)", (_lock_key(tenant_id),)).fetchone()[0]:
            return 0
        try:
            v = current_version(d)
            if v is None:
                return 0
            path = d / v
            index = tantivy.Index.open(str(path))
            stats = _read_stats(path) or {"docs": 0, "title_tokens": 0, "body_tokens": 0}
            for _ in range(max_batches):
                with psycopg.connect(url) as c:
                    q = c.execute("SELECT id, kind, row_id FROM lexical_queue WHERE tenant_id = %s ORDER BY id LIMIT %s",
                                  (tenant_id, batch)).fetchall()
                    if not q:
                        break
                    rec_ids = list({r for _, k, r in q if k == "r"})
                    sec_ids = list({r for _, k, r in q if k == "s"})
                    rows: list[tuple] = []
                    if rec_ids:
                        rows += [("r", *x) for x in c.execute("SELECT id, source_document_id, summary, keywords, left(detail, %s) "
                                                              "FROM memory_records WHERE id = ANY(%s)", (_BODY_CHARS, rec_ids))]
                    if sec_ids:
                        rows += [("s", *x) for x in c.execute("SELECT id, document_id, title, text, NULL FROM sections WHERE id = ANY(%s)",
                                                              (sec_ids,))]
                    writer = index.writer(128_000_000, 1)
                    for rid in rec_ids + sec_ids:
                        writer.delete_documents_by_term("id", str(rid))  # the older copy of a re-worded row
                    for kind, rid, doc, a, b_, det in rows:
                        title, body = record_text(a, b_, det) if kind == "r" else section_text(a, b_)
                        writer.add_document(_doc(tantivy, rid, kind, doc, title, body))
                        stats["docs"] += 1
                        stats["title_tokens"] += len(analyze(title))
                        stats["body_tokens"] += len(analyze(body))
                    writer.commit()
                    writer.wait_merging_threads()
                    _write_stats(path, stats)
                    c.execute("DELETE FROM lexical_queue WHERE id = ANY(%s)", ([i for i, _, _ in q],))
                    c.commit()
                    done += len(q)
        finally:
            lockc.execute("SELECT pg_advisory_unlock(%s)", (_lock_key(tenant_id),))
    return done


def sync_all(url: str, settings: Settings | None = None) -> dict[str, int]:
    """Sync every tenant with an index and rows waiting; drop queued rows of tenants that have no index (a build
    reads them from the database anyway)."""
    import psycopg

    url = url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DELETE FROM lexical_queue q WHERE NOT EXISTS (SELECT 1 FROM lexical_state s WHERE s.tenant_id = q.tenant_id)")
        tenants = [t for (t,) in c.execute("SELECT DISTINCT q.tenant_id FROM lexical_queue q JOIN lexical_state s "
                                           "ON s.tenant_id = q.tenant_id AND s.status = 'ready'")]
    return {str(t): sync(url, t, settings) for t in tenants}


def status(session: Session, settings: Settings | None = None) -> list[dict[str, Any]]:
    out = []
    for st in session.scalars(select(LexicalState)):
        waiting = session.scalar(select(func.count()).select_from(LexicalQueue).where(LexicalQueue.tenant_id == st.tenant_id))
        out.append({"tenant_id": str(st.tenant_id), "status": st.status, "version": st.version, "built_at": st.built_at,
                    "docs": st.docs, "waiting": waiting, "current": current_version(tenant_dir(st.tenant_id, settings)),
                    "bytes": (st.detail or {}).get("bytes")})
    return out
