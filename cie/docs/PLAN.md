# Implementation plan

## Decisions taken without asking (defaults, all replaceable)

| Decision | Default | Why | Swap point |
|---|---|---|---|
| Code location | `cie/` sub-project inside `integratedai` | The trading stack in `src/iai` stays untouched; CIE has its own `pyproject.toml`, venv, tests and compose file | Move to its own repo by copying `cie/` |
| Lexical search | PostgreSQL full-text (`tsvector`, `ts_rank_cd`) | Zero extra services for the MVP; interface `LexicalIndex` | `cie.retrieval.lexical.OpenSearchIndex` (adapter skeleton, marked not implemented) |
| Vector search | pgvector HNSW, cosine, 384-d | Same database as metadata, permission filter in the same query | Any `VectorIndex` implementation |
| Embeddings | `fastembed` ONNX `BAAI/bge-small-en-v1.5` (local, CPU) | Real semantic embeddings without GPU or API key; downloaded once | `hashed` (no model, tests) or `openai` |
| Graph store | Postgres `record_links` table + Python bounded BFS | Sparse graph with a log(N) budget touches few rows; no Neo4j operational cost | `GraphStore` protocol; Neo4j adapter is roadmap |
| Workflow engine | Postgres job table with `SKIP LOCKED` and per-page checkpoints | Durable, resumable, testable without Temporal | Temporal worker is roadmap |
| Object store | local filesystem; MinIO via `s3` backend in compose | | `VaultBackend` |
| LLM | `none` by default: strict evidence mode is extractive | No API key in the build environment; answers stay reproducible | `anthropic`, `openai`, `gemini`, `local` adapters; `fake` for tests |
| OCR | `auto`: PyMuPDF text layer, Tesseract for scanned pages | Both run locally | `unlimited_ocr` adapter against a vLLM/SGLang endpoint |
| Token counting | provider usage when available, else estimate | Labelled as estimate everywhere | |
| Auth | API key per principal (`X-API-Key`) | Simple and auditable | OIDC is roadmap |

## Repository structure

```
cie/
  pyproject.toml            package metadata, deps, pytest/ruff config
  alembic/                  migrations
  docker-compose.yml        postgres(pgvector) · redis · minio · api · worker · dashboard
  Dockerfile
  config/                   example agent registry and policies
  docs/                     ARCHITECTURE, SCHEMA, PLAN, RISKS, REUSE_MAP, API, SECURITY,
                            BENCHMARKS, COST_STORAGE, KNOWN_LIMITATIONS, ROADMAP, SETUP
  src/cie/
    core/       settings · logging · db · models · util
    vault/      backends (local, s3) · service (ingest, versions, verify)
    extraction/ detect · extractors (pymupdf, tesseract, unlimited_ocr, text, html,
                email, csv, code) · corrections · sectioning · facts · checks · pipeline
    memory/     scopes · records (supersede/contradict/confirm/extend) · glyph ·
                graph (edges) · embeddings · indexing
    retrieval/  intent · scope resolution · exact · lexical · vector · fusion ·
                graph expansion · rerank · contradictions · packet · answer
    agents/     registry · scorecards · router · messages · head · specialists ·
                scheduler · verification · ledger · providers (LLM adapters)
    governance/ permissions · audit · scanners (pii, secrets, injection) ·
                retention · approvals
    workers/    job queue · worker loop
    api/        FastAPI app and routers
    eval/       synthetic corpus · acceptance · bench_retrieval · bench_graph ·
                bench_glyph · cost report
    cli.py
  tests/
  dashboard/                React + TypeScript (Vite)
```

## Phases

**Phase 1 – Foundation (vertical slice).** Vault, ingestion API, job queue,
extractors, sectioning, FTS + vector indexes, citations, extractive cited
answer, audit trail. Exit test: ingest a PDF, ask a question, get an answer
with page-level citation, view the page, see the audit entries.

**Phase 2 – Structured memory.** Typed records, entity resolution, glyphs,
supersede/contradict/confirm/extend, graph with three horizons and budget,
hybrid retrieval with rerank and contradiction check, glyph and graph
benchmarks.

**Phase 3 – Multi-agent.** Registry, scorecards, router with reasons,
head-agent planning, dependency scheduler, structured messages, verification,
synthesis, hash-chained ledger, simulation harness.

**Phase 4 – Company deployment.** Department/company scopes, RBAC/ABAC,
scanners, retention and deletion workflow, approvals, dashboard, compose,
metrics, backup notes.

Each phase has its own test module and is finished (tests green) before the
next begins. The order of work in this session followed the phases.

## Vertical slice (Phase 1 exit)

```
POST /ingest (file) → blob + document → job extract_document
  → pages/blocks (with bbox) → sections (tsv, embedding) → derived records
POST /search  → evidence packet (records + sections, scores, trace)
POST /answer  → extractive answer, citations [{document_id, page_no, bbox, quote}]
GET  /sources/{doc}/pages/{n}  → page text + block boxes; /image → rendered page
GET  /audit?resource_id=...    → every access to the evidence
```
