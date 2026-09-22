### Retrieval benchmark (15 documents, 18 questions, embeddings=fastembed, ocr=tesseract, ingest 14.4s)

| arm | recall@20 | exact-field acc | citation correctness | status acc | insufficient-evidence det. | conflict det. | permission leaks | p50 ms | p95 ms | packet tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| vector-only | 0.9667 | 1.0 (n=14) | 1.0 (n=51) | 1.0 | 1.0 | 1.0 | 0 | 65.12 | 93.62 | 4169.3 |
| bm25-only | 0.9333 | 0.7143 (n=14) | 1.0 (n=53) | 0.9444 | 1.0 | 0.0 | 0 | 59.04 | 65.37 | 2155.4 |
| hybrid | 0.9667 | 1.0 (n=14) | 1.0 (n=50) | 1.0 | 1.0 | 1.0 | 0 | 80.64 | 106.61 | 4192 |
| hybrid+graph(unbounded) | 0.9667 | 1.0 (n=14) | 1.0 (n=50) | 1.0 | 1.0 | 1.0 | 0 | 89.26 | 165.74 | 4192 |
| hybrid+graph(bounded, REM) | 0.9667 | 1.0 (n=14) | 1.0 (n=50) | 1.0 | 1.0 | 1.0 | 0 | 79.52 | 119.2 | 4192 |

Full-context prompting (what a model would need to hold per question, by principal):

- admin: ~4,546 tokens/question, est. $0.0181/question at claude-sonnet-5 prices
- analyst: ~4,286 tokens/question, est. $0.0174/question at claude-sonnet-5 prices
- finance_reader: ~141 tokens/question, est. $0.0049/question at claude-sonnet-5 prices
- no LLM provider configured in this build; token load and cost are reported, answer quality is not

Warm metadata lookup: p50 0.41 ms, p95 0.73 ms.

Storage: raw 12,756,178 bytes in 15 blobs; counts {'documents': 15, 'pages': 72, 'sections': 73, 'records': 289}.