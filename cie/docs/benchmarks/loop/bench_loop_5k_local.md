# One-project loop benchmark (3 worlds, 20 changes each)

Host tenant: erbfull-5000-9688c2. FICTIONAL, GENERATED project data; expected answers from the generator's world model.

| Measure | loop-relied | no-routing |
|---|---|---|
| Needed records in the task context | 1.0 | 1.0 |
| Needed records the answer relied on (its inputs) | 1.0 | 1.0 |
| Delay-question evidence found (traversal + search) | 0.994 | 0.9628 |
| … of which passages found by search over the whole memory | 0.9665 | 0.8977 |
| Exhaustive scans incomplete | 0 | 0 |
| Findings passing verification | 1.0 | 1.0 |
| Published answers matching the oracle | 1.0 | 1.0 |
| Served answers matching the oracle (after each change) | 1.0 | 0.4577 |
| Answers right when given | 1.0 | 1.0 |
| … delivery verdict / budget verdict / cost / milestones at risk right | 1.0 / 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 / 1.0 |
| Wrong answers served because the analyst erred | 0 | 0 |
| Runs without a usable answer | 0 | 0 |
| Wrong cost or budget figures / blocked by verification | 0 / 0 | 0 / 0 |
| Right figures blocked by verification | 0 | 0 |
| Stale answers served (right when given, wrong now, not reopened or flagged) | 0 | 410 |
| Stale published findings | 0 | 492 |
| Affected projects / missed | 119 / 0 | 119 / 119 |
| Routed but not affected | 0 | 0 |
| Affected projects whose task held no answer | 0 | 0 |
| Duplicate actions (versions / reopenings / transitions / suggestions) | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Tasks completed / total (re-runs) | 36 / 36 (119) | 36 / 36 (0) |
| Event processing p50 / worst p95 (ms) | 176.5 / 465.1 | 153.5 / 359.7 |
| Context build p50 / worst p95 (ms) | 1591.9667 / 3737.9 | 1740.3667 / 3442.9 |
| Verification and publication p50 (ms) | 222.5333 | 178.1667 |
| Change to refreshed answers p50 / worst p95 (ms) | 3701.6 / 13133.6 | 153.5 / 359.7 |
| Delay question p50 (ms) | 1117.9 | 1160.5333 |
| Context tokens (total) | 6521510 | 1489767 |
| Model calls / tokens in / tokens out | 0 / 0 / 0 | 0 / 0 / 0 |
| Model replies not in the requested JSON form / invented record ids / failed calls | 0 / 0 / 0 | 0 / 0 / 0 |
| Model call p50 / worst p95 (ms) | None / 0 | None / 0 |
| Model cost (USD) | 0.0 | 0.0 |

Model: none. `loop*` and `no-routing` use the deterministic analyst (no model); `llm-*` arms use the model. Arms ending in `no-routing` apply the same changes with event routing off.

## Pre-registered criteria (docs/LOOP_PREREGISTRATION.md)

**All criteria met.**

| Arm | Criterion | Met | Value |
|---|---|---|---|
| loop-relied | 1. no stale answers or stale published findings | yes | 0 / 0 |
| loop-relied | 2. no missed dependencies | yes | 0 of 119 |
| loop-relied | 3. no duplicate actions | yes | 0 / 0 / 0 / 0 |
| loop-relied | 4. every needed record in the context, every scan complete | yes | 1.0, incomplete scans 0 |
| loop-relied | 5. findings verified >= 0.99, published answers all correct | yes | 1.0, 1.0 |
| loop-relied | 6. every task completed | yes | 36 of 36, failed 0, waiting 0 |
| loop-relied | 7. no re-runs of unaffected projects | yes | 0 |
