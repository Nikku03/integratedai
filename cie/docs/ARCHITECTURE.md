# Architecture

The Company Intelligence Engine (CIE) turns files, decisions, communications,
projects, tasks, evidence and agent results into one searchable, connected
organizational memory, and runs a head agent plus five specialists on top of it.

Two rules govern every layer:

1. **Raw documents are the lossless record.** Everything above them is a
   derived, citable index that points back to an exact page and bounding box.
   Nothing derived is ever called "lossless".
2. **No model ever holds the memory.** A project memory addresses ~200M tokens
   and an agent memory ~50M tokens as persistent, searchable storage. Each
   inference receives a compact evidence packet of 20–100 records.

## Layer diagram

```
                       ┌──────────────────────────────────────────────────────┐
   connectors / API    │  upload · connector:x · email · repo · db export      │
                       └───────────────┬──────────────────────────────────────┘
                                       ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ A. IMMUTABLE RAW VAULT            blobs (sha256-addressed, encrypted at rest) │
 │    documents: id · checksum · location · source · owner · dept/project ·     │
 │    file time · ingest time · version/family · sensitivity · acl · retention  │
 └───────────────┬─────────────────────────────────────────────────────────────┘
                 ▼  durable job queue (Postgres, SKIP LOCKED, per-page checkpoints)
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ B. DOCUMENT PROCESSING            pluggable extractors                       │
 │    detect type/lang → extract (text/tables/figures/signatures/layout) with   │
 │    page + bbox → OCR corrections (separate table) → semantic sections →      │
 │    facts/summaries → completeness + confidence checks                        │
 │    extractors: pymupdf (born-digital) · tesseract (scans) · unlimited_ocr    │
 │    (vLLM/SGLang endpoint) · plain/markdown/html/email/csv/code               │
 └───────────────┬─────────────────────────────────────────────────────────────┘
                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ C/D. STRUCTURED MEMORY                                                       │
 │    sections (FTS + vector, spans→pages/blocks)                              │
 │    memory_records: 22 typed kinds · summary · content · detail · source      │
 │      locations · valid_from/valid_to · recorded_at · confidence ·           │
 │      verification · sensitivity · version/family · superseded_by · glyph    │
 │    record_links: sparse graph (depends_on, causes, precedes, contradicts,    │
 │      confirms, supersedes, extends, mentions, part_of, shortcut)            │
 │    scopes: company ▸ department ▸ project ▸ agent ▸ task (inheritance,       │
 │      not duplication)                                                       │
 └───────────────┬─────────────────────────────────────────────────────────────┘
                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ F. HYBRID RETRIEVAL   intent → scope → exact → lexical ∥ vector → fusion →   │
 │    bounded graph expansion (3 horizons, budget ≈ c·log N) → rerank →        │
 │    contradiction check → evidence packet (20–100 records) → cited answer    │
 └───────────────┬─────────────────────────────────────────────────────────────┘
                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 5–7. MULTI-AGENT OS   head agent: decompose → dependencies → route by        │
 │    per-task-type scorecard → brief + packet → track → detect conflicts →    │
 │    verify → synthesize.  5 specialists: research · finance · legal ·        │
 │    operations · engineering.  Structured messages only. Append-only,        │
 │    hash-chained project ledger.                                             │
 └───────────────┬─────────────────────────────────────────────────────────────┘
                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 8. GOVERNANCE   RBAC+ABAC · tenant/project isolation · audit log ·           │
 │    PII/secret/prompt-injection scanners · retention · legal hold ·          │
 │    deletion workflow · approval gates · prompt/model version tracking       │
 └─────────────────────────────────────────────────────────────────────────────┘
        ▲                                     ▲
   FastAPI (cie.api)                    React dashboard (cie/dashboard)
```

## A. Immutable raw vault (`cie.vault`)

* `Blob` rows are content-addressed by sha256 and deduplicated per tenant.
  Bytes are stored by a `VaultBackend` (`local` filesystem or `s3`/MinIO). An
  optional AES-GCM key encrypts bytes at rest; the checksum is of the plaintext.
* `Document` rows hold all required metadata. Re-ingesting a changed file with
  the same `family_id` creates version N+1 and links `previous_version_id`.
  Versions are never overwritten.
* `vault.read(document_id)` verifies the checksum on every read, so the system
  can always return to the original evidence and prove it is unchanged.

## B. Document processing (`cie.extraction`)

* `detect.py` sniffs media type (magic bytes + extension) and language.
* `Extractor` protocol: `extract(blob, page_range) -> ExtractedPage*`. A page
  carries blocks with kind (`text|heading|table|figure|signature|formula`),
  bbox in PDF points, text, structured table cells and a confidence.
* PDFs stream page by page. The `extract_document` job writes each page and
  checkpoints `pages_done`; a killed worker resumes at the next page. A
  300-page scan therefore needs 300 short OCR calls, never one giant response.
* Scanned pages (fewer than `ocr_min_chars_per_page` characters from the text
  layer) go to the OCR backend. `tesseract` returns word boxes and confidences;
  `unlimited_ocr` talks to a vLLM/SGLang OpenAI-compatible endpoint serving
  `baidu/Unlimited-OCR` and parses its `<|det|>type [bbox]<|/det|>` layout
  markers. The system never depends on one OCR model.
* `corrections.py` proposes conservative fixes (character confusions inside
  dictionary words, broken hyphenation, common ligatures). Corrections are
  stored in their own table; the original block text is never modified.
* `sectioning.py` splits the page stream into semantic sections using heading
  detection (numbering, capitalisation, font size when available) and a token
  budget, keeping exact spans `[{page_no, block_ids, bbox}]`.
* `facts.py` derives structured records deterministically (dates, deadlines,
  monetary amounts, parties, clause numbers, defined terms, requirements
  phrased with shall/must) and, when an LLM provider is configured, richer
  typed records. Every derived item links to its exact source span.
* `checks.py` verifies completeness: page count equals the container's page
  count, no page silently empty without an `empty_page` flag, mean OCR
  confidence, and duplicate-page detection.
* Extraction, corrections and derived records live in separate tables. OCR
  working state is per document and discarded at job end unless a
  cross-document job is explicitly requested.

## C. Memory hierarchy (`cie.memory.scopes`)

Scopes form a tree: company → department → project → agent → task. A record
belongs to exactly one scope. Retrieval for a principal at a scope sees:

* records in that scope and its descendants the principal may read, and
* records in ancestor scopes (inherited), permission permitting.

No record is copied between levels. An agent's "50M-token memory" is the set
of records addressable from its agent scope plus what it inherits; a project's
"200M-token memory" is likewise addressable, never loaded.

## D. Memory records (`cie.memory.records`)

`MemoryRecord` has the 22 required types and every required field (see
`docs/SCHEMA.md`). Mutations are events, not overwrites:

* `supersede(old, new)` sets `old.superseded_by_id`, closes `old.valid_to`,
  links `new -supersedes-> old`.
* `contradict(a, b)` adds a `contradicts` edge and a `contradiction` record
  that cites both.
* `confirm(a, b)` / `extend(a, b)` add edges and raise confidence.

Point-in-time queries filter on `valid_from <= t < valid_to` and
`superseded_by_id IS NULL` for "current" facts.

## E. Glyphs (`cie.memory.glyph`)

A glyph is a typed, compact memory card stored as JSONB inside the record:
what, who, why, project/department, time, status, dependencies, consequences,
confidence, evidence pointers. It is built deterministically from the record
and its edges. It is a navigation structure; it never replaces the source.
`cie.eval.bench_glyph` compares the glyph's storage encodings (JSON, zlib,
msgpack, columnar, and a PNG "pixel" encoding) and reports the winner. Exotic
encodings that fail exact round-trip or searchability are rejected.

## F. Hybrid retrieval (`cie.retrieval`)

`RetrievalPipeline.run(query, principal, scope, filters)`:

1. `intent.classify` (exact-id, entity, definition, temporal, comparison,
   list, open question) – rule based, LLM optional.
2. `scopes.resolve` – company/department/project/agent scope set and time
   window; permission filter is applied in SQL, never after the fact.
3. `exact.lookup` – ids, clause numbers, entity names (trigram), keywords.
4. `lexical.search` (Postgres FTS, `ts_rank_cd`) ∥ `vector.search` (pgvector
   cosine, HNSW) over sections and records; reciprocal-rank fusion.
5. `graph.expand` – bounded BFS with three horizons; budget `⌈c·log2 N⌉`.
6. `rerank` – fused score × recency × verification × type prior × hub penalty;
   superseded records are demoted but retained when the query is temporal.
7. `contradictions.check` – pulls the other side of every `contradicts` edge.
8. `packet.build` – 20–100 records inside a token budget, stored in
   `evidence_packets` with the full trace so any answer is reproducible.
9. `answer` – strict mode is extractive (each sentence quotes a record and
   cites it); assisted mode calls the LLM and then verifies every claim
   against the packet, dropping unsupported claims.
10. Raw pages are fetched only via `/sources/{document_id}/pages/{n}`.

## REM-inspired sparse graph (`cie.retrieval.graph`)

Edges are typed and sparse. Horizon 1 follows `depends_on`, `part_of`,
`supersedes`, `contradicts`, `confirms`, `extends`; horizon 2 adds
`relates_to`, `mentions`, `causes`, `precedes`, `assigned_to`, `derived_from`;
horizon 3 crosses project/department scopes and may use `shortcut` edges.
Shortcuts are added only with a justification string (strong semantic,
causal or organizational reason) and are capped per node. The expander
benchmark decides whether a Ramanujan-style overlay is worth adding.

## Multi-agent OS (`cie.agents`)

* `HeadAgent.plan(objective)` → task DAG with types, risk levels and
  dependencies (rule templates by default, LLM planner optional).
* `Router.select(task)` scores each candidate agent on the task-type
  scorecard (accuracy, citation quality, completion, latency, cost,
  hallucination, verification score, recency), availability, permissions
  and cost; the chosen reason is stored on the task and shown in the UI.
* `Scheduler.step()` runs ready tasks, blocks on dependencies, retries
  failures, and re-plans on stagnation.
* Specialists receive a brief + evidence packet and reply with structured
  messages only (eight kinds). High-risk tasks spawn a verification task for
  a different agent; unresolved conflicts create `contradiction` records and
  an approval item.
* `Ledger.append()` writes hash-chained entries; any agent reads
  `Ledger.state(project)` to see the current objectives, tasks, results,
  blockers and next actions without replaying conversation history.

## Governance (`cie.governance`)

RBAC (roles with read/write/admin) + ABAC (role clearance ≥ record
sensitivity; scope attributes) resolved in SQL. Tenant id is on every table
and every query. Audit log on every read of evidence, every answer, every
permission change. Scanners flag secrets, PII and prompt-injection phrases at
ingestion; retrieved text is always wrapped as untrusted data when passed to
a model. Legal holds block deletion; deletion is a workflow with an approval
gate. Prompt and model versions are recorded on every answer and record.

## Resource minimisation

* Dedup by content hash at blob and section level.
* Only sections and records are embedded, never full pages twice.
* Evidence packets are token-budgeted; raw pages are lazy.
* Metrics table records tokens, latency, cost and storage for every call.
