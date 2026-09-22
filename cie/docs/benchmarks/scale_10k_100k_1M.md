### Scale benchmark: memory bank and retrieval (embeddings=fastembed, pgvector 0.6.0, shared_buffers 2GB)

| records | sections | load s | tsvector s | HNSW build s (records) | all indexes s | records table+idx | HNSW idx | GIN tsv idx |
|---|---|---|---|---|---|---|---|---|
| 10000 | 2,500 | 132.8 | 1.3 | 4.9 | 8.2 | 0.20 GB | 52 MB | 1 MB |
| 100000 | 25,000 | 61.2 | 13.7 | 15.7 | 25.5 | 0.80 GB | 242 MB | 4 MB |
| 1000000 | 250,000 | 229.6 | 144.7 | 132.3 | 191.2 | 6.71 GB | 2085 MB | 25 MB |

| records | principal | arm | cold p50 | cold p95 | warm p50 | warm p95 | warm max | hit@20 | timeouts |
|---|---|---|---|---|---|---|---|---|---|
| 10000 | admin@company | hybrid+graph(bounded) | 346.9 | 410.6 | 337.3 | 419.7 | 442.9 | 0.88 | 0 |
| 10000 | admin@company | hybrid(no graph) | 338.4 | 405.8 | 333.4 | 403.8 | 424.4 | 0.88 | 0 |
| 10000 | admin@company | vector-only | 152.1 | 197.6 | 149.0 | 201.8 | 212.1 | 0.88 | 0 |
| 10000 | admin@company | lexical-only | 223.7 | 293.1 | 221.7 | 275.7 | 307.1 | 1.0 | 0 |
| 10000 | analyst@department(20%) | hybrid+graph(bounded) | 160.0 | 217.1 | 159.3 | 233.6 | 316.1 | 1.0 | 0 |
| 10000 | analyst@department(20%) | vector-only | 94.8 | 139.4 | 87.8 | 143.3 | 157.4 | 0.9 | 0 |
| 100000 | admin@company | hybrid+graph(bounded) | 565.7 | 981.7 | 595.6 | 1011.1 | 1102.8 | 0.84 | 0 |
| 100000 | admin@company | hybrid(no graph) | 591.8 | 1046.3 | 676.7 | 1306.1 | 1448.2 | 0.84 | 0 |
| 100000 | admin@company | vector-only | 173.7 | 275.9 | 158.1 | 263.9 | 281.2 | 0.8 | 0 |
| 100000 | admin@company | lexical-only | 456.8 | 1052.2 | 506.2 | 994.4 | 1499.1 | 0.86 | 0 |
| 100000 | analyst@department(20%) | hybrid+graph(bounded) | 654.3 | 1238.3 | 595.5 | 742.9 | 834.2 | 0.75 | 0 |
| 100000 | analyst@department(20%) | vector-only | 255.7 | 320.3 | 247.3 | 328.0 | 363.5 | 0.75 | 0 |
| 1000000 | admin@company | hybrid+graph(bounded) | 2164.5 | 6344.6 | 2173.6 | 6175.6 | 6437.5 | 0.22 | 0 |
| 1000000 | admin@company | hybrid(no graph) | 1739.2 | 5740.7 | 1789.8 | 5749.9 | 6216.5 | 0.22 | 0 |
| 1000000 | admin@company | vector-only | 266.2 | 411.0 | 261.0 | 401.3 | 468.7 | 0.14 | 0 |
| 1000000 | admin@company | lexical-only | 1267.6 | 5261.0 | 1251.2 | 5255.8 | 5551.2 | 0.26 | 0 |
| 1000000 | analyst@department(20%) | hybrid+graph(bounded) | 3025.9 | 4092.0 | 3192.0 | 4691.6 | 5942.7 | 0.2 | 0 |
| 1000000 | analyst@department(20%) | vector-only | 192.1 | 305.6 | 191.9 | 315.2 | 366.5 | 0.0 | 0 |
| 1000000 (after fixes) | admin@company | hybrid+graph(bounded) | 370.2 | 909.8 | 241.8 | 581.7 | 845.9 | 0.98 | 0 |
| 1000000 (after fixes) | admin@company | hybrid(no graph) | 245.9 | 557.4 | 231.9 | 549.3 | 791.8 | 0.98 | 0 |
| 1000000 (after fixes) | admin@company | vector-only | 122.7 | 187.6 | 119.8 | 202.8 | 465.6 | 0.94 | 0 |
| 1000000 (after fixes) | admin@company | lexical-only | 127.6 | 182.4 | 121.0 | 183.2 | 286.6 | 0.98 | 0 |
| 1000000 (after fixes) | analyst@department(20%) | hybrid+graph(bounded) | 606.3 | 1070.8 | 579.4 | 782.0 | 1147.5 | 1.0 | 0 |
| 1000000 (after fixes) | analyst@department(20%) | vector-only | 104.2 | 159.9 | 108.7 | 149.9 | 377.1 | 0.8 | 0 |

| records | stage (admin, hybrid, cold p50 ms) |
|---|---|
| 10000 | exact_ms=10.2, lexical_ms=106.5, embed_ms=10.0, vector_ms=49.6, named_docs_ms=20.7, graph_ms=15.9, materialise_ms=52.3, rerank_ms=44.3, contradictions_ms=7.1, packet_ms=12.2; metadata lookup p95 1.5 ms |
| 100000 | exact_ms=46.5, lexical_ms=266.8, embed_ms=12.8, vector_ms=15.6, named_docs_ms=20.6, graph_ms=45.2, materialise_ms=46.5, rerank_ms=39.9, contradictions_ms=7.1, packet_ms=12.3; metadata lookup p95 1.8 ms |
| 1000000 | exact_ms=392.1, lexical_ms=993.5, embed_ms=16.8, vector_ms=26.7, named_docs_ms=33.9, graph_ms=393.5, materialise_ms=59.8, rerank_ms=46.6, contradictions_ms=13.0, packet_ms=13.1; metadata lookup p95 3.6 ms |
| 1000000 (after fixes) | exact_ms=36.2, lexical_ms=36.5, embed_ms=14.4, vector_ms=25.2, named_docs_ms=89.0, graph_ms=9.5, materialise_ms=18.9, rerank_ms=24.0, contradictions_ms=6.1, packet_ms=16.3; metadata lookup p95 1.2 ms |