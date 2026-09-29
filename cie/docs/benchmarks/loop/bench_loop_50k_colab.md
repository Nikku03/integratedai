# One-project loop benchmark (3 worlds, 20 changes each): test run as reported

Run on Colab (A100) by `notebooks/enterprise_rag_bench_colab.ipynb` Part 2, inside host tenant
`erbfull-50000-cb66f7` (50,000 EnterpriseRAG-Bench documents, full memory bank). The worlds were 301, 302 and 303;
the embeddings were `sentence_transformers[cuda]`; the wall time was 1,265.1 s. FICTIONAL, GENERATED project data;
expected answers from the generator's world model.

| Measure | loop | loop-explicit | no-routing |
|---|---|---|---|
| Needed records in the task context | 1.0 | 1.0 | 1.0 |
| Delay-question evidence found (traversal + search) | 0.97 | 0.9614 | 0.7482 |
| … of which passages found by search over the whole memory | 0.9949 | 0.9889 | 0.948 |
| Exhaustive scans incomplete | 0 | 0 | 0 |
| Findings passing verification | 1.0 | 1.0 | 1.0 |
| Published answers matching the oracle | 1.0 | 1.0 | 1.0 |
| Served answers matching the oracle (after each change) | 1.0 | 1.0 | 0.5335 |
| Stale answers served (not reopened or flagged) | 0 | 0 | 347 |
| Stale published findings | 0 | 0 | 432 |
| Affected projects / missed | 104 / 0 | 104 / 0 | 104 / 104 |
| Routed but not affected | 191 | 0 | 0 |
| Duplicate actions (versions / reopenings / transitions / suggestions) | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Tasks completed / total (re-runs) | 36 / 36 (295) | 36 / 36 (104) | 36 / 36 (0) |
| Event processing p50 / worst p95 (ms) | 228.5 / 517.2 | 156.7 / 389.3 | 122.2 / 293.6 |
| Context build p50 / worst p95 (ms) | 1569.4 / 3525.3 | 1524.0 / 3597.8 | 1671.9 / 3576.6 |
| Verification and publication p50 (ms) | 140.3 | 137.9 | 116.7 |
| Change to refreshed answers p50 / worst p95 (ms) | 12066.1 / 25743.4 | 3212.5 / 13250.5 | 122.2 / 293.6 |
| Delay question p50 (ms) | 1263.8 | 1293.9 | 1263.0 |
| Context tokens (total) | 17,011,025 | 7,378,809 | 1,945,175 |

Pre-registered criteria: **all met**, for both `loop` and `loop-explicit`. The values were:
- stale answers / stale published findings: 0 / 0;
- missed dependencies: 0 of 104;
- duplicate actions: 0 / 0 / 0 / 0;
- needed records in the context: 1.0, with no incomplete scans;
- findings verified: 1.0, and published answers correct: 1.0;
- tasks completed: 36 of 36, with none failed or waiting on a person.

| World | Arm | Served answers correct | Stale answers served | Missed | Re-runs |
|---|---|---|---|---|---|
| 301 | loop | 1.0 | 0 | 0 / 28 | 114 |
| 302 | loop | 1.0 | 0 | 0 / 30 | 84 |
| 303 | loop | 1.0 | 0 | 0 / 46 | 97 |
| 301 | loop-explicit | 1.0 | 0 | 0 / 28 | 28 |
| 302 | loop-explicit | 1.0 | 0 | 0 / 30 | 30 |
| 303 | loop-explicit | 1.0 | 0 | 0 / 46 | 46 |
| 301 | no-routing | 0.7143 | 72 | 28 / 28 | 0 |
| 302 | no-routing | 0.5292 | 113 | 30 / 30 | 0 |
| 303 | no-routing | 0.3571 | 162 | 46 / 46 | 0 |
