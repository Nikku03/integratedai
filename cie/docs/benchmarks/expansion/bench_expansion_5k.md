### EnterpriseRAG-Bench through CIE (haystack 5,000 of 511,958 documents, 500 questions, embeddings=fastembed)

| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid+graph(REM) [BM25+expansion] | 0.872 | 0.81 | 0.756 | 0.677 | 0.902 | 0.83 | 8.487 | 0.05 | 0.021 | 400.8 / 860.7 |
| hybrid+graph(REM) [BM25] | 0.878 | 0.817 | 0.761 | 0.677 | 0.911 | 0.834 | 8.56 | 0 | 0.013 | 419.1 / 878.8 |

Keyword engine that served each keyword search: hybrid+graph(REM) [BM25+expansion]: bm25 1,000; hybrid+graph(REM) [BM25]: bm25 1,000.

By category (hybrid+graph(REM) [BM25+expansion]):

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.96 | 0.835 | 0.76 | 0.96 | 0.96 | 8.857 | 0.017 | 353.6 |
| semantic | 125 | 0.728 | 0.475 | 0.368 | 0.728 | 0.728 | 9.024 | 0.024 | 389.1 |
| intra_document_reasoning | 40 | 0.975 | 0.857 | 0.775 | 0.975 | 0.975 | 8.775 | 0.025 | 705.8 |
| project_related | 40 | 0.802 | 0.908 | 0.85 | 0.975 | 0.5 | 6.25 | 0.025 | 595.5 |
| constrained | 30 | 0.967 | 0.892 | 0.833 | 1 | 0.933 | 8.633 | 0 | 727.5 |
| conflicting_info | 20 | 0.95 | 0.958 | 0.95 | 1 | 0.9 | 8.15 | 0 | 609.5 |
| completeness | 20 | 0.629 | 0.733 | 0.6 | 0.9 | 0.35 | 5.85 | 0.05 | 748.7 |
| miscellaneous | 20 | 0.95 | 0.925 | 0.9 | 0.95 | 0.95 | 8.55 | 0.05 | 321.4 |
| high_level | 10 | None | None | None | None | None | None | 0.2 | 748.0 |
| info_not_found | 20 | None | None | None | None | None | None | 0.05 | 604.5 |