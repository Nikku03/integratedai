# BM25 keyword search, test A (5,000 documents, local): report as produced

Run by `python -m cie.eval.bench_enterprise --docs 5000 --reuse-tenant erbfull-5000-9688c2 --arms
"hybrid+graph(REM),hybrid+graph(REM) [BM25],lexical-only,lexical-only [BM25]"` on a 4-CPU machine with nothing else
running, with the code of commit 97f079f and fastembed embeddings. Rules:
`docs/BM25_PREREGISTRATION.md`. Results and decision: `docs/BM25_RESULTS.md`.

### EnterpriseRAG-Bench through CIE (haystack 5,000 of 511,958 documents, 500 questions, embeddings=fastembed)

BM25 keyword index: 29,649 records and 33,200 sections, 15.6 MB, built in 7.3 s.

| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid+graph(REM) | 0.848 | 0.78 | 0.719 | 0.63 | 0.889 | 0.8 | 8.66 | 0.05 | 0.011 | 545.7 / 1906.9 |
| hybrid+graph(REM) [BM25] | 0.878 | 0.817 | 0.761 | 0.677 | 0.911 | 0.834 | 8.56 | 0 | 0.013 | 413.9 / 838.3 |
| lexical-only | 0.705 | 0.667 | 0.627 | 0.56 | 0.745 | 0.664 | 8.757 | 0.25 | 0.015 | 246.7 / 1311.3 |
| lexical-only [BM25] | 0.853 | 0.79 | 0.734 | 0.649 | 0.883 | 0.809 | 8.606 | 0 | 0.009 | 140.3 / 236.4 |

Keyword engine that served each keyword search: hybrid+graph(REM): fts 1,000; hybrid+graph(REM) [BM25]: bm25 1,000; lexical-only: fts 1,000; lexical-only [BM25]: bm25 1,000.

By category (hybrid+graph(REM)):

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.96 | 0.781 | 0.68 | 0.96 | 0.96 | 8.983 | 0.006 | 475.9 |
| semantic | 125 | 0.688 | 0.444 | 0.344 | 0.688 | 0.688 | 9.144 | 0.016 | 508.7 |
| intra_document_reasoning | 40 | 0.975 | 0.831 | 0.725 | 0.975 | 0.975 | 9.025 | 0 | 798.8 |
| project_related | 40 | 0.74 | 0.91 | 0.85 | 1 | 0.375 | 6.875 | 0 | 731.3 |
| constrained | 30 | 0.883 | 0.853 | 0.8 | 0.967 | 0.8 | 8.433 | 0.033 | 944.5 |
| conflicting_info | 20 | 0.975 | 0.967 | 0.95 | 1 | 0.95 | 8.05 | 0 | 684.4 |
| completeness | 20 | 0.552 | 0.636 | 0.5 | 0.85 | 0.3 | 6.7 | 0 | 801.1 |
| miscellaneous | 20 | 0.95 | 0.925 | 0.9 | 0.95 | 0.95 | 8.55 | 0.05 | 363.5 |
| high_level | 10 | None | None | None | None | None | None | 0.2 | 861.9 |
| info_not_found | 20 | None | None | None | None | None | None | 0.05 | 662.0 |

By category, the BM25 arms:

hybrid+graph(REM) [BM25]:

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.971 | 0.84 | 0.76 | 0.971 | 0.971 | 8.971 | 0.006 | 353.3 |
| semantic | 125 | 0.728 | 0.478 | 0.368 | 0.728 | 0.728 | 9.032 | 0.024 | 400.0 |
| intra_document_reasoning | 40 | 0.975 | 0.857 | 0.775 | 0.975 | 0.975 | 8.775 | 0.025 | 712.3 |
| project_related | 40 | 0.814 | 0.921 | 0.85 | 1 | 0.5 | 6.425 | 0 | 543.7 |
| constrained | 30 | 0.967 | 0.892 | 0.833 | 1 | 0.933 | 8.633 | 0 | 711.7 |
| conflicting_info | 20 | 0.95 | 0.958 | 0.95 | 1 | 0.9 | 8.15 | 0 | 564.5 |
| completeness | 20 | 0.649 | 0.758 | 0.6 | 0.95 | 0.35 | 6.15 | 0 | 673.2 |
| miscellaneous | 20 | 0.95 | 0.925 | 0.9 | 0.95 | 0.95 | 8.55 | 0.05 | 309.2 |
| high_level | 10 | None | None | None | None | None | None | 0.3 | 709.0 |
| info_not_found | 20 | None | None | None | None | None | None | 0 | 607.5 |

lexical-only [BM25]:

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.949 | 0.794 | 0.697 | 0.949 | 0.949 | 8.989 | 0.006 | 139.2 |
| semantic | 125 | 0.664 | 0.454 | 0.352 | 0.664 | 0.664 | 9.232 | 0.008 | 131.9 |
| intra_document_reasoning | 40 | 1.0 | 0.828 | 0.75 | 1 | 1 | 9 | 0 | 139.0 |
| project_related | 40 | 0.785 | 0.892 | 0.825 | 0.975 | 0.475 | 6.175 | 0.025 | 151.1 |
| constrained | 30 | 0.933 | 0.928 | 0.9 | 0.967 | 0.9 | 8.667 | 0 | 164.4 |
| conflicting_info | 20 | 0.9 | 0.955 | 0.95 | 1 | 0.8 | 8.25 | 0 | 132.4 |
| completeness | 20 | 0.714 | 0.8 | 0.7 | 0.9 | 0.45 | 5.3 | 0.05 | 180.2 |
| miscellaneous | 20 | 1.0 | 0.881 | 0.8 | 1 | 1 | 9 | 0 | 114.1 |
| high_level | 10 | None | None | None | None | None | None | 0.1 | 120.1 |
| info_not_found | 20 | None | None | None | None | None | None | 0 | 141.7 |

