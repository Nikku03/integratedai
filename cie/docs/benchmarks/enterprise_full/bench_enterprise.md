### EnterpriseRAG-Bench through CIE (haystack 511,958 of 511,958 documents, 500 questions, embeddings=sentence_transformers[cuda])

Load (full memory bank): 511,958 documents → 3,218,249 sections and 2,425,509 memory records (metric 631,134, document 511,958, risk 318,912, requirement 301,712, task 162,989, decision 136,526, deadline 123,125, person 106,734, organization 57,568, open_question 31,621, result 22,499, project 13,306, fact 7,425); 164,302 people and companies, 13,306 projects; links: part_of 1,788,717, mentions 1,542,925, relates_to 57,515, depends_on 39,831, references 34,721, near_duplicate 29,803, contradicts 17,490; 29,803 near-duplicate document pairs, 8,745 conflicting facts; 8629.0 s (4078.0 s embedding).

| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid+graph(REM) | 0.524 | 0.468 | 0.44 | 0.372 | 0.581 | 0.481 | 9.102 | 0.05 | 0.017 | 3366.9 / 11918.0 |
| vector-only | 0.523 | 0.468 | 0.444 | 0.377 | 0.589 | 0.472 | 9.221 | 0 | 0.006 | 228.9 / 497.1 |
| lexical-only | 0.266 | 0.252 | 0.253 | 0.215 | 0.319 | 0.234 | 8.764 | 0.3 | 0.077 | 2482.2 / 10773.5 |

By category (hybrid+graph(REM)):

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.686 | 0.492 | 0.394 | 0.686 | 0.686 | 9.314 | 0 | 3516.6 |
| semantic | 125 | 0.16 | 0.099 | 0.064 | 0.16 | 0.16 | 9.6 | 0.024 | 3255.2 |
| intra_document_reasoning | 40 | 0.725 | 0.577 | 0.525 | 0.725 | 0.725 | 8.775 | 0.05 | 2905.6 |
| project_related | 40 | 0.436 | 0.711 | 0.625 | 0.875 | 0.1 | 8.15 | 0.025 | 3741.3 |
| constrained | 30 | 0.7 | 0.495 | 0.4 | 0.767 | 0.633 | 9.1 | 0 | 4176.7 |
| conflicting_info | 20 | 0.725 | 0.783 | 0.75 | 0.85 | 0.6 | 8.5 | 0 | 3151.7 |
| completeness | 20 | 0.314 | 0.469 | 0.45 | 0.55 | 0.2 | 7.8 | 0.05 | 5143.6 |
| miscellaneous | 20 | 0.9 | 0.85 | 0.8 | 0.9 | 0.9 | 8.6 | 0.05 | 2698.8 |
| high_level | 10 | None | None | None | None | None | None | 0.1 | 3153.7 |
| info_not_found | 20 | None | None | None | None | None | None | 0.05 | 1985.3 |