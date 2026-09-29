# EnterpriseRAG-Bench through CIE: 50,000-document haystack, full memory bank

Run on Colab (A100) with `notebooks/enterprise_rag_bench_colab.ipynb` Part 1 (`DOCS = 50000`, `MEMORY = "full"`,
composed answers with `llama3.1:8b` through Ollama). The code came from branch `claude/epic-keller-gevn7j`: the
notebook checks out the head of the branch, which was 3885922. Embeddings: `BAAI/bge-small-en-v1.5` through
sentence-transformers on CUDA. Haystack: 50,000 of 511,958 documents (every gold document plus a stratified
sample). 500 questions. Memory bank tenant `erbfull-50000-cb66f7`.

## Load

**Output:** 50,000 documents became 316,223 sections and 253,454 memory records.

| Record type | Count |
|---|---|
| metric | 61,476 |
| document | 50,000 |
| risk | 31,508 |
| requirement | 29,515 |
| person | 21,988 |
| task | 16,009 |
| decision | 13,556 |
| deadline | 11,985 |
| organization | 8,723 |
| open_question | 3,046 |
| result | 2,512 |
| project | 2,373 |
| fact | 763 |

**Entities:** 30,711 people and companies, and 2,373 projects.

| Link type | Count |
|---|---|
| part_of | 174,247 |
| mentions | 151,805 |
| relates_to | 2,134 |
| depends_on | 1,700 |
| references | 1,221 |
| near_duplicate | 1,125 |
| contradicts | 420 |

**Duplicates and conflicts:** 1,125 near-duplicate document pairs and 210 conflicting facts.

**Time:** 782.7 s in total, of which 383.4 s was embedding.

## Arms

| arm | doc recall@10 | recall@5 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained on info-not-found | false abstentions | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid+graph(REM) | 0.7 | 0.635 | 0.594 | 0.511 | 0.755 | 0.645 | 8.811 | 0.15 | 0.017 | 776.4 / 5953.9 |
| vector-only | 0.685 | 0.638 | 0.607 | 0.538 | 0.738 | 0.636 | 8.885 | 0 | 0.015 | 194.8 / 235.7 |
| lexical-only | 0.517 | 0.482 | 0.457 | 0.398 | 0.572 | 0.468 | 8.945 | 0.3 | 0.023 | 406.6 / 5635.6 |
| hybrid+graph(REM), composed answers | 0.599 | 0.562 | 0.533 | 0.468 | 0.649 | 0.549 | 6.204 | 0.95 | 0.291 | 3235.6 / 8703.0 |

**Composed answers.** The model was `cie-llama3.1-8b` (Ollama, 12k-token context). It read 3,066,328 input
tokens and wrote 34,745 output tokens, at a cost of USD 0.0. One answer was replaced by the evidence-only answer,
and the checker attributed 55 citations.

## By category (hybrid+graph(REM))

| category | n | doc recall@10 | MRR | hit@1 | hit@10 | all gold found | extra docs@10 | abstained | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| basic | 175 | 0.863 | 0.675 | 0.566 | 0.863 | 0.863 | 9.137 | 0 | 630.9 |
| semantic | 125 | 0.352 | 0.215 | 0.168 | 0.352 | 0.352 | 9.248 | 0.04 | 694.6 |
| intra_document_reasoning | 40 | 0.9 | 0.73 | 0.625 | 0.9 | 0.9 | 8.8 | 0.025 | 956.1 |
| project_related | 40 | 0.618 | 0.877 | 0.8 | 1 | 0.175 | 7.3 | 0 | 1017.7 |
| constrained | 30 | 0.9 | 0.748 | 0.633 | 1 | 0.8 | 8.767 | 0 | 1178.7 |
| conflicting_info | 20 | 0.9 | 0.915 | 0.9 | 1 | 0.8 | 8.25 | 0 | 958.5 |
| completeness | 20 | 0.41 | 0.569 | 0.5 | 0.7 | 0.25 | 6.7 | 0.1 | 1073.5 |
| miscellaneous | 20 | 1.0 | 0.883 | 0.8 | 1 | 1 | 9 | 0 | 488.7 |
| high_level | 10 | None | None | None | None | None | None | 0.1 | 946.0 |
| info_not_found | 20 | None | None | None | None | None | None | 0.15 | 819.4 |
