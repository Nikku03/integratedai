# Quoting evidence-only answers: results

Pre-registration: `docs/QUOTES_PREREGISTRATION.md` (committed in 14ef032 before the test run).

## In short

Without a model, the answer is now built from quotes: the sentences of the leading evidence that best match the
question, each with a citation. On the test half of the 5,000-document memory bank, these answers held **2.7 times
as many of the gold answer facts** as the old answers (233 against 85), at a shorter length. Every pre-registered
criterion was met, so quotes are the default (`extractive_answer = "quotes"`).

## Test run: even question numbers, 190 judged questions (local, BM25 with document expansion)

| | cards (before) | quotes |
|---|---|---|
| gold answer facts in the answer (of 652) | 85 (13%) | **233 (36%)** |
| questions with every fact in the answer | 18 | **65** |
| mean answer length | 1,141 characters | 1,050 characters |
| longest answer | 1,788 characters | 1,087 characters |
| declined / conflict | 0 / 1 | 0 / 1 |

| Criterion | Result | Met |
|---|---|---|
| 1. facts in the answer at least 1.5 times | 233 vs 85 (2.74 times) | yes |
| 2. questions with every fact at least 1.5 times | 65 vs 18 | yes |
| 3. mean length not longer; no answer over 1,100 characters | 1,050 vs 1,141; longest 1,087 | yes |
| 4. declines and conflicts within 1 | identical | yes |

**Decision (as fixed in advance):** the default evidence-only answer is `quotes`. `CIE_EXTRACTIVE_ANSWER=cards` gives
the old one.

The fact check is lexical (the evidence audit's), not a judge. It finds a fact when its numbers and 70% of its
content words appear in the answer.

## A fix after the test run

The full test suite, run after the test, failed one acceptance test: "What was the Northwind monthly fee as of March
1, 2025?" The quote answer quoted both the old fee and the later amendment's.

Raw passages carry no validity dates; only memory records do. Two changes followed:
- A question that names a date ("as of"), or asks for an earlier version (previous, superseded, original, history and
  similar words), keeps the card answer, which reads the records valid at that time.
- A superseded record is never quoted.

The question classifier's own history flag was not used here: it also fires on "was" and "before", which 157 of the
470 benchmark questions contain. 14 benchmark questions match the narrower words.

**Re-measured after the fix (not pre-registered):**

| | cards | quotes, test run | quotes, after the fix |
|---|---|---|---|
| facts in the answer, even half | 85 | 233 | **227** |
| questions with every fact, even half | 18 | 65 | **64** |
| mean length, even half | 1,141 | 1,050 | 1,048 |
| longest answer, even half | 1,788 | 1,087 | 1,497 |
| facts in the answer, odd half (development) | 79 | 171 | 169 |

The longest answers after the fix are card answers to the questions that now keep the card answer. They are no
longer than before.

## By question type (even half, after the fix)

| type | judged | facts: cards | facts: quotes | of |
|---|---|---|---|---|
| basic | 69 | 38 | **108** | 169 |
| semantic | 45 | 13 | 30 | 122 |
| intra_document_reasoning | 20 | 7 | 22 | 40 |
| constrained | 15 | 7 | 27 | 69 |
| project_related | 20 | 9 | 11 | 117 |
| completeness | 9 | 11 | 15 | 102 |
| conflicting_info | 5 | 0 | 7 | 18 |
| miscellaneous | 7 | 0 | 7 | 15 |

Quotes help most where one passage holds the answer. Project and completeness questions barely move: their answers
are spread over many documents, and 1,100 characters cannot quote them all. A model reading the evidence is the
right tool there.

## What this does not show

- **Answer correctness as a judge sees it.** Quotes are not composed sentences; the benchmark's judge may still mark
  a quote that holds every fact as "not an answer". Part 1c of the notebook grades them on Colab.
- **Answers composed by a model.** This changes only the answer given without a model. With Llama or Claude, the
  model writes the answer from the evidence, as before.

## Files

`docs/benchmarks/quotes/`: the audits of both halves with each style, and after the fix.
