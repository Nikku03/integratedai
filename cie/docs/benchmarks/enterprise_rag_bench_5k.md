### EnterpriseRAG-Bench through CIE (haystack 5,000 of 511,958 documents, 500 questions, embeddings=fastembed)

Load: 5,000 documents → 31,927 sections, 5,000 document records, 0 entity links; 551.3 s (459.9 s embedding, 80.3 texts/s).

| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid+graph(REM) | 0.857 | 0.808 | 0.738 | 0.655 | 0.885 | 0.821 | 8.379 | 0.05 | 0.032 | 469.8 / 1301.2 |
| hybrid+cliques+bonus | 0.857 | 0.808 | 0.738 | 0.655 | 0.885 | 0.821 | 8.379 | 0.05 | 0.032 | 460.6 / 1293.5 |
| vector-only | 0.855 | 0.818 | 0.78 | 0.717 | 0.887 | 0.817 | 8.551 | 0.05 | 0.019 | 287.2 / 342.1 |
| lexical-only | 0.672 | 0.61 | 0.581 | 0.515 | 0.711 | 0.628 | 8.643 | 0.25 | 0.028 | 191.2 / 1020.2 |

By category (hybrid+graph(REM)):

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.949 | 0.801 | 0.714 | 0.949 | 0.949 | 8.869 | 0.017 | 448.6 |
| semantic | 125 | 0.688 | 0.449 | 0.336 | 0.688 | 0.688 | 8.672 | 0.064 | 476.9 |
| intra_document_reasoning | 40 | 1.0 | 0.886 | 0.8 | 1 | 1 | 8.925 | 0 | 470.3 |
| project_related | 40 | 0.82 | 0.909 | 0.875 | 0.975 | 0.55 | 6.125 | 0.025 | 481.0 |
| constrained | 30 | 0.967 | 0.901 | 0.867 | 0.967 | 0.967 | 8.5 | 0 | 602.2 |
| conflicting_info | 20 | 0.925 | 0.95 | 0.95 | 0.95 | 0.9 | 7.5 | 0.05 | 471.8 |
| completeness | 20 | 0.571 | 0.733 | 0.6 | 0.9 | 0.3 | 6.2 | 0.05 | 528.8 |
| miscellaneous | 20 | 0.95 | 0.892 | 0.85 | 0.95 | 0.95 | 8.55 | 0.05 | 397.5 |
| high_level | 10 | None | None | None | None | None | None | 0.5 | 461.1 |
| info_not_found | 20 | None | None | None | None | None | None | 0.05 | 475.4 |