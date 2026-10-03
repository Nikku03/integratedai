# What kinds of answer facts are missing: a 50-document analysis

## Setup

- **Documents.** 50 documents, built in memory from the benchmark files with the memory bank's own document builder
  (`cie.ingest.builder`). No database was used, and the 5,000-document memory bank was not touched.
- **Questions.** Development-half questions (odd numbers), one of each question type in turn, adding each question's
  gold documents while the set stays within 50 documents. That gives 26 questions of all 8 types; 12 of them have
  two to six gold documents.
- **Facts.** 147 answer facts. "The answer must not ..." facts are left out: they constrain the answer and no evidence
  can hold them.
- **Search,** per question, as today's defaults do for passages:
  - BM25 and vector search (bge-small), fused by RRF;
  - then document expansion: the first 3 documents, 5 passages each.

  Memory records and the reranker are not used. The model reads the top passages up to 24,000 characters.
- **Fact check:**
  1. The evidence audit's word check.
  2. Facts the word check cannot follow (57) went to a judge agent, along with the 3 that search lost. The judge reads
     every passage of the question's documents and decides whether the documents state each fact, and where.
  3. A separate agent sorted all 147 facts by kind. It did not know which facts were missed.

Run `mini50.py`, then `combine.py`. `facts.json` has every fact with its outcome, kind and the judge's note.

## Results

**Where the 147 facts end up:**

| | facts |
|---|---|
| reached the model, words match | 87 (59%) |
| reached the model, in different words | 43 (29%) |
| **not written anywhere: must be worked out** | **8 (5%)** |
| **spread over several passages, not all reached the model** | **4 (3%)** |
| **the documents say something different** | **3 (2%)** |
| **in a passage that did not reach the model** | **2 (1%)** |

Search at 50 documents loses little. 87 of the 90 facts the word check can follow reached the model (97%). On the
5,000-document memory bank, it was 477 of 673 (71%; a different set of 189 questions). Most of that loss comes from
the number of documents competing for the 24,000 characters (`docs/benchmarks/inside_bm25/`).

**By kind of fact** (missing: worked out | spread or lost | documents differ):

| kind | facts | missing |
|---|---|---|
| action or recommendation | 45 | **8** (5 \| 3 \| 0) |
| figure | 14 | 2 (2 \| 0 \| 0) |
| date or duration | 15 | 2 (0 \| 0 \| 2) |
| decision or status | 8 | 2 (1 \| 0 \| 1) |
| cause or reason | 23 | 2 (0 \| 2 \| 0) |
| rule or requirement | 23 | 1 (0 \| 1 \| 0) |
| name or identifier | 12 | 0 |
| person or owner | 3 | 0 |
| description | 4 | 0 |

**By question type:** project_related 8 of 42 missing, conflicting_info 4 of 14, constrained 3 of 17, basic 1 of 15,
completeness 1 of 31. semantic, intra_document_reasoning and miscellaneous: none.

## The missing facts, by what they need

1. **Not written anywhere; the answer must work it out (8).**
   - **Recommendations derived from a problem (5).** For example, "the UI should display the baseline window and
     stale_as_of timestamp" or "verify 5xx rates stay below burn thresholds". The documents describe the problem or
     the dashboards; the gold answer turns that into what to do.
   - **Arithmetic (1):** a score drop of 0.8, from 2.7 − 1.9. The 0.8 is never written.
   - **A count across documents (1):** "4 incident writeups describe activating automatic fallback", counted over
     separate postmortems.
   - **A comparison (1):** "earlier guidance omitted top_p, num_beams ..."; this appears only by comparing two lists.
2. **Spread over several places (4 + 2).** Root causes told over several turns of a Slack incident thread. A config
   change whose flag names sit in one document and label names in another. Recommendations split across chat
   messages. Part of the pieces reached the model and part did not; the passages ranked 24th and 32nd.
3. **The documents say something different (3, one conflicting_info question).** The gold answer keeps a 72-hour grace
   window and a 48-hour notice. The documents give 5 business days, with 72 hours only as the superseded value, and
   record an approval that the gold answer says is not recorded. Three facts cannot tell whether the benchmark or the
   judge is wrong.

**Never missed:** names, identifiers, people, owners and descriptions.

## What follows

- **Worked-out facts are the model's job, not search's.** The evidence is there. Counting and arithmetic are better
  done by code (the analyst's calculator) than by the model.
- **Facts spread over a thread or several documents need more of the source in front of the model.** Two ways: read
  more (the read-more arm, 60,000 characters), or retrieve a whole thread or section when one passage of it ranks.
- **The word check undercounts.** 39% of the facts are not written word-for-word in the documents, but 43 of those 57
  reached the model in other words. The evidence audit's "every fact reached" figures are a floor.

## Limits

- 26 questions and 147 facts on a 50-document set: the kinds and proportions are indicative.
- 50 documents is easy for search. At 5,000 documents and beyond, most losses are documents outranked by others (see
  above).
- One judge and one classifier, both LLM agents. Their notes are in `judge.json` and `kinds.json`.
