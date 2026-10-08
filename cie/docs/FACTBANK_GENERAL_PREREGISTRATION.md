# New words from general English, without a language model: what decides, fixed before the method was built

I wrote this on 2026-10-08. I wrote it after the test set was frozen and before the general-English word counts were
built. The results go in `docs/FACTBANK_GENERAL_RESULTS.md`.

## Why

Word meanings counted from the company's own documents did not help (`docs/FACTBANK_WORDS_RESULTS.md`): 0.576 against
0.611 without them. That technical text places words by topic ("created" next to "ticket"). The plain English words in
people's questions found no close known word.

This test adds **general English**. The same counts are made over a large body of ordinary English text, where words like
"responsible", "urgent" or "plate" are common.

## What may be used

**Counts over two public bodies of English text**, fixed now:
- **WikiText-103**: the training split, about 100 million words of Wikipedia articles (Salesforce/wikitext,
  wikitext-103-raw-v1, CC BY-SA);
- **C4** (English): the first two training files, `c4-train.00000` and `c4-train.00001` of 1,024, about 350 million
  words of ordinary web pages (allenai/c4, ODC-BY). They are streamed and never stored.

The method is the same as the company word space:
- positive pointwise mutual information over the words found within 2 places of each other;
- reduced to 200 dimensions;
- 80,000 words kept (each seen at least 10 times).

**Not used:** no language model, neural network or pretrained word vectors, no hand-written dictionary or synonym list,
and no document of any test set.

## Data (frozen)

**The set.** A new sample of the whole benchmark: 20,000 documents, stratified by source, seed 29. Only linking sources
are kept (2,318 documents). None of them is among the documents of any earlier set: the 5,000-document haystack, the
retest set or the new-words set (5,189 documents excluded).

| | documents | questions | link | combine | compare | sha256 of questions.jsonl |
|---|---|---|---|---|---|---|
| general-English test set | 50 | 50 | 18 | 24 | 8 | `b966b488089fb68b…` |
| the same, changed information | 50 | 50 | 18 | 24 | 8 | `61a3d38bf9379ba9…` |

By kind:
- pull request → Linear issue: 8;
- Linear issue → pull request author: 4;
- ticket → linked ticket: 6;
- a person's issue count: 8;
- a person's first issue due: 7;
- an action item's owner → their issues: 9;
- which of two is due first: 8.

The changed copy renames 104 people and moves every ISO date 23 days later.

**Wordings, written blind** (`BLIND` in `cie/src/cie/eval/factbank_multi.py`).
- Three independent writers wrote them. They worked as three separate agent sessions, each with a different role: an
  engineering manager on Slack, an operations manager writing email, and a support lead on a phone.
- Each was told only what each question must ask. None saw the method, the code or the training questions.
- Their full output is in `docs/benchmarks/factbank_general/writers.json`.
- **The selection rule was fixed before they wrote.** Writers 1 and 2 give the pair. Writer 3 stands in for a wording
  that does not use each placeholder exactly once, or runs over 200 characters. One wording was replaced this way:
  writer 1's "who owns the ticket that's linked to {k}? not {k} itself, the other one" uses {k} twice.
- Examples: "who's got the linear ticket that PR #{n} is tied to?", "how many linear tickets are on {p}'s plate?" and
  "quick one, {a} vs {b}, which is due first?".
- 51% of their words (50 of 98) appear in no training question. Many of them are politeness ("thanks", "could you").

## Arms

| arm | |
|---|---|
| v1 | the fact bank's engine, untrained |
| v4 | the plan learner with no word meanings |
| v5 | with word meanings from the company's documents, exactly as tested (`plan_lessons_v5.json`) |
| **v6** | with word meanings from the company's documents and from general English |

All plan weights are learned from the same 48 training questions.

## Measure

Own answers, no model, as before:
- values and dates must match exactly;
- lists score F1;
- a count must be the right number.

The mean is the mean of the three groups.

## Rules

1. **New words are understood:** v6 − v4 ≥ +0.10, general-English test set.
2. **General English adds to the company's words:** v6 − v5 ≥ +0.05, general-English test set.
3. **Principles, not memorisation:** v6 on the test set ≥ v6 on its training questions − 0.15.
4. **It holds when the information changes:** v6 on the changed copy ≥ v6 on the test set − 0.05.
5. **No harm where v4 already worked:** v6 ≥ v4 − 0.03 on the retest set, and on the training questions.

## How the method may be developed

**Allowed:**
- the training questions, including the check that holds out one training wording at a time;
- the retest set and the new-words set, both already seen.

**Not allowed:** looking at the general-English test set before the run.

The only choices left to development, made from this list and recorded before the run:
- **How the two word spaces combine:** general English only, the higher of the two similarities, or their mean.
- **How close a known word must be to lend its meaning:** 0.4, 0.5 or 0.6.

**How the choice is made** (added before any development result was seen):
- Among the 9 allowed choices, take the one with the highest mean of three development scores: one training wording held
  out at a time, the retest set, and the new-words set.
- Ties go to the higher closeness, then to "general English only" before "the higher" before "the mean".
- A choice that lowers the training score by more than 0.03 is not allowed.

## Frozen before the run (added after development, before the test set was asked)

**The general-English word space.**
- WikiText-103 train (3.9 million sentences) and C4 files 00000–00001 (14.4 million sentences): 18.4 million sentences,
  321 million words.
- 80,000 words kept, window 2, 200 dimensions.
- `general_w2.npz`, sha256 `79f89eb788e3b631…`, built in 673 s.

**Development results** for every allowed choice. The training score is 0.927 for all of them.

| how the spaces combine | closeness | one training wording held out | retest set | new-words set | mean |
|---|---|---|---|---|---|
| company only (v5) | 0.5 | 0.752 | 0.631 | 0.576 | 0.653 |
| general only | 0.4 | 0.752 | 0.590 | 0.613 | 0.652 |
| general only | 0.5 | 0.752 | 0.590 | 0.611 | 0.651 |
| general only | 0.6 | 0.752 | 0.590 | 0.611 | 0.651 |
| the higher | 0.4 | 0.752 | 0.622 | 0.620 | 0.665 |
| the higher | 0.5 | 0.752 | 0.622 | 0.576 | 0.650 |
| the higher | 0.6 | 0.752 | 0.606 | 0.576 | 0.645 |
| **the mean** | **0.4** | 0.752 | **0.657** | 0.611 | **0.673** |
| the mean | 0.5 | 0.752 | 0.622 | 0.611 | 0.662 |
| the mean | 0.6 | 0.752 | 0.622 | 0.611 | 0.662 |

For comparison, v4 scores 0.752, 0.596 and 0.611.

**The choice, by the rule above:** the mean of the two spaces, with closeness 0.4.
- The plan weights are the same as v5's: every training word is known, so nothing is borrowed while learning.
- `plan_lessons_v6.json`, sha256 `20916dba7f1e4268…`.

**Expectation, written before the run.**
- The gains over v4 in development are small: +0.06 on the retest set, none on the new-words set, none on the held-out
  training wordings.
- So rule 1 (+0.10) and rule 2 (+0.05 over v5) may well not be met.

(The development run was cut by a container restart after the first four rows. The other six were rerun with the same
code; the four finished rows were kept.)
