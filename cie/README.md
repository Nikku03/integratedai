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

## Showcase

`notebooks/showcase_colab.ipynb` (Colab, any GPU) loads 5,000 documents of the EnterpriseRAG-Bench company and runs
`cie.eval.showcase`:
1. example questions answered with citations, beside the benchmark's expected answers;
2. a supplier delay that turns a fictional project's answer from "can deliver" to "cannot", routed and re-answered
   in seconds;
3. a cell to ask your own question.

On a loaded memory bank: `python -m cie.eval.showcase --tenant <name> --root <EnterpriseRAG-Bench checkout>`. It
writes `showcase.html`. Measured results: `docs/BENCHMARKS.md`.

## Does the memory bank beat plain search?

`notebooks/memory_test_colab.ipynb` (Colab, A100 or H100) runs `cie.eval.memory_test`. It asks 243 questions that a
memory bank is meant for: owners, deadlines, lists and conflicts. Each one is answered five ways, with plain search and
with the memory bank, by the same model. The rules that decide are in
[`docs/MEMORY_TEST_PREREGISTRATION.md`](docs/MEMORY_TEST_PREREGISTRATION.md); the results go in
[`docs/MEMORY_TEST.md`](docs/MEMORY_TEST.md).

## Fact bank (the cell memory bank's design)

`cie.factbank` rebuilds the memory bank of the Nikku03/cell repository for company documents:
- one sourced fact per field, with a checker;
- SQLite lookup by subject;
- one hop at a time, with each result written down and votes when sources disagree;
- a journal that replays.

On 50 documents and 50 questions, its evidence held the answer far more often than the present memory bank's (0.987
against 0.630), and it answered 88% of the questions with no model. It is 30 times faster. Its storage missed the
pre-registered bar, so it does not replace the bank yet. See [`docs/FACTBANK_RESULTS.md`](docs/FACTBANK_RESULTS.md).

Taught on those 50 documents, then retested on 50 others with reworded questions and changed names and dates
([`docs/FACTBANK_LEARNING_RESULTS.md`](docs/FACTBANK_LEARNING_RESULTS.md)):
- **What carried over:** its evidence put the answer in the first 2,000 characters 89% of the time, against 72%
  untrained. Lists were all right in new wording.
- **What did not:** choosing a single answer. It learned the word "due", not the idea of a deadline.
- **Changed information:** renaming everyone and moving every date changed nothing.

**Questions that need several documents**, such as "who has the Linear issue that PR #123 links to?" or "how many issues
does P have?". The fact bank enumerates plans: a start, hops between documents, a field and a way to combine. Learned
weights pick one ([`docs/FACTBANK_MULTI_RESULTS.md`](docs/FACTBANK_MULTI_RESULTS.md)):
- **Reaching the pieces:** the right plan was always among those enumerated. The evidence held every piece of 0.99 of
  the questions, against 0.32 for the present memory bank.
- **Choosing the plan:** the first version failed (0.08 on held-out questions). It had learned to copy from the
  question.
- **The revised version:** on 50 new documents with new wordings, 0.60 of its own answers were right, against 0.25 for
  the first version. Changed names and dates made no difference.
- **Not met:** it scored 0.93 on its training questions. New words still trip it ("own", "nearest deadline").

**New words without a language model** ([`docs/FACTBANK_WORDS_RESULTS.md`](docs/FACTBANK_WORDS_RESULTS.md)): word
meanings were learned by counting over 200,000 of the company's documents, and a new word borrowed the meaning of the
nearest known one. It did not help: 0.58 against 0.61 without it, on 50 questions where half the words were new. This
technical text places words by topic ("created" next to "ticket") rather than by meaning. Most of the plain English
words in managers' questions ("responsible", "urgent", "tally") found no close known word.

## Brain-wired reasoning neurons (research)

`cie.neuro` wires the reasoning engine's spiking neurons like a piece of Blue Brain's cortex model (directed cliques of
up to 5 neurons) and switches them on and off with light (ChR2 and NpHR, with PyRhO's fitted kinetics). The
pre-registered test found that the brain wiring changes nothing: composition, robustness and speed are no better
than with random wiring, and a plain network does better. See [`docs/BRAIN_WIRING_RESULTS.md`](docs/BRAIN_WIRING_RESULTS.md).

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
REM (`docs/REM.md`): dependency exploration, evidence selection and change-impact
tracking over a versioned business graph in PostgreSQL — `POST /api/rem/query`,
`POST /api/rem/changes`, `GET /api/rem/impacts/{event_id}`, `GET /api/rem/explanations/{result_id}`,
`cie rem demo|ingest|query|change|replay|bench`; results against the baselines in
`docs/REM_RESULTS.md`.
Out-of-sample test on EnterpriseRAG-Bench (512k-document company corpus, 500
questions): `python -m cie.eval.bench_enterprise --root <checkout> --docs N`
(`--memory full` builds the full memory bank described in `docs/MEMORY_BANK.md`;
`--memory chunks` loads sections only)
(results in `docs/BENCHMARKS.md`; answers files for the benchmark's LLM judge in
`eval_out/enterprise`).
Scale benchmark of the memory bank and retrieval at 10k / 100k / 1M records:
`python -m cie.eval.bench_scale` (results in `docs/BENCHMARKS.md`; add
`--remeasure` to measure again the tenants an earlier run loaded, without the
load and index build), or the notebook `notebooks/scale_benchmark_colab.ipynb`
on Colab with a GPU.

## Configuration

See `.env.example`. Notable switches: `CIE_LLM_PROVIDER` (`none` = strict
extractive answers; `anthropic|openai|gemini|local` enable assisted answers and
LLM agent strategies; `local` is any OpenAI-compatible server such as Ollama running
Llama 3.1 8B or Llama 3.2 3B, set with `CIE_LLM_MODEL` and `CIE_LLM_BASE_URL`, and gets
deterministic, length-bounded generation and a budgeted share of the evidence,
`CIE_LLM_LOCAL_EVIDENCE_CHARS`), `CIE_EMBEDDING_PROVIDER` (`fastembed` local ONNX model,
`hashed` no-model fallback, `openai`), `CIE_OCR_BACKEND` (`auto`, `tesseract`,
`unlimited_ocr`: Baidu's Unlimited-OCR through `CIE_UNLIMITED_OCR_URL`, a vLLM/SGLang
server, or loaded on this machine's CUDA GPU; `auto` uses it whenever a GPU or server is
there, and Tesseract otherwise: see `docs/OCR_RESULTS.md`), `CIE_LEXICAL_ENGINE` (`bm25`, the default: a BM25 index per tenant, built by
`cie bootstrap`, by bulk loads or with `cie lexical build --tenant <name>`, and kept current
by the worker; `fts`: PostgreSQL full text, which is also the fallback for a tenant without
an index), `CIE_PACKET_EXPAND_DOCUMENTS` (3, the default: the best passages of the first 3
documents join the packet, `CIE_PACKET_EXPAND_SECTIONS` each; 0 turns it off: see
`docs/EXPANSION_RESULTS.md`),
`CIE_LLM_PROVIDER` (`openai` for ChatGPT models with `OPENAI_API_KEY`, `anthropic`, `local`, `gemini`, or `none`),
`CIE_LLM_MODEL` (e.g. `gpt-5.4`), `CIE_LLM_REASONING_EFFORT` (OpenAI reasoning models: `low`, `medium`, `high`),
`CIE_LLM_PRICE_IN` / `CIE_LLM_PRICE_OUT` (USD per million tokens, for a model missing from the price list; without
them its cost is reported unknown), `CIE_ENCRYPTION_KEY` (AES-GCM at rest for the vault).

## Layout

```
src/cie/core        settings, models (29 tables), db, util
src/cie/vault       content-addressed immutable storage, versions, integrity
src/cie/extraction  detectors, extractors (pdf/ocr/office/email/csv/text), corrections, sectioning, facts, checks, pipeline
src/cie/memory      scopes, records (supersede/contradict/confirm/extend), glyphs, entities, autolink, embeddings
src/cie/retrieval   intent, exact, lexical, vector, fusion, bounded graph expansion, rerank, contradictions, packet, answer
src/cie/agents      registry, scorecards, router, messages, ledger, planner, specialists, verification, head, providers
src/cie/governance  permissions (RBAC+ABAC), audit, scanners, retention/deletion
src/cie/rem         REM: versioned business graph, bounded exploration, change rules, evidence packets
src/cie/workers     durable job queue and worker
src/cie/api         FastAPI routes (core, agents, governance)
src/cie/eval        synthetic corpus, benchmarks, simulation, demo
dashboard/          React + TypeScript control dashboard
```
