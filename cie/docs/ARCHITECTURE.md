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

## D2. Organisation views (`cie.memory.organise`)

The bank is browsable as well as searchable, from the records it already holds
(nothing generated, every value a record, a count or an edge):

* `entity_profile(entity)`: everything addressable about one organisation or
  person, grouped by record type, newest first, current only unless history is
  asked for, as of a date if given; with the documents involved, open questions
  and recorded contradictions. Backed by JSONB containment on `entity_ids`
  (GIN, `jsonb_path_ops`) and the `mentions` edges, so it costs the same at a
  million records as at a thousand.
* `document_card(document)`: what one document contributed: parties, people,
  values, deadlines, obligations, risks, decisions, open questions,
  superseded records, contradiction edges and the version chain.
* `scope_digest(scope)`: what a department or project holds: record and
  document counts by type from the scope/type index, the most mentioned
  entities from the `mentions` edges, newest documents, conflicts.
* `find_entities(q)`: entities by name or alias (trigram index on the
  canonical name, keyword index on normalised aliases).

Entity resolution (`cie.memory.entities`) is company-wide for organisations
(a supplier first met by one project is the same supplier elsewhere) and
department-wide for people. It scores only index-served candidates: names
sharing trigrams with the mention, or whose recorded aliases contain it
(aliases are kept normalised in the indexed `keywords`); an exact normalised
match wins outright, so "Northwind Logistics 37 Ltd" is never confused with
"Northwind Logistics 3 Ltd" by a fuzzy score.

Exposed as `GET /memory/entities?q=`, `GET /memory/entities/{id}/profile`,
`GET /documents/{id}/card`, `GET /scopes/{id}/digest`; all permission-filtered
by the same predicate as search.

## D3. Structured-source ingestion (`cie.ingest`)

Exported records from company systems (chat, e-mail, tickets, pull requests,
wiki, drive, CRM, meetings) are turned into the full memory bank at bulk speed:
field-aware sections, memory cards (extractive summary, tags, people, companies,
project, identifiers), typed records from structured fields and prose, company-wide
entities and projects, cross-document references, near-duplicates and the facts
they disagree on. Details and the measurement in `docs/MEMORY_BANK.md`.

## E. Glyphs (`cie.memory.glyph`)

A glyph is a typed, compact memory card stored as JSONB inside the record:
what, who, why, project/department, time, status, dependencies, consequences,
confidence, evidence pointers. It is built deterministically from the record
and its edges. It is a navigation structure; it never replaces the source.
`cie.eval.bench_glyph` compares the glyph's storage encodings (JSON, zlib,
msgpack, columnar, and a PNG "pixel" encoding) and reports the winner. Exotic
encodings that fail exact round-trip or searchability are rejected.

## F. Hybrid retrieval (`cie.retrieval`)

`Retriever.retrieve(query, principal, scope, filters)`:

1. `intent.classify` (exact-id, exact-field, entity, definition, temporal,
   comparison, list, open) plus hints: clause numbers, quoted phrases, record
   type hints, an `as of` date, whether history is wanted.
2. Scope and permission resolution: addressable scopes of the query scope ∩
   scopes visible to the principal; the permission predicate and the
   point-in-time predicate (`valid_from ≤ t < valid_to`, not superseded unless
   history is asked for) are compiled into one SQL filter used by every search.
3. `exact.lookup`: record ids, clause numbers, quoted phrases, entity names
   (trigram), keyword overlap.
4. Lexical (PostgreSQL FTS, OR of content terms ranked by `ts_rank_cd`) ∥
   vector (pgvector cosine, HNSW) over records and sections. When the query
   names a document or supplier that appears in a file title, an extra search
   restricted to those documents is added, because templated files tie on text
   and the named file's clause would otherwise be cut at the candidate limit.
   Reciprocal-rank fusion merges all lists.
5. `graph.expand`: bounded BFS over the sparse record graph with three horizons
   and budget `⌈c·log2 N⌉`; neighbours outside the query scope are deferred to
   horizon 3 and admitted only if the principal may read them.
6. `rerank`: every candidate gets an **evidence support** score in [0, 1]:
   IDF-weighted coverage of the question's informative terms (entity names and
   generic words excluded, whole-word prefix matching, terms absent from every
   candidate excluded from the denominator; if no informative term is present
   anywhere support is 0 for all). Vector similarity is deliberately not
   support: neural cosine is high for related text that does not answer the
   question. Final score = fused rank × (0.35 + 0.65·support) + support-scaled
   bonuses (type hint match, document/entity affinity) + verification and
   confidence terms − penalties (superseded unless history asked, document
   stubs, drafts unless asked, entity records for non-entity questions, hubs,
   graph distance, other documents when a document is named).
7. `contradictions.check` pulls the other side of every `contradicts` edge.
8. `packet.build`: 20–100 records within a token budget; flagged
   prompt-injection sentences are redacted in packet text; the packet and its
   trace are stored so any answer can be reproduced.
9. `answer`: strict mode is extractive (value + quote for exact-field
   questions, summary + quoted detail otherwise; a `conflict` status when a
   leading record has a contradiction partner in the packet; `insufficient
   evidence` when no leading item has support ≥ 0.34). Assisted mode calls the
   LLM with items wrapped as untrusted data and drops claims the packet does
   not support.
10. Raw pages are fetched only via `/sources/{document_id}/pages/{n}`.

### Vector index precision

With pgvector 0.7 or newer the HNSW indexes are built on `embedding::halfvec`
(16-bit floats) by the `b7c8d9e0f1a2` migration: half the index size and a
faster build; the scale benchmark reports the hit rate with it. Older pgvector
keeps float32 indexes, and `cie.retrieval.vector` detects which kind the
database has so the query expression matches the index.

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
