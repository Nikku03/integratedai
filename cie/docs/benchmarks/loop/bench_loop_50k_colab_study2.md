# One-project loop benchmark, study 2 (3 worlds, 20 changes each): test run as reported

Run on Colab (A100) by `notebooks/enterprise_rag_bench_colab.ipynb` Part 2, inside host tenant
`erbfull-50000-96a2d0` (50,000 EnterpriseRAG-Bench documents, full memory bank). The notebook checked out the head
of branch `claude/epic-keller-gevn7j`, which was cbe890a. The worlds were 304, 305 and 306; the embeddings were
`sentence_transformers[cuda]`; the model was `llama3.1:8b` through Ollama on the same GPU; the wall time was
2,915.7 s. FICTIONAL, GENERATED project data; expected answers from the generator's world model.

| Measure | loop | loop-relied | llm-relied | llm-no-routing |
|---|---|---|---|---|
| Needed records in the task context | 1.0 | 1.0 | 1.0 | 1.0 |
| Needed records the answer relied on (its inputs) | 1.0 | 1.0 | 0.9944 | 0.9722 |
| Delay-question evidence found (traversal + search) | 0.906 | 0.9162 | 0.916 | 0.9057 |
| … of which passages found by search over the whole memory | 0.9931 | 0.9815 | 0.9931 | 0.9523 |
| Exhaustive scans incomplete | 0 | 0 | 0 | 0 |
| Findings passing verification | 1.0 | 1.0 | 0.5242 | 0.527 |
| Published answers matching the oracle | 1.0 | 1.0 | None (none published) | None (none published) |
| Served answers matching the oracle (after each change) | 1.0 | 1.0 | 0.0 | 0.0 |
| Answers right when given | 1.0 | 1.0 | 0.0 | 0.0 |
| … delivery verdict / budget verdict / cost / milestones at risk right | 1.0 / 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 / 1.0 | 0.5197 / 0.7171 / 0.0 / 0.2039 | 0.4571 / 0.7714 / 0.0 / 0.0286 |
| Wrong answers served because the analyst erred | 0 | 0 | 735 | 735 |
| Runs without a usable answer | 0 | 0 | 2 | 2 |
| Wrong cost or budget figures / blocked by verification | 0 / 0 | 0 / 0 | 152 / 152 | 35 / 35 |
| Right figures blocked by verification | 0 | 0 | 0 | 0 |
| Stale answers served (right when given, wrong now, not reopened or flagged) | 0 | 0 | 0 | 0 |
| Stale published findings | 0 | 0 | 0 | 347 |
| Affected projects / missed | 119 / 0 | 119 / 0 | 117 / 0 | 115 / 115 |
| Routed but not affected | 54 | 0 | 0 | 0 |
| Affected projects whose task held no answer | 0 | 0 | 2 | 4 |
| Duplicate actions (versions / reopenings / transitions / suggestions) | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Tasks completed / total (re-runs) | 36 / 36 (173) | 36 / 36 (119) | 35 / 36 (117) | 35 / 36 (0) |
| Event processing p50 / worst p95 (ms) | 289.8 / 627.9 | 257.5 / 947.1 | 281.4 / 608.0 | 215.4 / 538.6 |
| Context build p50 / worst p95 (ms) | 2747.9 / 6530.1 | 3692.3 / 9384.9 | 3653.9 / 10355.1 | 3151.5 / 6994.6 |
| Verification and publication p50 (ms) | 155.0 | 152.2 | 111.5 | 119.6 |
| Change to refreshed answers p50 / worst p95 (ms) | 9889.1 / 26851.9 | 5050.1 / 27406.4 | 7887.9 / 33225.8 | 215.4 / 538.6 |
| Delay question p50 (ms) | 2129.5 | 2069.8 | 2170.1 | 2401.7 |
| Context tokens (total) | 10,742,259 | 8,489,297 | 8,738,139 | 2,150,522 |
| Model calls / tokens in / tokens out | 0 / 0 / 0 | 0 / 0 / 0 | 158 / 110,687 / 34,132 | 39 / 26,383 / 7,945 |
| Model replies not in the requested JSON form / invented record ids / failed calls | 0 / 0 / 0 | 0 / 0 / 0 | 6 / 0 / 0 | 4 / 0 / 0 |
| Model call p50 / worst p95 (ms) | – | – | 1705.9 / 2359.9 | 1670.5 / 2141.2 |
| Model cost (USD) | 0.0 | 0.0 | 0.0 | 0.0 |

`loop*` use the deterministic analyst (no model); `llm-*` use the model. `llm-no-routing` applies the same changes
with event routing off. "Served" answers are the answers the completed tasks hold, whether or not the publication
gate let them into shared memory.

Pre-registered criteria (`docs/LOOP_PREREGISTRATION.md`, study 2): **all met.**

| Arm | Criterion | Met | Value |
|---|---|---|---|
| loop | 1. no stale answers or stale published findings | yes | 0 / 0 |
| loop | 2. no missed dependencies | yes | 0 of 119 |
| loop | 3. no duplicate actions | yes | 0 / 0 / 0 / 0 |
| loop | 4. every needed record in the context, every scan complete | yes | 1.0, incomplete scans 0 |
| loop | 5. findings verified >= 0.99, published answers all correct | yes | 1.0, 1.0 |
| loop | 6. every task completed | yes | 36 of 36, failed 0, waiting 0 |
| loop-relied | 1. no stale answers or stale published findings | yes | 0 / 0 |
| loop-relied | 2. no missed dependencies | yes | 0 of 119 |
| loop-relied | 3. no duplicate actions | yes | 0 / 0 / 0 / 0 |
| loop-relied | 4. every needed record in the context, every scan complete | yes | 1.0, incomplete scans 0 |
| loop-relied | 5. findings verified >= 0.99, published answers all correct | yes | 1.0, 1.0 |
| loop-relied | 6. every task completed | yes | 36 of 36, failed 0, waiting 0 |
| loop-relied | 7. no re-runs of unaffected projects | yes | 0 |
| llm-relied | 1. no stale answers or stale published findings | yes | 0 / 0 |
| llm-relied | 2. no missed dependencies | yes | 0 of 117 |
| llm-relied | 3. no duplicate actions | yes | 0 / 0 / 0 / 0 |
| llm-relied | 4. every needed record in the context, every scan complete | yes | 1.0, incomplete scans 0 |

| World | Arm | Right when given | Served answers correct | Stale served | Missed | Re-runs | Context tokens | Model calls |
|---|---|---|---|---|---|---|---|---|
| 304 | loop | 1.0 | 1.0 | 0 | 0 / 49 | 71 | 3,231,985 | – |
| 305 | loop | 1.0 | 1.0 | 0 | 0 / 32 | 57 | 3,856,549 | – |
| 306 | loop | 1.0 | 1.0 | 0 | 0 / 38 | 45 | 3,653,725 | – |
| 304 | loop-relied | 1.0 | 1.0 | 0 | 0 / 49 | 49 | 2,595,213 | – |
| 305 | loop-relied | 1.0 | 1.0 | 0 | 0 / 32 | 32 | 2,485,642 | – |
| 306 | loop-relied | 1.0 | 1.0 | 0 | 0 / 38 | 38 | 3,408,442 | – |
| 304 | llm-relied | 0.0 | 0.0 | 0 | 0 / 47 | 47 | 2,855,964 | 62 |
| 305 | llm-relied | 0.0 | 0.0 | 0 | 0 / 32 | 32 | 2,636,299 | 45 |
| 306 | llm-relied | 0.0 | 0.0 | 0 | 0 / 38 | 38 | 3,245,876 | 51 |
| 304 | llm-no-routing | 0.0 | 0.0 | 0 | 49 / 49 | 0 | 583,091 | 12 |
| 305 | llm-no-routing | 0.0 | 0.0 | 0 | 28 / 28 | 0 | 810,788 | 15 |
| 306 | llm-no-routing | 0.0 | 0.0 | 0 | 38 / 38 | 0 | 756,643 | 12 |

The last reply of each model arm that was not in the requested JSON form (abridged as printed by the run):

- `llm-relied`, 215 tokens: `{"milestones": [{"id": "M1", "at_risk": true, "reason": "Insufficient stock and open orders for P1"}, {"id": "M2", "at_risk": true, …}, …` … `123 * 46 + 123 * 15 + 310 * 60, "budget": 28701.0, "within_budget": true, "feasible": false}`
- `llm-no-routing`, 186 tokens: `{"milestones": [{"id": "M1", "at_risk": true, …}, {"id": "M2", "at_risk": false, …}` … `": 138 * 31 + 371 * 58 + 27 * 56, "budget": 35500.0, "within_budget": true, "feasible": true}`

The model wrote the arithmetic instead of its result where a number was asked for.
