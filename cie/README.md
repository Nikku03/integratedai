# Company Intelligence Engine (CIE)

Shared organizational memory and a multi-agent operating system. Raw files go
into an immutable vault; extraction produces page- and box-level provenance;
typed, versioned memory records and a sparse graph sit above it; hybrid
retrieval assembles small evidence packets; a head agent runs five specialist
agents on dependent work and writes everything to an append-only ledger.

* Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
* Schema: [`docs/SCHEMA.md`](docs/SCHEMA.md) · API: [`docs/API.md`](docs/API.md) · Security: [`docs/SECURITY.md`](docs/SECURITY.md)
* Benchmarks and acceptance results: [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) · Cost/storage: [`docs/COST_STORAGE.md`](docs/COST_STORAGE.md)
* Known limitations: [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) · Roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md)
* What was reused from the research repositories: [`docs/REUSE_MAP.md`](docs/REUSE_MAP.md)

## Quick start (Docker Compose)

```bash
cd cie
docker compose up -d --build            # postgres(pgvector), redis, minio, api, 2 workers, dashboard
docker compose exec api cie bootstrap --tenant acme --company "Acme" --admin admin
#  -> prints {"company_scope_id": "...", "api_key": "..."}
export CIE_KEY=<api_key> SCOPE=<company_scope_id>
curl -H "X-API-Key: $CIE_KEY" -F file=@contract.pdf -F scope_id=$SCOPE -F doc_type=contract localhost:8000/api/ingest
curl -H "X-API-Key: $CIE_KEY" -H 'content-type: application/json' \
     -d '{"query":"What is the monthly fee in clause 3.1?","scope_id":"'$SCOPE'"}' localhost:8000/api/answer
```

Dashboard: http://localhost:5173 (enter the API key in Settings). API docs: http://localhost:8000/docs.

## Local development (no Docker)

Requires PostgreSQL 16 with the `vector` and `pg_trgm` extensions, Tesseract
(`apt install tesseract-ocr`) and `libmagic1`.

```bash
cd cie
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -e ".[dev,embeddings]"
createdb cie && psql cie -c 'create extension vector; create extension pg_trgm;'
cp .env.example .env                    # adjust CIE_DATABASE_URL
cie migrate && cie bootstrap
cie serve --reload &                    # API on :8000
cie worker &                            # processes ingestion and agent jobs
```

Tests (needs a `cie_test` database): `pytest -m "not slow"`; the 300-page OCR
acceptance test: `pytest -m slow`. Benchmarks: `cie bench all`; multi-agent
simulation: `cie simulate`; the end-to-end vertical slice: `cie demo`.
Organisation views (entity profile, document card, scope digest) are under
`/api/memory/entities`, `/api/documents/{id}/card` and `/api/scopes/{id}/digest`.
The topological memory bank (Blue Brain cliques and cavities, `docs/TOPOLOGY.md`)
is a retrieval arm (`graph_mode="cliques"`) compared against the standard bank by
`python -m cie.eval.bench_topology`.
The dynamic bank (`CIE_DYNAMIC_MEMORY=true`) forms new links and shapes from the
answers it gives; `GET /memory/shapes` shows them, `python -m cie.eval.bench_dynamic`
measures them against the static bank.
Scale benchmark of the memory bank and retrieval at 10k / 100k / 1M records:
`python -m cie.eval.bench_scale` (results in `docs/BENCHMARKS.md`; add
`--remeasure` to measure again the tenants an earlier run loaded, without the
load and index build), or the notebook `notebooks/scale_benchmark_colab.ipynb`
on Colab with a GPU.

## Configuration

See `.env.example`. Notable switches: `CIE_LLM_PROVIDER` (`none` = strict
extractive answers; `anthropic|openai|gemini|local` enable assisted answers and
LLM agent strategies), `CIE_EMBEDDING_PROVIDER` (`fastembed` local ONNX model,
`hashed` no-model fallback, `openai`), `CIE_OCR_BACKEND` (`auto`, `tesseract`,
`unlimited_ocr` with `CIE_UNLIMITED_OCR_URL` pointing at a vLLM/SGLang server),
`CIE_ENCRYPTION_KEY` (AES-GCM at rest for the vault).

## Layout

```
src/cie/core        settings, models (29 tables), db, util
src/cie/vault       content-addressed immutable storage, versions, integrity
src/cie/extraction  detectors, extractors (pdf/ocr/office/email/csv/text), corrections, sectioning, facts, checks, pipeline
src/cie/memory      scopes, records (supersede/contradict/confirm/extend), glyphs, entities, autolink, embeddings
src/cie/retrieval   intent, exact, lexical, vector, fusion, bounded graph expansion, rerank, contradictions, packet, answer
src/cie/agents      registry, scorecards, router, messages, ledger, planner, specialists, verification, head, providers
src/cie/governance  permissions (RBAC+ABAC), audit, scanners, retention/deletion
src/cie/workers     durable job queue and worker
src/cie/api         FastAPI routes (core, agents, governance)
src/cie/eval        synthetic corpus, benchmarks, simulation, demo
dashboard/          React + TypeScript control dashboard
```
