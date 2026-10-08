# Questions that need several documents: results

**Run on 2026-10-07.** Both tests were scored by rules written before they ran:
- the first test: `docs/FACTBANK_MULTI_PREREGISTRATION.md`;
- the retest of the revised planner, on new documents and new wordings: `docs/FACTBANK_MULTI_RETEST_PREREGISTRATION.md`.

Raw results and the learned plan weights are in `docs/benchmarks/factbank_multi/`. The code is
`cie/src/cie/factbank/plans.py` and `cie/src/cie/eval/factbank_multi.py`. No language model was used anywhere.

## In short

- **The pieces are always reachable.** For every question in every set, one of the plans the fact bank enumerates gives
  the right answer: 48 of 48 training questions, 50 of 50 in the first held-out set and 50 of 50 in the retest.
- **The pieces reach the evidence.** Within 24,000 characters, the fact bank's evidence holds 0.99 of a question's
  pieces on average, and every piece for 0.98 of the questions. The present memory bank's evidence holds 0.32 of the
  pieces, and every piece for 0.13 of the questions. (Corrected after review: this first read "every piece for 0.99 of
  the questions". The figures are the average share.)
- **The first version could not choose the plan:** 0.083 of its own answers were right on held-out questions. It had
  learned to copy something already written in the question.
- **The revised version (v4), on 50 new documents with new wordings, gets 0.596 right.** The first version gets 0.250
  on the same set, and the untrained engine 0.111. The result is the same when every name and date changes. Three of
  the four rules are met.
- **Not met:** v4 is much better on its training questions (0.927) than on new ones (0.596). The misses on new questions
  come from words it never saw. For example, it reads "own" as authorship and "nearest deadline" as a count.

## The first test

### Decision

| Rule | Result |
|---|---|
| 1. Learned plans answer multi-document questions (v3 − v1 ≥ +0.20, held-out) | **Not met:** 0.083 against 0.013 (+0.070) |
| 2. Principles, not memorisation (held-out ≥ training − 0.15) | **Not met:** 0.083 against 0.309 (−0.226) |
| 3. It holds when the information changes (changed ≥ held-out − 0.05) | **Met:** 0.083 against 0.083 (0.000). First reported as not met because of a scoring bug (see Corrections) |
| 4. It brings the fragments together (v3 − memory bank ≥ +0.10, all pieces within 24,000 characters) | **Met:** 0.990 against 0.315 (+0.675) |

### Results

Own answers, no model (the mean is the mean of the three groups):

| | link | combine | compare | mean |
|---|---|---|---|---|
| held-out, v1 (untrained) | 0.000 | 0.040 | 0.000 | 0.013 |
| held-out, v2 (single-document lessons) | 0.176 | 0.080 | 0.000 | 0.085 |
| held-out, **v3** (learned plans) | 0.000 | 0.000 | 0.250 | 0.083 |
| training questions, v3 | 0.176 | 0.000 | 0.750 | 0.309 |
| changed information, v3 | 0.000 | 0.000 | 0.250 | 0.083 |

Share of a question's pieces in the evidence, averaged over questions (held-out set). The pre-registered rule 4 uses
this measure. In the first version of this document the heading said "all of a question's pieces", which was wrong:

| | within 2,000 characters | within 24,000 characters |
|---|---|---|
| fact bank v3 | 0.621 | 0.990 |
| fact bank v1 | 0.607 | 0.996 |
| plain keyword + vector search | 0.584 | 0.846 |
| plain keyword search | 0.250 | 0.811 |
| present memory bank | 0.078 | 0.315 |

### Why it failed

I looked at the training questions first, then described the held-out set the same way.

1. **The right plan was always there.**
   - Training: 48 of 48 questions had a plan that gives the right answer.
   - Held-out: 50 of 50.
   - What failed was the choice.
2. **It learned to copy from the question.**
   - The winning plan's answer was already written in the question for 42 of the 48 training questions and 46 of the 50
     held-out ones. Examples: the person's own name for "how many issues does P have?", or the ticket's own key for
     "who has the ticket that K links to?".
   - The cause is the compare questions ("A or B: which is due first?"). There the answer is always one of the two keys
     in the question, so the one weight for "the answer is in the question" came out positive (+2.34).
   - The single-document lessons had learned the opposite, and rightly: a value the question contains is a clue, not
     the answer.
3. **Fixed patterns misread the question.** "Which is due first? Give the key" was read as a question asking for a
   date, because of the word "due". The weight for "the kind of answer fits" came out negative.
4. **Plans walked out and straight back.** For example: ticket → its assignee → that person's tickets → their assignee.
   This ends at the start's own assignee.
5. **"One value" read the first of many.** A plan that reached ten issues and read one value gave the first issue's
   value.

## The revision (v4)

The changes, each written as a rule that holds for any question:
- The clue rule is split by whether the question offers a choice.
- The kind of answer is learned from the question's words: how much more often "how many" comes with a count than counts
  come in general.
- No plan walks back the way it came:
  - every hop must reach something new;
  - no relation is followed by its inverse;
  - no field pointing back is read;
  - no plan answers with only what it started from or passed through.
- "One value" needs every entity reached to agree.
- One more weight: the answer comes from the system the question names.

The first version is kept (`rules="v3"`). It reproduces the first test's weights and all 148 of its answers exactly (training, held-out and changed).

**Checks on the training set only, before the retest:**
- 0.917 of training questions right, against 0.309 for v3. The two are different measures: 0.917 is the share of
  questions, 0.309 the mean of the three groups. As group means, the figures are 0.927 against 0.309.
- 0.688 when each training wording is held out in turn.

## The retest: new documents, new wordings

**The set.** 50 documents and 50 questions, drawn from a new sample of the whole 511,958-document benchmark.
- It shares no document with any set used before.
- The wordings are new.
- Link: 21 questions, combine: 21, compare: 8.

### Decision

| Rule | Result |
|---|---|
| 1. Learned plans answer multi-document questions (v4 − v1 ≥ +0.20) | **Met:** 0.596 against 0.111 (+0.485) |
| 2. The revision helps on new data (v4 − v3 ≥ +0.20) | **Met:** 0.596 against 0.250 (+0.346) |
| 3. Principles, not memorisation (new set ≥ training − 0.15) | **Not met:** 0.596 against 0.927 (−0.331) |
| 4. It holds when the information changes (changed ≥ new set − 0.05) | **Met:** 0.596 against 0.596 (0.000). The scoring code as first run read 0.000 as a miss (see Corrections) |

### Results

Own answers, no model:

| | link | combine | compare | mean |
|---|---|---|---|---|
| new set, v1 (untrained) | 0.333 | 0.000 | 0.000 | 0.111 |
| new set, v2 (single-document lessons) | 0.000 | 0.000 | 0.000 | 0.000 |
| new set, v3 (first version) | 0.000 | 0.000 | 0.750 | 0.250 |
| new set, **v4** | 0.524 | 0.514 | 0.750 | **0.596** |
| training questions, v4 | 0.824 | 0.957 | 1.000 | 0.927 |
| new set with changed information, v4 | 0.524 | 0.514 | 0.750 | 0.596 |

By kind, v4 on the new set:

| kind | questions | right |
|---|---|---|
| ticket → linked ticket | 9 | 0.667 |
| pull request → Linear issue | 8 | 0.375 |
| Linear issue → pull request author | 4 | 0.500 |
| an action item's owner → their issues (F1) | 9 | 0.644 |
| a person's issue count | 6 | 0.333 |
| a person's first issue due | 6 | 0.500 |
| which of two is due first | 8 | 0.750 |

**The evidence.** v4's evidence starts with the plan and every entity each hop reached.
- Within its first 2,000 characters it holds 0.899 of a question's pieces on average, against 0.699 for v3 and 0.775
  for v1.
- It holds every piece for 0.863 of the questions, against 0.552 for v3 and 0.603 for v1.

(Corrected after review: this first said "all of a question's pieces … for 0.899 of the questions".)

### What still goes wrong

This describes the misses. Nothing was tuned on it.
- **The right plan was always there:** for all 50 questions. It was ranked first for 27 and within the top three for 41.
- **Words never seen in training:**
  - "How many Linear issues does P currently own?" chose the issues linked from P's pull requests ("own" read as
    authorship).
  - "Which one has the nearest deadline?" chose a count.
  - "Whose PR is it?" chose the pull request's number instead of its author.
  - "What deadline does the Linear issue… have?" ranked the due date below other fields.
- **The wrong start:** twice for compare questions and twice for action items, a document found by content was preferred
  to the one the question names.

These are the limits the pre-registration expected from a method without a language model. A new word can be
understood only through field names or words it learned in training.

## Corrections and limits

**Found by a review after the general-English test** (`docs/FACTBANK_GENERAL_RESULTS.md` has the full list). None of
them changes a decision here:
- **The changed copies renamed statuses.** Two-word statuses such as "In Progress" were renamed as if they were
  people.
  - With fixed copies, v3 on the changed set is still 0.083 (rule 3 met) and v4 on the retest's changed set is still
    0.596.
- **A customer attendee is matched to the same-named engineer's tickets.** Action items are joined to Linear
  assignees by name alone. In 5 of the 8 training questions and 3 of the 9 retest questions of that kind, the owner is a
  customer attendee and inherits the issues of a Redwood engineer with the same name.
  - Without those questions, v4 scores 0.941 on training (was 0.927) and 0.588 on the retest (was 0.596).
- **One document carries many questions.** Reused ticket keys put several questions on one document. All 8
  pull-request questions of the first held-out set reach the same ENG-4821 document. So the sets hold fewer
  independent questions than they count.

- **A scoring bug, found after both runs.**
  - The rule checks were written as `(difference or -1) >= threshold`, which reads a difference of exactly 0 as missing.
  - It turned two rules that the written rules meet into "not met": the first test's rule 3 (0.083 against 0.083) and
    the retest's rule 4 (0.596 against 0.596).
  - It is fixed (`at_least` in `factbank_multi.py`). Every number is unchanged.
  - The first report, as first produced, is kept: `docs/benchmarks/factbank_multi/multi_report_as_first_run.md`.
  - The single-document learning test had the same line. Its difference was −0.017, so its decision is unaffected.
- **v4 was designed after the first held-out results were seen.**
  - Its fixes were developed on the training questions only.
  - The retest uses new documents and new wordings for this reason.
  - The retest wordings were written after v4's training checks were seen.
- **A first draw of the retest set was discarded** before any answer was computed. It had no pull request questions,
  because the 5,000-document haystack had none left unused.
- **Overlap in the first test.** The first held-out set shares 4 documents with the documents the single-document lessons
  were learned from. Those lessons hold no values. The retest shares no document with any earlier set.
- **Small numbers per kind.** There are 4–9 questions per kind, so one question moves a kind's score by 0.11–0.25.
- **Template questions.** Real questions that need several documents are messier.
- **The memory bank was not rerun for the retest.** v4 changes only which plan is chosen.

## Reproduce

```bash
# the sets (the 5,000-document haystack's documents as JSON; the benchmark's index)
python -m cie.eval.factbank_multi build --docs hay5k_docs.json --index index.json --root <benchmark> --train $TRAIN --test $TEST
python -m cie.eval.factbank_split changed --work $TEST --out $CHANGED
python -m cie.eval.factbank_multi fresh --index index.json --root <benchmark> --exclude $HAY5K $FB50 $FBTEST $TRAIN $TEST --out $NEW
python -m cie.eval.factbank_split changed --work $NEW --out $NEWCHANGED
# per set: the fact bank (v1, v2), then the plans (v3, v4)
python -m cie.eval.factbank_test build --work $W --name factbank
python -m cie.eval.factbank_test ask --work $W --name factbank
python -m cie.eval.factbank_test build --work $W --name factbank_v2 --text-facts
python -m cie.eval.factbank_test ask --work $W --name factbank_v2 --lessons lessons.json
python -m cie.eval.factbank_multi train --work $TRAIN --single lessons.json --plans plan_lessons.json --rules v3
python -m cie.eval.factbank_multi train --work $TRAIN --single lessons.json --plans plan_lessons_v4.json --rules v4
python -m cie.eval.factbank_multi ask --work $W --single lessons.json --plans plan_lessons.json --name factbank_v3
python -m cie.eval.factbank_multi ask --work $W --single lessons.json --plans plan_lessons_v4.json --name factbank_v4
# the decisions
python -m cie.eval.factbank_multi compare --work $TEST --changed $CHANGED --train $TRAIN
python -m cie.eval.factbank_multi retest --work $NEW --changed $NEWCHANGED --train $TRAIN
```

The memory bank and plain-search arms of the first test come from the memory test (`python -m cie.eval.memory_test load`
and its evidence step, with `--reuse ""`).
