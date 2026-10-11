### The company brain test

215 questions (multi 36, not_found 20, prose 50, single 109) on /tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain/test5k.

| arm | single | multi | prose | not_found | mean of families | left out | not answered |
|---|---|---|---|---|---|---|---|
| quotes | 0.086 | 0.000 | 0.707 | 0.000 | **0.198** | 0 | 0 |
| v1 | 0.794 | 0.028 | 0.000 | 0.250 | **0.268** | 0 | 0 |
| v2 | 0.617 | 0.111 | 0.000 | 0.250 | **0.244** | 0 | 0 |
| v13 | 0.275 | 0.889 | 0.000 | 0.000 | **0.291** | 0 | 0 |
| v15 | 0.821 | 0.972 | 0.583 | 1.000 | **0.844** | 0 | 0 |
| v15_seed1 | 0.821 | 0.972 | 0.583 | 1.000 | **0.844** | 0 | 0 |

| arm | combine | compare | deadlines | descriptive | fields | link | lists | names | not_found | prose |
|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 0.000 | 0.067 | 0.103 | 0.100 | 0.000 | 0.000 | 0.137 | 0.000 | 0.707 |
| v1 | 0.000 | 0.000 | 0.933 | 0.795 | 0.800 | 0.067 | 0.800 | 0.553 | 0.250 | 0.000 |
| v2 | 0.067 | 0.000 | 0.800 | 0.590 | 0.633 | 0.200 | 0.800 | 0.122 | 0.250 | 0.000 |
| v13 | 1.000 | 1.000 | 0.467 | 0.179 | 0.300 | 0.733 | 0.467 | 0.000 | 0.000 | 0.000 |
| v15 | 1.000 | 1.000 | 1.000 | 0.744 | 0.933 | 0.933 | 0.800 | 0.553 | 1.000 | 0.583 |
| v15_seed1 | 1.000 | 1.000 | 1.000 | 0.744 | 0.933 | 0.933 | 0.800 | 0.553 | 1.000 | 0.583 |

False "not found" on answerable questions, prose facts in the evidence, time per question (ms), and the answers' length (characters):

| arm | false not found | prose 2,000 | prose 6,000 | prose 24,000 | median ms | p90 ms | max ms | median chars |
|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 0.880 | 0.980 | 1.000 | 24.0 | 45.9 | 90.3 | 1059 |
| v1 | 0.092 | 0.030 | 0.070 | 0.110 | 719.0 | 1115.0 | 1438.2 | 10 |
| v2 | 0.046 | 0.060 | 0.140 | 0.190 | 1713.6 | 2094.9 | 2459.4 | 10 |
| v13 | 0.000 | 0.060 | 0.140 | 0.180 | 4192.7 | 6023.6 | 11732.4 | 10 |
| v15 | 0.000 | 0.597 | 0.860 | 1.000 | 4556.6 | 5602.5 | 10103.5 | 11 |
| v15_seed1 | 0.000 | 0.597 | 0.860 | 1.000 | 4494.0 | 5568.7 | 10240.2 | 11 |

Routes of quotes (right route: single and multi fact, prose prose, not found not_found):

| family | routes | right route |
|---|---|---|
| single | {"prose": 109} | 0.000 |
| multi | {"prose": 36} | 0.000 |
| prose | {"prose": 50} | 1.000 |
| not_found | {"prose": 20} | 0.000 |
| mean over families | | **0.250** |

Routes of v15 (right route: single and multi fact, prose prose, not found not_found):

| family | routes | right route |
|---|---|---|
| single | {"fact": 53, "plan": 55, "prose": 1} | 0.991 |
| multi | {"plan": 36} | 1.000 |
| prose | {"prose": 50} | 1.000 |
| not_found | {"not_found": 20} | 1.000 |
| mean over families | | **0.998** |

Routes of v15_seed1 (right route: single and multi fact, prose prose, not found not_found):

| family | routes | right route |
|---|---|---|
| single | {"fact": 53, "plan": 55, "prose": 1} | 0.991 |
| multi | {"plan": 36} | 1.000 |
| prose | {"prose": 50} | 1.000 |
| not_found | {"not_found": 20} | 1.000 |
| mean over families | | **0.998** |

Big folder minus the small one (/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain/test5ksmall; not reproduced there, left out: 3):

| arm | questions | single | multi | prose | not_found | mean of families | changed |
|---|---|---|---|---|---|---|---|
| quotes | 212 | -0.019 | -0.056 | -0.036 | 0.000 | -0.028 | 21 |
| v1 | 212 | 0.000 | -0.055 | 0.000 | 0.000 | -0.013 | 6 |
| v2 | 212 | -0.009 | 0.000 | 0.000 | 0.000 | -0.002 | 11 |
| v13 | 212 | -0.019 | 0.000 | 0.000 | 0.000 | -0.005 | 4 |
| v15 | 212 | -0.029 | 0.000 | -0.034 | 0.150 | 0.022 | 16 |

Rules:
- 1 single-document questions: v15 >= v1 - 0.03: **met**
- 2 multi-document questions: v15 >= v13 - 0.03: **met**
- 3 free text: v15 >= plain search with quotes - 0.05: **not met**
- 4 not found: v15 >= 0.80 on questions about nothing in the bank, and false 'not found' <= 0.03 on the others: **met**
- 5 one brain for every kind: v15's mean over families >= every other arm's + 0.20: **met**
- 6 it holds at size: v15 at 5,000 documents >= the small set - 0.05 (mean over single, multi and free text): **met**
- 7 the right route: v15's route accuracy, mean over families, >= 0.90: **met**

- paired differences behind rules 1 to 3 (mean, 95% bootstrap interval): {"single: v15 - v1": {"questions": 109, "mean": 0.028, "interval_95": [-0.018, 0.073]}, "multi: v15 - v13": {"questions": 36, "mean": 0.083, "interval_95": [0.0, 0.194]}, "prose: v15 - quotes": {"questions": 50, "mean": -0.123, "interval_95": [-0.243, -0.003]}}
- hash-seed check (v15 under hash seed 1): {"questions": 215, "different": []}
- arms: {"quotes": {"arm": "quotes", "file": "quotes.jsonl", "single": null, "plans": null, "router": null, "seconds": 11.64, "answers": 215}, "v1": {"arm": "v1", "file": "factbank.jsonl", "single": null, "plans": null, "router": null, "seconds": 176.84, "answers": 215}, "v2": {"arm": "v2", "file": "factbank_v2.jsonl", "single": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/fb50/lessons.json", "plans": null, "router": null, "seconds": 384.73, "answers": 215}, "v13": {"arm": "v13", "file": "factbank_v13.jsonl", "single": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/fb50/lessons.json", "plans": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/mdtrain/plan_lessons_v13.json", "router": null, "seconds": 974.99, "answers": 215}, "v15": {"arm": "v15", "file": "factbank_v15.jsonl", "single": "docs/benchmarks/brain/lessons/single_lessons.json", "plans": "docs/benchmarks/brain/lessons/plan_lessons.json", "router": "docs/benchmarks/brain/lessons/router.json", "seconds": 921.81, "answers": 215}, "v15_seed1": {"arm": "v15", "file": "v15_seed1.jsonl", "single": "docs/benchmarks/brain/lessons/single_lessons.json", "plans": "docs/benchmarks/brain/lessons/plan_lessons.json", "router": "docs/benchmarks/brain/lessons/router.json", "seconds": 914.35, "answers": 215}}
- left out as stale: {}
- builds: {"factbank": {"sources": 5000, "entities": 14261, "facts": 97324, "bytes": 95019008, "check": {"ok": true, "errors": [], "facts": 97324, "stale": 97307, "contradictions": 0, "contradiction_examples": []}, "seconds": 7.55}, "factbank_v2": {"sources": 5000, "entities": 14261, "facts": 115455, "bytes": 102834176, "check": {"ok": true, "errors": [], "facts": 115455, "stale": 115429, "contradictions": 0, "contradiction_examples": []}, "seconds": 14.96}}
- draw: {"seed": 810, "mix": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50}, "mix_given": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50, "descriptive": 39}, "set_aside_written": {"action_owner_issues": 8, "person_count": 5, "ticket_link": 3}, "gold_documents": 259}
