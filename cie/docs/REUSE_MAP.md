# Reuse map: what the two research repositories contribute

Both repositories were inspected before design. Verdicts below are based on
reading the code, not the docstrings, and on whether a committed benchmark
exists.

## `Nikku03/integratedai` (this repository, trading research stack)

| Component | Where | What it actually is | Verdict |
|---|---|---|---|
| Point-in-time discipline (`event_ts` vs `available_ts`, `LookaheadError`) | `src/iai/core/types.py`, `docs/ARCHITECTURE.md` | Two timestamps on every event; validation is a hard failure | **Reused as design.** Memory records are bitemporal: `valid_from/valid_to` (world time) and `recorded_at` (system time). "Current vs superseded" queries are point-in-time queries. |
| Pre-registration + RESULT culture | `docs/PREREG_*.md`, `docs/RESULT_*.md` | Hypothesis, criteria, result, failed criterion, consequence, all committed | **Reused as design.** The project ledger entry types (hypothesis, test, result, failure, consequence, artifact) copy this structure exactly. |
| Resumable batch extraction keyed by content id | `scripts/llm_extract.py` | JSONL written as results land; interrupted runs resume without re-paying | **Reused as design.** Extraction jobs checkpoint per page in `jobs.checkpoint`. |
| Ramanujan partition / pi features | `scripts/ramanujan.py`, `docs/RESULT_RAMANUJAN.md` | Number-theory features for price prediction; all three pre-registered tests failed | **Rejected.** Not a graph component. The name "Ramanujan" in the brief refers to expander graphs, which are benchmarked separately (`cie.eval.bench_graph`). |
| REM residual model | `scripts/rem_solver.py`, `docs/RESULT_REM.md` | Closed-form diffusion solver + residual MLP; MSE claim supported, trading claim not | **Rejected as code.** The "REM-inspired graph" in the brief is implemented from its description (sparse graph, bounded horizons, few long-range shortcuts), not from this script. |
| ADRNN | `scripts/adrnn_*.py`, `docs/RESULT_ADRNN.md` | Attention + residual GRU for move magnitude; lost to gradient boosting | **Rejected.** Nothing in it applies to document memory. |
| Filing corpus cleaning | `scripts/filing_corpus.py` | Conservative HTML-to-text with header cut | **Idea reused** in the email/HTML extractor: strip noise, never summarize at extraction time. |

## `Nikku03/enzyme_Software` (chemistry, cell simulation, trading lab)

Searched for: memory bank, glyph, pixel, frequency/DNA/shape encoding, graph,
expander, REM, compression, ADRN/ADRNN, orchestration, agent, OCR, embeddings.

**Not present at all:** glyph or pixel encodings, ADRN/ADRNN, text or record
compression, a knowledge graph, an LLM adapter, OCR, embeddings, or any
multi-agent code. All "memory" code is molecular analogy retrieval over RDKit
fingerprints, none of it covered by a test or a committed benchmark.

| Component | Path | Verdict |
|---|---|---|
| Content-addressed dataset vault (sha256 of bytes, refuses invalid data, integrity re-check, tested) | `trading_research_lab/src/lab/data/vault.py` | **Reused as design** for `cie.vault` (blobs keyed by sha256, verify on read). |
| Score ledger / scorecard primitives (`ScoreTerm`, `ScoreCardMetric`, `low_support` when n<5, tested) | `src/enzyme_software/score_ledger.py`, `scorecard.py` | **Reused as design** for `agent_scorecards` (n_tasks gates confidence in a score). |
| Evidence store schema (runs, outcomes, artifacts, datapoints, literature evidence) | `src/enzyme_software/evidence_store.py` | **Reused as design** for the project ledger. |
| Explainable expert router (gate weight = confidence × input-availability penalty × support penalty, with a human-readable summary) | `src/enzyme_software/moe_router.py` | **Reused as design** for `cie.agents.router` (every assignment carries a reason object). |
| Consistency market (cross-module contradiction penalty with named reasons) | `src/enzyme_software/unity_layer.py` | **Reused as design** for conflict detection between agent conclusions. |
| Anti-loop pivot controller + sealed evaluator + leaderboard (tested) | `trading_research_lab/src/lab/loop_controller.py` | **Reused as design** for head-agent stagnation handling (two rounds without new artifacts force a pivot or escalation). |
| Hyperbolic memory bank (shortlist → diversity → hub penalty → softmax mixture, cached bank) | `nexus/reasoning/hyperbolic_memory.py` | **Idea only.** The hub penalty and diversity selection inform the reranker. Poincaré embeddings are not adopted: no benchmark exists and cosine on pgvector is the conventional baseline to beat. |
| Precedent logbook (leave-one-out by content key, 6-dim evidence brief) | `liquid_nn_v2/model/precedent_logbook.py` | **Idea only.** The "brief" concept became the glyph's `evidence` block. Leave-one-out by content hash is used in the retrieval benchmark to stop a query retrieving its own source. |
| PGW transport, NFTM, DAG learner, ucme/uce banks, V22 notebook (never executed), byte-identical `nexus_sorted/` copies | various | **Rejected.** Domain-bound or unvalidated. |

## What this means for the brief's experimental concepts

Each is implemented only as a benchmark harness with a conventional baseline;
none is adopted by default:

* **Pixel/glyph/frequency/shape/DNA encodings** → `cie.eval.bench_glyph` compares
  JSON, zlib-JSON, msgpack, columnar (Arrow/Parquet when installed) and a PNG
  "pixel" encoding on size, encode/decode latency, exact round-trip and
  searchability. See `docs/BENCHMARKS.md` for the measured result.
* **Ramanujan/expander topology** → `cie.eval.bench_graph` compares a kNN sparse
  graph, kNN + random long-range shortcuts, and a Ramanujan-style expander
  overlay on recall@k under a fixed expansion budget.
* **REM-inspired bounded-horizon retrieval** → `cie.retrieval.graph` with three
  horizons and a log(N) budget; compared against hybrid-only retrieval in
  `cie.eval.bench_retrieval`.
