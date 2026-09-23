### EnterpriseRAG-Bench through CIE (haystack 5,000 of 511,958 documents, 500 questions, embeddings=fastembed)

Load (full memory bank): 5,000 documents → 33,200 sections and 28,722 memory records (metric 6,269, document 5,000, person 3,947, risk 3,362, requirement 3,260, task 1,758, decision 1,494, deadline 1,206, organization 1,199, result 493, project 327, open_question 309, fact 98); 5,146 people and companies, 327 projects; links: part_of 18,630, mentions 16,373, references 388, relates_to 48, near_duplicate 45, depends_on 42, contradicts 26; 45 near-duplicate document pairs, 13 conflicting facts; 905.2 s (817.9 s embedding).

| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid+graph(REM) | 0.848 | 0.78 | 0.719 | 0.63 | 0.889 | 0.8 | 8.66 | 0.05 | 0.011 | 549.4 / 1883.1 |
| hybrid+cliques+bonus | 0.849 | 0.786 | 0.718 | 0.628 | 0.887 | 0.802 | 8.649 | 0.05 | 0.011 | 528.9 / 1874.0 |
| vector-only | 0.836 | 0.788 | 0.744 | 0.664 | 0.883 | 0.789 | 8.721 | 0 | 0.009 | 314.5 / 387.9 |
| lexical-only | 0.703 | 0.662 | 0.623 | 0.555 | 0.743 | 0.662 | 8.76 | 0.25 | 0.015 | 169.0 / 1146.6 |

By category (hybrid+graph(REM)):

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.96 | 0.784 | 0.686 | 0.96 | 0.96 | 8.983 | 0.006 | 502.4 |
| semantic | 125 | 0.688 | 0.438 | 0.336 | 0.688 | 0.688 | 9.144 | 0.016 | 508.4 |
| intra_document_reasoning | 40 | 0.975 | 0.833 | 0.725 | 0.975 | 0.975 | 9.025 | 0 | 851.0 |
| project_related | 40 | 0.74 | 0.91 | 0.85 | 1 | 0.375 | 6.875 | 0 | 768.1 |
| constrained | 30 | 0.883 | 0.853 | 0.8 | 0.967 | 0.8 | 8.433 | 0.033 | 855.5 |
| conflicting_info | 20 | 0.975 | 0.967 | 0.95 | 1 | 0.95 | 8.05 | 0 | 716.7 |
| completeness | 20 | 0.552 | 0.636 | 0.5 | 0.85 | 0.3 | 6.7 | 0 | 836.4 |
| miscellaneous | 20 | 0.95 | 0.925 | 0.9 | 0.95 | 0.95 | 8.55 | 0.05 | 403.8 |
| high_level | 10 | None | None | None | None | None | None | 0.2 | 951.6 |
| info_not_found | 20 | None | None | None | None | None | None | 0.05 | 680.6 |