# Roadmap: from MVP to a 200-million-token project memory

Token counts below are addressable memory (searchable storage), never model
context. At ~120 tokens per memory record and ~350 tokens per section, 200M
tokens is roughly 600k sections plus 1M records per project.

## Stage 0 (this build): single-node MVP
15-document synthetic corpus, one PostgreSQL, local embeddings, extractive
answers, five agents in-process. Measured in BENCHMARKS.md.

## Stage 1: production hardening (weeks)
* Run compose stack and load test; OIDC; rate limits; secret management (KMS
  key for vault encryption); backup/restore drill (pg_dump + object store
  replication) with a documented RTO/RPO.
* Live LLM providers: assisted answers and LLM specialist strategy behind the
  existing claim verifier; record provider usage for real token/cost metrics.
* Unlimited-OCR on GPU for scans; compare against Tesseract on the acceptance
  corpus (page accuracy, confidence, cost per page).
* Connectors: IMAP, Drive/SharePoint, Git; incremental sync with version
  detection (the folder connector already does this).

## Stage 2: 10M–50M tokens per project
* Partition `sections` and `memory_records` by tenant/scope; HNSW per
  partition; `ef_search` tuning; materialized "current" view for point-in-time
  queries.
* Move lexical search to OpenSearch (the `LexicalIndex` swap point) when
  Postgres FTS latency exceeds the 2 s p95 budget under load.
* Learned reranker (cross-encoder) behind the `rerank()` interface, trained
  on graded packets from the evaluation set and human corrections.
* Agent memory: per-agent scopes get summarization records (glyph rollups) so
  an agent's 50M-token history is navigable by glyphs before records.

## Stage 3: 200M tokens per project
* Tiered storage: hot records/sections in Postgres, cold sections in
  Parquet/zstd on object storage (the encoding benchmark's batch winner) with
  a section-id index; page images rendered on demand from the vault.
* Sharded vector index (per department) with scatter-gather retrieval and the
  same permission predicate pushed to each shard.
* Graph: keep edges in Postgres but add a compact adjacency cache (Redis) for
  horizon-1 expansion; budget stays ⌈c·log₂N⌉ so expansion cost grows
  logarithmically.
* Temporal (or equivalent) for long-running agent workflows and human
  approval waits; the job table remains for ingestion.

## Stage 4: company memory
* Department and company scopes populated by rollup agents that write
  decisions, metrics and risks as records with provenance to the project
  records they summarize.
* Cross-tenant isolation tests in CI; per-department retention policies;
  legal-hold sweeps.

## Research items (benchmark first, adopt only on measured gain)
* Cross-document contradiction detection with an NLI model behind the same
  conservative filter.
* Learned graph edge weights from agent usage (which expansions were cited).
* Glyph-only retrieval for agents (cards before records) measured on packet
  tokens and answer accuracy.
