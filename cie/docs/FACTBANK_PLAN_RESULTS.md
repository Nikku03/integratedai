# Fixing the planning step: results

**Run on 2026-10-09**, by the rules in `docs/FACTBANK_PLAN_PREREGISTRATION.md`. The design was frozen at commit `7017046`,
before the test set was drawn or its blind wordings were read.
- **Raw results, the model's forms, the writers' wordings, the development summary and the review:**
  `docs/benchmarks/factbank_plan/`.
- **Code:**
  - `cie/src/cie/factbank/plans.py` (`Planner(rules="v9")`, `check`, `reads`, `rests_on`, `AskedKind`);
  - `cie/src/cie/factbank/reader.py` (`Former`, v10's form);
  - `cie/src/cie/eval/factbank_multi.py` (`build_training_all`, `plan_test`).

## In short

**Fixing the planning step worked.** On 50 new questions over 50 new documents:

| arm | right answers |
|---|---|
| v4, the plan learner before | 0.510 |
| v8, the glossary, the best so far | 0.722 |
| **v9, the planner fixed (no model when a question is asked)** | **0.975** |

**Its right answers are right for the right reason.**
- Counting only answers whose plan read the facts they rest on, v9 scores 0.968 and v4 scores 0.385.
- On the "which is due first" questions, v9 compares the two due dates every time.

**Six of the seven pre-registered rules are met.**
- The one not met is that the small model's form adds 0.05 (v10 = v9 = 0.975).
- On this test the bank's own lessons were sure what kind of answer was asked for in 49 of 50 questions, so the model was
  asked once.

**But 0.975 is partly the luck of the wording draw.** The review found this, and I checked it after the run:
- Each question was asked in one of two blind wordings, drawn at random. The draw happened to favour v9.
- Asked the same 50 questions in a single writer's wording, v9 scores 0.922 (the formal writer), 0.975 (the terse
  writer) and 0.872 (the plain-words writer, the stand-in).
- In every wording v9 stays far ahead of v4 and v8.
- On the less familiar wordings, v10's form adds about 0.05 (0.975 and 0.924).
- A fair expectation for new wordings is about 0.92 for v9 and 0.96 for v10, not 0.975.

**What this means:** the plan picker was the bottleneck, and fixing it fixed most of the multi-document questions. The
small model helps where the wording is unusual, so it is worth keeping for that, but it is no longer the main lever.

## Decision

| Rule | Result |
|---|---|
| 1. The fixed planner helps (v9 − v4 ≥ +0.10) | **Met:** 0.975 against 0.510 (+0.465) |
| 2. It helps beyond the glossary (v9 − v8 ≥ +0.05) | **Met:** 0.975 against 0.722 (+0.253) |
| 3. Right for the right reason (v9 − v4 ≥ +0.10, and v9 ≥ its own right answers − 0.05) | **Met:** 0.968 against 0.385; 0.968 against 0.975 |
| 4. A small model's form adds (v10 − v9 ≥ +0.05) | **Not met:** 0.975 against 0.975 (0.000) |
| 5. Principles, not memorisation (test ≥ training − 0.15) | **Met:** v9 0.975 and v10 0.975 against 0.993 each |
| 6. It holds when the information changes (changed ≥ test − 0.05) | **Met:** v9 and v10 0.975 against 0.975 |
| 7. No harm on what was learned (≥ v4 − 0.03 on the first 48 training questions) | **Met:** v9 0.993 and v10 0.993 against 0.927 |

## Results

Own answers, no model judging (the mean is the mean of the three groups):

| | link | combine | compare | mean | right for the right reason |
|---|---|---|---|---|---|
| test set, v1 (untrained) | 0.105 | 0.000 | 0.000 | 0.035 | – |
| test set, v4 | 0.263 | 0.391 | 0.875 | 0.510 | 0.385 |
| test set, v8 (glossary) | 0.421 | 0.870 | 0.875 | 0.722 | 0.639 |
| test set, **v9** | 0.947 | 0.978 | 1.000 | **0.975** | **0.968** |
| test set, v9n (v9 without the glossary) | 0.947 | 0.978 | 1.000 | 0.975 | 0.968 |
| test set, **v10** (v9 + the 3B model's form) | 0.947 | 0.978 | 1.000 | **0.975** | 0.968 |
| changed copy, v4 / v8 / v9 / v10 | | | | 0.510 / 0.722 / 0.975 / 0.975 | |
| first 48 training questions, v4 / v9 / v10 | | | | 0.927 / 0.993 / 0.993 | 0.743 / 0.986 / 0.986 |
| 201 training questions, v4 / v9 / v10 | | | | 0.822 / 0.993 / 0.993 | 0.638 / 0.986 / 0.986 |

**By kind of question** (test set, share right):

| kind | n | v4 | v8 | v9 | v10 |
|---|---|---|---|---|---|
| pull request → Linear issue (assignee, due date, status) | 7 | 0.29 | 0.57 | **1.00** | **1.00** |
| Linear issue → pull request author | 5 | 0.00 | 0.20 | **1.00** | **1.00** |
| ticket → linked ticket | 7 | 0.43 | 0.43 | 0.86 | 0.86 |
| a person's issue count | 8 | 0.50 | 1.00 | 1.00 | 1.00 |
| a person's first issue due | 7 | 0.29 | 1.00 | 1.00 | 1.00 |
| an action item's owner → their issues | 8 | 0.38 | 0.63 | 0.94 | 0.94 |
| which of two is due first | 8 | 0.88 | 0.88 | 1.00 | 1.00 |

**The two misses:**
- **An action item.** It asked for the list of the owner's tickets. v9 answered with only the first one due, which
  scores 0.5 on the list.
- **A linked ticket's status** ("Ticket ENG-4823 is linked to another ticket. Could you please tell me where that other
  ticket currently stands?"). This was the one question where the bank's lessons were unsure of the kind of answer.
  - v9 answered with a ticket key.
  - v10 asked the model, which correctly said "status", but the bank then read the wrong ticket's status.
  - ENG-4823 is in the same cluster of linked tickets as earlier misses.

**The changed copy:**
- People are renamed and dates shifted, which changes 13 expected answers.
- Every arm scores exactly as on the original. That is expected: the plans read names and dates, they do not remember
  them.
- It shows nothing about changed statuses, links or counts.

### v10: the model's form

| | test set |
|---|---|
| questions where the bank's own lessons were unsure of the kind of answer, so the form was used | 1 of 50 |
| questions where the form's kind differs from the lessons' (when they were sure) | 0 |
| answers that differ from v9 | 1 (the linked-ticket status above; both wrong) |
| the model's time per question | median 1.9 s, at most 21 s (4 CPU cores, no GPU) |
| the bank's time per question | median 0.18 s |

### The same questions in other blind wordings (after the run; information only)

This was not part of the decision. The review raised it, and I ran it after the test: the same 50 questions and answers,
asked in one writer's wording only.

| wording | v4 | v8 | v9 | v9n | v10 | form used (lessons unsure) |
|---|---|---|---|---|---|---|
| as drawn (the test) | 0.510 | 0.722 | 0.975 | 0.975 | 0.975 | 1 |
| writer 1 only (a finance analyst, formal) | 0.527 | 0.652 | 0.922 | 0.887 | **0.975** | 9 |
| writer 2 only (a senior engineer, terse) | 0.481 | 0.742 | 0.975 | 0.975 | 0.975 | 0 |
| writer 3 only (a marketing coordinator, plain words; the stand-in) | 0.547 | 0.638 | 0.872 | 0.843 | **0.924** | 3 |

**What fails in plain words:**
- **"When is the ticket supposed to be done by?"** v9's lessons do not know this asks for a date, and it reads the status.
  The model's form says "date", and v10 gets all three right.
- **"Whoever got the X to-do in the Y meeting, can you list the ticket IDs?"** This never says "Linear". The bank reads
  "meeting" as the system asked about and answers from the meeting notes. It gets 4 of the 8 wrong, and so does v10.
  - The bank does not know that "ticket" means Linear or Jira.
  - No training or earlier question tested this.

### The earlier sets (seen in development; information only)

| set | v4 | v8 | v9n | v9 | v10 |
|---|---|---|---|---|---|
| first held-out | 0.653 | 0.549 | 0.882 | 0.980 | 0.980 |
| retest | 0.596 | 0.800 | 0.968 | 0.984 | 0.968 |
| new words | 0.611 | 0.669 | 0.802 | 0.877 | **0.947** |
| general-English blind | 0.727 | 0.898 | 0.977 | 0.958 | 0.977 |
| language-model test | 0.586 | 0.601 | 0.983 | 0.983 | 0.983 |
| **mean of the five** | 0.635 | 0.703 | 0.922 | 0.956 | **0.971** |

These are optimistic: their failures guided the design. Development step by step is in
`docs/benchmarks/factbank_plan/development.json` and in the pre-registration.

## What the review found

**Before the test:** an independent review found nine problems in the uncommitted code and protocol. All were fixed
before freezing; see the pre-registration.

**After the test:** three reviewers checked:
- the numbers;
- how hard the test was;
- the protocol.

A fourth reviewer tried to refute each finding (`review.json`).

1. **Every number and rule verdict reproduces, and the inputs match the freeze.**
   - The test set was drawn after the freeze commit and shares no document with any excluded set.
   - The frozen lessons, prompt and wordings are the ones used.
2. **The headline depends on the wording draw** (above). The rule verdicts do not: in every wording, v9 − v4 ≥ 0.31 and
   v9 − v8 ≥ 0.20.
3. **Rule 4 says little.**
   - With 49 of 50 questions sure, the form had no room to add on this draw.
   - On the other wordings it adds +0.053 and +0.052.
   - So "not met" means "this test could not show it", not "the form does not help".
4. **v9 = v9n = v10 is a product of the draw**, not of a fault. On the other wordings the glossary adds +0.035 and +0.029.
   So "no language model is needed" does not follow from this test.
5. **The test's words were new to training but not to development.** Almost every word in the test wordings appears in
   the earlier sets whose failures shaped v9. That is not a leak: v9 learns words only from training. But it makes this
   test less of a stretch than the new-words set.
6. **v4's low score (0.510) comes from these documents' mix of kinds,** not from hard wording. It should not be read as
   a sign that the test was hard.
7. **The right answers read the right things.**
   - Every v9 answer counted right reads the right entity.
   - The linked-ticket answers rely on the 50-document bank: the plan follows "dependencies" and does not single out
     "the other ticket". In a larger bank the same plan could reach several tickets.
8. **Smaller points:**
   - The three-group mean makes v9 − v4 smaller than a per-question mean would (+0.465 against +0.55).
   - The scratch files the run used are not all in the repository. The questions, forms, lessons, wordings and reports
     are.

## What this shows

- **The plan picker was the bottleneck, and it is fixed** for the kinds of question the bank was taught. That took
  three things:
  - teaching every kind;
  - learning only from plans right for the right reason;
  - checking each plan against what the question names and asks for.
- **No language model is needed for this when the wording is ordinary.** v9n, with no model anywhere, matches v9 on the
  test.
- **A small model helps where the wording is unusual.** "Supposed to be done by" and "what lands soonest" are examples.
  Used only where the bank is unsure:
  - it never scored below v9 on the test or its other wordings;
  - it added about 0.05 on the less familiar ones;
  - on one earlier set it lost a question (the retest: 0.984 against 0.968).

**What is not solved:**
- **"Ticket" without a system name.** In plain words, "ticket" with no system named sends action-item questions to the
  meeting notes.
- **Picking out "the other ticket"** in a bank where a ticket links to several.
- **Kinds of question never taught.** The bank answers only the seven kinds it was taught.

**Next** (each needs its own pre-registered test):
- teach the bank that "ticket" means a Linear or Jira item when no system is named;
- test on a larger bank (500 documents or more), so links reach several things;
- test new kinds of question, to see whether the planner's principles carry over to questions it was never taught.

## Reproduce

```bash
python -m cie.eval.factbank_multi trainall --work $TRAIN --out $TRAIN9          # the 201 training questions
python -m cie.eval.factbank_multi train --work $TRAIN9 --single lessons.json --plans plan_lessons_v9.json --rules v9 --proper --glossary glossary.json
python -m cie.eval.factbank_multi train --work $TRAIN9 --single lessons.json --plans plan_lessons_v9n.json --rules v9 --proper
bash docs/benchmarks/factbank_plan/run_test.sh   # draws the test set, answers with every arm, scores the rules
# v10 needs Ollama serving llama3.2:3b for new forms; the forms in docs/benchmarks/factbank_plan/forms/ replay without it
```
