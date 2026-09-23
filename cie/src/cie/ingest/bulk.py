"""Bulk writer for ``DocMemory`` batches: the full memory bank at corpus scale.

Per batch (binary COPY, no ORM): blobs, documents, sections, the document record, typed
records, first-seen entities and projects, and the links inside a document (typed
record ``part_of`` document, document ``part_of`` project, ``mentions`` of people and
companies; ``entity_ids`` set on every record that names them).

Text-search vectors are computed as rows are inserted (COPY into a session staging
table, then ``INSERT ... SELECT`` with ``to_tsvector``), so no pass rewrites the tables.
A batch that the database rejects is retried document by document; a document that
still fails is skipped, counted and logged, and nothing links to it.

At the end (``finish``):
* explicit references between documents are resolved (a ticket key, a pull request, a
  wiki page, a CRM account) into ``references`` / ``depends_on`` links. A key carried by
  several documents resolves to the one most similar to the citing document, or to
  none when no holder stands out; a key carried by many is ambiguous and is skipped;
* documents that carry the same identifier are linked only when they plausibly describe
  the same object (same title, or similar memory cards); identifiers collide across
  unrelated records in real exports;
* documents of the same project are chained in time order (``relates_to``);
* near-duplicate documents are found by mutual nearest neighbours of their memory-card
  embeddings (GPU when available) and linked; their aligned sentences that differ in
  numbers (identifiers, times and versions ignored) become disputed ``fact`` records,
  each in its own document's scope, joined by ``contradicts`` edges whose text quotes
  neither side. A ``contradiction`` record quoting both is written only when both
  documents share a scope, at the stricter of their sensitivities;
* entity and project records get their aggregate detail (roles, documents, sources)
  and the sensitivity of the least restricted document that names them; the aggregate
  counts only documents at that sensitivity;
* statistics; for large loads the vector and text indexes are then built by the caller.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from cie.core.models import LinkKind, RecordType, VerificationStatus
from cie.core.util import utcnow
from cie.ingest.builder import DocMemory, RecOut, short
from cie.memory.entities import normalise
from cie.memory.glyph import _WHY_BY_TYPE, EvidencePointer, Glyph

NEAR_DUPLICATE = 0.92  # cosine of memory-card embeddings, mutual nearest neighbours only
MAX_KEY_HOLDERS = 3  # an identifier carried by more documents than this is ambiguous
SAME_OBJECT_SAME_SOURCE = 0.92  # two records of one system sharing a key are one object only if their cards (nearly) match
SAME_OBJECT_CROSS_SOURCE = 0.80  # the same key in two systems (a Jira key cited in Linear) needs less
REF_MARGIN = 0.03  # a citation of a shared key resolves to the most similar holder only if it leads by this much
DECISION_TYPES = ("decision", "metric")  # records whose own date is the moment they took effect
MAX_CONFLICTS_PER_PAIR = 2
REC_COLS = ("id, tenant_id, scope_id, type, summary, content, detail, source_document_id, source_locations, event_time, valid_from, valid_to, "
            "recorded_at, producing_agent, confidence, verification, sensitivity, acl, version, family_id, entity_ids, keywords, glyph, embedding, "
            "content_sha256")
REC_TSV = ("setweight(to_tsvector('english', summary), 'A') || setweight(to_tsvector('english', array_to_string(keywords, ' ')), 'A') || "
           "setweight(to_tsvector('english', left(detail, 20000)), 'B')")
SEC_COLS = ("id, tenant_id, document_id, extraction_id, scope_id, order_index, title, level, page_start, page_end, text, text_sha256, "
            "token_estimate, spans, embedding, sensitivity")
SEC_TYPES = ["uuid", "uuid", "uuid", "uuid", "uuid", "int4", "text", "int4", "int4", "int4", "text", "text", "int4", "jsonb", "vector", "int4"]
SEC_TSV = "setweight(to_tsvector('english', coalesce(title, '')), 'A') || setweight(to_tsvector('english', text), 'B')"
BLOB_COLS = "id, tenant_id, sha256, size_bytes, media_type, storage_uri, encrypted, created_at"
BLOB_TYPES = ["uuid", "uuid", "text", "int8", "text", "text", "bool", "timestamptz"]
WRITE_ERRORS = (psycopg.Error, UnicodeError, ValueError)
REC_TYPES = ["uuid", "uuid", "uuid", "record_type", "text", "jsonb", "text", "uuid", "jsonb", "timestamptz", "timestamptz", "timestamptz",
             "timestamptz", "text", "float8", "verification_status", "int4", "jsonb", "int4", "uuid", "jsonb", "varchar[]", "jsonb", "vector", "text"]
PRODUCER = "structured_ingest_v1"


# ------------------------------------------------------------------ embedding cache
class CachedEmbedder:
    """Wraps an embedding provider with an on-disk cache keyed by (model, text), so a
    re-load after a change to linking or scoring never re-embeds unchanged text."""

    def __init__(self, embedder, path: Path | None):
        self.embedder = embedder
        self.name = getattr(embedder, "name", "?")
        self.model = getattr(embedder, "model_name", None) or getattr(embedder, "model", None) or self.name
        self.db = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(path))
            self.db.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, v BLOB)")
        self.hits = self.misses = 0

    def _key(self, t: str) -> str:
        return hashlib.sha1(f"{self.model}\x00{t}".encode()).hexdigest()

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        keys = [self._key(t) for t in texts]
        found: dict[str, np.ndarray] = {}
        if self.db is not None:
            uniq = list(dict.fromkeys(keys))
            for i in range(0, len(uniq), 800):
                part = uniq[i:i + 800]
                q = f"SELECT k, v FROM emb WHERE k IN ({','.join('?' * len(part))})"
                for k, v in self.db.execute(q, part):
                    found[k] = np.frombuffer(v, dtype=np.float16).astype(np.float32)
        todo = [(i, t) for i, (t, k) in enumerate(zip(texts, keys, strict=True)) if k not in found]
        self.hits += len(texts) - len(todo)
        self.misses += len(todo)
        if todo:
            uniq_texts = list(dict.fromkeys(t for _, t in todo))
            vecs = self.embedder.embed(uniq_texts)
            by_text = {t: np.asarray(v, dtype=np.float32) for t, v in zip(uniq_texts, vecs, strict=True)}
            for t, v in by_text.items():
                found[self._key(t)] = v
            if self.db is not None:
                self.db.executemany("INSERT OR IGNORE INTO emb (k, v) VALUES (?, ?)",
                                    [(self._key(t), v.astype(np.float16).tobytes()) for t, v in by_text.items()])
                self.db.commit()
        return [found[k] for k in keys]


# ------------------------------------------------------------------ loader
class BulkLoader:
    def __init__(self, url: str, *, tenant_id: uuid.UUID, company_id: uuid.UUID, scope_ids: dict[str, uuid.UUID], embedder: CachedEmbedder,
                 log=print):
        self.url, self.tenant_id, self.company_id, self.scope_ids, self.embedder, self.log = url, tenant_id, company_id, scope_ids, embedder, log
        self.conn = psycopg.connect(url)
        register_vector(self.conn)
        from psycopg.types.enum import EnumInfo, register_enum
        from psycopg.types.string import StrBinaryDumperVarchar

        for tname, py in (("record_type", RecordType), ("verification_status", VerificationStatus), ("link_kind", LinkKind)):
            register_enum(EnumInfo.fetch(self.conn, tname), self.conn, py)
        self.conn.adapters.register_dumper(str, StrBinaryDumperVarchar)
        with self.conn.cursor() as cur:  # staging tables live for the session, outside any batch transaction a rollback could undo
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS stage_records (LIKE memory_records INCLUDING DEFAULTS) ON COMMIT DELETE ROWS")
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS stage_sections (LIKE sections INCLUDING DEFAULTS) ON COMMIT DELETE ROWS")
        self.conn.commit()
        self.ext_id: uuid.UUID | None = None
        self.now = utcnow()
        # company-wide registries
        self.entity_id: dict[tuple[str, str], uuid.UUID] = {}
        self.entity_info: dict[uuid.UUID, dict[str, Any]] = {}
        self.project_id: dict[str, uuid.UUID] = {}
        self.project_docs: dict[uuid.UUID, list[tuple[Any, uuid.UUID]]] = defaultdict(list)
        self.key_to_doc: dict[str, list[uuid.UUID]] = defaultdict(list)  # identifier -> documents that carry it
        self.pending_refs: list[tuple[uuid.UUID, str, str]] = []
        self.doc_ids: list[uuid.UUID] = []  # document-record ids in load order
        self.doc_vecs: list[np.ndarray] = []
        self.doc_pos: dict[uuid.UUID, int] = {}
        self.doc_ctx: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID, int, str, str]] = {}  # doc record -> (document, scope, sensitivity, title, source)
        self.doc_numeric: dict[uuid.UUID, list[str]] = {}
        self.failed: set[uuid.UUID] = set()  # document records the database rejected
        self.links: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
        self.stats: Counter = Counter()
        self.t_embed = 0.0

    # -------------------------------------------------------------- helpers
    def _glyph(self, rid: uuid.UUID, r: RecOut, project: str | None, source: str, doc_id: uuid.UUID | None, section_id: uuid.UUID | None) -> dict:
        return Glyph(id=str(rid), type=r.type, what=r.summary[:300], who=r.mentions[:8], why=_WHY_BY_TYPE.get(r.type), project=project,
                     department=source, time={k: v for k, v in {"event": r.event_time.isoformat() if r.event_time else None,
                                                                  "recorded": self.now.isoformat()}.items() if v},
                     confidence=round(float(r.confidence), 3), keywords=list(r.keywords)[:12],
                     evidence=[EvidencePointer(document_id=str(doc_id) if doc_id else None, section_id=str(section_id) if section_id else None,
                                               quote=r.detail[:200])]).to_compact()

    @staticmethod
    def _agg() -> dict[str, Any]:
        return {"roles": Counter(), "docs": 0, "sources": Counter(), "aliases": set()}

    def _registry(self, eid: uuid.UUID, name: str, etype: str, sens: int) -> dict[str, Any]:
        """The registry entry of an entity or project, keeping one aggregate per sensitivity level so that what a
        company-wide record says about it never comes from a restricted document."""
        info = self.entity_info.get(eid)
        if info is None:
            info = self.entity_info[eid] = {"name": name, "type": etype, "sens": sens, "by": {}, "new": True}
        elif sens < info["sens"]:
            info["sens"], info["name"] = sens, name  # the least restricted sighting names it
        agg = info["by"].get(sens)
        if agg is None:
            agg = info["by"][sens] = self._agg()
        if name != info["name"]:
            agg["aliases"].add(name)
        return agg

    def _entity(self, name: str, etype: str, role: str | None, source: str, sens: int = 1) -> uuid.UUID | None:
        key = normalise(name)
        if not key or len(key) < 3:
            return None
        k = (etype, key)
        eid = self.entity_id.get(k)
        if eid is None:
            eid = self.entity_id[k] = uuid.uuid4()
        agg = self._registry(eid, name, etype, sens)
        if role:
            agg["roles"][role] += 1
        agg["sources"][source] += 1
        return eid

    def _project(self, name: str, source: str, sens: int = 1) -> uuid.UUID:
        key = normalise(name) or name.lower()
        pid = self.project_id.get(key)
        if pid is None:
            pid = self.project_id[key] = uuid.uuid4()
        agg = self._registry(pid, name, "project", sens)
        agg["docs"] += 1
        agg["sources"][source] += 1
        return pid

    def _link(self, rows: list, src: uuid.UUID, dst: uuid.UUID, kind: str, weight: float, why: str | None = None, seen: set | None = None) -> None:
        """Queue one link. ``seen`` de-duplicates (src, dst, kind); links made inside a batch are unique by construction
        (their sources are new records), so only cross-document links need the long-lived set."""
        seen = self.links if seen is None else seen
        if src == dst or (src, dst, kind) in seen or src in self.failed or dst in self.failed:
            return
        seen.add((src, dst, kind))
        rows.append((uuid.uuid4(), self.tenant_id, src, dst, LinkKind(kind), float(weight), why, Jsonb({"producer": PRODUCER}), self.now))
        self.stats[f"link_{kind}"] += 1

    def _copy_links(self, cur, rows: list) -> None:
        if not rows:
            return
        with cur.copy("COPY record_links (id, tenant_id, src_id, dst_id, kind, weight, justification, evidence, created_at) FROM STDIN WITH (FORMAT BINARY)") as cp:
            cp.set_types(["uuid", "uuid", "uuid", "uuid", "link_kind", "float8", "text", "jsonb", "timestamptz"])
            for row in rows:
                cp.write_row(row)

    def _copy_records(self, cur, rows: list) -> None:
        """Records go through the staging table so their tsvector is computed on the way in."""
        if not rows:
            return
        self._copy(cur, "stage_records", REC_COLS, REC_TYPES, rows)
        cur.execute(f"INSERT INTO memory_records ({REC_COLS}, tsv) SELECT {REC_COLS}, {REC_TSV} FROM stage_records")
        cur.execute("TRUNCATE stage_records")

    def _copy_sections(self, cur, rows: list) -> None:
        if not rows:
            return
        self._copy(cur, "stage_sections", SEC_COLS, SEC_TYPES, rows)
        cur.execute(f"INSERT INTO sections ({SEC_COLS}, tsv) SELECT {SEC_COLS}, {SEC_TSV} FROM stage_sections")
        cur.execute("TRUNCATE stage_sections")

    def _record_row(self, rid, scope_id, r: RecOut, *, doc_id, section_id, sensitivity, entity_ids, vec, project, source, verification=None):
        loc = [{"page_no": 1, "section_id": str(section_id) if section_id else None, "quote": r.detail[:300]}]
        # a record's date says when its event happens (a due date, a meeting), not when the record becomes true: only a
        # decision or a metric takes effect on its date, and never later than the load (a future date must not hide it)
        valid_from = min(r.event_time, self.now) if r.event_time is not None and r.type in DECISION_TYPES else None
        return (rid, self.tenant_id, scope_id, RecordType(r.type), r.summary[:1000], Jsonb(r.content), r.detail[:4000], doc_id, Jsonb(loc),
                r.event_time, valid_from, None, self.now, PRODUCER, float(r.confidence), verification or VerificationStatus.unverified,
                sensitivity, Jsonb({}), 1, uuid.uuid4(), Jsonb([str(e) for e in entity_ids]), list(r.keywords)[:24],
                Jsonb(self._glyph(rid, r, project, source, doc_id, section_id)), vec, hashlib.sha256(f"{r.summary}|{r.detail}".encode()).hexdigest())

    # -------------------------------------------------------------- per batch
    def write_batch(self, mems: list[DocMemory]) -> None:
        mems = [m for m in mems if m is not None]
        if not mems:
            return
        # 1. registries: entities and projects first seen in this batch, document identifiers
        doc_rec_ids = [uuid.uuid4() for _ in mems]
        doc_ids = [uuid.uuid4() for _ in mems]
        ent_of: list[dict[str, uuid.UUID]] = []
        proj_of: list[uuid.UUID | None] = []
        for m, drid in zip(mems, doc_rec_ids, strict=True):
            names: dict[str, uuid.UUID] = {}
            sens = m.sensitivity
            for n, role in m.people:
                eid = self._entity(n, "person", role, m.source, sens)
                if eid:
                    names[n] = eid
            for n in m.orgs:
                eid = self._entity(n, "organization", None, m.source, sens)
                if eid:
                    names[n] = eid
            for r in m.records[1:]:  # task owners named in items but not in the metadata
                for n in r.mentions:
                    if n not in names and r.content.get("owner") == n:
                        eid = self._entity(n, "person", "task owner", m.source, sens)
                        if eid:
                            names[n] = eid
            for eid in set(names.values()):
                self.entity_info[eid]["by"][sens]["docs"] += 1
            ent_of.append(names)
            pid = self._project(m.project, m.source, sens) if m.project else None
            if pid:
                self.project_docs[pid].append((m.created, drid))
            proj_of.append(pid)
            for k in m.keys:
                holders = self.key_to_doc[k]
                if len(holders) <= MAX_KEY_HOLDERS and drid not in holders:
                    holders.append(drid)
            for k, kind in m.refs:
                self.pending_refs.append((drid, k, kind))
        new_entities = [eid for eid, info in self.entity_info.items() if info.pop("new", False)]

        # 2. embeddings (one call: sections, records, new entities/projects)
        texts: list[str] = []
        for m in mems:
            texts += [e for _, _, e in m.sections]
            texts += [r.embed for r in m.records]
        ent_texts = [self._entity_text(eid) for eid in new_entities]
        t = time.perf_counter()
        vecs = self.embedder.embed(texts + ent_texts)
        self.t_embed += time.perf_counter() - t
        vi = 0

        # 3. rows, one bundle per document so a rejected batch can be retried document by document
        bundles: list[dict[str, Any]] = []
        for m, drid, did, names, pid in zip(mems, doc_rec_ids, doc_ids, ent_of, proj_of, strict=True):
            scope = self.scope_ids.get(m.source) or self.company_id
            bid = uuid.uuid4()
            b: dict[str, Any] = {"drid": drid, "rel": m.rel, "blobs": [], "docs": [], "secs": [], "recs": [], "links": [], "seen": set()}
            b["blobs"].append((bid, self.tenant_id, hashlib.sha256(m.rel.encode()).hexdigest(), sum(len(s) for _, s, _ in m.sections),
                               "application/json", f"export://{m.rel}", False, self.now))
            ident = next((k.split(":", 1)[-1] for k in m.keys), None) or m.dsid or m.title[:120]
            b["docs"].append((did, self.tenant_id, bid, uuid.uuid4(), 1, m.title[:500], f"{m.source}:{ident}"[:500], m.source, scope, m.sensitivity,
                              Jsonb({}), "default", False, self.now, Jsonb({"dsid": m.dsid, "source": m.source, "summary": m.summary, "tags": m.tags[:20],
                                                                            "project": m.project, **{k: v for k, v in list(m.meta_extra.items())[:20]}}),
                              "indexed", Jsonb([]), Jsonb([]), m.source, m.created))
            sec_ids = []
            for oi, (st, stext, _e) in enumerate(m.sections):
                sid = uuid.uuid4()
                sec_ids.append(sid)
                b["secs"].append((sid, self.tenant_id, did, None, scope, oi, st[:300], 1, 1, 1, stext, hashlib.sha256(stext.encode()).hexdigest(),
                                  len(stext) // 4, Jsonb([{"page_no": 1, "block_ids": [], "bbox": [0, 0, 0, 0]}]), vecs[vi], m.sensitivity))
                vi += 1
            for ri, r in enumerate(m.records):
                rid = drid if ri == 0 else uuid.uuid4()
                eids = [names[n] for n in (r.mentions if ri else list(names)) if n in names]
                sid = sec_ids[r.section] if r.section is not None and r.section < len(sec_ids) else None
                b["recs"].append(self._record_row(rid, scope, r, doc_id=did, section_id=sid, sensitivity=m.sensitivity, entity_ids=eids,
                                                  vec=vecs[vi], project=m.project, source=m.source))
                if ri == 0:
                    self.doc_pos[drid] = len(self.doc_ids)
                    self.doc_ids.append(drid)
                    self.doc_vecs.append(np.asarray(vecs[vi], dtype=np.float16))
                    self.doc_ctx[drid] = (did, scope, m.sensitivity, m.title, m.source)
                    if m.numeric:
                        self.doc_numeric[drid] = m.numeric
                    for eid in set(eids):
                        self._link(b["links"], drid, eid, "mentions", 0.6, seen=b["seen"])
                    if pid:
                        self._link(b["links"], drid, pid, "part_of", 0.8, seen=b["seen"])
                else:
                    self._link(b["links"], rid, drid, "part_of", 0.5, seen=b["seen"])
                    for eid in set(eids):
                        self._link(b["links"], rid, eid, "mentions", 0.6, seen=b["seen"])
                self.stats[f"rec_{r.type}"] += 1
                vi += 1
            bundles.append(b)
        ent_rows = []
        for eid, v in zip(new_entities, vecs[vi:], strict=True):
            info = self.entity_info[eid]
            r = RecOut(type=info["type"], summary=(f"Project: {info['name']}" if info["type"] == "project" else info["name"]),
                       detail=self._entity_text(eid), content={"name": info["name"], "aliases": []}, keywords=[normalise(info["name"]).replace(" ", "-")],
                       confidence=0.8, embed="")
            ent_rows.append(self._record_row(eid, self.company_id, r, doc_id=None, section_id=None, sensitivity=info["sens"], entity_ids=[], vec=v,
                                             project=info["name"] if info["type"] == "project" else None, source="company"))
            self.stats[f"rec_{info['type']}"] += 1
        # 4. COPY; on a rejected batch, company records first, then each document on its own
        try:
            self._write(bundles, ent_rows)
        except WRITE_ERRORS as e:
            self.conn.rollback()
            self.log(f"  batch rejected ({type(e).__name__}: {str(e)[:200]}); retrying {len(bundles)} documents one by one")
            self._write([], ent_rows)  # entity and project records quote no document text
            for b in bundles:
                try:
                    self._write([b], [])
                except WRITE_ERRORS as e2:
                    self.conn.rollback()
                    self.failed.add(b["drid"])
                    self.stats["documents_failed"] += 1
                    self.log(f"  skipped {b['rel']}: {type(e2).__name__}: {str(e2)[:200]}")
        ok = [b for b in bundles if b["drid"] not in self.failed]
        self.stats["documents"] += len(ok)
        self.stats["sections"] += sum(len(b["secs"]) for b in ok)

    def _write(self, bundles: list[dict[str, Any]], ent_rows: list) -> None:
        blobs = [r for b in bundles for r in b["blobs"]]
        docs = [r for b in bundles for r in b["docs"]]
        secs = [r for b in bundles for r in b["secs"]]
        recs = [r for b in bundles for r in b["recs"]]
        links = [r for b in bundles for r in b["links"]]
        ext = self.ext_id
        with self.conn.cursor() as cur:
            cur.execute("SET LOCAL synchronous_commit = off")
            self._copy(cur, "blobs", BLOB_COLS, BLOB_TYPES, blobs)
            self._copy(cur, "documents", self._doc_cols(), self._doc_types(), docs)
            if ext is None and docs:
                ext = uuid.uuid4()
                cur.execute("INSERT INTO extractions (id, tenant_id, document_id, extractor, extractor_version, status, page_count, pages_done, completeness, stats, created_at) "
                            "VALUES (%s, %s, %s, 'structured_ingest', '1', 'done', 1, 1, '{}', '{}', %s)", (ext, self.tenant_id, docs[0][0], self.now))
            self._copy_sections(cur, [row[:3] + (ext,) + row[4:] for row in secs])
            self._copy_records(cur, ent_rows + recs)  # entity and project rows before the links that point at them
            self._copy_links(cur, links)
        self.conn.commit()
        self.ext_id = ext

    @staticmethod
    def _doc_cols() -> str:
        return ("id, tenant_id, blob_id, family_id, version, title, original_filename, source, scope_id, sensitivity, acl, retention_policy, legal_hold, "
                "ingested_at, extra, status, injection_flags, pii_flags, doc_type, file_created_at")

    @staticmethod
    def _doc_types() -> list[str]:
        return ["uuid", "uuid", "uuid", "uuid", "int4", "text", "text", "text", "uuid", "int4", "jsonb", "text", "bool", "timestamptz",
                "jsonb", "text", "jsonb", "jsonb", "text", "timestamptz"]

    @staticmethod
    def _copy(cur, table: str, cols: str, types: list[str], rows: list) -> None:
        if not rows:
            return
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT BINARY)") as cp:
            cp.set_types(types)
            for row in rows:
                cp.write_row(row)

    def _entity_text(self, eid: uuid.UUID) -> str:
        info = self.entity_info[eid]
        kind = {"person": "Person", "organization": "Company", "project": "Project"}[info["type"]]
        agg = info["by"].get(info["sens"]) or self._agg()
        roles = ", ".join(r for r, _ in agg["roles"].most_common(4))
        return f"{kind}: {info['name']}" + (f" ({roles})" if roles else "")

    # -------------------------------------------------------------- end of load
    def _unit_vectors(self) -> np.ndarray:
        X = np.vstack(self.doc_vecs).astype(np.float32)
        X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
        return X

    def _cos(self, X: np.ndarray, a: uuid.UUID, b: uuid.UUID) -> float:
        return float(X[self.doc_pos[a]] @ X[self.doc_pos[b]])

    def _same_object(self, X: np.ndarray, a: uuid.UUID, b: uuid.UUID) -> bool:
        """Two documents that carry the same identifier describe one object only when their titles match or their
        memory cards are (nearly) the same; identifiers are reused across unrelated records of one system."""
        ta, tb = self.doc_ctx[a], self.doc_ctx[b]
        if normalise(ta[3]) and normalise(ta[3]) == normalise(tb[3]):
            return True
        return self._cos(X, a, b) >= (SAME_OBJECT_CROSS_SOURCE if ta[4] != tb[4] else SAME_OBJECT_SAME_SOURCE)

    def finish(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        rows: list = []
        X = self._unit_vectors() if self.doc_ids else np.zeros((0, 1), dtype=np.float32)
        # documents that carry the same identifier: one object (linked, checked for conflicting facts) or a collision
        self.same_key_pairs: list[tuple[uuid.UUID, uuid.UUID]] = []
        one_object: set[str] = set()
        collisions = 0
        for key, holders in self.key_to_doc.items():
            holders = [h for h in holders if h not in self.failed]
            if not 2 <= len(holders) <= MAX_KEY_HOLDERS:
                continue
            pairs = [(a, b) for i, a in enumerate(holders) for b in holders[i + 1:]]
            same = [(a, b) for a, b in pairs if self._same_object(X, a, b)]
            collisions += len(pairs) - len(same)
            if len(same) == len(pairs):
                one_object.add(key)
            for a, b in same:
                self._link(rows, a, b, "references", 0.9, f"same identifier {key}")
                self.same_key_pairs.append((a, b))
        # explicit references between documents
        unresolved = ambiguous = 0
        for src, key, kind in self.pending_refs:
            if src in self.failed:
                continue
            holders = [h for h in self.key_to_doc.get(key) or [] if h != src and h not in self.failed]
            if not holders:
                unresolved += 1
                continue
            if len(holders) > MAX_KEY_HOLDERS:
                ambiguous += 1
                continue
            if len(holders) > 1 and key not in one_object:
                ranked = sorted(((self._cos(X, src, h), h) for h in holders), key=lambda x: -x[0])
                if ranked[0][0] - ranked[1][0] < REF_MARGIN:
                    ambiguous += 1  # no holder stands out: an unresolved citation beats a wrong one
                    continue
                holders = [ranked[0][1]]
            lk = "depends_on" if kind == "depends_on" else "references"
            for dst in holders:
                self._link(rows, src, dst, lk, 1.0 if kind != "mentions_key" else 0.8, f"cites {key}")
        self.stats["refs_unresolved"] = unresolved
        self.stats["refs_ambiguous"] = ambiguous
        self.stats["same_key_collisions"] = collisions
        # project siblings, in time order
        for _pid, docs in self.project_docs.items():
            docs = sorted(docs, key=lambda x: (x[0] is None, x[0] or self.now))
            for i in range(len(docs)):
                for j in (i + 1, i + 2):
                    if j < len(docs):
                        self._link(rows, docs[i][1], docs[j][1], "relates_to", 0.7, "same project")
        with self.conn.cursor() as cur:
            self._copy_links(cur, rows)
        self.conn.commit()
        self.log(f"  links: {self.stats['link_references']} references, {self.stats['link_depends_on']} depends_on, "
                 f"{self.stats['link_relates_to']} project siblings; {unresolved} references unresolved, {ambiguous} ambiguous; "
                 f"{collisions} same-identifier pairs judged different objects")
        # near-duplicates and the facts they disagree on
        self._near_duplicates(X)
        del X
        # entity/project aggregate detail
        self._update_entities()
        with self.conn.cursor() as cur:
            for tbl in ("memory_records", "sections", "documents", "record_links"):
                cur.execute(f"ANALYZE {tbl}")
        self.conn.commit()
        self.stats["finish_seconds"] = round(time.perf_counter() - t0, 1)
        return dict(self.stats)

    def _near_duplicates(self, X: np.ndarray) -> None:
        n = len(self.doc_ids)
        if n < 2:
            return
        top_i, top_s = _top2(X)
        pairs = []
        for i in range(n):
            j = int(top_i[i])
            if j > i and float(top_s[i]) >= NEAR_DUPLICATE and int(top_i[j]) == i:  # mutual nearest neighbours
                if self.doc_ids[i] not in self.failed and self.doc_ids[j] not in self.failed:
                    pairs.append((i, j, float(top_s[i])))
        self.stats["near_duplicate_pairs"] = len(pairs)
        rows, recs, new_texts, new_meta = [], [], [], []
        candidates: dict[frozenset, tuple[uuid.UUID, uuid.UUID]] = {}
        for i, j, sim in pairs:
            a, b = self.doc_ids[i], self.doc_ids[j]
            self._link(rows, a, b, "near_duplicate", round(sim, 3), f"memory cards {sim:.3f} similar")
            candidates[frozenset((a, b))] = (a, b)
        for a, b in getattr(self, "same_key_pairs", []):
            candidates.setdefault(frozenset((a, b)), (a, b))
        for a, b in candidates.values():
            for sa, sb in _conflicting_sentences(self.doc_numeric.get(a, []), self.doc_numeric.get(b, []))[:MAX_CONFLICTS_PER_PAIR]:
                new_meta.append((a, b, sa, sb))
                new_texts += [sa, sb, f"Conflict: {sa} vs {sb}"]
        shared = 0
        if new_meta:
            vecs = self.embedder.embed(new_texts)
            for k, (a, b, sa, sb) in enumerate(new_meta):
                da, db = self.doc_ctx[a], self.doc_ctx[b]
                fa, fb = uuid.uuid4(), uuid.uuid4()
                same_scope = da[1] == db[1]
                c = uuid.uuid4() if same_scope else None
                # each disputed fact lives in its own document's scope and names the other only by record id; a reader
                # who may see both documents reaches the other side through the contradicts edge, anyone else does not
                for rid, other, (did, scope, sens, _title, _src), sent, vec in ((fa, fb, da, sa, vecs[3 * k]), (fb, fa, db, sb, vecs[3 * k + 1])):
                    content = {"conflict_with_record": str(other)}
                    if c is not None:
                        content["contradiction_record"] = str(c)
                    r = RecOut(type="fact", summary=short(sent, 220), detail=sent, content=content, keywords=[], confidence=0.6, embed="")
                    recs.append(self._record_row(rid, scope, r, doc_id=did, section_id=None, sensitivity=sens, entity_ids=[], vec=vec,
                                                 project=None, source="conflict", verification=VerificationStatus.disputed))
                why = "states a different number than a near-identical statement in another document"
                for x, y in ((fa, fb), (fb, fa)):
                    self._link(rows, x, y, "contradicts", 1.0, why)
                self._link(rows, fa, a, "part_of", 0.5)
                self._link(rows, fb, b, "part_of", 0.5)
                if c is not None:  # both documents share a scope: one record may quote both, at the stricter sensitivity
                    shared += 1
                    reason = f"'{da[3]}' and '{db[3]}' state different values: \"{short(sa, 160)}\" vs \"{short(sb, 160)}\""
                    rc = RecOut(type="contradiction", summary=short(f"Contradiction: {sa} vs {sb}", 400), detail=reason,
                                content={"record_a": str(fa), "record_b": str(fb), "document_a": da[3], "document_b": db[3], "reason": reason},
                                keywords=[], confidence=0.7, embed="")
                    recs.append(self._record_row(c, da[1], rc, doc_id=da[0], section_id=None, sensitivity=max(da[2], db[2]), entity_ids=[],
                                                 vec=vecs[3 * k + 2], project=None, source="conflict"))
                    for x in (fa, fb):
                        self._link(rows, c, x, "relates_to", 1.0)
            self.stats["contradictions"] = len(new_meta)
            self.stats["contradiction_records"] = shared
        with self.conn.cursor() as cur:
            self._copy_records(cur, recs)
            self._copy_links(cur, rows)
        self.conn.commit()
        self.log(f"  near-duplicates: {len(pairs)} document pairs (mutual nearest neighbours, cosine >= {NEAR_DUPLICATE}); "
                 f"{self.stats['contradictions']} conflicting facts recorded ({shared} within one scope)")

    def _update_entities(self) -> None:
        rows = []
        for eid, info in self.entity_info.items():
            kind = {"person": "Person", "organization": "Company", "project": "Project"}[info["type"]]
            agg = info["by"].get(info["sens"]) or self._agg()  # only documents as open as the record itself
            roles = ", ".join(f"{r} ({c})" for r, c in agg["roles"].most_common(6))
            sources = ", ".join(f"{s} ({c})" for s, c in agg["sources"].most_common(6))
            detail = f"{kind}: {info['name']}. Appears in {agg['docs']} documents" + (f"; roles: {roles}" if roles else "") + (f"; sources: {sources}" if sources else "") + "."
            if agg["aliases"]:
                detail += " Also written: " + ", ".join(sorted(agg["aliases"])[:8]) + "."
            content = {"name": info["name"], "aliases": sorted(agg["aliases"])[:20], "documents": agg["docs"],
                       "roles": dict(agg["roles"].most_common(10)), "sources": dict(agg["sources"])}
            summary = f"Project: {info['name']}" if info["type"] == "project" else info["name"]
            rows.append((eid, summary, detail[:4000], Jsonb(content), info["sens"]))
        with self.conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE ent_upd (id uuid, summary text, detail text, content jsonb, sens int4) ON COMMIT DROP")
            with cur.copy("COPY ent_upd (id, summary, detail, content, sens) FROM STDIN WITH (FORMAT BINARY)") as cp:
                cp.set_types(["uuid", "text", "text", "jsonb", "int4"])
                for row in rows:
                    cp.write_row(row)
            cur.execute("UPDATE memory_records m SET summary = u.summary, detail = u.detail, content = u.content, sensitivity = u.sens, "
                        "tsv = setweight(to_tsvector('english', u.summary), 'A') || setweight(to_tsvector('english', array_to_string(m.keywords, ' ')), 'A') || "
                        "setweight(to_tsvector('english', left(u.detail, 20000)), 'B') FROM ent_upd u WHERE m.id = u.id")
        self.conn.commit()
        self.stats["entities"] = sum(1 for i in self.entity_info.values() if i["type"] != "project")
        self.stats["projects"] = sum(1 for i in self.entity_info.values() if i["type"] == "project")
        self.stats["restricted_entities"] = sum(1 for i in self.entity_info.values() if i["sens"] > 1)

    def close(self) -> None:
        self.conn.close()


# ------------------------------------------------------------------ similarity helpers
def _top2(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For every row, its nearest other row and the cosine (rows are unit vectors). GPU when torch sees one."""
    n = len(X)
    try:
        import torch

        if torch.cuda.is_available():
            T = torch.from_numpy(X).to("cuda", dtype=torch.float16)
            idx, sim = np.empty(n, dtype=np.int64), np.empty(n, dtype=np.float32)
            for s in range(0, n, 8192):
                S = T[s:s + 8192] @ T.T
                S[torch.arange(S.shape[0]), torch.arange(s, s + S.shape[0])] = -2
                v, i = S.max(dim=1)
                idx[s:s + len(v)], sim[s:s + len(v)] = i.cpu().numpy(), v.float().cpu().numpy()
            return idx, sim
    except Exception:  # noqa: BLE001 - fall back to the CPU
        pass
    idx, sim = np.empty(n, dtype=np.int64), np.empty(n, dtype=np.float32)
    for s in range(0, n, 2048):
        S = X[s:s + 2048] @ X.T
        S[np.arange(S.shape[0]), np.arange(s, s + S.shape[0])] = -2
        idx[s:s + len(S)] = S.argmax(axis=1)
        sim[s:s + len(S)] = S[np.arange(S.shape[0]), idx[s:s + len(S)]]
    return idx, sim


_NUM = re.compile(r"\d+(?:[.,]\d+)?%?")
_W = re.compile(r"[a-z]{3,}")
# numbers that name something rather than state a quantity: links, addresses, ticket keys, #123, p95 / v2 / H100 (but not
# Q3, H1, FY26), clock times and dotted versions
_IDENTIFIER = re.compile(r"https?://\S+|\S+@\S+|\b[A-Z][A-Z0-9]{1,9}-\d+\b|#\d+|\bv?\d+(?:\.\d+){2,}\b|\b\d{1,2}:\d{2}(?::\d{2})?\b"
                         r"|\b(?!(?:Q[1-4]|H[12]|FY\d{2,4})\b)[A-Za-z]+[-_]?\d+[A-Za-z0-9]*\b")


def _numbers(s: str) -> set[str]:
    return set(_NUM.findall(_IDENTIFIER.sub(" ", s)))


def _conflicting_sentences(a: list[str], b: list[str]) -> list[tuple[str, str]]:
    """Sentence pairs that say the same thing (word Jaccard >= 0.5, numbers ignored) with different quantities."""
    out = []
    bw = [(s, set(_W.findall(s.lower())), _numbers(s)) for s in b]
    for sa in a:
        wa, na = set(_W.findall(sa.lower())), _numbers(sa)
        if len(wa) < 5 or not na:
            continue
        best = None
        for sb, wb, nb in bw:
            if not nb or len(wb) < 5:
                continue
            jac = len(wa & wb) / len(wa | wb)
            if jac >= 0.5 and na != nb and (best is None or jac > best[0]):
                best = (jac, sb)
        if best:
            out.append((sa, best[1]))
    return out
