### EnterpriseRAG-Bench through CIE (haystack 5,000 of 511,958 documents, 500 questions, embeddings=fastembed)

| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid+graph(REM) | 0.837 | 0.796 | 0.716 | 0.632 | 0.866 | 0.806 | 8.309 | 0.25 | 0.043 | 227.0 / 1057.2 |
| hybrid+cliques+bonus | 0.845 | 0.797 | 0.717 | 0.632 | 0.877 | 0.811 | 8.36 | 0.2 | 0.036 | 224.9 / 1115.5 |
| vector-only | 0.837 | 0.806 | 0.76 | 0.691 | 0.872 | 0.802 | 8.521 | 0.15 | 0.026 | 105.5 / 160.5 |
| lexical-only | 0.675 | 0.615 | 0.583 | 0.513 | 0.715 | 0.628 | 8.643 | 0.25 | 0.028 | 127.1 / 969.8 |

By category (hybrid+graph(REM)):

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.943 | 0.772 | 0.674 | 0.943 | 0.943 | 8.817 | 0.023 | 223.2 |
| semantic | 125 | 0.632 | 0.412 | 0.296 | 0.632 | 0.632 | 8.488 | 0.088 | 213.5 |
| intra_document_reasoning | 40 | 1.0 | 0.937 | 0.9 | 1 | 1 | 8.925 | 0 | 231.2 |
| project_related | 40 | 0.812 | 0.885 | 0.825 | 0.975 | 0.575 | 6.225 | 0.025 | 277.8 |
| constrained | 30 | 0.967 | 0.884 | 0.833 | 0.967 | 0.967 | 8.533 | 0 | 310.1 |
| conflicting_info | 20 | 0.95 | 0.925 | 0.9 | 0.95 | 0.95 | 7.55 | 0.05 | 238.7 |
| completeness | 20 | 0.552 | 0.768 | 0.7 | 0.9 | 0.3 | 6.3 | 0.05 | 267.5 |
| miscellaneous | 20 | 0.9 | 0.842 | 0.8 | 0.9 | 0.9 | 8.1 | 0.1 | 180.7 |
| high_level | 10 | None | None | None | None | None | None | 0.3 | 242.3 |
| info_not_found | 20 | None | None | None | None | None | None | 0.25 | 233.0 |