### Scale benchmark: memory bank and retrieval (embeddings=fastembed, pgvector 0.8.1, shared_buffers 2GB)

| records | sections | load s | tsvector s | HNSW build s (records) | all indexes s | records table+idx | HNSW idx | GIN tsv idx |
|---|---|---|---|---|---|---|---|---|
| 10000 | 2,500 | 64.2 | 1.4 | 2.2 | 3.5 | 0.06 GB | 12 MB (halfvec) | 0 MB |
| 100000 | 25,000 | 83.8 | 15.5 | 21.8 | 31.2 | 0.60 GB | 117 MB (halfvec) | 4 MB |
| 1000000 | 250,000 | 296.5 | 141.8 | 301.8 | 391.6 | 5.85 GB | 1170 MB (halfvec) | 28 MB |

| records | principal | arm | cold p50 | cold p95 | warm p50 | warm p95 | warm max | hit@20 | MRR | timeouts | topology (p50: nodes / max dim / cavities) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10000 | admin@company | hybrid+graph(bounded) | 214.2 | 311.2 | 213.3 | 296.6 | 371.1 | 1.0 | - | 0 | - |
| 10000 | admin@company | hybrid(no graph) | 199.3 | 292.8 | 200.6 | 276.4 | 333.2 | 1.0 | - | 0 | - |
| 10000 | admin@company | vector-only | 112.7 | 150.6 | 98.7 | 163.9 | 237.2 | 0.88 | - | 0 | - |
| 10000 | admin@company | lexical-only | 128.3 | 180.0 | 128.6 | 198.6 | 246.0 | 1.0 | - | 0 | - |
| 10000 | analyst@department(20%) | hybrid+graph(bounded) | 171.9 | 262.2 | 175.2 | 264.8 | 299.6 | 1.0 | - | 0 | - |
| 10000 | analyst@department(20%) | vector-only | 102.7 | 165.5 | 99.8 | 179.3 | 210.7 | 0.9 | - | 0 | - |
| 100000 | admin@company | hybrid+graph(bounded) | 283.4 | 397.4 | 280.3 | 400.3 | 474.5 | 1.0 | - | 0 | - |
| 100000 | admin@company | hybrid(no graph) | 271.9 | 382.4 | 270.2 | 392.3 | 432.5 | 1.0 | - | 0 | - |
| 100000 | admin@company | vector-only | 108.2 | 197.8 | 104.8 | 178.7 | 244.4 | 0.86 | - | 0 | - |
| 100000 | admin@company | lexical-only | 183.9 | 275.3 | 177.0 | 251.4 | 347.9 | 1.0 | - | 0 | - |
| 100000 | analyst@department(20%) | hybrid+graph(bounded) | 294.6 | 387.4 | 271.6 | 376.9 | 545.9 | 1.0 | - | 0 | - |
| 100000 | analyst@department(20%) | vector-only | 143.1 | 225.8 | 148.9 | 243.1 | 273.2 | 0.812 | - | 0 | - |
| 1000000 | admin@company | hybrid+graph(bounded) | 300.5 | 710.4 | 265.2 | 586.4 | 697.9 | 0.98 | - | 0 | - |
| 1000000 | admin@company | hybrid(no graph) | 257.2 | 552.2 | 255.4 | 526.6 | 586.9 | 0.98 | - | 0 | - |
| 1000000 | admin@company | vector-only | 128.2 | 233.1 | 128.8 | 221.9 | 322.6 | 0.94 | - | 0 | - |
| 1000000 | admin@company | lexical-only | 127.1 | 289.8 | 124.4 | 279.5 | 326.7 | 0.98 | - | 0 | - |
| 1000000 | analyst@department(20%) | hybrid+graph(bounded) | 654.8 | 771.5 | 672.7 | 836.5 | 914.6 | 1.0 | - | 0 | - |
| 1000000 | analyst@department(20%) | vector-only | 148.6 | 246.9 | 146.0 | 243.7 | 320.2 | 0.8 | - | 0 | - |
| 1000000 (re-measured) | admin@company | hybrid+graph(bounded) | 275.6 | 539.9 | 267.0 | 552.2 | 649.2 | 0.98 | 0.893 | 0 | - |
| 1000000 (re-measured) | admin@company | hybrid(no graph) | 262.1 | 537.6 | 250.0 | 535.3 | 642.3 | 0.98 | 0.893 | 0 | - |
| 1000000 (re-measured) | admin@company | vector-only | 132.1 | 207.0 | 127.8 | 220.6 | 444.0 | 0.94 | 0.823 | 0 | - |
| 1000000 (re-measured) | admin@company | lexical-only | 120.8 | 235.3 | 123.1 | 224.7 | 493.4 | 0.98 | 0.9 | 0 | - |
| 1000000 (re-measured) | admin@company | hybrid+cliques(topological) | 254.1 | 541.4 | 254.0 | 534.0 | 709.5 | 0.98 | 0.893 | 0 | 80 / 2 / 0 |
| 1000000 (re-measured) | admin@company | hybrid+cliques+bonus | 255.7 | 547.1 | 248.8 | 550.1 | 748.3 | 0.98 | 0.893 | 0 | 81 / 2 / 0 |
| 1000000 (re-measured) | analyst@department(20%) | hybrid+graph(bounded) | 578.7 | 770.2 | 564.0 | 787.3 | 1016.6 | 1.0 | 0.767 | 0 | - |
| 1000000 (re-measured) | analyst@department(20%) | vector-only | 148.8 | 198.1 | 143.0 | 184.3 | 378.5 | 0.8 | 0.624 | 0 | - |

| records | stage (admin, hybrid, cold p50 ms) |
|---|---|
| 10000 | exact_ms=5.0, lexical_ms=45.9, embed_ms=7.2, vector_ms=19.7, named_docs_ms=19.4, graph_ms=8.4, materialise_ms=33.2, rerank_ms=30.1, contradictions_ms=5.3, packet_ms=14.7; metadata lookup p95 1.5 ms |
| 100000 | exact_ms=11.7, lexical_ms=87.0, embed_ms=11.3, vector_ms=22.1, named_docs_ms=23.4, graph_ms=8.5, materialise_ms=32.5, rerank_ms=31.6, contradictions_ms=9.0, packet_ms=14.5; metadata lookup p95 1.9 ms |
| 1000000 | exact_ms=13.6, lexical_ms=45.4, embed_ms=14.0, vector_ms=46.1, named_docs_ms=30.4, graph_ms=10.7, materialise_ms=32.1, rerank_ms=29.3, contradictions_ms=17.9, packet_ms=14.1; metadata lookup p95 1.8 ms |
| 1000000 (re-measured) | exact_ms=15.1, lexical_ms=46.2, embed_ms=15.2, vector_ms=41.5, named_docs_ms=29.6, graph_ms=8.5, materialise_ms=27.7, rerank_ms=29.8, contradictions_ms=9.4, packet_ms=13.9; metadata lookup p95 1.2 ms |

| records | resolve name p50 / p95 ms | resolved to the right supplier | entity profile p50 / p95 ms | profile records (p50) | company digest ms (records) | department digest ms (records) |
|---|---|---|---|---|---|---|
| 10000 | 9.2 / 14.0 | 0.94 | 16.4 / 22.6 | 11 | 55.6 (10,000) | 24.9 (2,004) |
| 100000 | 35.4 / 72.8 | 0.9 | 50.4 / 55.2 | 11 | 182.4 (100,000) | 108.3 (20,004) |
| 1000000 | 447.2 / 1383.5 | 0.88 | 588.8 / 622.8 | 11 | 1852.6 (1,000,000) | 1211.7 (200,004) |
| 1000000 (re-measured) | 10.6 / 19.3 | 1.0 | 6.2 / 7.7 | 11 | 2249.8 (1,000,000) | 866.2 (200,004) |