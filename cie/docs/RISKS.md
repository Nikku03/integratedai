# Risky assumptions and how they are handled

| # | Assumption | Risk if wrong | Mitigation in this build |
|---|---|---|---|
| 1 | Postgres FTS is "good enough" lexical search at MVP scale | Ranking quality below BM25; no phrase/fuzzy tuning | `LexicalIndex` interface; benchmark harness includes a true in-memory BM25 arm so the gap is measured, not assumed |
| 2 | A 384-d small embedding model gives acceptable recall | Semantic recall below the 90% target on hard queries | Hybrid fusion with lexical + exact lookup; benchmark reports recall@20 per arm; model is a config value |
| 3 | Tesseract quality on real scans | OCR errors break exact-field accuracy | Confidence stored per page/block; correction layer separate from extraction; Unlimited-OCR adapter for a stronger model; completeness checks flag low-confidence pages for human review |
| 4 | Deterministic fact extraction (regex/rules) is enough for the vertical slice | Records too shallow without an LLM | Rule extraction covers dates, money, parties, clauses, requirements, deadlines; LLM extraction is a pluggable strategy; every record is marked with its producing method |
| 5 | Heuristic reranking (no cross-encoder) meets the 2 s p95 and quality targets | Precision below cross-encoder rerankers | Reranker is an interface; a cross-encoder can be dropped in; benchmark reports precision |
| 6 | Bounded graph expansion with a log(N) budget adds recall on cross-document questions | Extra latency with no gain | `bench_retrieval` compares hybrid vs hybrid+graph; graph expansion is off when the benchmark shows no gain |
| 7 | Expander (Ramanujan) topology helps | Complexity with no measurable gain | Only a benchmark; not wired into production paths unless it wins |
| 8 | A glyph JSON card is the right compact representation | Exotic encodings might be smaller | `bench_glyph` measures size, speed, exact round-trip and searchability; exotic encodings rejected on any failure |
| 9 | Postgres job table can replace Temporal for MVP | Weak at very high throughput and long-running sagas | Per-page checkpoints and lease timeouts make it resumable; Temporal is a roadmap swap |
| 10 | Rule-based head-agent planning is adequate without an LLM | Plans too rigid for open-ended objectives | Planner is a strategy; LLM planner adapter provided; the simulation uses the rule planner so results are reproducible |
| 11 | Scorecards seeded at neutral values will converge | Cold-start routing is arbitrary | Routing explanation always shown; `n_tasks < 5` marks a score as low-support and routes by skills/permissions/cost instead |
| 12 | Permission filtering in SQL is complete | A path that bypasses the filter leaks data | Single `visible_scope_ids()` + sensitivity ceiling used by every query; access-control test suite asserts zero unauthorized results |
| 13 | Prompt-injection detection by pattern is sufficient | Novel injections pass | Detection is a flag, not a guarantee; retrieved text is always passed to models inside a data envelope and never as instructions |
| 14 | 200M-token project memory scales on a single Postgres | HNSW build time and index size grow | Sharding by tenant/scope and external vector store are roadmap; storage report gives per-record bytes so the scale can be projected |
| 15 | No LLM API key in the build environment | Assisted mode untested against a live model | Provider adapters are exercised with a fake provider that follows the same interface; live calls are marked untested in KNOWN_LIMITATIONS |
