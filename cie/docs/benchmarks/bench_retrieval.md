### Retrieval benchmark (15 documents, 18 questions, embeddings=fastembed, ocr=tesseract, ingest 15.9s)

| arm | recall@20 | exact-field acc | citation correctness | status acc | insufficient-evidence det. | conflict det. | permission leaks | p50 ms | p95 ms | packet tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| vector-only | 0.9667 | 1.0 (n=14) | 1.0 (n=50) | 1.0 | 1.0 | 1.0 | 0 | 76.99 | 124.47 | 4247.6 |
| bm25-only | 0.9 | 0.7143 (n=14) | 1.0 (n=51) | 0.9444 | 1.0 | 0.0 | 0 | 67.23 | 82.5 | 2155.3 |
| hybrid | 0.9667 | 1.0 (n=14) | 1.0 (n=51) | 1.0 | 1.0 | 1.0 | 0 | 106.54 | 150.51 | 4242.1 |
| hybrid+graph(unbounded) | 0.9667 | 1.0 (n=14) | 1.0 (n=51) | 1.0 | 1.0 | 1.0 | 0 | 108.43 | 149.54 | 4243.8 |
| hybrid+graph(bounded, REM) | 0.9667 | 1.0 (n=14) | 1.0 (n=51) | 1.0 | 1.0 | 1.0 | 0 | 110.82 | 159.42 | 4242.1 |
| hybrid+cliques(topological) | 0.9667 | 1.0 (n=14) | 1.0 (n=51) | 1.0 | 1.0 | 1.0 | 0 | 122.06 | 223.73 | 4242.1 |
| hybrid+cliques+bonus | 0.9667 | 1.0 (n=14) | 1.0 (n=51) | 1.0 | 1.0 | 1.0 | 0 | 122.74 | 157.81 | 4226.8 |

Full-context prompting (what a model would need to hold per question, by principal):

- admin: ~4,546 tokens/question, est. $0.0121/question at claude-sonnet-5 prices
- analyst: ~4,286 tokens/question, est. $0.0116/question at claude-sonnet-5 prices
- finance_reader: ~141 tokens/question, est. $0.0033/question at claude-sonnet-5 prices
- no LLM provider configured in this build; token load and cost are reported, answer quality is not

Warm metadata lookup: p50 0.46 ms, p95 0.75 ms.

Storage: raw 12,756,178 bytes in 15 blobs; counts {'documents': 15, 'pages': 72, 'sections': 73, 'records': 289}.