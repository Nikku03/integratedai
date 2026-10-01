# One-project loop benchmark: a second run of study 2's worlds, as reported

Run on Colab (A100) by `notebooks/enterprise_rag_bench_colab.ipynb` Part 2, with `RUN_LOOP` turned on, inside host
tenant `erbfull-50000-7db44b` (a fresh load of the same 50,000 documents). The code was c00ed8d, in which BM25 is the
default keyword engine. The worlds were 304, 305 and 306, as in study 2's test run (`bench_loop_50k_colab_study2.md`),
so this is a repeat, not a new test. The embeddings were `sentence_transformers[cuda]`; the model was `llama3.1:8b`
through Ollama; the wall time was 1,919.7 s. FICTIONAL, GENERATED project data.

| Measure | loop | loop-relied | llm-relied | llm-no-routing |
|---|---|---|---|---|
| Needed records in the task context | 1.0 | 1.0 | 1.0 | 1.0 |
| Needed records the answer relied on (its inputs) | 1.0 | 1.0 | 1.0 | 0.9445 |
| Delay-question evidence found (traversal + search) | 0.9161 | 0.9088 | 0.8933 | 0.891 |
| … of which passages found by search over the whole memory | 0.8925 | 0.9277 | 0.9132 | 0.901 |
| Exhaustive scans incomplete | 0 | 0 | 0 | 0 |
| Findings passing verification | 1.0 | 1.0 | 0.5282 | 0.5342 |
| Published answers matching the oracle | 1.0 | 1.0 | None | None |
| Served answers matching the oracle (after each change) | 1.0 | 1.0 | 0.0 | 0.0 |
| Answers right when given | 1.0 | 1.0 | 0.0 | 0.0 |
| … delivery verdict / budget verdict / cost / milestones at risk right | 1.0 / 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 / 1.0 | 0.5032 / 0.7032 / 0.0 / 0.1936 | 0.4412 / 0.7941 / 0.0 / 0.0588 |
| Wrong answers served because the analyst erred | 0 | 0 | 756 | 714 |
| Runs without a usable answer | 0 | 0 | 1 | 4 |
| Wrong cost or budget figures / blocked by verification | 0 / 0 | 0 / 0 | 155 / 155 | 34 / 34 |
| Right figures blocked by verification | 0 | 0 | 0 | 0 |
| Stale answers served (right when given, wrong now, not reopened or flagged) | 0 | 0 | 0 | 0 |
| Stale published findings | 0 | 0 | 0 | 393 |
| Affected projects / missed | 119 / 0 | 119 / 0 | 119 / 0 | 113 / 113 |
| Routed but not affected | 165 | 0 | 0 | 0 |
| Affected projects whose task held no answer | 0 | 0 | 0 | 6 |
| Duplicate actions (versions / reopenings / transitions / suggestions) | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Tasks completed / total (re-runs) | 36 / 36 (284) | 36 / 36 (119) | 36 / 36 (119) | 34 / 36 (0) |
| Event processing p50 / worst p95 (ms) | 229.0 / 553.0 | 160.5 / 409.2 | 170.3 / 504.1 | 140.4 / 476.8 |
| Context build p50 / worst p95 (ms) | 1414.3 / 3916.0 | 1338.1 / 4063.2 | 1785.4 / 4315.9 | 1523.7 / 2924.6 |
| Verification and publication p50 (ms) | 152.7 | 153.1 | 113.7 | 110.9 |
| Change to refreshed answers p50 / worst p95 (ms) | 9642.3 / 23815.6 | 2872.7 / 12442.3 | 5339.7 / 21683.3 | 140.4 / 476.8 |
| Delay question p50 (ms) | 1019.5 | 1187.5 | 1171.1 | 1265.6 |
| Context tokens (total) | 16,573,492 | 8,255,541 | 8,620,612 | 1,771,970 |
| Model calls / tokens in / tokens out | 0 / 0 / 0 | 0 / 0 / 0 | 157 / 109,979 / 34,350 | 42 / 28,254 / 8,528 |
| Model replies not in the requested JSON form / invented record ids / failed calls | 0 / 0 / 0 | 0 / 0 / 0 | 2 / 0 / 0 | 8 / 0 / 0 |
| Model call p50 / worst p95 (ms) | – | – | 1716.4 / 2379.6 | 1647.5 / 2142.8 |
| Model cost (USD) | 0.0 | 0.0 | 0.0 | 0.0 |

Pre-registered criteria (`docs/LOOP_PREREGISTRATION.md`, study 2): **all met** (loop 1 to 6, loop-relied 1 to 7,
llm-relied 1 to 4), with the same values as the table above: no stale answers or stale published findings, 0 of 119
missed, no duplicate actions, every needed record in context with no incomplete scan, findings verified 1.0 and
published answers 1.0 in the deterministic arms, 36 of 36 tasks completed, 0 unaffected re-runs for loop-relied.

| World | Arm | Right when given | Served answers correct | Stale served | Missed | Re-runs | Context tokens | Model calls |
|---|---|---|---|---|---|---|---|---|
| 304 | loop | 1.0 | 1.0 | 0 | 0 / 49 | 142 | 7,908,458 | – |
| 305 | loop | 1.0 | 1.0 | 0 | 0 / 32 | 74 | 3,963,461 | – |
| 306 | loop | 1.0 | 1.0 | 0 | 0 / 38 | 68 | 4,701,573 | – |
| 304 | loop-relied | 1.0 | 1.0 | 0 | 0 / 49 | 49 | 3,684,652 | – |
| 305 | loop-relied | 1.0 | 1.0 | 0 | 0 / 32 | 32 | 2,180,450 | – |
| 306 | loop-relied | 1.0 | 1.0 | 0 | 0 / 38 | 38 | 2,390,439 | – |
| 304 | llm-relied | 0.0 | 0.0 | 0 | 0 / 49 | 49 | 4,193,737 | 63 |
| 305 | llm-relied | 0.0 | 0.0 | 0 | 0 / 32 | 32 | 2,092,893 | 44 |
| 306 | llm-relied | 0.0 | 0.0 | 0 | 0 / 38 | 38 | 2,333,982 | 50 |
| 304 | llm-no-routing | 0.0 | 0.0 | 0 | 47 / 47 | 0 | 646,395 | 15 |
| 305 | llm-no-routing | 0.0 | 0.0 | 0 | 28 / 28 | 0 | 600,544 | 15 |
| 306 | llm-no-routing | 0.0 | 0.0 | 0 | 38 / 38 | 0 | 525,031 | 12 |

The last reply of each model arm that was not in the requested JSON form (abridged as printed by the run):
- `llm-relied`, 214 tokens: `... "cost": 10800.0 + 12301.0 + 840.0, "budget": 20871.0, "within_budget": true, "feasible": true}`
- `llm-no-routing`, 186 tokens: `... ": 138 * 31 + 371 * 58 + 27 * 56, "budget": 35500.0, "within_budget": true, "feasible": true}`
