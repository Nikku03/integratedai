### Topological memory bank vs standard (largest loaded tenant)

Retrieval arms (admin over the whole company, from `bench_scale` row `1000000 (re-measured)`):

| arm | warm p50 ms | warm p95 ms | hit@20 | MRR | topology p50 (nodes / max dim / cavities) |
|---|---|---|---|---|---|
| hybrid+graph(bounded) | 267.0 | 552.2 | 0.98 | 0.893 | - |
| hybrid+cliques(topological) | 254.0 | 534.0 | 0.98 | 0.893 | 80 / 2 / 0 |
| hybrid+cliques+bonus | 248.8 | 550.1 | 0.98 | 0.893 | 81 / 2 / 0 |

Plasticity (STDP-like): 40 documents, 120 learning questions, 120 unseen questions about the same documents; links potentiated/depressed from what the packets used; weights restored afterwards.

| arm | set | hit@20 before → after | MRR before → after | p50 ms before → after | graph stage p50 ms before → after | links +/− |
|---|---|---|---|---|---|---|
| rem | same questions | 1.0 → 1.0 | 1.0 → 1.0 | 251.6 → 249.0 | 8.1 → 8.0 | 92 / 761 |
| rem | unseen questions, same documents | 1.0 → 1.0 | 0.79 → 0.79 | 270.8 → 271.9 | 8.5 → 8.3 | 92 / 761 |
| cliques | same questions | 1.0 → 1.0 | 1.0 → 1.0 | 248.7 → 246.5 | 9.4 → 9.6 | 89 / 610 |
| cliques | unseen questions, same documents | 1.0 → 1.0 | 0.79 → 0.79 | 256.6 → 273.0 | 10.4 → 10.8 | 89 / 610 |

Learned reranker on retrieval traces: 240 questions, 34,975 candidate rows (618 positives), 28 features; split by document (21,058 training rows, 13,917 test rows over 98 unseen-document queries).

| model | parameters | learning rule | train s | AUC (test) | hit@1 | hit@5 | MRR |
|---|---|---|---|---|---|---|---|
| heuristic reranker (hand-written) | 0 | none | 0.0 | 0.806 | 0.827 | 1.0 | 0.895 |
| clique network / backprop | 2,513 | backprop (Adam, weighted BCE) | 3.41 | 0.995 | 0.827 | 1.0 | 0.898 |
| clique network / Hebbian (local) | 2,513 | reward-modulated Hebbian (local, three-factor) | 3.17 | 0.959 | 0.827 | 1.0 | 0.895 |
| deep MLP (4x64) / backprop | 14,401 | backprop (Adam, weighted BCE) | 3.24 | 0.999 | 1.0 | 1.0 | 1.0 |