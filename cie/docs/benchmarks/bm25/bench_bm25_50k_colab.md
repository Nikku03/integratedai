# BM25 keyword search, test B (50,000 documents, Colab A100): report as produced

Run by `notebooks/enterprise_rag_bench_colab.ipynb` Part 1 on a fresh load of the 50,000-document haystack (tenant
`erbfull-50000-7db44b`), code of branch `claude/epic-keller-gevn7j` at c00ed8d, embeddings `sentence_transformers[cuda]`.
The BM25 index was built right after the load. Rules: `docs/BM25_PREREGISTRATION.md`. Results: `docs/BM25_RESULTS.md`.

Load (full memory bank): 50,000 documents → 316,223 sections and 253,454 memory records (metric 61,476, document
50,000, risk 31,508, requirement 29,515, person 21,988, task 16,009, decision 13,556, deadline 11,985, organization
8,723, open_question 3,046, result 2,512, project 2,373, fact 763); 30,711 people and companies, 2,373 projects; links:
part_of 174,247, mentions 151,805, relates_to 2,134, depends_on 1,700, references 1,221, near_duplicate 1,125,
contradicts 420; 1,125 near-duplicate document pairs, 210 conflicting facts; 790.0 s (387.2 s embedding).

BM25 keyword index: 254,077 records and 316,223 sections, 136.2 MB, built in 76.6 s.

| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid+graph(REM) | 0.691 | 0.627 | 0.593 | 0.513 | 0.747 | 0.636 | 8.798 | 0.15 | 0.019 | 773.1 / 5950.1 |
| hybrid+graph(REM) [BM25] | 0.734 | 0.669 | 0.638 | 0.564 | 0.781 | 0.689 | 8.809 | 0 | 0.009 | 376.0 / 860.8 |
| vector-only | 0.685 | 0.637 | 0.607 | 0.538 | 0.738 | 0.636 | 8.864 | 0 | 0.017 | 192.7 / 228.8 |
| lexical-only | 0.517 | 0.48 | 0.455 | 0.396 | 0.572 | 0.468 | 8.926 | 0.3 | 0.026 | 427.0 / 5639.2 |
| lexical-only [BM25] | 0.721 | 0.666 | 0.623 | 0.549 | 0.764 | 0.672 | 8.828 | 0 | 0.006 | 147.8 / 194.7 |
| hybrid+graph(REM), composed answers | 0.65 | 0.609 | 0.59 | 0.532 | 0.689 | 0.611 | 6.632 | 0.9 | 0.238 | 2979.6 / 3891.6 |

Keyword engine that served each keyword search: hybrid+graph(REM): fts 1,000; hybrid+graph(REM) [BM25]: bm25 1,000;
lexical-only: fts 1,000; lexical-only [BM25]: bm25 1,000; hybrid+graph(REM), composed answers: bm25 1,000.

Composed answers: model `cie-llama3.1-8b` (Ollama), 3,069,612 input and 39,933 output tokens, USD 0.0; no answer
replaced by the evidence-only answer; 80 citations attributed by the checker. With BM25 now the default, the composed
arm's retrieval used BM25.

By category (hybrid+graph(REM), full text; the run printed no per-category table for the BM25 arms):

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.857 | 0.676 | 0.577 | 0.857 | 0.857 | 9.086 | 0.006 | 661.5 |
| semantic | 125 | 0.336 | 0.208 | 0.16 | 0.336 | 0.336 | 9.264 | 0.04 | 727.1 |
| intra_document_reasoning | 40 | 0.875 | 0.728 | 0.625 | 0.875 | 0.875 | 8.825 | 0.025 | 1006.3 |
| project_related | 40 | 0.611 | 0.881 | 0.8 | 1 | 0.175 | 7.3 | 0 | 1035.7 |
| constrained | 30 | 0.9 | 0.754 | 0.633 | 1 | 0.8 | 8.767 | 0 | 1188.4 |
| conflicting_info | 20 | 0.9 | 0.915 | 0.9 | 1 | 0.8 | 8.25 | 0 | 1000.9 |
| completeness | 20 | 0.41 | 0.569 | 0.5 | 0.7 | 0.25 | 6.7 | 0.1 | 1252.5 |
| miscellaneous | 20 | 1.0 | 0.883 | 0.8 | 1 | 1 | 9 | 0 | 558.0 |
| high_level | 10 | None | None | None | None | None | None | 0.1 | 966.7 |
| info_not_found | 20 | None | None | None | None | None | None | 0.15 | 850.5 |

Pre-registered BM25 criteria (test B), as printed:

| Criterion | Met | Value |
|---|---|---|
| 1. recall@10 at least full text's - 0.01 | yes | 0.734 vs 0.691 |
| 1. MRR at least full text's - 0.01 | yes | 0.638 vs 0.593 |
| 2. p95 at most 0.6 x full text's | yes | 860.8 vs 5950.1 ms |
| 2. p50 at most 1.1 x full text's | yes | 376.0 vs 773.1 ms |
| 3. every keyword search served by BM25 | yes | bm25 1,000 |

All criteria met.
