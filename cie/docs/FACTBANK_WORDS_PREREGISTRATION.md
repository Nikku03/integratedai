# Understanding new words without a language model: what decides, fixed before the method was built

I wrote this on 2026-10-07. I wrote it after the test set and its wordings were frozen and before any of the word learning
was written. The results go in `docs/FACTBANK_WORDS_RESULTS.md`.

## The problem

The revised planner (v4, `docs/FACTBANK_MULTI_RESULTS.md`) answers 0.927 of its training questions, but 0.596 of
questions on new documents with new wordings. Its misses come from words it never saw. It read "own" as authorship, and
"nearest deadline" as a count.

## What is tested

Whether the fact bank can learn what new words mean from **the company's own documents alone**.

**What may be used:**
- counts over the text of the benchmark's documents: Slack threads, emails, Linear and Jira descriptions, pull requests,
  meeting notes;
- the documents' own fields, for example a sentence that names a Linear issue's assignee next to a word.

**What may not be used:**
- no language model, neural network or pretrained word vectors;
- no dictionary or synonym list written by hand;
- no document of any test set.

The plan weights are learned from the same 48 training questions as v4. The new arm is **v5**: v4 plus the learned word
meanings.

## Data (frozen)

**The set.** A new sample of the whole benchmark: 20,000 documents, stratified by source, seed 17. Only the sources whose
documents link are kept (2,320 documents). None of them is among:
- the 5,089 documents of the earlier haystack;
- the documents of the retest.

The test set is built from this sample with `python -m cie.eval.factbank_multi fresh --seed 17 --wordings words`.

| | documents | questions | link | combine | compare | sha256 of questions.jsonl |
|---|---|---|---|---|---|---|
| new-words set | 50 | 50 | 19 | 23 | 8 | `326c638e5f9551e8…` |
| new-words set, changed information | 50 | 50 | 19 | 23 | 8 | `7b57856bb2b39a0f…` |

By kind:
- pull request → Linear issue: 7;
- Linear issue → pull request author: 5;
- ticket → linked ticket: 7;
- a person's issue count: 8;
- a person's first issue due: 7;
- an action item's owner → their issues: 8;
- which of two is due first: 8.

The changed copy renames 119 people and moves every ISO date 23 days later.

**Wordings.** A fourth pair per kind (`NEW_WORDS` in `cie/src/cie/eval/factbank_multi.py`), written as a manager might
ask in chat. For example:
- "How big is P's Linear queue, in issues?"
- "Which of P's Linear tickets is most urgent by date? Key only."
- "A vs B: which one has to ship first?"
- "Who's handling the ticket referenced from K?"

51% of their words (39 of 77) appear in no training question, against 38–39% for the two earlier test sets. Among them
are: responsible, handling, target, land, stage, far along, submitted, created, queue, tally, urgent, ship, calendar,
tasked, hold.

## Arms

| arm | |
|---|---|
| v1 | the fact bank's engine, untrained |
| v4 | the revised planner as tested in the retest |
| **v5** | v4 plus word meanings learned from the documents |

## Measure

Own answers, no model, as before:
- values and dates must match exactly;
- lists score F1;
- a count must be the right number.

The mean is the mean of the three groups (link, combine, compare).

## Rules

1. **New words are understood:** v5 − v4 ≥ +0.10, new-words set.
2. **Principles, not memorisation:** v5 on the new-words set ≥ v5 on its training questions − 0.15. v4 failed this rule
   in the retest.
3. **It holds when the information changes:** v5 on the changed copy ≥ v5 on the new-words set − 0.05.
4. **No harm where v4 already worked:** v5 ≥ v4 − 0.03 on the retest set, and on the training questions.

## How the method may be developed

**Allowed:**
- the training questions, including the check that holds out one training wording at a time (v4: 0.688);
- the retest set, which has already been seen.

**Not allowed:** looking at the new-words set before the run.
