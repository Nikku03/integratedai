# BM25 keyword search: results

The rules were fixed in `docs/BM25_PREREGISTRATION.md`, and committed (4fa32a0) before the test ran. Test A used the
local 5,000-document EnterpriseRAG-Bench memory bank and all 500 questions, on 4 CPUs with nothing else running. The
raw report is `docs/benchmarks/bm25/bench_bm25_5k.md`. Test B used a fresh load of the 50,000-document memory bank on
Colab (A100); its raw report is `docs/benchmarks/bm25/bench_bm25_50k_colab.md`.

## Two stopped starts

The test was started twice before the run reported here. Both starts were stopped before any result was printed:
- **Contention.** The first start shared the CPUs with an OCR benchmark that I had started by mistake. That would have
  slowed the full-text arm, which ran first.
- **A bug.** Code review then found that BM25 queries were stemmed twice: the query parser stemmed terms that were
  already stemmed, so "proposal" was searched as "propo". The query is now built from term queries. A test covers it,
  and the second start was stopped.

The run below is the third start, with the fixed code (97f079f).

## Outcome

**Every criterion was met in both tests.** Following the decisions fixed in advance, **BM25 is the default keyword
engine**: test A made it the default, and test B, at ten times the size, confirmed it.

### Test B: 50,000 documents

| Criterion | Full text | BM25 | Rule | Met |
|---|---|---|---|---|
| 1. doc recall@10 (hybrid) | 0.691 | 0.734 | at least 0.681 | yes |
| 1. MRR (hybrid) | 0.593 | 0.638 | at least 0.583 | yes |
| 2. p95 latency (hybrid) | 5,950.1 ms | 860.8 ms | at most 3,570.1 ms | yes |
| 2. p50 latency (hybrid) | 773.1 ms | 376.0 ms | at most 850.4 ms | yes |
| 3. keyword searches served by BM25 | – | 1,000 of 1,000 | all | yes |

At 50,000 documents, BM25's lead grew:
- **The slow tail is gone.** The slowest 5% of questions took 0.86 s instead of 5.95 s, about 7 times faster.
  Typical questions took 0.38 s instead of 0.77 s.
- **Better ranking.** Recall@10 rose by 4.3 points, MRR by 4.5, and the right document came first for 56% of
  questions against 51%.
- **Keyword search alone** went from 0.517 to 0.721 recall@10, and its p95 from 5.64 s to 0.19 s. On its own it now
  beats vector search (0.685).
- **Fusion now pays.** With full text, hybrid search added under a point over vector search alone (0.691 against
  0.685) at 26 times its p95. With BM25 it adds 4.9 points (0.734), at a p95 of 0.86 s.
- **The index.** 254,077 records and 316,223 sections came to 136.2 MB, built in 76.6 s, after a 790 s load.
- **One loss repeats.** On the 20 questions whose answer is not in the corpus, the hybrid search abstained on none,
  against 3 with full text. False abstentions on answerable questions halved (0.009 against 0.019).
- **Composed answers.** The Llama arm uses the default engine, now BM25. Its recall@10 was 0.650, against 0.599 in
  the earlier 50k runs with full text, and its p95 3.9 s against 9.2 s. That arm was not part of the pre-registered
  comparison.

### Test A: 5,000 documents

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

- **Larger scale.** 50,000 documents is a tenth of the corpus. The BM25 index grew about linearly (16 MB at 5,000
  documents, 136 MB at 50,000), but the full 512,000 documents were not tested.
- **Load.** One question at a time. Several at once were not measured.
- **Freshness under writes.** Rows written after the index was built are scored from the database until the worker
  takes them in. Tests cover this path; the benchmark's memory bank did not change during the run.
