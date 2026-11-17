# The platform's full memory bank of the whole company (2026-09-24)

The platform's memory bank (`cie.eval.bench_enterprise --memory full`, `docs/MEMORY_BANK.md`) built from every
document of EnterpriseRAG-Bench, and its search measured on the benchmark's 500 questions. Run on Colab with a GPU
on 2026-09-24. The files were saved to Google Drive (`cie_enterprise/enterprise_full`) and copied here on 2026-11-17.

## What it holds

| | |
|---|---|
| documents | 511,958 of 511,958 (none failed) |
| sections (passages) | 3,218,249 |
| memory records | 2,425,509: 631,134 metrics, 511,958 documents, 318,912 risks, 301,712 requirements, 162,989 tasks, 136,526 decisions, 123,125 deadlines, 106,734 people, 57,568 companies, 31,621 open questions, 22,499 results, 13,306 projects, 7,425 disputed facts |
| links | 3.5 million: 1,788,717 part of, 1,542,925 mentions, 57,515 relates to, 39,831 depends on, 34,721 references, 29,803 near duplicates, 17,490 contradicts |
| found across documents | 164,302 people and companies; 29,803 near-duplicate pairs; 8,745 conflicting facts |
| references it could not resolve | 714,087 (the cited record is not in the company export); 36,376 ambiguous |
| build | 8,629 s (2.4 hours), of which 4,078 s embedding 5.6 million texts (`BAAI/bge-small-en-v1.5`, 384 dimensions) |

The database itself (PostgreSQL with pgvector, tenant `erbfull-511958-dd6d12`) lived on the Colab machine and is
not saved. Drive keeps its embedding cache (`emb_cache.sqlite`, 6.1 GB), which lets a rebuild skip most of the
embedding; it is not copied here.

## Checks made on 2026-11-17

- **The same benchmark as this repository's tests:** the report's fingerprints of the question ids (`2ee1c234a3d7`)
  and of the documents (`9a84fda535e8`, 511,958) equal those of the benchmark at commit `d36685e`.
- **The numbers stand:** recomputed from the per-question answer files here, document recall@10 is 0.524 (hybrid),
  0.523 (vector only) and 0.266 (keywords only), and the right document comes first for 0.372, 0.377 and 0.215: the
  report's figures.

## What it shows

| search over | right documents in the top 10 | of which, questions asked in other words ("semantic") |
|---|---|---|
| 5,000 documents (every gold document and a sample; `docs/BENCHMARKS.md`) | 0.857 | 0.688 |
| the whole company, 511,958 documents | 0.524 | 0.160 |

- With the whole company as distractors, the search finds the right documents for half the questions. Questions
  worded unlike their document fall to 16%.
- Search by meaning alone does as well as search by meaning, keywords and links together (0.523 against 0.524), at a
  fifteenth of the time (229 ms against 3,367 ms for a typical question).
- It says "not found" on 1 of the 20 questions whose answer is in no document.
- These are document-finding measures only. No answer was judged.

## Files

| file | what |
|---|---|
| `bench_enterprise.json`, `bench_enterprise.md` | the report: the load and every arm, overall and by question type |
| `load.json` | the load's counts and times |
| `answers_*_detail.jsonl.gz` | each arm's answer to each question and the documents it found, in order |
