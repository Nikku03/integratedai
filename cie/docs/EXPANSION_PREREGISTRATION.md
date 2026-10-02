# Document expansion: what is measured and what decides the default, fixed before the test runs

I wrote this before running anything on the test half below. The setting was chosen on the development half only.

## Question

The evidence audit (`docs/EVIDENCE_AUDIT.md`) follows each question's answer facts through the memory bank. On the
5,000-document memory bank with BM25, 24% of the judged questions had the right document in the packet but not the
passage that holds the answer ("right document, wrong part").

Passages of every document compete for the packet. A document often arrives through one passage, or through a memory
record, while the passage with the answer loses to other documents' passages.

Document expansion (`Retriever._expand_documents`) takes the first N documents of the ranked list. For each one, it
runs a keyword search inside that document only. The document's top M passages are placed right after its first item:
moved up when they were ranked lower, added when they were not candidates at all. They pass the same permission filter.
The packet's token budget (12,000) still decides what fits.

**Does document expansion get more questions' answer facts to the model without hurting search?**

## Development (odd question numbers)

Questions are split by number: odd numbers are the development half, even numbers the test half. Every number below
comes from the development half, on tenant `erbfull-5000-9688c2`, with BM25 and extractive answers.

**Diagnosis.** In the 47 "wrong part" questions there were 144 missing facts:
- 128 (89%) sat in a document that was in the packet, in a passage that was not;
- 13 sat in a document that was not in the packet;
- 3 were cut by the 1,200-character section trim.

Where the missing passage ranked inside its own document (a keyword search inside the document): 1st for 30 facts, 2nd
27, 3rd 31, 4th 14, 5th 5, lower 21.

**A bug found and fixed during development.** The first version only added passages that were not candidates at all.
A passage that was a candidate but ranked too low to fit was left where it was. It now moves up.

**Settings tried** (189 judged questions):

| documents × passages | wrong part | cut before model | everything reached the model | facts in packet | facts in model view |
|---|---|---|---|---|---|
| off | 47 | 16 | 120 (63%) | 516 | 447 |
| 1 × 5 | 40 | 13 | 130 (69%) | 527 | 463 |
| 2 × 3 | 39 | 14 | 130 (69%) | 532 | 472 |
| 3 × 3 | 38 | 13 | 132 (70%) | 533 | 473 |
| 5 × 3 | 39 | 12 | 132 (70%) | 536 | 471 |
| **3 × 5** | **34** | **11** | **138 (73%)** | **537** | **477** |
| 5 × 5 | 34 | 11 | 137 (72%) | 536 | 475 |
| 3 × 8 | 34 | 14 | 135 (71%) | 536 | 475 |
| 3 × 12 | 30 | 14 | 137 (72%) | 532 | 475 |
| 10 × 1 | 42 | 15 | 126 (67%) | 530 | 453 |
| 10 × 2 | 38 | 16 | 129 (68%) | 528 | 464 |
| 20 × 1 | 45 | 12 | 125 (66%) | 515 | 448 |

Search missed the document in 6 questions in every row except 5 × 5 (7) and 3 × 12 (8).

**Fixed for the test: 3 documents × 5 passages** (`packet_expand_documents = 3`, `packet_expand_sections = 5`).

**Cost.** On 80 development questions, expansion itself took 24 ms at p50 and 32 ms at p95 (three keyword searches).
Whole retrieval rose from 355 to 404 ms at p50, and from 382 to 426 ms in a repeat.

## Test runs

- **A. 5,000 documents, local.** Tenant `erbfull-5000-9688c2`, 4 CPUs. Run once.
  - The evidence audit on the **even half**, with expansion off (`--expand-documents 0`) and on (`3`). Extractive answers;
    model view of 24,000 characters (`llm_local_evidence_chars`), as in every earlier audit.
  - `cie.eval.bench_enterprise` on all 500 questions with two arms:
    - `hybrid+graph(REM) [BM25+expansion]` (expansion on), run first;
    - `hybrid+graph(REM) [BM25]` (expansion off; otherwise identical).

    Both halves are in this run: these numbers were not used to choose the setting.
- **B. 50,000 documents, Colab A100.** The notebook's Part 1 (the two arms are in the default `ARMS`) and Part 1b (the
  audit with expansion off and on). Run once, as confirmation. Its criteria use the audit's even half.

## Criteria

Document expansion becomes the default (`packet_expand_documents = 3`) if all of these hold:

1. **More answers reach the model.** "Everything reached the model" with expansion is at least 4 percentage points
   higher than without it, on the even half.
2. **Nothing lost on the way.**
   - Facts in the model view with expansion are at least as many as without it.
   - "Search missed the document" rises by at most 2 questions.
3. **Search unchanged.** `[BM25+expansion]` has doc recall@10 at least `[BM25]`'s minus 0.01, and MRR at least its MRR
   minus 0.01. 0.01 is the run-to-run variation measured between two loads of the 50k haystack.
4. **Speed.**
   - p50 latency at most `[BM25]`'s p50 + 100 ms.
   - p95 latency at most `[BM25]`'s p95 + 200 ms.

   About twice the cost measured on development questions, plus the variation between repeat runs.

## Reported, with no threshold

- Every stage count, with expansion on and off, by question category.
- How many questions moved between stages in each direction.
- Facts in the extractive answer, with expansion on and off.
- The same audit on the development half and on all questions (the development half was used to choose the setting).
- The `bench_enterprise` measures by category.

What this does not measure: whether a model's answers improve. Local runs have no GPU. The notebook's Part 1b with
`LLM_ANSWERS` measures that on Colab.

## Decisions fixed in advance

- **A meets 1 to 4.** The default becomes 3 documents × 5 passages now. B confirms it or reverts it.
- **A meets 3 and 4 but not 1 or 2.** Expansion stays off by default and stays available
  (`CIE_PACKET_EXPAND_DOCUMENTS`, or `expand_documents` per call).
- **A fails 3 or 4.** Expansion stays off by default. The loss is reported.
- **B fails any criterion.** The default goes back to off.

Every result is reported, including failures.

## Outcome of test A (added after the run)

**Every criterion was met** on the 5,000-document memory bank:
- everything reached the model: 71.6% against 66.3% on the even half (+5.3 points);
- facts in the model view: 487 against 464; search missed the document: 9 against 9;
- recall@10 0.872 against 0.878, and MRR 0.756 against 0.761;
- p50 401 ms against 419 ms, and p95 861 ms against 879 ms.

Document expansion is now on by default (3 documents × 5 passages). Test B (50,000 documents, Colab) confirms or
reverts it.

Two measures with no threshold got worse: facts in the extractive answer, and false abstentions. The extractive
answer read expansion's passages as leading items. It now reads the packet without them. This fix was made after the
test and was re-measured separately. Details are in `docs/EXPANSION_RESULTS.md`.
