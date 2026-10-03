# BM25 inside the first documents: sentence extracts (development half only; not adopted)

## Idea

Take the first documents of today's evidence packet, split every passage of those documents into sentences, and score
each sentence with BM25 against the question. BM25 statistics are computed over those sentences only, not the whole
corpus. Keep the best sentences, each with the sentence after it, up to a size limit. Two scorings were tried:
- **forward:** the question is the query and each sentence a document (k1 1.2, b 0.75, length-normalised);
- **reverse:** each sentence is the query and the question the document, which comes to the sum of the IDF of the
  question terms the sentence holds, with no length penalty.

The extracts were tried two ways: on their own, or placed first with today's items after them, up to the 24,000
characters a small model reads.

## Run

Tenant `erbfull-5000-9688c2` (5,000 documents), today's defaults (BM25, expansion 3 × 5). The run covered the
development half only (odd question numbers): 189 judged questions and 673 checkable answer facts. The fact check is
the evidence audit's: every number, and 70% of the content words, in one passage. `measure.py` gives the table below,
`diagnose.py` the breakdown after it. Raw results are in `dev_odd_half.json`.

| What the model reads | every fact reached | facts reached | characters read |
|---|---|---|---|
| **today (24k)** | **139 (74%)** | **477** | 23,524 |
| ceiling: every fact anywhere in the first 3 documents | 141 (75%) | 478 | — |
| ceiling: every fact anywhere in the first 5 documents | 152 (80%) | 520 | — |
| 5 documents, extracts only, 3k (forward) | 78 (41%) | 259 | 3,815 |
| 5 documents, extracts only, 6k (forward) | 94 (50%) | 332 | 7,057 |
| 5 documents, extracts only, 12k (forward) | 113 (60%) | 414 | 13,410 |
| 5 documents, 3k extracts, then today's items (forward) | 140 (74%) | 478 | 23,496 |
| 5 documents, 6k extracts, then today's items (forward) | 141 (75%) | 475 | 23,496 |
| 5 documents, 3k extracts, then today's items (reverse) | 140 (74%) | 480 | 23,493 |
| 5 documents, 6k extracts, then today's items (reverse) | 140 (74%) | 475 | 23,506 |
| 5 documents, 12k extracts, then today's items (reverse) | 135 (71%) | 467 | 23,486 |
| 3 documents, best of either scoring | 138 (73%) | 469 | 23,527 |

Extraction takes about 11 ms at p50 and 19 ms at p95 (5 documents, fetch and scoring). Every arm is in the JSON.

**Result:** at most +2 questions of 189, which is within run-to-run noise. Extracts on their own lose facts at every
size. The idea is not adopted, so the even half was not run and stays unused for a later pre-registered test.

## Why it cannot help much

Today's model view misses 196 of the 673 facts. Where those facts are:

| Where the missed fact is | facts |
|---|---|
| in a document outside the first 5 | 131 |
| gold document not in the packet | 13 |
| in the first 5 documents | 52 |

- **Most missed facts are in other documents.**
  - By question type: completeness 47, project_related 35, semantic 28, basic 9, constrained 7, conflicting_info 3,
    intra_document_reasoning 2.
  - By the question's number of gold documents: one 45, two 13, three 5, four 1, five or more 67.
  - No extraction from 5 documents can reach these facts.
- **The 52 facts in the first 5 documents are hard to pull out by sentence:**
  - 31 span more than two sentences, so a sentence extract cuts them;
  - for 14 of the rest, the best sentence holding the fact ranks 11th or lower among a few hundred sentences: the
    answer is worded differently from the question (for example, "memory-pressure cascade on westus-edge-3 shards"
    for "why did the response feed arrive in bursts");
  - only 7 rank in the top 10.

The limit is the number of documents an answer is spread over, not which part of the top documents is chosen. The
levers that address it are reading more (the pre-registered read-more arm, `docs/READ_MORE_PREREGISTRATION.md`) and
follow-up searches.
