# BM25 keyword search: results

The rules were fixed in `docs/BM25_PREREGISTRATION.md`, and committed (4fa32a0) before the test ran. Test A used the
local 5,000-document EnterpriseRAG-Bench memory bank and all 500 questions, on 4 CPUs with nothing else running. The
raw report is `docs/benchmarks/bm25/bench_bm25_5k.md`. Test B, at 50,000 documents on Colab, has not run yet.

## Two stopped starts

The test was started twice before the run reported here. Both starts were stopped before any result was printed:
- **Contention.** The first start shared the CPUs with an OCR benchmark that I had started by mistake. That would have
  slowed the full-text arm, which ran first.
- **A bug.** Code review then found that BM25 queries were stemmed twice: the query parser stemmed terms that were
  already stemmed, so "proposal" was searched as "propo". The query is now built from term queries. A test covers it,
  and the second start was stopped.

The run below is the third start, with the fixed code (97f079f).

## Outcome

**Every criterion was met.** Following the decision fixed in advance, **BM25 is now the default keyword engine**.
Test B confirms or reverts this.

| Criterion | Full text | BM25 | Rule | Met |
|---|---|---|---|---|
| 1. doc recall@10 (hybrid) | 0.848 | 0.878 | at least 0.838 | yes |
| 1. MRR (hybrid) | 0.719 | 0.761 | at least 0.709 | yes |
| 2. p95 latency (hybrid) | 1,906.9 ms | 838.3 ms | at most 1,144.1 ms | yes |
| 2. p50 latency (hybrid) | 545.7 ms | 413.9 ms | at most 600.3 ms | yes |
| 3. keyword searches served by BM25 | – | 1,000 of 1,000 | all | yes |

BM25 was both better and faster:
- The whole search found the right document in its top 10 for 3 more questions in 100.
- It ranked the first right document higher (MRR +0.042).
- Its slowest 5% of questions took 0.84 s instead of 1.9 s.
- Its typical question took 0.41 s instead of 0.55 s.

## Keyword search alone

| | Full text | BM25 |
|---|---|---|
| doc recall@10 | 0.705 | 0.853 |
| MRR | 0.627 | 0.734 |
| p50 / p95 | 246.7 / 1,311.3 ms | 140.3 / 236.4 ms |
| abstained on info-not-found | 0.25 | 0 |

Keyword search alone gained 15 points of recall, and its p95 fell from 1.31 s to 0.24 s. On its own it is now about as
good as the whole hybrid search was with full text (0.853 against 0.848).

## By question category (hybrid search)

| category | n | recall@10, full text | recall@10, BM25 | MRR, full text | MRR, BM25 |
|---|---|---|---|---|---|
| basic | 175 | 0.960 | 0.971 | 0.781 | 0.840 |
| semantic | 125 | 0.688 | 0.728 | 0.444 | 0.478 |
| intra_document_reasoning | 40 | 0.975 | 0.975 | 0.831 | 0.857 |
| project_related | 40 | 0.740 | 0.814 | 0.910 | 0.921 |
| constrained | 30 | 0.883 | 0.967 | 0.853 | 0.892 |
| conflicting_info | 20 | 0.975 | 0.950 | 0.967 | 0.958 |
| completeness | 20 | 0.552 | 0.649 | 0.636 | 0.758 |
| miscellaneous | 20 | 0.950 | 0.950 | 0.925 | 0.925 |

- **Gains.** BM25 gained recall in five categories, most in completeness questions (+0.10) and constrained questions
  (+0.08). Two were unchanged.
- **The one loss.** Conflicting-information questions lost 0.025 of recall, which is part of one gold document over
  20 questions.
- **Abstentions.** On the 20 questions whose answer is not in the corpus, the hybrid search abstained on none, against
  1 with full text. Abstaining is the right response there, so this is a small loss. False abstentions moved from
  0.011 to 0.013.

## The index

29,649 records and 33,200 sections, 15.6 MB, built in 7.3 s. The full-text vectors and GIN indexes of the same rows are
far larger (about 1.3 KB of vector per section alone); they stay, for the exact-lookup stage and as the fallback.

## Why BM25 did better, not only faster

Full-text search ranked in tiers: all words first, then fewer words, then any rare word, each tier under a time
limit. On a long question the strict tiers often find nothing, and the any-word tier is cut to the six rarest words and to
1.5 s. BM25 scores every document on all of the question's words at once, weighting rare words more, and returns the
best without scoring every match. The improvement is largest where questions are long and worded unlike the
documents (completeness, constrained, semantic).

## What this does not show

- **Scale.** Test B, at 50,000 documents on Colab, is the confirmation: 10 times the text and a GPU machine. If it
  fails any criterion, the default returns to full text.
- **Load.** One question at a time. Several at once were not measured.
- **Freshness under writes.** Rows written after the index was built are scored from the database until the worker
  takes them in. Tests cover this path; the benchmark's memory bank did not change during the run.
